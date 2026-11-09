"""
run_xrd.py - XRD Analysis GUI with Dual Plot & Fitting Visualization
"""
import os
import sys

# Add script directory to path for local imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import customtkinter as ctk
try:
    from . import xrd_core
except ImportError:
    import xrd_core
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import RectangleSelector
import pandas as pd
import numpy as np
import os
from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report

# Theme Colors
COL_BG = _pal.BG_WINDOW      # JV Main Background
COL_CARD = _pal.BG_CARD    # JV Card Background
COL_STROKE = _pal.BORDER  # JV Card Border
COL_TXT = _pal.TXT     # JV Text Primary
COL_MUT = _pal.TXT_SUB     # JV Text Secondary
COL_ACC = _pal.ACCENT     # JV Accent Blue
COL_FIT = _pal.RED     # JV Accent Red
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None

COL_ERR = _pal.RED     # JV Accent Red

class AIResultDialog(ctk.CTkToplevel):
    """Dialog showing AI analysis result as copyable text"""

    def __init__(self, parent, title: str, content: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("600x500")
        self.resizable(True, True)

        # Dark theme colors
        self.card_bg = COL_CARD

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
            text="Interpretation result",
            font=_pal.font(13, "bold"),
            text_color=_pal.TXT
        ).pack(side="left")

        # Copy button
        self.btn_copy = ctk.CTkButton(
            header_frame,
            text="Copy All",
            width=80,
            height=26,
            fg_color=COL_ACC,
            hover_color=_pal.ACCENT_HOV,
            command=self._copy_content
        )
        self.btn_copy.pack(side="right")

        # Text display (scrollable, selectable)
        self.text_display = ctk.CTkTextbox(
            main_frame,
            font=_pal.mono(11),
            fg_color=_pal.BG_SUB,
            text_color=COL_TXT,
            corner_radius=_pal.R_PILL,
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
            text_color=_pal.TXT_SUB,
            font=_pal.font(11)
        )
        self.lbl_status.pack(side="left")

        ctk.CTkButton(
            btn_frame,
            text="Close",
            width=80,
            height=26,
            fg_color=_pal.BG_SUB,
            hover_color=_pal.TXT_DIM,
            command=self.destroy
        ).pack(side="right")

    def _copy_content(self):
        """Copy all text"""
        content = self.text_display.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.lbl_status.configure(text="Copied to clipboard!", text_color=_pal.GREEN)
        self.after(2000, lambda: self.lbl_status.configure(text=""))

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
        
        ctk.CTkButton(self, text="Run Analysis", command=self.on_click_run, fg_color=_pal.BG_SUB, width=200, height=28).pack(pady=20)
        
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

class XRDAnalysisTab(ctk.CTkFrame):
    def __init__(self, parent, api_key_var, model_var, origin_path=""):
        super().__init__(parent, fg_color=COL_BG)
        self.api_key_var = api_key_var # linked to the main GUI API key
        self.model_var = model_var
        self.origin_path = origin_path
        self.current_peaks_df = pd.DataFrame()
        self.x_data = None
        self.y_data = None
        self.y_fit_total = None # full fitted-curve data
        self.zoom_history = []
        self.context_entry = None
        
        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Fonts
        btn_font = _pal.font(12, "bold")
        lbl_font = _pal.font(12, "bold")

        # --- LEFT PANEL (Controls & Peak List) ---
        self.left_panel = ctk.CTkFrame(self, width=280, fg_color=_pal.BG_PANEL, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.left_panel.grid_propagate(False)

        # 1. Controls Card (JV Style)
        controls_card = ctk.CTkFrame(self.left_panel, corner_radius=_pal.R_CARD, fg_color=COL_CARD)
        controls_card.pack(pady=(16, 8), padx=12, fill="x")

        ctk.CTkLabel(controls_card, text="XRD Controls", font=lbl_font, text_color=COL_TXT).pack(pady=(16, 8), padx=16, anchor="w")
        
        self.btn_load = ctk.CTkButton(controls_card, text="Load data", command=self.load_data, fg_color=_pal.BG_SUB, height=30, font=btn_font, text_color=COL_TXT, border_width=1, border_color=_pal.BORDER_HI)
        self.btn_load.pack(fill="x", padx=16, pady=3)
        
        self.btn_run = ctk.CTkButton(controls_card, text="Run fitting", command=self.run_analysis, fg_color=COL_ACC, hover_color=_pal.ACCENT_HOV, height=30, font=btn_font, state="disabled", text_color="white", text_color_disabled=COL_MUT)
        self.btn_run.pack(fill="x", padx=16, pady=3)
        
        self.btn_origin = ctk.CTkButton(controls_card, text="Plot to Origin", command=self.plot_to_origin, fg_color=_pal.BG_SUB, height=30, font=btn_font, state="disabled", text_color=COL_TXT, text_color_disabled=COL_MUT, border_width=1, border_color=_pal.BORDER_HI)
        self.btn_origin.pack(fill="x", padx=16, pady=3)

        self.btn_ai = ctk.CTkButton(controls_card, text="Interpretation", command=self.trigger_ai, fg_color=_pal.BG_SUB, height=30, font=btn_font, state="disabled", text_color=COL_TXT, text_color_disabled=COL_MUT, border_width=1, border_color=_pal.BORDER_HI)
        self.btn_ai.pack(fill="x", padx=16, pady=(3, 10))

        # analysis options: instrument broadening, Scherrer constant, Kalpha2 stripping
        opt = ctk.CTkFrame(controls_card, fg_color="transparent")
        opt.pack(fill="x", padx=16, pady=(0, 12))
        opt.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(opt, text="Instrument FWHM (°)", font=_pal.font(10), text_color=COL_MUT).grid(row=0, column=0, sticky="w")
        self.ent_inst = _theme.entry(opt, width=70, height=24); self.ent_inst.insert(0, "0.0")
        self.ent_inst.grid(row=0, column=1, sticky="e", pady=2)
        ctk.CTkLabel(opt, text="Scherrer K", font=_pal.font(10), text_color=COL_MUT).grid(row=1, column=0, sticky="w")
        self.ent_k = _theme.entry(opt, width=70, height=24); self.ent_k.insert(0, "0.9")
        self.ent_k.grid(row=1, column=1, sticky="e", pady=2)
        self.var_ka2 = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt, text="Strip Cu Kα2 (Rachinger)", variable=self.var_ka2, font=_pal.font(10),
                        text_color=COL_TXT, checkbox_width=16, checkbox_height=16).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.lbl_ci = ctk.CTkLabel(opt, text="Crystallinity index: -", font=_pal.font(10), text_color=COL_MUT, anchor="w")
        self.lbl_ci.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.wh_result = None

        # 2. Peak List Card (JV Style)
        peak_card = ctk.CTkFrame(self.left_panel, corner_radius=_pal.R_CARD, fg_color=COL_CARD)
        peak_card.pack(pady=8, padx=12, fill="both", expand=True)

        ctk.CTkLabel(peak_card, text="Peak List", font=lbl_font, text_color=COL_TXT).pack(pady=(16, 8), padx=16, anchor="w")
        
        # Treeview for Peaks
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=COL_CARD, foreground=COL_TXT, fieldbackground=COL_CARD, borderwidth=0, font=_pal.font(11), rowheight=25)
        style.map('Treeview', background=[('selected', COL_ACC)], foreground=[('selected', 'white')])
        style.configure("Treeview.Heading", background=COL_STROKE, foreground=COL_TXT, relief="flat", font=_pal.font(12, "bold"))
        
        self.tree_frame = ctk.CTkFrame(peak_card, fg_color="transparent")
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        columns = ("2th", "int", "d", "fwhm", "size", "eta", "r2")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("2th", text="2θ (°)"); self.tree.column("2th", width=58, anchor="center")
        self.tree.heading("int", text="I"); self.tree.column("int", width=50, anchor="center")
        self.tree.heading("d", text="d (Å)"); self.tree.column("d", width=55, anchor="center")
        self.tree.heading("fwhm", text="FWHM (°)"); self.tree.column("fwhm", width=62, anchor="center")
        self.tree.heading("size", text="τ (nm)"); self.tree.column("size", width=52, anchor="center")
        self.tree.heading("eta", text="η"); self.tree.column("eta", width=40, anchor="center")
        self.tree.heading("r2", text="R²"); self.tree.column("r2", width=50, anchor="center")
        
        scrollbar = ctk.CTkScrollbar(self.tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_peak_select)

        # JV_Analysis.exe-style table conveniences: right-click copy, Ctrl+C
        try:
            from scripts.common import plot_interactions as _pi
            _pi.attach_tree_context_menu(self, self.tree)
        except Exception as _pe:
            print(f"tree menu skip: {_pe}")

        # --- CENTER PANEL (Dual Plots) ---
        self.center_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        self.center_panel.grid_columnconfigure(0, weight=1)
        self.center_panel.grid_columnconfigure(1, weight=1)
        self.center_panel.grid_rowconfigure(0, weight=1)

        # 1. Left Plot: Preview
        self.frame_preview = ctk.CTkFrame(self.center_panel, fg_color=COL_CARD, border_width=1, border_color=COL_STROKE)
        self.frame_preview.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        ctk.CTkLabel(self.frame_preview, text="1. Data Preview", font=_pal.font(12, "bold"), text_color=COL_MUT).pack(pady=5)
        
        self.fig_prev, self.ax_prev = plt.subplots(figsize=(4, 5), dpi=100)
        self._setup_ax(self.fig_prev, self.ax_prev)
        self.canvas_prev = FigureCanvasTkAgg(self.fig_prev, master=self.frame_preview)
        self.canvas_prev.get_tk_widget().pack(fill="both", expand=True)

        # 2. Right Plot: Fitting Result
        self.frame_result = ctk.CTkFrame(self.center_panel, fg_color=COL_CARD, border_width=1, border_color=COL_STROKE)
        self.frame_result.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        
        ctk.CTkLabel(self.frame_result, text="2. Optimized Fitting", font=_pal.font(12, "bold"), text_color=COL_ACC).pack(pady=5)

        self.fig_res, self.ax_res = plt.subplots(figsize=(4, 5), dpi=100)
        self._setup_ax(self.fig_res, self.ax_res)
        self.canvas_res = FigureCanvasTkAgg(self.fig_res, master=self.frame_result)
        self.canvas_res.get_tk_widget().pack(fill="both", expand=True)

        # JV_Analysis.exe-style conveniences: wheel zoom + right-click menu on
        # both plots (left-drag stays reserved for range-fit / zoom selection)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas_prev)
            _pi.add_canvas_context_menu(self, self.canvas_prev, self.fig_prev)
            _pi.enable_wheel_zoom(self.canvas_res)
            _pi.add_canvas_context_menu(self, self.canvas_res, self.fig_res)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")
        
        # Zoom Controls (Custom) - Right Plot Only for now
        self.zoom_frame = ctk.CTkFrame(self.frame_result, fg_color="transparent", height=28)
        self.zoom_frame.pack(side="bottom", fill="x", padx=10, pady=5)
        
        self.btn_reset = ctk.CTkButton(self.zoom_frame, text="Reset view", command=self.reset_view, width=80, height=26, font=_pal.font(12, "bold"), fg_color=_pal.BG_SUB)
        self.btn_reset.pack(side="right", padx=5)
        
        self.btn_undo = ctk.CTkButton(self.zoom_frame, text="Undo", command=self.undo_zoom, width=80, height=26, font=_pal.font(12, "bold"), fg_color=_pal.BG_SUB)
        self.btn_undo.pack(side="right", padx=5)

        # Drag action mode: Zoom <-> Fit Range
        self.drag_mode = "zoom"
        self.btn_fitrange = ctk.CTkButton(self.zoom_frame, text="Fit range: off",
                                          command=self.toggle_fit_range, width=140, height=26,
                                          font=_pal.font(13, "bold"), fg_color=_pal.BG_SUB)
        self.btn_fitrange.pack(side="right", padx=5)

        self.btn_wh = ctk.CTkButton(self.zoom_frame, text="W-H plot",
                                    command=self.show_williamson_hall, width=110, height=26,
                                    font=_pal.font(13, "bold"),
                                    fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER)
        self.btn_wh.pack(side="right", padx=5)

        # Rectangle Selector for Zoom (Right Plot)
        self.rs = RectangleSelector(self.ax_res, self.on_select_zoom,
                                    useblit=True,
                                    button=[1], 
                                    minspanx=5, minspany=5,
                                    spancoords='pixels',
                                    interactive=True,
                                    props=dict(facecolor=COL_ACC, edgecolor='white', alpha=0.2, fill=True))

        # --- BOTTOM/RIGHT (Log/AI) ---
        self.ai_frame = ctk.CTkFrame(self, fg_color=COL_CARD, border_width=1, border_color=COL_STROKE, height=120)
        self.ai_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        
        ctk.CTkLabel(self.ai_frame, text="Interpretation Insights / Log", font=_pal.font(13, "bold"), text_color=COL_ACC).pack(anchor="w", padx=15, pady=5)
        
        self.ai_textbox = ctk.CTkTextbox(self.ai_frame, height=80, font=_pal.mono(11), fg_color=_pal.BG_CARD, text_color=COL_TXT)
        self.ai_textbox.pack(fill="x", padx=15, pady=(0, 15))
        self.log("Ready. Load data to start.")
        self.ai_textbox.configure(state="disabled")

    def _setup_ax(self, fig, ax):
        fig.patch.set_facecolor(COL_CARD)
        ax.set_facecolor(COL_CARD)
        ax.tick_params(colors=COL_MUT, labelcolor=COL_MUT, labelsize=12)
        ax.xaxis.label.set_color(COL_TXT)
        ax.yaxis.label.set_color(COL_TXT)
        for spine in ax.spines.values(): spine.set_color(COL_STROKE)
        ax.grid(True, color=COL_STROKE, linestyle='--', alpha=0.3)

    def log(self, msg):
        self.ai_textbox.configure(state="normal")
        self.ai_textbox.insert("end", f"> {msg}\n")
        self.ai_textbox.see("end")
        self.ai_textbox.configure(state="disabled")

    def load_data(self):
        file_path = filedialog.askopenfilename(filetypes=[("Data Files", "*.csv *.xlsx *.txt *.xls"), ("All Files", "*.*")])
        if not file_path: return
            
        try:
            self.log(f"Loading: {os.path.basename(file_path)}")
            self.x_data, self.y_data = xrd_core.load_data(file_path)
            
            # --- Left Plot: Preview ---
            self.ax_prev.clear()
            self.ax_prev.plot(self.x_data, self.y_data, color='gray', alpha=0.6, label='Raw')
            self.ax_prev.set_title("Raw Data", color=COL_TXT, fontsize=14)
            self.ax_prev.legend()
            self.canvas_prev.draw()
            
            # Reset Right Plot
            self.ax_res.clear()
            self.canvas_res.draw()
            
            # Reset Tree
            for item in self.tree.get_children(): self.tree.delete(item)
            
            self.btn_run.configure(state="normal")
            self.btn_ai.configure(state="disabled")
            self.btn_origin.configure(state="disabled")
            self.log(f"Data Loaded. Click 'Run Analysis' to fit peaks.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.log(f"Error: {e}")

    def run_analysis(self):
        if self.x_data is None: return
        
        try:
            self.log("Running pseudo-Voigt fitting...")
            inst, k = self._analysis_options()
            y_in = self.y_data
            if self.var_ka2.get():
                y_in = xrd_core.strip_kalpha2(self.x_data, self.y_data)
                self.log("Cu Kα2 contribution stripped (Rachinger, I2/I1 = 0.5).")
            self.y_used = y_in

            # --- Call Core Logic (Returns DF and Fitted Curve) ---
            self.current_peaks_df, self.y_fit_total = xrd_core.detect_peaks_and_fit(
                self.x_data, y_in, instrumental_fwhm_deg=inst, scherrer_k=k)
            try:
                ci = xrd_core.crystallinity_index(self.x_data, y_in)
                self.ci_result = ci
                self.lbl_ci.configure(text=f"Crystallinity index: {ci['CI_percent']:.1f} % (ALS amorphous background)")
            except Exception:
                self.ci_result = None
            
            # --- Right Plot: Fitting Result ---
            self.ax_res.clear()
            # 1. Raw Data (Background)
            self.ax_res.scatter(self.x_data, y_in, s=5, color='gray', alpha=0.4,
                                label='Kα1 (Kα2 stripped)' if self.var_ka2.get() else 'Raw')
            
            # 2. Fitted Curve (Red Line)
            if self.y_fit_total is not None:
                self.ax_res.plot(self.x_data, self.y_fit_total, color=COL_FIT, linewidth=1.5, label='Fit')
            
            # 3. Peak Markers
            if not self.current_peaks_df.empty:
                px = self.current_peaks_df["2Theta"]
                py = self.current_peaks_df["Intensity"]
                self.ax_res.plot(px, py, "v", color=_pal.GREEN, markersize=6, label="Peak")
                
                # Annotate top peaks
                for i in range(min(3, len(self.current_peaks_df))):
                    row = self.current_peaks_df.iloc[i]
                    self.ax_res.annotate(f"{row['2Theta']:.1f}", (row['2Theta'], row['Intensity']), 
                                         xytext=(0, 5), textcoords='offset points', ha='center', color=COL_TXT, fontsize=10)

                # Update Treeview
                for item in self.tree.get_children(): self.tree.delete(item)
                self._refresh_peak_table()
            
            self.ax_res.set_title("Fitted Result", color=COL_TXT, fontsize=14)
            self.ax_res.legend()
            self.canvas_res.draw()
            
            self.btn_ai.configure(state="normal")
            self.btn_origin.configure(state="normal")
            self.log(f"Optimization Complete. Found {len(self.current_peaks_df)} peaks.")
            
        except Exception as e:
            self.log(f"Analysis Error: {e}")

    def trigger_ai(self):
        if self.current_peaks_df.empty: return
        if not self.api_key_var.get():
            messagebox.showwarning("Warning", "API Key is missing.")
            return

        AIConfigDialog(self, self.api_key_var.get(), self.start_ai_thread)

    def start_ai_thread(self, model, context):
        self.log(f"Requesting AI analysis ({model})...")
        self.btn_ai.configure(state="disabled")
        api_key = self.api_key_var.get()
        threading.Thread(target=self._run_ai_analysis, args=(api_key, model, context), daemon=True).start()

    def _run_ai_analysis(self, api_key, model, context):
        try:
            comment = xrd_core.analyze_with_gemini(
                api_key, 
                model, 
                context, 
                self.current_peaks_df.head(10)
            )
            self.after(0, lambda: self.update_ai_ui(comment))
        except Exception as e:
            self.after(0, lambda err=str(e): self.update_ai_ui(f"Error: {err}"))

    def update_ai_ui(self, text):
        self.log("Interpretation Complete.")
        # Show Result in Popup
        AIResultDialog(self, "XRD Interpretation", text)
        self.btn_ai.configure(state="normal")
        
    def plot_to_origin(self):
        if self.x_data is None: return
        self.log("Connecting to Origin...")
        threading.Thread(target=self._origin_thread, daemon=True).start()
        
    def _origin_thread(self):
        origin = xrd_core.connect_to_origin(self.origin_path, log_callback=lambda m: self.after(0, lambda: self.log(m)))
        if origin:
            # Pass Fitted Curve (y_fit_total) as well
            xrd_core.plot_xrd_to_origin(
                origin, self.x_data, self.y_data, 
                self.y_fit_total,  # <--- pass fitted data
                self.current_peaks_df, 
                log_callback=lambda m: self.after(0, lambda: self.log(m))
            )

    def on_select_zoom(self, eclick, erelease):
        x1, y1 = eclick.xdata, eclick.ydata
        x2, y2 = erelease.xdata, erelease.ydata
        if None in (x1, x2):
            return

        if getattr(self, "drag_mode", "zoom") == "fit":
            self.fit_selected_range(min(x1, x2), max(x1, x2))
            return

        # Save current limits
        self.zoom_history.append((self.ax_res.get_xlim(), self.ax_res.get_ylim()))
        self.ax_res.set_xlim(min(x1, x2), max(x1, x2))
        self.ax_res.set_ylim(min(y1, y2), max(y1, y2))
        self.canvas_res.draw()

    def toggle_fit_range(self):
        self.drag_mode = "fit" if self.drag_mode == "zoom" else "zoom"
        if self.drag_mode == "fit":
            self.btn_fitrange.configure(text="Fit range: on", fg_color=_pal.GREEN)
            self.log("Fit Range mode: fits only the dragged 2-theta range.")
        else:
            self.btn_fitrange.configure(text="Fit range: off", fg_color=_pal.BG_SUB)
            self.log("Back to Zoom mode.")

    def fit_selected_range(self, xmin, xmax):
        """Voigt-fit only the dragged 2-theta range and update results."""
        if self.x_data is None:
            return
        mask = (self.x_data >= xmin) & (self.x_data <= xmax)
        if int(np.sum(mask)) < 10:
            self.log(f"Too few points in range [{xmin:.2f}, {xmax:.2f}].")
            return
        try:
            sub_df, sub_fit = xrd_core.detect_peaks_and_fit(
                self.x_data[mask], self.y_data[mask])
        except Exception as e:
            self.log(f"Range fit failed: {e}")
            return
        if sub_df.empty:
            self.log("No peaks found in the selected range.")
            return

        # Replace peaks in this range within existing results
        if self.current_peaks_df is not None and not self.current_peaks_df.empty:
            keep = self.current_peaks_df[
                (self.current_peaks_df["2Theta"] < xmin) |
                (self.current_peaks_df["2Theta"] > xmax)]
            self.current_peaks_df = (
                pd.concat([keep, sub_df], ignore_index=True)
                  .sort_values("Intensity", ascending=False)
                  .reset_index(drop=True))
        else:
            self.current_peaks_df = sub_df

        # Draw overlay
        self.ax_res.plot(self.x_data[mask], sub_fit, color=_pal.GREEN,
                         linewidth=1.8, label=f"Fit [{xmin:.1f}-{xmax:.1f}]")
        self.ax_res.legend(fontsize=8)
        self.canvas_res.draw()
        self._refresh_peak_table()
        self.log(f"Range [{xmin:.2f}, {xmax:.2f}] fitted: {len(sub_df)} peaks "
                 f"(mean FWHM {sub_df['FWHM'].mean():.3f} deg)")

    def _analysis_options(self):
        try:
            inst = max(float(self.ent_inst.get()), 0.0)
        except (ValueError, AttributeError):
            inst = 0.0
        try:
            k = float(self.ent_k.get())
            if not 0.5 < k < 1.5:
                k = 0.9
        except (ValueError, AttributeError):
            k = 0.9
        return inst, k

    def _refresh_peak_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if self.current_peaks_df is None:
            return
        for _, row in self.current_peaks_df.iterrows():
            size_nm = row.get('Crystallite_nm', float('nan'))
            eta = row.get('eta_pV', float('nan'))
            r2 = row.get('Fit_R2', float('nan'))
            self.tree.insert("", "end", values=(
                f"{row['2Theta']:.3f}", f"{row['Intensity']:.0f}",
                f"{row['d_spacing']:.4f}", f"{row['FWHM']:.3f}",
                f"{size_nm:.1f}" if pd.notna(size_nm) else "-",
                f"{eta:.2f}" if pd.notna(eta) else "-",
                f"{r2:.3f}" if pd.notna(r2) else "-"))

    def show_lattice_dialog(self):
        """Cubic lattice parameter from indexed reflections (mean and Nelson-Riley)."""
        df = self.current_peaks_df
        if df is None or df.empty:
            messagebox.showwarning("Lattice parameter", "Run the fitting first.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Lattice parameter (cubic)")
        win.geometry("520x520")
        win.configure(fg_color=_pal.BG_WINDOW)
        win.transient(self.winfo_toplevel())
        ctk.CTkLabel(win, text="Enter h k l for the reflections to use (leave blank to skip). "
                              "a = d·sqrt(h²+k²+l²); the Nelson-Riley extrapolation to θ = 90° removes "
                              "displacement and absorption errors.", font=_pal.font(10), text_color=COL_MUT,
                     wraplength=490, justify="left").pack(anchor="w", padx=12, pady=(12, 6))
        frame = ctk.CTkScrollableFrame(win, fg_color=COL_CARD, height=250)
        frame.pack(fill="both", expand=True, padx=12)
        entries = []
        peaks = df.sort_values("2Theta")
        for _, row in peaks.iterrows():
            r = ctk.CTkFrame(frame, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=f"2θ = {row['2Theta']:.3f}°   d = {row['d_spacing']:.4f} Å", font=_pal.font(10),
                         text_color=COL_TXT, width=240, anchor="w").pack(side="left")
            e = _theme.entry(r, width=90, height=24, placeholder_text="h k l")
            e.pack(side="right")
            entries.append((float(row["2Theta"]), e))
        out = ctk.CTkTextbox(win, height=110, font=_pal.mono(10), fg_color=COL_CARD, text_color=COL_TXT)
        out.pack(fill="x", padx=12, pady=8)

        def compute():
            tt, hkl = [], []
            for two_theta, e in entries:
                txt = e.get().strip().replace(",", " ")
                if not txt:
                    continue
                parts = txt.split()
                if len(parts) != 3:
                    messagebox.showwarning("Lattice parameter", f"'{txt}' is not an h k l triple.", parent=win)
                    return
                try:
                    hkl.append(tuple(int(v) for v in parts))
                except ValueError:
                    messagebox.showwarning("Lattice parameter", f"'{txt}' is not an h k l triple.", parent=win)
                    return
                tt.append(two_theta)
            if len(tt) < 1:
                return
            res = xrd_core.lattice_parameter_cubic(tt, hkl)
            lines = [f"a (mean of {len(tt)} reflections) = {res['a_mean_A']:.5f} ± {res['a_std_A']:.5f} Å"]
            if np.isfinite(res["a_NR_A"]):
                lines.append(f"a (Nelson-Riley extrapolation) = {res['a_NR_A']:.5f} Å   (R² = {res['NR_R2']:.3f})")
            else:
                lines.append("Nelson-Riley extrapolation needs at least 3 indexed reflections.")
            for (h, k_, l), a in zip(hkl, res["a_per_peak_A"]):
                lines.append(f"  ({h} {k_} {l}): a = {a:.5f} Å")
            out.configure(state="normal")
            out.delete("1.0", "end")
            out.insert("1.0", "\n".join(lines))
            out.configure(state="disabled")
            self.lattice_result = res
            self.log(lines[0] + ("; " + lines[1] if len(lines) > 1 else ""))

        ctk.CTkButton(win, text="Compute", height=28, fg_color=COL_ACC, hover_color=_pal.ACCENT_HOV, text_color="white",
                      font=_pal.font(11, "bold"), corner_radius=_pal.R_PILL, command=compute).pack(pady=(0, 12))

    def export_report(self):
        if self.current_peaks_df is None or self.current_peaks_df.empty:
            messagebox.showwarning("Report", "Run the fitting first.")
            return
        path = _report.ask_report_path(self, "XRD_report.md")
        if not path:
            return
        inst, k = self._analysis_options()
        sections = [("Fitted reflections", self.current_peaks_df.round(5))]
        if getattr(self, "wh_result", None):
            wh = self.wh_result
            sections.append(("Williamson-Hall", {"Crystallite size D (nm)": wh["D_nm"], "D standard error (nm)": wh["D_err_nm"],
                                                 "Microstrain": wh["strain"], "Strain standard error": wh["strain_err"],
                                                 "R²": wh["R2"], "Reflections": wh["n_peaks"]}))
        if getattr(self, "ci_result", None):
            sections.append(("Crystallinity", {"Crystallinity index (%)": self.ci_result["CI_percent"]}))
        if getattr(self, "lattice_result", None):
            lr = self.lattice_result
            sections.append(("Cubic lattice parameter", {"a mean (Å)": lr["a_mean_A"], "a std (Å)": lr["a_std_A"],
                                                         "a Nelson-Riley (Å)": lr["a_NR_A"]}))
        notes = (f"ALS background; overlapping reflections fitted simultaneously with pseudo-Voigt profiles. "
                 f"Scherrer τ = Kλ/(β cos θ), K = {k}, Cu Kα λ = {xrd_core.LAMBDA_CU} Å, instrument FWHM {inst}° "
                 f"removed in quadrature. Kα2 stripping: {'on' if self.var_ka2.get() else 'off'}.")
        try:
            _report.write_markdown_report(path, "XRD analysis", sections, figure=self.fig_res, notes=notes)
            self.log(f"Report saved: {path}")
        except Exception as ex:
            messagebox.showerror("Report", str(ex))

    def show_williamson_hall(self):
        """Williamson-Hall plot (xrd_core.williamson_hall): beta cos(theta) = K lambda/D + 4 eps sin(theta),
        with the instrument FWHM from the options removed in quadrature."""
        df = self.current_peaks_df
        if df is None or df.empty:
            messagebox.showwarning("W-H", "Run Analysis to fit peaks first.")
            return
        d2 = df[(df["FWHM"] > 0) & (df["FWHM"] < 5)].copy()
        if len(d2) < 2:
            messagebox.showwarning("W-H", "W-H plot needs at least 2 valid peaks.")
            return

        inst, K = self._analysis_options()
        lam = xrd_core.LAMBDA_CU  # Å
        wh = xrd_core.williamson_hall(d2["2Theta"].values, d2["FWHM"].values, instrumental_fwhm_deg=inst, k=K)
        if wh["n_peaks"] < 2:
            messagebox.showwarning("W-H", "Fewer than 2 reflections remain after the instrument correction.")
            return
        self.wh_result = wh
        X, Y = wh["x"], wh["y"]
        m, b = wh["slope"], wh["intercept"]
        eps, D_nm, r2 = wh["strain"], wh["D_nm"], wh["R2"]
        theta = np.radians(d2["2Theta"].values / 2.0)
        D_scherrer_nm = np.array([xrd_core.scherrer_size(t, f, inst, K) for t, f in zip(d2["2Theta"].values, d2["FWHM"].values)])

        win = ctk.CTkToplevel(self)
        win.title("Williamson-Hall Plot")
        win.geometry("760x600")
        win.configure(fg_color=_pal.BG_WINDOW)
        win.transient(self.winfo_toplevel())

        from matplotlib.figure import Figure as _Fig
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _Canvas
        fig = _Fig(figsize=(7, 4), dpi=100, facecolor=_pal.BG_CARD)
        ax = fig.add_subplot(111)
        ax.set_facecolor(_pal.PLOT_AXES)
        for sp in ax.spines.values():
            sp.set_color(_pal.PLOT_SPINE)
        ax.tick_params(colors=_pal.PLOT_TICK)
        ax.scatter(X, Y, s=45, color=_pal.ACCENT, zorder=3, label="peaks")
        xs = np.linspace(0, X.max() * 1.05, 100)
        ax.plot(xs, m * xs + b, color=_pal.RED, linewidth=2,
                label=f"fit  (R²={r2:.4f})")
        ax.set_xlabel("4·sinθ", color=_pal.TXT_MUTED)
        ax.set_ylabel("β·cosθ (rad)", color=_pal.TXT_MUTED)
        err_d = f" ± {wh['D_err_nm']:.1f}" if np.isfinite(wh["D_err_nm"]) else ""
        err_e = f" ± {wh['strain_err']:.1e}" if np.isfinite(wh["strain_err"]) else ""
        ax.set_title(f"D = {D_nm:.1f}{err_d} nm    ε = {eps:.2e}{err_e}", color=_pal.PLOT_FG)
        ax.grid(True, linestyle="--", alpha=0.3, color=_pal.BG_SUB)
        ax.legend(facecolor=_pal.BG_SUB, edgecolor=_pal.PLOT_SPINE, labelcolor=_pal.TXT_MUTED)
        fig.tight_layout()
        cv = _Canvas(fig, master=win)
        cv.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=12)
        cv.draw()

        txt = ctk.CTkTextbox(win, height=150, font=_pal.mono(11),
                             fg_color=_pal.BG_CARD, text_color=_pal.TXT_MUTED)
        txt.pack(fill="x", padx=12, pady=(0, 12))
        lines = [f"Williamson-Hall:  βcosθ = Kλ/D + 4ε·sinθ   (K={K}, λ={lam} Å, Cu Kα)",
                 f"  Crystallite size D = {D_nm:.2f}{err_d} nm   |   Microstrain ε = {eps:.3e}{err_e}   |   R² = {r2:.4f}",
                 (f"  instrument FWHM {inst}° removed in quadrature" if inst > 0 else
                  "  (note: no instrument correction entered -> D is a lower bound)"),
                 "-" * 72,
                 f"  {'2θ(°)':>8} {'FWHM(°)':>9} {'Scherrer D(nm)':>15}"]
        for tt, fw, dd in zip(d2['2Theta'].values, d2['FWHM'].values, D_scherrer_nm):
            lines.append(f"  {tt:>8.2f} {fw:>9.3f} {dd:>15.1f}")
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")
        self.log(f"W-H: D = {D_nm:.1f}{err_d} nm, ε = {eps:.2e}{err_e} (R² = {r2:.3f}, {wh['n_peaks']} reflections)")

    def undo_zoom(self):
        if self.zoom_history:
            xlim, ylim = self.zoom_history.pop()
            self.ax_res.set_xlim(xlim)
            self.ax_res.set_ylim(ylim)
            self.canvas_res.draw()

    def reset_view(self):
        self.zoom_history.clear()
        self.ax_res.autoscale()
        self.canvas_res.draw()

    def on_peak_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        try:
            values = self.tree.item(selected[0], "values")
            if not values: return
            
            target_2th = float(values[0])
            
            # Save history for Undo
            self.zoom_history.append((self.ax_res.get_xlim(), self.ax_res.get_ylim()))
            
            span = 2.0 # +/- 2 degrees
            self.ax_res.set_xlim(target_2th - span, target_2th + span)
            
            if self.x_data is not None and self.y_data is not None:
                mask = (self.x_data >= target_2th - span) & (self.x_data <= target_2th + span)
                if mask.any():
                    y_sub = self.y_data[mask]
                    self.ax_res.set_ylim(y_sub.min(), y_sub.max() * 1.2)
            
            self.canvas_res.draw()
        except Exception as e:
            self.log(f"Zoom error: {e}")

# Main Window Wrapper
class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("XRD Analysis")
        self.geometry("1100x750")
        
        # Variables
        self.api_key_var = ctk.StringVar(value=api_key)
        self.model_var = ctk.StringVar(value="gemini-2.5-flash")
        
        self.tab = XRDAnalysisTab(self, self.api_key_var, self.model_var, origin_path)
        self.tab.pack(fill="both", expand=True)

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "XRD Analysis", {
                    "open": ("Open", self.tab.load_data),
                    "run": ("Run analysis", self.tab.run_analysis),
                    "fit": [("W-H plot", self.tab.show_williamson_hall),
                            ("Lattice parameter", self.tab.show_lattice_dialog)],
                    "png": True,
                    "report": ("Report", self.tab.export_report),
                    "origin": ("Origin", self.tab.plot_to_origin),
                    "ai": ("Interpretation", self.tab.trigger_ai)
                }, hints="Drag on the fit plot: zoom (or fit range when 'Fit range' is on)  |  Click a peak row: zoom to it  |  "
                         "Wheel: zoom  |  Right-click: menus")
            except Exception as _ce:
                print(f"shell skip: {_ce}")

        
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

if __name__ == "__main__":
    try:
        ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
        root = ctk.CTk()
        AnalysisWindow(root)
        root.mainloop()
    except Exception as e:
        print(f"Error: {e}")
