"""Scanners for Claude Code (~/.claude) and Codex (~/.codex) session stores."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Project, Session, Status

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CLAUDE_HISTORY = Path.home() / ".claude" / "history.jsonl"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
CODEX_HISTORY = Path.home() / ".codex" / "history.jsonl"
CODEX_SESSION_INDEX = Path.home() / ".codex" / "session_index.jsonl"

# How many leading lines of a Claude session file to scan for a "cwd" field
# (the first records are headers carrying only type/sessionId).
_CWD_SCAN_LINES = 25

# How many leading lines to scan for the first real user prompt (session title).
_TITLE_SCAN_LINES = 300
_TITLE_MAX_LEN = 100


def _clean_title(text: str) -> str:
    text = " ".join(text.split())
    if not text or text.startswith(("<", "/", "Caveat:", "[Request interrupted")):
        return ""
    return text[:_TITLE_MAX_LEN]


def _dir_size(path: Path) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        total += _dir_size(Path(entry.path))
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _encode_claude_path(real_path: str) -> str:
    """Encode a path the way Claude Code names project dirs (/ and . -> -)."""
    return real_path.replace("/", "-").replace(".", "-")


def _classify(real_path: str | None) -> Status:
    if not real_path:
        return Status.UNRESOLVED
    if Path(real_path).is_dir():
        return Status.OK
    if "/Library/CloudStorage/" in real_path:
        return Status.CLOUD_UNAVAILABLE
    return Status.MISSING


def _claude_cwd_from_session(jsonl: Path) -> str | None:
    """Read the first records of a Claude session file looking for a cwd field."""
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(_CWD_SCAN_LINES):
                line = f.readline()
                if not line:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = rec.get("cwd")
                if cwd:
                    return cwd
    except OSError:
        pass
    return None


def _title_from_record(rec: dict) -> str:
    """A session-name record, if this is one: custom-title (user rename),
    ai-title (auto-generated), or summary."""
    t = rec.get("type")
    if t == "custom-title":
        return " ".join(str(rec.get("customTitle", "")).split())[:_TITLE_MAX_LEN]
    if t == "ai-title":
        return " ".join(str(rec.get("aiTitle", "")).split())[:_TITLE_MAX_LEN]
    if t == "summary":
        return " ".join(str(rec.get("summary", "")).split())[:_TITLE_MAX_LEN]
    return ""


def _claude_title_from_session(jsonl: Path) -> str:
    """Session name from a Claude session file.

    Preference order: custom-title (user rename) > ai-title (auto-generated)
    > summary > first real user prompt. Name records usually sit in the header,
    but a rename can be appended later, so the tail is checked too.
    """
    custom = ai = summary = prompt = ""
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(_TITLE_SCAN_LINES):
                line = f.readline()
                if not line:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("type")
                if t == "custom-title":
                    custom = custom or _title_from_record(rec)
                elif t == "ai-title":
                    ai = ai or _title_from_record(rec)
                elif t == "summary":
                    summary = summary or _title_from_record(rec)
                elif (
                    not prompt
                    and t == "user"
                    and not rec.get("isMeta")
                    and not rec.get("isSidechain")
                ):
                    content = rec.get("message", {}).get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = " ".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict) and part.get("type") == "text"
                        )
                    else:
                        continue
                    prompt = _clean_title(text)
                if custom:
                    return custom
            if not (custom or ai):
                # A rename mid-session appends the record; check the file tail.
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536))
                for line in f.readlines()[1:]:
                    if '"custom-title"' not in line and '"ai-title"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") == "custom-title":
                        custom = _title_from_record(rec)
                    elif rec.get("type") == "ai-title":
                        ai = _title_from_record(rec)
    except OSError:
        pass
    return custom or ai or summary or prompt


def _claude_history_maps() -> tuple[dict[str, str], dict[str, str]]:
    """From ~/.claude/history.jsonl: (encoded dir name -> real path,
    sessionId -> first real prompt)."""
    paths: dict[str, str] = {}
    titles: dict[str, str] = {}
    try:
        with CLAUDE_HISTORY.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                proj = rec.get("project")
                if proj:
                    paths[_encode_claude_path(proj)] = proj
                sid = rec.get("sessionId")
                if sid and sid not in titles:
                    title = _clean_title(rec.get("display", ""))
                    if title:
                        titles[sid] = title
    except OSError:
        pass
    return paths, titles


def _codex_title_map() -> dict[str, str]:
    """Map session_id -> name: thread_name from ~/.codex/session_index.jsonl
    (set when the user names/renames a thread), falling back to the first
    prompt from ~/.codex/history.jsonl."""
    titles: dict[str, str] = {}
    try:
        with CODEX_HISTORY.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = rec.get("session_id")
                if sid and sid not in titles:
                    title = _clean_title(rec.get("text", ""))
                    if title:
                        titles[sid] = title
    except OSError:
        pass
    try:
        with CODEX_SESSION_INDEX.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = rec.get("id")
                name = " ".join(str(rec.get("thread_name") or "").split())
                if sid and name:
                    # The index is chronological; the last entry for an id wins.
                    titles[sid] = name[:_TITLE_MAX_LEN]
    except OSError:
        pass
    return titles


def scan_claude() -> list[Project]:
    projects: list[Project] = []
    if not CLAUDE_PROJECTS.is_dir():
        return projects
    history_map, title_map = _claude_history_maps()

    for proj_dir in sorted(p for p in CLAUDE_PROJECTS.iterdir() if p.is_dir()):
        sessions: list[Session] = []
        real_path: str | None = None
        session_dir_names: set[str] = set()

        jsonls = sorted(
            (f for f in proj_dir.glob("*.jsonl") if not f.name.startswith("agent-")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for jsonl in jsonls:
            sid = jsonl.stem
            extra: list[Path] = []
            sidecar = proj_dir / sid
            size = jsonl.stat().st_size
            if sidecar.is_dir():
                extra.append(sidecar)
                size += _dir_size(sidecar)
                session_dir_names.add(sid)
            if real_path is None:
                real_path = _claude_cwd_from_session(jsonl)
            sessions.append(
                Session(
                    session_id=sid,
                    source="claude",
                    file=jsonl,
                    extra_paths=extra,
                    last_used=jsonl.stat().st_mtime,
                    size_bytes=size,
                    title=_claude_title_from_session(jsonl) or title_map.get(sid, ""),
                )
            )

        if real_path is None:
            real_path = history_map.get(proj_dir.name)

        # Store contents not attributed to a session: memory/, legacy agent-*.jsonl,
        # and orphan sidecar dirs whose .jsonl is gone.
        extra_size = 0
        try:
            with os.scandir(proj_dir) as it:
                for entry in it:
                    name = entry.name
                    if name.endswith(".jsonl") and not name.startswith("agent-"):
                        continue
                    if entry.is_dir(follow_symlinks=False) and name in session_dir_names:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        extra_size += _dir_size(Path(entry.path))
                    else:
                        extra_size += entry.stat(follow_symlinks=False).st_size
        except OSError:
            pass

        projects.append(
            Project(
                source="claude",
                real_path=real_path,
                store_path=proj_dir,
                sessions=sessions,
                status=_classify(real_path),
                extra_size_bytes=extra_size,
            )
        )
    return projects


def _codex_session_meta(jsonl: Path) -> tuple[str | None, str | None]:
    """Return (cwd, session_id) from line 0 of a Codex rollout file."""
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as f:
            line = f.readline()
        rec = json.loads(line)
        payload = rec.get("payload", {})
        return payload.get("cwd"), payload.get("session_id") or payload.get("id")
    except (OSError, json.JSONDecodeError):
        return None, None


def scan_codex() -> list[Project]:
    if not CODEX_SESSIONS.is_dir():
        return []
    title_map = _codex_title_map()
    groups: dict[str | None, list[Session]] = {}
    for jsonl in sorted(CODEX_SESSIONS.rglob("rollout-*.jsonl")):
        cwd, sid = _codex_session_meta(jsonl)
        st = jsonl.stat()
        groups.setdefault(cwd, []).append(
            Session(
                session_id=sid or jsonl.stem,
                source="codex",
                file=jsonl,
                last_used=st.st_mtime,
                size_bytes=st.st_size,
                title=title_map.get(sid or "", ""),
            )
        )
    return [
        Project(
            source="codex",
            real_path=cwd,
            store_path=None,
            sessions=sessions,
            status=_classify(cwd),
        )
        for cwd, sessions in sorted(groups.items(), key=lambda kv: kv[0] or "~")
    ]


def prune_empty_codex_dirs() -> None:
    """Remove now-empty YYYY/MM/DD dirs under ~/.codex/sessions after deletions."""
    if not CODEX_SESSIONS.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(CODEX_SESSIONS, topdown=False):
        p = Path(dirpath)
        if p == CODEX_SESSIONS:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass


def scan_all() -> list[Project]:
    return scan_claude() + scan_codex()
