# run_dark_jv.py - Dark J-V Curve Analysis GUI (Simplified)
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
    from .dark_jv_core import (
        DarkJVSettings,
        process_dark_jv_directory,
        save_to_excel,
        create_dark_iv_plot,
        create_single_dark_iv_plot,
        create_multi_dark_iv_plot,
        connect_to_origin,
        plot_dark_iv_to_origin,
    )
except ImportError:
    from dark_jv_core import (
        DarkJVSettings,
        process_dark_jv_directory,
        save_to_excel,
        create_dark_iv_plot,
        create_single_dark_iv_plot,
        create_multi_dark_iv_plot,
        connect_to_origin,
        plot_dark_iv_to_origin,
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "dark_jv_config.json")
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None



# =========================
# Main GUI
# =========================
class DarkAnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("Dark J-V Curve Analysis")
        self.geometry("1200x800")

        # Data from main window
        self.passed_origin_path = origin_path
        self.passed_api_key = api_key

        # Settings
        self.settings = DarkJVSettings()

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
                _shell.attach_chrome(self, "J-V Dark Analysis", {
                    "open": [("📁 Open", self.browse_folder),
                             ("＋ Add", self.add_folder),
                             ("🕘 Recent", self.open_recent_menu)],
                    "run": ("▶ Process", self.start_processing),
                    "excel": ("Excel", self.open_excel),
                    "png": True,
                    "origin": ("Origin", self.send_iv_to_origin)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

    # =====================
    # Config I/O
    # =====================
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.x_min.set(config.get('x_min', -1.5))
                    self.x_max.set(config.get('x_max', 1.5))
                    self.y_min.set(config.get('y_min', 1e-6))
                    self.y_max.set(config.get('y_max', 100.0))
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

    # Device area: |CURRENT_CONVERSION_FACTOR|=25000 = 1000(mA/A) / 0.04(cm^2)
    DEVICE_AREA_CM2 = 0.04

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

        # Y Axis (LOG SCALE)
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

        self.btn_origin_iv = ctk.CTkButton(btn_frame, text="Send to Origin", command=self.send_iv_to_origin,
                                            fg_color="#252525", hover_color="#303030",
                                            corner_radius=10, height=40, font=("Segoe UI", 13),
                                            state="disabled")
        self.btn_origin_iv.pack(fill="x", pady=3)

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

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#0A0A0A")
        self.center_frame.grid(row=0, column=1, sticky="nsew")
        self.center_frame.grid_rowconfigure(1, weight=1)
        self.center_frame.grid_columnconfigure(0, weight=1)

        # --- View mode (I-V / J-V / |J|-V semilog) ---
        self.plot_mode = "semilog"
        mode_bar = ctk.CTkFrame(self.center_frame, fg_color="#0A0A0A")
        mode_bar.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 0))
        self.seg_mode = ctk.CTkSegmentedButton(
            mode_bar, values=["|J|-V (semilog)", "J-V (linear)", "I-V (mA)"],
            height=30, fg_color="#252525",
            selected_color="#3182F6", selected_hover_color="#2563EB",
            unselected_color="#252525", unselected_hover_color="#303030",
            font=("Segoe UI", 11), command=self._on_mode_change)
        self.seg_mode.set("|J|-V (semilog)")
        self.seg_mode.pack(side="left")

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

        # Statistics Card (Simplified - RShunt only)
        stats_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        stats_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))

        ctk.CTkLabel(stats_card, text="Statistics", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.lbl_selected_sample = ctk.CTkLabel(stats_card, text="", font=("Segoe UI", 12),
                                                 text_color=self.accent_blue)
        self.lbl_selected_sample.pack(pady=(0, 8), padx=16)

        stats_grid = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_grid.pack(fill="x", padx=16, pady=(0, 16))

        # RShunt display
        rshunt_frame = ctk.CTkFrame(stats_grid, corner_radius=10, fg_color="#252525")
        rshunt_frame.pack(fill="x", pady=4)

        ctk.CTkLabel(rshunt_frame, text="RShunt", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(pady=(12, 4))
        self.lbl_stats_rshunt = ctk.CTkLabel(rshunt_frame, text="- Ω", font=("Segoe UI", 16, "bold"),
                                              text_color=self.accent_orange)
        self.lbl_stats_rshunt.pack(pady=(0, 12))

        # Results Table Card
        results_card = ctk.CTkFrame(self.right_frame, corner_radius=16, fg_color=self.card_bg)
        results_card.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        results_card.grid_rowconfigure(1, weight=1)
        results_card.grid_columnconfigure(0, weight=1)

        # Header frame with title and reset button
        header_frame = ctk.CTkFrame(results_card, fg_color="transparent")
        header_frame.grid(row=0, column=0, pady=(16, 8), padx=16, sticky="ew")

        ctk.CTkLabel(header_frame, text="Samples", font=("Segoe UI", 16, "bold"),
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

        # Treeview with columns: Sample, RShunt, diode-fit results
        self.tree = ttk.Treeview(tree_frame, columns=("name", "rshunt", "n", "j0"),
                                 show="headings", selectmode="extended")
        self.tree.heading("name", text="Sample")
        self.tree.column("name", width=160, minwidth=120, anchor="w", stretch=True)
        self.tree.heading("rshunt", text="RShunt (Ω)")
        self.tree.column("rshunt", width=90, minwidth=70, anchor="center", stretch=False)
        self.tree.heading("n", text="n")
        self.tree.column("n", width=55, minwidth=45, anchor="center", stretch=False)
        self.tree.heading("j0", text="J0 (mA/cm²)")
        self.tree.column("j0", width=95, minwidth=80, anchor="center", stretch=False)

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
            _sn.attach_full_naming_menu(self, self.tree, on_rename=self._rename_sample)
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
                        'rshunt': values[1]
                    })

            if len(self.selected_samples) == 1:
                # Single selection
                sample = self.selected_samples[0]
                self.selected_sample = sample['name']
                self.lbl_selected_sample.configure(text=f"[{sample['name']}]")
                self.lbl_stats_rshunt.configure(text=f"{sample['rshunt']} Ω")
            elif len(self.selected_samples) > 1:
                # Multiple selection - show average
                self.selected_sample = None
                self.lbl_selected_sample.configure(text=f"[Multiple ({len(self.selected_samples)})]")

                # Calculate average
                try:
                    avg_rshunt = sum(float(s['rshunt']) for s in self.selected_samples) / len(self.selected_samples)
                    self.lbl_stats_rshunt.configure(text=f"{avg_rshunt:.2f} Ω (avg)")
                except (ValueError, TypeError):
                    self.lbl_stats_rshunt.configure(text="- Ω")

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
        # Thread-safe: log() is called directly from _process_data_thread;
        # tk widgets must only be touched on the main thread.
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
        folder = filedialog.askdirectory(title="Select folder with Dark JV text files")
        if folder:
            self.directory_path.set(folder)
            self.extra_dirs = []
            self._push_recent_dir(folder)
            self.log(f"Folder: {folder}")

    # ---- JV_Analysis.exe-style folder comparison + recent folders ----
    def add_folder(self):
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
            self.excel_file_path = os.path.join(directory_path, f"{folder_name}_Dark.xlsx")

            def progress_callback(idx, filename, total):
                progress = (idx + 1) / total
                self.after(0, lambda p=progress, f=filename: self._update_progress(p, f))

            dirs = [directory_path] + [d for d in self.extra_dirs if os.path.isdir(d)]
            if len(dirs) > 1:
                self.log(f"Processing {len(dirs)} folders (compare mode)...")
            else:
                self.log("Processing files...")
            self.processed_data = process_dark_jv_directory(dirs if len(dirs) > 1 else directory_path,
                                                            progress_callback)

            if "error" in self.processed_data:
                self.after(0, lambda: self.log(f"Error: {self.processed_data['error']}"))
                self.after(0, self._reset_buttons)
                return

            # Save Excel
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
        self.progress_bar.set(1.0)
        self.lbl_status.configure(text="Complete!")

        self.log(f"Saved: {self.excel_file_path}")
        self.log(f"Total files: {self.processed_data['total_files']}")

        # Auto-set y-axis range based on data
        if 'y_min_auto' in self.processed_data and 'y_max_auto' in self.processed_data:
            self.y_min.set(self.processed_data['y_min_auto'])
            self.y_max.set(self.processed_data['y_max_auto'])
            self.log(f"Auto-set Y range: {self.processed_data['y_min_auto']:.2e} ~ {self.processed_data['y_max_auto']:.2e}")

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
        """Update statistics with average values (when no sample selected)"""
        if not self.processed_data:
            return

        # Avg RShunt
        try:
            avg_rshunt = pd.to_numeric(self.processed_data['summary_df']['RShunt (ohms)'],
                                        errors='coerce').mean()
            self.lbl_stats_rshunt.configure(text=f"{avg_rshunt:.2f} Ω")
        except (KeyError, ValueError, TypeError):
            self.lbl_stats_rshunt.configure(text="- Ω")

    def _rename_sample(self, old: str, new: str):
        """Rename a sample everywhere (plot column, summary table, selection).
        Ported from JV_Analysis.exe's context-menu rename."""
        if not self.processed_data or not new:
            return
        cd = self.processed_data.get('combined_data')
        if cd is None or old not in cd.columns:
            return
        if new in cd.columns:
            raise ValueError(f"'{new}' already exists.")
        self.processed_data['combined_data'] = cd.rename(columns={old: new})
        sd = self.processed_data.get('summary_df')
        if sd is not None and 'Filename' in sd.columns:
            sd.loc[sd['Filename'] == old, 'Filename'] = new
        for s in self.selected_samples:
            if isinstance(s, dict) and s.get('name') == old:
                s['name'] = new
        self._update_table()
        self._update_plot()
        self.log(f"Renamed '{old}' -> '{new}'")

    def _update_table(self):
        self.tree.delete(*self.tree.get_children())
        if not self.processed_data:
            return

        summary_df = self.processed_data['summary_df']

        def _fmt(row, key, spec):
            try:
                val = row[key]
                if pd.isna(val):
                    return "-"
                return format(float(val), spec)
            except Exception:
                return "-"

        for _, row in summary_df.iterrows():
            self.tree.insert("", "end", values=(
                row['Filename'],
                row['RShunt (ohms)'],
                _fmt(row, 'Ideality n', '.2f'),
                _fmt(row, 'J0 (mA/cm2)', '.2e'),
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

        # Dark JV mode
        if len(self.selected_samples) > 1:
            # Multiple samples selected
            sample_names = [s['name'] for s in self.selected_samples]
            create_multi_dark_iv_plot(self.ax, self.processed_data['combined_data'],
                                  sample_names, self.settings)
        elif self.selected_sample:
            # Single sample selected
            create_single_dark_iv_plot(self.ax, self.processed_data['combined_data'],
                                   self.selected_sample, self.settings)
        else:
            # No selection - show all samples
            create_dark_iv_plot(self.ax, self.processed_data['combined_data'], self.settings)

        self._apply_plot_mode()
        self.fig.tight_layout()
        self.canvas_plot.draw()

    def _on_mode_change(self, value):
        self.plot_mode = {"|J|-V (semilog)": "semilog",
                          "J-V (linear)": "linear",
                          "I-V (mA)": "iv"}.get(value, "semilog")
        if self.processed_data:
            self._update_plot()

    def _apply_plot_mode(self):
        """Convert the core-drawn semilog |J|-V into the selected view mode.
        Physics: J(mA/cm^2) x A(cm^2) = I(mA). Data are |values|, so both log and linear are valid."""
        mode = getattr(self, "plot_mode", "semilog")
        if mode == "semilog":
            return
        for ln in self.ax.get_lines():
            if ln.get_label().startswith("_"):
                continue  # skip reference lines (axhline/axvline)
            if mode == "iv":
                ln.set_ydata(ln.get_ydata() * self.DEVICE_AREA_CM2)
        if mode == "iv":
            self.ax.set_ylabel("|Current| (mA)", fontsize=12, color='white')
        else:
            self.ax.set_ylabel("|Current Density| (mA/cm²)", fontsize=12, color='white')
        self.ax.set_yscale("linear")
        self.ax.relim(visible_only=True)
        self.ax.autoscale(enable=True, axis="y")

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

                # Filter combined_data for selected samples
                if selected_samples:
                    voltage_col = 'Voltage(V)'
                    cols_to_keep = [voltage_col] + [col for col in self.processed_data['combined_data'].columns
                                                     if col != voltage_col and col in selected_samples]
                    filtered_data = self.processed_data['combined_data'][cols_to_keep].copy()
                else:
                    filtered_data = self.processed_data['combined_data']

                plot_dark_iv_to_origin(origin, filtered_data, self.settings,
                                   log_callback=lambda msg: self.after(0, lambda m=msg: self.log(m)))
                self.after(0, lambda: self.log("Dark I-V plot sent to Origin!"))
            else:
                self.after(0, lambda: self.log("Origin connection failed"))

        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Origin error: {err}"))
        finally:
            self.after(0, lambda: self.btn_origin_iv.configure(state="normal"))


# =========================
# Standalone Entry Point
# =========================
def main():
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()
    win = DarkAnalysisWindow(root)
    win.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit()))
    root.mainloop()


# Alias for compatibility with main GUI
AnalysisWindow = DarkAnalysisWindow


if __name__ == "__main__":
    main()
