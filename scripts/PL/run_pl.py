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
        self.title("AI Analysis Configuration")
        self.geometry("500x400")
        self.api_key = api_key
        self.on_confirm = on_confirm
        self.attributes('-topmost', True)
        
        ctk.CTkLabel(self, text="Select Gemini Model:", font=("Segoe UI", 14, "bold")).pack(pady=(20, 5))
        self.combo_model = ctk.CTkComboBox(self, values=["Fetching models..."], width=300)
        self.combo_model.pack(pady=5)
        
        ctk.CTkLabel(self, text="Sample Context / Additional Info:", font=("Segoe UI", 14, "bold")).pack(pady=(15, 5))
        self.txt_context = ctk.CTkTextbox(self, width=400, height=150)
        self.txt_context.pack(pady=5)
        
        ctk.CTkButton(self, text="Run Analysis", command=self.on_click_run, fg_color="#252525", width=200, height=40).pack(pady=20)
        
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
        self.title("PL Analysis Pro (Final)")
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
        self.card_bg = "#1E1E1E"
        self.card_border = "#2D2D2D"
        self.panel_bg = "#141414"
        self.center_bg = "#0A0A0A"
        self.text_primary = "#FFFFFF"
        self.text_secondary = "#8B8B8B"
        self.accent_blue = "#3182F6"
        self.accent_green = "#10B981"
        self.accent_purple = "#8B5CF6"
        self.accent_pink = "#EC4899"
        self.accent_red = "#EF4444"
        self.accent_orange = "#F59E0B"

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
                    "open": ("📁 Open", self.load_data),
                    "run": ("▶ RUN Analysis", self.run_analysis),
                    "excel": ("Excel", self.export_excel),
                    "png": True,
                    "origin": ("Origin", self.send_to_origin),
                    "ai": ("🤖 AI", self.run_ai_analysis)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")


    def _setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, minsize=self.left_width)
        self.grid_columnconfigure(1, minsize=self.resizer_width)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, minsize=200)

        # === Left Control Panel ===
        self.left_panel = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=self.panel_bg)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.left_panel.grid_propagate(False)

        self.left_scroll = ctk.CTkScrollableFrame(self.left_panel, width=280, fg_color=self.panel_bg, corner_radius=0)
        self.left_scroll.pack(fill="both", expand=True)
        left_content = self.left_scroll

        # Header
        ctk.CTkLabel(left_content, text="PL Analysis", font=("Segoe UI", 22, "bold"),
                     text_color=self.text_primary).pack(pady=(20, 10))

        # 1. Load Data Card
        load_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        load_card.pack(fill="x", padx=12, pady=(8, 6))

        ctk.CTkLabel(load_card, text="Load Data", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        file_row = ctk.CTkFrame(load_card, fg_color="transparent")
        file_row.pack(fill="x", padx=16, pady=(0, 8))

        self.entry_file = ctk.CTkEntry(file_row, textvariable=self.file_path_var,
                                       placeholder_text="Select file...", height=36)
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(file_row, text="...", width=40, height=36,
                      command=self.browse_file, corner_radius=8).pack(side="right")

        self.btn_load = ctk.CTkButton(
            load_card, text="Load Data (Auto Sheet)", command=self.load_data,
            height=42, corner_radius=12, fg_color=self.accent_blue, hover_color="#2563EB",
            font=("Segoe UI", 13)
        )
        self.btn_load.pack(fill="x", padx=16, pady=(0, 16))

        # 2. Mode Card
        mode_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        mode_card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(mode_card, text="Mode", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkLabel(mode_card, text="Layer Mode:", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(anchor="w", padx=16)
        self.seg_layer = ctk.CTkSegmentedButton(mode_card, values=["1 Layer", "2 Layer"],
                                                variable=self.var_layer_mode, command=self.on_mode_change)
        self.seg_layer.pack(fill="x", padx=16, pady=(6, 16))
        self.seg_layer.set("1 Layer")

        # 3. Column Selection Card
        self.frame_cols = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        self.frame_cols.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(self.frame_cols, text="Columns", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")
        ctk.CTkLabel(self.frame_cols, text="Sample Column:", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(anchor="w", padx=16)
        self.opt_sample = ctk.CTkOptionMenu(self.frame_cols, variable=self.var_sample_col, command=self.on_col_change)
        self.opt_sample.pack(fill="x", padx=16, pady=2)

        self.lbl_ref = ctk.CTkLabel(self.frame_cols, text="Reference Column:",
                                    text_color=self.text_secondary, font=("Segoe UI", 12))
        self.opt_ref = ctk.CTkOptionMenu(self.frame_cols, variable=self.var_ref_col, command=self.on_col_change)

        # 3.5 Sample Roles Card - assign Pristine/Bi-layer, exclude, average repeats
        roles_card = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        roles_card.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(roles_card, text="Sample Roles", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 2), padx=16, anchor="w")
        ctk.CTkLabel(roles_card,
                     text="Select columns, assign roles -> Apply.\nRepeated measurements of the same role are averaged automatically.",
                     text_color=self.text_secondary, font=("Segoe UI", 11),
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
                      fg_color="#252525", hover_color="#303030",
                      font=("Segoe UI", 11, "bold"),
                      command=lambda: self._set_role("Pristine")).pack(side="left", padx=(0, 4))
        ctk.CTkButton(rb_row, text="Bi-layer", width=74, height=28,
                      fg_color=self.accent_blue, hover_color="#2563EB",
                      font=("Segoe UI", 11, "bold"),
                      command=lambda: self._set_role("Bi-layer")).pack(side="left", padx=4)
        ctk.CTkButton(rb_row, text="Exclude", width=70, height=28,
                      fg_color="#252525", hover_color="#303030",
                      font=("Segoe UI", 11, "bold"),
                      command=lambda: self._set_role("Exclude")).pack(side="left", padx=4)
        ctk.CTkButton(roles_card, text="Apply Roles (create averages -> ready to analyze)", height=40,
                      fg_color="#252525", hover_color="#303030",
                      font=("Segoe UI", 12, "bold"),
                      command=self._apply_roles).pack(fill="x", padx=16, pady=(2, 16))

        # 4. Parameters Card (Real-time Preview)
        frame_params = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        frame_params.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(frame_params, text="Parameters (Live Preview)", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8))

        # Filter Width
        ctk.CTkLabel(frame_params, text="Filter Width (Smoothness)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(anchor="w", padx=16)
        self.sl_width = ctk.CTkSlider(frame_params, from_=0, to=101, number_of_steps=101, variable=self.var_filter_width)
        self.sl_width.pack(fill="x", padx=16, pady=2)

        # Baseline Rigidity
        ctk.CTkLabel(frame_params, text="Baseline Rigidity (Background)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(anchor="w", padx=16)
        self.sl_rigid = ctk.CTkSlider(frame_params, from_=0, to=9, number_of_steps=90, variable=self.var_rigidity)
        self.sl_rigid.pack(fill="x", padx=16, pady=2)

        # Peak Protection (Using slider for log/small scale visually)
        ctk.CTkLabel(frame_params, text="Peak Protection (Fit Sens)", text_color=self.text_secondary,
                     font=("Segoe UI", 12)).pack(anchor="w", padx=16)
        self.sl_prot = ctk.CTkSlider(frame_params, from_=0, to=0.1, number_of_steps=100, variable=self.var_protection)
        self.sl_prot.pack(fill="x", padx=16, pady=(2, 16))

        # 5. Actions Card
        frame_action = ctk.CTkFrame(left_content, corner_radius=16, fg_color=self.card_bg)
        frame_action.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(frame_action, text="Actions", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        self.btn_run = ctk.CTkButton(frame_action, text="RUN Analysis", command=self.run_analysis,
                                     fg_color="#252525", hover_color="#303030",
                                     height=40, font=("Segoe UI", 13, "bold"), state="disabled")
        self.btn_run.pack(fill="x", padx=16, pady=4)

        self.btn_export = ctk.CTkButton(frame_action, text="Save Excel", command=self.export_excel, state="disabled")
        self.btn_export.pack(fill="x", padx=16, pady=4)

        self.btn_origin = ctk.CTkButton(frame_action, text="Plot to Origin", command=self.send_to_origin,
                                        fg_color="#252525", hover_color="#303030", state="disabled")
        self.btn_origin.pack(fill="x", padx=16, pady=4)

        self.btn_ai = ctk.CTkButton(frame_action, text="AI Analysis", command=self.run_ai_analysis,
                                    fg_color="#252525", hover_color="#303030", state="disabled")
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

        plot_container = ctk.CTkFrame(self.center_panel, corner_radius=12, fg_color=self.card_bg)
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
        self.right_panel = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=self.panel_bg)
        self.right_panel.grid(row=0, column=3, sticky="nsew")
        self.right_panel.grid_rowconfigure(1, weight=1)

        results_card = ctk.CTkFrame(self.right_panel, corner_radius=16, fg_color=self.card_bg)
        results_card.grid(row=0, column=0, sticky="nsew", padx=12, pady=(16, 8))

        ctk.CTkLabel(results_card, text="Results", font=("Segoe UI", 16, "bold"),
                     text_color=self.text_primary).pack(pady=(16, 8), padx=16, anchor="w")

        tree_frame = ctk.CTkFrame(results_card, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.results_tree = ttk.Treeview(tree_frame, columns=(), show="headings", height=14)
        self.results_tree.pack(fill="both", expand=True)
        self._init_results_table()

        # === Bottom Status & Guide ===
        self.bottom_panel = ctk.CTkFrame(self, height=120, fg_color=self.panel_bg)
        self.bottom_panel.grid(row=1, column=0, columnspan=4, sticky="ew", padx=0, pady=(0, 10))

        # Status Log (Left)
        self.lbl_status = ctk.CTkLabel(self.bottom_panel, text="Status: Ready", anchor="w", width=400,
                                       text_color=self.text_secondary, font=("Segoe UI", 12))
        self.lbl_status.pack(side="left", padx=16, fill="x", expand=True)

        # Parameter Guide Card (Right)
        guide_frame = ctk.CTkFrame(self.bottom_panel, fg_color=self.card_bg, corner_radius=12)
        guide_frame.pack(side="right", padx=12, pady=8, fill="y")
        guide_text = (
            "Parameter Guide:\\n"
            "Filter Width: Reduces noise (Larger = Smoother)\\n"
            "Baseline Rigidity: Background stiffness (Larger = Straighter line)\\n"
            "Peak Protection: Preserves peak shapes (Smaller = Stronger protection)"
        )
        ctk.CTkLabel(guide_frame, text=guide_text, justify="left",
                     text_color=self.text_secondary, font=("Consolas", 11)).pack(padx=10, pady=5)

    def _style_axes(self, ax):
        ax.set_facecolor(self.card_bg)
        ax.tick_params(colors="#AAAAAA", labelsize=10)
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
            font=("Segoe UI", 12),
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background="#252525",
            foreground=self.text_primary,
            font=("Segoe UI", 12, "bold"),
        )

        cols = ["Sample", "Peak (nm)", "FWHM (nm)", "Max Intensity",
                "Quench eta (peak)", "Quench eta (integral)"]
        self.results_tree.configure(columns=cols)
        for col in cols:
            self.results_tree.heading(col, text=col)
            self.results_tree.column(col, width=130, anchor="center")
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
            ref_col = self.var_ref_col.get()
            if ref_col:
                y_ref = self.df[ref_col].values
                _, _, y_ref_c = pl_core.process_spectrum(x, y_ref, fw, rig, prot)
                self.ax.plot(x, y_ref_c, color="#EC4899", linestyle="--", label=f"{ref_col} (Ref)", linewidth=2)
            
            # 2. Plot Selected Sample (Solid) - Currently single select via OptionMenu
            # If you want multi-select, need to change UI to Listbox
            samp_col = self.var_sample_col.get()
            if samp_col and samp_col != ref_col:
                y_samp = self.df[samp_col].values
                _, _, y_samp_c = pl_core.process_spectrum(x, y_samp, fw, rig, prot)
                self.ax.plot(x, y_samp_c, color="#00E5FF", label=samp_col)

            self.ax.legend(facecolor=self.card_bg, labelcolor=self.text_primary, fontsize=10, edgecolor=self.card_border)
            self.ax.set_xlabel("Wavelength (nm)", fontsize=12)
            self.ax.set_ylabel("Intensity", fontsize=12)
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
        
        for col in analyze_list:
            y_raw = self.df[col].values
            _, _, y_proc = pl_core.process_spectrum(x, y_raw, fw, rig, prot)
            self.processed_data[col] = y_proc
            
            # Fitting
            fit_res = pl_core.fit_peak_gaussian(x, y_proc)
            
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
                "Peak (nm)": f"{fit_res['center']:.1f}",
                "FWHM (nm)": f"{fit_res['fwhm']:.2f}",
                "Max Intensity": f"{i_max:.0f}",
                "Quench eta (peak)": f"{eta_peak*100:.1f}%",
                "Quench eta (integral)": f"{eta_int*100:.1f}%",
            })
            
        self.ax.legend(facecolor=self.card_bg, labelcolor=self.text_primary, edgecolor=self.card_border)
        self.ax.set_title("Analysis with Gaussian Fits (Red Dashed)", color=self.text_primary, fontsize=12)
        self.ax.set_xlabel("Wavelength (nm)", color=self.text_primary, fontsize=12)
        self.ax.set_ylabel("Intensity (a.u.)", color=self.text_primary, fontsize=12)
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
            font=("Segoe UI", 12),
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background="#252525",
            foreground=self.text_primary,
            font=("Segoe UI", 12, "bold"),
        )

        # Rebuild columns
        cols = list(df.columns)
        self.results_tree.configure(columns=cols)
        for col in cols:
            self.results_tree.heading(col, text=col)
            self.results_tree.column(col, width=140, anchor="center")

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
            self.after(0, lambda: self.show_result_popup(response, "AI Analysis Result"))
        finally:
            self.after(0, lambda: self.btn_ai.configure(state="normal"))

    def show_result_popup(self, text, title):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("700x600")
        top.attributes("-topmost", True)
        txt = ctk.CTkTextbox(top, font=("Segoe UI", 16))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", text)

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
