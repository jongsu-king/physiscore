"""Common window for the curve-analysis tools added in 3.5 (SCLC, light-
intensity dependence, TRPL, impedance, Mott-Schottky, stability).

Each tool is a small subclass that states its parameters and views and hands
the numbers to its core module; this class owns everything the six windows
share:

    left    data files (several at once), parameters, Run
    centre  view selector, graph, table of all analysed files
    right   results of the selected file, checks

    File list ........ add / remove / clear, or a synthetic example produced by
                       the tool's own model (labelled as such everywhere)
    Run .............. one file per event-loop step, on the Tk thread
    All files ........ one line per file; selecting a line shows that file
    Overlay .......... the other files drawn behind the selected one
    Export ........... Excel (summary, results, checks, data tables) with the
                       analysis side-car, Markdown report, figure
    Interpretation ... rule-based reading of the selected result
    Parameters ....... the last values used are remembered per tool

The window never computes anything itself: `load`, `analyse`, `rows`, `checks`
and `interpret` belong to the subclass and its core.
"""
from __future__ import annotations

import os
import tkinter as tk
import warnings
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

import customtkinter as ctk
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg   # no pyplot, no backend switch
from matplotlib.figure import Figure

from scripts.common import app_config
from scripts.common import curve_batch
from scripts.common import curve_io
from scripts.common import palette as _pal
from scripts.common import plot_interactions as _pi
from scripts.common import report as _report
from scripts.common import theme as _theme
from scripts.common.curve_batch import fmt_value

try:
    from scripts.common import analysis_shell as _shell
except Exception:                     # pragma: no cover - the shell is part of the program
    _shell = None

EXAMPLE_PREFIX = "<example> "          # data made by the tool's own model, never a measurement
SET_PREFIX = "<set> "                  # one data set assembled from several files (a J-V intensity series)
_PREFIX_LABELS = {EXAMPLE_PREFIX: "Synthetic example: ", SET_PREFIX: "Set: "}
DATA_FILETYPES = [("Data files", "*.csv *.txt *.dat *.tsv *.xlsx *.xls"), ("All files", "*.*")]


def short_name(path: str) -> str:
    for prefix in _PREFIX_LABELS:
        if path.startswith(prefix):
            return path[len(prefix):]
    return os.path.splitext(os.path.basename(path))[0]


def display_name(path: str) -> str:
    for prefix, label in _PREFIX_LABELS.items():
        if path.startswith(prefix):
            return label + path[len(prefix):]
    return os.path.basename(path)


class CurveToolWindow(ctk.CTkToplevel):
    # ---- what a subclass states -------------------------------------------------
    TOOL_NAME = "Curve analysis"
    SLUG = "curve"                    # file stem of exports, key of the remembered parameters
    CORE = None                       # the core module (summary_rows, checks, COLUMN_SPEC)
    FILE_HINT = ""
    FIELDS: List[Dict[str, Any]] = []
    VIEWS: List[str] = ["Result"]
    OVERLAY = True                    # offer "Overlay all files"
    BATCH: List[tuple] = []           # (heading, key | callable(result), unit)
    HINTS = ("Wheel: zoom  |  Right-click the graph: data reader, plot details, worksheet, export  |  "
             "F5: run  |  Ctrl+O: add files  |  Ctrl+E: Excel  |  Ctrl+S: save figure")
    NOTES = ""                        # method paragraph for the report
    METHOD_SECTION = ""               # section number in docs/METHODS.md, e.g. "17."

    # ---- hooks ---------------------------------------------------------------------
    def load(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read one file -> dict of arrays. A tool of `curve_batch` is read the
        way the command line reads it; any other takes the columns named in
        the core's COLUMN_SPEC."""
        if self.SLUG in curve_batch.TOOLS:
            return curve_batch.load(self.SLUG, path, params)
        df = curve_io.read_numeric_table(path)
        data, names = curve_io.pick_columns(df, self.CORE.COLUMN_SPEC)
        data["_columns"] = names
        return data

    def analyse(self, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        if self.SLUG in curve_batch.TOOLS:
            return curve_batch.analyse(self.SLUG, data, params)
        raise NotImplementedError

    def draw(self, fig, data, result, view: str, params, others) -> None:
        raise NotImplementedError

    def rows(self, result) -> List[tuple]:
        return list(self.CORE.summary_rows(result))

    def checks(self, result) -> List[str]:
        return list(self.CORE.checks(result))

    def interpret(self, result, subject: str):
        if self.SLUG in curve_batch.TOOLS:
            return curve_batch.interpret(self.SLUG, result, subject)
        raise NotImplementedError

    def tables(self, data, result) -> Dict[str, pd.DataFrame]:
        if self.SLUG in curve_batch.TOOLS:
            return curve_batch.tables(self.SLUG, data, result)
        return {}

    def demo(self) -> Optional[tuple]:
        """(name, data) or (name, data, parameters) of a synthetic example, or
        None. The parameters are entered in the form so that the example is
        analysed with the values it was generated with."""
        return None

    def open_actions(self) -> List[tuple]:
        """Further ways of bringing data in: [(label, callback), ...]."""
        return []

    def resolve(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Data of one entry of the file list: an in-memory set or a file."""
        if path in self._memory:
            return self._memory[path]
        return self.load(path, params)

    # ---- construction ----------------------------------------------------------------
    def __init__(self, parent=None, origin_path: str = ""):
        super().__init__(parent)
        self.origin_path = origin_path
        self.directory_path = ""                     # the launcher may set a start folder
        self.files: List[str] = []
        self.items: Dict[str, Dict[str, Any]] = {}
        self.params: Dict[str, Any] = {}
        self.current: Optional[str] = None
        self._memory: Dict[str, Any] = {}
        self._vars: Dict[str, Any] = {}
        self._busy = False
        self._syncing = False
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left()
        self._build_center()
        self._build_right()
        if _shell is not None:
            _shell.attach_chrome(self, self.TOOL_NAME, {
                "open": [("Add files", self.add_files)] + list(self.open_actions())
                        + [("Example", self.load_example)],
                "run": ("Run", self.run),
                "excel": ("Excel", self.export_excel),
                "png": True,
                "report": ("Report", self.export_report),
                "ai": ("Interpretation", self._interpret),
            }, hints=self.HINTS)
        self._restore_params()
        self._redraw()

    # ---- left ------------------------------------------------------------------------
    def _build_left(self):
        left = ctk.CTkScrollableFrame(self, width=330, fg_color=_pal.BG_PANEL, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        gf, g = _theme.group(left, "Data files")
        gf.pack(fill="x", padx=8, pady=(8, 4))
        _theme.style_treeview(rowheight=22)
        self.file_tree = ttk.Treeview(g, columns=("f", "s"), show="headings", height=6, selectmode="browse")
        self.file_tree.heading("f", text="File")
        self.file_tree.heading("s", text="State")
        self.file_tree.column("f", width=205, anchor="w", stretch=True)
        self.file_tree.column("s", width=80, anchor="w", stretch=False)
        self.file_tree.pack(fill="x")
        self.file_tree.bind("<<TreeviewSelect>>", lambda e: self._on_pick(self.file_tree))
        row = ctk.CTkFrame(g, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        for text, cb, width in (("Add...", self.add_files, 62), ("Remove", self.remove_file, 66),
                                ("Clear", self.clear_files, 56), ("Example", self.load_example, 70)):
            _theme.secondary_button(row, text, command=cb, width=width, height=26).pack(side="left", padx=(0, 4))
        if self.FILE_HINT:
            ctk.CTkLabel(g, text=self.FILE_HINT, font=_pal.font(10), text_color=_pal.TXT_MUTED, justify="left",
                         anchor="w", wraplength=300).pack(fill="x", pady=(6, 0))

        groups: Dict[str, Any] = {}
        for f in self.FIELDS:
            name = f.get("group", "Parameters")
            if name not in groups:
                frame, body = _theme.group(left, name)
                frame.pack(fill="x", padx=8, pady=4)
                body.grid_columnconfigure(0, weight=1)
                groups[name] = [body, 0]
            body, r = groups[name]
            kind = f.get("kind", "float")
            default = f.get("default", "")
            if callable(default):
                default = default()
            if kind == "bool":
                var = tk.BooleanVar(value=bool(default))
                ctk.CTkCheckBox(body, text=f["label"], variable=var, font=_pal.font(11), text_color=_pal.TXT,
                                checkbox_width=16, checkbox_height=16, corner_radius=2, border_width=1,
                                fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV).grid(
                    row=r, column=0, columnspan=2, sticky="w", padx=2, pady=4)
            else:
                ctk.CTkLabel(body, text=f["label"], font=_pal.font(11), text_color=_pal.TXT, anchor="w").grid(
                    row=r, column=0, sticky="w", padx=(2, 6), pady=3)
                var = tk.StringVar(value=f"{default:g}" if isinstance(default, float) else str(default))
                if kind == "choice":
                    ctk.CTkOptionMenu(body, values=[str(c) for c in f["choices"]], variable=var, width=124, height=26,
                                      fg_color=_pal.BG_SUB, button_color=_pal.BG_SUB,
                                      button_hover_color=_pal.BG_HOVER, text_color=_pal.TXT, font=_pal.font(11),
                                      dropdown_font=_pal.font(11), corner_radius=_pal.R_INPUT).grid(
                        row=r, column=1, sticky="e", pady=3)
                else:
                    _theme.entry(body, width=124, textvariable=var).grid(row=r, column=1, sticky="e", pady=3)
            self._vars[f["key"]] = var
            groups[name][1] = r + 1
        ctk.CTkButton(left, text="Run   (F5)", command=self.run, height=32, fg_color=_pal.ACCENT,
                      hover_color=_pal.ACCENT_HOV, text_color="white", corner_radius=_pal.R_PILL,
                      font=_pal.font(12, "bold")).pack(fill="x", padx=8, pady=(8, 10))

    # ---- centre ----------------------------------------------------------------------
    def _build_center(self):
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=0, column=1, sticky="nsew", padx=(8, 4), pady=8)
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(mid, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.var_view = tk.StringVar(value=self.VIEWS[0])
        self.seg_view = ctk.CTkSegmentedButton(
            top, values=list(self.VIEWS), variable=self.var_view, height=26, font=_pal.font(11),
            selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV, unselected_color=_pal.BG_SUB,
            unselected_hover_color=_pal.BG_HOVER, text_color=_pal.TXT, corner_radius=_pal.R_PILL,
            command=lambda _v: self._redraw())
        self.seg_view.pack(side="left")
        self.var_overlay = tk.BooleanVar(value=False)
        if self.OVERLAY:
            ctk.CTkCheckBox(top, text="Overlay all files", variable=self.var_overlay, command=self._redraw,
                            font=_pal.font(11), text_color=_pal.TXT, checkbox_width=16, checkbox_height=16,
                            corner_radius=2, border_width=1, fg_color=_pal.ACCENT,
                            hover_color=_pal.ACCENT_HOV).pack(side="right", padx=4)

        holder = ctk.CTkFrame(mid, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD, border_width=1,
                              border_color=_pal.BORDER)
        holder.grid(row=1, column=0, sticky="nsew")
        _pal.apply_mpl()
        self.fig = Figure(figsize=(9, 6), dpi=100)
        self.fig.patch.set_facecolor(_pal.PLOT_BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=holder)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=2, pady=2)
        _pi.enable_wheel_zoom(self.canvas)
        _pi.add_canvas_context_menu(self, self.canvas, self.fig)

        box = ctk.CTkFrame(mid, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD, border_width=1,
                           border_color=_pal.BORDER)
        box.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        head = ctk.CTkLabel(box, text="All files", font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB, anchor="w")
        head.pack(fill="x", padx=10, pady=(6, 0))
        _theme.panel_header(head, box)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=6, pady=(0, 6))
        cols = ["file"] + [f"b{i}" for i in range(len(self.BATCH))] + ["chk"]
        self.batch_tree = ttk.Treeview(inner, columns=cols, show="headings", height=5, selectmode="browse")
        self.batch_tree.heading("file", text="File")
        self.batch_tree.column("file", width=200, anchor="w", stretch=True)
        for i, b in enumerate(self.BATCH):
            unit = f" ({b[2]})" if len(b) > 2 and b[2] else ""
            self.batch_tree.heading(f"b{i}", text=f"{b[0]}{unit}")
            self.batch_tree.column(f"b{i}", width=118, anchor="e", stretch=True)
        self.batch_tree.heading("chk", text="Checks")
        self.batch_tree.column("chk", width=160, anchor="w", stretch=True)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=sb.set)
        self.batch_tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.batch_tree.bind("<<TreeviewSelect>>", lambda e: self._on_pick(self.batch_tree))
        _pi.attach_tree_context_menu(self, self.batch_tree)

    # ---- right -----------------------------------------------------------------------
    def _build_right(self):
        right = ctk.CTkFrame(self, width=430, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD, border_width=1,
                             border_color=_pal.BORDER)
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 8), pady=8)
        right.grid_propagate(False)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        self.lbl_result = ctk.CTkLabel(right, text="Results", font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB,
                                       anchor="w")
        self.lbl_result.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 0))
        _theme.panel_header(self.lbl_result, right)
        _theme.style_treeview(rowheight=22)
        self.tree = ttk.Treeview(right, columns=("q", "v", "u"), show="headings", selectmode="extended")
        for col, text, width, anchor in (("q", "Quantity", 205, "w"), ("v", "Value", 120, "e"), ("u", "Unit", 70, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, minwidth=50, anchor=anchor, stretch=(col == "q"))
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=(0, 6))
        sb.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=(0, 6))
        _pi.attach_tree_context_menu(self, self.tree)
        head = ctk.CTkLabel(right, text="Checks", font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB, anchor="w")
        head.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 0))
        _theme.panel_header(head, right)
        self.txt_checks = ctk.CTkTextbox(right, height=210, wrap="word", font=_pal.font(11), fg_color=_pal.BG_CARD,
                                         text_color=_pal.TXT, border_width=0, corner_radius=0)
        self.txt_checks.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self.txt_checks.configure(state="disabled")

    # ---- parameters ------------------------------------------------------------------
    def _params(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in self.FIELDS:
            key, kind = f["key"], f.get("kind", "float")
            raw = self._vars[key].get()
            if kind == "bool":
                out[key] = bool(raw)
            elif kind in ("choice", "text"):
                out[key] = str(raw).strip()
            else:
                text = str(raw).strip().replace(",", ".")
                if not text:
                    if f.get("optional"):
                        out[key] = None
                        continue
                    raise ValueError(f"{f['label']}: a value is needed")
                try:
                    out[key] = float(text)
                except ValueError:
                    raise ValueError(f"{f['label']}: '{raw}' is not a number") from None
                lo, hi = f.get("min"), f.get("max")
                if (lo is not None and out[key] < lo) or (hi is not None and out[key] > hi):
                    raise ValueError(f"{f['label']}: {out[key]:g} is outside the allowed range "
                                     f"({'-inf' if lo is None else lo} ... {'inf' if hi is None else hi})")
                if kind == "int":
                    out[key] = int(round(out[key]))
        return out

    def set_param(self, key: str, value) -> None:
        if key in self._vars:
            self._vars[key].set(value if isinstance(value, bool) else str(value))

    def _restore_params(self):
        try:
            saved = (app_config.get("tool_params", {}) or {}).get(self.SLUG, {}) or {}
        except Exception:
            saved = {}
        for f in self.FIELDS:
            key = f["key"]
            if key not in saved or f.get("remember") is False:
                continue
            val = saved[key]
            kind = f.get("kind", "float")
            try:
                if kind == "bool":
                    self._vars[key].set(bool(val))
                elif kind == "choice":
                    if str(val) in [str(c) for c in f["choices"]]:
                        self._vars[key].set(str(val))
                elif val is None:
                    self._vars[key].set("")
                else:
                    self._vars[key].set(f"{val:g}" if isinstance(val, float) else str(val))
            except Exception:
                pass

    def _save_params(self, params):
        try:
            store = dict(app_config.get("tool_params", {}) or {})
            store[self.SLUG] = {k: v for k, v in params.items()
                                if isinstance(v, (int, float, str, bool)) or v is None}
            app_config.update({"tool_params": store})
        except Exception:
            pass

    # ---- files -----------------------------------------------------------------------
    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self, title=f"{self.TOOL_NAME}: data files",
                                            initialdir=self.directory_path or None, filetypes=DATA_FILETYPES)
        if paths:
            self.directory_path = os.path.dirname(paths[0])
            self.load_paths(list(paths))

    def load_paths(self, paths: List[str], run: bool = True):
        """Add files (used by the launcher's workspace too) and analyse them."""
        for p in paths:
            if p and p not in self.files:
                self.files.append(p)
        self._fill_files()
        if run and self.files:
            self.run()

    def load_example(self):
        made = self.demo()
        if not made:
            messagebox.showinfo(self.TOOL_NAME, "This tool has no built-in example.", parent=self)
            return
        name, data = made[0], made[1]
        for k, v in (made[2] if len(made) > 2 else {}).items():
            self.set_param(k, v)
        self.add_memory(EXAMPLE_PREFIX, name, data)
        self.run()

    def add_memory(self, prefix: str, name: str, data: Dict[str, Any]) -> str:
        """Put a data set that is not a single file in the file list."""
        key = prefix + name
        self._memory[key] = data
        if key not in self.files:
            self.files.append(key)
        self.current = key
        self._fill_files()
        return key

    def remove_file(self):
        sel = self.file_tree.selection()
        if not sel:
            return
        path = sel[0]
        if path in self.files:
            self.files.remove(path)
        self.items.pop(path, None)
        self._memory.pop(path, None)
        if self.current == path:
            self.current = next((p for p in self.files if self.items.get(p, {}).get("result")), None)
        self._fill_files()
        self._fill_batch()
        self._show()

    def clear_files(self):
        self.files, self.items, self._memory, self.current = [], {}, {}, None
        self._fill_files()
        self._fill_batch()
        self._show()

    def _state(self, path) -> str:
        it = self.items.get(path)
        if it is None:
            return "not run"
        if it["error"]:
            return "error"
        n = len(it.get("checks") or [])
        return "ok" if n == 0 else f"{n} check{'s' if n != 1 else ''}"

    def _fill_files(self):
        self._syncing = True
        try:
            self.file_tree.delete(*self.file_tree.get_children())
            for p in self.files:
                self.file_tree.insert("", "end", iid=p, values=(display_name(p), self._state(p)))
            if self.current in self.files:
                self.file_tree.selection_set(self.current)
        finally:
            self._syncing = False

    def _batch_value(self, spec, result):
        return curve_batch.batch_value(spec, result)

    def _fill_batch(self):
        self._syncing = True
        try:
            self.batch_tree.delete(*self.batch_tree.get_children())
            for p in self.files:
                it = self.items.get(p)
                if it is None:
                    continue
                if it["error"]:
                    vals = [short_name(p)] + ["-"] * len(self.BATCH) + [it["error"]]
                else:
                    n = len(it["checks"])
                    vals = ([short_name(p)] + [fmt_value(self._batch_value(b, it["result"])) for b in self.BATCH]
                            + ["none" if n == 0 else f"{n} to read"])
                self.batch_tree.insert("", "end", iid=p, values=vals)
            if self.current is not None and self.batch_tree.exists(self.current):
                self.batch_tree.selection_set(self.current)
        finally:
            self._syncing = False

    def _on_pick(self, tree):
        if self._syncing:
            return
        sel = tree.selection()
        if not sel or sel[0] == self.current or sel[0] not in self.items:
            return
        self.current = sel[0]
        self._syncing = True
        try:
            for other in (self.file_tree, self.batch_tree):
                if other is not tree and other.exists(self.current):
                    other.selection_set(self.current)
        finally:
            self._syncing = False
        self._show()

    # ---- run -------------------------------------------------------------------------
    def _work_one(self, path, params) -> Dict[str, Any]:
        try:
            data = self.resolve(path, params)
            result = self.analyse(data, params)
            remarks = self.checks(result)
            if self.SLUG in curve_batch.TOOLS and os.path.isfile(path):
                remarks = curve_batch.file_check(self.SLUG, path) + remarks
            return {"data": data, "result": result, "error": "", "checks": remarks}
        except Exception as e:              # noqa: BLE001 - one bad file must not stop the others
            return {"data": None, "result": None, "error": f"{type(e).__name__}: {e}", "checks": []}

    def _work(self, files, params) -> Dict[str, Dict[str, Any]]:
        return {p: self._work_one(p, params) for p in files}

    def run(self, sync: bool = False):
        if self._busy:
            return
        if not self.files:
            messagebox.showinfo(self.TOOL_NAME, "Add a data file first (or load the example).", parent=self)
            return
        try:
            params = self._params()
        except ValueError as e:
            messagebox.showerror(self.TOOL_NAME, str(e), parent=self)
            return
        self._save_params(params)
        files = list(self.files)
        if sync:
            self._done(self._work(files, params), params)
            return
        # One file per event-loop turn, on the Tk thread.  A worker thread is not used:
        # Python may collect Tk objects of a closed window from whichever thread happens
        # to be running, and Tcl must only ever be entered from the thread that owns it.
        self._busy = True
        self._status(f"Analysing {len(files)} file{'s' if len(files) != 1 else ''}...")
        job = {"files": files, "out": {}, "next": 0}
        self.after(10, lambda: self._run_step(job, params))

    def _run_step(self, job, params):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        files, i = job["files"], job["next"]
        if i >= len(files):
            self._done(job["out"], params)
            return
        if len(files) > 1:
            self._status(f"Analysing {i + 1} / {len(files)}: {short_name(files[i])}")
            self.update_idletasks()
        job["out"][files[i]] = self._work_one(files[i], params)
        job["next"] = i + 1
        self.after(1, lambda: self._run_step(job, params))

    def _done(self, out, params):
        self._busy = False
        self.items, self.params = out, params
        good = [p for p in self.files if out.get(p, {}).get("result") is not None]
        if self.current not in good:
            self.current = good[0] if good else (self.files[0] if self.files else None)
        self._fill_files()
        self._fill_batch()
        self._show()
        bad = len(out) - len(good)
        self._status(f"{len(good)} file{'s' if len(good) != 1 else ''} analysed"
                     + (f", {bad} could not be read" if bad else ""))

    def _status(self, text):
        if _shell is not None:
            _shell.set_status(self, text)

    # ---- display ---------------------------------------------------------------------
    def _item(self):
        it = self.items.get(self.current) if self.current else None
        return it if it and it.get("result") is not None else None

    def _show(self):
        self.tree.delete(*self.tree.get_children())
        it = self.items.get(self.current) if self.current else None
        lines: List[str] = []
        if it is None:
            self.lbl_result.configure(text="Results")
        elif it["error"]:
            self.lbl_result.configure(text=f"Results - {short_name(self.current)}")
            lines = ["This file could not be analysed.", "", it["error"]]
        else:
            self.lbl_result.configure(text=f"Results - {short_name(self.current)}")
            for q, v, u in self.rows(it["result"]):
                self.tree.insert("", "end", values=(q, fmt_value(v), u))
            cols = (it["data"] or {}).get("_columns") if isinstance(it["data"], dict) else None
            if self.current.startswith(EXAMPLE_PREFIX):
                lines.append("Synthetic example produced by the tool's own model - not a measurement.")
                lines.append("")
            elif cols:
                lines.append("Columns read: " + ", ".join(f"{k} = {v}" for k, v in cols.items()))
                lines.append("")
            how = (it["data"] or {}).get("_how") if isinstance(it["data"], dict) else None
            if how:
                lines.append(f"Read as: {how}")
                lines.append("")
            if it["checks"]:
                lines += [f"- {c}" for c in it["checks"]]
            else:
                lines.append("No check raised a remark.")
        self.txt_checks.configure(state="normal")
        self.txt_checks.delete("1.0", "end")
        self.txt_checks.insert("1.0", "\n".join(lines))
        self.txt_checks.configure(state="disabled")
        self._redraw()

    def _others(self):
        if not (self.OVERLAY and self.var_overlay.get()):
            return []
        return [(short_name(p), self.items[p]["data"], self.items[p]["result"]) for p in self.files
                if p != self.current and self.items.get(p, {}).get("result") is not None]

    def _redraw(self):
        self.fig.clear()
        it = self._item()
        if it is None:
            ax = self.fig.add_subplot(111)
            _pal.style_axes(ax)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "Add a data file and press Run (F5),\nor load the synthetic example.",
                    ha="center", va="center", transform=ax.transAxes, color=_pal.TXT_MUTED, fontsize=11)
        else:
            try:
                self.draw(self.fig, it["data"], it["result"], self.var_view.get(), self.params, self._others())
            except Exception as e:          # noqa: BLE001 - a view that cannot be drawn says why
                self.fig.clear()
                ax = self.fig.add_subplot(111)
                ax.set_xticks([])
                ax.set_yticks([])
                ax.text(0.5, 0.5, f"This view cannot be drawn for this file:\n{e}", ha="center", va="center",
                        transform=ax.transAxes, color=_pal.TXT_MUTED, fontsize=10, wrap=True)
            for ax in self.fig.axes:
                _pal.style_axes(ax, grid=bool(getattr(ax, "_physiscore_grid", False)))
        try:
            with warnings.catch_warnings():          # a view may hold axes tight_layout cannot place
                warnings.simplefilter("ignore")
                self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw_idle()

    # ---- export ----------------------------------------------------------------------
    def _export_items(self) -> List[Dict[str, Any]]:
        """The analysed entries in list order, labelled as the tables show them."""
        return [dict(self.items[p], file=short_name(p)) for p in self.files if p in self.items]

    def summary_frame(self) -> pd.DataFrame:
        return curve_batch.summary_table(self._export_items(), self.BATCH)

    def results_frame(self) -> pd.DataFrame:
        return curve_batch.results_table(self._export_items(), self.rows)

    def _inputs(self) -> List[str]:
        out: List[str] = []
        for p in self.files:
            if p not in self.items:
                continue
            if p.startswith(EXAMPLE_PREFIX):
                out.append("synthetic example (not a measurement): " + short_name(p))
            elif p.startswith(SET_PREFIX):
                data = self.items[p].get("data") or self._memory.get(p) or {}
                out.extend(data.get("files") or data.get("_jv_files") or [short_name(p)])
            else:
                out.append(p)
        return out

    def _need_result(self) -> bool:
        if self._item() is None:
            messagebox.showinfo(self.TOOL_NAME, "Run the analysis first.", parent=self)
            return False
        return True

    def write_excel(self, path: str) -> str:
        return curve_batch.write_workbook(path, self.TOOL_NAME, self._export_items(), self.params, self.BATCH,
                                          self.rows, self.tables, inputs=self._inputs())

    def export_excel(self):
        if not self._need_result():
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx", title="Save results",
                                            initialdir=self.directory_path or None,
                                            initialfile=f"{self.SLUG}_results.xlsx",
                                            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            self.write_excel(path)
            self._status(f"Saved {os.path.basename(path)} and its analysis record")
        except Exception as e:
            messagebox.showerror(self.TOOL_NAME, f"Save failed: {e}", parent=self)

    def report_sections(self) -> List[tuple]:
        it = self._item()
        sections: List[tuple] = [("Parameters", {k: ("-" if v is None else v) for k, v in self.params.items()})]
        sections.append((f"Results - {short_name(self.current)}",
                         pd.DataFrame([{"Quantity": q, "Value": fmt_value(v), "Unit": u}
                                       for q, v, u in self.rows(it["result"])])))
        if len([p for p in self.files if p in self.items]) > 1:
            sections.append(("All files", self.summary_frame().drop(columns=["Error"]).map(
                lambda v: fmt_value(v) if not isinstance(v, str) else v)))
        sections.append(("Checks", "\n".join(f"- {c}" for c in it["checks"]) or "No check raised a remark."))
        try:
            rep = self.interpret(it["result"], short_name(self.current))
            if rep.findings:
                sections.append(("Interpretation", pd.DataFrame(
                    [{"Level": f.level, "Topic": f.topic, "Finding": f.text, "Evidence": f.evidence,
                      "Reference": f.ref} for f in rep.sorted()])))
        except Exception:
            pass
        if self.NOTES:
            sections.append(("Method", self.NOTES))
        return sections

    def export_report(self):
        if not self._need_result():
            return
        path = _report.ask_report_path(self, f"{self.SLUG}_report.md")
        if not path:
            return
        try:
            _report.write_markdown_report(path, f"{self.TOOL_NAME} - {short_name(self.current)}",
                                          self.report_sections(), figure=self.fig, inputs=self._inputs())
            self._status(f"Saved {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror(self.TOOL_NAME, f"Report failed: {e}", parent=self)

    def _interpret(self):
        if not self._need_result():
            return None
        from scripts.common.interpret_window import show
        return show(self, self.interpret(self._item()["result"], short_name(self.current)),
                    title=f"Interpretation - {self.TOOL_NAME}")


# --------------------------------------------------------------------------- drawing helpers
def data_kw(i: int = 0, label: Optional[str] = None, hollow: bool = True, line: bool = False,
            ms: float = 4.5) -> Dict[str, Any]:
    """Measured points: open circles in the colour of series i."""
    c = _pal.series_color(i)
    return dict(color=c, marker="o", ms=ms, mfc=_pal.PLOT_AXES if hollow else c, mec=c, mew=1.1,
                ls="-" if line else "none", lw=1.0, label=label)


def fit_kw(label: Optional[str] = None, color: Optional[str] = None, lw: float = 1.7, ls: str = "-") -> Dict[str, Any]:
    """A fitted or model curve."""
    return dict(color=color or _pal.RED, lw=lw, ls=ls, label=label, zorder=5)


def other_kw(k: int, label: Optional[str] = None) -> Dict[str, Any]:
    """The other files of the list, drawn behind the selected one."""
    return dict(color=_pal.series_color(k + 1), lw=1.1, alpha=0.9, label=label, zorder=1)


def ref_line(ax, x=None, y=None, text: str = "", side: str = "right", **kw) -> None:
    """Dashed reference line with an optional small label (`side`: the end of
    a horizontal line that carries the label)."""
    style = dict(color=_pal.PLOT_REF, lw=0.9, ls="--", zorder=2)
    style.update(kw)
    if y is not None:
        ax.axhline(y, **style)
        if text:
            left = side == "left"
            ax.annotate(text, xy=(0.0 if left else 1.0, y), xycoords=("axes fraction", "data"),
                        xytext=(4 if left else -4, 3), textcoords="offset points",
                        ha="left" if left else "right", va="bottom", fontsize=8.5, color=_pal.PLOT_TICK)
    if x is not None:
        ax.axvline(x, **style)
        if text:
            ax.annotate(text, xy=(x, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -4),
                        textcoords="offset points", ha="left", va="top", fontsize=8.5, color=_pal.PLOT_TICK,
                        rotation=90)


def legend(ax, loc: str = "best") -> None:
    _pi.smart_legend(ax, loc=loc)


def note_box(ax, text: str, loc: str = "lower right") -> None:
    """Small result box inside the axes (parameters of the fit drawn)."""
    pos = {"lower right": (0.98, 0.04, "right", "bottom"), "upper right": (0.98, 0.96, "right", "top"),
           "upper left": (0.02, 0.96, "left", "top"), "lower left": (0.02, 0.04, "left", "bottom")}[loc]
    ax.text(pos[0], pos[1], text, transform=ax.transAxes, ha=pos[2], va=pos[3], fontsize=9, color=_pal.PLOT_FG,
            bbox=dict(boxstyle="square,pad=0.4", fc=_pal.PLOT_AXES, ec=_pal.PLOT_SPINE, lw=0.8), zorder=20)


def run_standalone(window_class):
    root = ctk.CTk()
    root.withdraw()
    win = window_class(root)
    win.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
