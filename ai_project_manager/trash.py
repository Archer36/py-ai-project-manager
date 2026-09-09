"""Move files/folders to the macOS Trash using only the standard library."""

from __future__ import annotations

import shutil
import subprocess
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
    """Trash via Finder (AppleScript). Preserves 'Put Back'. Returns True on success."""
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


def _fallback_trash(paths: list[Path]) -> list[Path]:
    """Move items into ~/.Trash directly. Returns paths that could not be moved."""
    trash_dir = Path.home() / ".Trash"
    failed: list[Path] = []
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
    """Move the given paths to the Trash. Returns a list of paths that failed."""
    existing = [p for p in paths if p.exists()]
    if not existing:
        return []
    if _finder_trash(existing):
        return [p for p in existing if p.exists()]
    return _fallback_trash([p for p in existing if p.exists()])
