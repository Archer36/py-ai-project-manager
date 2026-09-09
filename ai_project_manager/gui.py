"""Tkinter GUI for browsing and cleaning up Claude Code / Codex projects and sessions."""

from __future__ import annotations

import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .models import Project, Session, Status, human_size
from .scanners import prune_empty_codex_dirs, scan_all
from .trash import move_to_trash

STATUS_LABELS = {
    Status.OK: "✓ exists",
    Status.MISSING: "✗ missing",
    Status.CLOUD_UNAVAILABLE: "☁ unavailable",
    Status.UNRESOLVED: "? unresolved",
}

SOURCE_LABELS = {"claude": "Claude", "codex": "Codex"}


def _fmt_time(ts: float) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Project Manager")
        self.geometry("1050x650")

        self.projects: list[Project] = []
        # tree item id -> ("project", Project) | ("session", Project, Session)
        self.items: dict[str, tuple] = {}
        self._scan_queue: queue.Queue = queue.Queue()

        self._build_toolbar()
        self._build_tree()
        self._build_statusbar()

        # Workaround for macOS + old Tk (8.5/8.6): window can come up blank
        # until it is hidden/reshown once and nudged.
        if self.tk.call("tk", "windowingsystem") == "aqua":
            self.withdraw()
            self.after(0, self.deiconify)
            self.after(100, self._macos_repaint_nudge)

        self.refresh()

    def _macos_repaint_nudge(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        if w > 1 and h > 1:
            self.geometry(f"{w + 1}x{h}")
            self.after(50, lambda: self.geometry(f"{w}x{h}"))
        self.lift()

    # ------------------------------------------------------------------ UI

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="Source:").pack(side="left")
        self.source_var = tk.StringVar(value="All")
        src = ttk.Combobox(
            bar, textvariable=self.source_var, state="readonly", width=8,
            values=["All", "Claude", "Codex"],
        )
        src.pack(side="left", padx=(2, 10))

        ttk.Label(bar, text="Status:").pack(side="left")
        self.status_var = tk.StringVar(value="All")
        st = ttk.Combobox(
            bar, textvariable=self.status_var, state="readonly", width=14,
            values=["All", "Missing only", "Exists", "Unavailable", "Unresolved"],
        )
        st.pack(side="left", padx=(2, 10))

        ttk.Label(bar, text="Older than (days):").pack(side="left")
        self.age_var = tk.StringVar(value="0")
        age = ttk.Spinbox(bar, textvariable=self.age_var, from_=0, to=3650, width=5)
        age.pack(side="left", padx=(2, 10))

        ttk.Label(bar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.search_var, width=18)
        search.pack(side="left", padx=(2, 10))

        ttk.Button(bar, text="Delete Selected", command=self.delete_selected).pack(side="right", padx=2)
        ttk.Button(bar, text="Reveal in Finder", command=self.reveal_selected).pack(side="right", padx=2)
        ttk.Button(bar, text="Select All (Filtered)", command=self.select_all_filtered).pack(side="right", padx=2)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right", padx=2)

        for var in (self.source_var, self.status_var, self.age_var, self.search_var):
            var.trace_add("write", lambda *_: self.rebuild_tree())

    def _build_tree(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        cols = ("source", "status", "sessions", "size", "last_used")
        self.tree = ttk.Treeview(frame, columns=cols, selectmode="extended")
        self.tree.heading("#0", text="Project / Session")
        self.tree.heading("source", text="Source")
        self.tree.heading("status", text="Status")
        self.tree.heading("sessions", text="Sessions")
        self.tree.heading("size", text="Size")
        self.tree.heading("last_used", text="Last Used")
        self.tree.column("#0", width=470, stretch=True)
        self.tree.column("source", width=70, anchor="center", stretch=False)
        self.tree.column("status", width=110, anchor="center", stretch=False)
        self.tree.column("sessions", width=70, anchor="e", stretch=False)
        self.tree.column("size", width=80, anchor="e", stretch=False)
        self.tree.column("last_used", width=130, anchor="center", stretch=False)

        self.tree.tag_configure("missing", foreground="#c62828")
        self.tree.tag_configure("cloud", foreground="#e08b00")
        self.tree.tag_configure("unresolved", foreground="#757575")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _build_statusbar(self) -> None:
        self.statusbar = ttk.Label(self, text="", padding=(8, 4), anchor="w")
        self.statusbar.pack(fill="x")

    # ------------------------------------------------------------ scanning

    def refresh(self) -> None:
        self.statusbar.config(text="Scanning…")

        def worker() -> None:
            try:
                self._scan_queue.put(scan_all())
            except Exception as e:  # surface scan failures instead of hanging
                self._scan_queue.put(e)

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_scan)

    def _poll_scan(self) -> None:
        try:
            result = self._scan_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_scan)
            return
        if isinstance(result, Exception):
            messagebox.showerror("Scan failed", str(result))
            self.statusbar.config(text="Scan failed.")
            return
        self.projects = result
        self.rebuild_tree()

    # ----------------------------------------------------------- filtering

    def _filtered_projects(self) -> list[Project]:
        source = self.source_var.get()
        status = self.status_var.get()
        try:
            min_age_days = int(self.age_var.get() or 0)
        except ValueError:
            min_age_days = 0
        needle = self.search_var.get().strip().lower()
        cutoff = time.time() - min_age_days * 86400

        out = []
        for p in self.projects:
            if source != "All" and SOURCE_LABELS[p.source] != source:
                continue
            if status == "Missing only" and p.status is not Status.MISSING:
                continue
            if status == "Exists" and p.status is not Status.OK:
                continue
            if status == "Unavailable" and p.status is not Status.CLOUD_UNAVAILABLE:
                continue
            if status == "Unresolved" and p.status is not Status.UNRESOLVED:
                continue
            if min_age_days > 0 and p.last_used > cutoff:
                continue
            if needle and needle not in p.display_path.lower():
                continue
            out.append(p)
        return out

    def rebuild_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.items.clear()

        shown = self._filtered_projects()
        for proj in shown:
            tags = ()
            if proj.status is Status.MISSING:
                tags = ("missing",)
            elif proj.status is Status.CLOUD_UNAVAILABLE:
                tags = ("cloud",)
            elif proj.status is Status.UNRESOLVED:
                tags = ("unresolved",)
            pid = self.tree.insert(
                "", "end", text=proj.display_path, tags=tags,
                values=(
                    SOURCE_LABELS[proj.source],
                    STATUS_LABELS[proj.status],
                    len(proj.sessions),
                    human_size(proj.total_size),
                    _fmt_time(proj.last_used),
                ),
            )
            self.items[pid] = ("project", proj)
            for sess in sorted(proj.sessions, key=lambda s: s.last_used, reverse=True):
                sid = self.tree.insert(
                    pid, "end", text=sess.display_name,
                    values=(
                        SOURCE_LABELS[sess.source], "", "",
                        human_size(sess.size_bytes),
                        _fmt_time(sess.last_used),
                    ),
                )
                self.items[sid] = ("session", proj, sess)

        total = sum(p.total_size for p in shown)
        self.statusbar.config(
            text=f"{len(shown)} of {len(self.projects)} projects shown · "
                 f"{sum(len(p.sessions) for p in shown)} sessions · {human_size(total)}"
        )

    # ------------------------------------------------------------- actions

    def select_all_filtered(self) -> None:
        project_rows = self.tree.get_children("")
        self.tree.selection_set(project_rows)

    def reveal_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        kind, *rest = self.items[sel[0]]
        if kind == "project":
            proj: Project = rest[0]
            target = proj.real_path if proj.real_path and Status.OK is proj.status else proj.store_path
            if target is None and proj.sessions:
                target = proj.sessions[0].file
        else:
            target = rest[1].file
        if target:
            subprocess.run(["open", "-R", str(target)], check=False)

    def delete_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select projects or sessions to delete.")
            return

        # Collapse selection: if a project is selected, ignore its selected children.
        selected_projects: list[Project] = []
        selected_sessions: list[tuple[Project, Session]] = []
        project_set = set()
        for iid in sel:
            entry = self.items.get(iid)
            if entry and entry[0] == "project":
                selected_projects.append(entry[1])
                project_set.add(id(entry[1]))
        for iid in sel:
            entry = self.items.get(iid)
            if entry and entry[0] == "session" and id(entry[1]) not in project_set:
                selected_sessions.append((entry[1], entry[2]))

        paths = []
        total = 0
        memory_warning = False
        for proj in selected_projects:
            paths.extend(proj.delete_paths())
            total += proj.total_size
            if proj.store_path is not None and (proj.store_path / "memory").is_dir():
                memory_warning = True
        for _, sess in selected_sessions:
            paths.extend(sess.all_paths)
            total += sess.size_bytes

        if not paths:
            return

        lines = [f"Move to Trash: {len(selected_projects)} project(s), "
                 f"{len(selected_sessions)} session(s) — {human_size(total)}", ""]
        for proj in selected_projects[:8]:
            lines.append(f"• {SOURCE_LABELS[proj.source]} project: {proj.display_path}")
        if len(selected_projects) > 8:
            lines.append(f"• … and {len(selected_projects) - 8} more projects")
        for proj, sess in selected_sessions[:8]:
            lines.append(f"• session {sess.session_id[:13]}… ({proj.display_path})")
        if len(selected_sessions) > 8:
            lines.append(f"• … and {len(selected_sessions) - 8} more sessions")
        if memory_warning:
            lines += ["", "⚠ One or more Claude projects contain a memory/ folder "
                          "(Claude's saved project memory). It will be trashed too."]
        lines += ["", "Items go to the macOS Trash and can be restored."]

        if not messagebox.askyesno("Confirm delete", "\n".join(lines), icon="warning"):
            return

        failed = move_to_trash(paths)
        if any(p.source == "codex" for p in selected_projects) or any(
            s.source == "codex" for _, s in selected_sessions
        ):
            prune_empty_codex_dirs()

        if failed:
            messagebox.showerror(
                "Some items could not be trashed",
                "\n".join(str(p) for p in failed[:15]),
            )
        self.refresh()


def run() -> None:
    App().mainloop()
