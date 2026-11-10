# run_eqe.py - EQE Analyzer (ABS-style UI) + EQE_core features integrated
# - Left: file/sheet load, view controls (no slider), derivative smoothing, actions
# - Center: 3 plots (EQE + Integrated on right Y, ln(EQE), derivative)
# - Right: summary + log
# - Exports: Excel (Result / EQE_Data / Urbach_Data), Origin (Workbook + Graphs)
#
# Requirements:
#   pip install numpy pandas matplotlib scipy openpyxl customtkinter pywin32
#
# Notes:
# - "Integrated" curve in EQE plot uses your earlier D = wl * EQE_frac * AM15 / 1240 / 1000 definition,
#   then cumulative trapezoid over wavelength.
# - "calculate_jsc" uses photon-flux method (physical Jsc in mA/cm^2).
#
import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import numpy as np
import pandas as pd
import customtkinter as ctk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import SpanSelector
from matplotlib.gridspec import GridSpec

from scipy.signal import savgol_filter
from scipy.constants import h, c, e
from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report

# Win32com check (Origin) - use JV's implementation for consistency
try:
    from scripts.JV import jv_core
except ImportError:
    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)
    from scripts.JV import jv_core
WIN32COM_AVAILABLE = jv_core.WIN32COM_AVAILABLE
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None



# ============================================================
# Origin path auto-find (EQE_core style)
# ============================================================
def find_origin_path():
    search_dirs = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    ]

    for base_dir in search_dirs:
        origin_lab_dir = os.path.join(base_dir, "OriginLab")
        if os.path.exists(origin_lab_dir):
            try:
                subdirs = [d for d in os.listdir(origin_lab_dir) if d.lower().startswith("origin")]
                subdirs.sort(reverse=True)  # latest first
                for d in subdirs:
                    exe_path = os.path.join(origin_lab_dir, d, "Origin64.exe")
                    if os.path.exists(exe_path):
                        return exe_path
            except Exception:
                continue

    return r"C:\Program Files\OriginLab\Origin2024\Origin64.exe"


# ============================================================
# Physics lives in eqe_core (GUI-free, tested); re-exported here so older
# callers that imported these names from run_eqe keep working.
# ============================================================
try:
    from scripts.EQE import eqe_core
except ImportError:
    from . import eqe_core  # type: ignore

get_am15g_spectrum = eqe_core.get_am15g_spectrum
compute_am15_integrals = eqe_core.compute_am15_integrals
calculate_jsc = eqe_core.calculate_jsc
_eqe_to_fraction = eqe_core.eqe_to_fraction


# ============================================================
# UI (ABS-style) + EQE_core features
# ============================================================
class EQEWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("EQE Analyzer")
        self.geometry("1500x920")

        self.origin_path = origin_path or find_origin_path()
        self.api_key = api_key  # stored for potential future use

        # colors
        self.card_bg = _pal.BG_CARD
        self.accent_blue = _pal.ACCENT
        self.accent_orange = _pal.ORANGE
        self.accent_green = _pal.GREEN
        self.text_primary = _pal.TXT
        self.text_secondary = _pal.TXT_SUB

        # state
        self.target_file: Path | None = None
        self.sheet_name: str | None = None
        self.df: pd.DataFrame | None = None

        self.raw_x = None  # wavelength (nm)
        self.raw_y = None  # EQE (%)
        self.hv = None     # energy (eV) (filtered, sorted)
        self.ln_eqe = None # ln(EQE) (filtered, sorted)
        self.hv_eqe = None # energy (eV) for EQE plot
        self.eqe_energy = None  # EQE (%) sorted by energy
        self.eg_der_eqe = np.nan
        self.eqe_span = None  # (min, max) selected on EQE vs Energy

        # extra for integrated curve
        self.am15_interp = None
        self.D_int = None
        self.E_cum = None

        self.jsc_val = None
        self.fit_result = None
        self.span = None

        # view inputs
        self.wl_max = tk.DoubleVar(value=800.0)
        self.e_min = tk.DoubleVar(value=1.40)
        self.e_max = tk.DoubleVar(value=2.20)
        self.sg_window = tk.IntVar(value=11)

        # Origin path entry
        self.origin_path_var = tk.StringVar(value=self.origin_path)

        # sheet menu var
        self.selected_sheet = tk.StringVar(value="-")

        # layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._create_left_panel()
        self._create_center_panel()
        self._create_right_panel()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.attributes("-topmost", True)
        self.after(100, lambda: self.attributes("-topmost", False))

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "EQE Analysis", {
                    "open": ("Open file", self._browse_file),
                    "run": ("Load and plot", self._load_and_plot),
                    "extra": [("Compare files", self.open_compare)],
                    "fit": ("Auto fit", self._auto_fit_all),
                    "excel": ("Excel", self._save_excel),
                    "png": True,
                    "report": ("Report", self._export_report),
                    "origin": ("Origin", self._send_origin)
                }, hints="Drag on ln(EQE): Urbach fit  |  Drag on EQE vs E: derivative band gap  |  "
                         "Wheel: zoom (Ctrl = x, Shift = y)  |  Right-click: plot menu")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

    # ---------------- panels ----------------
    def _create_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=340, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        # Load card
        load_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        row = ctk.CTkFrame(load_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_file = ctk.CTkEntry(row, placeholder_text="Select EQE Excel/CSV...", height=28)
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text="...", width=40, height=28,
                      command=self._browse_file, corner_radius=_pal.R_PILL).pack(side="right")

        sheet_row = ctk.CTkFrame(load_card, fg_color="transparent")
        sheet_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(sheet_row, text="Sheet:", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")

        self.sheet_menu = ctk.CTkOptionMenu(
            sheet_row, values=["-"], variable=self.selected_sheet,
            command=lambda _v: None, width=210
        )
        self.sheet_menu.pack(side="right")

        self.btn_load = ctk.CTkButton(
            load_card, text="Load & Plot", command=self._load_and_plot,
            corner_radius=_pal.R_CARD, height=30, fg_color=self.accent_blue,
            hover_color=_pal.ACCENT_HOV, font=_pal.font(11),
            state="disabled"
        )
        self.btn_load.pack(pady=(0, 16), padx=16, fill="x")

        # View card
        set_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        set_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(set_card, text="View / Derivative", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        wl_row = ctk.CTkFrame(set_card, fg_color="transparent")
        wl_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(wl_row, text="WL max (nm)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_wlmax = ctk.CTkEntry(wl_row, width=130, height=26,
                                        font=_pal.font(12), textvariable=self.wl_max)
        self.entry_wlmax.pack(side="right")

        e_row = ctk.CTkFrame(set_card, fg_color="transparent")
        e_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(e_row, text="E view (eV)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")

        e_inputs = ctk.CTkFrame(e_row, fg_color="transparent")
        e_inputs.pack(side="right")
        self.entry_emin = ctk.CTkEntry(e_inputs, width=70, height=26,
                                       font=_pal.font(12), textvariable=self.e_min)
        self.entry_emin.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(e_inputs, text="~", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_emax = ctk.CTkEntry(e_inputs, width=70, height=26,
                                       font=_pal.font(12), textvariable=self.e_max)
        self.entry_emax.pack(side="left", padx=(6, 0))

        sg_row = ctk.CTkFrame(set_card, fg_color="transparent")
        sg_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(sg_row, text="Smooth window", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_sg = ctk.CTkEntry(sg_row, width=130, height=26,
                                     font=_pal.font(12), textvariable=self.sg_window)
        self.entry_sg.pack(side="right")

        self.btn_apply = ctk.CTkButton(
            set_card, text="Apply View", command=self._apply_view,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_apply.pack(pady=(0, 8), padx=16, fill="x")

        # One-click auto fit: auto-select absorption edge (derivative Eg) + Urbach tail (ln EQE)
        self.btn_autofit = ctk.CTkButton(
            set_card, text="Auto fit (Eg and Urbach)",
            command=self._auto_fit_all, height=28,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            font=_pal.font(13, "bold"), corner_radius=_pal.R_PILL, state="disabled", text_color=_pal.TXT)
        self.btn_autofit.pack(pady=(0, 16), padx=16, fill="x")

        # Origin card
        origin_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        origin_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(origin_card, text="Origin", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        op_row = ctk.CTkFrame(origin_card, fg_color="transparent")
        op_row.pack(fill="x", padx=16, pady=(0, 12))
        self.entry_origin = ctk.CTkEntry(op_row, height=28, textvariable=self.origin_path_var)
        self.entry_origin.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(op_row, text="Browse", width=80, height=28, corner_radius=_pal.R_PILL,
                      command=self._browse_origin).pack(side="right")

        # Actions card
        act_card = ctk.CTkFrame(self.left_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        act_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(act_card, text="Actions", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.btn_excel = ctk.CTkButton(
            act_card, text="Save Excel", command=self._save_excel,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_excel.pack(padx=16, pady=4, fill="x")

        self.btn_origin = ctk.CTkButton(
            act_card, text="Send to Origin", command=self._send_origin,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
            corner_radius=_pal.R_PILL, height=28, font=_pal.font(11),
            state="disabled", text_color=_pal.TXT)
        self.btn_origin.pack(padx=16, pady=(0, 16), fill="x")

    def _create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=_pal.BG_WINDOW)
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(0, weight=1)
        self.center_frame.grid_rowconfigure(1, weight=1)  # bottom placeholder
        self.center_frame.grid_columnconfigure(0, weight=1)

        # ---- plot container (top) ----
        plot_container = ctk.CTkFrame(self.center_frame, corner_radius=_pal.R_CARD, fg_color=_pal.BG_CARD)
        plot_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        plot_container.grid_rowconfigure(0, weight=1)
        plot_container.grid_columnconfigure(0, weight=1)

        # ---- Figure + GridSpec (2x2, use 3) ----
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=_pal.BG_CARD)

        gs = self.fig.add_gridspec(
            2, 2,
            width_ratios=[1.0, 1.2],     # right (lnEQE) slightly wider
            height_ratios=[1.0, 1.0],    # top/bottom equal
            wspace=0.42, hspace=0.58        # room for the twin Jsc axis label and the titles below the x labels
        )

        # Top-left: EQE (large)
        self.ax_eqe = self.fig.add_subplot(gs[0, 0])

        # Top-right: lnEQE
        self.ax_ln = self.fig.add_subplot(gs[0, 1])

        # Bottom-right: Derivative (EQE vs Energy)
        self.ax_der = self.fig.add_subplot(gs[1, 1])

        # Bottom-left: EQE vs Energy (select range)
        self.ax_eqe_energy = self.fig.add_subplot(gs[1, 0])

        for ax in (self.ax_eqe, self.ax_ln, self.ax_der, self.ax_eqe_energy):
            self._style_axes(ax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_container)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        # JV_Analysis.exe-style conveniences: wheel zoom (Ctrl=X, Shift=Y) and
        # right-click menu. (No drag-pan here: left-drag is used by the fit
        # SpanSelectors.)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas)
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")

        # Initial guide text (on EQE axis only)
        self.ax_eqe.text(
            0.5, 0.5, "Load EQE file to preview",
            ha="center", va="center", color=_pal.BORDER_HI,
            transform=self.ax_eqe.transAxes, fontsize=14
        )
        self.canvas.draw()

        # ---- bottom panel: detailed-balance quantities ----
        self.center_frame.grid_rowconfigure(1, weight=0)
        bottom_panel = ctk.CTkFrame(self.center_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        bottom_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        bottom_panel.grid_columnconfigure(0, weight=1)
        bottom_panel.grid_columnconfigure(1, weight=1)
        head = ctk.CTkFrame(bottom_panel, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 2))
        ctk.CTkLabel(head, text="Band gap, Urbach tail and detailed balance", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(side="left")
        ctk.CTkButton(head, text="Recompute", width=90, height=24, fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(10),
                      corner_radius=_pal.R_PILL, command=self._update_detailed_balance).pack(side="right")
        ctk.CTkLabel(head, text="Measured Voc (V)", font=_pal.font(10), text_color=self.text_secondary
                     ).pack(side="right", padx=(0, 6))
        self.entry_voc = ctk.CTkEntry(head, width=70, height=24, font=_pal.font(10), fg_color=_pal.BG_CARD,
                                      border_color=_pal.BORDER, text_color=_pal.TXT, corner_radius=_pal.R_INPUT,
                                      placeholder_text="e.g. 1.10")
        self.entry_voc.pack(side="right", padx=(0, 10))
        ctk.CTkLabel(head, text="T (K)", font=_pal.font(10), text_color=self.text_secondary).pack(side="right", padx=(0, 6))
        self.entry_temp = ctk.CTkEntry(head, width=52, height=24, font=_pal.font(10), fg_color=_pal.BG_CARD,
                                       border_color=_pal.BORDER, text_color=_pal.TXT, corner_radius=_pal.R_INPUT)
        self.entry_temp.insert(0, "300")
        self.entry_temp.pack(side="right", padx=(0, 10))
        self.db_tree_left = _theme.kv_table(bottom_panel, height=8, key_width=230)
        self.db_tree_left.grid(row=1, column=0, sticky="nsew", padx=(12, 4), pady=(0, 10))
        self.db_tree_right = _theme.kv_table(bottom_panel, height=8, key_width=230)
        self.db_tree_right.grid(row=1, column=1, sticky="nsew", padx=(4, 12), pady=(0, 10))
        self.eqe_summary = None

    def _create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, width=360, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.right_frame.grid(row=0, column=2, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        stats = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        stats.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats, text="Summary", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.lbl_file = ctk.CTkLabel(stats, text="",
                                     text_color=self.accent_blue, font=_pal.font(12))
        self.lbl_file.pack(padx=16, anchor="w")

        grid = ctk.CTkFrame(stats, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(8, 16))

        self.lbl_jsc = ctk.CTkLabel(grid, text="Jsc: - mA/cm²", font=_pal.font(12, "bold"),
                                    text_color=self.accent_green)
        self.lbl_jsc.pack(anchor="w")

        self.lbl_eg_fit = ctk.CTkLabel(grid, text="Eg(Fit): - eV", font=_pal.font(11),
                                       text_color=self.text_secondary)
        self.lbl_eg_fit.pack(anchor="w", pady=(4, 0))

        self.lbl_eg_der = ctk.CTkLabel(grid, text="Eg(Deriv): - eV", font=_pal.font(11),
                                       text_color=self.text_secondary)
        self.lbl_eg_der.pack(anchor="w", pady=(4, 0))

        self.lbl_eg_rau = ctk.CTkLabel(grid, text="Eg(Rau, dEQE/dE): - eV", font=_pal.font(11),
                                       text_color=self.text_secondary)
        self.lbl_eg_rau.pack(anchor="w", pady=(4, 0))

        self.lbl_voc_rad = ctk.CTkLabel(grid, text="Voc,rad: - V", font=_pal.font(11),
                                        text_color=self.text_secondary)
        self.lbl_voc_rad.pack(anchor="w", pady=(4, 0))

        self.lbl_eu = ctk.CTkLabel(grid, text="Eu: - meV", font=_pal.font(11),
                                   text_color=self.text_secondary)
        self.lbl_eu.pack(anchor="w", pady=(4, 0))

        self.lbl_r2 = ctk.CTkLabel(grid, text="R²: -", font=_pal.font(11),
                                   text_color=self.text_secondary)
        self.lbl_r2.pack(anchor="w", pady=(4, 0))

        self.lbl_fit = ctk.CTkLabel(grid, text="Fit: - ~ - eV", font=_pal.font(11),
                                    text_color=self.text_secondary)
        self.lbl_fit.pack(anchor="w", pady=(4, 0))

        log = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 16))
        log.grid_rowconfigure(1, weight=1)
        log.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log, text="Log", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).grid(row=0, column=0, sticky="w",
                                                       padx=16, pady=(16, 8))

        self.log_text = ctk.CTkTextbox(log, font=_pal.mono(11))
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 16))
        self.log_text.configure(state="disabled")

    # ---------------- helpers ----------------
    def _style_axes(self, ax):
        ax.set_facecolor(_pal.BG_CARD)
        ax.tick_params(colors=_pal.PLOT_TICK, labelsize=10)
        for spine in ax.spines.values():
            spine.set_color(_pal.BORDER)
        ax.xaxis.label.set_color(_pal.TXT)
        ax.yaxis.label.set_color(_pal.TXT)
        ax.title.set_color(_pal.TXT)

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


    # ---------------- browse ----------------
    def _browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select EQE file",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Text", "*.csv *.tsv *.txt"), ("All", "*.*")]
        )
        if not file_path:
            return

        self.entry_file.delete(0, "end")
        self.entry_file.insert(0, file_path)
        self.target_file = Path(file_path)

        try:
            if self.target_file.suffix.lower() in [".xlsx", ".xls"]:
                engine = "xlrd" if self.target_file.suffix.lower() == ".xls" else None
                xls = pd.ExcelFile(self.target_file, engine=engine)
                sheets = xls.sheet_names
                if not sheets:
                    raise ValueError("No sheets found.")
                self.sheet_menu.configure(values=sheets)
                self.selected_sheet.set(sheets[0])
            else:
                self.sheet_menu.configure(values=["-"])
                self.selected_sheet.set("-")

            self.btn_load.configure(state="normal")
            self._log(f"Selected file: {file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Open error: {e}")
            self.btn_load.configure(state="disabled")

    def _browse_origin(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askopenfilename(
            title="Select Origin Executable",
            filetypes=[("Executable", "*.exe"), ("All", "*.*")]
        )
        root.destroy()
        if p:
            self.origin_path_var.set(p)
            self._log(f"Origin path set: {p}")

    # ---------------- load + plot ----------------
    def _load_and_plot(self):
        if not self.target_file:
            return

        try:
            if self.target_file.suffix.lower() in [".xlsx", ".xls"]:
                sh = self.selected_sheet.get()
                engine = "xlrd" if self.target_file.suffix.lower() == ".xls" else None
                self.df = pd.read_excel(self.target_file, sheet_name=sh, engine=engine)
                self.sheet_name = sh
            else:
                self.df = pd.read_csv(self.target_file, sep=None, engine="python")
                self.sheet_name = self.target_file.stem

            lam = self.df.iloc[:, 0].to_numpy(dtype=float)
            eqe = self.df.iloc[:, 1].to_numpy(dtype=float)

            self.raw_x = lam
            self.raw_y = eqe

            # energy for urbach: hv = 1240/lambda
            hv_all = 1239.842 /lam

            # ln(EQE): keep only positive
            mask = np.isfinite(hv_all) & np.isfinite(eqe) & (eqe > 0)
            hv = hv_all[mask]
            eqe_pos = eqe[mask]
            idx = np.argsort(hv)

            self.hv = hv[idx]
            self.ln_eqe = np.log(eqe_pos[idx])

            # EQE vs Energy (for derivative selector)
            eqe_all = np.asarray(self.raw_y, dtype=float)
            wl_all = np.asarray(self.raw_x, dtype=float)
            valid2 = np.isfinite(wl_all) & np.isfinite(eqe_all) & (wl_all > 0)
            hv_all = 1239.842 /wl_all[valid2]
            eqe_all = eqe_all[valid2]
            idx2 = np.argsort(hv_all)
            self.hv_eqe = hv_all[idx2]
            self.eqe_energy = eqe_all[idx2]
            self.eg_der_eqe = np.nan

            # integrated curve (right axis)
            self.am15_interp, self.D_int, self.E_cum = compute_am15_integrals(self.raw_x, self.raw_y)

            # physical Jsc
            self.jsc_val = float(calculate_jsc(self.raw_x, self.raw_y))

            self._plot_all()
            self._apply_view()
            self._update_detailed_balance()

            self.btn_apply.configure(state="normal")
            self.btn_autofit.configure(state="normal")
            self.lbl_file.configure(text=f"{self.target_file.name} | {self.sheet_name}")
            self._log(f"Loaded: {self.sheet_name} (rows={len(self.df)})")

        except Exception as e:
            messagebox.showerror("Load Error", f"{e}")

    def _plot_all(self):
        # clear axes
        for ax in (self.ax_eqe, self.ax_ln, self.ax_der, self.ax_eqe_energy):
            ax.clear()
            self._style_axes(ax)

        # ---- Plot 1: EQE + Integrated on right axis ----
        self.ax_eqe.plot(self.raw_x, self.raw_y, linewidth=1.6)
        self.ax_eqe.set_title("EQE Spectrum")
        self.ax_eqe.set_xlabel("Wavelength (nm)")
        self.ax_eqe.set_ylabel("EQE (%)")
        self.ax_eqe.grid(True, linestyle="--", alpha=0.35)

        # WL xlim
        try:
            wlmax = float(self.wl_max.get())
        except Exception:
            wlmax = float(np.nanmax(self.raw_x))
        self.ax_eqe.set_xlim(300, wlmax)

        # right axis integrated
        # remove old twin if exists
        try:
            if hasattr(self, "ax_eqe2") and self.ax_eqe2 is not None:
                self.ax_eqe2.remove()
        except Exception:
            pass

        self.ax_eqe2 = self.ax_eqe.twinx()
        self._style_axes(self.ax_eqe2)
        self.ax_eqe2.plot(self.raw_x, self.E_cum, linestyle="--", linewidth=1.5)
        self.ax_eqe2.set_ylabel(r"Integrated $J_{sc}$ (mA/cm$^2$)", rotation=270, labelpad=16)
        self.ax_eqe2.tick_params(axis="y", labelsize=9)

        # ---- Plot 2: ln(EQE) with span-fit ----
        self.ax_ln.plot(self.hv, self.ln_eqe, "o", markersize=3.5, alpha=0.65)
        self.ax_ln.set_title("ln EQE (drag a range to fit the Urbach tail)", color=_pal.PLOT_FG)
        self.ax_ln.set_xlabel("Energy (eV)")
        self.ax_ln.set_ylabel(r"$\ln(EQE)$")
        self.ax_ln.grid(True, linestyle="--", alpha=0.35)
        self.slope_text_ln = self.ax_ln.text(
            0.98, 0.05, "",
            transform=self.ax_ln.transAxes,
            ha="right", va="bottom", fontsize=9, color=_pal.PLOT_FG,
            bbox=dict(boxstyle="square,pad=0.25", fc=_pal.PLOT_AXES, ec=_pal.PLOT_SPINE, lw=0.6)
        )

        self.fit_line, = self.ax_ln.plot([], [], linewidth=2.5)
        self.v1 = self.ax_ln.axvline(np.nan, linestyle="--", alpha=0.7)
        self.v2 = self.ax_ln.axvline(np.nan, linestyle="--", alpha=0.7)

        # ---- Plot 3: derivative (empty until select) ----
        self.der_line, = self.ax_der.plot([], [], linewidth=1.8)
        self.ax_der.set_title("Derivative (selected range)")
        self.ax_der.set_xlabel("Energy (eV)")
        self.ax_der.set_ylabel(r"$d(EQE)/dE$")
        self.ax_der.grid(True, linestyle="--", alpha=0.35)

        self.peak_annot = self.ax_der.annotate(
            "", xy=(0, 0), xytext=(0, -20), textcoords="offset points",
            ha="center", va="top",
            fontsize=9, color=_pal.PLOT_FG,
            bbox=dict(boxstyle="square,pad=0.25", fc=_pal.PLOT_AXES, ec=_pal.PLOT_SPINE, lw=0.6),
            arrowprops=dict(arrowstyle="->", color=_pal.PLOT_SPINE, lw=0.8)
        )
        self.peak_annot.set_visible(False)
        self.eg_text_der = self.ax_der.text(
            0.98, 0.95, "",
            transform=self.ax_der.transAxes,
            ha="right", va="top", fontsize=9, color=_pal.PLOT_FG
        )

        # ---- Plot 4: EQE vs Energy (selector) ----
        if self.hv_eqe is not None and self.eqe_energy is not None:
            self.ax_eqe_energy.plot(self.hv_eqe, self.eqe_energy, linewidth=1.6)
        self.ax_eqe_energy.set_title("EQE vs Energy (select range)")
        self.ax_eqe_energy.set_xlabel("Energy (eV)")
        self.ax_eqe_energy.set_ylabel("EQE (%)")
        self.ax_eqe_energy.grid(True, linestyle="--", alpha=0.35)

        # summary initial
        self.fit_result = None
        self._update_summary(clear=True)

        self.btn_excel.configure(state="disabled")
        self.btn_origin.configure(state="disabled")

        # span selector (ln(EQE))
        if self.span is not None:
            try:
                self.span.disconnect_events()
            except Exception:
                pass

        self.span = SpanSelector(
            self.ax_ln, self._on_span,
            "horizontal", useblit=False, interactive=True,
            props=dict(alpha=0.20, facecolor="red")
        )

        # span selector (EQE vs Energy)
        if hasattr(self, "span_eqe") and self.span_eqe is not None:
            try:
                self.span_eqe.disconnect_events()
            except Exception:
                pass

        self.span_eqe = SpanSelector(
            self.ax_eqe_energy, self._on_span_eqe_energy,
            "horizontal", useblit=False, interactive=True,
            props=dict(alpha=0.20, facecolor="orange")
        )

        # Layout: avoid tight_layout issues in Tk embedding
        self.fig.subplots_adjust(left=0.07, right=0.97, top=0.93, bottom=0.09, wspace=0.42, hspace=0.58)
        self.canvas.draw()

    def _apply_view(self):
        if self.hv is None:
            return

        # Energy view range
        try:
            emin = float(self.e_min.get())
            emax = float(self.e_max.get())
        except Exception:
            return

        xlo, xhi = float(np.nanmin(self.hv)), float(np.nanmax(self.hv))
        emin = max(xlo, emin)
        emax = min(xhi, emax)
        if emin >= emax:
            emin, emax = xlo, xhi

        self.ax_ln.set_xlim(emin, emax)
        self.ax_der.set_xlim(emin, emax)
        self.ax_eqe_energy.set_xlim(emin, emax)
        self._autoscale_ln()

        # WL max
        try:
            wlmax = float(self.wl_max.get())
            self.ax_eqe.set_xlim(300, wlmax)
        except Exception:
            pass

        self.canvas.draw_idle()

    def _autoscale_ln(self):
        xmin, xmax = self.ax_ln.get_xlim()
        vis = (self.hv >= xmin) & (self.hv <= xmax) & np.isfinite(self.ln_eqe)
        if np.any(vis):
            ymin = float(np.nanmin(self.ln_eqe[vis]))
            ymax = float(np.nanmax(self.ln_eqe[vis]))
            margin = (ymax - ymin) * 0.1 if ymax > ymin else 1.0
            self.ax_ln.set_ylim(ymin - margin, ymax + margin)

    def _compute_eqe_derivative(self, x_energy, y_eqe, fit_min, fit_max):
        """Compute d(EQE)/dE within selected range (Origin-like, no smoothing)."""
        if x_energy is None or y_eqe is None:
            return np.asarray([]), np.asarray([]), np.nan, np.nan

        sel = (x_energy >= fit_min) & (x_energy <= fit_max) & np.isfinite(y_eqe)
        if np.sum(sel) < 3:
            return np.asarray([]), np.asarray([]), np.nan, np.nan

        x_sel = np.asarray(x_energy[sel], dtype=float)
        y_sel = np.asarray(y_eqe[sel], dtype=float)
        if len(x_sel) < 3:
            return np.asarray([]), np.asarray([]), np.nan, np.nan

        # sort by energy and remove duplicate x by averaging (stable derivative)
        order = np.argsort(x_sel)
        x_sel = x_sel[order]
        y_sel = y_sel[order]
        x_unique, inv = np.unique(x_sel, return_inverse=True)
        if len(x_unique) != len(x_sel):
            sums = np.bincount(inv, weights=y_sel)
            counts = np.bincount(inv)
            y_sel = sums / np.maximum(counts, 1)
            x_sel = x_unique

        if len(x_sel) < 3:
            return np.asarray([]), np.asarray([]), np.nan, np.nan

        # Origin differentiate (no smoothing)
        dy = np.gradient(y_sel, x_sel)
        idx_max = int(np.argmax(dy))
        peak_x = float(x_sel[idx_max])
        peak_y = float(dy[idx_max])
        return x_sel, dy, peak_x, peak_y

    # ---------------- EQE(E) span for derivative ----------------
    def _on_span_eqe_energy(self, xmin, xmax):
        if xmin == xmax or self.hv_eqe is None or self.eqe_energy is None:
            return

        fitMin, fitMax = (min(xmin, xmax), max(xmin, xmax))
        self.eqe_span = (float(fitMin), float(fitMax))
        x_u, dy, peak_x, peak_y = self._compute_eqe_derivative(self.hv_eqe, self.eqe_energy, fitMin, fitMax)
        if x_u.size == 0:
            self._log("Derivative: not enough points in selection.")
            self.der_line.set_data([], [])
            self.peak_annot.set_visible(False)
            self.canvas.draw_idle()
            return

        self.eg_der_eqe = peak_x
        self.der_line.set_data(x_u, dy)
        self.ax_der.relim()
        self.ax_der.autoscale_view()

        self.peak_annot.set_text(f"Peak: {peak_x:.3f} eV")
        self.peak_annot.xy = (peak_x, peak_y)
        self.peak_annot.set_visible(True)
        if hasattr(self, "eg_text_der"):
            self.eg_text_der.set_text(f"Eg (Deriv): {peak_x:.3f} eV")

        # update summary label if available
        if hasattr(self, "lbl_eg_der"):
            self.lbl_eg_der.configure(
                text=f"Eg(Deriv): {self.eg_der_eqe:.3f} eV"
                if np.isfinite(self.eg_der_eqe) else "Eg(Deriv): - eV"
            )

        self.canvas.draw_idle()

    # ---------------- fit callback ----------------
    def _auto_fit_all(self):
        """Auto-detect the absorption edge and Urbach tail ranges and call the existing fit handlers.
        Physics: Eg(deriv) = location of max|dEQE/dE|; the Urbach region is the exponential tail below the edge."""
        if self.hv_eqe is None or self.eqe_energy is None:
            self._log("AutoFit: Load data first.")
            return
        hv = np.asarray(self.hv_eqe, dtype=float)
        eqe = np.asarray(self.eqe_energy, dtype=float)
        fin = np.isfinite(hv) & np.isfinite(eqe)
        hv, eqe = hv[fin], eqe[fin]
        if len(hv) < 10:
            self._log("AutoFit: not enough data points.")
            return

        # 1) Absorption edge: the half-maximum window of P(E) = dEQE/dE (Rau et al. 2017)
        rau = eqe_core.bandgap_rau(hv, eqe)
        if np.isfinite(rau["E_lo"]) and rau["E_hi"] > rau["E_lo"]:
            lo_e, hi_e = rau["E_lo"] - 0.05, rau["E_hi"] + 0.05
        else:
            e0 = eqe_core.bandgap_inflection(hv, eqe)
            lo_e, hi_e = e0 - 0.15, e0 + 0.15
        self._log(f"Auto fit: edge window [{lo_e:.3f}, {hi_e:.3f}] eV; Eg(Rau) = {rau['Eg']:.3f} eV, "
                  f"sigma = {1000 * rau['sigma']:.0f} meV")
        self._on_span_eqe_energy(lo_e, hi_e)

        # 2) Urbach tail: exponential region below the edge (EQE between 1% and 30% of its maximum)
        try:
            lo, hi = eqe_core.auto_urbach_window(hv, eqe)
            if not np.isfinite(lo):
                e0 = rau["E_inflection"] if np.isfinite(rau["E_inflection"]) else eqe_core.bandgap_inflection(hv, eqe)
                lo, hi = e0 - 0.25, e0 - 0.03
            self._log(f"Auto fit: Urbach range [{lo:.3f}, {hi:.3f}] eV")
            self._on_span(lo, hi)
        except Exception as ex:
            self._log(f"Auto fit (Urbach) failed: {ex}")
        self._update_detailed_balance()

    def _on_span(self, xmin, xmax):
        if xmin == xmax:
            return

        x = self.hv
        y = self.ln_eqe

        fitMin, fitMax = (min(xmin, xmax), max(xmin, xmax))
        sel = (x >= fitMin) & (x <= fitMax) & np.isfinite(y)
        if np.sum(sel) < 2:
            self._log("Fit: not enough points in selection.")
            return

        try:
            m, b = np.polyfit(x[sel], y[sel], 1)
        except Exception:
            return
        if m == 0:
            return

        # Eu (meV)
        Eu_meV = (1.0 / abs(m)) * 1000.0

        # Eg from fit: intersect with max ln(EQE)
        max_log = float(np.nanmax(y))
        Eg_fit = (max_log - b) / m

        # R2
        yfit = m * x[sel] + b
        ss_res = float(np.sum((y[sel] - yfit) ** 2))
        ss_tot = float(np.sum((y[sel] - np.mean(y[sel])) ** 2))
        R2 = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

        # update fit visuals
        xline = np.linspace(fitMin, fitMax, 200)
        self.fit_line.set_data(xline, m * xline + b)
        self.v1.set_xdata([fitMin, fitMin])
        self.v2.set_xdata([fitMax, fitMax])

        # Derivative is handled by EQE vs Energy selector
        Eg_der = float(self.eg_der_eqe) if np.isfinite(self.eg_der_eqe) else np.nan

        # update ln title fully
        self.ax_ln.set_title(
            f"Urbach fit: Eg = {Eg_fit:.3f} eV, Eu = {Eu_meV:.1f} meV",
            color=_pal.PLOT_FG
        )
        if hasattr(self, "slope_text_ln"):
            self.slope_text_ln.set_text(f"Slope: {m:.4f} 1/eV")

        # store result (needed for exports)
        self.fit_result = {
            "file": self.target_file.name if self.target_file else "",
            "sheet": self.sheet_name or "",
            "Jsc": float(self.jsc_val) if self.jsc_val is not None else np.nan,
            "Eg_fit": float(Eg_fit),
            "Eg_der": float(Eg_der) if np.isfinite(Eg_der) else np.nan,
            "Eu_meV": float(Eu_meV),
            "R2": float(R2) if np.isfinite(R2) else np.nan,
            "m": float(m),
            "b": float(b),
            "fitMin": float(fitMin),
            "fitMax": float(fitMax),
            "raw_x": np.asarray(self.raw_x, dtype=float),
            "raw_y": np.asarray(self.raw_y, dtype=float),
            "am15_interp": np.asarray(self.am15_interp, dtype=float) if self.am15_interp is not None else None,
            "D_int": np.asarray(self.D_int, dtype=float) if self.D_int is not None else None,
            "E_cum": np.asarray(self.E_cum, dtype=float) if self.E_cum is not None else None,
            "x_full": np.asarray(self.hv, dtype=float),
            "y_full": np.asarray(self.ln_eqe, dtype=float),
            "ln_xlim": tuple(self.ax_ln.get_xlim()),
            "ln_ylim": tuple(self.ax_ln.get_ylim()),
            "wl_xlim": tuple(self.ax_eqe.get_xlim()),
            "wl_ylim": tuple(self.ax_eqe.get_ylim()),
            "eqe_span": tuple(self.eqe_span) if self.eqe_span else None,
        }

        self._update_summary(clear=False)
        self.btn_excel.configure(state="normal")
        self.btn_origin.configure(state="normal")
        self.canvas.draw_idle()

    def open_compare(self):
        """Several EQE files side by side (Jsc, Eg, Urbach, Voc,rad) with an overlay."""
        from scripts.common.compare_window import CompareWindow
        CompareWindow(self, "eqe", options={"temperature_k": self._temperature_k()})

    def _measured_voc(self):
        try:
            return float(self.entry_voc.get())
        except (ValueError, AttributeError):
            return None

    def _temperature_k(self):
        try:
            t = float(self.entry_temp.get())
            return t if 100 < t < 500 else 300.0
        except (ValueError, AttributeError):
            return 300.0

    def _update_detailed_balance(self):
        """Band gap (Rau), Urbach energy, J0,rad / Voc,rad, SQ limits and voltage losses."""
        if self.raw_x is None or self.raw_y is None:
            return
        try:
            r = eqe_core.analyze_eqe(self.raw_x, self.raw_y, temperature_k=self._temperature_k(),
                                     voc_measured_v=self._measured_voc())
        except Exception as ex:
            self._log(f"Detailed balance failed: {ex}")
            return
        self.eqe_summary = r
        f = lambda v, fmt: (format(v, fmt) if isinstance(v, (int, float)) and np.isfinite(v) else "-")
        left = [("Jsc, AM1.5G integrated (mA/cm²)", r["Jsc_mA_cm2"], ".3f"),
                ("Eg, derivative distribution (eV)", r["Eg_Rau_eV"], ".4f"),
                ("Edge width sigma (meV)", 1000 * r["Eg_sigma_eV"] if np.isfinite(r["Eg_sigma_eV"]) else float("nan"), ".0f"),
                ("Eg, inflection point (eV)", r["Eg_inflection_eV"], ".4f"),
                ("Urbach energy (meV)", r["Eu_meV"], ".1f"),
                ("Urbach fit R²", r["Eu_R2"], ".4f"),
                ("Urbach window (eV)", f"{f(r['Eu_window_lo_eV'], '.3f')} - {f(r['Eu_window_hi_eV'], '.3f')}"),
                ("Tail extrapolated for J0,rad", "yes" if r.get("tail_extended") else "no")]
        right = [("J0,rad (mA/cm²)", r["J0_rad_mA_cm2"], ".3e"),
                 ("Voc,rad (V)", r["Voc_rad_V"], ".4f"),
                 ("SQ limit: Jsc (mA/cm²)", r["Jsc_SQ"], ".2f"),
                 ("SQ limit: Voc (V)", r["Voc_SQ"], ".4f"),
                 ("SQ limit: FF", r["FF_SQ"], ".3f"),
                 ("SQ limit: PCE (%)", r["PCE_SQ"], ".2f")]
        if "dV3_nonrad" in r:
            right += [("dV1 = Eg/q - Voc,SQ (V)", r["dV1_SQ"], ".3f"),
                      ("dV2 = Voc,SQ - Voc,rad (V)", r["dV2_rad"], ".3f"),
                      ("dV3 = Voc,rad - Voc (non-radiative, V)", r["dV3_nonrad"], ".3f"),
                      ("EQE_EL implied by dV3", r["EQE_EL"], ".2e")]
        _theme.fill_kv(self.db_tree_left, left)
        _theme.fill_kv(self.db_tree_right, right)
        self.lbl_eg_rau.configure(text=f"Eg(Rau, dEQE/dE): {f(r['Eg_Rau_eV'], '.3f')} eV")
        self.lbl_voc_rad.configure(text=f"Voc,rad: {f(r['Voc_rad_V'], '.3f')} V")

    def _export_report(self):
        if self.raw_x is None:
            messagebox.showwarning("Report", "Load a file first.")
            return
        self._update_detailed_balance()
        path = _report.ask_report_path(self, f"{self.target_file.stem if self.target_file else 'EQE'}_report.md")
        if not path:
            return
        sections = []
        if self.eqe_summary:
            sections.append(("Band gap, Urbach tail, detailed balance", {k: v for k, v in self.eqe_summary.items()
                                                                         if not isinstance(v, bool)}))
        if self.fit_result:
            r = self.fit_result
            sections.append(("Interactive Urbach fit (ln EQE vs E)", {"Eu (meV)": r["Eu_meV"], "Eg (fit, eV)": r["Eg_fit"],
                                                                      "R²": r["R2"], "range (eV)": f"{r['fitMin']:.3f}-{r['fitMax']:.3f}"}))
        notes = ("Jsc = q Int EQE Phi_AM1.5G dE (ASTM G173-03). Eg from the mean of P(E) = dEQE/dE over its half-maximum "
                 "window (Rau et al., Phys. Rev. Applied 7, 044016 (2017)). J0,rad = q Int EQE Phi_BB dE; "
                 "Voc,rad = kT/q ln(Jsc/J0,rad + 1). SQ limit for a step absorber at the derived Eg; FF from Green's formula. "
                 "dV1 + dV2 + dV3 = Eg/q - Voc.")
        try:
            _report.write_markdown_report(path, f"EQE analysis: {self.target_file.name if self.target_file else ''}",
                                          sections, figure=self.fig, inputs=[str(self.target_file)] if self.target_file else None,
                                          notes=notes)
            self._log(f"Report saved: {path}")
        except Exception as ex:
            messagebox.showerror("Report", str(ex))

    def _update_summary(self, clear: bool):
        if clear:
            if self.jsc_val is None:
                self.lbl_jsc.configure(text="Jsc: - mA/cm²")
            else:
                self.lbl_jsc.configure(text=f"Jsc: {self.jsc_val:.2f} mA/cm²")
                self.lbl_eg_fit.configure(text="Eg(Fit): - eV")
                self.lbl_eg_der.configure(text="Eg(Deriv): - eV")
                self.lbl_eu.configure(text="Eu: - meV")
                self.lbl_r2.configure(text="R²: -")
                self.lbl_fit.configure(text="Fit: - ~ - eV")
            return

        r = self.fit_result
        self.lbl_jsc.configure(text=f"Jsc: {r['Jsc']:.2f} mA/cm²")
        self.lbl_eg_fit.configure(text=f"Eg(Fit): {r['Eg_fit']:.3f} eV")
        self.lbl_eg_der.configure(text=f"Eg(Deriv): {r['Eg_der']:.3f} eV" if np.isfinite(r["Eg_der"]) else "Eg(Deriv): - eV")
        self.lbl_eu.configure(text=f"Eu: {r['Eu_meV']:.1f} meV")
        self.lbl_r2.configure(text=f"R²: {r['R2']:.4f}" if np.isfinite(r["R2"]) else "R²: -")
        self.lbl_fit.configure(text=f"Fit: {r['fitMin']:.3f} ~ {r['fitMax']:.3f} eV")

    # ---------------- Excel export (EQE_core style) ----------------
    def _save_excel(self):
        if not self.target_file:
            messagebox.showwarning("Warning", "Load file first.")
            return
        if not self.fit_result:
            messagebox.showwarning("Warning", "Fit first (drag range).")
            return

        r = self.fit_result
        out_path = self.target_file.parent / f"{self.target_file.stem}_result.xlsx"

        # Result sheet
        df_res = pd.DataFrame([{
            "Sample": r["sheet"],
            "Integrated Jsc (mA/cm2)": r["Jsc"],
            "Urbach Energy (meV)": r["Eu_meV"],
            "Eg (Fit) (eV)": r["Eg_fit"],
            "Eg (Deriv) (eV)": r["Eg_der"],
            "R2": r["R2"],
            "Slope": r["m"],
            "Intercept": r["b"],
            "Fit Range Min (eV)": r["fitMin"],
            "Fit Range Max (eV)": r["fitMax"],
        }])

        # EQE_Data sheet: include AM1.5G + integrand + cumulative
        df_eqe = pd.DataFrame({
            "Wavelength (nm)": r["raw_x"],
            "EQE (%)": r["raw_y"],
            "AM1.5G (W/m2/nm)": r["am15_interp"],
            "Jsc integrand (mA/cm2/nm)": r["D_int"],
            "Integrated": r["E_cum"],
        })

        # Urbach_Data: Energy + ln(EQE) + Fit line columns
        x_full = r["x_full"]
        y_full = r["y_full"]
        x_min_all = float(np.nanmin(x_full))
        x_max_all = float(np.nanmax(x_full))
        fit_x = np.linspace(x_min_all, x_max_all, 200)
        fit_y = r["m"] * fit_x + r["b"]

        df_urb = pd.DataFrame({"Energy (eV)": x_full, "ln(EQE)": y_full})
        max_len = max(len(df_urb), len(fit_x))

        def pad(arr, n):
            arr = np.asarray(arr, dtype=float)
            if len(arr) < n:
                return np.concatenate([arr, np.full(n - len(arr), np.nan)])
            return arr

        df_fit = pd.DataFrame({
            "Fit_X (eV)": pad(fit_x, max_len),
            "Fit_Y (lnEQE)": pad(fit_y, max_len),
        })

        df_urb = df_urb.reindex(range(max_len))
        df_urb_fit = pd.concat([df_urb, df_fit], axis=1)

        def _write(path):
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df_res.to_excel(writer, sheet_name="Result", index=False)
                df_eqe.to_excel(writer, sheet_name="EQE_Data", index=False)
                df_urb_fit.to_excel(writer, sheet_name="Urbach_Data", index=False)
                if self.eqe_summary:
                    pd.DataFrame([{k: v for k, v in self.eqe_summary.items()}]).T.reset_index().rename(
                        columns={"index": "Quantity", 0: "Value"}).to_excel(writer, sheet_name="DetailedBalance", index=False)
            return path

        try:
            try:
                saved = _write(out_path)
            except PermissionError:
                # target open in Excel -> write a timestamped copy instead of failing
                import time as _time
                alt = out_path.parent / f"{out_path.stem}_{_time.strftime('%H%M%S')}.xlsx"
                saved = _write(alt)
                self._log(f"Excel was locked -> saved as {alt.name}")
            from scripts.common.provenance import write_sidecar
            write_sidecar(str(saved), "EQE", inputs=[str(self.target_file)],
                          parameters={"sheet": self.sheet_name, "temperature_K": self._temperature_k(),
                                      "measured_Voc_V": self._measured_voc(),
                                      "urbach_fit_range_eV": [r["fitMin"], r["fitMax"]], "derivative_window_eV": r.get("eqe_span")},
                          results=self.eqe_summary or {})
            messagebox.showinfo("Success", f"Saved:\n{saved}")
            self._log(f"Excel saved: {saved}")
        except Exception as e:
            messagebox.showerror("Excel Error", str(e))

    # ---------------- Origin export (Workbook + plots + double Y) ----------------
    def _send_origin(self):
        if not WIN32COM_AVAILABLE:
            messagebox.showerror("Error", "pywin32 not installed. (pip install pywin32)")
            return
        if not self.fit_result:
            messagebox.showwarning("Warning", "Fit first (drag range).")
            return

        r = self.fit_result
        origin_path = self.origin_path_var.get().strip() or find_origin_path()

        # prepare arrays
        lam = np.asarray(r["raw_x"], dtype=float)
        eqe = np.asarray(r["raw_y"], dtype=float)
        am15 = np.asarray(r["am15_interp"], dtype=float)
        dint = np.asarray(r["D_int"], dtype=float)
        cum  = np.asarray(r["E_cum"], dtype=float)

        x_full = np.asarray(r["x_full"], dtype=float)
        y_full = np.asarray(r["y_full"], dtype=float)
        fit_x = np.linspace(float(np.nanmin(x_full)), float(np.nanmax(x_full)), 200)
        fit_y = r["m"] * fit_x + r["b"]

        def clean_list(arr):
            arr = np.asarray(arr, dtype=float)
            arr = np.where(np.isfinite(arr), arr, np.nan)
            return [float(v) if np.isfinite(v) else np.nan for v in arr]

        try:
            origin = jv_core.connect_to_origin(origin_path, log_callback=self._log)
            if not origin:
                raise RuntimeError(f"Could not connect to Origin.\nCheck path:\n{origin_path}")

            # Workbooks (3 separate sheets in 3 workbooks)
            wb_eqe = origin.CreatePage(2, f"EQE_{(self.sheet_name or 'S')}"[:10], "Origin")
            origin.Execute(f"page.active$={wb_eqe};")
            origin.Execute('wks.name$="EQE_Data";')
            origin.Execute("wks.ncols=5;")
            origin.Execute("wks.col1.type=4; wks.col2.type=1;")
            origin.Execute('wks.col1.lname$="Wavelength"; wks.col1.units$="nm";')
            origin.Execute('wks.col2.lname$="EQE"; wks.col2.units$="%";')
            origin.Execute('wks.col3.type=1; wks.col3.lname$="AM1.5G";    wks.col3.units$="W/m2/nm";')
            origin.Execute('wks.col4.type=1; wks.col4.lname$="Integrand"; wks.col4.units$="a.u.";')
            origin.Execute('wks.col5.type=1; wks.col5.lname$="Integrated Jsc ";       wks.col5.units$="(mA/cm²)";')
            origin.PutWorksheet(f"[{wb_eqe}]EQE_Data", clean_list(lam), 0, 0)
            origin.PutWorksheet(f"[{wb_eqe}]EQE_Data", clean_list(eqe), 0, 1)
            origin.PutWorksheet(f"[{wb_eqe}]EQE_Data", clean_list(am15), 0, 2)
            origin.PutWorksheet(f"[{wb_eqe}]EQE_Data", clean_list(dint), 0, 3)
            origin.PutWorksheet(f"[{wb_eqe}]EQE_Data", clean_list(cum), 0, 4)

            wb_ln = origin.CreatePage(2, "Urbach_Data"[:10], "Origin")
            origin.Execute(f"page.active$={wb_ln};")
            origin.Execute('wks.name$="Urbach_Data";')
            origin.Execute("wks.ncols=4;")
            origin.Execute("wks.col1.type=4; wks.col2.type=1; wks.col3.type=4; wks.col4.type=1;")
            origin.Execute('wks.col1.lname$="Energy"; wks.col1.units$="eV";')
            origin.Execute('wks.col2.lname$="ln(EQE)"; wks.col2.units$="a.u.";')
            origin.Execute('wks.col3.lname$="Fit_X"; wks.col3.units$="eV";')
            origin.Execute('wks.col4.lname$="Fit_Y"; wks.col4.units$="a.u.";')
            origin.PutWorksheet(f"[{wb_ln}]Urbach_Data", clean_list(x_full), 0, 0)
            origin.PutWorksheet(f"[{wb_ln}]Urbach_Data", clean_list(y_full), 0, 1)
            origin.PutWorksheet(f"[{wb_ln}]Urbach_Data", clean_list(fit_x), 0, 2)
            origin.PutWorksheet(f"[{wb_ln}]Urbach_Data", clean_list(fit_y), 0, 3)

            # Deriv_Data (d EQE / dE) - match UI behavior
            der_x = np.asarray([], dtype=float)
            der_y = np.asarray([], dtype=float)
            try:
                eqe_all = np.asarray(r["raw_y"], dtype=float)
                wl_all = np.asarray(r["raw_x"], dtype=float)
                valid = np.isfinite(wl_all) & np.isfinite(eqe_all) & (wl_all > 0)
                hv_all = 1239.842 /wl_all[valid]
                eqe_all = eqe_all[valid]
                idx = np.argsort(hv_all)
                hv_all = hv_all[idx]
                eqe_all = eqe_all[idx]

                full_min = float(np.nanmin(hv_all))
                full_max = float(np.nanmax(hv_all))
                x_u, dy, _, _ = self._compute_eqe_derivative(hv_all, eqe_all, full_min, full_max)
                der_x = x_u
                der_y = dy
            except Exception:
                der_x = np.asarray([], dtype=float)
                der_y = np.asarray([], dtype=float)

            wb_der = origin.CreatePage(2, "Deriv_Data"[:10], "Origin")
            origin.Execute(f"page.active$={wb_der};")
            origin.Execute('wks.name$="Deriv_Data";')
            origin.Execute("wks.ncols=2;")
            origin.Execute("wks.col1.type=4; wks.col2.type=1;")
            origin.Execute('wks.col1.lname$="Energy"; wks.col1.units$="eV";')
            origin.Execute('wks.col2.lname$="d(EQE)/dE"; wks.col2.units$="a.u.";')
            origin.PutWorksheet(f"[{wb_der}]Deriv_Data", clean_list(der_x), 0, 0)
            origin.PutWorksheet(f"[{wb_der}]Deriv_Data", clean_list(der_y), 0, 1)

            # -------------------------
            # Graph 1: Double Y (EQE left, Cum right)
            # Use Origin template doubleY if available.
            # -------------------------
            # Create graph page from template (doubleY)
            # If template missing, this call may fail -> fallback to normal plot.
            # try:
            #     # create graph from template
            #     origin.Execute('win -t plot;')  # ensure plot engine ready
            #     origin.Execute('dlg -gp;')      # safe no-op in some versions
            #     origin.Execute('newbook name:=EQEPlot;')  # placeholder no-op
            # except Exception:
            #     pass

            # try:
            #     # Preferred: plot with template doubleY into new graph
            #     origin.Execute(f'plotxy iy:=[{wb}]EQE_Data!(1,2) plot:=200 ogl:=[<new template:=doubleY>];')
            #     # Add Cum to layer2
            #     origin.Execute(f'plotxy iy:=[{wb}]EQE_Data!(1,5) plot:=200 ogl:=2;')
            #     # Turn off layer2 left y-axis to avoid overlap, use right axis
            #     origin.Execute("layer -s 2;")
            #     origin.Execute("layer.y.showAxes=0;")      # left Y off
            #     origin.Execute("layer.y2.showAxes=3;")     # right Y on
            #     origin.Execute("layer.y2.ticks=1;")
            #     origin.Execute("layer -s 1;")              # back to layer1




            # except Exception:
            #     # Fallback: simple plot (no doubleY)
            #     gp1 = origin.CreatePage(3, f"EQE_{(self.sheet_name or 'S')}"[:10], "Origin")
            #     origin.Execute(f"page.active$={gp1};")
            #     origin.Execute(f"plotxy iy:=[{wb}]EQE_Data!(1,2) plot:=200; layer -d;")

            # # Set axis ranges similar to UI
            # origin.Execute(f"layer.x.from={r['wl_xlim'][0]}; layer.x.to={r['wl_xlim'][1]};")
            # origin.Execute("layer.x.type=0;")
            # origin.Execute('label -x1 "Wavelength (nm)";')
            # origin.Execute('label -y1 "EQE (%)";')
            # # For right axis label (if doubleY): try label -y2
            # try:
            #     origin.Execute('label -y2 "Integrated Jsc (a.u.)";')
            # except Exception:
            #     pass

            # -------------------------
            # Graph 1) EQE (Wavelength vs EQE)
            # -------------------------
            gp_eqe = origin.CreatePage(3, f"EQE_{(self.sheet_name or 'S')}"[:10], "Origin")
            origin.Execute(f"win -a {gp_eqe};")
            origin.Execute(f"plotxy iy:=[{wb_eqe}]EQE_Data!(1,2) plot:=200 o:=[{gp_eqe}]1!;")
            origin.Execute(f"layer.x.from = {r['wl_xlim'][0]}; layer.x.to = {r['wl_xlim'][1]};")
            origin.Execute(f"layer.y.from = {r['wl_ylim'][0]}; layer.y.to = {r['wl_ylim'][1]};")
            origin.Execute("layer.x.type=0; layer.y.type=0;")
            origin.Execute('label -x1 "Wavelength (nm)";')
            origin.Execute('label -y1 "EQE (%)";')
            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")
            origin.Execute("set %C -k 20;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.x.showLabels = 1;")
            origin.Execute("layer.x2.label.show = 0;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.y2.ticks = 0;")
            origin.Execute("layer.y.showLabels = 1;")
            origin.Execute("layer.y2.label.show = 0;")
            origin.Execute("layer.y.inc = 5;")
            origin.Execute("layer.x.inc = .5;")
            origin.Execute("legend -r;")
            origin.Execute("doc -uw;")

            # -------------------------
            # Graph 2) ln(EQE) (Energy vs ln(EQE))
            # -------------------------
            gp_ln = origin.CreatePage(3, "lnEQE"[:10], "Origin")
            origin.Execute(f"win -a {gp_ln};")
            origin.Execute(f"plotxy iy:=[{wb_ln}]Urbach_Data!(1,2) plot:=201 o:=[{gp_ln}]1!;")
            origin.Execute(f"plotxy iy:=[{wb_ln}]Urbach_Data!(3,4) plot:=200 o:=[{gp_ln}]1!;")

            ln_xlim = r.get("ln_xlim", (1.4, 2.2))
            ln_ylim = r.get("ln_ylim", (-10.0, 1.0))
            origin.Execute(f"layer.x.from = {float(ln_xlim[0])}; layer.x.to = {float(ln_xlim[1])};")
            origin.Execute(f"layer.y.from = {float(ln_ylim[0])}; layer.y.to = {float(ln_ylim[1])};")
            origin.Execute("layer.x.type=0; layer.y.type=0;")
            origin.Execute('label -x1 "Energy (eV)";')
            origin.Execute('label -y1 "ln(EQE)";')
            origin.Execute("layer.plot = 2; set %C -w 2000;")
            origin.Execute("layer.plot = 1;")
            origin.Execute(f'label -r "Slope = {r["m"]:.4f} 1/eV";')
            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")
            origin.Execute("set %C -k 20;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.x.showLabels = 1;")
            origin.Execute("layer.x2.label.show = 0;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.y2.ticks = 0;")
            origin.Execute("layer.y.showLabels = 1;")
            origin.Execute("layer.y2.label.show = 0;")
            origin.Execute("layer.y.inc = 5;")
            origin.Execute("layer.x.inc = .5;")
            origin.Execute("legend -r;")
            origin.Execute("doc -uw;")

            # -------------------------
            # Graph 3) d(ln(EQE))/dE (Energy vs derivative)
            # -------------------------
            gp_der = origin.CreatePage(3, "dlnEQE"[:10], "Origin")
            origin.Execute(f"win -a {gp_der};")
            origin.Execute(f"plotxy iy:=[{wb_der}]Deriv_Data!(1,2) plot:=200 o:=[{gp_der}]1!;")
            origin.Execute(f"layer.x.from = {float(ln_xlim[0])}; layer.x.to = {float(ln_xlim[1])};")
            origin.Execute("layer.x.type=0; layer.y.type=0;")
            origin.Execute('label -x1 "Energy (eV)";')
            origin.Execute('label -y1 "d(EQE)/dE";')
            if np.isfinite(r.get("Eg_der", np.nan)):
                origin.Execute(f'label -r "Eg = {r["Eg_der"]:.3f} eV";')
            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")
            origin.Execute("set %C -k 20;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.x.showLabels = 1;")
            origin.Execute("layer.x2.label.show = 0;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.y2.ticks = 0;")
            origin.Execute("layer.y.showLabels = 1;")
            origin.Execute("layer.y2.label.show = 0;")
            origin.Execute("layer.y.inc = 5;")
            origin.Execute("layer.x.inc = .5;")
            origin.Execute("legend -r;")
            origin.Execute("doc -uw;")

            # arrange windows
            origin.Execute("doc -uw; tile -h;")
            origin.Visible = 1

            self._log("Origin export done.")
        except Exception as e:
            messagebox.showerror("Origin Error", str(e))

    def _on_close(self):
        try:
            self.destroy()
        except Exception:
            pass


# ============================================================
# main
# ============================================================
def main():
    ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()

    win = EQEWindow(root, origin_path=find_origin_path())
    win.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit(0)))
    root.mainloop()


# Alias for main GUI compatibility
AnalysisWindow = EQEWindow


if __name__ == "__main__":
    main()
