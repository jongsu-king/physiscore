"""
run_pl.py - Fixed Origin Plot & FWHM Visualization
"""
import os
import sys

# Add script directory to path for local imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import threading
import re
from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None

try:
    from . import pl_core
except ImportError:
    import pl_core

class AIConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent, api_key, on_confirm):
        super().__init__(parent)
        self.title("Interpretation settings")
        self.geometry("500x400")
        self.api_key = api_key
        self.on_confirm = on_confirm
        self.attributes('-topmost', True)
        
        ctk.CTkLabel(self, text="Select Gemini Model:", font=_pal.font(12, "bold")).pack(pady=(20, 5))
        self.combo_model = ctk.CTkComboBox(self, values=["Fetching models..."], width=300)
        self.combo_model.pack(pady=5)
        
        ctk.CTkLabel(self, text="Sample Context / Additional Info:", font=_pal.font(12, "bold")).pack(pady=(15, 5))
        self.txt_context = ctk.CTkTextbox(self, width=400, height=150)
        self.txt_context.pack(pady=5)
        
        ctk.CTkButton(self, text="Run Analysis", command=self.on_click_run, fg_color=_pal.BG_SUB, width=200, height=28, text_color=_pal.TXT).pack(pady=20)
        
        threading.Thread(target=self.fetch_models, daemon=True).start()
        
    def fetch_models(self):
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            if not models: models = ["models/gemini-2.5-flash"]
            self.after(0, lambda: self.combo_model.configure(values=models))
            self.after(0, lambda: self.combo_model.set(models[0]))
        except: self.after(0, lambda: self.combo_model.configure(values=["models/gemini-2.5-flash"]))

    def on_click_run(self):
        self.on_confirm(self.combo_model.get(), self.txt_context.get("1.0", "end").strip())
        self.destroy()

class PLAnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("PL Analysis")
        self.geometry("1400x900")
        self.origin_path = origin_path
        self.api_key = api_key
        
        self.df = None
        self.preview_timer = None
        self.last_results_df = None
        self.ai_result_text = "" # Store AI result for export
        self.processed_data = {} # {col_name: y_processed} for Origin
        
        # State variables
        self.preview_timer = None
        
        # Define UI Variables
        self.var_layer_mode = ctk.StringVar(value="1 Layer") # "1 Layer", "2 Layer"
        self.var_sample_col = ctk.StringVar(value="")
        self.var_ref_col = ctk.StringVar(value="")
        
        # Filter Parameters (with default values matching summary logic)
        self.var_filter_width = ctk.DoubleVar(value=0.0)   # 0 = Raw
        self.var_rigidity = ctk.DoubleVar(value=0.0)       # 0 = Raw
        self.var_protection = ctk.DoubleVar(value=0.0)     # 0 = Raw
        self.var_unit = ctk.StringVar(value="nm")          # X-axis unit

        # Theme (match JV)
        self.card_bg = _pal.BG_CARD
        self.card_border = _pal.BORDER
        self.panel_bg = _pal.BG_PANEL
        self.center_bg = _pal.BG_WINDOW
        self.text_primary = _pal.TXT
        self.text_secondary = _pal.TXT_SUB
        self.accent_blue = _pal.ACCENT
        self.accent_green = _pal.GREEN
        self.accent_purple = _pal.PURPLE
        self.accent_pink = _pal.PINK
        self.accent_red = _pal.RED
        self.accent_orange = _pal.ORANGE

        self.file_path_var = tk.StringVar()
        self.left_width = 280
        self.min_left_width = 220
        self.max_left_width = 420
        self._drag_start_x = None
        self._drag_start_left_width = None
        self.resizer_width = 8

        self._setup_ui()
        self._setup_bindings()

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "PL Analysis", {
                    "open": ("Open", self.load_data),
                    "run": ("Run analysis", self.run_analysis),
                    "extra": [("Compare files", self.open_compare)],
                    "excel": ("Excel", self.export_excel),
                    "png": True,
                    "report": ("Report", self.export_report),
                    "origin": ("Origin", self.send_to_origin),
                    "ai": ("Interpretation", self.run_ai_analysis)
                }, hints="Sliders update the preview live  |  Wheel: zoom (Ctrl = x, Shift = y)  |  Drag: pan  |  "
                         "Double-click: auto range  |  Double-click a role row to cycle its role")
            except Exception as _ce:
                print(f"shell skip: {_ce}")


    def _setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, minsize=self.left_width)
        self.grid_columnconfigure(1, minsize=self.resizer_width)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, minsize=520)   # results panel: fixed width, scrolls sideways

        # === Left Control Panel ===
        self.left_panel = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=self.panel_bg)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.left_panel.grid_propagate(False)

        self.left_scroll = ctk.CTkScrollableFrame(self.left_panel, width=280, fg_color=self.panel_bg, corner_radius=0)
        self.left_scroll.pack(fill="both", expand=True)
        left_content = self.left_scroll

        # Header
        ctk.CTkLabel(left_content, text="PL Analysis", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(20, 10))

        # 1. Load Data Card
        load_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        load_card.pack(fill="x", padx=12, pady=(8, 6))

        ctk.CTkLabel(load_card, text="Load Data", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        file_row = ctk.CTkFrame(load_card, fg_color="transparent")
        file_row.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_file = ctk.CTkEntry(file_row, textvariable=self.file_path_var,
                                       placeholder_text="Select file...", height=28)
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(file_row, text="...", width=40, height=28,
                      command=self.browse_file, corner_radius=_pal.R_PILL).pack(side="right")

        self.btn_load = ctk.CTkButton(
            load_card, text="Load data", command=self.load_data,
            height=30, corner_radius=_pal.R_CARD, fg_color=self.accent_blue, hover_color=_pal.ACCENT_HOV,
            font=_pal.font(11)
        )
        self.btn_load.pack(fill="x", padx=16, pady=(0, 16))

        # 2. Mode Card
        mode_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        mode_card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(mode_card, text="Mode", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkLabel(mode_card, text="Layer Mode:", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(anchor="w", padx=16)
        self.seg_layer = ctk.CTkSegmentedButton(mode_card, values=["1 Layer", "2 Layer"],
                                                variable=self.var_layer_mode, command=self.on_mode_change)
        self.seg_layer.pack(fill="x", padx=16, pady=(6, 16))
        self.seg_layer.set("1 Layer")

        # 3. Column Selection Card
        self.frame_cols = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        self.frame_cols.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(self.frame_cols, text="Columns", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkLabel(self.frame_cols, text="Sample Column:", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(anchor="w", padx=16)
        self.opt_sample = ctk.CTkOptionMenu(self.frame_cols, variable=self.var_sample_col, command=self.on_col_change)
        self.opt_sample.pack(fill="x", padx=16, pady=2)

        self.lbl_ref = ctk.CTkLabel(self.frame_cols, text="Reference Column:",
                                    text_color=self.text_secondary, font=_pal.font(12))
        self.opt_ref = ctk.CTkOptionMenu(self.frame_cols, variable=self.var_ref_col, command=self.on_col_change)

        # 3.5 Sample Roles Card - assign Pristine/Bi-layer, exclude, average repeats
        roles_card = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        roles_card.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(roles_card, text="Sample Roles", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 2), padx=16, anchor="w")
        ctk.CTkLabel(roles_card,
                     text="Select columns, assign roles -> Apply.\nRepeated measurements of the same role are averaged automatically.",
                     text_color=self.text_secondary, font=_pal.font(11), wraplength=220,
                     justify="left").pack(anchor="w", padx=16)

        tree_wrap = ctk.CTkFrame(roles_card, fg_color="transparent")
        tree_wrap.pack(fill="x", padx=16, pady=(6, 4))
        self.roles_tree = ttk.Treeview(tree_wrap, columns=("col", "role"),
                                       show="headings", height=6, selectmode="extended")
        self.roles_tree.heading("col", text="Column")
        self.roles_tree.heading("role", text="Role")
        self.roles_tree.column("col", width=150)
        self.roles_tree.column("role", width=80, anchor="center")
        self.roles_tree.pack(fill="x")
        self.roles_tree.bind("<Double-1>", self._cycle_role)
        self.column_roles = {}

        rb_row = ctk.CTkFrame(roles_card, fg_color="transparent")
        rb_row.pack(fill="x", padx=16, pady=(2, 4))
        ctk.CTkButton(rb_row, text="Pristine", width=74, height=28,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      font=_pal.font(11, "bold"),
                      command=lambda: self._set_role("Pristine"), text_color=_pal.TXT).pack(side="left", padx=(0, 4))
        ctk.CTkButton(rb_row, text="Bi-layer", width=74, height=28,
                      fg_color=self.accent_blue, hover_color=_pal.ACCENT_HOV,
                      font=_pal.font(11, "bold"),
                      command=lambda: self._set_role("Bi-layer")).pack(side="left", padx=4)
        ctk.CTkButton(rb_row, text="Exclude", width=70, height=28,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      font=_pal.font(11, "bold"),
                      command=lambda: self._set_role("Exclude"), text_color=_pal.TXT).pack(side="left", padx=4)
        ctk.CTkButton(roles_card, text="Apply roles (average repeats)", height=28,
                      fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      font=_pal.font(12, "bold"),
                      command=self._apply_roles, text_color=_pal.TXT).pack(fill="x", padx=16, pady=(2, 16))

        # 4. Parameters Card (Real-time Preview)
        frame_params = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        frame_params.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(frame_params, text="Parameters (Live Preview)", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8))

        # Filter Width
        ctk.CTkLabel(frame_params, text="Filter Width (Smoothness)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(anchor="w", padx=16)
        self.sl_width = ctk.CTkSlider(frame_params, from_=0, to=101, number_of_steps=101, variable=self.var_filter_width)
        self.sl_width.pack(fill="x", padx=16, pady=2)

        # Baseline Rigidity
        ctk.CTkLabel(frame_params, text="Baseline Rigidity (Background)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(anchor="w", padx=16)
        self.sl_rigid = ctk.CTkSlider(frame_params, from_=0, to=9, number_of_steps=90, variable=self.var_rigidity)
        self.sl_rigid.pack(fill="x", padx=16, pady=2)

        # Peak Protection (Using slider for log/small scale visually)
        ctk.CTkLabel(frame_params, text="Peak Protection (Fit Sens)", text_color=self.text_secondary,
                     font=_pal.font(12)).pack(anchor="w", padx=16)
        self.sl_prot = ctk.CTkSlider(frame_params, from_=0, to=0.1, number_of_steps=100, variable=self.var_protection)
        self.sl_prot.pack(fill="x", padx=16, pady=(2, 10))

        # X axis and fit model
        ctk.CTkLabel(frame_params, text="X axis", text_color=self.text_secondary, font=_pal.font(12)).pack(anchor="w", padx=16)
        self.var_axis = ctk.StringVar(value="Wavelength (nm)")
        ctk.CTkSegmentedButton(frame_params, values=["Wavelength (nm)", "Energy (eV)"], variable=self.var_axis,
                               command=lambda _v: self.schedule_preview(), height=26, font=_pal.font(10),
                               selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT, corner_radius=_pal.R_PILL).pack(fill="x", padx=16, pady=(2, 8))
        ctk.CTkLabel(frame_params, text="Peak model", text_color=self.text_secondary, font=_pal.font(12)).pack(anchor="w", padx=16)
        self.var_model = ctk.StringVar(value="Single Gaussian")
        ctk.CTkOptionMenu(frame_params, values=["Single Gaussian", "Multi-component (AIC, up to 3)",
                                                "Multi-component Voigt (AIC, up to 3)"],
                          variable=self.var_model, height=26, font=_pal.font(10)).pack(fill="x", padx=16, pady=(2, 16))

        # 5. Actions Card
        frame_action = ctk.CTkFrame(left_content, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        frame_action.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(frame_action, text="Actions", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.btn_run = ctk.CTkButton(frame_action, text="RUN Analysis", command=self.run_analysis,
                                     fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                                     height=28, font=_pal.font(13, "bold"), state="disabled", text_color=_pal.TXT)
        self.btn_run.pack(fill="x", padx=16, pady=4)

        self.btn_export = ctk.CTkButton(frame_action, text="Save Excel", command=self.export_excel, state="disabled")
        self.btn_export.pack(fill="x", padx=16, pady=4)

        self.btn_origin = ctk.CTkButton(frame_action, text="Plot to Origin", command=self.send_to_origin,
                                        fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER, state="disabled", text_color=_pal.TXT)
        self.btn_origin.pack(fill="x", padx=16, pady=4)

        self.btn_ai = ctk.CTkButton(frame_action, text="Interpretation", command=self.run_ai_analysis,
                                    fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER, state="disabled", text_color=_pal.TXT)
        self.btn_ai.pack(fill="x", padx=16, pady=(4, 16))

        # Left resizer (drag bar)
        self.left_resizer = tk.Frame(self, width=self.resizer_width, bg=self.card_border, cursor="sb_h_double_arrow")
        self.left_resizer.grid(row=0, column=1, sticky="nsew")
        self.left_resizer.grid_propagate(False)
        self.left_resizer.bind("<Button-1>", self._on_left_resizer_press)
        self.left_resizer.bind("<B1-Motion>", self._on_left_resizer_drag)

        # === Center Plot Area ===
        self.center_panel = ctk.CTkFrame(self, corner_radius=0, fg_color=self.center_bg)
        self.center_panel.grid(row=0, column=2, sticky="nsew")
        self.center_panel.grid_rowconfigure(0, weight=1)
        self.center_panel.grid_columnconfigure(0, weight=1)

        plot_container = ctk.CTkFrame(self.center_panel, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        plot_container.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        plot_container.grid_rowconfigure(0, weight=1)
        plot_container.grid_columnconfigure(0, weight=1)

        self.fig, self.ax = plt.subplots(figsize=(6, 5), dpi=100)
        self.fig.patch.set_facecolor(self.card_bg)
        self._style_axes(self.ax)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_container)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        # JV_Analysis.exe-style conveniences: wheel zoom (Ctrl=X, Shift=Y),
        # left-drag pan, double-click auto range, right-click context menu
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas)
            _pi.enable_drag_pan(self.canvas)
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")

        # === Right Results Panel ===
        # Fixed width: the results table has ten columns and used to claim their full
        # width, which pushed the plot out of the window on a 1440-pixel screen.
        self.right_panel = ctk.CTkFrame(self, width=520, corner_radius=0, fg_color=self.panel_bg)
        self.right_panel.grid(row=0, column=3, sticky="nsew")
        self.right_panel.grid_propagate(False)
        self.right_panel.grid_rowconfigure(0, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)

        results_card = ctk.CTkFrame(self.right_panel, corner_radius=_pal.R_CARD, fg_color=self.card_bg)
        results_card.grid(row=0, column=0, sticky="nsew", padx=12, pady=(16, 8))

        ctk.CTkLabel(results_card, text="Results", font=_pal.font(12, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        tree_frame = ctk.CTkFrame(results_card, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.results_tree = ttk.Treeview(tree_frame, columns=(), show="headings", height=14)
        xs = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(xscrollcommand=xs.set)
        xs.pack(side="bottom", fill="x")
        self.results_tree.pack(fill="both", expand=True)
        self._init_results_table()

        # === Bottom Status & Guide ===
        self.bottom_panel = ctk.CTkFrame(self, height=120, fg_color=self.panel_bg)
        self.bottom_panel.grid(row=1, column=0, columnspan=4, sticky="ew", padx=0, pady=(0, 10))

        # Status Log (Left)
        self.lbl_status = ctk.CTkLabel(self.bottom_panel, text="Status: Ready", anchor="w", width=400,
                                       text_color=self.text_secondary, font=_pal.font(12))
        self.lbl_status.pack(side="left", padx=16, fill="x", expand=True)

        # Parameter Guide Card (Right)
        guide_frame = ctk.CTkFrame(self.bottom_panel, fg_color=self.card_bg, corner_radius=_pal.R_CARD)
        guide_frame.pack(side="right", padx=12, pady=8, fill="y")
        guide_text = (
            "Filter width: Savitzky-Golay smoothing (larger = smoother)\n"
            "Baseline rigidity: ALS stiffness, log10(lambda) (larger = straighter)\n"
            "Peak protection: ALS asymmetry p (smaller = peaks protected)\n"
            "Energy axis: I(E) = I(lambda) lambda^2 / hc (Jacobian applied)"
        )
        ctk.CTkLabel(guide_frame, text=guide_text, justify="left",
                     text_color=self.text_secondary, font=_pal.mono(11)).pack(padx=10, pady=5)

    def _style_axes(self, ax):
        ax.set_facecolor(self.card_bg)
        ax.tick_params(colors=_pal.PLOT_TICK, labelsize=10)
        for spine in ax.spines.values():
            spine.set_color(self.card_border)
        ax.xaxis.label.set_color(self.text_primary)
        ax.yaxis.label.set_color(self.text_primary)
        ax.title.set_color(self.text_primary)

    def _on_left_resizer_press(self, event):
        self._drag_start_x = event.x_root
        self._drag_start_left_width = self.left_width

    def _on_left_resizer_drag(self, event):
        if self._drag_start_x is None:
            return
        delta = event.x_root - self._drag_start_x
        new_width = int(self._drag_start_left_width + delta)
        new_width = max(self.min_left_width, min(self.max_left_width, new_width))
        if new_width == self.left_width:
            return
        self.left_width = new_width
        self.grid_columnconfigure(0, minsize=self.left_width)
        self.left_panel.configure(width=self.left_width)
        self.left_panel.update_idletasks()

    def _setup_bindings(self):
        # Trace slider variables for realtime preview
        self.var_filter_width.trace_add("write", self.schedule_preview)
        self.var_rigidity.trace_add("write", self.schedule_preview)
        self.var_protection.trace_add("write", self.schedule_preview)

    def _init_results_table(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Treeview",
            background=self.card_bg,
            foreground=self.text_primary,
            fieldbackground=self.card_bg,
            font=_pal.font(11),
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=_pal.BG_SUB,
            foreground=self.text_primary,
            font=_pal.font(12, "bold"),
        )

        cols = ["Sample", "Peak (nm)", "Peak (eV)", "FWHM (nm)", "FWHM (meV)", "Area", "Max Intensity",
                "Quench eta (peak)", "Quench eta (integral)", "Components"]
        self.results_tree.configure(columns=cols)
        for col in cols:
            self.results_tree.heading(col, text=col)
            self.results_tree.column(col, width=150 if col == "Sample" else 100, anchor="center", stretch=False)
        self.results_tree.insert("", "end", values=["-"] * len(cols))

    def log(self, msg):
        self.lbl_status.configure(text=f"Status: {msg}")
        print(f"[Log] {msg}")

    def on_mode_change(self, value):
        if value == "2 Layer":
            self.lbl_ref.pack(anchor="w", padx=16)
            self.opt_ref.pack(fill="x", padx=16, pady=2)
        else:
            self.lbl_ref.pack_forget()
            self.opt_ref.pack_forget()
        self.schedule_preview()
        
    def browse_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Data Files", "*.xlsx *.xls *.csv")])
        if file_path:
            self.file_path_var.set(file_path)

    def load_data(self):
        file_path = self.file_path_var.get().strip()
        if not file_path:
            file_path = filedialog.askopenfilename(filetypes=[("Data Files", "*.xlsx *.xls *.csv")])
            if not file_path:
                return
            self.file_path_var.set(file_path)
        
        try:
            self.df, filename = pl_core.load_data_preview(file_path)
            columns = list(self.df.columns)
            
            # Assuming Col 0 is Wavelength
            self.x_col = columns[0]
            
            # Set dropdown values
            data_cols = columns[1:]
            self.opt_sample.configure(values=data_cols)
            self.opt_ref.configure(values=data_cols)
            
            # Setup Listbox
            if hasattr(self, 'sample_list'): # If using listbox
                self.sample_list.delete(0, tk.END)
                for c in data_cols:
                    self.sample_list.insert(tk.END, c)
            else: # Fallback or if using option menu
                self.var_sample_col.set(data_cols[0])
                if len(data_cols) > 1:
                    self.var_ref_col.set(data_cols[1])
                else:
                    self.var_ref_col.set(data_cols[0])
                
            # Populate roles tree (reset existing roles)
            self.column_roles = {c: "-" for c in data_cols}
            for item in self.roles_tree.get_children():
                self.roles_tree.delete(item)
            for c in data_cols:
                self.roles_tree.insert("", "end", iid=c, values=(c, "-"))

            self.btn_run.configure(state="normal")
            self.btn_export.configure(state="normal")
            self.btn_origin.configure(state="normal")
            self.btn_ai.configure(state="normal")
            
            self.log(f"Loaded {filename} ({len(self.df)} rows, {len(data_cols)} data cols)")
            self.schedule_preview()
            
        except Exception as e:
            self.log(f"Error loading data: {e}")
            messagebox.showerror("Load Error", str(e))

    def on_col_change(self, _):
        self.schedule_preview()

    def _set_role(self, role):
        sel = self.roles_tree.selection()
        if not sel:
            messagebox.showinfo("Roles", "Select columns in the table first.")
            return
        for iid in sel:
            self.column_roles[iid] = role
            self.roles_tree.item(iid, values=(iid, role))

    def _cycle_role(self, _event):
        iid = self.roles_tree.focus()
        if not iid:
            return
        order = ["-", "Pristine", "Bi-layer", "Exclude"]
        cur = self.column_roles.get(iid, "-")
        nxt = order[(order.index(cur) + 1) % len(order)]
        self.column_roles[iid] = nxt
        self.roles_tree.item(iid, values=(iid, nxt))

    @staticmethod
    def _repeat_base(name):
        """Base name with repeat-measurement suffix (_1, -02, (3), .1, space+number) removed."""
        return re.sub(r"[\s_\-\.]*\(?\d+\)?$", "", str(name)).strip() or str(name)

    def _apply_roles(self):
        """Average columns per role to create Pristine(avg)/Bi-layer(avg) columns, then
        wire them into the existing pipeline (ref=Pristine, sample=Bi-layer).
        Physics: steady-state PL quenching efficiency eta = 1 - I_bi/I_pristine."""
        if self.df is None:
            messagebox.showwarning("Roles", "Load data first.")
            return
        pris = [c for c, r in self.column_roles.items() if r == "Pristine"]
        bil  = [c for c, r in self.column_roles.items() if r == "Bi-layer"]
        if not pris:
            messagebox.showwarning("Roles", "Assign at least one column to the Pristine role.")
            return

        def log_groups(cols, label):
            groups = {}
            for c in cols:
                groups.setdefault(self._repeat_base(c), []).append(c)
            for base, cs in groups.items():
                if len(cs) > 1:
                    self.log(f"[{label}] averaged {len(cs)} repeats: {base} ({', '.join(cs)})")

        log_groups(pris, "Pristine")
        p_name = f"Pristine (avg n={len(pris)})"
        self.df[p_name] = self.df[pris].mean(axis=1)
        new_cols = [p_name]

        b_name = None
        if bil:
            log_groups(bil, "Bi-layer")
            b_name = f"Bi-layer (avg n={len(bil)})"
            self.df[b_name] = self.df[bil].mean(axis=1)
            new_cols.append(b_name)

        # Refresh option menus (remove excluded columns from the list)
        excl = {c for c, r in self.column_roles.items() if r == "Exclude"}
        base_cols = [c for c in self.df.columns[1:] if c not in excl]
        self.opt_sample.configure(values=base_cols)
        self.opt_ref.configure(values=base_cols)

        if b_name:
            self.var_ref_col.set(p_name)     # reference (denominator of quenching) = Pristine
            self.var_sample_col.set(b_name)  # sample = Bi-layer
            self.seg_layer.set("2 Layer")
            self.on_mode_change("2 Layer")
            self.log(f"Roles applied: ref={p_name}, sample={b_name} -> RUN Analysis to compute quenching efficiency (eta)")
        else:
            self.var_sample_col.set(p_name)
            self.seg_layer.set("1 Layer")
            self.on_mode_change("1 Layer")
            self.log(f"Roles applied: sample={p_name} (Pristine-only analysis)")
        self.schedule_preview()

    def get_selected_samples(self):
        # If using OptionMenu (single select)
        return [self.var_sample_col.get()]

    def schedule_preview(self, *args):
        # Debounce the slider updates
        if self.preview_timer:
            self.after_cancel(self.preview_timer)
        self.preview_timer = self.after(100, self.update_preview_graph)

    def update_preview_graph(self):
        if self.df is None: return
        
        try:
            # Get current parameters
            fw = self.var_filter_width.get()
            rig = self.var_rigidity.get()
            prot = self.var_protection.get()
            
            x = self.df[self.x_col].values
            y_raw = self.df[self.var_sample_col.get()].values

            # Plot
            self.ax.clear()
            self._style_axes(self.ax)
            
            # 1. Plot Reference (Dashed)
            energy_axis = getattr(self, "var_axis", None) is not None and self.var_axis.get().startswith("Energy")

            def _xy(xx, yy):
                return pl_core.to_energy_axis(xx, yy) if energy_axis else (xx, yy)

            ref_col = self.var_ref_col.get()
            if ref_col:
                y_ref = self.df[ref_col].values
                _, _, y_ref_c = pl_core.process_spectrum(x, y_ref, fw, rig, prot)
                self.ax.plot(*_xy(x, y_ref_c), color=_pal.PINK, linestyle="--", label=f"{ref_col} (Ref)", linewidth=1.6)
            
            # 2. Plot Selected Sample (Solid) - Currently single select via OptionMenu
            # If you want multi-select, need to change UI to Listbox
            samp_col = self.var_sample_col.get()
            if samp_col and samp_col != ref_col:
                y_samp = self.df[samp_col].values
                _, _, y_samp_c = pl_core.process_spectrum(x, y_samp, fw, rig, prot)
                self.ax.plot(*_xy(x, y_samp_c), color=_pal.ACCENT, label=samp_col, linewidth=1.6)

            self.ax.legend(facecolor=self.card_bg, labelcolor=self.text_primary, fontsize=10, edgecolor=self.card_border)
            self.ax.set_xlabel("Energy (eV)" if energy_axis else "Wavelength (nm)", fontsize=11)
            self.ax.set_ylabel("Intensity per eV (a.u.)" if energy_axis else "Intensity (a.u.)", fontsize=11)
            self.ax.grid(True, color=self.card_border)
            
            self.canvas.draw()
            
        except Exception as e:
            print(f"Preview Error: {e}")

    def run_analysis(self):
        if self.df is None:
            return

        self.log("Running analysis...")
        
        fw = self.var_filter_width.get()
        rig = self.var_rigidity.get()
        prot = self.var_protection.get()
        
        x = self.df[self.x_col].values
        ref_col = self.var_ref_col.get()
        
        # 1. Process Reference
        y_ref_raw = self.df[ref_col].values
        _, _, y_ref = pl_core.process_spectrum(x, y_ref_raw, fw, rig, prot)
        self.processed_data = {ref_col: y_ref}
        
        # 2. Analyze All Columns (except X)
        results = []
        analyze_list = [c for c in self.df.columns if c != self.x_col]
        
        model = self.var_model.get()
        energy_axis = self.var_axis.get().startswith("Energy")
        self.fit_curves = {}
        samp_col = self.var_sample_col.get()
        for col in analyze_list:
            y_raw = self.df[col].values
            _, _, y_proc = pl_core.process_spectrum(x, y_raw, fw, rig, prot)
            self.processed_data[col] = y_proc

            # --- wavelength-domain fit (nm) and energy-domain fit (eV, Jacobian) ---
            n_comp = 1
            if model.startswith("Single"):
                fit_res = pl_core.fit_peak_gaussian(x, y_proc)
                peak_nm, fwhm_nm = fit_res["center"], fit_res["fwhm"]
                comps_nm = [fit_res["y_fit"]] if fit_res["success"] else []
            else:
                shape = "voigt" if "Voigt" in model else "gaussian"
                try:
                    mres = pl_core.fit_multi_peak(x, y_proc, max_peaks=3, shape=shape)
                    main = max(mres.peaks, key=lambda pk: pk.height) if mres.peaks else None
                    peak_nm = main.center if main else float("nan")
                    fwhm_nm = main.fwhm if main else float("nan")
                    comps_nm = list(mres.components) if mres.success else []
                    n_comp = len(mres.peaks)
                except Exception as ex:
                    self.log(f"Multi-component fit failed for {col}: {ex}")
                    peak_nm = fwhm_nm = float("nan")
                    comps_nm = []
            try:
                e_axis, y_e = pl_core.to_energy_axis(x, y_proc)
                fe = pl_core.fit_peak_gaussian(e_axis, y_e)
                peak_ev, fwhm_mev = fe["center"], 1000.0 * fe["fwhm"]
            except Exception:
                peak_ev = fwhm_mev = float("nan")
            metrics = pl_core.peak_metrics(x, y_proc)
            self.fit_curves[col] = comps_nm

            # Quenching efficiency: report BOTH peak-based and integral-based.
            #   peak:     eta = 1 - I_sample_max / I_ref_max
            #   integral: eta = 1 - (integral PL_sample) / (integral PL_ref)
            if col == ref_col:
                eta_peak = 0.0
                eta_int = 0.0
                i_max = np.max(y_proc)
            else:
                eta_peak, i_s, i_r = pl_core.calculate_quenching_efficiency(y_proc, y_ref)
                eta_int, _, _ = pl_core.calculate_quenching_efficiency_integral(x, y_proc, y_ref)
                i_max = i_s

            results.append({
                "Sample": col,
                "Peak (nm)": f"{peak_nm:.1f}",
                "Peak (eV)": f"{peak_ev:.4f}",
                "FWHM (nm)": f"{fwhm_nm:.2f}",
                "FWHM (meV)": f"{fwhm_mev:.1f}",
                "Area": f"{metrics['area']:.4g}",
                "Max Intensity": f"{i_max:.0f}",
                "Quench eta (peak)": f"{eta_peak*100:.1f}%",
                "Quench eta (integral)": f"{eta_int*100:.1f}%",
                "Components": str(n_comp),
            })

        # redraw: processed spectra of the selected sample/reference with fit components
        self.ax.clear()
        self._style_axes(self.ax)
        for col, color, style in ((ref_col, _pal.PINK, "--"), (samp_col, _pal.ACCENT, "-")):
            if not col or col not in self.processed_data or (col == ref_col and samp_col == ref_col and style == "--"):
                continue
            yp = self.processed_data[col]
            if energy_axis:
                xe, ye = pl_core.to_energy_axis(x, yp)
                self.ax.plot(xe, ye, color=color, linestyle=style, label=col, linewidth=1.6)
                for comp in self.fit_curves.get(col, []):
                    xe2, ce = pl_core.to_energy_axis(x, comp)
                    self.ax.plot(xe2, ce, ":", color=_pal.RED, linewidth=1.1)
            else:
                self.ax.plot(x, yp, color=color, linestyle=style, label=col, linewidth=1.6)
                for comp in self.fit_curves.get(col, []):
                    self.ax.plot(x, comp, ":", color=_pal.RED, linewidth=1.1)
        self.ax.legend(facecolor=self.card_bg, labelcolor=self.text_primary, edgecolor=self.card_border)
        self.ax.set_title("Processed spectra and fit components (dotted)", color=self.text_primary, fontsize=11)
        self.ax.set_xlabel("Energy (eV)" if energy_axis else "Wavelength (nm)", color=self.text_primary, fontsize=11)
        self.ax.set_ylabel("Intensity (a.u.)" if not energy_axis else "Intensity per eV (a.u.)", color=self.text_primary, fontsize=11)
        self.ax.grid(True, color=self.card_border)
        self.canvas.draw()
            
        self.last_results_df = pd.DataFrame(results)
        self.show_results_table(self.last_results_df)
        
        self.btn_export.configure(state="normal")
        self.btn_origin.configure(state="normal")
        self.btn_ai.configure(state="normal")

    def show_results_table(self, df):
        # Configure Treeview style (match JV tone)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Treeview",
            background=self.card_bg,
            foreground=self.text_primary,
            fieldbackground=self.card_bg,
            font=_pal.font(11),
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=_pal.BG_SUB,
            foreground=self.text_primary,
            font=_pal.font(12, "bold"),
        )

        # Rebuild columns
        cols = list(df.columns)
        self.results_tree.configure(columns=cols)
        for col in cols:
            self.results_tree.heading(col, text=col)
            self.results_tree.column(col, width=150 if col == "Sample" else 100, anchor="center", stretch=False)

        # Clear and insert rows
        for row_id in self.results_tree.get_children():
            self.results_tree.delete(row_id)
        for _, row in df.iterrows():
            self.results_tree.insert("", "end", values=list(row))

    def _build_processed_data(self):
        if self.df is None:
            return None, None
        fw = self.var_filter_width.get()
        rig = self.var_rigidity.get()
        prot = self.var_protection.get()

        x = self.df[self.x_col].values
        processed = {}
        for col in self.df.columns:
            if col == self.x_col:
                continue
            y_raw = self.df[col].values
            _, _, y_proc = pl_core.process_spectrum(x, y_raw, fw, rig, prot)
            processed[col] = y_proc
        return processed, x

    def send_to_origin(self):
        if self.df is None:
            messagebox.showwarning("Warning", "Load data first.", parent=self)
            return

        if not self.processed_data:
            processed, x = self._build_processed_data()
            if not processed:
                messagebox.showwarning("Warning", "No data to plot.", parent=self)
                return
            self.processed_data = processed
        else:
            x = self.df[self.x_col].values

        if not self.processed_data:
            messagebox.showwarning("Warning", "No data to plot.", parent=self)
            return
            
        # ??FIX: Log Callback Passed Correctly
        self.log("Connecting to Origin...")
        origin = pl_core.connect_to_origin(self.origin_path, log_callback=self.log)
        
        if not origin:
            messagebox.showerror("Error", "Could not connect to Origin.\nCheck path or install pywin32.", parent=self)
            return
            
        pl_core.plot_all_pl_to_origin(origin, x, self.processed_data, title="PL_Analysis")
        messagebox.showinfo("Success", "Plots sent to Origin!", parent=self)

    def run_ai_analysis(self):
        if not self.api_key:
            messagebox.showerror("Error", "API Key Missing", parent=self)
            return
        
        AIConfigDialog(self, self.api_key, self.start_ai_thread)

    def start_ai_thread(self, model_name, context):
        # Gather data in main thread
        last_results_df = self.last_results_df
        self.btn_ai.configure(text="Analyzing...", state="disabled")
        threading.Thread(target=self._ai_thread, args=(model_name, context, self.api_key, last_results_df), daemon=True).start()

    def _ai_thread(self, model_name, context, api_key, last_results_df):
        try:
            if last_results_df is None: return
            summary = last_results_df.to_string()
            response = pl_core.analyze_pl_with_gemini(api_key, model_name, context, summary)
            self.ai_result_text = response
            self.after(0, lambda: self.show_result_popup(response, "Interpretation result"))
        finally:
            self.after(0, lambda: self.btn_ai.configure(state="normal"))

    def show_result_popup(self, text, title):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("700x600")
        top.attributes("-topmost", True)
        txt = ctk.CTkTextbox(top, font=_pal.font(12))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", text)

    def open_compare(self):
        """Several PL files side by side (peak, FWHM in nm and meV, integrated intensity)."""
        from scripts.common.compare_window import CompareWindow
        CompareWindow(self, "pl", options={"filter_width": float(self.var_filter_width.get()),
                                           "rigidity": float(self.var_rigidity.get()),
                                           "protection": float(self.var_protection.get())})

    def export_report(self):
        if self.last_results_df is None:
            messagebox.showwarning("Report", "Run the analysis first.", parent=self)
            return
        path = _report.ask_report_path(self, "PL_report.md")
        if not path:
            return
        notes = ("Smoothing: Savitzky-Golay; baseline: asymmetric least squares (Eilers & Boelens 2005). "
                 f"Peak model: {self.var_model.get()}. Energy-domain values use I(E) = I(lambda) lambda^2/hc "
                 "(Jacobian) before fitting. Quenching eta = 1 - I_sample/I_reference (peak height and integrated area).")
        try:
            _report.write_markdown_report(path, "PL analysis", [("Results", self.last_results_df)], figure=self.fig,
                                          inputs=[self.file_path_var.get()] if self.file_path_var.get() else None, notes=notes)
            self.log(f"Report saved: {path}")
        except Exception as ex:
            messagebox.showerror("Report", str(ex), parent=self)

    def export_excel(self):
        if self.last_results_df is None:
            messagebox.showwarning("Warning", "No results.", parent=self)
            return
        
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            try:
                with pd.ExcelWriter(path) as writer:
                    self.last_results_df.to_excel(writer, sheet_name="PL_Results", index=False)
                    # Processed spectra (optional second sheet)
                    if self.processed_data:
                        try:
                            proc = pd.DataFrame({self.x_col: self.df[self.x_col].values})
                            for col, y in self.processed_data.items():
                                proc[col] = y
                            proc.to_excel(writer, sheet_name="Processed", index=False)
                        except Exception:
                            pass
                from scripts.common.provenance import write_sidecar
                write_sidecar(path, "PL", inputs=[self.file_path_var.get()],
                              parameters={"filter_width": float(self.var_filter_width.get()),
                                          "rigidity_log10_lambda": float(self.var_rigidity.get()),
                                          "protection_p": float(self.var_protection.get()),
                                          "model": self.var_model.get(), "axis": self.var_axis.get(),
                                          "reference_column": self.var_ref_col.get()},
                              results={"table": self.last_results_df})
                messagebox.showinfo("Saved", f"Saved to {path}", parent=self)
                self.log(f"Excel saved: {path}")
            except Exception as e:
                messagebox.showerror("Save Error", str(e), parent=self)


AnalysisWindow = PLAnalysisWindow


def main():
    root = ctk.CTk()
    root.withdraw()
    PLAnalysisWindow(root, "", "")
    root.mainloop()


if __name__ == "__main__":
    main()
