"""Entry point: `python -m ai_project_manager` (GUI) or `--list` (text mode)."""

from __future__ import annotations

import argparse
import time

from .models import human_size
from .scanners import scan_all


def list_mode() -> None:
    projects = scan_all()
    for p in projects:
        last = time.strftime("%Y-%m-%d", time.localtime(p.last_used)) if p.last_used else "-"
        print(
            f"[{p.source:6}] {p.status.value:17} {len(p.sessions):3} sessions "
            f"{human_size(p.total_size):>9}  last {last}  {p.display_path}"
        )
        if p.store_path is not None:
            print(f"         store: {p.store_path}")
    total = sum(p.total_size for p in projects)
    print(f"\n{len(projects)} projects, "
          f"{sum(len(p.sessions) for p in projects)} sessions, {human_size(total)} total")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-pm", description="Claude Code / Codex project & session manager")
    parser.add_argument("--list", action="store_true", help="print projects to stdout instead of launching the GUI")
    args = parser.parse_args()
    if args.list:
        list_mode()
    else:
        from .gui import run

        run()


if __name__ == "__main__":
    main()
