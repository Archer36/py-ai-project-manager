"""Data models for projects and sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Status(Enum):
    OK = "exists"
    MISSING = "missing"
    CLOUD_UNAVAILABLE = "cloud/unavailable"
    UNRESOLVED = "unresolved"


@dataclass
class Session:
    session_id: str
    source: str  # "claude" | "codex"
    file: Path
    extra_paths: list[Path] = field(default_factory=list)  # e.g. Claude <uuid>/ sidecar dir
    last_used: float = 0.0  # epoch seconds
    size_bytes: int = 0

    @property
    def all_paths(self) -> list[Path]:
        return [self.file, *self.extra_paths]


@dataclass
class Project:
    source: str  # "claude" | "codex"
    real_path: str | None  # the project's working directory, if resolved
    store_path: Path | None  # Claude project dir; None for Codex synthetic groups
    sessions: list[Session] = field(default_factory=list)
    status: Status = Status.UNRESOLVED
    extra_size_bytes: int = 0  # store contents not attributed to a session (memory/, agent-*.jsonl)

    @property
    def total_size(self) -> int:
        return self.extra_size_bytes + sum(s.size_bytes for s in self.sessions)

    @property
    def last_used(self) -> float:
        return max((s.last_used for s in self.sessions), default=0.0)

    @property
    def display_path(self) -> str:
        if self.real_path:
            return self.real_path
        if self.store_path is not None:
            return self.store_path.name
        return "<unknown>"

    def delete_paths(self) -> list[Path]:
        """Paths to trash when deleting the whole project."""
        if self.store_path is not None:
            return [self.store_path]
        # Codex synthetic project: delete every session's files
        paths: list[Path] = []
        for s in self.sessions:
            paths.extend(s.all_paths)
        return paths


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
