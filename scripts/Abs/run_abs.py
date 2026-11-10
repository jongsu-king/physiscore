# run_abs.py - Absorbance/Tauc Analyzer (JV-style UI draft)
import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import numpy as np
import pandas as pd
import customtkinter as ctk

# Matplotlib embed
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from matplotlib.widgets import RangeSlider, SpanSelector, RadioButtons
from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report
from scripts.Abs import abs_core

# Win32com check
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "abs_config.json")
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None



class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("Absorbance / Tauc Plot Analyzer")
        self.geometry("1400x900")

        self.passed_origin_path = origin_path
        self.passed_api_key = api_key

        # -------------------------
        # Style
        # -------------------------
        self.card_bg = _pal.BG_CARD
        self.card_border = _pal.BORDER
        self.accent_blue = _pal.ACCENT
        self.accent_orange = _pal.ORANGE
        self.accent_green = _pal.GREEN
        self.accent_purple = _pal.PURPLE
        self.text_primary = _pal.TXT
        self.text_secondary = _pal.TXT_SUB

        # -------------------------
        # State
        # -------------------------
        self.x_slider = None
        
        self.df = None
        self.target_file: Path | None = None
        self.sheet_name: str | None = None

        self.raw_x = None  # wavelength (nm)
        self.raw_y = None  # absorbance
        self.hv = None     # energy (eV)
        self.absorbance = None

        self.bandgap_mode = tk.StringVar(value="Direct")  # Direct/Indirect
        self.x_min = tk.DoubleVar(value=0)
        self.x_max = tk.DoubleVar(value=0)

        self.fit_result = None   # store dict
        self.data_state = {}     # x, y, y_label, etc.

        self.selected_sheet = tk.StringVar(value="")

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_center_panel()
        self.create_right_panel()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Bring to front
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "Absorbance / Tauc Analysis", {
                    "open": ("Open Excel", self.browse_excel),
                    "run": ("Load and plot", self.load_data_from_ui),
                    "extra": [("Compare files", self.open_compare)],
                    "fit": ("Auto fit", self.auto_fit_expected),
                    "excel": ("Excel", self.save_to_excel),
                    "png": True,
                    "report": ("Report", self.export_report),
                    "origin": ("Origin", self.send_to_origin)
                }, hints="Drag on the Tauc plot: linear fit of that range  |  Auto fit: automatic region  |  "
                         "Wheel: zoom (Ctrl = x, Shift = y)  |  Right-click: plot menu")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

    def on_closing(self):
        self.destroy()

    # =====================
    # UI
    # =====================
    def create_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=300, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        # ---- Load Card ----
        load_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        row = ctk.CTkFrame(load_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_file = ctk.CTkEntry(row, placeholder_text="Select Excel file...", height=28)
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(row, text="...", width=40, height=28,
                      command=self.browse_excel, corner_radius=_pal.R_PILL).pack(side="right")

        # Sheet select
        sheet_row = ctk.CTkFrame(load_card, fg_color="transparent")
        sheet_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(sheet_row, text="Sheet:", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")

        self.sheet_menu = ctk.CTkOptionMenu(
            sheet_row, values=["-"], variable=self.selected_sheet,
            command=lambda _v: None,  # apply after loading
            width=200
        )
        self.sheet_menu.pack(side="right")

        col_row = ctk.CTkFrame(load_card, fg_color="transparent")
        col_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(col_row, text="Column:", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.selected_ycol = tk.StringVar(value="-")
        self.ycol_menu = ctk.CTkOptionMenu(col_row, values=["-"], variable=self.selected_ycol, width=200,
                                           command=lambda _v: None)
        self.ycol_menu.pack(side="right")

        self.btn_load = ctk.CTkButton(
            load_card, text="Load & Plot", command=self.load_data_from_ui,
            corner_radius=_pal.R_CARD, height=30, fg_color=self.accent_blue,
            hover_color=_pal.ACCENT_HOV, font=_pal.font(11),
            state="disabled"
        )
        self.btn_load.pack(pady=(0, 16), padx=16, fill="x")

        # ---- Analysis Card ----
        ana_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        ana_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(ana_card, text="Analysis Settings", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        # Bandgap type
        bg_row = ctk.CTkFrame(ana_card, fg_color="transparent")
        bg_row.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(bg_row, text="Mode", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")

        self.mode_btn = ctk.CTkSegmentedButton(
            bg_row, values=["Direct", "Indirect"],
            command=self.on_mode_change,
            font=_pal.font(12),
            width=200
        )
        self.mode_btn.set("Direct")
        self.mode_btn.pack(side="right")

        # y-axis basis: Absorbance (A) or absorption coefficient (alpha).
        # Tauc: (alpha*hv)^n with alpha = 2.303*A/d. A and alpha differ only by a
        # constant (2.303/d), so the x-intercept (Eg) is identical; only the
        # y-axis scale/label changes. Enter thickness (nm) to report alpha.
        basis_row = ctk.CTkFrame(ana_card, fg_color="transparent")
        basis_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(basis_row, text="Y basis", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.tauc_basis = ctk.CTkSegmentedButton(
            basis_row, values=["A", "alpha"], command=self._on_basis_change,
            font=_pal.font(12), width=140)
        self.tauc_basis.set("A")
        self.tauc_basis.pack(side="right")

        thick_row = ctk.CTkFrame(ana_card, fg_color="transparent")
        thick_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(thick_row, text="Film thickness (nm)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_thickness = ctk.CTkEntry(thick_row, width=80, height=26,
                                            font=_pal.font(12),
                                            placeholder_text="e.g. 100")
        self.entry_thickness.pack(side="right")

        # Expected Eg + Auto Fit (auto-detect the steepest linear region near Eg)
        eg_row = ctk.CTkFrame(ana_card, fg_color="transparent")
        eg_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(eg_row, text="Expected Eg (eV)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_expected_eg = ctk.CTkEntry(eg_row, width=70, height=26,
                                              font=_pal.font(12),
                                              placeholder_text="optional")
        self.entry_expected_eg.pack(side="right")
        ctk.CTkButton(ana_card, text="Auto fit (expected Eg)", height=28,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      font=_pal.font(13, "bold"), corner_radius=_pal.R_PILL,
                      command=self.auto_fit_expected, text_color=_pal.TXT).pack(fill="x", padx=16, pady=(0, 10))

        # X range
        xr_row = ctk.CTkFrame(ana_card, fg_color="transparent")
        xr_row.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkLabel(xr_row, text="X (eV)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")

        x_inputs = ctk.CTkFrame(xr_row, fg_color="transparent")
        x_inputs.pack(side="right")

        self.entry_xmin = ctk.CTkEntry(x_inputs, width=70, height=26, font=_pal.font(12),
                                       textvariable=self.x_min)
        self.entry_xmin.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(x_inputs, text="~", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_xmax = ctk.CTkEntry(x_inputs, width=70, height=26, font=_pal.font(12),
                                       textvariable=self.x_max)
        self.entry_xmax.pack(side="left", padx=(6, 0))

        self.btn_apply_view = ctk.CTkButton(
            ana_card, text="Apply View Range", command=self.apply_view_range,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_apply_view.pack(pady=(0, 16), padx=16, fill="x")\
        
        

        

        # ---- Actions Card ----
        act_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        act_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(act_card, text="Actions", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.btn_export_excel = ctk.CTkButton(
            act_card, text="Save Excel", command=self.save_to_excel,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_export_excel.pack(padx=16, pady=4, fill="x")

        self.btn_export_origin = ctk.CTkButton(
            act_card, text="Send to Origin", command=self.send_to_origin,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_export_origin.pack(padx=16, pady=(0, 16), fill="x")

        # ---- Status Card ----
        status_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        status_card.pack(pady=(8, 16), padx=12, fill="x")

        ctk.CTkLabel(status_card, text="Status", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.progress_bar = ctk.CTkProgressBar(status_card, height=6, corner_radius=3,
                                               progress_color=self.accent_green)
        self.progress_bar.set(0)
        self.progress_bar.pack(padx=16, fill="x")

        self.lbl_status = ctk.CTkLabel(status_card, text="Ready",
                                       text_color=self.text_secondary, font=_pal.font(12))
        self.lbl_status.pack(pady=(8, 16))

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=_pal.BG_WINDOW)
        self.center_frame.grid(row=0, column=1, sticky="nsew")

        # Vertical split: top(graph) : bottom(spare) = 1:1 -> graph gets half height
        self.center_frame.grid_rowconfigure(0, weight=1)  # plot
        self.center_frame.grid_rowconfigure(1, weight=1)  # bottom empty / future panel
        self.center_frame.grid_columnconfigure(0, weight=1)

        # --------- TOP: Plot container (height ~ 50%) ----------
        plot_container = ctk.CTkFrame(self.center_frame, corner_radius=_pal.R_CARD, fg_color=_pal.BG_CARD)
        plot_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        plot_container.grid_rowconfigure(0, weight=1)
        plot_container.grid_columnconfigure(0, weight=1)

        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=_pal.BG_CARD)
        self.ax_abs = self.fig.add_subplot(1, 2, 1)
        self.ax_tauc = self.fig.add_subplot(1, 2, 2)
        self._style_axes(self.ax_abs)
        self._style_axes(self.ax_tauc)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_container)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        # JV_Analysis.exe-style conveniences: wheel zoom (Ctrl=X, Shift=Y) and
        # right-click menu. (No drag-pan: left-drag is the Tauc fit selector.)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas)
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")

        self.ax_abs.text(0.5, 0.5, "Load Excel to preview",
                        ha="center", va="center", color=_pal.BORDER_HI,
                        transform=self.ax_abs.transAxes, fontsize=14)
        self.canvas.draw()

        # --------- BOTTOM: result table ----------
        self.center_frame.grid_rowconfigure(0, weight=3)
        self.center_frame.grid_rowconfigure(1, weight=0)
        bottom_panel = ctk.CTkFrame(self.center_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        bottom_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        ctk.CTkLabel(bottom_panel, text="Band-gap results", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(anchor="w", padx=12, pady=(8, 2))
        self.result_tree = _theme.kv_table(bottom_panel, height=7, key_width=260)
        self.result_tree.pack(fill="x", padx=12, pady=(0, 10))

    def _style_axes(self, ax):
        ax.set_facecolor(_pal.BG_CARD)
        ax.tick_params(colors=_pal.PLOT_TICK, labelsize=10)
        for spine in ax.spines.values():
            spine.set_color(_pal.BORDER)
        ax.xaxis.label.set_color(_pal.TXT)
        ax.yaxis.label.set_color(_pal.TXT)
        ax.title.set_color(_pal.TXT)

    def create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, width=330, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.right_frame.grid(row=0, column=2, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        # ---- Stats Card ----
        stats_card = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        stats_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats_card, text="Fit Summary", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.lbl_file = ctk.CTkLabel(stats_card, text="",
                                     text_color=self.accent_blue, font=_pal.font(12))
        self.lbl_file.pack(padx=16, anchor="w")

        grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(8, 16))

        self.lbl_eg = ctk.CTkLabel(grid, text="Eg: - eV", font=_pal.font(12, "bold"),
                                   text_color=self.accent_orange)
        self.lbl_eg.pack(anchor="w")

        self.lbl_r2 = ctk.CTkLabel(grid, text="R²: -", font=_pal.font(11),
                                   text_color=self.text_secondary)
        self.lbl_r2.pack(anchor="w", pady=(4, 0))

        self.lbl_mode = ctk.CTkLabel(grid, text="Mode: Direct", font=_pal.font(11),
                                     text_color=self.text_secondary)
        self.lbl_mode.pack(anchor="w", pady=(4, 0))

        self.lbl_fit_range = ctk.CTkLabel(grid, text="Fit: - ~ - eV", font=_pal.font(11),
                                          text_color=self.text_secondary)
        self.lbl_fit_range.pack(anchor="w", pady=(4, 0))

        # ---- Log Card ----
        log_card = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        log_card.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 16))
        log_card.grid_rowconfigure(0, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_card, text="Log", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.log_text = ctk.CTkTextbox(log_card, font=_pal.mono(11))
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        self.log_text.configure(state="disabled")

    # =====================
    # Logging / Status
    # =====================
    def log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, msg: str, progress: float | None = None):
        self.lbl_status.configure(text=msg)
        if progress is not None:
            self.progress_bar.set(progress)

    # =====================
    # Load & Plot
    # =====================
    def browse_excel(self):
        file_path = filedialog.askopenfilename(
            title="Select UV-Vis Excel",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if not file_path:
            return

        self.entry_file.delete(0, "end")
        self.entry_file.insert(0, file_path)
        self.target_file = Path(file_path)

        try:
            xls = pd.ExcelFile(file_path)
            sheets = xls.sheet_names
            if not sheets:
                raise ValueError("No sheets found")

            self.sheet_menu.configure(values=sheets)
            self.selected_sheet.set(sheets[0])

            self.btn_load.configure(state="normal")
            self.log(f"Selected file: {file_path}")
            self.set_status("File selected", 0)

        except Exception as e:
            messagebox.showerror("Error", f"Excel open error: {e}")
            self.btn_load.configure(state="disabled")

    def load_data_from_ui(self):
        if not self.target_file:
            messagebox.showwarning("Warning", "Select an Excel file first.")
            return

        sheet = self.selected_sheet.get()
        try:
            self.set_status("Loading...", 0.1)
            self.df = pd.read_excel(self.target_file, sheet_name=sheet)
            self.sheet_name = sheet

            # col0: wavelength (nm); Y: the chosen column (default: the first numeric one after it)
            cols = [str(c) for c in self.df.columns]
            self.df.columns = cols
            ycols = [c for c in cols[1:] if pd.to_numeric(self.df[c], errors="coerce").notna().sum() > 3]
            if not ycols:
                raise ValueError("No numeric absorbance column found after the wavelength column.")
            chosen = self.selected_ycol.get() if self.selected_ycol.get() in ycols else ycols[0]
            self.ycol_menu.configure(values=ycols)
            self.selected_ycol.set(chosen)
            self.raw_x = pd.to_numeric(self.df.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
            self.raw_y = pd.to_numeric(self.df[chosen], errors="coerce").to_numpy(dtype=float)
            ok = np.isfinite(self.raw_x) & np.isfinite(self.raw_y) & (self.raw_x > 0)
            self.raw_x, self.raw_y = self.raw_x[ok], self.raw_y[ok]

            self.hv = 1239.842 /self.raw_x
            self.absorbance = self.raw_y

            self.log(f"Loaded sheet: {sheet}, column: {chosen}")
            self.lbl_file.configure(text=f"{self.target_file.name} | {sheet} | {chosen}")

            self.init_plot()
            self.apply_view_range()  # set xlim based on entry
            self.set_status("Ready (Drag on Tauc to Fit)", 1.0)

            self.btn_apply_view.configure(state="normal")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {e}")
            self.set_status("Load failed", 0)

    def init_plot(self):
        # clear axes
        self.ax_abs.clear()
        self.ax_tauc.clear()
        self._style_axes(self.ax_abs)
        self._style_axes(self.ax_tauc)

        # sanitize/sort hv + absorbance
        hv = np.asarray(self.hv, dtype=float)
        ab = np.asarray(self.absorbance, dtype=float)
        raw_x = np.asarray(self.raw_x, dtype=float)
        raw_y = np.asarray(self.raw_y, dtype=float)

        mask = np.isfinite(hv) & np.isfinite(ab)
        hv = hv[mask]
        ab = ab[mask]
        idx = np.argsort(hv)
        hv = hv[idx]
        ab = ab[idx]

        self.hv = hv
        self.absorbance = ab
        self.raw_x = raw_x
        self.raw_y = raw_y

        # set data_state by mode
        mode = self.mode_btn.get()
        self.data_state = {"x": hv}
        self._recompute_tauc_y(mode)

        # Abs plot
        self.ax_abs.plot(self.raw_x, self.raw_y, linewidth=1.6)
        self.ax_abs.set_xlabel("Wavelength (nm)")
        self.ax_abs.set_ylabel("Absorbance")
        self.ax_abs.set_title("Absorption Spectrum")
        self.ax_abs.grid(True, linestyle="--", alpha=0.35)

        # Tauc scatter
        self.line_tauc, = self.ax_tauc.plot(
            self.data_state["x"], self.data_state["y"],
            "o", markersize=3.5, alpha=0.65
        )
        self.ax_tauc.set_xlabel("hν (eV)")
        self.ax_tauc.set_ylabel(self.data_state["y_label"])
        self.title_text = self.ax_tauc.set_title("Tauc plot (drag a range to fit)", color=_pal.PLOT_FG)
        self.ax_tauc.grid(True, linestyle="--", alpha=0.35)

        # fit visuals
        self.fit_line, = self.ax_tauc.plot([], [], linewidth=2.5)
        self.v1 = self.ax_tauc.axvline(np.nan, linestyle="--", alpha=0.7)
        self.v2 = self.ax_tauc.axvline(np.nan, linestyle="--", alpha=0.7)

        self.fit_result = None
        self._update_stats_panel(clear=True)

        # setup mpl widgets (radio/slider/span)
        self._setup_mpl_widgets()

        self.fig.tight_layout()
        self.canvas.draw()

        # enable export (after fit only)
        self.btn_export_excel.configure(state="disabled")
        self.btn_export_origin.configure(state="disabled")

    def _recompute_tauc_y(self, mode: str):
        # Tauc plot: (X*hv)^n where X is Absorbance A (default) or
        # absorption coefficient alpha = 2.303*A/d (d = film thickness).
        # Eg (x-intercept) is unchanged by the A<->alpha switch; only the
        # y-axis magnitude and label differ.
        hv = self.data_state["x"]
        A = self.absorbance

        basis = getattr(self, "tauc_basis", None)
        basis = basis.get() if basis is not None else "A"
        if basis == "alpha":
            d_nm = self._thickness_nm()
            if d_nm and d_nm > 0:
                d_cm = d_nm * 1e-7                      # nm -> cm
                X = 2.302585 * A / d_cm                 # alpha [1/cm]
                sym = r"\alpha"
            else:
                X, sym = A, "A"                          # no thickness -> fall back to A
        else:
            X, sym = A, "A"

        if mode == "Direct":
            y = (X * hv) ** 2
            y_label = r"$(%s \cdot h\nu)^2$" % sym
        else:
            y = (X * hv) ** 0.5
            y_label = r"$(%s \cdot h\nu)^{1/2}$" % sym

        self.data_state["y"] = y
        self.data_state["y_label"] = y_label

    def _thickness_nm(self):
        try:
            return float(self.entry_thickness.get())
        except (ValueError, AttributeError, TypeError):
            return None

    def _on_basis_change(self, _value=None):
        if self.data_state.get("x") is None:
            return
        self._recompute_tauc_y(self.mode_btn.get())
        self.line_tauc.set_ydata(self.data_state["y"])
        self.ax_tauc.set_ylabel(self.data_state["y_label"])
        self._autoscale_y()
        self.canvas.draw_idle()

    def _setup_mpl_widgets(self):
        # remove old widgets if exist (best effort)
        try:
            if self.radio is not None:
                self.radio.disconnect_events()
        except Exception:
            pass

        # clean old axes used by widgets
        # (matplotlib widgets live on extra axes; delete them if already exist)
        for ax in list(self.fig.axes):
            # keep only 2 main axes
            if ax not in (self.ax_abs, self.ax_tauc):
                try:
                    ax.remove()
                except Exception:
                    pass

        # Radio buttons (inside figure, top-left)
        #ax_radio = self.fig.add_axes([0.06, 0.86, 0.12, 0.11], facecolor="#F5F5F5")
        #self.radio = RadioButtons(ax_radio, ("Direct", "Indirect"))
        #self.radio.on_clicked(self._on_radio_clicked)

        # Slider (bottom)
        # ax_slider = self.fig.add_axes([0.22, 0.06, 0.60, 0.03])
        # x = self.data_state["x"]
        # xmin, xmax = float(np.nanmin(x)), float(np.nanmax(x))
        # init_min = max(xmin, float(self.x_min.get()))
        # init_max = min(xmax, float(self.x_max.get()))
        # if init_min >= init_max:
        #    init_min, init_max = xmin, xmax

        # self.x_slider = RangeSlider(
        #    ax=ax_slider,
        #    label="X View",
        #    valmin=xmin,
        #    valmax=xmax,
        #    valinit=(init_min, init_max)
        # )
        # self.x_slider.on_changed(self._on_slider_change)

        # SpanSelector (fit range)
        self.span = SpanSelector(
            self.ax_tauc, self._on_span_select, "horizontal",
            useblit=False, interactive=True,
            props=dict(alpha=0.20, facecolor="red")
        )

    

    # =====================
    # Events
    # =====================
    def on_mode_change(self, value):
        # segmented button callback
        self._on_mode_change_internal(value)

    def _on_radio_clicked(self, label):
        # radio buttons callback
        self.mode_btn.set(label)
        self._on_mode_change_internal(label)

    def _on_mode_change_internal(self, label):
        if self.hv is None or self.absorbance is None:
            return

        self._recompute_tauc_y(label)
        self.line_tauc.set_ydata(self.data_state["y"])
        self.ax_tauc.set_ylabel(self.data_state["y_label"])

        # reset fit visuals
        self.fit_line.set_data([], [])
        self.v1.set_xdata([np.nan, np.nan])
        self.v2.set_xdata([np.nan, np.nan])
        self.title_text.set_text("Tauc plot (drag a range to fit)")
        self.title_text.set_color(_pal.PLOT_FG)
        self.fit_result = None

        self._autoscale_y()
        self.canvas.draw_idle()

        self.btn_export_excel.configure(state="disabled")
        self.btn_export_origin.configure(state="disabled")

        self._update_stats_panel(clear=True)
        self.lbl_mode.configure(text=f"Mode: {label}")

    def apply_view_range(self):
        if self.hv is None:
            return
        try:
            xmin = float(self.x_min.get())
            xmax = float(self.x_max.get())
        except tk.TclError:
            return

        x = self.data_state["x"]
        xlo, xhi = float(np.nanmin(x)), float(np.nanmax(x))
        xmin = max(xlo, xmin)
        xmax = min(xhi, xmax)
        if xmin >= xmax:
            xmin, xmax = xlo, xhi

        self.ax_tauc.set_xlim(xmin, xmax)
        self._autoscale_y()
        self.canvas.draw_idle()

        # keep slider synced if exists
        if self.x_slider is not None:
            try:
                self.x_slider.set_val((xmin, xmax))
            except Exception:
                pass

    def _on_slider_change(self, val):
        self.ax_tauc.set_xlim(val[0], val[1])
        self._autoscale_y()
        self.canvas.draw_idle()

    def _autoscale_y(self):
        x = self.data_state["x"]
        y = self.data_state["y"]
        xmin, xmax = self.ax_tauc.get_xlim()
        vis = (x >= xmin) & (x <= xmax) & np.isfinite(y)
        if np.any(vis):
            ymax = float(np.nanmax(y[vis]))
            self.ax_tauc.set_ylim(0, 1.1 * ymax if ymax > 0 else 1.0)

    def auto_fit_expected(self):
        """Select the linear Tauc region automatically (abs_core.auto_linear_region):
        steepest locally linear stretch of the edge, grown while the slope stays
        above 60% of its maximum and trimmed to R^2 >= 0.98. The expected Eg,
        if given, restricts the search to +-0.6 eV around it."""
        if self.data_state.get("x") is None:
            messagebox.showwarning("Warning", "Load data first.")
            return
        txt = self.entry_expected_eg.get().strip()
        eg_exp = None
        if txt:
            try:
                eg_exp = float(txt)
            except ValueError:
                messagebox.showwarning("Warning", "Expected Eg must be a number (eV) or empty.")
                return
        x = np.asarray(self.data_state["x"], dtype=float)
        y = np.asarray(self.data_state["y"], dtype=float)
        reg = abs_core.auto_linear_region(x, y, expected_eg=eg_exp)
        if not np.isfinite(reg["Eg"]):
            messagebox.showwarning("Auto fit", "No linear edge region found. Check the transition type or the data range.")
            return
        self._on_span_select(reg["lo"], reg["hi"])
        if self.fit_result:
            self.log(f"[Auto fit] region {reg['lo']:.3f}-{reg['hi']:.3f} eV -> Eg = {self.fit_result['Eg']:.4f} eV "
                     f"(R² = {self.fit_result['R2']:.4f}, {reg['n_points']} points)")
            if eg_exp is not None and abs(self.fit_result["Eg"] - eg_exp) > 0.3:
                self.log("[Auto fit] differs from the expected value by more than 0.3 eV - check Direct/Indirect.")

    def _on_span_select(self, xmin, xmax):
        if xmin == xmax:
            return

        x = self.data_state["x"]
        y = self.data_state["y"]

        fitMin, fitMax = (min(xmin, xmax), max(xmin, xmax))
        sel = (x >= fitMin) & (x <= fitMax) & np.isfinite(y)

        if np.sum(sel) < 2:
            return

        try:
            m, b = np.polyfit(x[sel], y[sel], 1)
        except Exception:
            return
        if m == 0:
            return

        Eg = -b / m

        # R2
        yfit = m * x[sel] + b
        ss_res = float(np.sum((y[sel] - yfit) ** 2))
        ss_tot = float(np.sum((y[sel] - np.mean(y[sel])) ** 2))
        R2 = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

        xline = np.linspace(fitMin, fitMax, 200)
        self.fit_line.set_data(xline, m * xline + b)
        self.v1.set_xdata([fitMin, fitMin])
        self.v2.set_xdata([fitMax, fitMax])

        self.title_text.set_text(f"Tauc fit: Eg = {Eg:.4f} eV, R² = {R2:.4f}")
        self.title_text.set_color(_pal.PLOT_FG)

        lin = abs_core.linear_fit(x, y, fitMin, fitMax)
        urb = abs_core.urbach_from_absorbance(self.raw_x, self.raw_y - float(np.nanmin(self.raw_y)),
                                              float(Eg) - 0.25, float(Eg) - 0.02)
        eg_der = abs_core.derivative_bandgap(self.raw_x, self.raw_y)
        self.fit_result = {
            "Eg": float(Eg),
            "Eg_err": float(lin["Eg_err"]),
            "Eu_meV": float(urb["Eu_meV"]),
            "Eu_R2": float(urb["R2"]),
            "Eg_derivative": float(eg_der),
            "n_points": int(lin["n_points"]),
            "R2": float(R2) if np.isfinite(R2) else np.nan,
            "m": float(m),
            "b": float(b),
            "fitMin": float(fitMin),
            "fitMax": float(fitMax),
            "x_full": np.asarray(x, dtype=float),
            "y_full": np.asarray(y, dtype=float),
            "raw_x": np.asarray(self.raw_x, dtype=float),
            "raw_y": np.asarray(self.raw_y, dtype=float),
            "y_label": self.data_state["y_label"],
            "mode": self.mode_btn.get(),
            "tauc_xlim": tuple(self.ax_tauc.get_xlim()),
            "tauc_ylim": tuple(self.ax_tauc.get_ylim()),
        }

        self.canvas.draw_idle()
        self._update_stats_panel()
        self._update_result_table()

        self.btn_export_excel.configure(state="normal")
        self.btn_export_origin.configure(state="normal")

    def open_compare(self):
        """Several absorbance files side by side (automatic Tauc Eg, Urbach) with an overlay."""
        from scripts.common.compare_window import CompareWindow
        mode = "direct" if self.mode_btn.get() == "Direct" else "indirect"
        CompareWindow(self, "abs", options={"mode": mode, "thickness_nm": None})

    def _update_result_table(self):
        if not hasattr(self, "result_tree"):
            return
        r = self.fit_result
        if not r:
            _theme.fill_kv(self.result_tree, [("Drag a range on the Tauc plot or use Auto fit", "")])
            return
        basis = getattr(self, "tauc_basis", None)
        basis = basis.get() if basis is not None else "A"
        d_nm = self._thickness_nm()
        items = [("Transition", f"{r['mode']} (Tauc exponent {'2' if r['mode'] == 'Direct' else '1/2'})"),
                 ("Y basis", "alpha = 2.303 A / d" + (f", d = {d_nm:g} nm" if basis == "alpha" and d_nm else "") if basis == "alpha" and d_nm else "absorbance A"),
                 ("Eg, Tauc intercept (eV)", r["Eg"], ".4f"),
                 ("Standard error of Eg (eV)", r.get("Eg_err", float('nan')), ".4f"),
                 ("Linear region (eV)", f"{r['fitMin']:.3f} - {r['fitMax']:.3f}  ({r.get('n_points', 0)} points)"),
                 ("R² of the linear fit", r["R2"], ".4f"),
                 ("Eg, derivative dA/dE maximum (eV)", r.get("Eg_derivative", float('nan')), ".4f"),
                 ("Urbach energy below the edge (meV)", r.get("Eu_meV", float('nan')), ".1f"),
                 ("Urbach fit R²", r.get("Eu_R2", float('nan')), ".4f")]
        _theme.fill_kv(self.result_tree, items)

    def export_report(self):
        if not self.fit_result:
            messagebox.showwarning("Report", "Fit first.")
            return
        path = _report.ask_report_path(self, f"{self.target_file.stem if self.target_file else 'Abs'}_report.md")
        if not path:
            return
        r = self.fit_result
        table = {"Transition": r["mode"], "Eg Tauc (eV)": r["Eg"], "Eg standard error (eV)": r.get("Eg_err"),
                 "Linear region (eV)": f"{r['fitMin']:.3f}-{r['fitMax']:.3f}", "R2": r["R2"],
                 "Eg derivative (eV)": r.get("Eg_derivative"), "Urbach energy (meV)": r.get("Eu_meV"),
                 "Urbach R2": r.get("Eu_R2")}
        notes = ("Tauc: (alpha h nu)^(1/r) = B (h nu - Eg), r = 1/2 direct, 2 indirect; Eg is the x-intercept of the "
                 "straight line through the selected region. Urbach energy from ln A vs E just below the edge "
                 "(baseline = minimum absorbance subtracted). Derivative band gap = energy of maximum dA/dE.")
        try:
            _report.write_markdown_report(path, f"Absorbance / Tauc analysis: {self.target_file.name if self.target_file else ''}",
                                          [("Results", table)], figure=self.fig,
                                          inputs=[str(self.target_file)] if self.target_file else None, notes=notes)
            self.log(f"Report saved: {path}")
        except Exception as ex:
            messagebox.showerror("Report", str(ex))

    def _update_stats_panel(self, clear=False):
        if clear or not self.fit_result:
            self.lbl_eg.configure(text="Eg: - eV")
            self.lbl_r2.configure(text="R²: -")
            self.lbl_mode.configure(text=f"Mode: {self.mode_btn.get()}")
            self.lbl_fit_range.configure(text="Fit: - ~ - eV")
            if hasattr(self, "result_tree"):
                self._update_result_table()
            return

        r = self.fit_result
        err = f" ± {r['Eg_err']:.4f}" if np.isfinite(r.get("Eg_err", float("nan"))) else ""
        self.lbl_eg.configure(text=f"Eg: {r['Eg']:.4f}{err} eV")
        self.lbl_r2.configure(text=f"R²: {r['R2']:.4f}" if np.isfinite(r["R2"]) else "R²: -")
        self.lbl_mode.configure(text=f"Mode: {r['mode']}")
        self.lbl_fit_range.configure(text=f"Fit: {r['fitMin']:.3f} ~ {r['fitMax']:.3f} eV")

    # =====================
    # Export
    # =====================
    def save_to_excel(self):
        if not self.target_file or not self.fit_result:
            messagebox.showwarning("Warning", "Fit first.")
            return

        out_path = self.target_file.parent / f"{self.target_file.stem}_result.xlsx"
        res = self.fit_result

        df_result = pd.DataFrame([{
            "File": self.target_file.name,
            "Sheet": self.sheet_name,
            "Eg (eV)": res["Eg"],
            "R2": res["R2"],
            "Slope": res["m"],
            "Intercept": res["b"],
            "Bandgap Mode": res["mode"],
            "Fit Min (eV)": res["fitMin"],
            "Fit Max (eV)": res["fitMax"],
            "Eg std error (eV)": res.get("Eg_err"),
            "Eg derivative (eV)": res.get("Eg_derivative"),
            "Urbach energy (meV)": res.get("Eu_meV"),
            "Urbach R2": res.get("Eu_R2"),
        }])

        df_uvvis = pd.DataFrame({
            "Wavelength (nm)": res["raw_x"],
            "Absorbance": res["raw_y"],
        })

        # export visible tauc range only + fit line in same sheet (like your code)
        xmin, xmax = self.ax_tauc.get_xlim()
        x_full = res["x_full"]
        y_full = res["y_full"]

        vis = np.isfinite(x_full) & np.isfinite(y_full) & (x_full >= xmin) & (x_full <= xmax)
        x_vis = x_full[vis]
        y_vis = y_full[vis]

        fit_x = np.linspace(res["fitMin"], res["fitMax"], 200)
        fit_y = res["m"] * fit_x + res["b"]

        df_tauc = pd.DataFrame({"Energy (eV)": x_vis, "Tauc Value": y_vis})
        df_fit = pd.DataFrame({"Fit X (eV)": fit_x, "Fit Y": fit_y})
        df_tauc_fit = pd.concat([df_tauc.reset_index(drop=True), df_fit.reset_index(drop=True)], axis=1)

        try:
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                df_result.to_excel(writer, sheet_name="Result", index=False)
                df_uvvis.to_excel(writer, sheet_name="UV-Vis", index=False)
                df_tauc_fit.to_excel(writer, sheet_name="Tauc_Data", index=False)
            from scripts.common.provenance import write_sidecar
            write_sidecar(str(out_path), "Absorbance", inputs=[str(self.target_file)],
                          parameters={"sheet": self.sheet_name, "column": self.selected_ycol.get(), "mode": res["mode"],
                                      "basis": self.tauc_basis.get(), "thickness_nm": self._thickness_nm(),
                                      "fit_range_eV": [res["fitMin"], res["fitMax"]]},
                          results={k: v for k, v in res.items() if not hasattr(v, "__len__") or isinstance(v, str)})

            self.log(f"Saved Excel: {out_path}")
            messagebox.showinfo("Success", f"Saved:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Excel Error", str(e))

    def send_to_origin(self):
        if not WIN32COM_AVAILABLE:
            messagebox.showerror("Error", "pywin32 not installed. (pip install pywin32)")
            return
        if not self.fit_result:
            messagebox.showwarning("Warning", "Fit first.")
            return

        # origin path: try passed, else user should set
        origin_path = self.passed_origin_path or ""

        # (path input UI omitted in this draft - add an Entry to the left card if needed)
        if not origin_path:
            # try to auto-detect any installed Origin version
            import glob as _glob
            for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                         os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")):
                hits = sorted(_glob.glob(os.path.join(base, "OriginLab", "Origin*", "Origin64.exe")), reverse=True)
                if hits:
                    origin_path = hits[0]
                    break
            else:
                origin_path = r"C:\Program Files\OriginLab\Origin2024\Origin64.exe"

        res = self.fit_result

        try:
            # connect
            origin = None
            try:
                origin = win32com.client.Dispatch("Origin.ApplicationSI")
                origin.Visible = 1
            except Exception:
                if os.path.exists(origin_path):
                    subprocess.Popen([origin_path])
                    time.sleep(8)
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1

            if origin is None:
                raise RuntimeError("Could not connect to Origin.")

            # UI limits
            xmin, xmax = self.ax_tauc.get_xlim()
            ymin, ymax = self.ax_tauc.get_ylim()

            # UV
            uv_x = np.asarray(res["raw_x"], dtype=float)
            uv_y = np.asarray(res["raw_y"], dtype=float)

            # Tauc visible
            x_full = np.asarray(res["x_full"], dtype=float)
            y_full = np.asarray(res["y_full"], dtype=float)
            vis = np.isfinite(x_full) & np.isfinite(y_full) & (x_full >= xmin) & (x_full <= xmax)
            tauc_x = x_full[vis]
            tauc_y = y_full[vis]

            m = float(res["m"])
            b = float(res["b"])
            fit_y_full = (m * tauc_x + b).astype(float)

            # Workbook UV
            wb_uv = origin.CreatePage(2, f"UV_{(self.sheet_name or 'S')}"[:10], "Origin")
            origin.Execute(f"page.active$={wb_uv};")
            origin.Execute("wks.ncols=2;")
            origin.Execute('wks.col1.type=4; wks.col2.type=1;')
            origin.Execute('wks.col1.lname$="Wavelength"; wks.col1.units$="nm";')
            origin.Execute('wks.col2.lname$="Absorbance"; wks.col2.units$="a.u.";')
            origin.PutWorksheet(f"[{wb_uv}]Sheet1", uv_x.tolist(), 0, 0)
            origin.PutWorksheet(f"[{wb_uv}]Sheet1", uv_y.tolist(), 0, 1)

            # Workbook Tauc
            wb_tauc = origin.CreatePage(2, f"Tauc_{(self.sheet_name or 'S')}"[:10], "Origin")
            origin.Execute(f"page.active$={wb_tauc};")
            origin.Execute("wks.ncols=3;")
            origin.Execute('wks.col1.type=4; wks.col2.type=1; wks.col3.type=1;')
            origin.Execute('wks.col1.lname$="Energy"; wks.col1.units$="eV";')
            origin.Execute('wks.col2.lname$="Tauc"; wks.col2.units$="a.u.";')
            origin.Execute('wks.col3.lname$="FitY"; wks.col3.units$="a.u.";')
            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", tauc_x.tolist(), 0, 0)
            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", tauc_y.tolist(), 0, 1)
            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", fit_y_full.tolist(), 0, 2)

            # Worksheets (UV + Tauc) are populated above.
            # Origin graph styling is optional and will be removed in a future
            # version (Origin export is a convenience, not part of the physics).
            self.set_status("Sent to Origin (UV + Tauc worksheets).", 1.0)
            messagebox.showinfo("Origin", "Data sent to Origin (UV + Tauc worksheets).")
        except Exception as e:
            messagebox.showerror("Origin Error", str(e))


def main():
    root = ctk.CTk()
    root.withdraw()
    AnalysisWindow(root, "", "")
    root.mainloop()


if __name__ == "__main__":
    main()
