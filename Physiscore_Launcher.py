# ============================================================
# Physiscore_Launcher.py - main window of the analysis suite
#  - menu bar (File / Analysis / Tools / Help); tool tree and tool panel (workbench)
#  - Workspace tab: the data files of a project folder with the measurement each one
#    holds (scripts/common/detect.py); Results tab: the analyses exported under it
#  - Settings: Origin path, cell area, theme
#  - status bar: cell area, Origin, version
#  - command line: --version, --selftest [--out f], --update, --spectra TAB [FILE],
#    --tool NAME [FILE ...] (open one analysis window directly),
#    --open FILE ... | FOLDER (detect the measurement, open the matching tool)
# ============================================================
import gc
import importlib
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.common import app_config  # noqa: E402
from scripts.common import palette as _pal  # noqa: E402

CONFIG_FILE = app_config.config_path()
APP_VERSION = "3.5.0"
REPO_URL = "https://github.com/jongsu-king/physiscore"

ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
ctk.set_default_color_theme("blue")
from scripts.common import theme as _theme  # noqa: E402  palette theme for customtkinter (3.2)

CATEGORIES = ["All", "Device", "Transport and recombination", "Optical", "Structural", "Vibrational", "Surface"]

# (name, category, icon file, module path, auto-fit tab or None, description)
# module path "exe:<file>" prefers an external program (Windows) and falls back
# to the built-in module; "spectra:<TAB>" opens the auto-fit workspace.
TOOLS = [
    ("J-V Curve", "Device", "J-V Curve.png", "exe:JV_Analysis.exe", None,
     "Voc, Jsc, FF, PCE, Rs, Rsh from the curve; one-diode fit; forward/reverse hysteresis; group statistics"),
    ("J-V Dark", "Device", "J-V dark.png", "scripts.Dark_JV.run_jv_dark", None,
     "Ideality factor, J0, Rsh and Rs from dark curves; full diode fit and Cheung analysis"),
    ("Device summary", "Device", "J-V Curve.png", "scripts.Device.run_device", None,
     "J-V + EQE (+ absorbance, PL) of one device: Jsc cross-check, band gap from three techniques, Voc vs Voc,rad and Voc,SQ"),
    ("EQE", "Device", "EQE.png", "scripts.EQE.run_eqe", None,
     "AM1.5G-integrated Jsc, band gap (Rau), Urbach energy, Voc,rad and voltage-loss breakdown"),
    ("Stability", "Device", "Stability.png", "scripts.Stability.run_stability", None,
     "T80, burn-in and stabilised Ts80, degradation rate from a power or efficiency trace; ISOS protocol on record"),
    ("Light intensity", "Transport and recombination", "Light intensity.png", "scripts.Intensity.run_intensity", None,
     "Ideality factor from Voc(I), Jsc power law, Suns-Voc pseudo J-V, pseudo fill factor and transport loss"),
    ("SCLC", "Transport and recombination", "SCLC.png", "scripts.SCLC.run_sclc", None,
     "Single-carrier J-V: ohmic, trap-filling and Child regimes, trap density, Mott-Gurney mobility, validity limits"),
    ("Impedance", "Transport and recombination", "Impedance.png", "scripts.EIS.run_eis", None,
     "Equivalent-circuit fit (complex least squares), circuit choice by AICc, linear Kramers-Kronig validity test"),
    ("C-V (Mott-Schottky)", "Transport and recombination", "C-V.png", "scripts.CV.run_cv", None,
     "1/C² against V: doping density, built-in voltage, depletion width, doping profile, full-depletion limit"),
    ("TRPL", "Transport and recombination", "TRPL.png", "scripts.TRPL.run_trpl", None,
     "Multi-exponential and stretched tail fits chosen by AICc, average and differential lifetimes, diffusion length"),
    ("Absorbance", "Optical", "Abs.png", "scripts.Abs.run_abs", None,
     "Tauc plot with automatic linear-region selection, Urbach tail, derivative band gap"),
    ("PL", "Optical", "PL.png", "scripts.PL.run_pl", "PL",
     "Baseline, Gaussian/Voigt fitting, energy axis with Jacobian, quenching efficiency"),
    ("XRD", "Structural", "XRD.png", "scripts.XRD.run_xrd", "XRD",
     "Background, pseudo-Voigt peak fitting, d-spacing, Scherrer, Williamson-Hall, Kalpha2 stripping"),
    ("FE-SEM", "Structural", "FE-SEM.png", "scripts.SEM.run_sem", None,
     "Grain segmentation, size distribution with log-normal statistics"),
    ("Raman", "Vibrational", "Raman.png", "scripts.Raman.run_raman", None,
     "Baseline, band detection and Lorentzian fitting, peak-shift tables, band library"),
    ("FTIR", "Vibrational", "FTIR.png", "scripts.FTIR.run_ftir", None,
     "Transmittance/absorbance, baseline, band fitting, peak-shift tables, band library"),
    ("XPS", "Surface", "logo.png", "spectra:XPS", None,
     "Shirley background, Voigt singlet/doublet fitting, charge referencing, atomic concentration"),
]

BUILTIN_FALLBACK = {"exe:JV_Analysis.exe": "scripts.JV.run_jv"}

# Shown in the Tool panel of the main window. "sections" are the headings of
# docs/METHODS.md that *Method notes* opens (offline copy bundled with the installers).
TOOL_DETAILS = {
    "J-V Curve": dict(
        input="Folder of instrument exports (Vmeas/Imeas) or CSV/TSV/DAT/Excel I-V files",
        output="<folder>.xlsx: summary, curve analysis, statistics, hysteresis, box charts; side-car",
        results="Voc, Jsc, FF, PCE, Vmpp, Rs, Rsh; one-diode Jph, J0, n, Rs, Rsh, R²; hysteresis index; statistics",
        defaults="area 0.04 cm²; 100 mW/cm²; 298.15 K; slope window ±5 % Voc; diode fit up to Voc + 0.15 V",
        refs="Jain & Kapoor 2004 (Lambert W); Hegedus & Shafarman 2004; Snaith et al. 2014",
        sections=["1.", "13."]),
    "J-V Dark": dict(
        input="Folder of dark I-V files (instrument exports or CSV/Excel)",
        output="<folder>_Dark.xlsx: CombinedData, SummaryTable (window and full fit); side-car",
        results="n and J0 (sliding window), Rsh,dark; full fit J0, n, Rs, Rsh; Cheung Rs and n",
        defaults="0.25 V window from 0.15 V, step 0.02 V, n in [0.5, 10]; |V| ≤ 0.15 V for Rsh; Cheung J ≥ 5 % of max",
        refs="Cheung & Cheung 1986", sections=["2."]),
    "Device summary": dict(
        input="J-V curve and EQE of one device; absorbance and PL of the absorber (optional)",
        output="Excel: Summary, AllValues, Checks, Inputs; Markdown report; side-car",
        results="Jsc mismatch; Eg from EQE, Tauc, PL and spread; Stokes shift; SQ fractions; ΔV1, ΔV2, ΔV3; EQE_EL",
        defaults="mismatch warning 5 %; band-gap spread warning 60 meV; 300 K; reverse sweep",
        refs="Rau 2007; Rau et al. 2017; Snaith 2012; Zimmermann et al. 2016", sections=["11."]),
    "EQE": dict(
        input="Wavelength (nm) and EQE (% or fraction), CSV or Excel",
        output="<file>_result.xlsx: Result, EQE_Data, Urbach_Data, DetailedBalance; side-car",
        results="Jsc (AM1.5G); Eg (Rau) ± σ; inflection Eg; Urbach energy; J0,rad, Voc,rad; SQ limits; ΔV1-ΔV3",
        defaults="ASTM G173-03; Urbach window 1-30 % of max; tail extrapolated 0.6 eV; 300 K",
        refs="Rau et al. 2017; Urbach 1953; Green 1981; Rühle 2016", sections=["3."]),
    "Stability": dict(
        input="Time and PCE (or power, normalised efficiency), text table or Excel; several traces overlay",
        output="Excel: Summary, Results, Checks, Parameters, Trace; side-car",
        results="T80 (measured or extrapolated, marked), burn-in amplitude and time constant, Ts80, rate per 1000 h, final value",
        defaults="time in h; normalised to the first point; level 0.8; model chosen by AICc; protocol not stated",
        refs="Reese et al. 2011 (ISOS); Roesch et al. 2015; Khenkin et al. 2020", sections=["22."]),
    "Light intensity": dict(
        input="Irradiance with Voc (and Jsc, FF, PCE), one row per intensity; or J-V files with the intensity in the name",
        output="Excel: Summary, Results, Checks, Parameters, Series, Pseudo J-V; side-car",
        results="n_id ± error from Voc(ln I); α of Jsc ~ I^α; pseudo J-V, pseudo FF, transport loss; local ideality",
        defaults="300 K; all intensities; reverse sweep when J-V files are given",
        refs="Koster et al. 2005; Sinton & Cuevas 2000; Tress et al. 2018; Caprioglio et al. 2020", sections=["18."]),
    "SCLC": dict(
        input="Dark J-V of an electron-only or hole-only device (V, I or J), text table or Excel",
        output="Excel: Summary, Results, Checks, Parameters, Curve; side-car",
        results="Regime slopes; V_TFL (V1), V2, V_inf; trap density and its resolution limit; μ (Mott-Gurney); σ, n0; hysteresis",
        defaults="thickness 500 nm; εr 25; 300 K; up sweep; slope window 5 points; Murgatroyd off",
        refs="Mott & Gurney 1940; Lampert 1956; Röhr et al. 2018; Le Corre et al. 2021", sections=["17."]),
    "Impedance": dict(
        input="Frequency (Hz), Z' and Z'' (Ω); the sign convention of Z'' is detected",
        output="Excel: Summary, Results, Checks, Parameters, Spectrum; side-car",
        results="Rs, R and C (or CPE Q, α) per arc with errors, τ, f_peak, C_eff; fit rms; Kramers-Kronig residual",
        defaults="circuit chosen by AICc among R(RC), R(RQ), R(RC)(RC), R(RQ)(RQ); modulus weighting; all frequencies",
        refs="Boukamp 1995; Schönleber et al. 2014; Hsu & Mansfeld 2001; von Hauff & Klotz 2022", sections=["20."]),
    "C-V (Mott-Schottky)": dict(
        input="Voltage (V) and capacitance (F, nF, pF or per cm²), text table or Excel",
        output="Excel: Summary, Results, Checks, Parameters, Curve; side-car",
        results="N from the 1/C² slope, V_bi, depletion width W0, doping profile N(W), full-depletion limit N_min",
        defaults="area from Settings; εr 25; 300 K; linear window found automatically; slope factor m = 2",
        refs="Sze & Ng 2007; Kirchartz et al. 2012; Almora et al. 2016; Ravishankar et al. 2021, 2022", sections=["21."]),
    "TRPL": dict(
        input="Time and counts (TCSPC export) or normalised intensity, text table or Excel",
        output="Excel: Summary, Results, Checks, Parameters, Decay, Fit, Differential lifetime; side-car",
        results="τ_i and amplitudes with errors, ⟨τ⟩ amplitude- and intensity-weighted, τ_1/e, χ²_red, differential lifetime",
        defaults="1-3 exponentials or stretched, chosen by AICc; Poisson weights for counts; tail fit from the peak; time in ns",
        refs="Lakowicz 2006; Kirchartz et al. 2020; Krückemeier et al. 2021; Peán et al. 2020", sections=["19."]),
    "Absorbance": dict(
        input="Wavelength (nm) and one or more absorbance columns, Excel or text export",
        output="<file>_result.xlsx: Result, UV-Vis, Tauc_Data; side-car",
        results="Tauc Eg ± standard error, linear region, derivative Eg, Urbach energy",
        defaults="window max(7, 4 %); local R² ≥ 0.8; slope ≥ 60 % of anchor; R² ≥ 0.98; ±0.6 eV around expected Eg",
        refs="Tauc, Grigorovici & Vancu 1966; Makuła et al. 2018", sections=["4."]),
    "PL": dict(
        input="Wavelength column and sample columns, CSV or Excel",
        output="Excel: PL_Results, Processed; side-car",
        results="Peak (nm, eV), FWHM (nm, meV), area, components (AICc), quenching by peak and area",
        defaults="Savitzky-Golay window; ALS log10 λ (8 for 0.5 nm sampling of a broad band), p 0.01; Jacobian",
        refs="Mooney & Kambhampati 2013; Akaike 1974", sections=["6."]),
    "XRD": dict(
        input="2θ (°) and intensity; reference peak list (2θ or d, hkl, I) optional",
        output="Excel: Peaks, Pattern, WilliamsonHall, ReferenceMatch, Crystallinity; side-car",
        results="Position, d, FWHM, η, Scherrer size; W-H size and strain ± error; crystallinity; reference match",
        defaults="ALS λ 10⁷, p 0.01; K 0.9; Cu Kα 1.5406 Å; reference tolerance 0.15°",
        refs="Scherrer 1918; Williamson & Hall 1953; Rachinger 1948; Nelson & Riley 1945", sections=["5.", "12."]),
    "FE-SEM": dict(
        input="TIF, PNG, JPG or BMP image, 8 or 16 bit",
        output="Excel: Grains, Statistics; side-car",
        results="Equivalent diameters; mean, sd, median, D10/D50/D90, CV; log-normal μ, σ, geometric mean and sd",
        defaults="Otsu threshold + marker watershed; two-point or scale-bar calibration; Freedman-Diaconis bins",
        refs="Otsu 1979", sections=["8."]),
    "Raman": dict(
        input="Raman shift (cm⁻¹) and up to ten spectra",
        output="Band, fit and shift tables; Excel",
        results="Band positions, widths, heights (Lorentzian); shifts against a reference layer; library suggestions",
        defaults="arPLS log10 λ 5; prominence 2 %; shift tolerance 8 cm⁻¹",
        refs="Baek, Park, Ahn & Choo 2015 (arPLS)", sections=["7."]),
    "FTIR": dict(
        input="Wavenumber (cm⁻¹) and transmittance or absorbance",
        output="Band, fit and shift tables; Excel",
        results="Band positions, widths, depths (Gaussian); shifts against a reference layer; library suggestions",
        defaults="arPLS log10 λ 5; prominence 1 %; T → A = -log10 T optional",
        refs="Baek et al. 2015", sections=["7."]),
    "XPS": dict(
        input="Binding energy (eV) and counts; Thermo Avantage exports",
        output="peaks_fitted.csv, processed.csv, Excel, peak report; atomic concentrations",
        results="Components (centre, FWHM, area), Shirley background, atomic %",
        defaults="C 1s at 284.8 eV; Scofield factors; doublet ratios 1:2, 2:3, 3:4; overlapping peaks fitted together",
        refs="Shirley 1972; Scofield 1976; Greczynski & Hultman 2020", sections=["9."]),
}
METHODS_URL = "https://github.com/jongsu-king/physiscore/blob/main/docs/METHODS.md"


class _TreeCell:
    """Status cell of one tool in the tool tree; keeps the cards[...]["status"]
    interface (cget/configure) used by the smoke test and the screenshot tool."""

    def __init__(self, tree, iid):
        self.tree, self.iid = tree, iid

    def cget(self, key):
        try:
            return self.tree.set(self.iid, "status") if key == "text" else ""
        except Exception:
            return ""

    def configure(self, text=None, **_kw):
        if text is not None:
            try:
                self.tree.set(self.iid, "status", text)
            except Exception:
                pass


def find_external_exe(filename):
    candidates = [
        os.path.join(BASE_DIR, filename),
        os.path.join(BASE_DIR, os.path.splitext(filename)[0], filename),
        os.path.join(os.path.dirname(BASE_DIR), os.path.splitext(filename)[0], filename),
        os.path.join(os.path.dirname(BASE_DIR), filename),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def resource_dir(sub: str) -> str:
    """Resource folder in both frozen and source runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            return p
        return os.path.join(os.path.dirname(sys.executable), sub)
    return os.path.join(BASE_DIR, sub)


# ------------------------------------------------------------
# Settings dialog
# ------------------------------------------------------------
class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        self.geometry("600x520")
        self.resizable(False, False)
        self.configure(fg_color=_pal.BG_WINDOW)
        self.transient(parent)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD,
                            border_width=1, border_color=_pal.BORDER)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        def label(text, pady=(10, 2)):
            ctk.CTkLabel(body, text=text, font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB,
                         anchor="w").pack(fill="x", padx=16, pady=pady)

        def field(placeholder="", show=None):
            e = ctk.CTkEntry(body, height=28, fg_color=_pal.BG_SUB, border_color=_pal.BORDER,
                             text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT,
                             placeholder_text=placeholder, show=show or "")
            return e

        # cell area
        label("Device active area (cm²)", pady=(14, 2))
        row0 = ctk.CTkFrame(body, fg_color="transparent")
        row0.pack(fill="x", padx=16)
        self.ent_area = field("0.04")
        self.ent_area.pack(side="left", fill="x", expand=True)
        self.ent_area.insert(0, f"{app_config.cell_area_cm2():g}")
        ctk.CTkLabel(row0, text="Scales Jsc and PCE linearly; re-read for every analysis.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM).pack(side="left", padx=10)

        # Origin
        label("OriginLab executable (Windows, optional)")
        row1 = ctk.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x", padx=16)
        self.ent_origin = field(r"C:\Program Files\OriginLab\...\Origin64.exe")
        self.ent_origin.pack(side="left", fill="x", expand=True)
        if parent.origin_path:
            self.ent_origin.insert(0, parent.origin_path)
        ctk.CTkButton(row1, text="Browse...", width=84, height=28, fg_color=_pal.BG_SUB,
                      hover_color=_pal.BG_HOVER, border_width=1, border_color=_pal.BORDER_HI,
                      text_color=_pal.TXT, corner_radius=_pal.R_PILL, font=_pal.font(11),
                      command=self._browse).pack(side="left", padx=(8, 0))

        # theme
        label("Appearance (applies after restart)")
        self.theme_var = ctk.StringVar(value=_pal.THEME.capitalize())
        ctk.CTkSegmentedButton(body, values=["Light", "Dark"], variable=self.theme_var, height=26,
                               font=_pal.font(11), corner_radius=_pal.R_PILL,
                               selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT).pack(anchor="w", padx=16)

        # plot colours
        label("Plot colours (applies after restart)")
        self.colors_var = ctk.StringVar(value="Origin" if _pal.PLOT_COLORS == "origin" else "Colour-blind safe")
        ctk.CTkSegmentedButton(body, values=["Origin", "Colour-blind safe"], variable=self.colors_var, height=26,
                               font=_pal.font(11), corner_radius=_pal.R_PILL,
                               selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT).pack(anchor="w", padx=16)
        ctk.CTkLabel(body, text="Origin: black, red, blue, magenta, olive, navy ... (OriginLab's default increment). "
                                "Colour-blind safe: Okabe-Ito.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="w").pack(fill="x", padx=16)

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(12, 12), side="bottom")
        ctk.CTkButton(btns, text="Cancel", width=90, height=30, fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                      corner_radius=_pal.R_PILL, font=_pal.font(11), command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Save", width=100, height=30, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV,
                      text_color="white", font=_pal.font(11, "bold"), corner_radius=_pal.R_PILL,
                      command=self._save).pack(side="right")
        self.after(80, self.focus)

    def _browse(self):
        path = filedialog.askopenfilename(title="Select Origin executable",
                                          filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.ent_origin.delete(0, "end")
            self.ent_origin.insert(0, path)

    def _save(self):
        try:
            area = float(self.ent_area.get())
            if not area > 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Settings", "The device area must be a positive number (cm²).", parent=self)
            return
        self.parent.origin_path = self.ent_origin.get().strip()
        theme = self.theme_var.get().lower()
        colors = "origin" if self.colors_var.get() == "Origin" else "colorblind"
        self.parent.save_config(extra={"cell_area_cm2": area, "theme": theme, "plot_colors": colors})
        self.parent.refresh_statusbar()
        if theme != _pal.THEME or colors != _pal.PLOT_COLORS:
            self.parent.set_status("Appearance saved; restart Physiscore to apply it.")
        else:
            self.parent.set_status("Settings saved.")
        self.destroy()


# ------------------------------------------------------------
# Main window
# ------------------------------------------------------------
class LauncherApp(ctk.CTk):
    def __init__(self, workspace=None):
        super().__init__()
        self.title("Physiscore")
        self.geometry("1280x860")
        self.minsize(1040, 680)
        self.configure(fg_color=_pal.BG_WINDOW)

        self.origin_path = ""
        self.workspace_folder = ""
        self.load_config()
        if workspace:
            self.workspace_folder = os.path.abspath(workspace)

        self.logo_dir = resource_dir("logo")
        self.modules = {}          # module_path -> module | None | "loading" | str(exe path)
        self.cards = {}
        self.current_category = "All"
        self.updater = None
        self.update_worker = None

        self._build_menubar()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.refresh_cards()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._setup_updates()
        # imports run in a worker thread; the main thread polls the results
        # (an after() issued from the worker is dropped by some Tk builds)
        self._preload_done = False
        threading.Thread(target=self._preload_modules, daemon=True).start()
        self.after(100, self._poll_modules)
        self.after(500, self._refresh_updates)
        self.after(1500, self._maybe_whats_new)
        if self.workspace_folder and os.path.isdir(self.workspace_folder):
            self.after(300, lambda: self.ws_panel.set_folder(self.workspace_folder))

    # ---------------- config ----------------
    def load_config(self):
        data = app_config.load(refresh=True)
        self.origin_path = data.get("origin_path", "")
        self.workspace_folder = str(data.get("workspace_folder") or "")

    def save_config(self, extra=None):
        values = {"origin_path": self.origin_path}
        if extra:
            values.update(extra)
        try:
            # 3.4 removed the Gemini panels; a key stored by an older version is
            # dropped from the settings file on the next save
            app_config.update(values, drop=app_config.RETIRED_KEYS)
        except Exception as e:
            print(f"Config save error: {e}")

    # ---------------- menu bar ----------------
    def _build_menubar(self):
        bar = tk.Menu(self, tearoff=False)

        m_file = tk.Menu(bar, tearoff=False)
        m_file.add_command(label="Open data...", accelerator="Ctrl+O", command=self.open_data_dialog)
        m_file.add_command(label="Open workspace folder...", accelerator="Ctrl+Shift+O",
                           command=self.open_workspace_dialog)
        m_file.add_command(label="Collect results to Excel...", command=self.collect_results)
        m_file.add_separator()
        m_file.add_command(label="Settings...", accelerator="Ctrl+,", command=self.open_settings)
        m_file.add_command(label="Open settings folder", command=self._open_config_folder)
        m_file.add_separator()
        m_file.add_command(label="Quit", accelerator="Ctrl+Q", command=self.on_closing)
        bar.add_cascade(label="File", menu=m_file)

        m_an = tk.Menu(bar, tearoff=False)
        for cat in CATEGORIES[1:]:
            for name, _cat, _icon, mod_path, tab, _desc in (t for t in TOOLS if t[1] == cat):
                m_an.add_command(label=name, command=lambda m=mod_path, n=name: self.open_tool(m, n))
            m_an.add_separator()
        m_an.add_command(label="Auto-fit workspace: PL", command=lambda: self.open_spectra("PL"))
        m_an.add_command(label="Auto-fit workspace: XRD", command=lambda: self.open_spectra("XRD"))
        m_an.add_command(label="Auto-fit workspace: XPS", command=lambda: self.open_spectra("XPS"))
        bar.add_cascade(label="Analysis", menu=m_an)

        m_tools = tk.Menu(bar, tearoff=False)
        self.update_menu = tk.Menu(m_tools, tearoff=False)
        m_tools.add_cascade(label="Updates", menu=self.update_menu)
        m_tools.add_command(label="Run self-test", command=self._run_selftest)
        m_tools.add_command(label="Command-line interface (help)", command=self._show_cli_help)
        bar.add_cascade(label="Tools", menu=m_tools)

        m_help = tk.Menu(bar, tearoff=False)
        m_help.add_command(label="User guide", accelerator="F1", command=lambda: self.open_doc("USER_GUIDE"))
        m_help.add_command(label="Methods and algorithms", command=lambda: self.open_doc("METHODS"))
        m_help.add_command(label="Validation", command=lambda: self.open_doc("VALIDATION"))
        m_help.add_command(label="File formats", command=lambda: self.open_doc("FILE_FORMATS"))
        m_help.add_command(label="Command line", command=lambda: self.open_doc("CLI"))
        m_help.add_command(label="Installation and updates", command=lambda: self.open_doc("INSTALL"))
        m_help.add_command(label=f"What's new in {APP_VERSION}", command=self.show_whats_new)
        m_help.add_separator()
        m_help.add_command(label="Documentation on the web", command=lambda: self._open_url(f"{REPO_URL}/tree/main/docs"))
        m_help.add_command(label="Report an issue", command=lambda: self._open_url(f"{REPO_URL}/issues"))
        m_help.add_separator()
        m_help.add_command(label="About Physiscore", command=self._about)
        bar.add_cascade(label="Help", menu=m_help)
        self.configure(menu=bar)
        self.bind("<Control-q>", lambda e: self.on_closing())
        self.bind("<Control-o>", lambda e: self.open_data_dialog())
        self.bind("<Control-O>", lambda e: self.open_workspace_dialog())        # Ctrl+Shift+O
        self.bind("<Control-comma>", lambda e: self.open_settings())
        self.bind("<F1>", lambda e: self.open_doc("USER_GUIDE"))

    def open_doc(self, name, section=None):
        """Open the bundled documentation (offline HTML); the web copy if it is missing."""
        try:
            from scripts.common import docs_viewer
            if docs_viewer.open_doc(name, section=section) is not None:
                self.set_status(f"Opened {docs_viewer.DOCS.get(name, name)} (offline copy)")
                return
        except Exception as e:  # noqa: BLE001
            print(f"[Physiscore] offline documentation: {e}")
        self._open_url(f"{REPO_URL}/blob/main/docs/{name}.md")

    def show_whats_new(self):
        try:
            from scripts.common import docs_viewer
            if docs_viewer.open_release_notes(APP_VERSION) is not None:
                return
        except Exception as e:  # noqa: BLE001
            print(f"[Physiscore] release notes: {e}")
        self._open_url(f"{REPO_URL}/releases/tag/v{APP_VERSION}")

    def _maybe_whats_new(self):
        """After an update (the version differs from the last run), open the release notes once."""
        if os.environ.get("PHYSISCORE_NO_UPDATE") or os.environ.get("CI"):
            return
        last = app_config.get("last_run_version")
        if last == APP_VERSION:
            return
        try:
            app_config.update({"last_run_version": APP_VERSION})
        except Exception:
            pass
        if last:
            self.set_status(f"Updated from {last} to {APP_VERSION}; the release notes are open in the browser.")
            self.show_whats_new()

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _open_config_folder(self):
        folder = os.path.dirname(app_config.config_path())
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showinfo("Settings folder", f"{folder}\n\n({e})")

    def _about(self):
        messagebox.showinfo(
            "About Physiscore",
            f"Physiscore {APP_VERSION}\n"
            "Physics-constrained analysis of thin-film photovoltaic device and material measurements:\n"
            "J-V (light and dark), EQE, stability, light-intensity series, SCLC, impedance, C-V, TRPL,\n"
            "absorbance, PL, XRD, SEM, Raman, FTIR, XPS. All analysis runs on this computer.\n\n"
            "Hybrid Materials and Optoelectronics Laboratory (H-MOL), Incheon National University.\n"
            "MIT License.  Concept DOI 10.5281/zenodo.22267588\n"
            f"{REPO_URL}")

    def _show_cli_help(self):
        messagebox.showinfo(
            "Command line",
            "Physiscore --open FILE ... | FOLDER   detect the measurement and open its tool\n"
            "Physiscore --tool \"TRPL\" [FILE ...]  open one analysis window\n"
            "Physiscore --spectra XRD|PL|XPS [FILE] auto-fit workspace\n"
            "Physiscore --selftest [--out f.json] headless check\n"
            "Physiscore --update                  check for / install updates\n"
            "Physiscore --version\n\n"
            "Batch analysis without the GUI: python -m physiscore_cli --help")

    def _run_selftest(self):
        self.set_status("Running self-test...")

        def work():
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = selftest(None)
            self.after(0, lambda: (self.set_status("Self-test passed" if code == 0 else "Self-test FAILED"),
                                   messagebox.showinfo("Self-test", buf.getvalue()[:4000])))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- updates ----------------
    def _setup_updates(self):
        self.update_menu.add_command(label="Installation and updates (web)",
                                     command=lambda: self._open_url(f"{REPO_URL}/blob/main/docs/INSTALL.md"))
        self.update_menu.add_separator()
        try:
            import selfupdate
            self.updater = selfupdate.Updater(make_update_app(selfupdate))
            self.update_worker = selfupdate.attach_tk(self, self.updater, self.update_menu, lang="en",
                                                      status=lambda text: text and self.set_status(text))
        except Exception as e:  # updates must never stop the analysis suite
            print(f"[Physiscore] update support unavailable: {e}")

    # ---------------- toolbar ----------------
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, height=36, fg_color=_pal.TOOL_BG, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, height=1, fg_color=_pal.BORDER_HI, corner_radius=0).place(
            relx=0, rely=1.0, relwidth=1.0, anchor="sw")
        ctk.CTkLabel(bar, text="Physiscore", font=_pal.font(13, "bold"), text_color=_pal.TXT
                     ).pack(side="left", padx=(12, 6))
        ctk.CTkLabel(bar, text="thin-film photovoltaic characterisation", font=_pal.font(11),
                     text_color=_pal.TXT_SUB).pack(side="left", padx=(0, 16))
        ctk.CTkButton(bar, text="Settings", width=76, height=24, fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                      corner_radius=_pal.R_PILL, command=self.open_settings).pack(side="right", padx=10, pady=6)
        ctk.CTkButton(bar, text="Open data...", width=96, height=24, fg_color=_pal.ACCENT,
                      hover_color=_pal.ACCENT_HOV, text_color="white", font=_pal.font(11, "bold"),
                      corner_radius=_pal.R_PILL, command=self.open_data_dialog).pack(side="left", padx=(0, 6), pady=6)
        ctk.CTkButton(bar, text="Workspace folder...", width=130, height=24, fg_color=_pal.BG_PANEL,
                      hover_color=_pal.BG_HOVER, text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                      font=_pal.font(11), corner_radius=_pal.R_PILL,
                      command=self.open_workspace_dialog).pack(side="left", pady=6)
        self.search_var = ctk.StringVar()
        ent = ctk.CTkEntry(bar, width=190, height=24, fg_color=_pal.BG_CARD, border_color=_pal.BORDER_HI,
                           text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT,
                           placeholder_text="Filter tools", textvariable=self.search_var)
        ent.pack(side="right", padx=(0, 4), pady=6)
        ent.bind("<KeyRelease>", lambda e: self.refresh_cards())

    # ---------------- body ----------------
    def _build_body(self):
        """Workbench: tool tree on the left; the selected tool, the session and the
        conventions on the right (3.2; replaces the card grid)."""
        from tkinter import ttk
        body = ctk.CTkFrame(self, fg_color=_pal.BG_WINDOW, corner_radius=0)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.grid_columnconfigure(0, weight=0, minsize=340)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- left: tool tree ----
        left = _theme.card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        hdr = ctk.CTkLabel(left, text="Analysis tools", font=_pal.font(11, "bold"))
        hdr.pack(fill="x")
        _theme.panel_header(hdr, left)
        _theme.style_treeview(rowheight=24)
        self.tree = ttk.Treeview(left, columns=("status",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Tool", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.column("#0", width=200, minwidth=160, stretch=True)
        self.tree.column("status", width=120, minwidth=90, stretch=False, anchor="w")
        self.tree.tag_configure("category", font=_pal.font(11, "bold"), foreground=_pal.TXT_SUB)
        self.tree.tag_configure("unavailable", foreground=_pal.RED)
        self.tree.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._open_selected())
        self.tree.bind("<Return>", lambda e: self._open_selected())
        self._iid_tool = {}
        self._selected_tool = None

        # ---- right: the selected tool on top; Workspace / Results / Session / ... in tabs ----
        right = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        tool = _theme.card(right)
        tool.grid(row=0, column=0, sticky="ew")
        th = ctk.CTkLabel(tool, text="Tool", font=_pal.font(11, "bold"))
        th.pack(fill="x")
        _theme.panel_header(th, tool)
        top = ctk.CTkFrame(tool, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(2, 4))
        self.lbl_icon = ctk.CTkLabel(top, text="", width=52)
        self.lbl_icon.pack(side="left", padx=(0, 10))
        names = ctk.CTkFrame(top, fg_color="transparent")
        names.pack(side="left", fill="x", expand=True)
        self.lbl_tool = ctk.CTkLabel(names, text="", font=_pal.font(16, "bold"), text_color=_pal.TXT, anchor="w")
        self.lbl_tool.pack(fill="x")
        self.lbl_cat = ctk.CTkLabel(names, text="", font=_pal.font(11), text_color=_pal.TXT_SUB, anchor="w")
        self.lbl_cat.pack(fill="x")
        self.lbl_desc = ctk.CTkLabel(tool, text="", font=_pal.font(12), text_color=_pal.TXT, anchor="w",
                                     justify="left", wraplength=700)
        self.lbl_desc.pack(fill="x", padx=12, pady=(0, 6))
        self.tool_table = _theme.kv_table(tool, height=7, key_width=110, value_width=600)
        self.tool_table.heading("k", text="Item")
        self.tool_table.heading("v", text="Description")
        self.tool_table.column("v", anchor="w")
        self.tool_table.pack(fill="x", padx=12, pady=(0, 8))
        btns = ctk.CTkFrame(tool, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_open = ctk.CTkButton(btns, text="Open", width=96, height=26, fg_color=_pal.ACCENT,
                                      hover_color=_pal.ACCENT_HOV, text_color="white", font=_pal.font(12, "bold"),
                                      corner_radius=_pal.R_PILL, command=self._open_selected)
        self.btn_open.pack(side="left")
        self.btn_autofit = ctk.CTkButton(btns, text="Auto-fit workspace", width=140, height=26,
                                         fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER, text_color=_pal.TXT,
                                         border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                                         corner_radius=_pal.R_PILL, command=self._open_selected_autofit)
        self.btn_methods = ctk.CTkButton(btns, text="Method notes", width=110, height=26,
                                         fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER, text_color=_pal.TXT,
                                         border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                                         corner_radius=_pal.R_PILL, command=self._open_selected_methods)
        self.btn_methods.pack(side="right")
        self.btn_guide = ctk.CTkButton(btns, text="User guide", width=96, height=26,
                                       fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER, text_color=_pal.TXT,
                                       border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                                       corner_radius=_pal.R_PILL, command=lambda: self.open_doc("USER_GUIDE"))
        self.btn_guide.pack(side="right", padx=(0, 6))
        self.lbl_hint = ctk.CTkLabel(btns, text="Double-click a tool or press Enter to open it.",
                                     font=_pal.font(10), text_color=_pal.TXT_DIM)
        self.lbl_hint.pack(side="right", padx=10)

        self.tabs = ctk.CTkTabview(right, fg_color=_pal.BG_CARD, border_width=1, border_color=_pal.BORDER,
                                   corner_radius=_pal.R_CARD, anchor="nw", height=250,
                                   segmented_button_fg_color=_pal.BORDER_HI,
                                   segmented_button_selected_color=_pal.ACCENT,
                                   segmented_button_selected_hover_color=_pal.ACCENT_HOV,
                                   segmented_button_unselected_color=_pal.BG_SUB,
                                   segmented_button_unselected_hover_color=_pal.BG_HOVER,
                                   text_color=_pal.TXT)
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for name in ("Workspace", "Results", "Session", "Updates", "Recent folders", "Conventions"):
            self.tabs.add(name)

        from scripts.common import workspace_panel as _wp
        self.ws_panel = _wp.WorkspacePanel(self.tabs.tab("Workspace"), on_open=self.open_detections,
                                           on_compare=self.open_compare, on_status=self.set_status,
                                           on_scanned=self._on_workspace_scanned)
        self.ws_panel.pack(fill="both", expand=True)
        self.res_panel = _wp.ResultsPanel(self.tabs.tab("Results"), on_status=self.set_status)
        self.res_panel.pack(fill="both", expand=True)

        self.session_table = _theme.kv_table(self.tabs.tab("Session"), height=8, key_width=180, value_width=530)
        self.session_table.heading("k", text="Setting")
        self.session_table.heading("v", text="Value")
        self.session_table.column("v", anchor="w")
        self.session_table.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        upd = self.tabs.tab("Updates")
        self.update_table = _theme.kv_table(upd, height=6, key_width=180, value_width=530)
        self.update_table.heading("k", text="Item")
        self.update_table.heading("v", text="Value")
        self.update_table.column("v", anchor="w")
        self.update_table.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        urow = ctk.CTkFrame(upd, fg_color="transparent")
        urow.pack(fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(urow, text="Automatic updates", font=_pal.font(11), text_color=_pal.TXT_SUB).pack(side="left")
        self._mode_labels = {"auto": "Download and install", "notify": "Only tell me", "off": "Off"}
        self.update_mode_var = ctk.StringVar(value=self._mode_labels["auto"])
        self.opt_update_mode = ctk.CTkOptionMenu(urow, values=list(self._mode_labels.values()), width=170, height=24,
                                                 variable=self.update_mode_var, font=_pal.font(11),
                                                 command=self._set_update_mode)
        self.opt_update_mode.pack(side="left", padx=(8, 12))
        ctk.CTkButton(urow, text="Check now", width=96, height=24, fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                      corner_radius=_pal.R_PILL, command=self._check_updates_now).pack(side="left")
        self.btn_install_now = ctk.CTkButton(urow, text="Install now and restart", width=160, height=24,
                                             fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV, text_color="white",
                                             font=_pal.font(11, "bold"), corner_radius=_pal.R_PILL,
                                             command=self._install_update_now)
        ctk.CTkButton(urow, text="Release page", width=96, height=24, fg_color=_pal.BG_PANEL,
                      hover_color=_pal.BG_HOVER, text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                      font=_pal.font(11), corner_radius=_pal.R_PILL,
                      command=lambda: self._open_url(f"{REPO_URL}/releases/latest")).pack(side="right")
        ctk.CTkButton(urow, text="What's new", width=90, height=24, fg_color=_pal.BG_PANEL,
                      hover_color=_pal.BG_HOVER, text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                      font=_pal.font(11), corner_radius=_pal.R_PILL,
                      command=self.show_whats_new).pack(side="right", padx=(0, 6))

        rec = self.tabs.tab("Recent folders")
        self.recent_table = ttk.Treeview(rec, columns=("folder", "tool"), show="headings", height=5,
                                         selectmode="browse")
        self.recent_table.heading("folder", text="Folder", anchor="w")
        self.recent_table.heading("tool", text="Tool", anchor="w")
        self.recent_table.column("folder", width=560, anchor="w", stretch=True)
        self.recent_table.column("tool", width=120, anchor="w", stretch=False)
        self.recent_table.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.recent_table.bind("<Double-1>", lambda e: self._open_recent())
        self._recent_rows = {}

        ctk.CTkLabel(self.tabs.tab("Conventions"), justify="left", anchor="nw", wraplength=760, font=_pal.font(11),
                     text_color=_pal.TXT_SUB,
                     text=("Current density in mA/cm², photocurrent plotted negative; energies in eV, wavelengths in nm; "
                           "T = 298.15 K unless set. Jsc from EQE uses ASTM G173-03 AM1.5G (1000.4 W/m²).\n\n"
                           "Every Excel export writes a .analysis.json side-car with the inputs, parameters and version; "
                           "the Results tab lists the side-cars of the workspace folder and collects them in one workbook.\n\n"
                           "The Workspace tab names the measurement in each file from the file name, the column names and "
                           "the numbers, and says why. A low-confidence guess is a suggestion: it asks before opening.\n\n"
                           "Graphs follow OriginLab's look: black axis box, ticks in on all four sides, Arial, "
                           "Origin's colour order (Settings: colour-blind-safe colours instead).\n\n"
                           "Equations, defaults and references: Help → Methods and algorithms (offline copy).")
                     ).pack(fill="both", expand=True, padx=8, pady=6)

    # ---------------- status bar ----------------
    def _build_statusbar(self):
        sb = ctk.CTkFrame(self, height=24, fg_color=_pal.BG_PANEL, corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.lbl_ready = ctk.CTkLabel(sb, text="Ready", font=_pal.font(10), text_color=_pal.TXT_SUB, anchor="w")
        self.lbl_ready.pack(side="left", padx=10)
        self.lbl_env = ctk.CTkLabel(sb, text="", font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="e")
        self.lbl_env.pack(side="right", padx=10)
        self.refresh_statusbar()

    def refresh_statusbar(self):
        area = app_config.cell_area_cm2()
        o = "Origin: configured" if self.origin_path else "Origin: not set"
        self.lbl_env.configure(text=f"Cell area {area:g} cm²   |   {o}   |   Interpretation: rule-based, offline   |   v{APP_VERSION}")
        if getattr(self, "session_table", None) is not None:
            _theme.fill_kv(self.session_table, [
                ("Device active area", f"{area:g} cm²  (current density = current / area)"),
                ("Irradiance for PCE", "100 mW/cm² (one sun; set per analysis)"),
                ("Temperature", "298.15 K (J-V, diode fits); 300 K (detailed balance)"),
                ("OriginLab", self.origin_path or "not set (Origin export on Windows)"),
                ("Workspace folder", self.workspace_folder or "not set (Workspace tab, or File → Open workspace folder)"),
                ("Interpretation", "rule-based and offline (scripts/common/interpret.py); nothing leaves this computer"),
                ("Settings file", str(CONFIG_FILE)),
                ("Version", f"Physiscore {APP_VERSION}, Python {sys.version.split()[0]}"),
            ])

    def set_status(self, text):
        try:
            self.lbl_ready.configure(text=text)
        except Exception:
            pass

    # ---------------- module loading ----------------
    def _preload_modules(self):
        for _, _, _, mod_path, _, _ in TOOLS:
            self.modules[mod_path] = "loading"
        for _, _, _, mod_path, _, _ in TOOLS:
            if mod_path.startswith("exe:"):
                exe = find_external_exe(mod_path[4:]) if sys.platform == "win32" else None
                fallback = BUILTIN_FALLBACK.get(mod_path)
                if exe or not fallback:
                    self.modules[mod_path] = exe
                else:
                    try:
                        self.modules[mod_path] = importlib.import_module(fallback)
                    except Exception as e:
                        print(f"[Physiscore] {fallback} import failed: {e}")
                        self.modules[mod_path] = None
            elif mod_path.startswith("spectra:"):
                try:
                    self.modules[mod_path] = importlib.import_module("spectra.app")
                except Exception as e:
                    print(f"[Physiscore] spectra import failed: {e}")
                    self.modules[mod_path] = None
            else:
                try:
                    self.modules[mod_path] = importlib.import_module(mod_path)
                except Exception as e:
                    print(f"[Physiscore] {mod_path} import failed: {e}")
                    self.modules[mod_path] = None
        self._preload_done = True

    def _poll_modules(self):
        for mod_path in list(self.cards):
            self._update_card_state(mod_path)
        if not self._preload_done:
            self.after(150, self._poll_modules)
        else:
            self._fill_recent()

    def _tool_state(self, mod_path):
        mod = self.modules.get(mod_path, "loading")
        if isinstance(mod, str) and mod == "loading":
            return "Loading...", False
        if mod is None:
            return "Unavailable (see console)", False
        if mod_path.startswith("exe:") and isinstance(mod, str):
            return "External program", True
        return "Ready", True

    def _update_card_state(self, mod_path):
        card = self.cards.get(mod_path)
        if not card:
            return
        text, ok = self._tool_state(mod_path)
        card["status"].configure(text=text)
        try:
            tags = [t for t in self.tree.item(card["iid"], "tags") if t != "unavailable"]
            if text.startswith("Unavailable"):
                tags.append("unavailable")
            self.tree.item(card["iid"], tags=tags)
        except Exception:
            pass
        if self._selected_tool is not None and self._selected_tool[3] == mod_path:
            self._refresh_detail()

    # ---------------- tool tree ----------------
    def refresh_cards(self):
        """Rebuild the tool tree (filtered by the search field), grouped by category."""
        q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        keep = self._selected_tool[0] if self._selected_tool else None
        self.tree.delete(*self.tree.get_children())
        self.cards.clear()
        self._iid_tool = {}
        first = None
        n = 0
        for cat in CATEGORIES[1:]:
            tools = [t for t in TOOLS if t[1] == cat and (not q or q in t[0].lower() or q in t[5].lower())]
            if not tools:
                continue
            pid = self.tree.insert("", "end", text=cat, open=True, values=("",), tags=("category",))
            for t in tools:
                iid = self.tree.insert(pid, "end", text=t[0], values=("Loading...",))
                self._iid_tool[iid] = t
                self.cards[t[3]] = {"status": _TreeCell(self.tree, iid), "iid": iid}
                self._update_card_state(t[3])
                n += 1
                if first is None or t[0] == keep:
                    first = iid if (first is None or t[0] == keep) else first
        if first is not None:
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._on_select()
        self.set_status(f"{n} analysis tools")

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        tool = self._iid_tool.get(sel[0])
        if tool is None:                       # a category row: select its first tool
            kids = self.tree.get_children(sel[0])
            if kids:
                self.tree.selection_set(kids[0])
            return
        self._selected_tool = tool
        self._refresh_detail()

    def _refresh_detail(self):
        tool = self._selected_tool
        if tool is None:
            return
        name, category, icon, mod_path, spectra_tab, description = tool
        img = None
        p = os.path.join(self.logo_dir, icon)
        if os.path.exists(p):
            try:
                pil = Image.open(p)
                img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(46, 46))
            except Exception:
                img = None
        self._icon_ref = img
        self.lbl_icon.configure(image=img, text="" if img else name[:2])
        self.lbl_tool.configure(text=name)
        src = self.modules.get(mod_path)
        if mod_path.startswith("spectra:"):
            where = "auto-fit workspace"
        elif mod_path.startswith("exe:") and isinstance(src, str) and src != "loading":
            where = f"external program {os.path.basename(src)}"
        else:
            where = BUILTIN_FALLBACK.get(mod_path, mod_path)
        self.lbl_cat.configure(text=f"{category}  ·  {where}")
        self.lbl_desc.configure(text=description)
        d = TOOL_DETAILS.get(name, {})
        state, ok = self._tool_state(mod_path)
        secs = ", ".join(x.rstrip(".") for x in d.get("sections", []))
        _theme.fill_kv(self.tool_table, [("Input", d.get("input", "-")), ("Output", d.get("output", "-")),
                                         ("Results", d.get("results", "-")), ("Defaults", d.get("defaults", "-")),
                                         ("References", d.get("refs", "-")),
                                         ("Method notes", f"Methods and algorithms, section {secs}" if secs else "-"),
                                         ("Status", state)])
        self.btn_open.configure(state="normal" if ok else "disabled",
                                fg_color=_pal.ACCENT if ok else _pal.BG_SUB,
                                text_color="white" if ok else _pal.TXT_DIM)
        if spectra_tab:
            self.btn_autofit.pack(side="left", padx=(8, 0), after=self.btn_open)
        else:
            self.btn_autofit.pack_forget()

    def _fill_recent(self):
        """Folders processed by the J-V tools (their own recent lists), newest first."""
        tbl = getattr(self, "recent_table", None)
        if tbl is None:
            return
        tbl.delete(*tbl.get_children())
        self._recent_rows = {}
        rows = []
        for mod_path, label in (("exe:JV_Analysis.exe", "J-V Curve"), ("scripts.Dark_JV.run_jv_dark", "J-V Dark")):
            mod = self.modules.get(mod_path)
            cfg = getattr(mod, "CONFIG_FILE", None) if mod not in (None, "loading") and not isinstance(mod, str) else None
            if not cfg:
                continue
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    dirs = json.load(f).get("recent_dirs", [])
            except Exception:
                dirs = []
            rows += [(d, label, mod_path) for d in dirs if os.path.isdir(d)]
        for d, label, mod_path in rows[:8]:
            iid = tbl.insert("", "end", values=(d, label))
            self._recent_rows[iid] = (d, label, mod_path)
        if not rows:
            tbl.insert("", "end", values=("No folders yet: folders processed in J-V Curve or J-V Dark appear here.", ""))

    def _open_recent(self):
        sel = self.recent_table.selection()
        row = self._recent_rows.get(sel[0]) if sel else None
        if row:
            folder, label, mod_path = row
            self.open_tool(mod_path, label, folder=folder)

    def _open_selected(self):
        tool = self._selected_tool
        if tool is None:
            return
        name, _cat, _icon, mod_path, _tab, _desc = tool
        if self._tool_state(mod_path)[1]:
            self.open_tool(mod_path, name)

    def _open_selected_methods(self):
        tool = self._selected_tool
        secs = TOOL_DETAILS.get(tool[0], {}).get("sections", []) if tool else []
        self.open_doc("METHODS", section=secs[0] if secs else None)

    # ---------------- updates panel ----------------
    _KIND_TEXT = {"win-setup": "Windows installer", "win-portable": "Windows portable folder",
                  "mac-app": "macOS application bundle", "linux-deb": "Debian package (/opt/physiscore)",
                  "unix-dir": "folder installation (tar.gz)", "pip": "pip package", "source": "source checkout"}

    def _refresh_updates(self):
        """Fill the Updates tab from the updater's state; repeats every 2 s."""
        try:
            self._fill_updates()
        except Exception as e:  # noqa: BLE001 - the panel must never break the main window
            print(f"[Physiscore] update panel: {e}")
        try:
            self.after(2000, self._refresh_updates)
        except Exception:
            pass

    def _fill_updates(self):
        tbl = getattr(self, "update_table", None)
        if tbl is None:
            return
        up = self.updater
        if up is None:
            _theme.fill_kv(tbl, [("Installed version", APP_VERSION), ("Update support", "unavailable (see console)")])
            return
        import time as _time
        import selfupdate
        st = up._settings
        last = st.get("last_check")
        seen = st.get("last_seen") or ""
        busy = bool(self.update_worker is not None and self.update_worker.busy)
        if up.pending is not None:
            state = f"{up.pending.version} downloaded and verified (SHA-256); installed when you close Physiscore"
        elif busy:
            state = "checking or downloading ..."
        elif seen and selfupdate.is_newer(seen, APP_VERSION):
            state = f"{seen} is available"
        elif last:
            state = "up to date"
        else:
            state = "not checked yet"
        if selfupdate.disabled_by_environment(up.app):
            checks = "disabled (PHYSISCORE_NO_UPDATE or CI is set)"
        elif up.mode == "off":
            checks = "off"
        else:
            checks = "once a day at start-up (GitHub releases), plus Check now"
        inst = up.install
        _theme.fill_kv(tbl, [
            ("Installed version", f"Physiscore {APP_VERSION}"),
            ("Installation", self._KIND_TEXT.get(inst.kind, inst.kind)),
            ("Can update itself", "yes" if inst.can_apply else f"no - {inst.reason}"),
            ("Checks", checks),
            ("Last check", _time.strftime("%Y-%m-%d %H:%M", _time.localtime(float(last))) if last else "never"),
            ("Latest release seen", seen or "-"),
            ("State", state),
        ])
        label = self._mode_labels.get(up.mode, "")
        if label and self.update_mode_var.get() != label:
            self.update_mode_var.set(label)
        packed = self.btn_install_now.winfo_manager() == "pack"   # the tab may be hidden: not "ismapped"
        if up.pending is not None and not packed:
            self.btn_install_now.pack(side="left", padx=(8, 0))
        elif up.pending is None and packed:
            self.btn_install_now.pack_forget()

    def _set_update_mode(self, label):
        mode = {v: k for k, v in self._mode_labels.items()}.get(label)
        if self.updater is None or mode is None:
            return
        self.updater.mode = mode
        var = getattr(self, "_selfupdate_mode_var", None)
        if var is not None:
            var.set(mode)
        self.set_status(f"Automatic updates: {label}")

    def _check_updates_now(self):
        if self.update_worker is None:
            self.set_status("Update support is unavailable in this copy.")
            return
        self.update_worker.check(manual=True)
        self.set_status("Checking GitHub for a newer release ...")

    def _install_update_now(self):
        if self.updater is not None and self.updater.pending is not None:
            if messagebox.askyesno("Update", f"Install Physiscore {self.updater.pending.version} now? "
                                             "Physiscore closes and starts again.", parent=self):
                if self.updater.apply_now(relaunch=True):
                    self.on_closing()

    def _open_selected_autofit(self):
        tool = self._selected_tool
        if tool is not None and tool[4]:
            self.open_spectra(tool[4])

    # ---------------- launching ----------------
    def open_tool(self, mod_path, name, folder=None, files=None):
        """Open one analysis window. `folder` presets the folder of the J-V tools;
        `files` are handed to the window once it is up (Workspace tab, Open data)."""
        mod = self.modules.get(mod_path)
        if mod_path.startswith("spectra:"):
            self.open_spectra(mod_path.split(":", 1)[1], files[0] if files else "")
            return
        if mod_path.startswith("exe:") and not hasattr(mod, "AnalysisWindow"):
            exe = mod if isinstance(mod, str) else find_external_exe(mod_path[4:])
            if not exe or not os.path.isfile(exe):
                messagebox.showerror("Error", f"The external program for {name} was not found.")
                return
            try:
                self._sync_config_to(os.path.dirname(exe))
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
                self.set_status(f"Started {name} (external program)")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to start {name}:\n{e}")
            return
        if mod in (None, "loading"):
            messagebox.showerror("Error", f"The {name} module is not ready yet.")
            return
        try:
            win_cls = getattr(mod, "AnalysisWindow")
        except AttributeError:
            messagebox.showerror("Error", f"AnalysisWindow not found in {mod_path}.")
            return
        try:
            self.iconify()
            win = win_cls(self, self.origin_path)
            if folder and hasattr(win, "directory_path"):
                try:
                    win.directory_path.set(folder)
                except Exception:
                    pass
            if files:
                win.after(350, lambda: hand_over(win, list(files), status=self.set_status))
            self.wait_window(win)
            gc.collect()                # Tk fonts of the closed window: free them on this thread
            self._fill_recent()
            if getattr(self, "ws_panel", None) is not None:
                self.ws_panel.refresh_results()        # new exports show up in the Results tab
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open {name}:\n{e}")
        finally:
            try:
                self.deiconify()
            except Exception:
                pass

    def _sync_config_to(self, folder):
        """Share the Origin path and the cell area with the external program's config."""
        try:
            target = os.path.join(folder, "physisfera_config.json")
            data = {}
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if self.origin_path:
                data["origin_path"] = self.origin_path
            data["cell_area_cm2"] = app_config.cell_area_cm2()
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"config sync skip: {e}")

    def open_spectra(self, tab, data_file=""):
        """Auto-fit workspace in a separate process (its own Tk main loop); `data_file`
        is loaded in the XRD/XPS tab when given."""
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--spectra", tab]
            else:
                cmd = [sys.executable, "-m", "spectra.app", tab]
            if data_file:
                cmd.append(os.path.abspath(data_file))
            subprocess.Popen(cmd, cwd=BASE_DIR)
            self.set_status(f"Opened the {tab} auto-fit workspace"
                            + (f" with {os.path.basename(data_file)}" if data_file else ""))
        except Exception as e:
            messagebox.showerror("Error", f"Could not open the workspace:\n{e}")

    # ---------------- workspace, results, open data ----------------
    def open_data_dialog(self):
        """File → Open data: pick files, detect the measurement, open the matching tool."""
        start = self.workspace_folder if os.path.isdir(self.workspace_folder) else None
        paths = filedialog.askopenfilenames(
            title="Open data", initialdir=start,
            filetypes=[("Data files", "*.txt *.csv *.tsv *.dat *.xy *.asc *.prn *.xlsx *.xls *.tif *.tiff *.png *.jpg"),
                       ("All files", "*.*")])
        if paths:
            self.open_paths(list(paths))

    def open_paths(self, paths):
        from scripts.common import detect
        self.open_detections([detect.detect_file(p) for p in paths if os.path.isfile(p)])

    def open_workspace_dialog(self):
        self.tabs.set("Workspace")
        self.ws_panel.choose_folder()

    def set_workspace(self, folder):
        self.tabs.set("Workspace")
        self.ws_panel.set_folder(folder)

    def collect_results(self):
        self.tabs.set("Results")
        if not self.res_panel.entries:
            messagebox.showinfo("Collect results",
                                "No exported analyses are listed.\n\nChoose a workspace folder first (Workspace tab); "
                                "the exports found under it are collected in one workbook.", parent=self)
            return
        self.res_panel.collect()

    def _on_workspace_scanned(self, folder, detections, entries):
        self.res_panel.set_entries(entries, folder)
        if folder != self.workspace_folder or app_config.get("workspace_folder") != folder:
            self.workspace_folder = folder
            self.save_config({"workspace_folder": folder})
            self.refresh_statusbar()

    def open_detections(self, detections, ask=False):
        """Open detected files in their tool. Files of the first one's kind go
        together; a missing or low-confidence detection asks for the tool first."""
        ds = [d for d in detections if d is not None]
        if not ds:
            return
        first = ds[0]
        group = [d for d in ds if d.kind == first.kind]
        tool = first.tool
        if ask or first.confidence in ("none", "low"):
            tool = self._ask_tool(first, tool, len(group))
            if not tool:
                return
        self.open_tool_by_name(tool, [d.path for d in group])
        if len(group) < len(ds):
            self.set_status(f"Opened {len(group)} of {len(ds)} selected files in {tool}; "
                            "the others hold a different measurement.")

    def open_tool_by_name(self, name, files=None):
        from scripts.common import detect
        match = next((t for t in TOOLS if t[0] == name), None)
        if match is None:
            messagebox.showerror("Error", f"Unknown tool: {name}", parent=self)
            return
        mod_path = match[3]
        if not self._tool_state(mod_path)[1]:
            messagebox.showinfo(name, f"{name} is not ready yet ({self._tool_state(mod_path)[0]}).", parent=self)
            return
        files = [f for f in (files or []) if f]
        if files and name in detect.FOLDER_TOOLS:
            self.open_tool(mod_path, name, folder=os.path.dirname(files[0]))
        else:
            self.open_tool(mod_path, name, files=files or None)

    def _ask_tool(self, detection, suggested, n_files=1):
        """Modal question for a file whose measurement is uncertain; returns the tool name or ''."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Open with")
        dlg.geometry("520x260")
        dlg.resizable(False, False)
        dlg.configure(fg_color=_pal.BG_WINDOW)
        dlg.transient(self)
        more = f" (and {n_files - 1} more of the same kind)" if n_files > 1 else ""
        ctk.CTkLabel(dlg, text=detection.name + more, font=_pal.font(13, "bold"), text_color=_pal.TXT,
                     anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        if detection.kind:
            why = f"Looks like {detection.label} ({detection.confidence} confidence): {detection.why()}."
        else:
            why = "The measurement in this file was not recognised" + (f" ({detection.error})." if detection.error else ".")
        ctk.CTkLabel(dlg, text=why + "\n" + detection.describe(), font=_pal.font(11), text_color=_pal.TXT_SUB,
                     anchor="w", justify="left", wraplength=480).pack(fill="x", padx=16)
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(row, text="Open in", font=_pal.font(11), text_color=_pal.TXT).pack(side="left")
        names = [t[0] for t in TOOLS if t[0] != "Device summary"]
        var = ctk.StringVar(value=suggested if suggested in names else names[0])
        ctk.CTkOptionMenu(row, values=names, variable=var, width=240, height=26, font=_pal.font(11)
                          ).pack(side="left", padx=10)
        answer = {"tool": ""}

        def accept():
            answer["tool"] = var.get()
            dlg.destroy()

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", side="bottom", padx=16, pady=14)
        _theme.pill_button(btns, "Open", command=accept, primary=True, width=90, height=26).pack(side="right")
        _theme.pill_button(btns, "Cancel", command=dlg.destroy, width=80, height=26).pack(side="right", padx=8)
        dlg.bind("<Return>", lambda e: accept())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.after(100, lambda: (dlg.lift(), dlg.grab_set()))
        self.wait_window(dlg)
        return answer["tool"]

    def open_compare(self, kind, paths):
        """Overlay several files of one technique (Workspace tab → Compare selected)."""
        try:
            from scripts.common.compare_window import CompareWindow
            self.iconify()
            win = CompareWindow(self, kind, files=list(paths))
            self.wait_window(win)
            gc.collect()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open the comparison:\n{e}")
        finally:
            try:
                self.deiconify()
            except Exception:
                pass

    def open_settings(self):
        SettingsDialog(self)

    def _on_category(self, value):
        self.current_category = value
        self.refresh_cards()

    def on_closing(self):
        try:
            for aid in self.tk.call("after", "info"):
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        self.quit()
        self.destroy()


def hand_over(win, files, status=None):
    """Give files to an analysis window that is already up: windows that take a
    file list get all of them, single-file windows the first one."""
    try:
        if not win.winfo_exists():
            return
        if hasattr(win, "load_paths"):
            win.load_paths(list(files))
        elif hasattr(win, "open_path"):
            win.open_path(files[0])
            if len(files) > 1 and status is not None:
                status(f"Opened {os.path.basename(files[0])}; this tool takes one file at a time "
                       "(Compare selected overlays several).")
        elif hasattr(win, "directory_path"):
            win.directory_path.set(files[0] if os.path.isdir(files[0]) else os.path.dirname(files[0]))
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Open data", f"The file could not be loaded:\n{e}")


def make_update_app(selfupdate):
    return selfupdate.App(repo="jongsu-king/physiscore", name="Physiscore",
                          version=APP_VERSION, env_prefix="PHYSISCORE")


def selftest(out=None) -> int:
    """Headless check used by the installer builds: import every analysis core and
    GUI module and compute reference quantities of synthetic data."""
    import numpy as np
    result = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), "imports": {}}
    for mod in ("scripts.common.spectral", "scripts.common.vibrational", "scripts.JV.jv_core",
                "scripts.Dark_JV.dark_jv_core", "scripts.EQE.eqe_core", "scripts.Abs.abs_core",
                "scripts.PL.pl_core", "scripts.XRD.xrd_core", "scripts.SEM.sem_core", "spectra.core.xps",
                "scripts.common.device_summary", "scripts.common.batch", "scripts.common.iv_io",
                "scripts.common.provenance", "scripts.Device.run_device", "scripts.common.compare_window",
                "scripts.JV.run_jv", "scripts.Dark_JV.run_jv_dark", "scripts.EQE.run_eqe",
                "scripts.SEM.run_sem", "scripts.Abs.run_abs", "scripts.Raman.run_raman",
                "scripts.FTIR.run_ftir", "scripts.XRD.run_xrd", "scripts.PL.run_pl", "spectra.app",
                "scripts.SCLC.sclc_core", "scripts.Intensity.intensity_core", "scripts.TRPL.trpl_core",
                "scripts.EIS.eis_core", "scripts.CV.cv_core", "scripts.Stability.stability_core",
                "scripts.common.curve_io", "scripts.common.interpret_transport", "scripts.common.detect",
                "scripts.common.results_index", "scripts.common.plot_tools", "scripts.common.curve_tool",
                "scripts.common.workspace_panel", "scripts.SCLC.run_sclc", "scripts.Intensity.run_intensity",
                "scripts.TRPL.run_trpl", "scripts.EIS.run_eis", "scripts.CV.run_cv",
                "scripts.Stability.run_stability"):
        try:
            importlib.import_module(mod)
            result["imports"][mod] = "ok"
        except Exception as e:  # noqa: BLE001
            result["imports"][mod] = f"failed: {e!r}"
    checks = {}
    try:
        from scripts.JV.jv_core import compute_jv_parameters, fit_single_diode, single_diode_current
        v = np.linspace(-0.2, 1.1, 261)
        j = single_diode_current(v, 22.0, 1e-9, 1.5, 2.0, 2000.0)
        p = compute_jv_parameters(v, j, pin_mw_cm2=100.0)
        fit = fit_single_diode(v, j)
        checks["jv"] = {k: float(p[k]) for k in ("Voc", "Jsc", "FF", "PCE")}
        checks["jv"]["n_fit"] = float(fit["n"])
        checks["jv_ok"] = bool(p["PCE"] > 0 and abs(fit["n"] - 1.5) < 0.1)
    except Exception as e:  # noqa: BLE001
        checks["jv"] = f"failed: {e!r}"
        checks["jv_ok"] = False
    try:
        from scripts.EQE.eqe_core import shockley_queisser
        sq = shockley_queisser(1.34)
        checks["sq_1p34eV"] = {k: float(sq[k]) for k in ("Jsc_SQ", "Voc_SQ", "PCE_SQ")}
        checks["sq_ok"] = bool(32.5 < sq["PCE_SQ"] < 34.5)
    except Exception as e:  # noqa: BLE001
        checks["sq_1p34eV"] = f"failed: {e!r}"
        checks["sq_ok"] = False
    try:
        # transport and recombination tools (3.5): each core recovers the parameters
        # its own synthetic data were made with
        from scripts.SCLC import sclc_core as _sc
        from scripts.CV import cv_core as _cc
        from scripts.EIS import eis_core as _ec
        from scripts.TRPL import trpl_core as _tc
        from scripts.Intensity import intensity_core as _ic
        from scripts.Stability import stability_core as _st
        tr = {}
        v, j = _sc.simulate(thickness_nm=500, eps_r=25, mobility_cm2_Vs=1.0, n_t_cm3=5e16, n0_cm3=1e13)
        r = _sc.analyse(v, j, thickness_nm=500, eps_r=25)
        tr["sclc_n_t_cm3"] = float(r["n_t_cm3"])
        v, c = _cc.simulate(n_cm3=1e17, v_bi=0.9, eps_r=25.0, area_cm2=0.1)
        r = _cc.analyse(v, c, area_cm2=0.1, eps_r=25.0)
        tr["cv_N_cm3"], tr["cv_Vbi_V"] = float(r["N_cm3"]), float(r["V_bi"])
        f, zre, zim = _ec.simulate(model="R(RQ)")
        r = _ec.analyse(f, zre, zim)
        tr["eis_rms_pct"], tr["eis_model"] = float(r["rms_pct"]), str(r["model"])
        t, y = _tc.simulate(taus=(5.0, 60.0), amps=(0.7, 0.3))
        r = _tc.analyse(t, y)
        tr["trpl_model"], tr["trpl_tau_int_ns"] = str(r["model"]), float(r["tau_int"])
        d = _ic.simulate()
        r = _ic.analyse(d["intensity"], d["voc"], jsc=d["jsc"], ff=d["ff"], pce=d["pce"])
        tr["intensity_n_id"] = float(r["voc_fit"]["n_id"])
        t, y = _st.simulate()
        r = _st.analyse(t, y)
        tr["stability_model"] = str(r["model"])
        checks["transport"] = tr
        checks["transport_ok"] = bool(
            abs(tr["sclc_n_t_cm3"] / 5e16 - 1) < 0.15 and abs(tr["cv_N_cm3"] / 1e17 - 1) < 0.05
            and abs(tr["cv_Vbi_V"] - 0.9) < 0.03 and tr["eis_rms_pct"] < 2.0
            and tr["trpl_model"] == "exp2" and 1.0 < tr["intensity_n_id"] < 2.2)
    except Exception as e:  # noqa: BLE001
        checks["transport"] = f"failed: {e!r}"
        checks["transport_ok"] = False
    try:
        from scripts.common.vibrational import load_library
        checks["band_library_entries"] = len(load_library())
        checks["library_ok"] = checks["band_library_entries"] > 40
    except Exception as e:  # noqa: BLE001
        checks["band_library_entries"] = f"failed: {e!r}"
        checks["library_ok"] = False
    try:
        from scripts.common import docs_viewer
        found = [n for n in docs_viewer.DOCS if docs_viewer.doc_path(n) is not None]
        checks["docs"] = found
        checks["release_notes"] = docs_viewer.release_notes_path(APP_VERSION) is not None
        html_ok = "<table>" in docs_viewer.markdown_to_html("| a | b |\n|---|---|\n| 1 | 2 |")
        checks["docs_ok"] = bool(len(found) == len(docs_viewer.DOCS) and checks["release_notes"] and html_ok)
    except Exception as e:  # noqa: BLE001
        checks["docs"] = f"failed: {e!r}"
        checks["docs_ok"] = False
    result["checks"] = checks
    ok = (all(v == "ok" for v in result["imports"].values())
          and checks.get("jv_ok") and checks.get("sq_ok") and checks.get("library_ok") and checks.get("docs_ok")
          and checks.get("transport_ok"))
    result["ok"] = bool(ok)
    result["executable"] = sys.executable
    result["config"] = app_config.config_path()
    result["theme"] = _pal.THEME
    text = json.dumps(result, indent=2)
    if not ok:
        print(text, file=sys.stderr)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0 if ok else 1


def _open_single_tool(name: str, files=None) -> int:
    """`--tool NAME [FILE ...]`: open one analysis window without the main window."""
    match = next((t for t in TOOLS if t[0].lower() == name.lower()), None)
    if match is None:
        print("unknown tool; choose one of: " + ", ".join(t[0] for t in TOOLS), file=sys.stderr)
        return 2
    files = [os.path.abspath(f) for f in (files or []) if os.path.exists(f)]
    mod_path = match[3]
    if mod_path.startswith("spectra:"):
        from spectra.app import App as SpectraApp
        SpectraApp(start_tab=mod_path.split(":", 1)[1], data_file=files[0] if files else "").mainloop()
        return 0
    mod_path = BUILTIN_FALLBACK.get(mod_path, mod_path)
    mod = importlib.import_module(mod_path)
    root = ctk.CTk()
    root.withdraw()
    data = app_config.load(refresh=True)
    win = mod.AnalysisWindow(root, data.get("origin_path", ""))

    def close():
        # pending timers of the window would otherwise fire on a destroyed interpreter
        try:
            for aid in root.tk.call("after", "info"):
                try:
                    root.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        root.quit()
        root.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    if files:
        win.after(350, lambda: hand_over(win, files))
    root.mainloop()
    return 0


def _open_detected(paths) -> int:
    """`--open FILE ... | FOLDER`: a folder opens the main window with that
    workspace; files open in the tool their measurement belongs to."""
    from scripts.common import detect
    paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
    if not paths:
        print("--open needs an existing file or folder", file=sys.stderr)
        return 2
    if os.path.isdir(paths[0]):
        LauncherApp(workspace=paths[0]).mainloop()
        return 0
    ds = [detect.detect_file(p) for p in paths if os.path.isfile(p)]
    first = ds[0]
    if not first.kind:
        print(f"{first.name}: measurement not recognised; name the tool with --tool NAME FILE", file=sys.stderr)
        return 2
    print(f"{first.name}: {first.label} ({first.confidence} confidence; {first.why()}) -> {first.tool}")
    return _open_single_tool(first.tool, [d.path for d in ds if d.kind == first.kind])


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"Physiscore {APP_VERSION}")
        sys.exit(0)
    if "--selftest" in sys.argv:
        _out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
        sys.exit(selftest(_out))
    if "--doc" in sys.argv:
        _i = sys.argv.index("--doc")
        from scripts.common import docs_viewer as _dv
        sys.exit(0 if _dv.open_doc(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "USER_GUIDE") else 1)
    if "--update" in sys.argv:
        import selfupdate
        sys.exit(selfupdate.cli(selfupdate.Updater(make_update_app(selfupdate))))
    if "--spectra" in sys.argv:
        _i = sys.argv.index("--spectra")
        _tab = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "PL"
        _file = sys.argv[_i + 2] if len(sys.argv) > _i + 2 and not sys.argv[_i + 2].startswith("--") else ""
        try:
            from spectra.app import App as SpectraApp
            SpectraApp(start_tab=_tab, data_file=_file).mainloop()
        except Exception as e:
            print(f"spectra run failed: {e}")
        sys.exit(0)
    if "--tool" in sys.argv:
        _i = sys.argv.index("--tool")
        _rest = [a for a in sys.argv[_i + 2:] if not a.startswith("--")]
        sys.exit(_open_single_tool(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "", _rest))
    if "--open" in sys.argv:
        _i = sys.argv.index("--open")
        sys.exit(_open_detected([a for a in sys.argv[_i + 1:] if not a.startswith("--")]))
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    app = LauncherApp()
    app.mainloop()
