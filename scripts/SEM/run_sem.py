
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
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import core logic from sem_core.py
try:
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
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("SEM Grain Analysis (Gemini 3.0 / 2.5)")
        # Wider to accommodate expanded right panel without clipping
        self.geometry("1460x900")
        self.minsize(1460, 900)

        # Store data received from main window (per spec)
        self.passed_origin_path = origin_path
        self.passed_api_key = api_key

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
        self.comp_ratio_var = tk.StringVar(value="")
        self.use_antisolvent_var = tk.BooleanVar(value=True)
        self.antisolvent_var = tk.StringVar(value="")
        self.extra_info_var = tk.StringVar(value="")
        self._advisor_win = None
        self.chat_history = []
        self.advisor_model_var = tk.StringVar(value="gemini-3-flash-preview")
        self._advisor_models = {
            "Gemini": [
                "gemini-3-flash-preview",
                "gemini-2.5-flash",
                "gemini-2.0-flash-exp",
                "gemini-1.5-flash",
            ],
        }

        self.mode_add = True
        self.mode_edit = False
        self.brush_radius = self.SET.brush_radius
        self.dragging = False
        self.last_draw_pt = None
        self.dragging_calib = False
        self.draw_path = []
        self.footer_cutoff = None
        self.initial_api_key = ""
        self._nano_win = None

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
        if self.passed_api_key:
            self.entry_api_key.delete(0, "end")
            self.entry_api_key.insert(0, self.passed_api_key)
        self.initial_api_key = self.passed_api_key or self.entry_api_key.get().strip()

        self.bind("<Key>", self.on_key_press)
        self.bind("<Button-1>", self.on_global_click)

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "FE-SEM Analysis", {
                    "open": ("📁 Open Image", self.load_image),
                    "run": ("▶ Auto Segment", self.run_auto_segment),
                    "excel": ("Excel", self.export_excel),
                    "origin": ("Origin", self.export_origin),
                    "ai": ("🤖 AI", self.open_advisor_dialog)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")


    # =====================
    # UI Creation
    # =====================
    def create_left_panel(self):
        # Toss-style color definitions
        self.card_bg = "#1E1E1E"
        self.card_border = "#2D2D2D"
        self.accent_blue = "#3182F6"
        self.accent_orange = "#F59E0B"
        self.text_primary = "#FFFFFF"
        self.text_secondary = "#8B8B8B"

        self.left_frame = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="#141414")
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        # Lock left panel width to JV size
        self.left_frame.grid_propagate(False)
        self.left_scroll = ctk.CTkScrollableFrame(self.left_frame, width=280, fg_color="#141414", corner_radius=0)
        self.left_scroll.pack(fill="both", expand=True)
        left_content = self.left_scroll

        # 1. Load Data card
        load_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkButton(load_card, text="Load SEM Image", command=self.load_image,
                      corner_radius=12, height=40, fg_color=self.accent_blue,
                      hover_color="#2563EB", font=("Segoe UI", 13)).pack(pady=(0, 16), padx=16, fill="x")
        nano_row = ctk.CTkFrame(load_card, fg_color="transparent")
        nano_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkLabel(nano_row, text="Nano Banana", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")
        ctk.CTkButton(nano_row, text="Open", command=self.open_nano_banana,
                      corner_radius=10, height=30, fg_color="#252525",
                      hover_color="#303030", font=("Segoe UI", 11)).pack(side="right")
        self.lbl_shortcuts = ctk.CTkLabel(
            load_card,
            text="Shortcuts: shown after image is loaded.",
            text_color=self.text_secondary,
            font=("Segoe UI", 13),
            justify="left",
            anchor="w",
            wraplength=240,
        )
        self.lbl_shortcuts.pack(pady=(0, 14), padx=(20, 16), anchor="w", fill="x")

        # 2. Calibration card
        calib_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        calib_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(calib_card, text="Calibration", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        sf = ctk.CTkFrame(calib_card, fg_color="transparent")
        sf.pack(fill="x", padx=16)
        ctk.CTkLabel(sf, text="Known (nm)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(side="left")
        self.entry_scale_nm = ctk.CTkEntry(sf, width=100, corner_radius=8, height=32)
        self.entry_scale_nm.insert(0, "100")
        self.entry_scale_nm.pack(side="right")

        self.btn_calib = ctk.CTkButton(calib_card, text="Calibrate", command=self.toggle_calibration,
                                        fg_color="#252525", hover_color="#303030",
                                        corner_radius=12, height=40, font=("Segoe UI", 13))
        self.btn_calib.pack(pady=12, padx=16, fill="x")

        self.btn_calib_auto = ctk.CTkButton(
            calib_card, text="Auto Calibrate (Scale Bar)", command=self.auto_calibrate_from_scale_bar,
            fg_color="#252525", hover_color="#303030", corner_radius=10, height=36, font=("Segoe UI", 11)
        )
        self.btn_calib_auto.pack(pady=(0, 12), padx=16, fill="x")

        self.lbl_scale_info = ctk.CTkLabel(calib_card, text="Scale: Not set",
                                            text_color=self.text_secondary, font=("Segoe UI", 12))
        self.lbl_scale_info.pack(pady=(0, 16))

        # 3. Tools card
        tools_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        tools_card.pack(pady=4, padx=12, fill="x")

        ctk.CTkLabel(tools_card, text="Brush Tool", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(10, 6), padx=16, anchor="w")

        self.slider_brush = ctk.CTkSlider(tools_card, from_=1, to=50, number_of_steps=49,
                                          command=self.update_brush_size,
                                          button_color=self.accent_blue,
                                          button_hover_color="#2563EB",
                                          progress_color=self.accent_blue)
        self.slider_brush.set(self.SET.brush_radius)
        self.slider_brush.pack(padx=16, pady=(0, 4), fill="x")

        self.lbl_brush_val = ctk.CTkLabel(tools_card, text=f"Size: {self.SET.brush_radius}",
                                          text_color=self.text_secondary, font=("Segoe UI", 12))
        self.lbl_brush_val.pack(pady=(4, 10))

        # 4. Actions card (export and other action buttons)
        actions_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        actions_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(actions_card, text="Actions", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        btn_frame = ctk.CTkFrame(actions_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkButton(btn_frame, text="Export Excel", command=self.export_excel,
                      fg_color="#252525", hover_color="#303030",
                      corner_radius=10, height=36, font=("Segoe UI", 12)).pack(fill="x", pady=3)
        ctk.CTkButton(btn_frame, text="Delete Selected", command=self.delete_selected_row,
                      fg_color="#252525", hover_color="#303030",
                      corner_radius=10, height=36, font=("Segoe UI", 12)).pack(fill="x", pady=3)
        ctk.CTkButton(btn_frame, text="Send to Origin", command=self.export_origin,
                      fg_color="#252525", hover_color="#303030",
                      corner_radius=10, height=36, font=("Segoe UI", 12)).pack(fill="x", pady=3)

        # 5. Auto Segment Card (Replaces Status)
        auto_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        auto_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(auto_card, text="Auto Segment", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        # Params
        param_row = ctk.CTkFrame(auto_card, fg_color="transparent")
        param_row.pack(fill="x", padx=16, pady=(0, 4))

        ctk.CTkLabel(param_row, text="Max Pts", text_color=self.text_secondary, font=("Segoe UI", 11)).pack(side="left")
        self.entry_max_pts = ctk.CTkEntry(param_row, width=60, height=28, corner_radius=6)
        self.entry_max_pts.insert(0, str(self.SET.seed_max_points))
        self.entry_max_pts.pack(side="left", padx=(4, 0))

        param_row2 = ctk.CTkFrame(auto_card, fg_color="transparent")
        param_row2.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(param_row2, text="Min Dist", text_color=self.text_secondary, font=("Segoe UI", 11)).pack(side="left")
        self.entry_min_dist = ctk.CTkEntry(param_row2, width=60, height=28, corner_radius=6)
        self.entry_min_dist.insert(0, str(self.SET.seed_min_distance_px))
        self.entry_min_dist.pack(side="left", padx=(4, 0))

        ctk.CTkButton(auto_card, text="Run Auto Segment", command=self.run_auto_segment,
                      fg_color=self.accent_blue, hover_color="#2563EB",
                      corner_radius=12, height=40, font=("Segoe UI", 13)).pack(pady=(8, 16), padx=16, fill="x")

        # 6. Process Advisor (Gemini)
        advisor_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        advisor_card.pack(pady=8, padx=12, fill="both", expand=True)
        advisor_card.bind("<Button-1>", lambda e: self.open_advisor_dialog())

        header_row = ctk.CTkFrame(advisor_card, fg_color="transparent")
        header_row.pack(pady=(16, 6), padx=16, fill="x")
        header_row.bind("<Button-1>", lambda e: self.open_advisor_dialog())

        ctk.CTkLabel(header_row, text="Process Advisor", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(side="left")
        ctk.CTkLabel(header_row, text="Click to open", font=("Segoe UI", 11),
                     text_color=self.text_secondary).pack(side="right")

        ctk.CTkLabel(advisor_card,
                     text="Enter composition / antisolvent conditions\nto get grain-size based advice.",
                     text_color=self.text_secondary,
                     font=("Segoe UI", 11),
                     justify="left").pack(pady=(0, 8), padx=16, anchor="w")

        self.lbl_advice_status = ctk.CTkLabel(
            advisor_card,
            text="Ready",
            text_color=self.text_secondary,
            font=("Segoe UI", 11),
            wraplength=240,
            justify="left"
        )
        self.lbl_advice_status.pack(pady=(0, 8), padx=16, anchor="w", fill="x")

        ctk.CTkButton(
            advisor_card, text="Open Advisor", command=self.open_advisor_dialog,
            fg_color="#252525", hover_color="#303030", corner_radius=10, height=32, font=("Segoe UI", 12)
        ).pack(padx=16, pady=(0, 16), fill="x")

        # Hidden entries for settings (API key, Origin path) & model combo
        self.entry_origin = ctk.CTkEntry(self.left_frame, height=1)
        detected = find_origin_exe_from_registry()
        if detected:
            self.entry_origin.insert(0, detected)
        self.entry_api_key = ctk.CTkEntry(self.left_frame, show="*", height=1)
        model_list = [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.0-flash-exp",
            "gemini-1.5-flash"
        ]
        self.combo_model = ctk.CTkComboBox(self.left_frame, values=model_list, height=1)
        self.combo_model.set("gemini-3-flash-preview")

        # Spacer to push shortcuts to bottom
        spacer = ctk.CTkFrame(left_content, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        # Shortcuts card (bottom)
        shortcuts_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        shortcuts_card.pack(pady=(8, 16), padx=12, fill="x")

        ctk.CTkLabel(shortcuts_card, text="Shortcuts", font=("Segoe UI", 13, "bold"),
                     text_color=self.text_secondary).pack(pady=(12, 8), padx=16, anchor="w")

        shortcuts_text = "M Save  •  N Discard  •  Z/X Undo/Redo\n[/] Size  •  P Eraser  •  Right-click Toggle"
        ctk.CTkLabel(shortcuts_card, text=shortcuts_text, justify="left",
                     text_color="#666666", font=("Segoe UI", 11)).pack(padx=16, pady=(0, 12), anchor="w")

    def open_nano_banana(self):
        api_key = self.initial_api_key or self.entry_api_key.get().strip()
        if api_key:
            self.clipboard_clear()
            self.clipboard_append(api_key)

        url = (
            "https://aistudio.google.com/app/prompts/new_chat"
            "?model=models%2Fgemini-3-pro-image-preview"
            "&prompt=Generate%20an%20image%20of%20a%20banana%20wearing%20a%20costume."
        )
        webbrowser.open_new_tab(url)

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0A0A0A")
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(0, weight=1)
        self.center_frame.grid_columnconfigure(0, weight=1)

        # Canvas container (for padding)
        canvas_container = ctk.CTkFrame(self.center_frame, corner_radius=12, fg_color="#1E1E1E")
        canvas_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        self.v_scroll = ctk.CTkScrollbar(canvas_container, orientation="vertical")
        self.h_scroll = ctk.CTkScrollbar(canvas_container, orientation="horizontal")
        self.canvas = tk.Canvas(canvas_container, bg="#141414", highlightthickness=0,
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
        self.right_resizer = tk.Frame(self, width=10, bg="#3D3D3D", cursor="sb_h_double_arrow")
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
        self.right_frame = ctk.CTkFrame(self, width=self.right_width, corner_radius=0, fg_color="#141414")
        self.right_frame.grid(row=0, column=3, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        # Statistics card
        stats_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        stats_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats_card, text="Statistics", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        # Statistics grid layout
        stats_grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_grid.pack(fill="x", padx=16, pady=(0, 16))

        # Mean & Std Row
        row1 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row1.pack(fill="x", pady=4)

        mean_box = ctk.CTkFrame(row1, corner_radius=10, fg_color="#252525")
        mean_box.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkLabel(mean_box, text="Mean", text_color=self.text_secondary,
                     font=("Segoe UI", 10)).pack(pady=(8, 2))
        self.lbl_stats_mean = ctk.CTkLabel(mean_box, text="- nm", font=("Segoe UI", 14, "bold"),
                                           text_color=self.accent_blue)
        self.lbl_stats_mean.pack(pady=(0, 8))

        std_box = ctk.CTkFrame(row1, corner_radius=10, fg_color="#252525")
        std_box.pack(side="right", expand=True, fill="x", padx=(4, 0))
        ctk.CTkLabel(std_box, text="Std Dev", text_color=self.text_secondary,
                     font=("Segoe UI", 10)).pack(pady=(8, 2))
        self.lbl_stats_std = ctk.CTkLabel(std_box, text="- nm", font=("Segoe UI", 14, "bold"),
                                          text_color=self.accent_blue)
        self.lbl_stats_std.pack(pady=(0, 8))

        # Min & Max Row
        row2 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row2.pack(fill="x", pady=4)

        min_box = ctk.CTkFrame(row2, corner_radius=10, fg_color="#252525")
        min_box.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkLabel(min_box, text="Min", text_color=self.text_secondary,
                     font=("Segoe UI", 10)).pack(pady=(8, 2))
        self.lbl_stats_min = ctk.CTkLabel(min_box, text="- nm", font=("Segoe UI", 14, "bold"),
                                          text_color="#10B981")
        self.lbl_stats_min.pack(pady=(0, 8))

        max_box = ctk.CTkFrame(row2, corner_radius=10, fg_color="#252525")
        max_box.pack(side="right", expand=True, fill="x", padx=(4, 0))
        ctk.CTkLabel(max_box, text="Max", text_color=self.text_secondary,
                     font=("Segoe UI", 10)).pack(pady=(8, 2))
        self.lbl_stats_max = ctk.CTkLabel(max_box, text="- nm", font=("Segoe UI", 14, "bold"),
                                          text_color="#EF4444")
        self.lbl_stats_max.pack(pady=(0, 8))

        # Results card (table)
        results_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        results_card.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(results_card, text="Results", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).grid(row=0, column=0, pady=(16, 8), padx=16, sticky="w")

        # Table style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#1E1E1E",
                        foreground="white",
                        fieldbackground="#1E1E1E",
                        borderwidth=0,
                        rowheight=30,
                        font=("Segoe UI", 11))
        style.configure("Treeview.Heading",
                        background="#252525",
                        foreground="white",
                        borderwidth=0,
                        font=("Segoe UI", 11, "bold"))
        style.map("Treeview", background=[("selected", "#3182F6")])

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
        hist_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        hist_card.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 16))
        self.right_frame.grid_rowconfigure(2, weight=2)  # larger weight

        ctk.CTkLabel(hist_card, text="Distribution", font=("Segoe UI", 15, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.hist_frame = ctk.CTkFrame(hist_card, fg_color="#252525", corner_radius=12)
        self.hist_frame.pack(fill="both", expand=True, padx=12, pady=(0, 16))

        self.fig = Figure(figsize=(4, 3), dpi=100, facecolor='#252525')
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor('#252525')
        self.ax.set_facecolor('#252525')
        self.ax.tick_params(colors='#AAAAAA', labelsize=10, width=1)
        self.ax.tick_params(axis='both', which='major', labelsize=10)
        for spine in self.ax.spines.values():
            spine.set_color('#2D2D2D')
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
                    self.entry_api_key.delete(0, "end")
                    self.entry_api_key.insert(0, data.get("api_key", ""))
                    saved_model = data.get("model_name", "")
                    if saved_model:
                        self.combo_model.set(saved_model)
                    saved_ratio = data.get("composition_ratio", "")
                    if saved_ratio:
                        self.comp_ratio_var.set(saved_ratio)
                    self.use_antisolvent_var.set(True)
                    saved_anti = data.get("antisolvent_condition", "")
                    if saved_anti:
                        self.antisolvent_var.set(saved_anti)
                    saved_extra = data.get("extra_info", "")
                    if saved_extra:
                        self.extra_info_var.set(saved_extra)
                    saved_model = data.get("advisor_model", "")
                    if saved_model:
                        self.advisor_model_var.set(saved_model)
            except:
                pass

    def save_settings(self):
        data = {
            "origin_path": self.entry_origin.get().strip(),
            "api_key": self.entry_api_key.get().strip(),
            "model_name": self.combo_model.get().strip(),
            "composition_ratio": self.comp_ratio_var.get().strip(),
            "use_antisolvent": bool(self.use_antisolvent_var.get()),
            "antisolvent_condition": self.antisolvent_var.get().strip(),
            "extra_info": self.extra_info_var.get().strip(),
            "advisor_model": self.advisor_model_var.get().strip(),
        }
        try:
            with open(self.config_file, "w") as f:
                json.dump(data, f)
        except:
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
        path = filedialog.askopenfilename()
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
            self.lbl_advice_status.configure(text="Ready", text_color=self.text_secondary)
            if hasattr(self, "list_advice"):
                self.list_advice.delete(0, "end")
            self.advice_items = []
            return
        vals = [r["nm"] for r in self.records]
        self.ax.hist(vals, bins=10, color='#1f538d', edgecolor='white', alpha=0.7)
        self.ax.set_title(f"N={len(vals)}", color='white', fontsize=10)
        self.fig.tight_layout()
        self.canvas_hist.draw()

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
    # Process Advisor (Gemini)
    # =====================
    def _set_advice_status(self, text, color=None):
        if color is None:
            color = self.text_secondary
        self.lbl_advice_status.configure(text=text, text_color=color)

    def _append_chat(self, role, text):
        if self._advisor_win is None or not self._advisor_win.winfo_exists():
            return
        if not hasattr(self, "chat_log"):
            return
        self.chat_log.configure(state="normal")
        prefix = "You: " if role == "user" else "Gemini: "
        self.chat_log.insert("end", f"{prefix}{text}\n\n")
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

    def _append_chat_rich(self, role, text):
        if self._advisor_win is None or not self._advisor_win.winfo_exists():
            return
        if not hasattr(self, "chat_log"):
            return
        if text is None:
            return
        prefix = "You: " if role == "user" else "Gemini: "
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", prefix)
        parts = re.split(r"(\[RED\].*?\[/RED\])", text, flags=re.IGNORECASE | re.DOTALL)
        for part in parts:
            if not part:
                continue
            m = re.match(r"\[RED\](.*?)\[/RED\]", part, flags=re.IGNORECASE | re.DOTALL)
            if m:
                self.chat_log.insert("end", m.group(1), ("red",))
            else:
                self.chat_log.insert("end", part)
        self.chat_log.insert("end", "\n\n")
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

    def _append_chat_streamed(self, role, text, delay_ms=15, chunk_size=20):
        if self._advisor_win is None or not self._advisor_win.winfo_exists():
            return
        if not hasattr(self, "chat_log"):
            return

        prefix = "You: " if role == "user" else "Gemini: "
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", prefix)
        self.chat_log.configure(state="disabled")
        self.chat_log.see("end")

        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

        def _step(idx=0):
            if self._advisor_win is None or not self._advisor_win.winfo_exists():
                return
            if not hasattr(self, "chat_log"):
                return
            if idx >= len(chunks):
                self.chat_log.configure(state="normal")
                self.chat_log.insert("end", "\n\n")
                self.chat_log.configure(state="disabled")
                self.chat_log.see("end")
                return
            self.chat_log.configure(state="normal")
            self.chat_log.insert("end", chunks[idx])
            self.chat_log.configure(state="disabled")
            self.chat_log.see("end")
            self.after(delay_ms, lambda: _step(idx + 1))

        _step()

    def _update_advice_list(self, items):
        self.advice_items = items
        if not items:
            self._set_advice_status("No suggestions", "#F59E0B")
            self._append_chat_rich("assistant", "No suggestions returned.")
            return
        msg = "\n".join([f"- {line}" for line in items])
        self._append_chat_rich("assistant", msg)

    def _build_context_text(self):
        comp_ratio = self.comp_ratio_var.get().strip()
        anti_text = self.antisolvent_var.get().strip()
        extra_info = self._get_extra_info()
        vals = [r["nm"] for r in self.records]
        mean_nm = float(np.mean(vals)) if vals else 0.0
        std_nm = float(np.std(vals)) if vals else 0.0
        min_nm = float(np.min(vals)) if vals else 0.0
        max_nm = float(np.max(vals)) if vals else 0.0
        n = len(vals)
        anti_part = f"Antisolvent condition: {anti_text}." if anti_text else "Antisolvent condition: not provided."
        extra_part = f"Extra conditions: {extra_info}." if extra_info else "Extra conditions: not provided."
        return (
            f"Composition ratio: {comp_ratio}.\n"
            f"{anti_part}\n"
            f"{extra_part}\n"
            f"Grain stats: N={n}, mean={mean_nm:.1f} nm, std={std_nm:.1f} nm, "
            f"min={min_nm:.1f} nm, max={max_nm:.1f} nm."
        )

    def _get_extra_info(self):
        if self._advisor_win is not None and self._advisor_win.winfo_exists():
            if hasattr(self, "txt_extra_info"):
                try:
                    return self.txt_extra_info.get("1.0", "end").strip()
                except Exception:
                    pass
        return self.extra_info_var.get().strip()

    def _get_advisor_model(self):
        model = self.advisor_model_var.get().strip()
        if not model:
            model = (self._advisor_models.get("Gemini") or [""])[0]
        return model

    def _call_gemini(self, model, api_key, prompt):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(model)
        resp = gmodel.generate_content(prompt)
        return (resp.text or "").strip()

    def _format_advisor_text(self, text):
        # Remove markdown-like symbols and normalize into a readable list + summary
        if not text:
            return ""
        cleaned = text.replace("***", "").replace("**", "").replace("*", "")
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        out = []
        idx = 1
        in_summary = False
        for ln in lines:
            l = ln.lstrip("-•").strip()
            if l.lower().startswith("summary") or l.startswith("Summary"):
                in_summary = True
                continue
            if in_summary:
                continue
            out.append(f"{idx}) {l}")
            idx += 1
        return "\n".join(out)

    def open_advisor_dialog(self):
        if self._advisor_win is not None and self._advisor_win.winfo_exists():
            self._advisor_win.focus()
            return

        win = ctk.CTkToplevel(self)
        win.title("Process Advisor")
        win.geometry("520x540")
        win.attributes("-topmost", True)
        self._advisor_win = win

        header = ctk.CTkFrame(win, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="Process Advisor", font=("Segoe UI", 16, "bold")).pack(side="left")

        ctk.CTkLabel(win, text="Composition", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
        entry_comp = ctk.CTkEntry(win, textvariable=self.comp_ratio_var,
                                  placeholder_text="FA:MA:Cs=0.8:0.1:0.1")
        entry_comp.pack(fill="x", padx=16, pady=(4, 10))

        model_row = ctk.CTkFrame(win, fg_color="transparent")
        model_row.pack(fill="x", padx=16, pady=(0, 8))
        model_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(model_row, text="Gemini model", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.combo_advisor_model = ctk.CTkComboBox(
            model_row,
            values=[],
            command=lambda v: self.advisor_model_var.set(v),
        )
        self.combo_advisor_model.pack(fill="x", pady=(4, 0))

        anti_row = ctk.CTkFrame(win, fg_color="transparent")
        anti_row.pack(fill="x", padx=16, pady=(0, 6))
        chk = ctk.CTkSwitch(
            anti_row,
            text="Antisolvent used",
            variable=self.use_antisolvent_var,
            command=lambda: toggle_anti_entry(),
        )
        chk.pack(side="left")
        chk.configure(state="disabled")

        entry_anti = ctk.CTkEntry(
            win,
            textvariable=self.antisolvent_var,
            placeholder_text="Antisolvent (e.g., CB 150uL @ 15s)",
        )
        entry_anti.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(win, text="Extra conditions", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
        self.txt_extra_info = ctk.CTkTextbox(win, height=90)
        self.txt_extra_info.pack(fill="x", padx=16, pady=(4, 10))
        if self.extra_info_var.get().strip():
            self.txt_extra_info.insert("1.0", self.extra_info_var.get().strip())

        def update_model_list():
            models = self._advisor_models.get("Gemini", [])
            if not models:
                models = ["gemini-2.5-flash"]
            self.combo_advisor_model.configure(values=models)
            current = self.advisor_model_var.get().strip()
            if current not in models:
                current = models[0]
                self.advisor_model_var.set(current)
            self.combo_advisor_model.set(current)

        def toggle_anti_entry():
            if self.use_antisolvent_var.get():
                entry_anti.configure(state="normal")
            else:
                self.antisolvent_var.set("")
                entry_anti.configure(state="disabled")

        update_model_list()
        toggle_anti_entry()

        def on_close():
            self.extra_info_var.set(self._get_extra_info())
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))
        self.btn_advice = ctk.CTkButton(
            btn_row, text="Get Suggestions", command=self.get_process_advice,
            fg_color="#252525", hover_color="#303030", corner_radius=10, height=32, font=("Segoe UI", 12)
        )
        self.btn_advice.pack(side="left", fill="x", expand=True)

        status = ctk.CTkLabel(
            win,
            text="Ready",
            text_color=self.text_secondary,
            font=("Segoe UI", 11),
            wraplength=460,
            justify="left"
        )
        status.pack(padx=16, pady=(0, 6), anchor="w", fill="x")
        self.lbl_advice_status = status

        chat_frame = ctk.CTkFrame(win, fg_color="#252525", corner_radius=10)
        chat_frame.pack(padx=16, pady=(0, 10), fill="both", expand=True)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_log = tk.Text(
            chat_frame,
            height=10,
            bg="#1E1E1E",
            fg="white",
            wrap="word",
            highlightthickness=0,
            spacing1=4,
            spacing2=2,
            spacing3=6,
        )
        self.chat_log.tag_config("red", foreground="#EF4444")
        self.chat_log.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        chat_scroll = ctk.CTkScrollbar(chat_frame, orientation="vertical", command=self.chat_log.yview)
        chat_scroll.grid(row=0, column=1, sticky="ns", padx=6, pady=6)
        self.chat_log.configure(yscrollcommand=chat_scroll.set, state="disabled")

        input_row = ctk.CTkFrame(win, fg_color="transparent")
        input_row.pack(fill="x", padx=16, pady=(0, 16))
        input_row.grid_columnconfigure(0, weight=1)

        self.entry_chat = ctk.CTkEntry(input_row, placeholder_text="Enter a question or comment...")
        self.entry_chat.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry_chat.bind("<Return>", lambda e: self.send_chat_message())

        ctk.CTkButton(
            input_row, text="Send", command=self.send_chat_message,
            fg_color=self.accent_blue, hover_color="#2563EB", corner_radius=10, height=32
        ).grid(row=0, column=1)

        if self.chat_history:
            for msg in self.chat_history:
                self._append_chat(msg["role"], msg["content"])
        elif self.advice_items:
            self._update_advice_list(self.advice_items)

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

    def get_process_advice(self):
        # Ensure chat window is visible for live interaction
        if self._advisor_win is None or not self._advisor_win.winfo_exists():
            self.open_advisor_dialog()

        comp_ratio = self.comp_ratio_var.get().strip()
        if not comp_ratio:
            messagebox.showwarning("Advisor", "Enter a composition ratio first.")
            return
        if self.current_mean_nm is None or not self.records:
            messagebox.showwarning("Advisor", "Mean grain size is not available yet.")
            return

        self.extra_info_var.set(self._get_extra_info())

        api_key = self.passed_api_key or self.entry_api_key.get().strip()
        model_name = self._get_advisor_model()
        if not api_key:
            messagebox.showwarning("Advisor", "API Key Required")
            return

        self.save_settings()
        self.btn_advice.configure(state="disabled", text="Analyzing...")
        self._set_advice_status("Connecting to Gemini...", "#F59E0B")

        def _worker():
            try:
                import google.generativeai as genai
            except ImportError:
                msg = "Missing dependency: google-generativeai"
                self.after(0, lambda: messagebox.showerror("Advisor", msg))
                vals = [r["nm"] for r in self.records]
                mean_nm = float(np.mean(vals)) if vals else 0.0
                std_nm = float(np.std(vals)) if vals else 0.0
                min_nm = float(np.min(vals)) if vals else 0.0
                max_nm = float(np.max(vals)) if vals else 0.0
                n = len(vals)
                tips = self._fallback_advice(mean_nm, std_nm, min_nm, max_nm, n)
                self.after(0, lambda: self._update_advice_list(tips))
                self.after(0, lambda: self._set_advice_status("Fallback suggestions", "#F59E0B"))
                self.after(0, lambda: self.btn_advice.configure(state="normal", text="Get Suggestions"))
                return

            error_msg = ""
            try:
                prompt = (
                    "You are a process advisor for SEM grain size optimization. "
                    "Given composition ratio and current SEM grain statistics, suggest practical changes. "
                    "Respond in English with detailed, structured guidance like a lab mentor. "
                    "Include rationale, expected effects, and potential trade-offs. "
                    "Provide exactly 3 high-impact strategies (no more). Do NOT add a summary.\n"
                    "Highlight important phrases by wrapping with [RED]...[/RED].\n"
                    "Do NOT use markdown or special symbols (no *, **, ***, #, bullets). Plain text only.\n\n"
                    f"{self._build_context_text()}"
                )
                full = self._call_gemini(model_name, api_key, prompt)
                if not (full or "").strip():
                    raise RuntimeError("Empty response from Gemini.")
                formatted = self._format_advisor_text(full)
                items = [line.strip() for line in formatted.splitlines() if line.strip()]
            except Exception as e:
                error_msg = str(e)
                items = []

            if not items:
                vals = [r["nm"] for r in self.records]
                mean_nm = float(np.mean(vals)) if vals else 0.0
                std_nm = float(np.std(vals)) if vals else 0.0
                min_nm = float(np.min(vals)) if vals else 0.0
                max_nm = float(np.max(vals)) if vals else 0.0
                n = len(vals)
                items = self._fallback_advice(mean_nm, std_nm, min_nm, max_nm, n)
                status = "Fallback suggestions"
                if error_msg:
                    status = f"Fallback suggestions (Gemini error: {error_msg})"
                self.after(0, lambda s=status: self._set_advice_status(s, "#F59E0B"))
            else:
                self.after(0, lambda: self._set_advice_status("Suggestions ready", self.text_secondary))

            if items:
                msg = "\n".join(items)
                self.after(0, lambda t=msg: self._append_chat_rich("assistant", t))
                self.chat_history.append({"role": "assistant", "content": msg})
            else:
                self.after(0, lambda: self._append_chat_rich("assistant", "No suggestions returned."))
            self.after(0, lambda: self.btn_advice.configure(state="normal", text="Get Suggestions"))

        threading.Thread(target=_worker, daemon=True).start()

    def send_chat_message(self):
        if not hasattr(self, "entry_chat"):
            return
        msg = self.entry_chat.get().strip()
        if not msg:
            return
        if self.current_mean_nm is None or not self.records:
            messagebox.showwarning("Advisor", "Mean grain size is not available yet.")
            return

        api_key = self.passed_api_key or self.entry_api_key.get().strip()
        model_name = self._get_advisor_model()
        if not api_key:
            messagebox.showwarning("Advisor", "API Key Required")
            return

        self.extra_info_var.set(self._get_extra_info())
        self.entry_chat.delete(0, "end")
        self.chat_history.append({"role": "user", "content": msg})
        self._append_chat("user", msg)
        self._set_advice_status("Thinking...", "#F59E0B")

        def _worker():
            try:
                import google.generativeai as genai
            except ImportError:
                reply = "Required library is missing. (install google-generativeai)"
                self.after(0, lambda: self._append_chat_rich("assistant", reply))
                self.after(0, lambda: self._set_advice_status("Fallback", "#F59E0B"))
                return

            error_msg = ""
            try:
                history_text = ""
                for h in self.chat_history[-6:]:
                    role = "User" if h["role"] == "user" else "Assistant"
                    history_text += f"{role}: {h['content']}\n"
                prompt = (
                    "You are a process advisor for SEM grain size optimization. "
                    "Respond in English with detailed, structured guidance like a lab mentor. "
                    "Be technical and practical. "
                    "If the question is complex, answer with best-effort reasoning and note assumptions; "
                    "do NOT ask the user to simplify. If information is missing, ask one targeted question "
                    "and still provide actionable guidance. "
                    "Include rationale, expected effects, and potential trade-offs. "
                    "Provide exactly 3 high-impact strategies (no more). Do NOT add a summary.\n"
                    "Highlight important phrases by wrapping with [RED]...[/RED].\n"
                    "Do NOT use markdown or special symbols (no *, **, ***, #, bullets). Plain text only.\n\n"
                    f"{self._build_context_text()}\n\n"
                    f"Conversation:\n{history_text}\n"
                    "Assistant:"
                )
                reply = self._call_gemini(model_name, api_key, prompt)
            except Exception as e:
                error_msg = str(e)
                reply = "Failed to generate a response. Try describing the conditions more simply."

            if not (reply or "").strip():
                if not error_msg:
                    error_msg = "Empty response"
                reply = "Failed to generate a response. I will still estimate as best I can. Providing key conditions (composition/solvent/spin/annealing) improves accuracy."
            reply = self._format_advisor_text(reply)
            self.chat_history.append({"role": "assistant", "content": reply})
            self.after(0, lambda t=reply: self._append_chat_rich("assistant", t))
            if error_msg:
                self.after(0, lambda s=f"Fallback reply (Gemini error: {error_msg})": self._set_advice_status(s, "#F59E0B"))
            else:
                self.after(0, lambda: self._set_advice_status("Ready", self.text_secondary))

        threading.Thread(target=_worker, daemon=True).start()

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
            pd.DataFrame([{"ID": r["id"], "Size(nm)": r["nm"]} for r in self.records]).to_excel(p, index=False)
            messagebox.showinfo("Export", "Saved")

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

    # =====================
    # Gemini Auto-Detection
    # =====================
    def run_gemini_detection(self):
        self.save_settings()
        api_key = self.passed_api_key or self.entry_api_key.get().strip()
        model_name = self.combo_model.get().strip()

        if not api_key:
            messagebox.showwarning("Gemini", "API Key Required")
            return
        if self.cv_bgr is None:
            messagebox.showwarning("Gemini", "Load Image First")
            return

        try:
            import google.generativeai as genai
        except ImportError:
            messagebox.showerror("Error", "pip install google-generativeai needed")
            return

        # Progress Popup
        self.progress_window = ctk.CTkToplevel(self)
        self.progress_window.title("AI Analysis")
        self.progress_window.geometry("300x150")
        self.progress_window.attributes("-topmost", True)

        lbl_info = ctk.CTkLabel(self.progress_window, text="Initializing...", font=("Segoe UI", 14))
        lbl_info.pack(pady=20)

        pbar = ctk.CTkProgressBar(self.progress_window, width=250)
        pbar.pack(pady=10)
        pbar.set(0)

        self.btn_gemini.configure(state="disabled")

        def update_popup(text, val):
            if self.progress_window.winfo_exists():
                lbl_info.configure(text=text)
                pbar.set(val)

        def _worker():
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(model_name)

                safety = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]

                # 1. Tiling
                self.after(0, lambda: update_popup("Tiling Image...", 0.1))
                tiles = get_tiles(self.cv_bgr, grid=(2, 2), overlap=100)
                all_points = []

                total_tiles = len(tiles)
                start_time = time.time()

                for i, (tile_img, off_x, off_y) in enumerate(tiles):
                    elapsed = time.time() - start_time
                    if i > 0:
                        avg_t = elapsed / i
                        rem_t = avg_t * (total_tiles - i)
                        eta = f"{int(rem_t)}s"
                    else:
                        eta = "..."

                    prog = 0.1 + 0.8 * (i / total_tiles)
                    msg = f"Analyzing... {int(prog * 100)}% (ETA: {eta})"
                    self.after(0, lambda m=msg, p=prog: update_popup(m, p))

                    th, tw = tile_img.shape[:2]
                    scale = 1.0
                    if max(th, tw) > 1024:
                        scale = 1024 / max(th, tw)
                        tile_resized = cv2.resize(tile_img, (0, 0), fx=scale, fy=scale)
                    else:
                        tile_resized = tile_img

                    rgb = cv2.cvtColor(tile_resized, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb)

                    prompt = (
                        "Detect the center [x, y] of EVERY SINGLE grain in this SEM image tile. "
                        "Do NOT miss small grains. "
                        "Return ONLY JSON: { \"points\": [[x1, y1], [x2, y2], ...] }"
                    )

                    try:
                        resp = model.generate_content([prompt, pil_img], safety_settings=safety)
                        txt = resp.text.strip()
                        match = re.search(r'\{.*\}', txt, re.DOTALL)
                        if match:
                            txt = match.group(0)

                        if not txt.endswith("}"):
                            txt += "]}"
                        data = json.loads(txt)

                        for pt in data.get("points", []):
                            gx = int(pt[0] / scale) + off_x
                            gy = int(pt[1] / scale) + off_y
                            all_points.append((gx, gy))

                    except Exception as e:
                        print(f"Tile {i} error: {e}")
                        continue

                    time.sleep(1.0)

                # 2. Remove duplicates
                self.after(0, lambda: update_popup("Merging Results...", 0.95))
                final_pts = remove_duplicate_points(all_points, threshold=20)

                if not final_pts:
                    raise Exception("No grains found")

                self.after(0, lambda: self._process_gemini_results(final_pts))
                self.after(0, lambda: self.progress_window.destroy())
                self.after(0, lambda: messagebox.showinfo("Done", f"Detected {len(final_pts)} grains."))

            except Exception as e:
                self.after(0, lambda: self.progress_window.destroy())
                self.after(0, lambda err=str(e): messagebox.showerror("Gemini Error", err))
            finally:
                self.after(0, lambda: self.btn_gemini.configure(state="normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def _process_gemini_results(self, points):
        count = 0
        h, w = self.cv_bgr.shape[:2]

        for pt in points:
            x, y = int(pt[0]), int(pt[1])
            if 0 <= x < w and 0 <= y < h:
                if is_point_in_existing(self.records, x, y):
                    continue

                self._perform_auto_segment(x, y)

                if self.mask is not None:
                    if check_mask_overlap(self.records, self.mask):
                        self.mask = None
                        self.mode_edit = False
                        self.update_display()
                        continue

                    _, _, eq_d_nm = area_and_eq_diameter(self.mask, self.nm_per_px)
                    if eq_d_nm < 100.0:
                        self.mask = None
                        self.mode_edit = False
                        self.update_display()
                        continue

                    self.save_grain()
                    count += 1


# =========================
# Standalone Entry Point
# =========================
def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()
    win = AnalysisWindow(root)
    win.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit()))
    root.mainloop()


if __name__ == "__main__":
    main()
