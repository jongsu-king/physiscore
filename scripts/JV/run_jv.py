# run_jv.py - J-V Curve Analysis GUI (UI Only)
import os
import sys
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd
import customtkinter as ctk

# Matplotlib for embedded plots
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import core logic
try:
    from .jv_core import (
        JVSettings,
        process_jv_directory,
        save_to_excel,
        save_selected_to_transit_excel,
        create_iv_plot,
        create_box_plot,
        create_single_iv_plot,
        create_multi_iv_plot,
        connect_to_origin,
        plot_iv_to_origin,
        plot_box_to_origin,
    )
except ImportError:
    from jv_core import (
        JVSettings,
        process_jv_directory,
        save_to_excel,
        save_selected_to_transit_excel,
        create_iv_plot,
        create_box_plot,
        create_single_iv_plot,
        create_multi_iv_plot,
        connect_to_origin,
        plot_iv_to_origin,
        plot_box_to_origin,
    )

# AI Assistant Integration
AI_AVAILABLE = False
MODEL_OPTIONS = ["gemini-2.0-flash"]
JVAIIntegration = None
AIWindow = None

try:
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        from .jv_ai_assistant import JVAIIntegration
        from .jv_ai_panel import AIWindow, MODEL_OPTIONS
        from .jv_ai_panel import AIWindow, MODEL_OPTIONS as _OPTS
        MODEL_OPTIONS = _OPTS
        AI_AVAILABLE = True
except (ImportError, Exception):
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            from jv_ai_assistant import JVAIIntegration
            from jv_ai_panel import AIWindow, MODEL_OPTIONS
            from jv_ai_panel import AIWindow, MODEL_OPTIONS as _OPTS
            MODEL_OPTIONS = _OPTS
            AI_AVAILABLE = True
    except (ImportError, Exception) as e:
        AI_AVAILABLE = False
        JVAIIntegration = None
        AIWindow = None
        MODEL_OPTIONS = ["gemini-2.0-flash"]
        print(f"AI features not available: {e}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "jv_config.json")
AI_CONFIG_FILE = os.path.join(BASE_DIR, "jv_ai_config.json")
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None



# =========================
# AI Result Dialog (copyable result window)
# =========================
class AIResultDialog(ctk.CTkToplevel):
    """Dialog showing AI analysis result as copyable text"""

    def __init__(self, parent, title: str, content: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x500")
        self.resizable(True, True)

        # Dark theme colors
        self.card_bg = "#1E1E1E"

        # Center on parent
        self.transient(parent)

        self._create_widgets(content)

        # Bring to front
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))
        self.focus()

    def _create_widgets(self, content: str):
        # Main frame
        main_frame = ctk.CTkFrame(self, fg_color=self.card_bg, corner_radius=0)
        main_frame.pack(fill="both", expand=True)

        # Header
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(
            header_frame,
            text="AI Analysis Result",
            font=("Segoe UI", 18, "bold"),
            text_color="#FFFFFF"
        ).pack(side="left")

        # Copy button
        self.btn_copy = ctk.CTkButton(
            header_frame,
            text="Copy All",
            width=80,
            height=32,
            fg_color="#3182F6",
            hover_color="#2563EB",
            command=self._copy_content
        )
        self.btn_copy.pack(side="right")

        # Text display (scrollable, selectable)
        self.text_display = ctk.CTkTextbox(
            main_frame,
            font=("Consolas", 12),
            fg_color="#252525",
            text_color="#DDDDDD",
            corner_radius=8,
            wrap="word"
        )
        self.text_display.pack(fill="both", expand=True, padx=16, pady=(8, 8))

        # Insert content
        self.text_display.insert("1.0", content)

        # Bottom buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))

        self.lbl_status = ctk.CTkLabel(
            btn_frame,
            text="",
            text_color="#8B8B8B",
            font=("Segoe UI", 11)
        )
        self.lbl_status.pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="Close",
            width=80,
            height=32,
            fg_color="#3D3D3D",
            hover_color="#666666",
            command=self.destroy
        ).pack(side="right")

    def _copy_content(self):
        """Copy all text"""
        content = self.text_display.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.lbl_status.configure(text="Copied to clipboard!", text_color="#10B981")
        self.after(2000, lambda: self.lbl_status.configure(text=""))


# =========================
# Main GUI
# =========================
class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("J-V Curve Analysis")
        self.geometry("1400x900")

        # Data from main window
        self.passed_origin_path = origin_path
        self.passed_api_key = api_key

        # AI Integration
        self._ai_window = None
        if AI_AVAILABLE and JVAIIntegration is not None:
            try:
                self.ai_model_name = "gemini-2.0-flash"
                self.ai_integration = JVAIIntegration(db_path=os.path.join(BASE_DIR, "jv_ai_history.db"))
                # API key priority: passed key > config file
                ai_config = self._load_ai_config()
                effective_api_key = api_key or ai_config.get("api_key", "")
                effective_model = ai_config.get("model_name", "")
                if effective_api_key:
                    if effective_model:
                        self.ai_model_name = effective_model
                    self.ai_integration.initialize(effective_api_key, model_name=effective_model)
                    self.passed_api_key = effective_api_key
            except Exception as e:
                print(f"AI initialization failed: {e}")
                self.ai_integration = None
        else:
            self.ai_integration = None

        # Settings
        self.settings = JVSettings()

        # Variables
        self.directory_path = tk.StringVar()
        self.x_min = tk.DoubleVar(value=self.settings.x_min)
        self.x_max = tk.DoubleVar(value=self.settings.x_max)
        self.y_min = tk.DoubleVar(value=self.settings.y_min)
        self.y_max = tk.DoubleVar(value=self.settings.y_max)

        # Processed data
        self.processed_data = None
        self.extra_dirs = []  # '+ Add' folder-comparison (JV_Analysis.exe)
        self.excel_file_path = None
        self.selected_sample = None  # Currently selected sample name
        self.selected_samples = []  # Multiple selected samples
        self.center_plot_mode = "JV"  # "JV" or "Box"
        self._ai_status_prev = None

        # Grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.load_config()
        self.create_left_panel()
        self.create_center_panel()
        self.create_right_panel()

        # Bind axis entry changes to update plot
        self.x_min.trace_add("write", self._on_axis_change)
        self.x_max.trace_add("write", self._on_axis_change)
        self.y_min.trace_add("write", self._on_axis_change)
        self.y_max.trace_add("write", self._on_axis_change)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Bring to front
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "J-V Curve Analysis", {
                    "open": [("📁 Open", self.browse_folder),
                             ("＋ Add", self.add_folder),
                             ("🕘 Recent", self.open_recent_menu)],
                    "run": ("▶ Process", self.start_processing),
                    "excel": ("Excel", self.open_excel),
                    "png": True,
                    "origin": [("Origin J-V", self.send_iv_to_origin), ("Origin Box", self.send_box_to_origin)],
                    "ai": ("🤖 AI", self._open_ai_window)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

    # =====================
    # Config I/O
    # =====================
    def _load_ai_config(self):
        """Load AI API key from config file"""
        if os.path.exists(AI_CONFIG_FILE):
            try:
                with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if isinstance(config, dict):
                        return config
            except Exception as e:
                print(f"AI config load error: {e}")
        return {}

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.x_min.set(config.get('x_min', -0.2))
                    self.x_max.set(config.get('x_max', 1.0))
                    self.y_min.set(config.get('y_min', -25.0))
                    self.y_max.set(config.get('y_max', 5.0))
            except Exception as e:
                print(f"Config load error: {e}")

    def save_config(self):
        # merge-preserve so keys like 'recent_dirs' survive
        config = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
        except Exception:
            config = {}
        config.update({
            'x_min': self.x_min.get(),
            'x_max': self.x_max.get(),
            'y_min': self.y_min.get(),
            'y_max': self.y_max.get(),
        })
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Config save error: {e}")

    def on_closing(self):
        self.save_config()
        self.destroy()

    def _on_axis_change(self, *_args):
        """Called when axis values change - update plot"""
        if self.processed_data:
            self._update_plot()

    # =====================
    # UI Creation
    # =====================
    def create_left_panel(self):
        # Toss style colors
        self.card_bg = "#1E1E1E"
        self.card_border = "#2D2D2D"
        self.accent_blue = "#3182F6"
        self.accent_orange = "#F59E0B"
        self.accent_green = "#10B981"
        self.accent_purple = "#8B5CF6"
        self.accent_pink = "#EC4899"
        self.accent_red = "#EF4444"
        self.text_primary = "#FFFFFF"
        self.text_secondary = "#8B8B8B"

        self.left_frame = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color="#141414")
        self.left_frame.grid(row=0, column=0, sticky="nsew")

        # 1. Load Data Card
        load_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        load_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(load_card, text="Load Data", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        folder_frame = ctk.CTkFrame(load_card, fg_color="transparent")
        folder_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_folder = ctk.CTkEntry(folder_frame, textvariable=self.directory_path,
                                          placeholder_text="Select folder...", height=36)
        self.entry_folder.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(folder_frame, text="...", width=40, height=36,
                      command=self.browse_folder, corner_radius=8).pack(side="right")

        self.btn_process = ctk.CTkButton(load_card, text="Process Data", command=self.start_processing,
                                          corner_radius=12, height=42, fg_color=self.accent_blue,
                                          hover_color="#2563EB", font=("Segoe UI", 14))
        self.btn_process.pack(pady=(0, 16), padx=16, fill="x")

        # 2. Axis Settings Card
        axis_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        axis_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(axis_card, text="Axis Settings", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 12), padx=16, anchor="w")

        # X Axis
        x_frame = ctk.CTkFrame(axis_card, fg_color="transparent")
        x_frame.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(x_frame, text="X:", text_color=self.text_secondary,
                     font=("Segoe UI", 13), width=30).pack(side="left")
        ctk.CTkEntry(x_frame, textvariable=self.x_min, width=70, height=32, font=("Segoe UI", 12)).pack(side="left", padx=4)
        ctk.CTkLabel(x_frame, text="~", text_color=self.text_secondary, font=("Segoe UI", 13)).pack(side="left")
        ctk.CTkEntry(x_frame, textvariable=self.x_max, width=70, height=32, font=("Segoe UI", 12)).pack(side="left", padx=4)
        ctk.CTkLabel(x_frame, text="V", text_color=self.text_secondary, font=("Segoe UI", 13)).pack(side="left")

        # Y Axis
        y_frame = ctk.CTkFrame(axis_card, fg_color="transparent")
        y_frame.pack(fill="x", padx=16, pady=(4, 16))
        ctk.CTkLabel(y_frame, text="Y:", text_color=self.text_secondary,
                     font=("Segoe UI", 13), width=30).pack(side="left")
        ctk.CTkEntry(y_frame, textvariable=self.y_min, width=70, height=32, font=("Segoe UI", 12)).pack(side="left", padx=4)
        ctk.CTkLabel(y_frame, text="~", text_color=self.text_secondary, font=("Segoe UI", 13)).pack(side="left")
        ctk.CTkEntry(y_frame, textvariable=self.y_max, width=70, height=32, font=("Segoe UI", 12)).pack(side="left", padx=4)
        ctk.CTkLabel(y_frame, text="mA/cm²", text_color=self.text_secondary, font=("Segoe UI", 13)).pack(side="left")

        # 3. Actions Card
        actions_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        actions_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(actions_card, text="Actions", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        btn_frame = ctk.CTkFrame(actions_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.btn_open_excel = ctk.CTkButton(btn_frame, text="Open Excel", command=self.open_excel,
                                             fg_color="#252525", hover_color="#303030",
                                             corner_radius=10, height=40, font=("Segoe UI", 13),
                                             state="disabled")
        self.btn_open_excel.pack(fill="x", pady=3)

        self.btn_origin_iv = ctk.CTkButton(btn_frame, text="Send J-V to Origin", command=self.send_iv_to_origin,
                                            fg_color="#252525", hover_color="#303030",
                                            corner_radius=10, height=40, font=("Segoe UI", 13),
                                            state="disabled")
        self.btn_origin_iv.pack(fill="x", pady=3)

        self.btn_origin_box = ctk.CTkButton(btn_frame, text="Send Box to Origin", command=self.send_box_to_origin,
                                             fg_color="#252525", hover_color="#303030",
                                             corner_radius=10, height=40, font=("Segoe UI", 13),
                                             state="disabled")
        self.btn_origin_box.pack(fill="x", pady=3)

        # 4. AI Assistant Card
        if AI_AVAILABLE:
            ai_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
            ai_card.pack(pady=8, padx=12, fill="x")

            ctk.CTkLabel(ai_card, text="AI Assistant", font=("Segoe UI", 16, "bold"),
                         text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

            # Model Selection
            model_frame = ctk.CTkFrame(ai_card, fg_color="transparent")
            model_frame.pack(fill="x", padx=16, pady=(0, 8))
            
            ctk.CTkLabel(model_frame, text="Model:", font=("Segoe UI", 12), 
                         text_color=self.text_secondary).pack(side="left", padx=(0, 5))
            
            self.combo_ai_model = ctk.CTkComboBox(model_frame, values=MODEL_OPTIONS, 
                                                  command=self._on_ai_model_change, height=24)
            self.combo_ai_model.set(self.ai_model_name)
            self.combo_ai_model.pack(side="left", fill="x", expand=True)

            ai_btn_frame = ctk.CTkFrame(ai_card, fg_color="transparent")
            ai_btn_frame.pack(fill="x", padx=12, pady=(0, 12))

            self.btn_quick_ai = ctk.CTkButton(ai_btn_frame, text="Quick Analysis",
                                               command=self._run_quick_ai_analysis,
                                               fg_color="#252525", hover_color="#303030",
                                               corner_radius=10, height=36, font=("Segoe UI", 12),
                                               state="disabled")
            self.btn_quick_ai.pack(fill="x", pady=3)

            self.btn_ai_panel = ctk.CTkButton(ai_btn_frame, text="Open AI Assistant",
                                               command=self._open_ai_window,
                                               fg_color="#252525", hover_color="#303030",
                                               corner_radius=10, height=36, font=("Segoe UI", 12))
            self.btn_ai_panel.pack(fill="x", pady=3)

            # AI Status
            self.lbl_ai_status = ctk.CTkLabel(ai_card, text="", text_color=self.text_secondary,
                                               font=("Segoe UI", 11))
            self.lbl_ai_status.pack(pady=(0, 12))
            self._update_ai_status()

        # 6. Status Card
        status_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        status_card.pack(pady=8, padx=12, fill="x")

        ctk.CTkLabel(status_card, text="Status", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.progress_bar = ctk.CTkProgressBar(status_card, height=6, corner_radius=3,
                                                progress_color=self.accent_green)
        self.progress_bar.set(0)
        self.progress_bar.pack(padx=16, fill="x")

        self.lbl_status = ctk.CTkLabel(status_card, text="Ready", text_color=self.text_secondary,
                                        font=("Segoe UI", 12))
        self.lbl_status.pack(pady=(8, 16))

        # Spacer
        spacer = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        # 7. Plot Selection Card (bottom)
        plot_card = ctk.CTkFrame(self.left_frame, corner_radius=16, fg_color=self.card_bg)
        plot_card.pack(pady=(8, 16), padx=12, fill="x")

        ctk.CTkLabel(plot_card, text="Preview", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.plot_selector = ctk.CTkSegmentedButton(
            plot_card,
            values=["J-V", "Voc", "Jsc", "FF", "PCE"],
            command=self.on_plot_select,
            font=("Segoe UI", 12)
        )
        self.plot_selector.set("J-V")
        self.plot_selector.pack(padx=16, pady=(0, 16), fill="x")

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0A0A0A")
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(1, weight=1)
        self.center_frame.grid_columnconfigure(0, weight=1)

        # Toggle button for JV/Box plot
        toggle_frame = ctk.CTkFrame(self.center_frame, fg_color="transparent")
        toggle_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))

        self.plot_toggle_btn = ctk.CTkSegmentedButton(
            toggle_frame,
            values=["J-V Curve", "Box Plot"],
            command=self._on_center_plot_toggle,
            font=("Segoe UI", 13),
            width=220
        )
        self.plot_toggle_btn.set("J-V Curve")
        self.plot_toggle_btn.pack(anchor="center")

        # Plot container
        plot_container = ctk.CTkFrame(self.center_frame, corner_radius=12, fg_color="#1E1E1E")
        plot_container.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        plot_container.grid_rowconfigure(0, weight=1)
        plot_container.grid_columnconfigure(0, weight=1)

        # Matplotlib figure
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor='#1E1E1E')
        self.ax = self.fig.add_subplot(111)
        self._style_axes(self.ax)

        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=plot_container)
        self.canvas_plot.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        # JV_Analysis.exe-style conveniences: wheel zoom (Ctrl=X, Shift=Y),
        # left-drag pan, double-click auto range, right-click context menu
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas_plot)
            _pi.enable_drag_pan(self.canvas_plot)
            _pi.add_canvas_context_menu(self, self.canvas_plot, self.fig)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")

        # Initial empty state
        self.ax.text(0.5, 0.5, "Load data to preview plot",
                     ha='center', va='center', fontsize=14, color='#3D3D3D',
                     transform=self.ax.transAxes)
        self.canvas_plot.draw()

    def _on_center_plot_toggle(self, value):
        """Handle center plot toggle between JV and Box plot - sync with Preview"""
        self.center_plot_mode = "JV" if value == "J-V Curve" else "Box"

        # Sync Preview segmented button
        if self.center_plot_mode == "JV":
            self.plot_selector.set("J-V")
        else:
            # Set Preview to match current selected_box_param
            param_to_preview = {
                "Voc V": "Voc",
                "Jsc mA/cm2": "Jsc",
                "Fill Factor": "FF",
                "PCE (%)": "PCE"
            }
            if self.selected_box_param in param_to_preview:
                self.plot_selector.set(param_to_preview[self.selected_box_param])

        self._update_plot()

    def _style_axes(self, ax):
        """Apply dark theme styling to axes."""
        ax.set_facecolor('#1E1E1E')
        ax.tick_params(colors='#AAAAAA', labelsize=10)
        for spine in ax.spines.values():
            spine.set_color('#2D2D2D')
        ax.xaxis.label.set_color('#FFFFFF')
        ax.yaxis.label.set_color('#FFFFFF')
        ax.title.set_color('#FFFFFF')

    def create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, width=320, corner_radius=0, fg_color="#141414")
        self.right_frame.grid(row=0, column=2, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)

        # Currently selected box plot parameter
        self.selected_box_param = "PCE (%)"

        # Statistics Card
        stats_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        stats_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        # Statistics header with sample name
        stats_header = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(stats_header, text="Statistics", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(side="left")

        self.lbl_selected_sample = ctk.CTkLabel(stats_header, text="", font=("Segoe UI", 12),
                                                 text_color=self.accent_blue)
        self.lbl_selected_sample.pack(side="right")

        stats_grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_grid.pack(fill="x", padx=16, pady=(0, 16))

        # Row 1: Voc & Jsc (as buttons for box plot selection)
        row1 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row1.pack(fill="x", pady=4)

        # Voc button - green color (swapped with PCE)
        self.btn_voc = ctk.CTkButton(row1, text="", corner_radius=10, fg_color="#252525",
                                      hover_color="#303030", command=lambda: self._select_box_param("Voc V"),
                                      height=75, width=140)
        self.btn_voc.pack(side="left", expand=True, fill="x", padx=(0, 4))
        # Voc inner content
        voc_inner = ctk.CTkFrame(self.btn_voc, fg_color="transparent")
        voc_inner.place(relx=0.5, rely=0.5, anchor="center")
        voc_label = ctk.CTkLabel(voc_inner, text="Voc", text_color=self.text_secondary,
                     font=("Segoe UI", 12))
        voc_label.pack()
        self.lbl_stats_voc = ctk.CTkLabel(voc_inner, text="- V", font=("Segoe UI", 16, "bold"),
                                           text_color=self.accent_green)
        self.lbl_stats_voc.pack()
        # Bind click events to inner widgets
        for widget in [voc_inner, voc_label, self.lbl_stats_voc]:
            widget.bind("<Button-1>", lambda e: self._select_box_param("Voc V"))

        # Jsc button
        self.btn_jsc = ctk.CTkButton(row1, text="", corner_radius=10, fg_color="#252525",
                                      hover_color="#303030", command=lambda: self._select_box_param("Jsc mA/cm2"),
                                      height=75, width=140)
        self.btn_jsc.pack(side="right", expand=True, fill="x", padx=(4, 0))
        # Jsc inner content
        jsc_inner = ctk.CTkFrame(self.btn_jsc, fg_color="transparent")
        jsc_inner.place(relx=0.5, rely=0.5, anchor="center")
        jsc_label = ctk.CTkLabel(jsc_inner, text="Jsc", text_color=self.text_secondary,
                     font=("Segoe UI", 12))
        jsc_label.pack()
        self.lbl_stats_jsc = ctk.CTkLabel(jsc_inner, text="- mA/cm²", font=("Segoe UI", 16, "bold"),
                                           text_color=self.accent_blue)
        self.lbl_stats_jsc.pack()
        # Bind click events to inner widgets
        for widget in [jsc_inner, jsc_label, self.lbl_stats_jsc]:
            widget.bind("<Button-1>", lambda e: self._select_box_param("Jsc mA/cm2"))

        # Row 2: FF & PCE (as buttons for box plot selection)
        row2 = ctk.CTkFrame(stats_grid, fg_color="transparent")
        row2.pack(fill="x", pady=4)

        # FF button
        self.btn_ff = ctk.CTkButton(row2, text="", corner_radius=10, fg_color="#252525",
                                     hover_color="#303030", command=lambda: self._select_box_param("Fill Factor"),
                                     height=75, width=140)
        self.btn_ff.pack(side="left", expand=True, fill="x", padx=(0, 4))
        # FF inner content
        ff_inner = ctk.CTkFrame(self.btn_ff, fg_color="transparent")
        ff_inner.place(relx=0.5, rely=0.5, anchor="center")
        ff_label = ctk.CTkLabel(ff_inner, text="FF", text_color=self.text_secondary,
                     font=("Segoe UI", 12))
        ff_label.pack()
        self.lbl_stats_ff = ctk.CTkLabel(ff_inner, text="- %", font=("Segoe UI", 16, "bold"),
                                          text_color=self.accent_purple)
        self.lbl_stats_ff.pack()
        # Bind click events to inner widgets
        for widget in [ff_inner, ff_label, self.lbl_stats_ff]:
            widget.bind("<Button-1>", lambda e: self._select_box_param("Fill Factor"))

        # PCE button - orange color (swapped with Voc)
        self.btn_pce = ctk.CTkButton(row2, text="", corner_radius=10, fg_color="#303030",
                                      hover_color="#303030", command=lambda: self._select_box_param("PCE (%)"),
                                      height=75, width=140, border_width=2, border_color=self.accent_orange)
        self.btn_pce.pack(side="right", expand=True, fill="x", padx=(4, 0))
        # PCE inner content
        pce_inner = ctk.CTkFrame(self.btn_pce, fg_color="transparent")
        pce_inner.place(relx=0.5, rely=0.5, anchor="center")
        pce_label = ctk.CTkLabel(pce_inner, text="PCE", text_color=self.text_secondary,
                     font=("Segoe UI", 12))
        pce_label.pack()
        self.lbl_stats_pce = ctk.CTkLabel(pce_inner, text="- %", font=("Segoe UI", 16, "bold"),
                                           text_color=self.accent_orange)
        self.lbl_stats_pce.pack()
        # Bind click events to inner widgets
        for widget in [pce_inner, pce_label, self.lbl_stats_pce]:
            widget.bind("<Button-1>", lambda e: self._select_box_param("PCE (%)"))

        # Store button references for highlighting
        self.stats_buttons = {
            "Voc V": self.btn_voc,
            "Jsc mA/cm2": self.btn_jsc,
            "Fill Factor": self.btn_ff,
            "PCE (%)": self.btn_pce
        }
        self.stats_colors = {
            "Voc V": self.accent_green,
            "Jsc mA/cm2": self.accent_blue,
            "Fill Factor": self.accent_purple,
            "PCE (%)": self.accent_orange
        }

        # Results Table Card
        results_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        results_card.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)

        # Header frame with title and reset button
        header_frame = ctk.CTkFrame(results_card, fg_color="transparent")
        header_frame.grid(row=0, column=0, pady=(16, 8), padx=16, sticky="ew")

        ctk.CTkLabel(header_frame, text="Best Performers", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(side="left")

        self.btn_deselect_all = ctk.CTkButton(
            header_frame, text="Clear", width=50, height=26,
            corner_radius=6, fg_color="#3D3D3D", hover_color="#3D3D3D",
            font=("Segoe UI", 11), command=self._deselect_all
        )
        self.btn_deselect_all.pack(side="right")

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

        # Treeview with columns: Sample, Voc, Jsc, FF, PCE
        self.tree = ttk.Treeview(tree_frame, columns=("name", "voc", "jsc", "ff", "pce"), show="headings", selectmode="extended")
        self.tree.heading("name", text="Sample")
        self.tree.column("name", width=120, minwidth=80, anchor="w", stretch=True)
        self.tree.heading("voc", text="Voc")
        self.tree.column("voc", width=55, minwidth=45, anchor="center", stretch=False)
        self.tree.heading("jsc", text="Jsc")
        self.tree.column("jsc", width=55, minwidth=45, anchor="center", stretch=False)
        self.tree.heading("ff", text="FF")
        self.tree.column("ff", width=50, minwidth=40, anchor="center", stretch=False)
        self.tree.heading("pce", text="PCE")
        self.tree.column("pce", width=55, minwidth=45, anchor="center", stretch=False)

        # Vertical scrollbar
        v_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scrollbar.set)

        # Horizontal scrollbar
        h_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=h_scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        # Bind selection event (multiple selection)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # JV_Analysis.exe-style table conveniences: full naming menu
        # (rename F2 / presets / compose / batch rename / revert / copy)
        try:
            from scripts.common import sample_naming as _sn
            _sn.attach_full_naming_menu(self, self.tree, on_rename=self._rename_group)
        except Exception as _pe:
            print(f"tree menu skip: {_pe}")

        # Log Card
        log_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        log_card.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 16))
        self.right_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(log_card, text="Log", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.log_text = ctk.CTkTextbox(log_card, height=120, font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 16))
        self.log_text.configure(state="disabled")

        # Initialize button highlighting for default selected_box_param (PCE)
        self.after(50, self._init_stats_button_highlight)

    def _init_stats_button_highlight(self):
        """Initialize statistics button highlighting on startup"""
        for p, btn in self.stats_buttons.items():
            if p == self.selected_box_param:
                btn.configure(fg_color="#303030", border_width=2, border_color=self.stats_colors[p])
            else:
                btn.configure(fg_color="#252525", border_width=0)

    def _deselect_all(self):
        """Clear all selections - show all samples (no filter)"""
        # Clear treeview selection
        self.tree.selection_remove(*self.tree.selection())

        # Reset selection variables
        self.selected_sample = None
        self.selected_samples = []
        self.lbl_selected_sample.configure(text="")

        # Update statistics to show averages
        self._update_statistics()

        # Update plot to show all samples
        self._update_plot()

    # =====================
    # Box Plot Parameter Selection
    # =====================
    def _select_box_param_no_sync(self, param):
        """Update box param selection without syncing Preview (to avoid loops)"""
        self.selected_box_param = param

        # Update button highlighting
        for p, btn in self.stats_buttons.items():
            if p == param:
                btn.configure(fg_color="#303030", border_width=2, border_color=self.stats_colors[p])
            else:
                btn.configure(fg_color="#252525", border_width=0)

    def _select_box_param(self, param):
        """Handle statistics button click for box plot parameter selection"""
        self.selected_box_param = param

        # Update button highlighting
        for p, btn in self.stats_buttons.items():
            if p == param:
                btn.configure(fg_color="#303030", border_width=2, border_color=self.stats_colors[p])
            else:
                btn.configure(fg_color="#252525", border_width=0)

        # Switch to Box mode and update center panel toggle
        self.center_plot_mode = "Box"
        self.plot_toggle_btn.set("Box Plot")

        # Update Preview segmented button
        param_to_preview = {
            "Voc V": "Voc",
            "Jsc mA/cm2": "Jsc",
            "Fill Factor": "FF",
            "PCE (%)": "PCE"
        }
        if param in param_to_preview:
            self.plot_selector.set(param_to_preview[param])

        self._update_plot()

    # =====================
    # Tree Selection
    # =====================
    def _on_tree_select(self, _event):
        """Handle tree selection - update stats and plot for selected samples (multiple selection supported)"""
        selection = self.tree.selection()
        if selection:
            # Get all selected items
            self.selected_samples = []
            for sel in selection:
                item = self.tree.item(sel)
                values = item['values']
                if values:
                    self.selected_samples.append({
                        'name': values[0],
                        'voc': values[1],
                        'jsc': values[2],
                        'ff': values[3],
                        'pce': values[4]
                    })

            if len(self.selected_samples) == 1:
                # Single selection
                sample = self.selected_samples[0]
                self.selected_sample = sample['name']
                self.lbl_selected_sample.configure(text=f"[{sample['name']}]")
                self.lbl_stats_voc.configure(text=f"{sample['voc']} V")
                self.lbl_stats_jsc.configure(text=f"{sample['jsc']} mA/cm²")
                self.lbl_stats_ff.configure(text=f"{sample['ff']} %")
                self.lbl_stats_pce.configure(text=f"{sample['pce']} %")
            elif len(self.selected_samples) > 1:
                # Multiple selection - show average
                self.selected_sample = None
                self.lbl_selected_sample.configure(text=f"[Multiple ({len(self.selected_samples)})]")

                # Calculate averages
                try:
                    avg_voc = sum(float(s['voc']) for s in self.selected_samples) / len(self.selected_samples)
                    self.lbl_stats_voc.configure(text=f"{avg_voc:.3f} V (avg)")
                except (ValueError, TypeError):
                    self.lbl_stats_voc.configure(text="- V")

                try:
                    avg_jsc = sum(float(s['jsc']) for s in self.selected_samples) / len(self.selected_samples)
                    self.lbl_stats_jsc.configure(text=f"{avg_jsc:.2f} mA/cm² (avg)")
                except (ValueError, TypeError):
                    self.lbl_stats_jsc.configure(text="-")

                try:
                    avg_ff = sum(float(s['ff']) for s in self.selected_samples) / len(self.selected_samples)
                    self.lbl_stats_ff.configure(text=f"{avg_ff:.2f} % (avg)")
                except (ValueError, TypeError):
                    self.lbl_stats_ff.configure(text="-")

                try:
                    avg_pce = sum(float(s['pce']) for s in self.selected_samples) / len(self.selected_samples)
                    self.lbl_stats_pce.configure(text=f"{avg_pce:.2f} % (avg)")
                except (ValueError, TypeError):
                    self.lbl_stats_pce.configure(text="- %")

            # Update plot to show selected samples
            self._update_plot()
        else:
            self.selected_sample = None
            self.selected_samples = []
            self.lbl_selected_sample.configure(text="")
            self._update_statistics()
            self._update_plot()

    # =====================
    # Logging
    # =====================
    def log(self, message):
        # Thread-safe: log() is called directly from _process_data_thread and
        # the AI analyze worker; tk widgets must only be touched on the main
        # thread, so marshal through after() when needed.
        def _append():
            try:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            try:
                self.after(0, _append)
            except Exception:
                pass

    # =====================
    # Data Processing
    # =====================
    def browse_folder(self):
        folder = filedialog.askdirectory(title="Select folder with JV text files")
        if folder:
            self.directory_path.set(folder)
            self.extra_dirs = []
            self._push_recent_dir(folder)
            self.log(f"Folder: {folder}")

    # ---- JV_Analysis.exe-style folder comparison + recent folders ----
    def add_folder(self):
        """'+ Add': overlay another folder onto the current one (compared in
        one Process run; duplicate sample names get ' (2)' suffixes)."""
        folder = filedialog.askdirectory(title="Add folder to compare")
        if not folder:
            return
        if folder == self.directory_path.get() or folder in self.extra_dirs:
            self.log("Folder already included.")
            return
        if not self.directory_path.get():
            self.directory_path.set(folder)
            self._push_recent_dir(folder)
            self.log(f"Folder: {folder}")
            return
        self.extra_dirs.append(folder)
        self._push_recent_dir(folder)
        self.log(f"+ Added folder ({1 + len(self.extra_dirs)} total): {folder} -> press Process")

    def _recent_dirs(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return [d for d in json.load(f).get('recent_dirs', []) if os.path.isdir(d)]
        except Exception:
            return []

    def _push_recent_dir(self, folder):
        try:
            data = {}
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            rec = [d for d in data.get('recent_dirs', []) if d != folder]
            data['recent_dirs'] = ([folder] + rec)[:8]
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def open_recent_menu(self):
        recents = self._recent_dirs()
        if not recents:
            self.log("No recent folders yet.")
            return
        m = tk.Menu(self, tearoff=0)
        for d in recents:
            m.add_command(label=d, command=lambda d=d: self._open_recent(d))
        try:
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            try:
                m.grab_release()
            except Exception:
                pass

    def _open_recent(self, d):
        self.directory_path.set(d)
        self.extra_dirs = []
        self._push_recent_dir(d)
        self.start_processing()

    def start_processing(self):
        if not self.directory_path.get():
            messagebox.showwarning("Warning", "Please select a folder first.")
            return

        self.btn_process.configure(state="disabled")
        self.btn_open_excel.configure(state="disabled")
        self.btn_origin_iv.configure(state="disabled")
        self.btn_origin_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Processing...")

        thread = threading.Thread(target=self._process_data_thread)
        thread.daemon = True
        thread.start()

    def _process_data_thread(self):
        try:
            directory_path = self.directory_path.get()

            if not os.path.exists(directory_path):
                self.after(0, lambda: self.log(f"Error: Path not found - {directory_path}"))
                self.after(0, self._reset_buttons)
                return

            folder_name = os.path.basename(directory_path)
            self.excel_file_path = os.path.join(directory_path, f"{folder_name}.xlsx")

            def progress_callback(idx, filename, total):
                progress = (idx + 1) / total
                self.after(0, lambda p=progress, f=filename: self._update_progress(p, f))

            dirs = [directory_path] + [d for d in self.extra_dirs if os.path.isdir(d)]
            if len(dirs) > 1:
                self.log(f"Processing {len(dirs)} folders (compare mode)...")
            else:
                self.log("Processing files...")
            self.processed_data = process_jv_directory(dirs if len(dirs) > 1 else directory_path,
                                                       progress_callback)

            if "error" in self.processed_data:
                self.after(0, lambda: self.log(f"Error: {self.processed_data['error']}"))
                self.after(0, self._reset_buttons)
                return

            # Save Excel (falls back to a timestamped name if the target
            # is open/locked in Excel; previously that failure was silent)
            self.log("Saving Excel...")
            saved_path = save_to_excel(self.processed_data, self.excel_file_path)
            if saved_path and saved_path != self.excel_file_path:
                self.excel_file_path = saved_path
                self.log(f"Excel was locked -> saved as {os.path.basename(saved_path)}")
            elif not saved_path:
                self.log("[ERROR] Excel save failed (see console).")

            self.after(0, self._on_processing_complete)

        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Error: {err}"))
            self.after(0, self._reset_buttons)

    def _update_progress(self, progress, filename):
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Processing: {filename}")

    def _reset_buttons(self):
        self.btn_process.configure(state="normal")
        self.lbl_status.configure(text="Ready")

    def _on_processing_complete(self):
        self.btn_process.configure(state="normal")
        self.btn_open_excel.configure(state="normal")
        self.btn_origin_iv.configure(state="normal")
        self.btn_origin_box.configure(state="normal")
        self.progress_bar.set(1.0)
        self.lbl_status.configure(text="Complete!")

        self.log(f"Saved: {self.excel_file_path}")
        self.log(f"Total files: {self.processed_data['total_files']}")

        # Enable AI button after processing
        if AI_AVAILABLE:
            self.btn_quick_ai.configure(state="normal")

            # Auto-save to AI database
            if self.ai_integration and self.ai_integration.is_ready():
                try:
                    save_result = self.ai_integration.assistant.db_manager.save_batch_samples(
                        self.processed_data['best_performance']
                    )
                    new_count = save_result.get('new', 0)
                    if new_count > 0:
                        self.log(f"[AI] Saved {new_count} new samples to database")
                except Exception as e:
                    self.log(f"[AI] Database save error: {e}")

        # Reset selection
        self.selected_sample = None
        self.selected_samples = []
        self.lbl_selected_sample.configure(text="")

        # Update statistics
        self._update_statistics()

        # Update table
        self._update_table()

        # Update plot
        self._update_plot()

    def _update_statistics(self):
        """Update statistics card (no sample selected).

        Shows mean ± std over ALL measured devices (summary_df), which is the
        publication-standard way to report device statistics. Previously this
        averaged only the best device of each condition, which is neither a
        population statistic nor a best value."""
        if not self.processed_data:
            return

        def _mean_std(col, fmt, unit):
            vals = pd.to_numeric(self.processed_data['summary_df'][col],
                                 errors='coerce').dropna()
            if len(vals) == 0:
                return f"- {unit}"
            if len(vals) == 1:
                return f"{vals.iloc[0]:{fmt}} {unit}"
            return f"{vals.mean():{fmt}}±{vals.std(ddof=1):{fmt}} {unit}"

        try:
            self.lbl_stats_voc.configure(text=_mean_std('Voc V', '.3f', 'V'))
        except (KeyError, ValueError, TypeError):
            self.lbl_stats_voc.configure(text="- V")

        try:
            self.lbl_stats_jsc.configure(text=_mean_std('Jsc mA/cm2', '.2f', 'mA/cm²'))
        except (KeyError, ValueError, TypeError):
            self.lbl_stats_jsc.configure(text="- mA/cm²")

        try:
            self.lbl_stats_ff.configure(text=_mean_std('Fill Factor', '.1f', '%'))
        except (KeyError, ValueError, TypeError):
            self.lbl_stats_ff.configure(text="- %")

        # Best PCE across all devices
        try:
            best_pce = pd.to_numeric(self.processed_data['summary_df']['PCE (%)'],
                                      errors='coerce').max()
            self.lbl_stats_pce.configure(text=f"{best_pce:.2f} %")
        except (KeyError, ValueError, TypeError):
            self.lbl_stats_pce.configure(text="- %")

    def _rename_group(self, old: str, new: str):
        """Rename a condition/group everywhere: best-performance table, J-V
        plot column, box-chart columns, statistics. Ported from
        JV_Analysis.exe's context-menu rename."""
        if not self.processed_data or not new:
            return
        bp = self.processed_data.get('best_performance')
        if bp is None or 'Filename' not in bp.columns or old not in set(bp['Filename']):
            return
        if new in set(bp['Filename']):
            raise ValueError(f"'{new}' already exists.")
        bp.loc[bp['Filename'] == old, 'Filename'] = new

        bcd = self.processed_data.get('best_combined_data')
        if bcd is not None and old in bcd.columns:
            self.processed_data['best_combined_data'] = bcd.rename(columns={old: new})

        box = self.processed_data.get('box_charts') or {}
        for param, df in list(box.items()):
            if df is not None and not df.empty and old in df.columns:
                box[param] = df.rename(columns={old: new})

        st = self.processed_data.get('statistics_df')
        if st is not None and 'Condition' in getattr(st, 'columns', []):
            st.loc[st['Condition'] == old, 'Condition'] = new

        sd = self.processed_data.get('summary_df')
        if sd is not None and 'Base_Name' in getattr(sd, 'columns', []):
            sd.loc[sd['Base_Name'] == old, 'Base_Name'] = new

        # keep current selection consistent
        for s in getattr(self, 'selected_samples', []):
            if isinstance(s, dict) and s.get('name') == old:
                s['name'] = new

        self._update_table()
        self._update_plot()
        self.log(f"Renamed '{old}' -> '{new}'")

    def _update_table(self):
        self.tree.delete(*self.tree.get_children())
        if not self.processed_data:
            return

        best_df = self.processed_data['best_performance']
        for _, row in best_df.iterrows():
            self.tree.insert("", "end", values=(
                row['Filename'],
                row['Voc V'],
                row['Jsc mA/cm2'],
                row['Fill Factor'],
                row['PCE (%)']
            ))

    def _update_plot(self):
        if not self.processed_data:
            return

        self.ax.clear()
        self._style_axes(self.ax)

        # Update settings from UI
        try:
            self.settings.x_min = self.x_min.get()
            self.settings.x_max = self.x_max.get()
            self.settings.y_min = self.y_min.get()
            self.settings.y_max = self.y_max.get()
        except tk.TclError:
            # Invalid value in entry, skip update
            return

        # Check center panel mode (JV or Box)
        if self.center_plot_mode == "JV":
            # JV Curve mode
            if len(self.selected_samples) > 1:
                # Multiple samples selected
                sample_names = [s['name'] for s in self.selected_samples]
                create_multi_iv_plot(self.ax, self.processed_data['best_combined_data'],
                                      sample_names, self.settings)
            elif self.selected_sample:
                # Single sample selected
                create_single_iv_plot(self.ax, self.processed_data['best_combined_data'],
                                       self.selected_sample, self.settings)
            else:
                # No selection - show all samples
                create_iv_plot(self.ax, self.processed_data['best_combined_data'], self.settings)
        else:
            # Box Plot mode - use selected_box_param from Statistics buttons
            param_name = self.selected_box_param
            box_df = self.processed_data['box_charts'].get(param_name, pd.DataFrame())

            # Get selected sample names for box plot filtering
            selected_sample_names = None
            if len(self.selected_samples) > 0:
                selected_sample_names = [s['name'] for s in self.selected_samples]
            elif self.selected_sample:
                selected_sample_names = [self.selected_sample]

            create_box_plot(self.ax, box_df, param_name, selected_sample_names)

        self.fig.tight_layout()
        self.canvas_plot.draw()

    def on_plot_select(self, value):
        """Handle Preview segmented button click - sync with center panel and statistics"""
        if value == "J-V":
            # Switch to JV mode
            self.center_plot_mode = "JV"
            self.plot_toggle_btn.set("J-V Curve")
        else:
            # Switch to Box mode for VOC, JSC, FF, PCE
            self.center_plot_mode = "Box"
            self.plot_toggle_btn.set("Box Plot")

            # Map preview selection to box parameter
            param_map = {
                "Voc": "Voc V",
                "Jsc": "Jsc mA/cm2",
                "FF": "Fill Factor",
                "PCE": "PCE (%)"
            }
            if value in param_map:
                self._select_box_param_no_sync(param_map[value])

        self._update_plot()

    # =====================
    # Actions
    # =====================
    def open_excel(self):
        if self.excel_file_path and os.path.exists(self.excel_file_path):
            os.startfile(self.excel_file_path)
            self.log(f"Opening: {self.excel_file_path}")
        else:
            messagebox.showwarning("Warning", "Excel file not found.")

    def send_iv_to_origin(self):
        if not self.processed_data:
            messagebox.showwarning("Warning", "Process data first.")
            return

        self.btn_origin_iv.configure(state="disabled")
        thread = threading.Thread(target=self._send_iv_thread)
        thread.daemon = True
        thread.start()

    def _send_iv_thread(self):
        try:
            self.after(0, lambda: self.log("Connecting to Origin..."))

            origin = connect_to_origin(self.passed_origin_path,
                                        log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))

            if origin:
                # Update settings
                self.settings.x_min = self.x_min.get()
                self.settings.x_max = self.x_max.get()
                self.settings.y_min = self.y_min.get()
                self.settings.y_max = self.y_max.get()

                # Get selected samples (empty list means all samples)
                selected_samples = [s['name'] for s in self.selected_samples] if self.selected_samples else []

                # Save selected data to transit Excel file
                transit_path = save_selected_to_transit_excel(
                    self.processed_data['best_combined_data'],
                    self.processed_data['box_charts'],
                    selected_samples,
                    self.excel_file_path,
                    log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m))
                )

                # Filter best_combined_data for selected samples
                if selected_samples:
                    voltage_col = 'Voltage (V)'
                    cols_to_keep = [voltage_col] + [col for col in self.processed_data['best_combined_data'].columns
                                                     if col != voltage_col and col in selected_samples]
                    filtered_data = self.processed_data['best_combined_data'][cols_to_keep].copy()
                else:
                    filtered_data = self.processed_data['best_combined_data']

                plot_iv_to_origin(origin, filtered_data, self.settings,
                                   log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))
                self.after(0, lambda: self.log("I-V plot sent to Origin!"))
            else:
                self.after(0, lambda: self.log("Origin connection failed"))

        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Origin error: {err}"))
        finally:
            self.after(0, lambda: self.btn_origin_iv.configure(state="normal"))

    def send_box_to_origin(self):
        if not self.processed_data:
            messagebox.showwarning("Warning", "Process data first.")
            return

        self.btn_origin_box.configure(state="disabled")
        thread = threading.Thread(target=self._send_box_thread)
        thread.daemon = True
        thread.start()

    def _send_box_thread(self):
        try:
            self.after(0, lambda: self.log("Connecting to Origin..."))

            origin = connect_to_origin(self.passed_origin_path,
                                        log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))

            if origin:
                # Get selected samples (empty list means all samples)
                selected_samples = [s['name'] for s in self.selected_samples] if self.selected_samples else []

                # Save selected data to transit Excel file
                save_selected_to_transit_excel(
                    self.processed_data['best_combined_data'],
                    self.processed_data['box_charts'],
                    selected_samples,
                    self.excel_file_path,
                    log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m))
                )

                # Filter box_charts for selected samples
                if selected_samples:
                    filtered_box_charts = {}
                    for param, box_df in self.processed_data['box_charts'].items():
                        if not box_df.empty:
                            cols = [col for col in box_df.columns if col in selected_samples]
                            if cols:
                                filtered_box_charts[param] = box_df[cols].copy()
                            else:
                                filtered_box_charts[param] = pd.DataFrame()
                        else:
                            filtered_box_charts[param] = pd.DataFrame()
                else:
                    filtered_box_charts = self.processed_data['box_charts']

                plot_box_to_origin(origin, filtered_box_charts,
                                    log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))
                self.after(0, lambda: self.log("Box plots sent to Origin!"))
            else:
                self.after(0, lambda: self.log("Origin connection failed"))

        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Origin error: {err}"))
        finally:
            self.after(0, lambda: self.btn_origin_box.configure(state="normal"))

    # =====================
    # AI Assistant Methods
    # =====================
    def _on_ai_model_change(self, selected_model: str):
        """AI model change handler"""
        if not AI_AVAILABLE or not self.ai_integration:
            return

        try:
            self.ai_model_name = selected_model
            # Initialize a new model with the current API key
            if self.passed_api_key:
                self.ai_integration.initialize(self.passed_api_key, model_name=selected_model)
                self.log(f"[AI] Model changed to: {selected_model}")
        except Exception as e:
            self.log(f"[AI] Model change failed: {e}")

    def _update_ai_status(self):
        """Update AI status"""
        if not AI_AVAILABLE:
            return

        if self.ai_integration and self.ai_integration.is_ready():
            self.lbl_ai_status.configure(text="API Connected ✓", text_color="#10B981")
        else:
            # Check whether the API key file exists
            if os.path.exists(AI_CONFIG_FILE):
                self.lbl_ai_status.configure(text="API Key found (not loaded)", text_color="#F59E0B")
            else:
                self.lbl_ai_status.configure(text="API Key: Not configured", text_color="#EF4444")


    def _set_ai_activity_status(self, state: str):
        if state == "running":
            if self._ai_status_prev is None:
                self._ai_status_prev = self.lbl_status.cget("text")
            self.lbl_status.configure(text="AI Analysis: Running...")
        elif state == "done":
            self.lbl_status.configure(text="AI Analysis: Complete")
            self.after(2000, self._clear_ai_activity_status)
        elif state == "error":
            self.lbl_status.configure(text="AI Analysis: Error")
            self.after(3000, self._clear_ai_activity_status)
        elif state == "idle":
            self._clear_ai_activity_status()

    def _clear_ai_activity_status(self):
        if self._ai_status_prev is not None:
            self.lbl_status.configure(text=self._ai_status_prev)
            self._ai_status_prev = None

    def _run_quick_ai_analysis(self):
        """Run quick AI analysis"""
        if not AI_AVAILABLE:
            messagebox.showwarning("Warning", "AI features not available.")
            return

        if not self.processed_data:
            messagebox.showwarning("Warning", "Process data first.")
            return

        if not self.ai_integration or not self.ai_integration.is_ready():
            # Open AI window if no API key
            self.log("[AI] API key not configured. Opening AI settings...")
            self._open_ai_window()
            return

        self.btn_quick_ai.configure(state="disabled", text="Analyzing...")
        self.log("[AI] Starting quick analysis...")

        # Start Progress Bar (Indeterminate)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self._set_ai_activity_status("running")

        analysis_state = {"error": False}

        def analyze():
            try:
                self.after(0, lambda: self.log("[AI] Calling Gemini API..."))
                result = self.ai_integration.analyze_processed_data(self.processed_data)

                # Error check
                if 'error' in result:
                    error_msg = result['error']
                    def show_error(msg=error_msg):
                        self.log(f"[AI Error] {msg}")
                        error_content = f"AI Analysis Error\n\n{msg}\n\nPlease check:\n- API key is valid\n- Internet connection\n- Gemini API status"
                        AIResultDialog(self, "AI Error", error_content)
                    self.after(0, show_error)
                    analysis_state["error"] = True
                    return

                # Handle result
                summary = result.get('summary', '')
                quality_score = result.get('quality_score')
                anomalies = result.get('anomalies', [])
                next_priority = result.get('next_priority', '')

                # Check if result is empty
                if not summary and quality_score is None and not anomalies and not next_priority:
                    def show_empty():
                        self.log("[AI] Analysis returned empty results. Check API connection.")
                        messagebox.showwarning("AI Quick Analysis", "No analysis results. Check API key and connection.")
                    self.after(0, show_empty)
                    return

                # Print result to log (late-binding fix)
                def log_complete():
                    self.log("[AI] Analysis complete!")
                self.after(0, log_complete)

                if summary:
                    def log_summary(s=summary):
                        self.log(f"[AI Summary] {s}")
                    self.after(0, log_summary)

                if quality_score is not None:
                    def log_score(qs=quality_score):
                        self.log(f"[AI] Quality Score: {qs}/100")
                    self.after(0, log_score)

                if anomalies:
                    for a in anomalies[:3]:
                        filename = a.get('filename', 'Unknown')
                        issue = a.get('issue', 'Unknown issue')
                        def log_anomaly(f=filename, i=issue):
                            self.log(f"[AI Warning] {f}: {i}")
                        self.after(0, log_anomaly)

                if next_priority:
                    def log_recommend(np=next_priority):
                        self.log(f"[AI Recommend] {np}")
                    self.after(0, log_recommend)

                # Show in a copyable result dialog
                msg_parts = []
                msg_parts.append("=" * 50)
                msg_parts.append("AI QUICK ANALYSIS RESULT")
                msg_parts.append("=" * 50)
                msg_parts.append("")

                if summary:
                    msg_parts.append("[Summary]")
                    msg_parts.append(summary)
                    msg_parts.append("")

                if quality_score is not None:
                    msg_parts.append(f"[Quality Score] {quality_score}/100")
                    msg_parts.append("")

                if anomalies:
                    msg_parts.append("[Detected Issues]")
                    for i, a in enumerate(anomalies, 1):
                        filename = a.get('filename', 'Unknown')
                        issue = a.get('issue', 'Unknown issue')
                        severity = a.get('severity', 'N/A')
                        cause = a.get('cause', '')
                        msg_parts.append(f"  {i}. {filename}")
                        msg_parts.append(f"     Issue: {issue}")
                        msg_parts.append(f"     Severity: {severity}")
                        if cause:
                            msg_parts.append(f"     Cause: {cause}")
                    msg_parts.append("")

                if next_priority:
                    msg_parts.append("[Recommendation]")
                    msg_parts.append(next_priority)
                    msg_parts.append("")

                msg_parts.append("=" * 50)
                msg_parts.append(f"Analyzed: {result.get('sample_count', 'N/A')} samples")
                msg_parts.append(f"Time: {result.get('timestamp', 'N/A')}")

                final_msg = "\n".join(msg_parts)

                def show_result(msg=final_msg):
                    AIResultDialog(self, "AI Quick Analysis", msg)
                self.after(0, show_result)

            except Exception as e:
                error_str = str(e)
                analysis_state["error"] = True
                def show_error(err=error_str):
                    self.log(f"[AI Error] {err}")
                    error_content = f"AI Analysis Error\n\n{err}\n\nPlease check:\n- API key is valid\n- Internet connection\n- Gemini API status"
                    AIResultDialog(self, "AI Error", error_content)
                self.after(0, show_error)

            finally:
                def reset_button():
                    self.btn_quick_ai.configure(state="normal", text="Quick Analysis")
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress_bar.set(1.0)
                    if analysis_state["error"]:
                        self._set_ai_activity_status("error")
                    else:
                        self._set_ai_activity_status("done")
                self.after(0, reset_button)

        thread = threading.Thread(target=analyze, daemon=True)
        thread.start()

    def _open_ai_window(self):
        """Open AI Assistant window"""
        if not AI_AVAILABLE or AIWindow is None:
            messagebox.showwarning("Warning", "AI features not available.\nInstall: pip install google-generativeai")
            return

        try:
            if self._ai_window is None or not self._ai_window.winfo_exists():
                self._ai_window = AIWindow(
                    self,
                    api_key=self.passed_api_key,
                    processed_data=self.processed_data,
                    activity_callback=self._set_ai_activity_status
                )
            else:
                # If a window already exists, update data and focus it
                self._ai_window.update_data(self.processed_data)
                self._ai_window.focus()
                self._ai_window.lift()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open AI window:\n{e}")
            print(f"AI window error: {e}")


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
