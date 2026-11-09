"""Multi-file comparison window shared by the EQE, absorbance, PL and XRD tools.

Several files are loaded at once, each spectrum is analysed with the same
function the batch command uses (scripts.common.batch), the results are shown
side by side in a table and the spectra are overlaid (optionally normalised
and offset, as in a stacked XRD or PL figure). The table and the figure are
exported like every other tool output, with a reproducibility side-car.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scripts.common import batch as _batch
from scripts.common import palette as _pal
from scripts.common import theme as _theme


class CompareWindow(ctk.CTkToplevel):
    """technique: 'eqe' | 'abs' | 'pl' | 'xrd' | 'raman' | 'ftir'."""

    TITLES = {"eqe": "EQE", "abs": "Absorbance", "pl": "PL", "xrd": "XRD", "raman": "Raman", "ftir": "FTIR"}
    AXES = {"eqe": ("Wavelength (nm)", "EQE"), "abs": ("Wavelength (nm)", "Absorbance"),
            "pl": ("Wavelength (nm)", "PL intensity (a.u.)"), "xrd": ("2θ (°)", "Intensity (a.u.)"),
            "raman": ("Raman shift (cm⁻¹)", "Intensity (a.u.)"), "ftir": ("Wavenumber (cm⁻¹)", "Transmittance")}

    def __init__(self, parent, technique: str, options: Optional[Dict] = None, files: Optional[List[str]] = None):
        super().__init__(parent)
        self.technique = technique
        self.options = dict(options or {})
        self.items: List[Dict] = []        # {path, column, x, y, result}
        self.title(f"Compare {self.TITLES[technique]} files - Physiscore")
        self.geometry("1320x820")
        self.minsize(1000, 640)
        self.configure(fg_color=_pal.BG_WINDOW)
        try:
            from scripts.common.analysis_shell import make_thread_safe
            make_thread_safe(self)
        except Exception:
            pass
        self._build()
        if files:
            self.add_paths(files)
        self.after(100, self.lift)

    # ---------------- UI ----------------
    def _btn(self, parent, text, cmd, primary=False):
        return ctk.CTkButton(parent, text=text, command=cmd, height=26, width=max(70, 8 + 7 * len(text)),
                             fg_color=_pal.ACCENT if primary else _pal.BG_SUB,
                             hover_color=_pal.ACCENT_HOV if primary else _pal.BG_HOVER,
                             text_color="white" if primary else _pal.TXT, border_width=0 if primary else 1,
                             border_color=_pal.BORDER_HI, font=_pal.font(11, "bold" if primary else None),
                             corner_radius=_pal.R_PILL)

    def _build(self):
        bar = ctk.CTkFrame(self, height=40, fg_color=_pal.BG_PANEL, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text=f"Compare {self.TITLES[self.technique]}", font=_pal.font(12, "bold"),
                     text_color=_pal.TXT).pack(side="left", padx=(12, 14))
        self._btn(bar, "Add files", self.add_files, primary=True).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Add folder", self.add_folder).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Remove selected", self.remove_selected).pack(side="left", padx=3, pady=7)
        self._btn(bar, "Clear", self.clear).pack(side="left", padx=3, pady=7)
        self.var_allcols = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(bar, text="Every column of a file", variable=self.var_allcols, font=_pal.font(10),
                        text_color=_pal.TXT, checkbox_width=16, checkbox_height=16).pack(side="left", padx=10)
        self._btn(bar, "Excel", self.export_excel).pack(side="right", padx=3, pady=7)
        self._btn(bar, "Figure", self.save_figure).pack(side="right", padx=3, pady=7)

        sb = ctk.CTkFrame(self, height=24, fg_color=_pal.BG_PANEL, corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.lbl_status = ctk.CTkLabel(sb, text="Add files to compare", font=_pal.font(10), text_color=_pal.TXT_SUB)
        self.lbl_status.pack(side="left", padx=10)

        body = ctk.CTkFrame(self, fg_color=_pal.BG_WINDOW)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        body.grid_rowconfigure(2, weight=0)

        view = ctk.CTkFrame(body, fg_color="transparent")
        view.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(view, text="Normalise", font=_pal.font(10), text_color=_pal.TXT_SUB).pack(side="left")
        self.var_norm = ctk.StringVar(value="max" if self.technique in ("xrd", "pl", "raman") else "none")
        ctk.CTkSegmentedButton(view, values=["none", "max", "area"], variable=self.var_norm, height=24,
                               font=_pal.font(10), command=lambda _v: self.redraw(),
                               selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT).pack(side="left", padx=(6, 16))
        ctk.CTkLabel(view, text="Offset", font=_pal.font(10), text_color=_pal.TXT_SUB).pack(side="left")
        self.var_offset = tk.DoubleVar(value=1.1 if self.technique == "xrd" else 0.0)
        ctk.CTkSlider(view, from_=0.0, to=2.0, number_of_steps=40, variable=self.var_offset, width=160,
                      command=lambda _v: self.redraw()).pack(side="left", padx=6)
        if self.technique in ("eqe", "abs", "pl"):
            self.var_energy = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(view, text="Energy axis (eV)", variable=self.var_energy, font=_pal.font(10),
                            text_color=_pal.TXT, checkbox_width=16, checkbox_height=16,
                            command=self.redraw).pack(side="left", padx=16)
        else:
            self.var_energy = None

        self.fig = Figure(figsize=(9, 4.6), dpi=100)
        _pal.apply_mpl()
        self.fig.patch.set_facecolor(_pal.PLOT_BG)
        self.ax = self.fig.add_subplot(111)
        _pal.style_axes(self.ax)
        self.canvas = FigureCanvasTkAgg(self.fig, master=body)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas)
            _pi.enable_drag_pan(self.canvas)
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception:
            pass

        table_frame = ctk.CTkFrame(body, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD,
                                   border_width=1, border_color=_pal.BORDER, height=230)
        table_frame.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        table_frame.grid_propagate(False)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        _theme.style_treeview(rowheight=22)
        self.tree = ttk.Treeview(table_frame, show="headings", selectmode="extended")
        ys = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=(6, 0))
        ys.grid(row=0, column=1, sticky="ns", pady=(6, 0))
        xs.grid(row=1, column=0, sticky="ew", padx=(6, 0))
        try:
            from scripts.common import plot_interactions as _pi
            _pi.attach_tree_context_menu(self, self.tree)
        except Exception:
            pass

    # ---------------- data ----------------
    def add_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="Add files",
                                            filetypes=[("Data", "*.csv *.txt *.tsv *.dat *.xy *.xlsx *.xls"),
                                                       ("All files", "*.*")])
        if paths:
            self.add_paths(list(paths))

    def add_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Add every data file of a folder")
        if folder:
            self.add_paths(_batch.list_data_files(folder))

    def add_paths(self, paths: List[str]):
        self.lbl_status.configure(text=f"Analysing {len(paths)} file(s)...")
        allcols = bool(self.var_allcols.get())

        def work():
            new, errors = [], []
            for p in paths:
                try:
                    spectra = _batch.read_all_columns(p) if allcols else [_batch.read_xy(p)]
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{os.path.basename(p)}: {exc}")
                    continue
                for x, y, col in spectra:
                    try:
                        res = _batch.ANALYSERS[self.technique](x, y, **self.options)
                    except Exception as exc:  # noqa: BLE001
                        res = {"Error": str(exc)}
                    new.append({"path": p, "column": col, "x": x, "y": y, "result": res})
            self.after(0, lambda: self._added(new, errors))

        threading.Thread(target=work, daemon=True).start()

    def _added(self, new, errors):
        self.items.extend(new)
        self.refresh_table()
        self.redraw()
        msg = f"{len(self.items)} spectra"
        if errors:
            msg += f"; {len(errors)} file(s) skipped"
            messagebox.showwarning("Compare", "\n".join(errors[:12]), parent=self)
        self.lbl_status.configure(text=msg)

    def remove_selected(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        for i in sel:
            if 0 <= i < len(self.items):
                self.items.pop(i)
        self.refresh_table()
        self.redraw()

    def clear(self):
        self.items.clear()
        self.refresh_table()
        self.redraw()

    def results_frame(self) -> pd.DataFrame:
        rows = []
        for it in self.items:
            row = {"File": os.path.basename(it["path"]), "Column": it["column"]}
            row.update(it["result"])
            rows.append(row)
        return pd.DataFrame(rows)

    def refresh_table(self):
        df = self.results_frame()
        self.tree.delete(*self.tree.get_children())
        cols = list(df.columns) if not df.empty else ["File", "Column"]
        self.tree.configure(columns=cols)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=150 if c == "File" else 110, anchor="w" if c in ("File", "Column") else "e",
                             stretch=False)
        for i, (_, row) in enumerate(df.iterrows()):
            vals = []
            for c in cols:
                v = row[c]
                if isinstance(v, float):
                    vals.append("" if not np.isfinite(v) else (f"{v:.4g}" if abs(v) < 1e4 else f"{v:.3e}"))
                else:
                    vals.append("" if v is None else str(v))
            self.tree.insert("", "end", iid=str(i), values=vals)

    # ---------------- plot ----------------
    def redraw(self):
        self.ax.clear()
        _pal.style_axes(self.ax)
        xlab, ylab = self.AXES[self.technique]
        energy = self.var_energy is not None and self.var_energy.get()
        norm = self.var_norm.get()
        offset = float(self.var_offset.get())
        for i, it in enumerate(self.items):
            x, y = np.asarray(it["x"], float), np.asarray(it["y"], float)
            if energy:
                from scripts.common.spectral import spectrum_to_energy
                x, y = spectrum_to_energy(x, y, jacobian=self.technique == "pl")
            if norm == "max" and np.nanmax(np.abs(y)) > 0:
                y = y / np.nanmax(np.abs(y))
            elif norm == "area":
                from scripts.common.spectral import integrate
                a = integrate(x, np.abs(y))
                y = y / a if a and np.isfinite(a) else y
            step = offset * (1.0 if norm != "none" else float(np.nanmax(np.abs(it["y"])) or 1.0))
            label = os.path.splitext(os.path.basename(it["path"]))[0]
            if it["column"] and len(self.items) > 1 and self.var_allcols.get():
                label += f" [{it['column']}]"
            self.ax.plot(x, y + i * step, linewidth=1.3, color=_pal.series_color(i), label=label)
        self.ax.set_xlabel("Energy (eV)" if energy else xlab)
        self.ax.set_ylabel(ylab + (" (normalised)" if norm != "none" else "") + (", offset" if offset > 0 else ""))
        if self.technique == "ftir":
            self.ax.invert_xaxis()
        if self.items:
            try:
                from scripts.common.plot_interactions import smart_legend
                smart_legend(self.ax, loc="best", max_items=14)
            except Exception:
                self.ax.legend(fontsize=8)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ---------------- export ----------------
    def export_excel(self):
        df = self.results_frame()
        if df.empty:
            messagebox.showinfo("Export", "Nothing to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx",
                                            initialfile=f"{self.technique}_comparison.xlsx",
                                            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                df.to_csv(path, index=False)
            else:
                with pd.ExcelWriter(path, engine="openpyxl") as w:
                    df.to_excel(w, sheet_name="Results", index=False)
                    for i, it in enumerate(self.items):
                        name = f"{i + 1:02d}_{os.path.splitext(os.path.basename(it['path']))[0]}"[:31]
                        pd.DataFrame({"x": it["x"], "y": it["y"]}).to_excel(w, sheet_name=name, index=False)
            from scripts.common.provenance import write_sidecar
            write_sidecar(path, f"Compare {self.TITLES[self.technique]}", inputs=[it["path"] for it in self.items],
                          parameters=self.options, results={"table": df})
            self.lbl_status.configure(text=f"Saved {os.path.basename(path)}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Export", str(exc), parent=self)

    def save_figure(self):
        from scripts.common.analysis_shell import save_fig_png
        save_fig_png(self)
