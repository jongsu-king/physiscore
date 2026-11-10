# gui/tab_dashboard.py
# ------------------------------------------------------------
# Auto-fit workspace tab (XRD / PL / XPS): parameters, run, export, batch, report
#
# requires:
#   pip install customtkinter matplotlib numpy pandas openpyxl
#   (pipeline deps) scipy pybaselines lmfit pydantic
# ------------------------------------------------------------

from __future__ import annotations

import os
import time
import threading
from typing import Optional, List

import numpy as np
import pandas as pd

import customtkinter as ctk

import matplotlib
try:  # the Tk canvas is embedded explicitly; a headless test run keeps its own backend
    matplotlib.use("TkAgg")
except ImportError:
    pass
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from scripts.common import app_config
from scripts.common import theme as _theme
from spectra.core.config import PipelineConfig
from spectra.core.utils import safe_sorted_xy, robust_read_csv

from spectra.pipelines.run_xrd import run_xrd_pipeline
from spectra.pipelines.run_pl import run_pl_pipeline
from spectra.pipelines.run_xps import run_xps_pipeline

from spectra.core.report import generate_ai_peak_report
from scripts.common import palette as _pal



def _resolve_api_key() -> str | None:
    """Environment first, then physisfera_config.json - see app_config.api_key.

    The local copy this replaced walked three directories up from spectra/gui/,
    one level above the project root, so a key in the config was never found.
    """
    return app_config.api_key()

# -------------------------
# Theme (you can tweak)
# -------------------------
COL_BG   = _pal.BG_WINDOW
COL_CARD = _pal.BG_CARD
COL_CARD2 = _pal.BG_SUB
COL_STROKE = _pal.BORDER
COL_TXT  = _pal.TXT
COL_MUT  = _pal.TXT_SUB

COL_ACC  = _pal.ACCENT
COL_OK   = _pal.GREEN
COL_WARN = _pal.ORANGE
COL_ERR  = _pal.RED

COL_RUN  = _pal.ACCENT
COL_RUN_H = _pal.ACCENT_HOV


class SpectraDashboardTab(ctk.CTkFrame):
    def __init__(self, master, name: str, defaults: PipelineConfig):
        super().__init__(master, fg_color=COL_BG)
        self.name = name
        self.cfg_default = defaults

        # data state
        self.file_path: Optional[str] = None
        self.df: Optional[pd.DataFrame] = None
        self.x: Optional[np.ndarray] = None
        self.y: Optional[np.ndarray] = None

        self.proc: Optional[pd.DataFrame] = None
        self.cand: Optional[pd.DataFrame] = None
        self.fitted: Optional[pd.DataFrame] = None

        # Excel sheet state
        self.excel_sheets: List[str] = []
        self.selected_sheet: Optional[str] = None

        # ----- Vars (restore full parameters) -----
        self.var_sg_window = ctk.IntVar(value=self.cfg_default.sg_window)
        self.var_sg_poly   = ctk.IntVar(value=self.cfg_default.sg_poly)
        self.var_lam       = ctk.DoubleVar(value=self.cfg_default.als_lam)
        self.var_p         = ctk.DoubleVar(value=self.cfg_default.als_p)

        self.var_use_noise_prom = ctk.IntVar(value=1 if self.cfg_default.use_noise_based_prominence else 0)
        self.var_noise_k        = ctk.DoubleVar(value=self.cfg_default.noise_k)
        self.var_min_sep_x      = ctk.DoubleVar(value=self.cfg_default.min_peak_separation_x)

        # AI
        self.var_use_gemini = ctk.IntVar(value=1 if self.cfg_default.use_gemini else 0)
        self.var_model      = ctk.StringVar(value=self.cfg_default.gemini_model)

        # PL
        self.var_pl_aic     = ctk.IntVar(value=1 if self.cfg_default.pl_enable_aic else 0)
        self.var_pl_maxp    = ctk.IntVar(value=self.cfg_default.pl_max_peaks)
        self.var_pl_fwhm_th = ctk.DoubleVar(value=self.cfg_default.pl_defect_fwhm_threshold)

        # plot toggles
        self.var_before_after = ctk.IntVar(value=1)
        self.var_show_only_fitted = ctk.IntVar(value=0)
        self.preview_mode = ctk.StringVar(value="Corrected")

        self._build_layout()
        self._refresh_buttons()
        self._plot_empty()
        try:
            from scripts.common.analysis_shell import make_thread_safe
            make_thread_safe(self)
        except Exception:
            pass


    # -------------------------
    # UI helpers
    # -------------------------
    def _card(self, parent, title: str):
        outer = ctk.CTkFrame(parent, fg_color=COL_CARD, corner_radius=_pal.R_CARD, border_width=1, border_color=COL_STROKE)
        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text=title, text_color=COL_TXT, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=10)
        return outer

    def _log(self, msg: str):
        # Thread-safe logging: _log is used as log_cb inside pipeline worker
        # threads; mutating tk widgets from a non-main thread crashes or
        # freezes tkinter intermittently, so marshal through after().
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"

        def _append():
            try:
                self.txt_log.configure(state="normal")
                self.txt_log.insert("end", line)
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            try:
                self.after(0, _append)
            except Exception:
                pass

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # ============ LEFT ============
        self.left = ctk.CTkFrame(self, fg_color="transparent")
        self.left.grid(row=0, column=0, sticky="nsw", padx=(12, 10), pady=12)
        self.left.grid_rowconfigure(99, weight=1)

        # Load/Actions card
        self.card_actions = self._card(self.left, "Actions")
        self.card_actions.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_actions_card(self.card_actions)

        # Parameters
        self.card_params = self._card(self.left, "Parameters")
        self.card_params.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._build_params_card(self.card_params)

        # AI
        self.card_ai = self._card(self.left, "Interpretation (Gemini, optional)")
        self.card_ai.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._build_ai_card(self.card_ai)

        # Status
        self.card_status = self._card(self.left, "Status")
        self.card_status.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._build_status_card(self.card_status)

        # ============ CENTER ============
        self.center = ctk.CTkFrame(self, fg_color="transparent")
        self.center.grid(row=0, column=1, sticky="nsew", padx=10, pady=12)
        self.center.grid_rowconfigure(1, weight=1)
        self.center.grid_columnconfigure(0, weight=1)

        # title bar
        self.center_top = ctk.CTkFrame(self.center, fg_color="transparent")
        self.center_top.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 8))
        self.center_top.grid_columnconfigure(0, weight=1)

        self.center_title = ctk.CTkLabel(
            self.center_top,
            text=f"{self.name} Spectrum",
            text_color=COL_TXT,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.center_title.grid(row=0, column=0, sticky="w")

        # plot card
        self.plot_card = ctk.CTkFrame(self.center, fg_color=COL_CARD, corner_radius=_pal.R_CARD, border_width=1, border_color=COL_STROKE)
        self.plot_card.grid(row=1, column=0, sticky="nsew")
        self.plot_card.grid_rowconfigure(1, weight=1)
        self.plot_card.grid_columnconfigure(0, weight=1)

        # plot toolbar
        self.plot_bar = ctk.CTkFrame(self.plot_card, fg_color="transparent")
        self.plot_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        self.plot_bar.grid_columnconfigure(99, weight=1)

        self.chk_before_after = ctk.CTkCheckBox(
            self.plot_bar, text="Before / After",
            variable=self.var_before_after, text_color=COL_TXT, fg_color=COL_ACC,
            command=self._plot
        )
        self.chk_before_after.grid(row=0, column=0, padx=(0, 14), pady=0, sticky="w")

        self.chk_only_fit = ctk.CTkCheckBox(
            self.plot_bar, text="Show only fitted",
            variable=self.var_show_only_fitted, text_color=COL_TXT, fg_color=COL_ACC,
            command=self._plot
        )
        self.chk_only_fit.grid(row=0, column=1, padx=(0, 14), pady=0, sticky="w")

        ctk.CTkLabel(self.plot_bar, text="Preview", text_color=COL_MUT).grid(row=0, column=2, padx=(8, 6), sticky="w")
        self.opt_preview = ctk.CTkOptionMenu(
            self.plot_bar,
            values=["Raw", "Smooth", "Baseline", "Corrected"],
            variable=self.preview_mode,
            command=lambda _v: self._plot()
        )
        self.opt_preview.configure(fg_color=COL_CARD2, button_color=COL_CARD2, button_hover_color=COL_STROKE)
        self.opt_preview.grid(row=0, column=3, padx=(0, 10), sticky="w")

        # matplotlib
        self.fig = Figure(figsize=(6, 4.8), dpi=100)
        self.fig.patch.set_facecolor(COL_CARD2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_card)
        w = self.canvas.get_tk_widget()
        w.grid(row=1, column=0, sticky="nsew", padx=14, pady=14)

        # ============ RIGHT ============
        self.right = ctk.CTkFrame(self, fg_color="transparent")
        self.right.grid(row=0, column=2, sticky="nse", padx=(10, 12), pady=12)
        self.right.grid_rowconfigure(98, weight=1)

        self.card_summary = self._card(self.right, "Quick Summary")
        self.card_summary.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_summary_card(self.card_summary)

        self.card_log = self._card(self.right, "Log")
        self.card_log.grid(row=1, column=0, sticky="nsew")
        self._build_log_card(self.card_log)


    # -------------------------
    # LEFT cards
    # -------------------------
    def _build_actions_card(self, card):
        body = card.winfo_children()[1]
        body.grid_columnconfigure(0, weight=1)

        # file row
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 8))
        row.grid_columnconfigure(0, weight=1)

        self.ent_path = ctk.CTkEntry(row, fg_color=COL_CARD2, placeholder_text="Select CSV / Excel...")
        self.ent_path.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn_browse = ctk.CTkButton(row, text="...", width=40, command=self.load_data, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_browse.grid(row=0, column=1)

        # excel sheet selector (hidden unless excel)
        sheet_row = ctk.CTkFrame(body, fg_color="transparent")
        sheet_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 10))
        sheet_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(sheet_row, text="Sheet", text_color=COL_MUT).grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.var_sheet = ctk.StringVar(value="")
        self.opt_sheet = ctk.CTkOptionMenu(sheet_row, values=[""], variable=self.var_sheet)
        self.opt_sheet.configure(fg_color=COL_CARD2, button_color=COL_CARD2, button_hover_color=COL_STROKE)
        self.opt_sheet.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.btn_sheet_apply = ctk.CTkButton(sheet_row, text="Apply", width=70, command=self.reload_selected_sheet, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_sheet_apply.grid(row=0, column=2, sticky="e")

        # action buttons
        self.btn_run = ctk.CTkButton(body, text="Run", command=self.run_clicked, fg_color=COL_ACC, hover_color=_pal.ACCENT_HOV, text_color="white")
        self.btn_run.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 8))

        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 0))
        grid.grid_columnconfigure((0, 1), weight=1)

        self.btn_save = ctk.CTkButton(grid, text="Save outputs...", command=self.save_outputs, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_save.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        self.btn_excel = ctk.CTkButton(grid, text="Export Excel", command=self.export_excel, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_excel.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))

        self.btn_batch = ctk.CTkButton(grid, text="Batch Folder", command=self.batch_folder, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_batch.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        self.btn_report = ctk.CTkButton(grid, text="Peak report", command=self.make_report, fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
        self.btn_report.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        if self.cfg_default.technique == "XPS":
            self.btn_quant = ctk.CTkButton(grid, text="Quantify (atomic %)...", command=self.quantify_dialog,
                                           fg_color=COL_CARD2, hover_color=COL_STROKE, text_color=_pal.TXT)
            self.btn_quant.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # hide sheet selector initially
        self._set_sheet_ui(False)

    def _build_params_card(self, card):
        body = card.winfo_children()[1]
        body.grid_columnconfigure(1, weight=1)

        def row(r, label, entry):
            ctk.CTkLabel(body, text=label, text_color=COL_MUT).grid(row=r, column=0, padx=10, pady=6, sticky="w")
            entry.grid(row=r, column=1, padx=10, pady=6, sticky="ew")

        self.ent_sg_w = ctk.CTkEntry(body, fg_color=COL_CARD2); self.ent_sg_w.insert(0, str(self.var_sg_window.get()))
        self.ent_sg_p = ctk.CTkEntry(body, fg_color=COL_CARD2); self.ent_sg_p.insert(0, str(self.var_sg_poly.get()))
        row(0, "SG window", self.ent_sg_w)
        row(1, "SG poly",   self.ent_sg_p)

        self.ent_lam = ctk.CTkEntry(body, fg_color=COL_CARD2); self.ent_lam.insert(0, f"{self.var_lam.get():g}")
        self.ent_p   = ctk.CTkEntry(body, fg_color=COL_CARD2); self.ent_p.insert(0,   f"{self.var_p.get():g}")
        row(2, "AsLS lam", self.ent_lam)
        row(3, "AsLS p",   self.ent_p)

        self.chk_noise = ctk.CTkCheckBox(
            body, text="Noise(MAD) prominence",
            variable=self.var_use_noise_prom, text_color=COL_TXT, fg_color=COL_ACC
        )
        self.chk_noise.grid(row=4, column=0, columnspan=2, padx=10, pady=(8, 2), sticky="w")

        line = ctk.CTkFrame(body, fg_color=COL_CARD2, corner_radius=_pal.R_CARD)
        line.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        line.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(line, text="k", text_color=COL_MUT).grid(row=0, column=0, padx=(10, 4), pady=8, sticky="w")
        self.ent_k = ctk.CTkEntry(line, fg_color=COL_CARD, width=90); self.ent_k.insert(0, f"{self.var_noise_k.get():g}")
        self.ent_k.grid(row=0, column=1, padx=(0, 10), pady=8, sticky="ew")

        ctk.CTkLabel(line, text="Min sep (x)", text_color=COL_MUT).grid(row=0, column=2, padx=(10, 4), pady=8, sticky="w")
        self.ent_sep = ctk.CTkEntry(line, fg_color=COL_CARD, width=90); self.ent_sep.insert(0, f"{self.var_min_sep_x.get():g}")
        self.ent_sep.grid(row=0, column=3, padx=(0, 10), pady=8, sticky="ew")

        # XPS block: background, charge referencing, doublet constraints, region of interest
        if self.cfg_default.technique == "XPS":
            xp = ctk.CTkFrame(body, fg_color=COL_CARD2, corner_radius=_pal.R_CARD)
            xp.grid(row=6, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
            xp.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(xp, text="Background", text_color=COL_MUT).grid(row=0, column=0, padx=10, pady=(8, 4), sticky="w")
            self.var_xps_bg = ctk.StringVar(value=self.cfg_default.xps_background)
            ctk.CTkOptionMenu(xp, values=["shirley", "asls"], variable=self.var_xps_bg, width=110, height=24,
                              fg_color=COL_CARD, button_color=COL_CARD, button_hover_color=COL_STROKE).grid(row=0, column=1, padx=10, pady=(8, 4), sticky="e")
            ctk.CTkLabel(xp, text="Charge shift (eV, added to BE)", text_color=COL_MUT).grid(row=1, column=0, padx=10, pady=4, sticky="w")
            self.ent_xps_shift = ctk.CTkEntry(xp, fg_color=COL_CARD, width=90); self.ent_xps_shift.insert(0, "0.0")
            self.ent_xps_shift.grid(row=1, column=1, padx=10, pady=4, sticky="e")
            ctk.CTkLabel(xp, text="Doublet split (eV; 0 = singlet)", text_color=COL_MUT).grid(row=2, column=0, padx=10, pady=4, sticky="w")
            self.ent_xps_split = ctk.CTkEntry(xp, fg_color=COL_CARD, width=90); self.ent_xps_split.insert(0, f"{self.cfg_default.xps_split_ev:g}")
            self.ent_xps_split.grid(row=2, column=1, padx=10, pady=4, sticky="e")
            ctk.CTkLabel(xp, text="Doublet area ratio (minor/major)", text_color=COL_MUT).grid(row=3, column=0, padx=10, pady=4, sticky="w")
            self.ent_xps_ratio = ctk.CTkEntry(xp, fg_color=COL_CARD, width=90); self.ent_xps_ratio.insert(0, f"{self.cfg_default.xps_area_ratio:g}")
            self.ent_xps_ratio.grid(row=3, column=1, padx=10, pady=4, sticky="e")
            ctk.CTkLabel(xp, text="Region of interest (eV, lo-hi)", text_color=COL_MUT).grid(row=4, column=0, padx=10, pady=(4, 8), sticky="w")
            self.ent_xps_roi = ctk.CTkEntry(xp, fg_color=COL_CARD, width=90, placeholder_text="e.g. 280-292")
            self.ent_xps_roi.grid(row=4, column=1, padx=10, pady=(4, 8), sticky="e")
            ctk.CTkLabel(xp, text="Typical splits: Pb4f 4.87 (3/4), I3d 11.5 (2/3), Ti2p 5.7 (1/2), Sn3d 8.41 (2/3), S2p 1.18 (1/2)",
                         text_color=COL_MUT, font=ctk.CTkFont(size=10), wraplength=300, justify="left").grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        # PL block
        if self.cfg_default.technique == "PL":
            pl = ctk.CTkFrame(body, fg_color=COL_CARD2, corner_radius=_pal.R_CARD)
            pl.grid(row=6, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
            pl.grid_columnconfigure(1, weight=1)

            self.chk_pl_aic = ctk.CTkCheckBox(pl, text="PL AIC select", variable=self.var_pl_aic, text_color=COL_TXT, fg_color=COL_ACC)
            self.chk_pl_aic.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")

            ctk.CTkLabel(pl, text="Max peaks", text_color=COL_MUT).grid(row=1, column=0, padx=10, pady=6, sticky="w")
            self.ent_pl_max = ctk.CTkEntry(pl, fg_color=COL_CARD, width=90); self.ent_pl_max.insert(0, str(self.var_pl_maxp.get()))
            self.ent_pl_max.grid(row=1, column=1, padx=10, pady=6, sticky="ew")

            ctk.CTkLabel(pl, text="Defect FWHM thr", text_color=COL_MUT).grid(row=2, column=0, padx=10, pady=(6, 10), sticky="w")
            self.ent_pl_thr = ctk.CTkEntry(pl, fg_color=COL_CARD, width=90); self.ent_pl_thr.insert(0, f"{self.var_pl_fwhm_th.get():g}")
            self.ent_pl_thr.grid(row=2, column=1, padx=10, pady=(6, 10), sticky="ew")

    def _build_ai_card(self, card):
        body = card.winfo_children()[1]
        body.grid_columnconfigure(1, weight=1)

        self.chk_ai = ctk.CTkCheckBox(
            body, text="Add Gemini commentary to the report",
            variable=self.var_use_gemini, text_color=COL_TXT, fg_color=COL_ACC
        )
        self.chk_ai.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")

        ctk.CTkLabel(body, text="Model", text_color=COL_MUT).grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")
        self.ent_model = ctk.CTkEntry(body, fg_color=COL_CARD2)
        self.ent_model.insert(0, str(self.var_model.get()))
        self.ent_model.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")

        key = _resolve_api_key()
        st = "API key: OK" if key else "API key: MISSING"
        col = COL_OK if key else COL_WARN
        self.lbl_key = ctk.CTkLabel(body, text=st, text_color=col)
        self.lbl_key.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

    def _build_status_card(self, card):
        body = card.winfo_children()[1]
        body.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(body, text="Ready", text_color=COL_OK)
        self.lbl_status.grid(row=0, column=0, padx=10, pady=(6, 2), sticky="w")

        self.pb = ctk.CTkProgressBar(body)
        self.pb.configure(progress_color=COL_ACC)
        self.pb.grid(row=1, column=0, padx=10, pady=(2, 10), sticky="ew")
        self.pb.set(0)

    # -------------------------
    # RIGHT cards
    # -------------------------
    def _build_summary_card(self, card):
        body = card.winfo_children()[1]
        body.grid_columnconfigure(1, weight=1)

        self.lbl_file = ctk.CTkLabel(body, text="File: -", text_color=COL_MUT)
        self.lbl_file.grid(row=0, column=0, columnspan=2, padx=10, pady=(6, 6), sticky="w")

        ctk.CTkLabel(body, text="Candidates", text_color=COL_MUT).grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.val_cand = ctk.CTkLabel(body, text="-", text_color=COL_TXT)
        self.val_cand.grid(row=1, column=1, padx=10, pady=6, sticky="e")

        ctk.CTkLabel(body, text="Fitted peaks", text_color=COL_MUT).grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.val_fit = ctk.CTkLabel(body, text="-", text_color=COL_TXT)
        self.val_fit.grid(row=2, column=1, padx=10, pady=6, sticky="e")

        ctk.CTkLabel(body, text="Output dir", text_color=COL_MUT).grid(row=3, column=0, padx=10, pady=6, sticky="w")
        self.val_out = ctk.CTkLabel(body, text="-", text_color=COL_TXT, wraplength=260, justify="left")
        self.val_out.grid(row=3, column=1, padx=10, pady=6, sticky="w")

    def _build_log_card(self, card):
        body = card.winfo_children()[1]
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.txt_log = ctk.CTkTextbox(body, fg_color=COL_CARD2, text_color=COL_TXT)
        self.txt_log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.txt_log.configure(state="disabled")


    # -------------------------
    # Sheet UI
    # -------------------------
    def _set_sheet_ui(self, enabled: bool, sheets: Optional[List[str]] = None):
        if not enabled:
            self.opt_sheet.configure(values=[""])
            self.var_sheet.set("")
            self.opt_sheet.configure(state="disabled")
            self.btn_sheet_apply.configure(state="disabled")
            return
        if sheets is None:
            sheets = [""]
        self.opt_sheet.configure(values=sheets)
        self.opt_sheet.configure(state="normal")
        self.btn_sheet_apply.configure(state="normal")

    def _load_excel_sheetnames(self, path: str) -> List[str]:
        xls = pd.ExcelFile(path)
        return list(xls.sheet_names)

    def reload_selected_sheet(self):
        if not self.file_path:
            return
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext not in [".xlsx", ".xls"]:
            return
        sheet = str(self.var_sheet.get()).strip()
        if not sheet:
            self._log("Select a sheet first.")
            return
        try:
            self._log(f"Reload Excel: sheet='{sheet}'")
            self._load_file(self.file_path, sheet_name=sheet)
        except Exception as e:
            self._log(f"[ERR] Sheet load: {e}")


    # -------------------------
    # Config from UI (IMPORTANT)
    # -------------------------
    def _cfg_from_ui(self) -> PipelineConfig:
        cfg = PipelineConfig(**self.cfg_default.__dict__)

        # common
        cfg.sg_window = int(self.ent_sg_w.get())
        cfg.sg_poly   = int(self.ent_sg_p.get())
        cfg.als_lam   = float(self.ent_lam.get())
        cfg.als_p     = float(self.ent_p.get())

        cfg.use_noise_based_prominence = (int(self.var_use_noise_prom.get()) == 1)
        cfg.noise_k = float(self.ent_k.get())
        cfg.min_peak_separation_x = float(self.ent_sep.get())

        # AI
        cfg.use_gemini = (int(self.var_use_gemini.get()) == 1)
        cfg.gemini_model = str(self.ent_model.get()).strip() or cfg.gemini_model

        if cfg.technique == "PL":
            cfg.pl_enable_aic = (int(self.var_pl_aic.get()) == 1)
            cfg.pl_max_peaks  = int(self.ent_pl_max.get())
            cfg.pl_defect_fwhm_threshold = float(self.ent_pl_thr.get())
        else:
            cfg.pl_enable_aic = False
        if cfg.technique == "XPS":
            cfg.xps_background = str(self.var_xps_bg.get())
            try:
                cfg.xps_charge_shift_ev = float(self.ent_xps_shift.get() or 0.0)
            except ValueError:
                cfg.xps_charge_shift_ev = 0.0
            try:
                cfg.xps_split_ev = float(self.ent_xps_split.get() or 0.0)
                cfg.xps_area_ratio = float(self.ent_xps_ratio.get() or 0.5)
            except ValueError:
                pass
            roi = self.ent_xps_roi.get().replace(" ", "")
            if "-" in roi:
                try:
                    lo, hi = roi.split("-", 1)
                    cfg.xps_roi_min, cfg.xps_roi_max = float(lo), float(hi)
                except ValueError:
                    cfg.xps_roi_min = cfg.xps_roi_max = 0.0
            else:
                cfg.xps_roi_min = cfg.xps_roi_max = 0.0

        return cfg


    # -------------------------
    # Load file
    # -------------------------
    def load_data(self):
        # lazy import to avoid forcing tkinter in CTk root init
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title=f"Load {self.name} data (CSV / Excel)",
            filetypes=[
                ("Data files", "*.csv *.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()

        if not path:
            return

        try:
            self.file_path = path
            self.ent_path.delete(0, "end")
            self.ent_path.insert(0, path)

            ext = os.path.splitext(path)[1].lower()

            if ext in [".xlsx", ".xls"]:
                sheets = self._load_excel_sheetnames(path)
                self.excel_sheets = sheets
                self._set_sheet_ui(True, sheets=sheets)

                default_sheet = sheets[0] if sheets else ""
                self.var_sheet.set(default_sheet)
                self.selected_sheet = default_sheet if default_sheet else None

                self._load_file(path, sheet_name=default_sheet if default_sheet else 0)
            else:
                self.excel_sheets = []
                self.selected_sheet = None
                self._set_sheet_ui(False)
                self._load_file(path, sheet_name=None)

        except Exception as e:
            self._log(f"[ERR] Load: {e}")

        self._refresh_buttons()

    def _load_file(self, path: str, sheet_name: Optional[str] = None):
        ext = os.path.splitext(path)[1].lower()

        if ext == ".csv":
            # robust: handles instrument exports (e.g. Thermo XPS) that put
            # metadata lines before the numeric block
            df = robust_read_csv(path)
        elif ext in [".xlsx", ".xls"]:
            use_sheet = sheet_name if sheet_name not in [None, ""] else 0
            df = pd.read_excel(path, sheet_name=use_sheet)
        else:
            raise ValueError("Supported: .csv, .xlsx, .xls")

        if df.shape[1] < 2:
            raise ValueError("Need at least 2 columns (x, y).")

        x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(dtype=float)
        x, y = safe_sorted_xy(x, y)

        self.df = df
        self.x, self.y = x, y
        self.proc = self.cand = self.fitted = None

        self.lbl_file.configure(text=f"File: {os.path.basename(path)}")
        self.val_cand.configure(text="-")
        self.val_fit.configure(text="-")
        self.val_out.configure(text="-")

        sm = f" | sheet={sheet_name}" if ext in [".xlsx", ".xls"] else ""
        self._log(f"Loaded: {os.path.basename(path)} (N={len(x)}){sm}")
        self._plot_raw()


    # -------------------------
    # Dispatch pipelines
    # -------------------------
    def _run_dispatch(self, cfg: PipelineConfig, outdir: str):
        if cfg.technique == "XRD":
            return run_xrd_pipeline(self.x, self.y, outdir, cfg, log_cb=self._log)
        if cfg.technique == "PL":
            return run_pl_pipeline(self.x, self.y, outdir, cfg, log_cb=self._log)
        if cfg.technique == "XPS":
            return run_xps_pipeline(self.x, self.y, outdir, cfg, log_cb=self._log)
        raise ValueError("Unknown technique")


    # -------------------------
    # Buttons enable/disable
    # -------------------------
    def _refresh_buttons(self):
        has_data = (self.x is not None and self.y is not None)
        self.btn_run.configure(state="normal" if has_data else "disabled")
        self.btn_save.configure(state="normal" if (self.proc is not None) else "disabled")
        self.btn_excel.configure(state="normal" if (self.proc is not None) else "disabled")
        self.btn_report.configure(state="normal" if (self.fitted is not None) else "disabled")


    # -------------------------
    # RUN (RED) + save/export/batch/report
    # -------------------------
    def run_clicked(self):
        if self.x is None or self.y is None:
            return

        cfg = self._cfg_from_ui()
        base = os.path.splitext(os.path.basename(self.file_path or f"{self.name}.csv"))[0]
        outdir = os.path.join(os.path.dirname(self.file_path or os.getcwd()), f"{base}_{self.name}_out")
        os.makedirs(outdir, exist_ok=True)

        self.pb.set(0.12)
        self.lbl_status.configure(text="Running...", text_color=COL_WARN)
        self._log(f"RUN → {outdir}")

        def worker():
            try:
                proc, cand, fitted = self._run_dispatch(cfg, outdir)
                self.proc, self.cand, self.fitted = proc, cand, fitted

                # auto report
                self._log("Generating peak report...")
                rp = generate_ai_peak_report(
                    proc=proc, cand=cand, fitted=fitted, cfg=cfg,
                    outdir=outdir,
                    file_label=os.path.basename(self.file_path or ""),
                    log_cb=self._log
                )
                self._log(f"Report saved: {rp}")

                self.after(0, lambda: self.val_cand.configure(text=str(0 if cand is None else len(cand))))
                self.after(0, lambda: self.val_fit.configure(text=str(0 if fitted is None else len(fitted))))
                self.after(0, lambda: self.val_out.configure(text=outdir))

                self.after(0, self._plot)
                self.after(0, self._refresh_buttons)
                self.after(0, lambda: self.pb.set(1.0))
                self.after(0, lambda: self.lbl_status.configure(text="Done", text_color=COL_OK))
                self._log("Finished.")
            except Exception as e:
                self.after(0, lambda: self.pb.set(0))
                self.after(0, lambda: self.lbl_status.configure(text="Error", text_color=COL_ERR))
                self._log(f"[ERR] Run: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def save_outputs(self):
        if self.proc is None:
            return

        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        outdir = filedialog.askdirectory(title=f"Select output folder for {self.name}")
        root.destroy()

        if not outdir:
            return
        os.makedirs(outdir, exist_ok=True)

        try:
            self.proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)
            if self.cand is not None:
                self.cand.to_csv(os.path.join(outdir, "peaks_candidates.csv"), index=False)
            if self.fitted is not None:
                self.fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)

            figpath = os.path.join(outdir, "plot.png")
            self.fig.savefig(figpath, dpi=220, facecolor=COL_CARD2)

            self._log(f"Saved outputs → {outdir}")
        except Exception as e:
            self._log(f"[ERR] Save: {e}")

    def export_excel(self):
        if self.proc is None:
            return

        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        path = filedialog.asksaveasfilename(
            title=f"Save {self.name} Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        root.destroy()

        if not path:
            return

        try:
            with pd.ExcelWriter(path) as w:
                self.proc.to_excel(w, "processed", index=False)
                if self.cand is not None:
                    self.cand.to_excel(w, "candidates", index=False)
                if self.fitted is not None:
                    self.fitted.to_excel(w, "fitted", index=False)
            self._log(f"Excel saved: {path}")
        except Exception as e:
            self._log(f"[ERR] Export Excel: {e}")

    def make_report(self):
        if self.proc is None or self.fitted is None:
            return

        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        outdir = filedialog.askdirectory(title="Select folder to save report")
        root.destroy()

        if not outdir:
            return

        try:
            cfg = self._cfg_from_ui()
            self._log("Generating peak report...")
            rp = generate_ai_peak_report(
                proc=self.proc, cand=self.cand, fitted=self.fitted, cfg=cfg,
                outdir=outdir,
                file_label=os.path.basename(self.file_path or ""),
                log_cb=self._log
            )
            self._log(f"Report written: {rp}")
        except Exception as e:
            self._log(f"[ERR] Report: {e}")

    def quantify_dialog(self):
        """Atomic concentration from fitted peak areas with editable sensitivity factors."""
        if self.fitted is None or self.fitted.empty:
            self._log("Quantify: run the fit first.")
            return
        from spectra.core import xps as _xps
        win = ctk.CTkToplevel(self)
        win.title("Atomic concentration")
        win.geometry("640x520")
        win.configure(fg_color=COL_BG)
        ctk.CTkLabel(win, text="Assign each fitted peak to a core level (e.g. C1s, O1s, Pb4f) and give its relative "
                              "sensitivity factor. Scofield values (relative to C 1s = 1) are filled in when the "
                              "name is recognised; prefer the factors supplied with your spectrometer.",
                     text_color=COL_MUT, wraplength=600, justify="left").pack(anchor="w", padx=12, pady=(12, 6))
        frame = ctk.CTkScrollableFrame(win, fg_color=COL_CARD, height=260)
        frame.pack(fill="both", expand=True, padx=12)
        hdr = ctk.CTkFrame(frame, fg_color="transparent"); hdr.pack(fill="x")
        for text, w in (("Centre (eV)", 90), ("Area", 110), ("Core level", 120), ("RSF", 90), ("Use", 50)):
            ctk.CTkLabel(hdr, text=text, width=w, text_color=COL_MUT, anchor="w").pack(side="left", padx=4)
        rows = []
        for _, r in self.fitted.sort_values("center").iterrows():
            fr = ctk.CTkFrame(frame, fg_color="transparent"); fr.pack(fill="x", pady=1)
            ctk.CTkLabel(fr, text=f"{r['center']:.2f}", width=90, anchor="w", text_color=COL_TXT).pack(side="left", padx=4)
            ctk.CTkLabel(fr, text=f"{r['area_amplitude']:.4g}", width=110, anchor="w", text_color=COL_TXT).pack(side="left", padx=4)
            e_name = ctk.CTkEntry(fr, width=120, fg_color=COL_CARD2); e_name.pack(side="left", padx=4)
            e_rsf = ctk.CTkEntry(fr, width=90, fg_color=COL_CARD2); e_rsf.pack(side="left", padx=4)
            use = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(fr, text="", variable=use, width=40, checkbox_width=16, checkbox_height=16).pack(side="left", padx=4)

            def _autofill(_ev=None, e_name=e_name, e_rsf=e_rsf):
                base = e_name.get().strip().split("_")[0]
                if base in _xps.SCOFIELD_RSF and not e_rsf.get().strip():
                    e_rsf.insert(0, f"{_xps.SCOFIELD_RSF[base]:g}")
            e_name.bind("<FocusOut>", _autofill)
            rows.append((float(r["area_amplitude"]), e_name, e_rsf, use))
        out = ctk.CTkTextbox(win, height=120, fg_color=COL_CARD2, text_color=COL_TXT)
        out.pack(fill="x", padx=12, pady=8)

        def compute():
            areas, rsf = {}, {}
            for area, e_name, e_rsf, use in rows:
                if not use.get():
                    continue
                name = e_name.get().strip()
                if not name:
                    continue
                key = name
                k = 2
                while key in areas:
                    key = f"{name}_{k}"; k += 1
                areas[key] = area
                try:
                    if e_rsf.get().strip():
                        rsf[key] = float(e_rsf.get())
                except ValueError:
                    pass
            try:
                conc = _xps.atomic_concentration(areas, rsf)
            except ValueError as ex:
                out.configure(state="normal"); out.delete("1.0", "end"); out.insert("1.0", f"{ex}"); out.configure(state="disabled")
                return
            lines = [f"{k:12s} {v:6.2f} at.%" for k, v in conc.items()]
            out.configure(state="normal"); out.delete("1.0", "end"); out.insert("1.0", "\n".join(lines)); out.configure(state="disabled")
            self._log("Atomic concentration: " + ", ".join(f"{k} {v:.1f}%" for k, v in conc.items()))

        ctk.CTkButton(win, text="Compute", command=compute, fg_color=COL_ACC, hover_color=_pal.ACCENT_HOV).pack(pady=(0, 12))

    def batch_folder(self):
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title=f"Select folder for {self.name} batch")
        root.destroy()

        if not folder:
            return

        cfg = self._cfg_from_ui()
        files = [f for f in os.listdir(folder) if f.lower().endswith((".csv", ".xlsx", ".xls"))]
        if not files:
            self._log("Batch: no CSV/XLSX/XLS files found.")
            return

        out_root = os.path.join(folder, f"batch_out_{self.name}")
        os.makedirs(out_root, exist_ok=True)
        self._log(f"Batch start: {len(files)} files → {out_root}")

        batch_sheet = str(self.var_sheet.get()).strip() or None
        summary_rows = []

        def worker():
            try:
                for i, fn in enumerate(files, 1):
                    path = os.path.join(folder, fn)
                    ext = os.path.splitext(path)[1].lower()

                    if ext == ".csv":
                        df = robust_read_csv(path)
                    else:
                        use_sheet = batch_sheet if batch_sheet not in [None, ""] else 0
                        df = pd.read_excel(path, sheet_name=use_sheet)

                    if df.shape[1] < 2:
                        self._log(f"[SKIP] {fn} (need 2 columns)")
                        continue

                    x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
                    y = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(dtype=float)
                    x, y = safe_sorted_xy(x, y)

                    base = os.path.splitext(fn)[0]
                    outdir = os.path.join(out_root, f"{base}_out")
                    os.makedirs(outdir, exist_ok=True)

                    self._log(f"({i}/{len(files)}) {fn} ...")

                    if cfg.technique == "XRD":
                        proc, cand, fitted = run_xrd_pipeline(x, y, outdir, cfg, log_cb=self._log)
                    elif cfg.technique == "XPS":
                        proc, cand, fitted = run_xps_pipeline(x, y, outdir, cfg, log_cb=self._log)
                    else:
                        proc, cand, fitted = run_pl_pipeline(x, y, outdir, cfg, log_cb=self._log)

                    generate_ai_peak_report(
                        proc=proc, cand=cand, fitted=fitted, cfg=cfg,
                        outdir=outdir,
                        file_label=fn,
                        log_cb=self._log
                    )

                    if fitted is not None and not fitted.empty:
                        f2 = fitted.copy()
                        f2["file"] = fn
                        good = f2.sort_values("area_amplitude", ascending=False).head(10)
                        summary_rows.append(good)

                summary_path = os.path.join(out_root, "summary.xlsx")
                with pd.ExcelWriter(summary_path) as w:
                    if summary_rows:
                        pd.concat(summary_rows, ignore_index=True).to_excel(w, "top_peaks", index=False)
                    else:
                        pd.DataFrame().to_excel(w, "top_peaks", index=False)
                self._log(f"Summary written: {summary_path}")
                self._log("Batch finished.")
            except Exception as e:
                self._log(f"[ERR] Batch: {e}")

        threading.Thread(target=worker, daemon=True).start()


    # -------------------------
    # Plotting (dark)
    # -------------------------
    def _style_axis(self, ax):
        ax.set_facecolor(COL_CARD2)
        ax.tick_params(colors=COL_MUT)
        for sp in ax.spines.values():
            sp.set_color(COL_STROKE)
        ax.grid(True, alpha=0.25, color=COL_STROKE)

    def _plot_empty(self):
        self.fig.clf()
        ax = self.fig.add_subplot(111)
        self._style_axis(ax)
        ax.set_title("Load data to preview plot", color=COL_MUT)
        self.canvas.draw()

    def _axis_labels(self):
        """(x label, y label, reverse x) for this workspace's technique. XPS is
        drawn with the binding energy decreasing to the right, as is customary."""
        tech = str(self.name).upper()
        if tech == "XPS":
            return "Binding energy (eV)", "Intensity (counts)", True
        if tech == "XRD":
            return "2θ (°)", "Intensity (counts)", False
        if tech == "PL":
            return "Wavelength (nm)", "PL intensity (counts)", False
        return "x", "Intensity", False

    def _label_axes(self, ax, x=True, y=True):
        xl, yl, rev = self._axis_labels()
        if x:
            ax.set_xlabel(xl, color=COL_MUT)
        if y:
            ax.set_ylabel(yl, color=COL_MUT)
        if rev and not ax.xaxis_inverted():
            ax.invert_xaxis()

    def _plot_raw(self):
        if self.x is None or self.y is None:
            self._plot_empty()
            return
        self.fig.clf()
        ax = self.fig.add_subplot(111)
        self._style_axis(ax)
        ax.plot(self.x, self.y, linewidth=1.1)
        ax.set_title(f"{self.name} - Raw", color=COL_TXT)
        self._label_axes(ax)
        self.fig.tight_layout(pad=1.2)
        self.canvas.draw()

    def _plot(self):
        if self.proc is None:
            self._plot_raw()
            return

        compare = int(self.var_before_after.get()) == 1
        show_only = int(self.var_show_only_fitted.get()) == 1

        x = self.proc["x"].to_numpy()
        y_raw = self.proc["y_raw"].to_numpy()
        y_s   = self.proc["y_smooth"].to_numpy()
        bl    = self.proc["baseline"].to_numpy()
        y_c   = self.proc["y_corr"].to_numpy()

        self.fig.clf()
        self.fig.patch.set_facecolor(COL_CARD2)

        if compare:
            ax1 = self.fig.add_subplot(211)
            ax2 = self.fig.add_subplot(212, sharex=ax1)
            self._style_axis(ax1); self._style_axis(ax2)

            ax1.plot(x, y_raw, linewidth=1.05, label="raw")
            ax1.plot(x, y_s,   linewidth=1.00, label="smooth")
            ax1.plot(x, bl,    linewidth=1.00, label="baseline")
            ax1.set_title(f"{self.name} - BEFORE", color=COL_TXT)
            self._label_axes(ax1, x=False)
            ax1.legend(framealpha=0.85)

            ax2.plot(x, y_c, linewidth=1.05, label="corrected")
            if (not show_only) and self.cand is not None and not self.cand.empty:
                ax2.scatter(self.cand["x"], self.cand["height"], s=18, label="candidates")
            if self.fitted is not None and not self.fitted.empty:
                ax2.scatter(self.fitted["center"], self.fitted["height"], s=35, marker="x", label="fitted")

            ax2.set_title(f"{self.name} - AFTER", color=COL_TXT)
            self._label_axes(ax2)
            ax2.legend(framealpha=0.85)

        else:
            ax = self.fig.add_subplot(111)
            self._style_axis(ax)

            mode = str(self.preview_mode.get())
            if mode == "Raw":
                ax.plot(x, y_raw, linewidth=1.1, label="raw")
                ax.set_title(f"{self.name} - Raw", color=COL_TXT)
            elif mode == "Smooth":
                ax.plot(x, y_s, linewidth=1.1, label="smooth")
                ax.set_title(f"{self.name} - Smooth", color=COL_TXT)
            elif mode == "Baseline":
                ax.plot(x, bl, linewidth=1.1, label="baseline")
                ax.set_title(f"{self.name} - Baseline", color=COL_TXT)
            else:
                ax.plot(x, y_c, linewidth=1.1, label="corrected")
                if (not show_only) and self.cand is not None and not self.cand.empty:
                    ax.scatter(self.cand["x"], self.cand["height"], s=18, label="candidates")
                if self.fitted is not None and not self.fitted.empty:
                    ax.scatter(self.fitted["center"], self.fitted["height"], s=35, marker="x", label="fitted")
                ax.set_title(f"{self.name} - Corrected + Fit", color=COL_TXT)

            self._label_axes(ax)
            ax.legend(framealpha=0.85)

        self.fig.tight_layout(pad=1.2)
        self.canvas.draw()
