"""Workspace and Results panels of the main window (3.5).

``WorkspacePanel`` lists the data files of a project folder with the
measurement each one most likely holds (:mod:`scripts.common.detect`); a
double-click hands the file to the matching analysis window.
``ResultsPanel`` lists the analyses already exported under that folder
(:mod:`scripts.common.results_index`) and collects their numbers in one
workbook. Both are plain views: the detection rules and the index live in
the two modules named above and run without a display.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence

import customtkinter as ctk

from scripts.common import detect, results_index
from scripts.common import palette as _pal
from scripts.common import theme as _theme

COMPARE_KINDS = ("eqe", "abs", "pl", "xrd", "raman", "ftir")     # techniques of the Compare window
ALL = "All measurements"
ALL_TOOLS = "All tools"
UNKNOWN = "Not recognised"
SCAN_SLICE_S = 0.04          # time spent classifying per event-loop turn


def open_with_system(path: str) -> None:
    """Open a file or folder with the program the operating system uses for it."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_in_folder(path: str) -> None:
    """Show a file in the file manager (selected where the platform allows it)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])


def _button(master, text, command, primary=False, width=110):
    return _theme.pill_button(master, text, command=command, primary=primary, width=width, height=26)


def _tree(master, columns, widths, height=8, selectmode="extended", stretch=None):
    """ttk.Treeview with a vertical scrollbar; returns (frame, tree)."""
    _theme.style_treeview(rowheight=22)
    frame = ctk.CTkFrame(master, fg_color="transparent", corner_radius=0)
    tree = ttk.Treeview(frame, columns=[c for c, _ in columns], show="headings", height=height,
                        selectmode=selectmode)
    for (key, title), width in zip(columns, widths):
        tree.heading(key, text=title, anchor="w")
        tree.column(key, width=width, minwidth=50, anchor="w", stretch=(key == stretch))
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, tree


# ---------------------------------------------------------------- workspace
class WorkspacePanel(ctk.CTkFrame):
    """Files of the project folder and what each one is.

    Callbacks
        on_open(detections, ask=False)   open the selected files in their tool
        on_compare(kind, paths)          overlay several files of one technique
        on_status(text)                  one-line message for the status bar
        on_scanned(folder, detections, entries)   a scan finished
    """

    COLUMNS = (("file", "File"), ("kind", "Measurement"), ("conf", "Confidence"), ("size", "Rows x cols"),
               ("cols", "Columns"), ("tool", "Opens in"))
    WIDTHS = (250, 170, 84, 84, 250, 130)

    def __init__(self, master, on_open: Callable, on_compare: Callable,
                 on_status: Optional[Callable[[str], None]] = None,
                 on_scanned: Optional[Callable] = None):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.on_open, self.on_compare = on_open, on_compare
        self.on_status = on_status or (lambda text: None)
        self.on_scanned = on_scanned
        self.folder = ""
        self.detections: List[detect.Detection] = []
        self.entries: List[results_index.Entry] = []
        self.scanning = False
        self._rows: Dict[str, detect.Detection] = {}
        self._token = 0
        self._sort = ("file", False)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
        ctk.CTkLabel(top, text="Folder", font=_pal.font(11), text_color=_pal.TXT_SUB).pack(side="left")
        self.folder_var = ctk.StringVar()
        self.ent_folder = _theme.entry(top, width=320, height=24, textvariable=self.folder_var)
        self.ent_folder.pack(side="left", fill="x", expand=True, padx=(8, 6))
        self.ent_folder.bind("<Return>", lambda e: self.set_folder(self.folder_var.get().strip()))
        _button(top, "Choose...", self.choose_folder, width=84).pack(side="left")
        _button(top, "Rescan", self.rescan, width=70).pack(side="left", padx=(6, 0))
        self.filter_var = ctk.StringVar(value=ALL)
        self.opt_filter = ctk.CTkOptionMenu(top, values=[ALL], variable=self.filter_var, width=190, height=24,
                                            font=_pal.font(11), command=lambda _v: self._fill())
        self.opt_filter.pack(side="left", padx=(10, 0))

        frame, self.tree = _tree(self, self.COLUMNS, self.WIDTHS, height=9, stretch="cols")
        frame.grid(row=1, column=0, sticky="nsew", padx=4)
        for key, _title in self.COLUMNS:
            self.tree.heading(key, command=lambda k=key: self.sort_by(k))
        self.tree.tag_configure("weak", foreground=_pal.TXT_DIM)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Button-2>", self._popup)
        self.tree.bind("<Control-Button-1>", self._popup)
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        self.lbl_info = ctk.CTkLabel(self, text="", font=_pal.font(11), text_color=_pal.TXT_SUB, anchor="w",
                                     justify="left", wraplength=820)
        self.lbl_info.grid(row=2, column=0, sticky="ew", padx=6, pady=(4, 2))
        self.bind("<Configure>", lambda e: self.lbl_info.configure(wraplength=max(300, e.width - 24)))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=4, pady=(2, 4))
        self.btn_open = _button(row, "Open selected", self.open_selected, primary=True, width=120)
        self.btn_open.pack(side="left")
        self.btn_with = _button(row, "Open with...", lambda: self.open_selected(ask=True), width=100)
        self.btn_with.pack(side="left", padx=(6, 0))
        self.btn_compare = _button(row, "Compare selected", self.compare_selected, width=130)
        self.btn_compare.pack(side="left", padx=(6, 0))
        _button(row, "Show in folder", self.reveal_selected, width=110).pack(side="left", padx=(6, 0))
        self.lbl_count = ctk.CTkLabel(row, text="", font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="e")
        self.lbl_count.pack(side="right", padx=4)

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Open", command=self.open_selected)
        self.menu.add_command(label="Open with...", command=lambda: self.open_selected(ask=True))
        self.menu.add_command(label="Compare selected", command=self.compare_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Show in folder", command=self.reveal_selected)
        self.menu.add_command(label="Copy path", command=self.copy_paths)
        self._hint()

    # ---- folder ----
    def _hint(self):
        self.lbl_info.configure(text=(
            "Choose the folder of a sample batch or project. Every data file below it (two folder levels) is listed "
            "with the measurement it most likely holds, judged from the file name, the column names and the numbers. "
            "A double-click opens the file in the matching tool; a low-confidence guess asks first."))

    def choose_folder(self):
        start = self.folder if os.path.isdir(self.folder) else os.path.expanduser("~")
        folder = filedialog.askdirectory(title="Workspace folder", initialdir=start)
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder: str, scan: bool = True):
        folder = os.path.abspath(os.path.expanduser(folder)) if folder else ""
        if folder and not os.path.isdir(folder):
            messagebox.showwarning("Workspace", f"This folder does not exist:\n{folder}", parent=self)
            self.folder_var.set(self.folder)
            return
        self.folder = folder
        self.folder_var.set(folder)
        self.after_idle(self._show_folder_end)
        if scan:
            self.rescan()

    def _show_folder_end(self):
        """A long path shows its end: the folder name says more than the drive."""
        try:
            self.ent_folder.xview_moveto(1.0)
        except (tk.TclError, AttributeError):
            pass

    def rescan(self):
        """Classify the files of the folder a few at a time on the Tk thread.

        No worker thread on purpose: Python may run a garbage collection in
        whichever thread allocates, and collecting the Tk fonts of a window that
        was just closed from another thread crashes Tk."""
        folder = self.folder
        self._token += 1
        if not folder:
            self.detections, self.entries, self.scanning = [], [], False
            self._fill()
            return
        job = {"token": self._token, "folder": folder, "items": None, "detections": [], "error": ""}
        self.scanning = True
        self.lbl_count.configure(text="Scanning ...")
        self.after(10, lambda: self._scan_step(job))

    def _scan_step(self, job):
        if job["token"] != self._token:
            return                                    # a newer scan replaced this one
        more = True
        try:
            if job["items"] is None:
                job["items"] = detect.iter_folder(job["folder"])
            end = time.monotonic() + SCAN_SLICE_S
            while time.monotonic() < end:
                i, n, d = next(job["items"])
                if d is not None:
                    job["detections"].append(d)
                self.lbl_count.configure(text=f"Scanning {i} / {n}")
        except StopIteration:
            more = False
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            job["error"] = f"{type(exc).__name__}: {exc}"
            more = False
        if more:
            self.after(1, lambda: self._scan_step(job))
            return
        try:
            entries = results_index.scan(job["folder"])
        except Exception as exc:  # noqa: BLE001
            entries = []
            job["error"] = job["error"] or f"{type(exc).__name__}: {exc}"
        self.scanning = False
        self.detections, self.entries = job["detections"], entries
        labels = [detect.KINDS[k][1] for k in detect.KINDS if any(d.kind == k for d in self.detections)]
        if any(not d.kind for d in self.detections):
            labels.append(UNKNOWN)
        self.opt_filter.configure(values=[ALL] + labels)
        if self.filter_var.get() not in labels:
            self.filter_var.set(ALL)
        self._fill()
        if job["error"]:
            self.lbl_info.configure(text=f"The folder could not be read completely: {job['error']}")
        n = len(self.detections)
        known = sum(1 for d in self.detections if d.kind)
        name = os.path.basename(job["folder"].rstrip(os.sep)) or job["folder"]
        self.on_status(f"Workspace {name}: {n} data file{'s' if n != 1 else ''}, {known} recognised, "
                       f"{len(entries)} exported analys{'es' if len(entries) != 1 else 'is'}")
        if self.on_scanned is not None:
            self.on_scanned(job["folder"], self.detections, self.entries)

    def refresh_results(self):
        """Read the side-cars again without classifying the data files again
        (an analysis window was closed and may have exported)."""
        if not self.folder or self.scanning:
            return
        try:
            self.entries = results_index.scan(self.folder)
        except Exception:  # noqa: BLE001
            return
        if self.on_scanned is not None:
            self.on_scanned(self.folder, self.detections, self.entries)

    # ---- list ----
    def _shown(self) -> List[detect.Detection]:
        want = self.filter_var.get()
        ds = [d for d in self.detections if want == ALL or d.label == want]
        key, reverse = self._sort
        order = {"high": 0, "medium": 1, "low": 2, "none": 3}
        keys = {"file": lambda d: self._rel(d.path).lower(),
                "kind": lambda d: (d.label == UNKNOWN, d.label.lower(), self._rel(d.path).lower()),
                "conf": lambda d: (order[d.confidence], self._rel(d.path).lower()),
                "size": lambda d: d.shape[0],
                "cols": lambda d: ", ".join(d.columns).lower(),
                "tool": lambda d: (not d.tool, d.tool.lower(), self._rel(d.path).lower())}
        return sorted(ds, key=keys[key], reverse=reverse)

    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.folder) if self.folder else path
        except ValueError:
            return path

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        shown = self._shown()
        for d in shown:
            size = f"{d.shape[0]} x {d.shape[1]}" if d.shape[0] else ""
            cols = d.error or ", ".join(d.columns[:6]) + (", ..." if len(d.columns) > 6 else "")
            conf = d.confidence if d.kind else "-"
            iid = self.tree.insert("", "end", values=(self._rel(d.path), d.label, conf, size, cols, d.tool or "-"),
                                   tags=("weak",) if d.confidence in ("low", "none") else ())
            self._rows[iid] = d
        n = len(self.detections)
        self.lbl_count.configure(text=(f"{len(shown)} of {n} files" if len(shown) != n else f"{n} files")
                                 if self.folder else "")
        if not self.folder:
            self._hint()
        elif not self.detections:
            self.lbl_info.configure(text="No data files in this folder (text tables, Excel workbooks, SEM images).")
        else:
            self.lbl_info.configure(text=detect.summary(self.detections) + ".")
        self._buttons()

    def sort_by(self, key: str):
        self._sort = (key, not self._sort[1] if self._sort[0] == key else False)
        self._fill()

    def selected(self) -> List[detect.Detection]:
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def select_paths(self, paths: Sequence[str]) -> int:
        """Select the rows of these files (used by the tests and the screenshots)."""
        want = {os.path.abspath(p) for p in paths}
        ids = [i for i, d in self._rows.items() if os.path.abspath(d.path) in want]
        self.tree.selection_set(ids)
        if ids:
            self.tree.see(ids[0])
        self._on_select()
        return len(ids)

    def comparable(self, ds: Sequence[detect.Detection]) -> str:
        """The technique the selection can be overlaid in, or ''."""
        kinds = {d.kind for d in ds}
        return next(iter(kinds)) if len(ds) >= 2 and len(kinds) == 1 and kinds <= set(COMPARE_KINDS) else ""

    def _buttons(self):
        ds = self.selected()
        on = "normal" if ds else "disabled"
        self.btn_open.configure(state=on, fg_color=_pal.ACCENT if ds else _pal.BG_SUB,
                                text_color="white" if ds else _pal.TXT_DIM)
        self.btn_with.configure(state=on)
        self.btn_compare.configure(state="normal" if self.comparable(ds) else "disabled")

    def _on_select(self):
        ds = self.selected()
        self._buttons()
        if not ds:
            return
        if len(ds) == 1:
            d = ds[0]
            if not d.kind:
                text = f"{d.name}: not recognised" + (f" ({d.error})" if d.error else "") + \
                       ". Open with... lets you choose the tool."
            else:
                text = f"{d.name}: {d.label}, {d.confidence} confidence - {d.why()}."
                others = [f"{detect.KINDS[k][1]} ({s:.1f})" for k, s in d.alternatives if s >= detect.LOW]
                if others:
                    text += f"  Also considered: {', '.join(others)} against {d.score:.1f}."
        else:
            text = f"{len(ds)} files selected: {detect.summary(ds).split(': ', 1)[-1]}."
            kind = self.comparable(ds)
            if kind:
                text += f"  Compare selected overlays them in one {detect.KINDS[kind][1]} graph."
        self.lbl_info.configure(text=text)

    def _popup(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)
        return "break"

    # ---- actions ----
    def open_selected(self, ask: bool = False):
        ds = self.selected()
        if ds:
            self.on_open(ds, ask=ask)

    def compare_selected(self):
        ds = self.selected()
        kind = self.comparable(ds)
        if kind:
            self.on_compare(kind, [d.path for d in ds])
        else:
            self.on_status("Compare needs two or more files of one technique: EQE, absorbance, PL, XRD, Raman or FTIR.")

    def reveal_selected(self):
        ds = self.selected()
        target = ds[0].path if ds else self.folder
        if not target:
            return
        try:
            reveal_in_folder(target) if ds else open_with_system(target)
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("Folder", f"{target}\n\n({exc})", parent=self)

    def copy_paths(self):
        ds = self.selected()
        if ds:
            self.clipboard_clear()
            self.clipboard_append("\n".join(d.path for d in ds))
            self.on_status(f"Copied {len(ds)} path(s)")


# ---------------------------------------------------------------- results
class ResultsPanel(ctk.CTkFrame):
    """Analyses already exported under the workspace folder (their side-cars)."""

    COLUMNS = (("date", "Date"), ("tool", "Tool"), ("sample", "Sample"), ("headline", "Key results"),
               ("export", "Export"))
    WIDTHS = (118, 140, 190, 380, 200)

    def __init__(self, master, on_status: Optional[Callable[[str], None]] = None):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.on_status = on_status or (lambda text: None)
        self.folder = ""
        self.entries: List[results_index.Entry] = []
        self._rows: Dict[str, results_index.Entry] = {}
        self._sort = ("date", True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
        self.lbl_summary = ctk.CTkLabel(top, text="", font=_pal.font(11), text_color=_pal.TXT_SUB, anchor="w")
        self.lbl_summary.pack(side="left", fill="x", expand=True)
        self.tool_var = ctk.StringVar(value=ALL_TOOLS)
        self.opt_tool = ctk.CTkOptionMenu(top, values=[ALL_TOOLS], variable=self.tool_var, width=180, height=24,
                                          font=_pal.font(11), command=lambda _v: self._fill())
        self.opt_tool.pack(side="right")
        self.search_var = ctk.StringVar()
        ent = _theme.entry(top, width=170, height=24, textvariable=self.search_var,
                           placeholder_text="Filter by sample")
        ent.pack(side="right", padx=(0, 6))
        ent.bind("<KeyRelease>", lambda e: self._fill())

        frame, self.tree = _tree(self, self.COLUMNS, self.WIDTHS, height=9, stretch="headline")
        frame.grid(row=1, column=0, sticky="nsew", padx=4)
        for key, _title in self.COLUMNS:
            self.tree.heading(key, command=lambda k=key: self.sort_by(k))
        self.tree.tag_configure("weak", foreground=_pal.TXT_DIM)
        self.tree.bind("<Double-1>", lambda e: self.show_record())
        self.tree.bind("<Return>", lambda e: self.show_record())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._buttons())

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=4, pady=(6, 4))
        self.btn_collect = _button(row, "Collect to Excel...", self.collect, primary=True, width=140)
        self.btn_collect.pack(side="left")
        self.btn_record = _button(row, "Show record", self.show_record, width=100)
        self.btn_record.pack(side="left", padx=(6, 0))
        self.btn_export = _button(row, "Open export", self.open_export, width=100)
        self.btn_export.pack(side="left", padx=(6, 0))
        self.btn_reveal = _button(row, "Show in folder", self.reveal_selected, width=110)
        self.btn_reveal.pack(side="left", padx=(6, 0))
        self.lbl_count = ctk.CTkLabel(row, text="", font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="e")
        self.lbl_count.pack(side="right", padx=4)
        self.set_entries([], "")

    def set_entries(self, entries: Sequence[results_index.Entry], folder: str):
        self.entries, self.folder = list(entries), folder
        tools = sorted({e.tool for e in self.entries if e.tool})
        self.opt_tool.configure(values=[ALL_TOOLS] + tools)
        if self.tool_var.get() not in tools:
            self.tool_var.set(ALL_TOOLS)
        self._fill()

    def shown(self) -> List[results_index.Entry]:
        tool, q = self.tool_var.get(), self.search_var.get().strip().lower()
        es = [e for e in self.entries if (tool == ALL_TOOLS or e.tool == tool)
              and (not q or q in e.sample.lower() or q in e.name.lower())]
        key, reverse = self._sort
        keys = {"date": lambda e: e.timestamp or "", "tool": lambda e: (e.tool.lower(), e.timestamp or ""),
                "sample": lambda e: e.sample.lower(), "headline": lambda e: results_index.headline(e).lower(),
                "export": lambda e: e.name.lower()}
        return sorted(es, key=keys[key], reverse=reverse)

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        shown = self.shown()
        for e in shown:
            iid = self.tree.insert("", "end", values=(e.date, e.tool or "-", e.sample,
                                                      e.error or results_index.headline(e), e.name),
                                   tags=("weak",) if (e.error or not e.export) else ())
            self._rows[iid] = e
        if not self.folder:
            text = "Exports of the workspace folder appear here once a folder is chosen in the Workspace tab."
        elif not self.entries:
            text = ("No exported analyses under this folder yet. Every Excel export writes a .analysis.json "
                    "side-car; those are listed here.")
        else:
            text = results_index.summary(self.entries)
        self.lbl_summary.configure(text=text)
        n = len(self.entries)
        self.lbl_count.configure(text=(f"{len(shown)} of {n} exports" if len(shown) != n else f"{n} exports")
                                 if self.folder else "")
        self._buttons()

    def sort_by(self, key: str):
        self._sort = (key, not self._sort[1] if self._sort[0] == key else False)
        self._fill()

    def selected(self) -> Optional[results_index.Entry]:
        sel = self.tree.selection()
        return self._rows.get(sel[0]) if sel else None

    def _buttons(self):
        e = self.selected()
        have = bool(self.shown())
        self.btn_collect.configure(state="normal" if have else "disabled",
                                   fg_color=_pal.ACCENT if have else _pal.BG_SUB,
                                   text_color="white" if have else _pal.TXT_DIM)
        self.btn_record.configure(state="normal" if e else "disabled")
        self.btn_export.configure(state="normal" if (e and e.export) else "disabled")
        self.btn_reveal.configure(state="normal" if e else "disabled")

    # ---- actions ----
    def collect(self, path: str = ""):
        """Write the listed exports (the current filter) to one workbook."""
        entries = self.shown()
        if not entries:
            self.on_status("Nothing to collect: no exported analyses are listed.")
            return ""
        if not path:
            name = (os.path.basename(self.folder.rstrip(os.sep)) or "physiscore") + "_results.xlsx"
            path = filedialog.asksaveasfilename(title="Collect results", initialdir=self.folder or None,
                                                initialfile=name, defaultextension=".xlsx",
                                                filetypes=[("Excel workbook", "*.xlsx")])
            if not path:
                return ""
        try:
            results_index.write_excel(entries, path, self.folder)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Collect results", f"The workbook could not be written:\n{exc}", parent=self)
            return ""
        self.on_status(f"Collected {len(entries)} exports in {os.path.basename(path)}")
        return path

    def open_export(self):
        e = self.selected()
        if e is None or not e.export:
            return
        try:
            open_with_system(e.export)
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("Export", f"{e.export}\n\n({exc})", parent=self)

    def reveal_selected(self):
        e = self.selected()
        if e is None:
            return
        try:
            reveal_in_folder(e.export or e.sidecar)
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo("Folder", f"{e.sidecar}\n\n({exc})", parent=self)

    def show_record(self):
        e = self.selected()
        if e is not None:
            return RecordWindow(self, e)
        return None


def record_rows(entry: results_index.Entry) -> List[tuple]:
    """(section, item, value) lines of one side-car, in reading order."""
    rows = [("Record", "Tool", entry.tool or "-"), ("Record", "Date", entry.date or "-"),
            ("Record", "Physiscore version", entry.version or "-"),
            ("Record", "Export", entry.export or "not found next to the side-car"),
            ("Record", "Side-car", entry.sidecar)]
    if entry.error:
        rows.append(("Record", "Problem", entry.error))
    rows += [("Input", str(i + 1), p) for i, p in enumerate(entry.inputs)]
    rows += [("Parameter", str(k), results_index.fmt(v)) for k, v in entry.parameters.items()]
    for table, label, quantity, value in results_index.flatten(entry.results):
        section = "Result" if table == "summary" else f"Result: {table}"
        rows.append((section, f"{label}  ·  {quantity}" if label else str(quantity), results_index.fmt(value)))
    return rows


class RecordWindow(ctk.CTkToplevel):
    """Everything one side-car records: inputs, parameters and numbers."""

    def __init__(self, master, entry: results_index.Entry):
        super().__init__(master)
        self.title(f"Analysis record - {entry.name}")
        self.geometry("820x560")
        self.minsize(560, 360)
        self.configure(fg_color=_pal.BG_WINDOW)
        self.entry = entry
        ctk.CTkLabel(self, text=f"{entry.tool or 'Analysis'}  ·  {entry.sample}", font=_pal.font(13, "bold"),
                     text_color=_pal.TXT, anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(self, text=f"{entry.date}  ·  Physiscore {entry.version or '?'}  ·  {entry.name}",
                     font=_pal.font(11), text_color=_pal.TXT_SUB, anchor="w").pack(fill="x", padx=12, pady=(0, 6))
        frame, self.tree = _tree(self, (("section", "Section"), ("item", "Item"), ("value", "Value")),
                                 (130, 300, 360), height=18, selectmode="extended", stretch="value")
        frame.pack(fill="both", expand=True, padx=12)
        self.rows = record_rows(entry)
        for r in self.rows:
            self.tree.insert("", "end", values=r)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)
        _button(row, "Copy table", self.copy, width=100).pack(side="left")
        if entry.export:
            _button(row, "Open export", lambda: open_with_system(entry.export), width=100).pack(side="left", padx=6)
        _button(row, "Close", self.destroy, width=80).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(120, self.lift)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join("\t".join(str(c) for c in r) for r in self.rows))
