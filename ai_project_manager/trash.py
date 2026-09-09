"""Move files/folders to the OS trash/recycle bin using only the standard library."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

_FINDER_DELETE_SCRIPT = """\
on run argv
    set fileList to {}
    repeat with p in argv
        set end of fileList to (POSIX file (p as text))
    end repeat
    tell application "Finder" to delete fileList
end run
"""


def _finder_trash(paths: list[Path]) -> bool:
    """macOS: trash via Finder (AppleScript). Preserves 'Put Back'."""
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", _FINDER_DELETE_SCRIPT, *(str(p) for p in paths)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _windows_recycle(paths: list[Path]) -> bool:
    """Windows: send to the Recycle Bin via SHFileOperationW with FOF_ALLOWUNDO."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004
    FOF_NOERRORUI = 0x0400

    # pFrom is a double-null-terminated list of null-separated paths.
    src = "\0".join(str(p.resolve()) for p in paths) + "\0\0"
    op = SHFILEOPSTRUCTW(
        None,
        FO_DELETE,
        src,
        None,
        FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
        False,
        None,
        None,
    )
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except OSError:
        return False
    return result == 0 and not op.fAnyOperationsAborted


def _folder_trash(paths: list[Path], trash_dir: Path) -> list[Path]:
    """Move items into a trash folder directly. Returns paths that could not be moved."""
    failed: list[Path] = []
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return list(paths)
    for p in paths:
        dest = trash_dir / p.name
        if dest.exists():
            # De-duplicate the way Finder does: append a time suffix.
            stamp = time.strftime("%H.%M.%S")
            dest = trash_dir / f"{p.stem} {stamp}{p.suffix}"
            n = 1
            while dest.exists():
                dest = trash_dir / f"{p.stem} {stamp}-{n}{p.suffix}"
                n += 1
        try:
            shutil.move(str(p), str(dest))
        except OSError:
            failed.append(p)
    return failed


def move_to_trash(paths: list[Path]) -> list[Path]:
    """Move the given paths to the OS trash. Returns a list of paths that failed.

    macOS: Finder (real Trash, 'Put Back'), falling back to moving into ~/.Trash.
    Windows: Recycle Bin via the shell API; no folder fallback (a fake .Trash
    folder on Windows would be surprising), failures are reported instead.
    Other platforms: XDG trash directory, falling back to ~/.Trash.
    """
    existing = [p for p in paths if p.exists()]
    if not existing:
        return []

    if sys.platform == "darwin":
        if _finder_trash(existing):
            return [p for p in existing if p.exists()]
        return _folder_trash([p for p in existing if p.exists()], Path.home() / ".Trash")

    if sys.platform == "win32":
        _windows_recycle(existing)
        return [p for p in existing if p.exists()]

    return _folder_trash(existing, Path.home() / ".local" / "share" / "Trash" / "files")
