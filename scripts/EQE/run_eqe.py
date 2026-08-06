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
# AM1.5G spectrum (EQE_core dataset)
# ============================================================
_AM15G_CACHE = None


def get_am15g_spectrum():
    """
    Returns the AM1.5G standard spectrum (ASTM G173-03 Global Tilt).
    Returns: (wavelength_nm, irradiance_W_m2_nm)

    Loads the full-resolution ASTM G173-03 dataset (280-4000 nm, 0.5-5 nm steps,
    integrated total 1000.4 W/m^2) bundled as 'astm_g173_global.csv' next to this
    module. Falls back to a coarse 10-nm table if the CSV is missing (e.g. in a
    frozen build without the data file).
    """
    global _AM15G_CACHE
    if _AM15G_CACHE is not None:
        return _AM15G_CACHE

    csv_path = Path(__file__).resolve().parent / "astm_g173_global.csv"
    try:
        arr = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
        wl = arr[:, 0].astype(float)
        irr = arr[:, 1].astype(float)
        ok = np.isfinite(wl) & np.isfinite(irr)
        wl, irr = wl[ok], irr[ok]
        if len(wl) > 100:
            _AM15G_CACHE = (wl, irr)
            return _AM15G_CACHE
    except Exception:
        pass

    # Fallback: coarse table (10 nm steps, 290-990 nm)
    am15_values = np.array([
        0.00102, 0.05094, 0.20527, 0.47139, 0.5018, 0.52798, 0.59817, 0.75507,
        0.70077, 0.79699, 1.1141, 1.0485, 1.1232, 0.87462, 1.3499, 1.5595,
        1.5291, 1.5077, 1.6181, 1.6224, 1.5451, 1.5481, 1.5236, 1.5446,
        1.4825, 1.5399, 1.474, 1.4816, 1.502, 1.3709, 1.4753, 1.4686,
        1.4739, 1.3924, 1.434, 1.3594, 1.3992, 1.4196, 1.3969, 1.1821,
        1.2823, 1.3175, 0.9855, 1.1285, 1.2195, 1.2341, 0.26604, 1.1608,
        1.1636, 1.091, 1.0725, 1.0559, 0.86188, 0.91601, 1.0157, 0.89372,
        0.98816, 0.96755, 0.93957, 0.92393, 0.7426, 0.62467, 0.74414,
        0.4321, 0.47181, 0.14726, 0.42066, 0.63461, 0.60468, 0.73227,
        0.73532
    ], dtype=float)
    wl = 290 + 10 * np.arange(len(am15_values), dtype=float)
    _AM15G_CACHE = (wl, am15_values)
    return _AM15G_CACHE


def _eqe_to_fraction(eqe):
    """Convert EQE to fraction robustly. Values are treated as percent when the
    maximum exceeds 1.5 (a real EQE fraction cannot exceed ~1 for single-junction
    devices, while percent data is typically 20-95)."""
    eqe = np.asarray(eqe, dtype=float)
    return eqe / 100.0 if np.nanmax(eqe) > 1.5 else eqe


# ============================================================
# Your "integrand + cumulative" helper (for right axis)
# ============================================================
def compute_am15_integrals(wavelength_nm, eqe_percent):
    """
    Return:
      am15_interp: AM1.5G irradiance interpolated to the EQE wavelength grid
      D: Jsc integrand density [mA cm^-2 nm^-1] = e/(hc) * lambda * EQE * E_AM1.5G
      E: cumulative trapezoid integral of D over wavelength [mA cm^-2]

    Physics: Jsc = e * Int[ EQE(l) * Phi_AM1.5G(l) dl ], with photon flux
    Phi = E(l)*l/(hc). With l in nm and E in W m^-2 nm^-1 the integrand is
    EQE * l * E / 1239.842 in A m^-2 nm^-1; multiply by 0.1 for mA cm^-2 nm^-1.
    """
    am15_lam, am15_irr = get_am15g_spectrum()

    wl = np.asarray(wavelength_nm, dtype=float)
    eqe_frac = _eqe_to_fraction(eqe_percent)

    # Interp AM1.5G to wl; zero outside the reference data range (no flat extrapolation)
    am15_interp = np.interp(wl, am15_lam, am15_irr, left=0.0, right=0.0)

    # hc/e = 1239.842 eV*nm
    D = wl * eqe_frac * am15_interp / 1239.842 * 0.1  # mA cm^-2 nm^-1

    # cumulative trapezoid
    E = np.zeros_like(D, dtype=float)
    if len(wl) >= 2:
        order = np.argsort(wl)
        D_s = D[order]
        wl_s = wl[order]
        dlam = np.diff(wl_s)
        E_s = np.zeros_like(D_s)
        E_s[1:] = np.cumsum(0.5 * (D_s[1:] + D_s[:-1]) * dlam)
        E[order] = E_s

    return am15_interp, D, E


# ============================================================
# Physical Jsc calculation (photon flux)
# ============================================================
def calculate_jsc(wavelength_nm, eqe_percent):
    """
    Jsc [mA/cm^2] = e * Int[ EQE(l) * Phi_AM1.5G(l) dl ] over the overlap of the
    EQE data and the ASTM G173-03 reference spectrum.

    Integration is performed on the union of both wavelength grids so that
    neither the EQE resolution nor the reference-spectrum resolution is lost.
    """
    am15_lam, am15_irr = get_am15g_spectrum()

    wavelength_nm = np.asarray(wavelength_nm, dtype=float)
    eqe_decimal = _eqe_to_fraction(eqe_percent)

    ok = np.isfinite(wavelength_nm) & np.isfinite(eqe_decimal)
    wavelength_nm, eqe_decimal = wavelength_nm[ok], eqe_decimal[ok]
    if len(wavelength_nm) < 2:
        return float("nan")
    order = np.argsort(wavelength_nm)
    wavelength_nm, eqe_decimal = wavelength_nm[order], eqe_decimal[order]

    # overlap range
    min_w = max(np.nanmin(wavelength_nm), np.nanmin(am15_lam))
    max_w = min(np.nanmax(wavelength_nm), np.nanmax(am15_lam))
    if min_w >= max_w:
        return float("nan")

    # union grid: keeps full resolution of both datasets
    grid = np.union1d(wavelength_nm, am15_lam)
    grid = grid[(grid >= min_w) & (grid <= max_w)]

    eqe_interp = np.interp(grid, wavelength_nm, eqe_decimal)
    irr_interp = np.interp(grid, am15_lam, am15_irr)

    lambda_m = grid * 1e-9
    photon_energy = h * c / lambda_m
    photon_flux = irr_interp / photon_energy  # photons s^-1 m^-2 nm^-1

    integrand = eqe_interp * photon_flux
    if hasattr(np, "trapezoid"):
        jsc_A_m2 = e * np.trapezoid(integrand, x=grid)
    else:
        jsc_A_m2 = e * np.trapz(integrand, x=grid)

    return jsc_A_m2 * 0.1  # mA/cm^2


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
        self.card_bg = "#1E1E1E"
        self.accent_blue = "#3182F6"
        self.accent_orange = "#F59E0B"
        self.accent_green = "#10B981"
        self.text_primary = "#FFFFFF"
        self.text_secondary = "#8B8B8B"

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
                    "open": ("📁 Open File", self._browse_file),
                    "run": ("▶ Load & Plot", self._load_and_plot),
                    "fit": ("⚡ Auto Fit", self._auto_fit_all),
                    "excel": ("Excel", self._save_excel),
                    "png": True,
                    "origin": ("Origin", self._send_origin)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

    # ---------------- panels ----------------
    def _create_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=340, corner_radius=0, fg_color="#141414")
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        # Load card
        load_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        row = ctk.CTkFrame(load_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_file = ctk.CTkEntry(row, placeholder_text="Select EQE Excel/CSV...", height=36)
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text="...", width=40, height=36,
                      command=self._browse_file, corner_radius=8).pack(side="right")

        sheet_row = ctk.CTkFrame(load_card, fg_color="transparent")
        sheet_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(sheet_row, text="Sheet:", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")

        self.sheet_menu = ctk.CTkOptionMenu(
            sheet_row, values=["-"], variable=self.selected_sheet,
            command=lambda _v: None, width=210
        )
        self.sheet_menu.pack(side="right")

        self.btn_load = ctk.CTkButton(
            load_card, text="Load & Plot", command=self._load_and_plot,
            corner_radius=12, height=42, fg_color=self.accent_blue,
            hover_color="#2563EB", font=("Segoe UI", 14),
            state="disabled"
        )
        self.btn_load.pack(pady=(0, 16), padx=16, fill="x")

        # View card
        set_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        set_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(set_card, text="View / Derivative", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        wl_row = ctk.CTkFrame(set_card, fg_color="transparent")
        wl_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(wl_row, text="WL max (nm)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")
        self.entry_wlmax = ctk.CTkEntry(wl_row, width=130, height=32,
                                        font=("Segoe UI", 12), textvariable=self.wl_max)
        self.entry_wlmax.pack(side="right")

        e_row = ctk.CTkFrame(set_card, fg_color="transparent")
        e_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(e_row, text="E view (eV)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")

        e_inputs = ctk.CTkFrame(e_row, fg_color="transparent")
        e_inputs.pack(side="right")
        self.entry_emin = ctk.CTkEntry(e_inputs, width=70, height=32,
                                       font=("Segoe UI", 12), textvariable=self.e_min)
        self.entry_emin.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(e_inputs, text="~", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")
        self.entry_emax = ctk.CTkEntry(e_inputs, width=70, height=32,
                                       font=("Segoe UI", 12), textvariable=self.e_max)
        self.entry_emax.pack(side="left", padx=(6, 0))

        sg_row = ctk.CTkFrame(set_card, fg_color="transparent")
        sg_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(sg_row, text="Smooth window", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")
        self.entry_sg = ctk.CTkEntry(sg_row, width=130, height=32,
                                     font=("Segoe UI", 12), textvariable=self.sg_window)
        self.entry_sg.pack(side="right")

        self.btn_apply = ctk.CTkButton(
            set_card, text="Apply View", command=self._apply_view,
            fg_color="#3D3D3D", hover_color="#3D3D3D",
            corner_radius=10, height=40, font=("Segoe UI", 13),
            state="disabled"
        )
        self.btn_apply.pack(pady=(0, 8), padx=16, fill="x")

        # One-click auto fit: auto-select absorption edge (derivative Eg) + Urbach tail (ln EQE)
        self.btn_autofit = ctk.CTkButton(
            set_card, text="⚡ Auto Fit (Eg + Urbach)",
            command=self._auto_fit_all, height=40,
            fg_color="#252525", hover_color="#303030",
            font=("Segoe UI", 13, "bold"), corner_radius=8, state="disabled")
        self.btn_autofit.pack(pady=(0, 16), padx=16, fill="x")

        # Origin card
        origin_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        origin_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(origin_card, text="Origin", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        op_row = ctk.CTkFrame(origin_card, fg_color="transparent")
        op_row.pack(fill="x", padx=16, pady=(0, 12))
        self.entry_origin = ctk.CTkEntry(op_row, height=34, textvariable=self.origin_path_var)
        self.entry_origin.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(op_row, text="Browse", width=80, height=34, corner_radius=10,
                      command=self._browse_origin).pack(side="right")

        # Actions card
        act_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        act_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(act_card, text="Actions", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.btn_excel = ctk.CTkButton(
            act_card, text="Save Excel", command=self._save_excel,
            fg_color="#252525", hover_color="#303030",
            corner_radius=10, height=40, font=("Segoe UI", 13),
            state="disabled"
        )
        self.btn_excel.pack(padx=16, pady=4, fill="x")

        self.btn_origin = ctk.CTkButton(
            act_card, text="Send to Origin", command=self._send_origin,
            fg_color="#252525", hover_color="#303030",
            corner_radius=10, height=40, font=("Segoe UI", 13),
            state="disabled"
        )
        self.btn_origin.pack(padx=16, pady=(0, 16), fill="x")

    def _create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0A0A0A")
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(0, weight=1)
        self.center_frame.grid_rowconfigure(1, weight=1)  # bottom placeholder
        self.center_frame.grid_columnconfigure(0, weight=1)

        # ---- plot container (top) ----
        plot_container = ctk.CTkFrame(self.center_frame, corner_radius=12, fg_color="#1E1E1E")
        plot_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        plot_container.grid_rowconfigure(0, weight=1)
        plot_container.grid_columnconfigure(0, weight=1)

        # ---- Figure + GridSpec (2x2, use 3) ----
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor="#1E1E1E")

        gs = self.fig.add_gridspec(
            2, 2,
            width_ratios=[1.0, 1.2],     # right (lnEQE) slightly wider
            height_ratios=[1.0, 1.0],    # top/bottom equal
            wspace=0.28, hspace=0.32
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
            ha="center", va="center", color="#3D3D3D",
            transform=self.ax_eqe.transAxes, fontsize=14
        )
        self.canvas.draw()

        # ---- bottom panel (placeholder) ----
        bottom_panel = ctk.CTkFrame(self.center_frame, corner_radius=12, fg_color="#141414")
        bottom_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        ctk.CTkLabel(
            bottom_panel, text="(space) Add table / notes / extra plot here",
            text_color="#666666", font=("Segoe UI", 13)
        ).pack(pady=20)

    def _create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, width=360, corner_radius=0, fg_color="#141414")
        self.right_frame.grid(row=0, column=2, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        stats = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        stats.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats, text="Summary", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.lbl_file = ctk.CTkLabel(stats, text="",
                                     text_color=self.accent_blue, font=("Segoe UI", 12))
        self.lbl_file.pack(padx=16, anchor="w")

        grid = ctk.CTkFrame(stats, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(8, 16))

        self.lbl_jsc = ctk.CTkLabel(grid, text="Jsc: - mA/cm²", font=("Segoe UI", 15, "bold"),
                                    text_color=self.accent_green)
        self.lbl_jsc.pack(anchor="w")

        self.lbl_eg_fit = ctk.CTkLabel(grid, text="Eg(Fit): - eV", font=("Segoe UI", 14),
                                       text_color=self.text_secondary)
        self.lbl_eg_fit.pack(anchor="w", pady=(4, 0))

        self.lbl_eg_der = ctk.CTkLabel(grid, text="Eg(Deriv): - eV", font=("Segoe UI", 14),
                                       text_color=self.text_secondary)
        self.lbl_eg_der.pack(anchor="w", pady=(4, 0))

        self.lbl_eu = ctk.CTkLabel(grid, text="Eu: - meV", font=("Segoe UI", 14),
                                   text_color=self.text_secondary)
        self.lbl_eu.pack(anchor="w", pady=(4, 0))

        self.lbl_r2 = ctk.CTkLabel(grid, text="R²: -", font=("Segoe UI", 14),
                                   text_color=self.text_secondary)
        self.lbl_r2.pack(anchor="w", pady=(4, 0))

        self.lbl_fit = ctk.CTkLabel(grid, text="Fit: - ~ - eV", font=("Segoe UI", 14),
                                    text_color=self.text_secondary)
        self.lbl_fit.pack(anchor="w", pady=(4, 0))

        log = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 16))
        log.grid_rowconfigure(1, weight=1)
        log.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log, text="Log", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).grid(row=0, column=0, sticky="w",
                                                       padx=16, pady=(16, 8))

        self.log_text = ctk.CTkTextbox(log, font=("Consolas", 11))
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 16))
        self.log_text.configure(state="disabled")

    # ---------------- helpers ----------------
    def _style_axes(self, ax):
        ax.set_facecolor("#1E1E1E")
        ax.tick_params(colors="#AAAAAA", labelsize=10)
        for spine in ax.spines.values():
            spine.set_color("#2D2D2D")
        ax.xaxis.label.set_color("#FFFFFF")
        ax.yaxis.label.set_color("#FFFFFF")
        ax.title.set_color("#FFFFFF")

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
        self.ax_ln.set_title("Drag range to Fit", color="#3182F6", fontweight="bold")
        self.ax_ln.set_xlabel("Energy (eV)")
        self.ax_ln.set_ylabel(r"$\ln(EQE)$")
        self.ax_ln.grid(True, linestyle="--", alpha=0.35)
        self.slope_text_ln = self.ax_ln.text(
            0.02, 0.95, "",
            transform=self.ax_ln.transAxes,
            ha="left", va="top", fontsize=11, color="#FCA5A5"
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
            bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.5),
            arrowprops=dict(arrowstyle="->")
        )
        self.peak_annot.set_visible(False)
        self.eg_text_der = self.ax_der.text(
            0.02, 0.95, "",
            transform=self.ax_der.transAxes,
            ha="left", va="top", fontsize=11, color="#FCD34D"
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
        self.fig.subplots_adjust(left=0.06, right=0.96, top=0.92, bottom=0.10, wspace=0.28)
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

        # 1) Absorption edge (band edge): max dEQE/dE on the low-energy rise
        dy = np.gradient(eqe, hv)
        e_max_eqe = hv[int(np.nanargmax(eqe))]
        edge_mask = hv <= e_max_eqe  # low-energy (left) side of the peak only
        if not np.any(edge_mask):
            edge_mask = np.ones_like(hv, bool)
        i_edge = int(np.nanargmax(np.where(edge_mask, dy, -np.inf)))
        e0 = float(hv[i_edge])
        self._log(f"AutoFit: absorption edge ~ {e0:.3f} eV -> derivative Eg range [{e0-0.15:.3f}, {e0+0.15:.3f}]")
        self._on_span_eqe_energy(e0 - 0.15, e0 + 0.15)

        # 2) Urbach tail: exponential region below the edge (low-energy side where EQE is 1-30% of max)
        try:
            y_max = float(np.nanmax(eqe))
            tail = (hv < e0) & (eqe > 0.01 * y_max) & (eqe < 0.3 * y_max)
            if np.sum(tail) >= 4:
                lo, hi = float(np.min(hv[tail])), float(np.max(hv[tail]))
            else:
                lo, hi = e0 - 0.25, e0 - 0.03
            self._log(f"AutoFit: Urbach range [{lo:.3f}, {hi:.3f}] eV")
            self._on_span(lo, hi)
        except Exception as ex:
            self._log(f"AutoFit Urbach failed: {ex}")

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
            f"Eg(Fit)={Eg_fit:.3f} eV | Eu={Eu_meV:.1f} meV",
            color="#F87171", fontweight="bold"
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
    ctk.set_appearance_mode("Dark")
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
