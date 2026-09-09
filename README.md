# AI Project Manager

A zero-dependency Tkinter GUI for macOS that lists your **Claude Code** (`~/.claude/projects`) and **Codex** (`~/.codex/sessions`) projects and sessions, shows whether each project's source folder still exists, and lets you clean up old data by moving it to the macOS Trash.

## Features

- Unified view of Claude Code and Codex projects with per-project session counts, sizes, and last-used dates
- Status per project: `✓ exists`, `✗ missing` (folder is gone), `☁ unavailable` (OneDrive/CloudStorage path not currently synced), `? unresolved`
- Filters: source (Claude/Codex), status, "older than N days", and path search — combine with **Select All (Filtered)** for bulk cleanup (e.g. filter to *Missing only* → select all → delete)
- Expand a project to delete individual sessions
- Deletions go to the **macOS Trash** via Finder (with "Put Back" support); falls back to moving into `~/.Trash` if Finder automation is denied
- Reveal a project or session file in Finder

## Correctness notes

- Claude project dir names encode paths lossily (`/` → `-`), so the real path is resolved by reading the `cwd` field inside session files, falling back to `~/.claude/history.jsonl` — never by decoding the dir name.
- Deleting a Claude session removes both `<uuid>.jsonl` and its sidecar `<uuid>/` directory (subagent transcripts, tool results).
- Deleting a whole Claude project also removes its `memory/` folder (Claude's saved project memory) — the confirm dialog warns when one is present.
- Codex has no per-project directories; sessions are grouped by their recorded `cwd`, and deleting a "project" deletes its session files (empty date directories are pruned afterwards).

## Usage

Requires a Python with Tk support. On macOS use Homebrew Python with `brew install python-tk@3.14` (Tk 9). Avoid Apple's `/usr/bin/python3` — its bundled Tk 8.5 draws a blank window on recent macOS in dark mode.

```sh
# GUI
python3 -m ai_project_manager

# Text listing (no GUI)
python3 -m ai_project_manager --list
```

Or install it: `pip install .` then run `ai-pm`.
