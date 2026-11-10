
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# run_sem.py - SEM Analysis GUI (UI Only)
import os
import math
import time
import sys
import threading
import json
import re
import ctypes
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageTk
import customtkinter as ctk

# Matplotlib for embedded histogram
import matplotlib
try:  # the Tk canvas is embedded explicitly; a headless test run keeps its own backend
    matplotlib.use("TkAgg")
except ImportError:
    pass
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report

# Import core logic from sem_core.py
try:
    from . import sem_core
    from .sem_core import (
        Settings,
        read_image_bgr,
        preprocess,
        area_and_eq_diameter,
        find_origin_exe_from_registry,
        try_origin_histogram_direct,
        get_tiles,
        remove_duplicate_points,
        perform_auto_segment,
        detect_footer_cutoff,
        is_point_in_existing,
        check_mask_overlap,
        batch_auto_measure_from_seeds,
    )
except ImportError:
    import sem_core
    from sem_core import (
        Settings,
        read_image_bgr,
        preprocess,
        area_and_eq_diameter,
        find_origin_exe_from_registry,
        try_origin_histogram_direct,
        get_tiles,
        remove_duplicate_points,
        perform_auto_segment,
        detect_footer_cutoff,
        is_point_in_existing,
        check_mask_overlap,
        batch_auto_measure_from_seeds,
    )


# =========================
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None

# Main GUI
# =========================
class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path=""):
        super().__init__(parent)
        self.title("FE-SEM Grain Analysis")
        # Wider to accommodate expanded right panel without clipping
        self.geometry("1460x900")
        self.minsize(1460, 900)

        # Store data received from main window (per spec)
        self.passed_origin_path = origin_path

        self.SET = Settings()
        self.img_path = ""
        self.cv_bgr = None
        self.cv_gray = None
        self.cv_enh = None
        self.photo_img = None
        self.mask = None
        self.seed_pt = None
        self.method = ""
        self.undo_stack = []
        self.redo_stack = []
        self.records = []
        self.nm_per_px = 1.0
        self.calib_pts = []
        self.is_calibrating = False
        self.zoom_scale = 1.0
        self.current_mean_nm = None
        self.advice_items = []

        self.mode_add = True
        self.mode_edit = False
        self.brush_radius = self.SET.brush_radius
        self.dragging = False
        self.last_draw_pt = None
        self.dragging_calib = False
        self.draw_path = []
        self.footer_cutoff = None

        # Widen SEM right panel to match JV Statistics card visual width
        self.right_width = 380
        self.min_right_width = 380
        self.max_right_width = 380
        self._drag_start_x = None
        self._drag_start_width = None

        self.grid_columnconfigure(0, minsize=280)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=10)
        self.grid_columnconfigure(3, minsize=self.right_width)
        self.grid_rowconfigure(0, weight=1)

        self.create_left_panel()
        self.create_center_panel()
        self.create_right_resizer()
        self.create_right_panel()

        self.config_file = os.path.join(SCRIPT_DIR, "sem_config.json")
        self.load_settings()

        self.bind("<Key>", self.on_key_press)
        self.bind("<Button-1>", self.on_global_click)

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "FE-SEM Analysis", {
                    "open": ("Open Image", self.load_image),
                    "run": ("Auto Segment", self.run_auto_segment),
                    "excel": ("Excel", self.export_excel),
                    "png": True,
                    "report": ("Report", self.export_report),
                    "origin": ("Origin", self.export_origin),
                    "ai": ("Interpretation", self.open_advisor_dialog)
                }, hints="Click: segment the grain under the cursor  |  Drag: brush  |  Calibrate: drag along the scale bar  |  Ctrl+Z / Ctrl+Y: undo / redo")
            except Exception as _ce:
                print(f"shell skip: {_ce}")


    # =====================
    # UI Creation
    # =====================
    def create_left_panel(self):
        # Toss-style color definitions
        self.card_bg = _pal.BG_CARD
        self.card_border = _pal.BORDER
        self.accent_blue = _pal.ACCENT
        self.accent_orange = _pal.ORANGE
        self.text_primary = _pal.TXT
        self.text_secondary = _pal.TXT_SUB

        self.left_frame = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        # Lock left panel width to JV size
        self.left_frame.grid_propagate(False)
        self.left_scroll = ctk.CTkScrollableFrame(self.left_frame, width=280, fg_color=_pal.BG_PANEL, corner_radius=0)
        self.left_scroll.pack(fill="both", expand=True)
        left_content = self.left_scroll

        # 1. Load Data card
        load_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkButton(load_card, text="Load SEM Image", command=self.load_image,
                      corner_radius=_pal.R_CARD, height=28, fg_color=self.accent_blue,
                      hover_color=_pal.ACCENT_HOV, font=_pal.font(11)).pack(pady=(0, 16), padx=16, fill="x")
        self.lbl_shortcuts = ctk.CTkLabel(
            load_card,
            text="Shortcuts: shown after image is loaded.",
            text_color=self.text_secondary,
            font=_pal.font(11),
            justify="left",
            anchor="w",
            wraplength=240,
        )
        self.lbl_shortcuts.pack(pady=(0, 14), padx=(20, 16), anchor="w", fill="x")

        # 2. Calibration card
        calib_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        calib_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(calib_card, text="Calibration", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        sf = ctk.CTkFrame(calib_card, fg_color="transparent")
        sf.pack(fill="x", padx=16)
        ctk.CTkLabel(sf, text="Known (nm)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(side="left")
        self.entry_scale_nm = ctk.CTkEntry(sf, width=100, corner_radius=_pal.R_PILL, height=26)
        self.entry_scale_nm.insert(0, "100")
        self.entry_scale_nm.pack(side="right")

        self.btn_calib = ctk.CTkButton(calib_card, text="Calibrate", command=self.toggle_calibration,
                                        fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                                        corner_radius=_pal.R_CARD, height=28, font=_pal.font(11), text_color=_pal.TXT)
        self.btn_calib.pack(pady=12, padx=16, fill="x")

        self.btn_calib_auto = ctk.CTkButton(
            calib_card, text="Auto Calibrate (Scale Bar)", command=self.auto_calibrate_from_scale_bar,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER, corner_radius=_pal.R_PILL, height=28, font=_pal.font(11), text_color=_pal.TXT)
        self.btn_calib_auto.pack(pady=(0, 12), padx=16, fill="x")

        self.lbl_scale_info = ctk.CTkLabel(calib_card, text="Scale: Not set",
                                            text_color=self.text_secondary, font=_pal.font(12))
        self.lbl_scale_info.pack(pady=(0, 16))

        # 3. Tools card
        tools_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        tools_card.pack(pady=4, padx=12, fill="x")

        ctk.CTkLabel(tools_card, text="Brush Tool", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(10, 6), padx=16, anchor="w")

        self.slider_brush = ctk.CTkSlider(tools_card, from_=1, to=50, number_of_steps=49,
                                          command=self.update_brush_size,
                                          button_color=self.accent_blue,
                                          button_hover_color=_pal.ACCENT_HOV,
                                          progress_color=self.accent_blue)
        self.slider_brush.set(self.SET.brush_radius)
        self.slider_brush.pack(padx=16, pady=(0, 4), fill="x")

        self.lbl_brush_val = ctk.CTkLabel(tools_card, text=f"Size: {self.SET.brush_radius}",
                                          text_color=self.text_secondary, font=_pal.font(12))
        self.lbl_brush_val.pack(pady=(4, 10))

        # 4. Actions card (export and other action buttons)
        actions_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        actions_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(actions_card, text="Actions", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        btn_frame = ctk.CTkFrame(actions_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkButton(btn_frame, text="Export Excel", command=self.export_excel,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      corner_radius=_pal.R_PILL, height=28, font=_pal.font(12), text_color=_pal.TXT).pack(fill="x", pady=3)
        ctk.CTkButton(btn_frame, text="Delete Selected", command=self.delete_selected_row,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      corner_radius=_pal.R_PILL, height=28, font=_pal.font(12), text_color=_pal.TXT).pack(fill="x", pady=3)
        ctk.CTkButton(btn_frame, text="Send to Origin", command=self.export_origin,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      corner_radius=_pal.R_PILL, height=28, font=_pal.font(12), text_color=_pal.TXT).pack(fill="x", pady=3)

        # 5. Auto Segment Card (Replaces Status)
        auto_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        auto_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(auto_card, text="Auto Segment", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        # Params
        param_row = ctk.CTkFrame(auto_card, fg_color="transparent")
        param_row.pack(fill="x", padx=16, pady=(0, 4))

        ctk.CTkLabel(param_row, text="Max Pts", text_color=self.text_secondary, font=_pal.font(11)).pack(side="left")
        self.entry_max_pts = ctk.CTkEntry(param_row, width=60, height=28, corner_radius=_pal.R_PILL)
        self.entry_max_pts.insert(0, str(self.SET.seed_max_points))
        self.entry_max_pts.pack(side="left", padx=(4, 0))

        param_row2 = ctk.CTkFrame(auto_card, fg_color="transparent")
        param_row2.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(param_row2, text="Min Dist", text_color=self.text_secondary, font=_pal.font(11)).pack(side="left")
        self.entry_min_dist = ctk.CTkEntry(param_row2, width=60, height=28, corner_radius=_pal.R_PILL)
        self.entry_min_dist.insert(0, str(self.SET.seed_min_distance_px))
        self.entry_min_dist.pack(side="left", padx=(4, 0))

        ctk.CTkButton(auto_card, text="Run Auto Segment", command=self.run_auto_segment,
                      fg_color=self.accent_blue, hover_color=_pal.ACCENT_HOV,
                      corner_radius=_pal.R_CARD, height=28, font=_pal.font(11)).pack(pady=(8, 16), padx=16, fill="x")

        # 6. Interpretation (rule-based, offline; 3.4 replaced the Gemini process advisor)
        advisor_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        advisor_card.pack(pady=8, padx=12, fill="x")
        ctk.CTkLabel(advisor_card, text="Interpretation", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 6), padx=16, anchor="w")
        self.lbl_advice_status = ctk.CTkLabel(
            advisor_card, text="Distribution width, bimodality, log-normal fit, sample size and process hints.",
            text_color=self.text_secondary, font=_pal.font(11), wraplength=240, justify="left")
        self.lbl_advice_status.pack(pady=(0, 8), padx=16, anchor="w", fill="x")
        ctk.CTkButton(
            advisor_card, text="Interpret grain statistics", command=self.open_advisor_dialog,
            fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER, corner_radius=_pal.R_PILL, height=26,
            font=_pal.font(12), text_color=_pal.TXT).pack(padx=16, pady=(0, 16), fill="x")

        # Hidden entry for the Origin path (read by the Origin export)
        self.entry_origin = ctk.CTkEntry(self.left_frame, height=1)
        detected = find_origin_exe_from_registry()
        if detected:
            self.entry_origin.insert(0, detected)

        # Spacer to push shortcuts to bottom
        spacer = ctk.CTkFrame(left_content, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        # Shortcuts card (bottom)
        shortcuts_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        shortcuts_card.pack(pady=(8, 16), padx=12, fill="x")

        ctk.CTkLabel(shortcuts_card, text="Shortcuts", font=_pal.font(13, "bold"),
                     text_color=self.text_secondary).pack(pady=(12, 8), padx=16, anchor="w")

        shortcuts_text = "M Save  •  N Discard  •  Z/X Undo/Redo\n[/] Size  •  P Eraser  •  Right-click Toggle"
        ctk.CTkLabel(shortcuts_card, text=shortcuts_text, justify="left",
                     text_color=_pal.TXT_DIM, font=_pal.font(11)).pack(padx=16, pady=(0, 12), anchor="w")

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=_pal.BG_WINDOW)
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(0, weight=1)
        self.center_frame.grid_columnconfigure(0, weight=1)

        # Canvas container (for padding)
        canvas_container = ctk.CTkFrame(self.center_frame, corner_radius=_pal.R_CARD, fg_color=_pal.BG_CARD)
        canvas_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        self.v_scroll = ctk.CTkScrollbar(canvas_container, orientation="vertical")
        self.h_scroll = ctk.CTkScrollbar(canvas_container, orientation="horizontal")
        self.canvas = tk.Canvas(canvas_container, bg=_pal.BG_PANEL, highlightthickness=0,
                                xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        self.v_scroll.configure(command=self.canvas.yview)
        self.h_scroll.configure(command=self.canvas.xview)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.v_scroll.grid(row=0, column=1, sticky="ns", pady=2)
        self.h_scroll.grid(row=1, column=0, sticky="ew", padx=2)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom)
        self.canvas.bind("<Button-3>", self.on_right_click)

    def create_right_resizer(self):
        self.right_resizer = tk.Frame(self, width=10, bg=_pal.BORDER_HI, cursor="sb_h_double_arrow")
        self.right_resizer.grid(row=0, column=2, sticky="nsew")
        self.right_resizer.grid_propagate(False)
        self.right_resizer.lift()
        self.right_resizer.bind("<Button-1>", self._on_resizer_press)
        self.right_resizer.bind("<B1-Motion>", self._on_resizer_drag)

    def _on_resizer_press(self, event):
        self._drag_start_x = event.x_root
        self._drag_start_width = self.right_width

    def _on_resizer_drag(self, event):
        if self._drag_start_x is None:
            return
        delta = event.x_root - self._drag_start_x
        new_width = int(self._drag_start_width - delta)
        new_width = max(self.min_right_width, min(self.max_right_width, new_width))
        if new_width == self.right_width:
            return
        self.right_width = new_width
        self.grid_columnconfigure(3, minsize=self.right_width)
        self.right_frame.configure(width=self.right_width)
        self.right_frame.update_idletasks()

    def create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, width=self.right_width, corner_radius=0, fg_color=_pal.BG_PANEL)
        self.right_frame.grid(row=0, column=3, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        # Statistics card
        stats_card = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        stats_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats_card, text="Statistics", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        # Statistics grid layout
        stats_grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_grid.pack(fill="x", padx=16, pady=(0, 16))

        # Mean & Std Row
        row1 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row1.pack(fill="x", pady=4)

        mean_box = ctk.CTkFrame(row1, corner_radius=_pal.R_PILL, fg_color=_pal.BG_SUB)
        mean_box.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkLabel(mean_box, text="Mean", text_color=self.text_secondary,
                     font=_pal.font(10)).pack(pady=(8, 2))
        self.lbl_stats_mean = ctk.CTkLabel(mean_box, text="- nm", font=_pal.font(12, "bold"),
                                           text_color=_pal.TXT)
        self.lbl_stats_mean.pack(pady=(0, 8))

        std_box = ctk.CTkFrame(row1, corner_radius=_pal.R_PILL, fg_color=_pal.BG_SUB)
        std_box.pack(side="right", expand=True, fill="x", padx=(4, 0))
        ctk.CTkLabel(std_box, text="Std Dev", text_color=self.text_secondary,
                     font=_pal.font(10)).pack(pady=(8, 2))
        self.lbl_stats_std = ctk.CTkLabel(std_box, text="- nm", font=_pal.font(12, "bold"),
                                          text_color=_pal.TXT)
        self.lbl_stats_std.pack(pady=(0, 8))

        # Min & Max Row
        row2 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row2.pack(fill="x", pady=4)

        min_box = ctk.CTkFrame(row2, corner_radius=_pal.R_PILL, fg_color=_pal.BG_SUB)
        min_box.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkLabel(min_box, text="Min", text_color=self.text_secondary,
                     font=_pal.font(10)).pack(pady=(8, 2))
        self.lbl_stats_min = ctk.CTkLabel(min_box, text="- nm", font=_pal.font(12, "bold"),
                                          text_color=_pal.TXT)
        self.lbl_stats_min.pack(pady=(0, 8))

        max_box = ctk.CTkFrame(row2, corner_radius=_pal.R_PILL, fg_color=_pal.BG_SUB)
        max_box.pack(side="right", expand=True, fill="x", padx=(4, 0))
        ctk.CTkLabel(max_box, text="Max", text_color=self.text_secondary,
                     font=_pal.font(10)).pack(pady=(8, 2))
        self.lbl_stats_max = ctk.CTkLabel(max_box, text="- nm", font=_pal.font(12, "bold"),
                                          text_color=_pal.TXT)
        self.lbl_stats_max.pack(pady=(0, 8))

        ctk.CTkLabel(stats_grid, text="Distribution", font=_pal.font(10, "bold"), text_color=self.text_secondary,
                     anchor="w").pack(fill="x", pady=(8, 2))
        self.dist_tree = _theme.kv_table(stats_grid, height=7, key_width=170, value_width=100)
        self.dist_tree.pack(fill="x")

        # Results card (table)
        results_card = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        results_card.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(results_card, text="Results", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).grid(row=0, column=0, pady=(16, 8), padx=16, sticky="w")

        # Table style
        _theme.style_treeview(rowheight=26)   # shared light/dark table style

        tree_frame = ctk.CTkFrame(results_card, fg_color="transparent")
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_frame, columns=("id", "nm"), show="headings")
        self.tree.heading("id", text="#")
        self.tree.column("id", width=50, anchor="center")
        self.tree.heading("nm", text="Size (nm)")
        self.tree.column("nm", width=120, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        # Distribution card (size improved)
        hist_card = ctk.CTkFrame(self.right_frame, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        hist_card.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 16))
        self.right_frame.grid_rowconfigure(2, weight=2)  # larger weight

        ctk.CTkLabel(hist_card, text="Distribution", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.hist_frame = ctk.CTkFrame(hist_card, fg_color=_pal.BG_SUB, corner_radius=_pal.R_CARD)
        self.hist_frame.pack(fill="both", expand=True, padx=12, pady=(0, 16))

        self.fig = Figure(figsize=(4, 3), dpi=100, facecolor=_pal.BG_SUB)
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor(_pal.BG_SUB)
        self.ax.set_facecolor(_pal.BG_SUB)
        self.ax.tick_params(colors=_pal.PLOT_TICK, labelsize=10, width=1)
        self.ax.tick_params(axis='both', which='major', labelsize=10)
        for spine in self.ax.spines.values():
            spine.set_color(_pal.BORDER)
        self.canvas_hist = FigureCanvasTkAgg(self.fig, master=self.hist_frame)
        self.canvas_hist.get_tk_widget().pack(fill="both", expand=True)

    # =====================
    # Settings I/O
    # =====================
    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    self.entry_origin.delete(0, "end")
                    self.entry_origin.insert(0, data.get("origin_path", ""))
            except Exception:
                pass

    def save_settings(self):
        data = {"origin_path": self.entry_origin.get().strip()}
        try:
            with open(self.config_file, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    # =====================
    # Image Loading & Display
    # =====================
    def play_mp3(self, filename):
        if os.path.exists(filename):
            try:
                mci = ctypes.windll.winmm.mciSendStringW
                mci(f'open "{filename}" type mpegvideo alias mp3', None, 0, 0)
                mci("play mp3 wait", None, 0, 0)
                mci("close mp3", None, 0, 0)
            except:
                pass
        else:
            try:
                import winsound
                winsound.Beep(1000, 300)
            except:
                self.bell()

    def load_image(self):
        path = filedialog.askopenfilename(title="Open SEM image",
                                          filetypes=[("Images", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.cv_bgr = read_image_bgr(path)
            self.img_path = path
            self.cv_gray = cv2.cvtColor(self.cv_bgr, cv2.COLOR_BGR2GRAY)
            self.cv_enh = preprocess(self.cv_gray)
            try:
                self.footer_cutoff = detect_footer_cutoff(self.cv_gray, self.SET)
            except Exception:
                self.footer_cutoff = None
            self.mask = None
            self.records = []
            self.tree.delete(*self.tree.get_children())
            self.update_display()
            self.update_hist()
            self.lbl_shortcuts.configure(text=(
                "Shortcuts / Controls\n"
                "  - Left click: select/edit\n"
                "             draw while editing\n"
                "  - Right click: toggle edit\n"
                "             delete when not editing\n"
                "  - M: save\n"
                "             N cancel\n"
                "  - Z: undo\n"
                "             X redo\n"
                "  - P: brush mode\n"
                "             toggle\n"
                "  - [ / ]: brush size"
            ))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def update_hist(self):
        self.ax.clear()
        if not self.records:
            self.canvas_hist.draw()
            self.current_mean_nm = None
            self.advice_items = []
            return
        vals = [r["nm"] for r in self.records]
        stats, counts, edges, xs, curve = sem_core.histogram_with_fit(vals)
        self.size_stats = stats
        if len(counts):
            self.ax.bar(edges[:-1], counts, width=np.diff(edges), align="edge", color=_pal.ACCENT,
                        edgecolor=_pal.PLOT_BG, alpha=0.75, label="grains")
            if len(vals) >= 5 and np.isfinite(stats.get("lognorm_sigma", float("nan"))) and stats["lognorm_sigma"] > 0:
                self.ax.plot(xs, curve, color=_pal.RED, linewidth=1.3,
                             label=f"log-normal (D50 {stats['D50']:.0f} nm, GSD {stats['gsd']:.2f})")
                self.ax.legend(fontsize=7, framealpha=0.9)
        self.ax.set_xlabel("Equivalent diameter (nm)", fontsize=9)
        self.ax.set_ylabel("Count", fontsize=9)
        self.ax.set_title(f"N = {len(vals)}", color=_pal.PLOT_FG, fontsize=10)
        self.fig.tight_layout()
        self.canvas_hist.draw()
        if hasattr(self, "dist_tree"):
            _theme.fill_kv(self.dist_tree, [
                ("N", int(stats["n"])),
                ("Median D50 (nm)", stats["D50"], ".1f"),
                ("D10 / D90 (nm)", f"{stats['D10']:.1f} / {stats['D90']:.1f}" if np.isfinite(stats["D10"]) else "-"),
                ("Coefficient of variation", stats["cv"], ".3f"),
                ("Geometric mean (nm)", stats["geo_mean"], ".1f"),
                ("Geometric std. deviation", stats["gsd"], ".3f"),
                ("Log-normal mode (nm)", stats["lognorm_mode"], ".1f"),
            ])

        # Update Stats Panel
        if vals:
            mean_val = np.mean(vals)
            # sample standard deviation (ddof=1) - the correct estimator for a
            # measured grain-size sample; population std biased results low
            std_val = np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            min_val = np.min(vals)
            max_val = np.max(vals)
            self.current_mean_nm = float(mean_val)
            self.lbl_stats_mean.configure(text=f"{mean_val:.1f} nm")
            self.lbl_stats_std.configure(text=f"{std_val:.1f} nm")
            self.lbl_stats_min.configure(text=f"{min_val:.1f} nm")
            self.lbl_stats_max.configure(text=f"{max_val:.1f} nm")
        else:
            self.current_mean_nm = None
            self.lbl_stats_mean.configure(text="- nm")
            self.lbl_stats_std.configure(text="- nm")
            self.lbl_stats_min.configure(text="- nm")
            self.lbl_stats_max.configure(text="- nm")

    def update_display(self):
        if self.cv_bgr is None:
            return
        disp = self.cv_bgr.copy()

        # Draw saved
        if self.records:
            ov = disp.copy()
            for r in self.records:
                if r["mask"] is not None:
                    cnts, _ = cv2.findContours(r["mask"], cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(disp, cnts, -1, (255, 200, 0), 1)
                    ov[r["mask"] == 255] = (255, 200, 0)
            cv2.addWeighted(ov, 0.2, disp, 0.8, 0, disp)

        # Draw current
        if self.mask is not None:
            cnts, _ = cv2.findContours(self.mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(disp, cnts, -1, (0, 255, 0), 2)
            ov = disp.copy()
            ov[self.mask == 255] = (0, 255, 0)
            cv2.addWeighted(ov, 0.3, disp, 0.7, 0, disp)

        # Draw Calib
        for p in self.calib_pts:
            cv2.circle(disp, p, 5, (0, 0, 255), -1)
        if len(self.calib_pts) == 2:
            cv2.line(disp, self.calib_pts[0], self.calib_pts[1], (0, 0, 255), 2)

        h, w = disp.shape[:2]
        nw, nh = int(w * self.zoom_scale), int(h * self.zoom_scale)
        if nw > 0 and nh > 0:
            res = cv2.resize(disp, (nw, nh), interpolation=cv2.INTER_NEAREST)
            self.photo_img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(res, cv2.COLOR_BGR2RGB)))
            self.canvas.config(scrollregion=(0, 0, nw, nh))
            self.canvas.create_image(0, 0, image=self.photo_img, anchor="nw")

    # =====================
    # Interpretation (rule-based)
    # =====================
    def open_advisor_dialog(self):
        """Rule-based interpretation of the grain statistics plus process hints (3.4; replaced the
        Gemini advisor): distribution width, bimodality, log-normal fit, sample size."""
        if not self.records:
            messagebox.showinfo("Interpretation", "Measure some grains first (Auto Segment or by hand).", parent=self)
            return
        from scripts.common import interpret as _interp
        from scripts.common import interpret_window as _iw
        d = np.array([r["nm"] for r in self.records], float)
        rep = _interp.interpret_sem(d, subject=os.path.basename(getattr(self, "img_path", "") or ""))
        for tip in self._fallback_advice(float(d.mean()), float(d.std(ddof=1)) if len(d) > 1 else 0.0,
                                         float(d.min()), float(d.max()), len(d)):
            rep.add("note", "Process hint", tip, f"mean {d.mean():.0f} nm, sd {d.std(ddof=1) if len(d) > 1 else 0:.0f} nm",
                    "rule of thumb for solution-processed films (grain size and spread)")
        self.lbl_advice_status.configure(text=rep.summary())
        _iw.show(self, rep)

    def _fallback_advice(self, mean_nm, std_nm, min_nm, max_nm, n):
        tips = []
        if mean_nm < 100:
            tips.append("Grain size is small. Slow down nucleation (reduce antisolvent amount/speed or delay drip timing).")
            tips.append("Consider raising solvent-annealing time/temperature to promote grain growth.")
        elif mean_nm > 500:
            tips.append("Grain size is large. Lower growth rate to improve uniformity (reduce annealing temperature/time).")
        else:
            tips.append("Grain size is moderate. Focus on reducing the distribution (standard deviation).")

        if std_nm > 0.3 * mean_nm:
            tips.append("Distribution is broad. Keep spin speed and antisolvent timing more consistent.")

        tips.append("Adjust precursor concentration and solvent ratio to control nucleation density.")
        tips.append("If film roughness is high, reduce antisolvent amount or switch to a milder antisolvent.")
        return tips[:5]

    def on_zoom(self, e):
        if self.cv_bgr is None:
            return
        if e.delta > 0:
            self.zoom_scale *= 1.1
        else:
            self.zoom_scale /= 1.1
        self.zoom_scale = max(0.1, min(10.0, self.zoom_scale))
        self.update_display()

    # =====================
    # Calibration
    # =====================
    def toggle_calibration(self):
        self.is_calibrating = not self.is_calibrating
        self.calib_pts = []
        self.btn_calib.configure(text="Cancel" if self.is_calibrating else "Calibrate (Drag Line)")
        self.mode_edit = False
        self.mask = None
        self.update_display()

    def update_brush_size(self, val):
        self.brush_radius = int(val)
        self.lbl_brush_val.configure(text=f"Size: {self.brush_radius}")

    # =====================
    # Auto Calibration (Scale Bar)
    # =====================
    def auto_calibrate_from_scale_bar(self):
        if self.cv_bgr is None:
            messagebox.showwarning("Calibration", "Load Image First")
            return
        try:
            known_nm = float(self.entry_scale_nm.get())
        except Exception:
            messagebox.showerror("Calibration", "Invalid nm value")
            return

        bar_px = self._detect_scale_bar_px(self.cv_bgr)
        if not bar_px or bar_px <= 0:
            messagebox.showwarning("Calibration", "Scale bar not found")
            return

        self.nm_per_px = float(known_nm) / float(bar_px)
        self.lbl_scale_info.configure(text=f"Scale: {self.nm_per_px:.4f} nm/px (auto)")
        self.is_calibrating = False
        self.btn_calib.configure(text="Calibrate")
        self.calib_pts = []
        self.update_display()
        messagebox.showinfo("Calibration", "Auto calibration done.")

    def _detect_scale_bar_px(self, img_bgr):
        # Detect bright horizontal bar near bottom of SEM image
        h, w = img_bgr.shape[:2]
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        # Focus only right-bottom area for scale bar
        y0 = int(h * 0.80)
        y1 = h
        x0 = int(w * 0.70)
        x1 = w
        roi = gray[y0:y1, x0:x1]

        # 1) Try OCR to find "nm" label, then search left of it
        try:
            import pytesseract
            data = pytesseract.image_to_data(roi, output_type=pytesseract.Output.DICT)
            nm_idx = None
            for i, txt in enumerate(data.get("text", [])):
                if not txt:
                    continue
                if re.search(r"\bnm\b", txt, re.IGNORECASE):
                    nm_idx = i
                    break
            if nm_idx is not None:
                x = data["left"][nm_idx]
                y = data["top"][nm_idx]
                ww = data["width"][nm_idx]
                hh = data["height"][nm_idx]
                # band around text, search to the left for bar
                band_y0 = max(0, y - int(hh * 2))
                band_y1 = min(roi.shape[0], y + int(hh * 2))
                band = roi[band_y0:band_y1, :max(0, x)]
                if band.size > 0:
                    hi = np.percentile(band, 95)
                    thr = int(max(190, min(hi, 245)))
                    th = (band >= thr).astype(np.uint8) * 255
                    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((5, 3), np.uint8), iterations=1)
                    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    candidates = []
                    for c in contours:
                        bx, by, bw, bh = cv2.boundingRect(c)
                        if bh == 0:
                            continue
                        ar = bw / float(bh)
                        if ar > 6 and bh <= (h * 0.05) and bw > (w * 0.04):
                            candidates.append((bw, bx, by, bw, bh))
                    if candidates:
                        candidates.sort(reverse=True)
                        return int(candidates[0][0])
        except Exception:
            pass

        # bright-bar pass (use high percentile threshold)
        hi = np.percentile(roi, 95)
        thr = int(max(190, min(hi, 245)))
        th = (roi >= thr).astype(np.uint8) * 255
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((7, 3), np.uint8), iterations=1)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            if ch == 0:
                continue
            ar = cw / float(ch)
            # wide, thin bar
            if ar > 6 and ch <= (h * 0.05) and cw > (w * 0.04):
                candidates.append((cw, x, y, cw, ch))
        if not candidates:
            # fallback: run-length scan on binary image
            bw = th.copy()
            best = 0
            for row in bw:
                run = 0
                for v in row:
                    if v:
                        run += 1
                        if run > best:
                            best = run
                    else:
                        run = 0
            if best <= int(roi.shape[1] * 0.04):
                return None
            return int(best)
        candidates.sort(reverse=True)
        _, x, y, cw, ch = candidates[0]

        # Sub-pixel length refinement using grayscale profiles
        bar = roi[y:y + ch, x:x + cw]
        if bar.size == 0:
            return int(cw)
        # sample multiple rows across the bar height
        rows = np.linspace(0, max(0, ch - 1), num=min(7, ch)).astype(int)
        lengths = []
        for r in rows:
            prof = bar[r].astype(np.float32)
            if prof.size < 4:
                continue
            # smooth 1D profile
            prof = cv2.GaussianBlur(prof.reshape(1, -1), (1, 5), 0).ravel()
            pmin, pmax = float(prof.min()), float(prof.max())
            if pmax - pmin < 5:
                continue
            thr_prof = pmin + 0.5 * (pmax - pmin)
            idx = np.where(prof >= thr_prof)[0]
            if idx.size < 2:
                continue
            left = float(idx[0])
            right = float(idx[-1])
            lengths.append(right - left + 1.0)
        if lengths:
            return int(round(float(np.mean(lengths))))
        return int(cw)
    # =====================
    # Grain Editing
    # =====================
    def find_record_at(self, x, y):
        for i in range(len(self.records) - 1, -1, -1):
            rec = self.records[i]
            mask = rec.get("mask")
            if mask is not None:
                h, w = mask.shape
                if 0 <= y < h and 0 <= x < w:
                    if mask[y, x] > 0:
                        return i, rec
        return None, None

    def load_record_for_editing(self, index, rec):
        self.records.pop(index)
        for i, r in enumerate(self.records):
            r["index"] = i + 1
        self.mask = rec["mask"].copy()
        self.mode_edit = True
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.refresh_table()
        self.update_display()
        self.update_hist()
        self.title(f"EDITING Grain #{rec['index']} - Press 'M' to Save, 'N' to Discard")

    def on_right_click(self, event):
        if self.cv_bgr is None:
            return
        x = int(self.canvas.canvasx(event.x) / self.zoom_scale)
        y = int(self.canvas.canvasy(event.y) / self.zoom_scale)
        if self.mode_edit:
            self.mode_add = not self.mode_add
            mode_str = "ADD (Draw)" if self.mode_add else "DELETE (Erase)"
            self.title(f"EDITING - Brush: {mode_str}")
        else:
            idx, rec = self.find_record_at(x, y)
            if rec:
                self.records.pop(idx)
                for i, r in enumerate(self.records):
                    r["index"] = i + 1
                self.refresh_table()
                self.update_display()
                self.update_hist()

    # =====================
    # Canvas Events
    # =====================
    def on_canvas_click(self, e):
        if self.cv_bgr is None:
            return
        self.focus()
        x = int(self.canvas.canvasx(e.x) / self.zoom_scale)
        y = int(self.canvas.canvasy(e.y) / self.zoom_scale)
        if not (0 <= x < self.cv_bgr.shape[1] and 0 <= y < self.cv_bgr.shape[0]):
            return

        if self.is_calibrating:
            self.calib_pts = [(x, y)]
            self.dragging_calib = True
            self.update_display()
            return

        if not self.mode_edit:
            idx, rec = self.find_record_at(x, y)
            if rec:
                self.load_record_for_editing(idx, rec)
            else:
                self._perform_auto_segment(x, y)
        else:
            self.push_undo()
            self.dragging = True
            self.last_draw_pt = (x, y)
            self.draw_path = [(x, y)]
            cv2.circle(self.mask, (x, y), self.brush_radius, 255 if self.mode_add else 0, -1)
            self.update_display()

    def on_canvas_drag(self, e):
        x = int(self.canvas.canvasx(e.x) / self.zoom_scale)
        y = int(self.canvas.canvasy(e.y) / self.zoom_scale)

        if self.is_calibrating and self.dragging_calib:
            if len(self.calib_pts) >= 1:
                self.calib_pts = [self.calib_pts[0], (x, y)]
                self.update_display()
            return

        if self.mode_edit and self.dragging:
            cv2.line(self.mask, self.last_draw_pt, (x, y), 255 if self.mode_add else 0, self.brush_radius * 2)
            self.last_draw_pt = (x, y)
            self.draw_path.append((x, y))
            self.update_display()

    def on_canvas_release(self, e):
        if self.is_calibrating and self.dragging_calib:
            self.dragging_calib = False
            if len(self.calib_pts) == 2:
                dist = math.hypot(self.calib_pts[1][0] - self.calib_pts[0][0],
                                  self.calib_pts[1][1] - self.calib_pts[0][1])
                if dist > 0:
                    try:
                        known = float(self.entry_scale_nm.get())
                        self.nm_per_px = known / dist
                        self.lbl_scale_info.configure(text=f"Scale: {self.nm_per_px:.4f} nm/px")
                        messagebox.showinfo("OK", "Calibration Done")
                    except:
                        messagebox.showerror("Err", "Invalid nm")
                    self.is_calibrating = False
                    self.btn_calib.configure(text="Calibrate")
                    self.calib_pts = []
            self.update_display()
            return

        if self.mode_edit and self.dragging and len(self.draw_path) > 10:
            start = self.draw_path[0]
            end = self.draw_path[-1]
            if math.hypot(start[0] - end[0], start[1] - end[1]) < self.brush_radius * 3:
                cv2.fillPoly(self.mask, [np.array(self.draw_path)], 255 if self.mode_add else 0)
                self.update_display()

        self.dragging = False
        self.draw_path = []

    # =====================
    # Segmentation (calls core)
    # =====================
    def _perform_auto_segment(self, x, y):
        if self.footer_cutoff is not None and y >= self.footer_cutoff:
            return
        full = perform_auto_segment(self.cv_enh, x, y, self.SET)
        if full is None:
            return
        if self.footer_cutoff is not None and 0 < self.footer_cutoff < full.shape[0]:
            full[self.footer_cutoff:, :] = 0
            if cv2.countNonZero(full) == 0:
                return
        self.mask = full
        self.mode_edit = True
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_display()

    # =====================
    # Undo/Redo
    # =====================
    def push_undo(self):
        if self.mask is not None:
            self.undo_stack.append(self.mask.copy())
            if len(self.undo_stack) > self.SET.undo_depth:
                self.undo_stack.pop(0)
            self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.mask.copy())
        self.mask = self.undo_stack.pop()
        self.update_display()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.mask.copy())
        self.mask = self.redo_stack.pop()
        self.update_display()

    # =====================
    # Grain Management
    # =====================
    def save_grain(self):
        if self.mask is None:
            return

        if cv2.countNonZero(self.mask) == 0:
            self.mask = None
            self.mode_edit = False
            self.update_display()
            return

        apx, aum, dnm = area_and_eq_diameter(self.mask, self.nm_per_px)
        rec = {"id": len(self.records) + 1, "nm": dnm, "mask": self.mask.copy()}
        self.records.append(rec)
        self.tree.insert("", "end", values=(rec["id"], f"{dnm:.1f}"))
        self.tree.yview_moveto(1)
        self.mask = None
        self.mode_edit = False
        self.update_display()
        self.update_hist()

    def on_key_press(self, e):
        if isinstance(e.widget, (tk.Entry, ctk.CTkEntry)):
            return
        k = e.char.lower()
        if k == 'm':
            self.save_grain()
        elif k == 'n':
            self.mask = None
            self.mode_edit = False
            self.update_display()
        elif k == 'z':
            self.undo()
        elif k == 'x':
            self.redo()
        elif k == '[':
            self.slider_brush.set(max(1, self.brush_radius - 2))
            self.update_brush_size(self.slider_brush.get())
        elif k == ']':
            self.slider_brush.set(min(50, self.brush_radius + 2))
            self.update_brush_size(self.slider_brush.get())
        elif k == 'p':
            if self.mode_edit:
                self.mode_add = not self.mode_add
                mode_str = "ADD (Draw)" if self.mode_add else "DELETE (Erase)"
                self.title(f"EDITING - Brush: {mode_str}")

    def on_global_click(self, e):
        if not isinstance(e.widget, (tk.Entry, ctk.CTkEntry)):
            self.focus()

    def delete_selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        ids = [int(self.tree.item(i, "values")[0]) for i in sel]
        self.records = [r for r in self.records if r["id"] not in ids]
        for i, r in enumerate(self.records):
            r["id"] = i + 1
        self.refresh_table()

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.records:
            self.tree.insert("", "end", values=(r["id"], f"{r['nm']:.1f}"))
        self.update_display()
        self.update_hist()

    # =====================
    # Export
    # =====================
    def export_excel(self):
        if not self.records:
            return
        p = filedialog.asksaveasfilename(defaultextension=".xlsx")
        if p:
            grains = pd.DataFrame([{"ID": r["id"], "Equivalent diameter (nm)": r["nm"],
                                    "Area (um2)": r.get("area_um2", np.nan), "Method": r.get("method", "")}
                                   for r in self.records])
            stats = sem_core.size_statistics([r["nm"] for r in self.records])
            st = pd.DataFrame(list(stats.items()), columns=["Quantity", "Value"])
            with pd.ExcelWriter(p, engine="openpyxl") as w:
                grains.to_excel(w, sheet_name="Grains", index=False)
                st.to_excel(w, sheet_name="Statistics", index=False)
            from scripts.common.provenance import write_sidecar
            write_sidecar(p, "SEM grain size", inputs=[getattr(self, "img_path", "")],
                          parameters={"nm_per_px": getattr(self, "nm_per_px", None)}, results=stats)
            messagebox.showinfo("Export", "Saved grains and statistics.")

    def export_report(self):
        if not self.records:
            messagebox.showwarning("Report", "Measure some grains first.")
            return
        path = _report.ask_report_path(self, "SEM_grain_report.md")
        if not path:
            return
        stats = sem_core.size_statistics([r["nm"] for r in self.records])
        grains = pd.DataFrame([{"ID": r["id"], "Equivalent diameter (nm)": round(r["nm"], 1)} for r in self.records])
        notes = ("Equivalent circular diameter of each segmented grain, d = 2 sqrt(A/pi). Statistics use the sample "
                 "standard deviation (N-1); the log-normal parameters are maximum-likelihood estimates of ln d.")
        try:
            _report.write_markdown_report(path, "SEM grain-size analysis",
                                          [("Statistics", stats), ("Grains", grains)], figure=self.fig, notes=notes)
            messagebox.showinfo("Report", f"Saved {os.path.basename(path)}")
        except Exception as ex:
            messagebox.showerror("Report", str(ex))

    def export_origin(self):
        if not self.records:
            return
        self.save_settings()
        data = [r["nm"] for r in self.records]
        exepath = self.entry_origin.get().strip()

        def run():
            import pythoncom
            pythoncom.CoInitialize()
            ok = try_origin_histogram_direct(data, show_origin=True, force_exe_launch=True, exe_hint=exepath)
            pythoncom.CoUninitialize()
            if ok:
                self.after(0, lambda: messagebox.showinfo("Origin", "Success"))
            else:
                self.after(0, lambda: messagebox.showerror("Origin", "Failed"))

        threading.Thread(target=run, daemon=True).start()

    # =====================
    # Auto Segment (Local)
    # =====================
    def run_auto_segment(self):
        if self.cv_bgr is None:
            messagebox.showwarning("Warning", "Load Image First")
            return

        # Update settings from UI
        try:
            self.SET.seed_max_points = int(self.entry_max_pts.get())
            self.SET.seed_min_distance_px = int(self.entry_min_dist.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid parameters (must be integer)")
            return

        def _worker():
            try:
                # Convert current records to format expected by core if needed,
                # but core expects list of dicts with 'mask'. Our records have 'mask'.
                new_records_core = batch_auto_measure_from_seeds(
                    image_bgr=self.cv_bgr,
                    nm_per_px=self.nm_per_px,
                    settings=self.SET,
                    existing_records=self.records
                )

                # Convert back to UI record format
                start_id = len(self.records) + 1
                added_count = 0
                for r in new_records_core:
                    ui_rec = {
                        "id": start_id + added_count,
                        "nm": r["eq_d_nm"],
                        "mask": r["mask"]
                    }
                    self.records.append(ui_rec)
                    added_count += 1

                self.after(0, lambda: self.refresh_table())
                self.after(0, lambda: messagebox.showinfo("Done", f"Auto-segment added {added_count} grains."))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Error", err))

        threading.Thread(target=_worker, daemon=True).start()


# =========================
# Standalone Entry Point
# =========================
def main():
    ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()
    win = AnalysisWindow(root)
    win.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit()))
    root.mainloop()


if __name__ == "__main__":
    main()
