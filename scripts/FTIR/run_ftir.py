import os
import sys

# Add script directory to path for local imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import json
import webbrowser
import urllib.parse
import numpy as np
import re
import threading
import customtkinter as ctk
try:
    from . import ftir_core
except ImportError:
    import ftir_core

CONFIG_FILE = os.path.join(SCRIPT_DIR, "ftir_config.json")
try:
    from scripts.common import analysis_shell as _shell
except Exception:
    _shell = None

# Extended color palette (10 colors)
LAYER_COLORS = [
    '#3182F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', 
    '#EC4899', '#6366F1', '#14B8A6', '#F97316', '#84CC16'
]

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
            
            def do_update():
                try:
                    if self.winfo_exists():
                        self.combo_model.configure(values=models)
                        self.combo_model.set(models[0])
                except (tk.TclError, AttributeError): pass

            # NOTE: do not call winfo_exists() from the worker thread; after()
            # itself is the thread-safe hand-off and raises if the widget died
            try:
                self.after(0, do_update)
            except Exception:
                pass
        except Exception:
            def do_err():
                try:
                    if self.winfo_exists():
                        self.combo_model.configure(values=["models/gemini-2.5-flash"])
                except (tk.TclError, AttributeError): pass
            try:
                self.after(0, do_err)
            except Exception:
                pass

    def on_click_run(self):
        self.on_confirm(self.combo_model.get(), self.txt_context.get("1.0", "end").strip())
        self.destroy()

class LoadingPopup(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.geometry("300x120")
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 150
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 60
        self.geometry(f"+{x}+{y}")
        self.frame = ctk.CTkFrame(self, fg_color="#303030", border_width=2, border_color="#3182F6")
        self.frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self.frame, text="AI Analyzing...", font=("Segoe UI", 16, "bold"), text_color="white").pack(pady=(25, 10))
        self.bar = ctk.CTkProgressBar(self.frame, width=220, mode="indeterminate", progress_color="#3182F6")
        self.bar.pack(pady=10)
        self.bar.start()

class ResultPopup(ctk.CTkToplevel):
    def __init__(self, parent, title, content, save_data=None):
        super().__init__(parent)
        self.title("Result")
        self.geometry("800x600")
        self.attributes("-topmost", True)
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 400
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 300
        self.geometry(f"+{x}+{y}")
        self.save_data = save_data
        
        header = ctk.CTkFrame(self, height=50, fg_color="#1E1E1E")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=title, font=("Segoe UI", 20, "bold"), text_color="#3182F6").pack(pady=10)
        
        self.textbox = ctk.CTkTextbox(self, font=("Segoe UI", 14), fg_color="#252525", text_color="#DDDDDD")
        self.textbox.pack(fill="both", expand=True, padx=20, pady=20)
        self.textbox.insert("1.0", content)
        self.textbox.configure(state="disabled")
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        if self.save_data:
            ctk.CTkButton(btn_frame, text="Save to Excel", command=self.save_excel, height=40, fg_color="#252525").pack(side="left", fill="x", expand=True, padx=(0, 10))
            
        ctk.CTkButton(btn_frame, text="Close", command=self.destroy, height=40, fg_color="#3D3D3D").pack(side="right", fill="x", expand=True, padx=(10, 0))

    def save_excel(self):
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if path:
            pd.DataFrame([self.save_data]).to_excel(path, index=False)
            messagebox.showinfo("Saved", "Result saved to Excel.")

class PeakListPopup(ctk.CTkToplevel):
    def __init__(self, parent, layer_name, peak_data):
        super().__init__(parent)
        self.title(f"Peak List - {layer_name}")
        self.geometry("600x400")
        
        # Treeview style (dark theme)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#252525", foreground="white", fieldbackground="#252525", borderwidth=0)
        style.map('Treeview', background=[('selected', '#3182F6')])
        style.configure("Treeview.Heading", background="#444444", foreground="white", relief="flat")

        # Column definitions
        columns = ("pos", "assign", "mat")
        tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        tree.heading("pos", text="Wavenumber (cm-1)")
        tree.heading("assign", text="Assignment")
        tree.heading("mat", text="Material/Func Group")
        
        tree.column("pos", width=120, anchor="center")
        tree.column("assign", width=200, anchor="w")
        tree.column("mat", width=200, anchor="w")
        
        # Scrollbar
        scrollbar = ctk.CTkScrollbar(self, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Insert data (sorted by wavenumber)
        sorted_keys = sorted(peak_data.keys())
        for wn in sorted_keys:
            info = peak_data[wn]
            tree.insert("", "end", values=(
                f"{wn:.1f}", 
                info.get("assignment", "-"), 
                info.get("material", "-")
            ))

class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path, api_key):
        super().__init__(parent)
        self.title("FTIR Analyzer Pro")
        self.geometry("1600x950")
        self.origin_path = origin_path
        
        self.initial_dir = "/"
        self.api_key_var = ctk.StringVar(value=api_key)
        self.model_var = ctk.StringVar(value="gemini-3-flash-preview")
        
        self.layers = []
        self.target_layer_idx = 0
        self.ref_layer_idx = 0
        self.layer_buttons = []
        
        self.compare_mode = False
        self.compare_step = 0
        self.compare_peaks = [None, None]
        self.compare_indices = [0, 0]

        self.pan_start = None
        self.current_peak_idx = -1
        self.loading_popup = None
        
        # [NEW] variables for managing zoom state
        self.force_reset_view = False  # if True, force reset (autoscale)
        self.is_initial_load = True    # whether this is the first load

        self.load_config()
        self.after(10, self.center_window)

        self.paned_window = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=5, bg="#252525", bd=0)
        self.paned_window.pack(fill="both", expand=True)

        self.create_left_panel()
        self.create_center_panel()
        self.create_right_panel()
        self._init_bindings()

        # Shared chrome: common toolbar/status bar across all tools (unified button order/position)
        if _shell is not None:
            try:
                _shell.attach_chrome(self, "FTIR Analysis", {
                    "open": ("📁 Open", self.load_data),
                    "run": ("▶ Auto Compare", self.run_auto_compare),
                    "excel": ("Excel", self.save_all_results),
                    "png": True,
                    "origin": ("Origin", self.plot_to_origin),
                    "ai": ("🤖 AI Compare", self.run_ai_compare)
                }, hints="Open -> Process -> Fit -> Export  |  shared toolbar across all tools")
            except Exception as _ce:
                print(f"shell skip: {_ce}")


    def center_window(self):
        if self.winfo_exists():
            self.state('zoomed')

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    if not self.api_key_var.get(): self.api_key_var.set(data.get("api_key", ""))
            except: pass

    def _init_bindings(self):
        self.bind('<Control-z>', lambda e: None)
        self.bind('<Escape>', self.on_esc_press)
        self.bind('<Return>', self.on_enter_press)
        self.bind('<Left>', self.on_key_press)
        self.bind('<Right>', self.on_key_press)
        self.bind('r', self.reset_view_action)
        self.bind('R', self.reset_view_action)
        
        for i in range(10):
            self.bind(str((i + 1) % 10), lambda e, idx=i: self.set_target_layer(idx))

    def create_left_panel(self):
        self.left_frame = ctk.CTkFrame(self.paned_window, width=320, corner_radius=0, fg_color="#141414")
        self.paned_window.add(self.left_frame, minsize=300)
        self.left_scroll = ctk.CTkScrollableFrame(self.left_frame, fg_color="transparent")
        self.left_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        self.add_card_label("Data & Target Layer")
        ctk.CTkButton(self.left_scroll, text="Load File (Max 10)", command=self.load_data, fg_color="#3182F6").pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(self.left_scroll, text="Target (Edit/Info):", text_color="#8B8B8B", font=("Segoe UI", 11)).pack(anchor="w", padx=10)
        self.combo_target = ctk.CTkComboBox(self.left_scroll, command=self.on_target_change)
        self.combo_target.pack(fill="x", padx=10, pady=(0, 10))
        
        ctk.CTkLabel(self.left_scroll, text="Sample Info (Context):", text_color="#8B8B8B", font=("Segoe UI", 11)).pack(anchor="w", padx=10)
        self.entry_context = ctk.CTkEntry(self.left_scroll)
        self.entry_context.pack(fill="x", padx=10, pady=(0, 10))
        self.entry_context.bind("<KeyRelease>", self.save_context_info)

        ctk.CTkLabel(self.left_scroll, text="Reference Layer:", text_color="#8B8B8B", font=("Segoe UI", 11)).pack(anchor="w", padx=10)
        self.combo_ref = ctk.CTkComboBox(self.left_scroll, command=self.on_ref_change)
        self.combo_ref.pack(fill="x", padx=10, pady=(0, 10))

        self.add_card_label("Edit Peaks")
        edit_frame = ctk.CTkFrame(self.left_scroll, fg_color="transparent")
        edit_frame.pack(fill="x", padx=10, pady=5)
        self.btn_add = ctk.CTkButton(edit_frame, text="Add Peak", command=self.toggle_add_mode, fg_color="#252525")
        self.btn_add.pack(fill="x", pady=(0, 5))
        self.btn_del = ctk.CTkButton(edit_frame, text="Delete Peak", command=self.toggle_delete_mode, fg_color="#252525")
        self.btn_del.pack(fill="x")
        self.lbl_edit_status = ctk.CTkLabel(self.left_scroll, text="Ready", text_color="#8B8B8B", font=("Segoe UI", 11))
        self.lbl_edit_status.pack(pady=(0, 10))

        self.add_card_label("Analysis (Target Layer)")
        self.btn_ai = ctk.CTkButton(self.left_scroll, text="Analyze Target Peaks", command=self.analyze_target_thread, fg_color="#252525")
        self.btn_ai.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(self.left_scroll, text="View Peak List (Table)", command=self.show_peak_list, fg_color="#252525").pack(fill="x", padx=10, pady=5)
        self.btn_origin = ctk.CTkButton(self.left_scroll, text="Plot to Origin", command=self.plot_to_origin, fg_color="#252525")
        self.btn_origin.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(self.left_scroll, text="Save All Layers (Excel)", command=self.save_all_results, fg_color="#252525").pack(fill="x", padx=10, pady=10)

        self.add_card_label("Compare vs Ref")
        comp_frame = ctk.CTkFrame(self.left_scroll, fg_color="transparent")
        comp_frame.pack(fill="x", padx=10, pady=5)
        
        self.btn_compare = ctk.CTkButton(self.left_scroll, text="1. Find Peaks (Python)", command=self.run_auto_compare, fg_color="#252525")
        self.btn_compare.pack(fill="x", padx=10, pady=(5, 5))
        
        self.btn_ai_compare = ctk.CTkButton(self.left_scroll, text="2. AI Compare", command=self.run_ai_compare, fg_color="#3182F6", state="disabled")
        self.btn_ai_compare.pack(fill="x", padx=10, pady=(0, 20))
        
        ctk.CTkButton(self.left_scroll, text="Batch Compare (All vs Ref)", command=self.batch_compare_all, fg_color="#252525").pack(fill="x", padx=10, pady=(0, 20))
        
        self.lbl_status = ctk.CTkLabel(self.left_scroll, text="Ready", text_color="#8B8B8B")
        self.lbl_status.pack()

        # Edit Mode Variables
        self.edit_mode = None
        self.temp_peak_idx = None
        self.temp_marker = None

    def add_card_label(self, text):
        f = ctk.CTkFrame(self.left_scroll, fg_color="#1E1E1E", corner_radius=6)
        f.pack(fill="x", padx=5, pady=(10, 5))
        ctk.CTkLabel(f, text=text, font=("Segoe UI", 13, "bold"), text_color="white").pack(anchor="w", padx=10, pady=5)

    def create_center_panel(self):
        self.center_frame = ctk.CTkFrame(self.paned_window, corner_radius=0, fg_color="#0A0A0A")
        self.paned_window.add(self.center_frame, minsize=500, stretch="always")
        
        # Layer Bar area
        self.layer_bar = ctk.CTkFrame(self.center_frame, fg_color="transparent", height=40)
        self.layer_bar.pack(side="top", fill="x", padx=10, pady=5)
        
        # [NEW] Reset View button (right-aligned)
        self.btn_reset_view = ctk.CTkButton(self.layer_bar, text="⟲ Reset View", width=100, height=28,
                                            font=("Segoe UI", 12), fg_color="#444444", 
                                            command=self.reset_view_action)
        self.btn_reset_view.pack(side="right", padx=5)

        self.fig, self.ax = plt.subplots(figsize=(8, 5))
        self.fig.patch.set_facecolor('#1E1E1E') 
        self.ax.set_facecolor('#1E1E1E')
        for spine in self.ax.spines.values(): spine.set_color('white')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.title.set_color('white')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.center_frame)
        self.canvas.draw()
        
        # Add toolbar and set style
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.center_frame)
        self.toolbar.config(background='#303030')
        
        for widget in self.toolbar.winfo_children():
            try:
                widget.config(background='#303030')
                widget.config(activebackground='#3D3D3D')
            except tk.TclError:
                pass
        
        self.toolbar.update()

        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0,10))

        # JV_Analysis.exe-style right-click context menu (zoom/pan already
        # exist here via Ctrl+wheel / Ctrl+drag)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception as _pe:
            print(f"plot interactions skip: {_pe}")

        self.canvas.mpl_connect('pick_event', self.on_pick_event)
        self.canvas.mpl_connect('button_press_event', self.on_canvas_click) 
        # Zoom & Pan Events
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.canvas.mpl_connect('button_press_event', self.on_mouse_press)
        self.canvas.mpl_connect('button_release_event', self.on_mouse_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)

    def create_right_panel(self):
        self.right_frame = ctk.CTkFrame(self.paned_window, width=350, corner_radius=0, fg_color="#141414")
        self.paned_window.add(self.right_frame, minsize=300)
        
        ctk.CTkLabel(self.right_frame, text="Peak Detail (Target Layer)", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
        self.lbl_peak_pos = ctk.CTkLabel(self.right_frame, text="-", text_color="white")
        self.lbl_peak_pos.pack(pady=5)
        
        self.txt_peak_desc = ctk.CTkTextbox(self.right_frame, font=("Segoe UI", 12), fg_color="#252525", text_color="white")
        self.txt_peak_desc.pack(fill="both", expand=True, padx=10, pady=10)

    # ==========================================
    # Logic: Data Load
    # ==========================================
    def load_data(self):
        path = filedialog.askopenfilename(filetypes=[("Data", "*.csv *.xlsx *.txt")])
        if not path: return
        try:
            raw_data = ftir_core.load_data(path)
            self.layers = []
            names = []
            
            for i, d in enumerate(raw_data):
                wn, inte = d['wavenumbers'], d['intensities']
                peaks, indices = ftir_core.detect_peaks(wn, inte)
                
                # Use context name if available
                layer_name = d.get('context', '').strip()
                if not layer_name:
                    layer_name = f"Layer {i+1}"
                
                self.layers.append({
                    'id': i,
                    'name': layer_name,
                    'visible': (i==0),
                    'context': d.get('context', ''),
                    'peak_data': {},
                    'wavenumbers': wn,
                    'intensities': inte,
                    'peaks': peaks,
                    'indices': indices
                })
                names.append(layer_name)

            self.combo_target.configure(values=names)
            self.combo_target.set(names[0])
            self.combo_ref.configure(values=names)
            self.combo_ref.set(names[0])
            
            self.target_layer_idx = 0
            self.ref_layer_idx = 0
            
            # [NEW] force a view reset (fit all) when loading a new file
            self.force_reset_view = True
            
            self.rebuild_layer_buttons()
            self.update_context_entry()
            self.redraw_graph()
            
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def rebuild_layer_buttons(self):
        for btn in self.layer_buttons:
            btn.destroy()
        self.layer_buttons = []
        
        for i in range(len(self.layers)):
            btn = ctk.CTkButton(self.layer_bar, text=str(i+1), width=35, height=28,
                                font=("Segoe UI", 12, "bold"), fg_color="#252525", 
                                command=lambda x=i: self.toggle_layer_visibility(x))
            btn.pack(side="left", padx=3)
            self.layer_buttons.append(btn)
        
        self.update_layer_buttons_color()

    def update_layer_buttons_color(self):
        for i, btn in enumerate(self.layer_buttons):
            is_vis = self.layers[i]['visible']
            color = LAYER_COLORS[i % len(LAYER_COLORS)]
            btn.configure(fg_color=color if is_vis else "#303030", 
                          text_color="white" if is_vis else "#8B8B8B")

    def toggle_layer_visibility(self, idx):
        if idx >= len(self.layers): return
        self.layers[idx]['visible'] = not self.layers[idx]['visible']
        self.update_layer_buttons_color()
        self.redraw_graph()

    def on_target_change(self, event=None):
        name = self.combo_target.get()
        # Fix: Find index by name instead of parsing "Layer X"
        for i, layer in enumerate(self.layers):
            if layer['name'] == name:
                self.target_layer_idx = i
                break
        self.update_context_entry()
        self.redraw_graph()
        
    def on_ref_change(self, event=None):
        name = self.combo_ref.get()
        for i, layer in enumerate(self.layers):
            if layer['name'] == name:
                self.ref_layer_idx = i
                break
        self.redraw_graph()

    def set_target_layer(self, idx):
        focused = self.focus_get()
        if focused and "entry" in focused.winfo_class().lower():
            return
        if not self.layers or idx >= len(self.layers): return
        self.target_layer_idx = idx
        self.combo_target.set(self.layers[idx]['name'])
        self.update_context_entry()
        for i, layer in enumerate(self.layers):
            layer['visible'] = (i == idx)
        self.update_layer_buttons_color()
        self.force_reset_view = True
        self.redraw_graph()

    def update_context_entry(self):
        if not self.layers: return
        ctx = self.layers[self.target_layer_idx]['context']
        self.entry_context.delete(0, tk.END)
        self.entry_context.insert(0, ctx)

    def save_context_info(self, event=None):
        if not self.layers: return
        self.layers[self.target_layer_idx]['context'] = self.entry_context.get()

    # ==========================================
    # Logic: Graphing (modified)
    # ==========================================
    def reset_view_action(self, event=None):
        """Reset view and redraw the plot"""
        if event:
            focused = self.focus_get()
            if focused and ("entry" in focused.winfo_class().lower() or "text" in focused.winfo_class().lower()):
                return
        self.force_reset_view = True
        self.redraw_graph()

    def redraw_graph(self):
        # [NEW] save current view state (axis ranges)
        # Save only when not the initial load and layers exist
        saved_xlim = None
        saved_ylim = None
        if not self.is_initial_load and self.layers and not self.force_reset_view:
             saved_xlim = self.ax.get_xlim()
             saved_ylim = self.ax.get_ylim()

        self.ax.clear()
        self.ax.set_title("FTIR Spectrum", color='white', fontsize=14, fontweight='bold')
        self.ax.set_xlabel("Wavenumber (cm-1)", color='white', fontsize=12)
        self.ax.set_ylabel("Transmittance", color='white', fontsize=12)
        self.ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.3)
        self.ax.tick_params(axis='both', which='major', labelsize=10)

        if not self.layers: 
            self.canvas.draw()
            return

        layers_to_draw = []
        
        if self.compare_mode:
            idx_a = self.target_layer_idx
            idx_b = self.ref_layer_idx
            
            alpha_a = 1.0 if self.compare_step in [0, 1] else 0.6
            alpha_b = 1.0 if self.compare_step in [0, 2] else 0.6
            
            focus_a = (self.compare_step == 1)
            focus_b = (self.compare_step == 2)
            
            layers_to_draw.append((idx_a, alpha_a, focus_a))
            layers_to_draw.append((idx_b, alpha_b, focus_b))
        else:
            for i, L in enumerate(self.layers):
                if L['visible']:
                    # Highlight Target and Reference
                    is_target = (i == self.target_layer_idx)
                    is_ref = (i == self.ref_layer_idx)
                    alpha = 1.0 if is_target else (0.8 if is_ref else 0.4)
                    layers_to_draw.append((i, alpha, is_target))

        for idx, alpha, is_target in layers_to_draw:
            if idx >= len(self.layers): continue
            L = self.layers[idx]
            c = LAYER_COLORS[idx % len(LAYER_COLORS)]
            
            label = L['name']
            if idx == self.ref_layer_idx: label += " (Ref)"
            
            style = '--' if idx == self.ref_layer_idx else '-'
            self.ax.plot(L['wavenumbers'], L['intensities'], color=c, alpha=alpha, label=label, linestyle=style)
            
            picker = 5 if (is_target or self.compare_mode) else False
            
            if is_target:
                m_size = 8
                m_style = "v"
                for px, py in zip(L['peaks'], L['intensities'][L['indices']]):
                    self.ax.annotate(f"{px:.0f}", xy=(px, py), xytext=(0, -10), textcoords='offset points', ha='center', va='top', color=c, fontsize=10, fontweight='bold')
            else:
                m_size = 4
                m_style = "."
            
            self.ax.plot(L['peaks'], L['intensities'][L['indices']], 
                         m_style, color='white', markeredgecolor=c, 
                         markersize=m_size, alpha=alpha, picker=picker)

        if self.compare_mode:
            if self.compare_peaks[0] is not None:
                self.draw_highlight(self.target_layer_idx, self.compare_peaks[0], 'cyan')
            if self.compare_peaks[1] is not None:
                self.draw_highlight(self.ref_layer_idx, self.compare_peaks[1], 'magenta')
        elif self.current_peak_idx != -1:
             L = self.layers[self.target_layer_idx]
             if self.current_peak_idx < len(L['peaks']):
                 self.draw_highlight(self.target_layer_idx, L['peaks'][self.current_peak_idx], 'yellow')

        # [NEW] restore view state
        if saved_xlim and saved_ylim:
            self.ax.set_xlim(saved_xlim)
            self.ax.set_ylim(saved_ylim)
        elif self.force_reset_view:
            self.ax.autoscale(True)
            self.ax.margins(0.05)  # Add margin to avoid tight view
            # [FIX] FTIR Standard: High Wavenumber -> Low Wavenumber (Left -> Right)
            # Ensure x-axis is inverted
            xlim = self.ax.get_xlim()
            if xlim[0] < xlim[1]:
                self.ax.set_xlim(xlim[1], xlim[0])
            
        # Reset flag
        self.force_reset_view = False
        self.is_initial_load = False

        # [FIX] Prevent graph clipping
        self.fig.tight_layout()
        self.canvas.draw()

    def draw_highlight(self, layer_idx, wn, color):
        L = self.layers[layer_idx]
        idx = (np.abs(L['wavenumbers'] - wn)).argmin()
        self.ax.plot(L['wavenumbers'][idx], L['intensities'][idx], 'o', ms=15, mfc='none', mec=color, mew=2)

    # ==========================================
    # Logic: Analysis & Info
    # ==========================================
    def analyze_target_thread(self):
        if not self.layers: return
        if not self.api_key_var.get():
            messagebox.showerror("Error", "API Key required")
            return
        
        AIConfigDialog(self, self.api_key_var.get(), self.start_ai_thread)

    def start_ai_thread(self, model, context):
        threading.Thread(target=self._run_analysis, args=(self.api_key_var.get(), model, context), daemon=True).start()
        self.show_loading()

    def _run_analysis(self, api_key, model, context):
        try:
            idx = self.target_layer_idx
            L = self.layers[idx]
            
            # Request English output and other possibilities via context injection
            # (the old "[OUTPUT: Korean]" here silently overrode the English
            # instruction inside ftir_core's prompt)
            req_context = context + "\n[OUTPUT: English]\n[INCLUDE: 'other_possibilities' if applicable]"
            results = ftir_core.analyze_with_gemini(
                api_key, model, req_context,
                L['peaks'], L['indices'], L['intensities']
            )
            
            for item in results:
                # Store result. Note: Gemini might return slightly different float values.
                # We store using the returned wavenumber.
                L['peak_data'][item.get("wavenumber", 0)] = item
                
            self.after(0, lambda: self.finish_analysis(idx, len(results)))
        except Exception as e:
            err_msg = str(e)
            if self.winfo_exists():
                self.after(0, lambda: messagebox.showerror("Error", err_msg) if self.winfo_exists() else None)
                self.after(0, lambda: self.hide_loading() if self.winfo_exists() else None)

    def finish_analysis(self, idx, count):
        self.hide_loading()
        L = self.layers[idx]
        
        # Select first peak and show details immediately
        if len(L['peaks']) > 0:
            self.current_peak_idx = 0
            self.redraw_graph()
            self.show_peak_info(L['peaks'][0])
            
        # [MODIFIED] Large ResultPopup removed. Simple notification added.
        messagebox.showinfo("Analysis Complete", f"Analyzed {count} peaks for {self.layers[idx]['name']}.")

    def analyze_single_peak_thread(self):
        """Show info for the currently selected peak (triggered by a canvas click).
        If the peak was already AI-analyzed, its stored info is shown; otherwise
        just the peak position is displayed. No AI re-call, so it never blocks."""
        if not self.layers:
            return
        L = self.layers[self.target_layer_idx]
        if self.current_peak_idx < 0 or self.current_peak_idx >= len(L['peaks']):
            return
        wn = L['peaks'][self.current_peak_idx]
        self.show_peak_info(wn)

    def finish_single_analysis(self, idx, wn):
        self.hide_loading()
        self.redraw_graph()
        self.show_peak_info(wn)
        messagebox.showinfo("Analysis Complete", "Single peak analysis finished.")

    def show_peak_list(self):
        if not self.layers: return
        L = self.layers[self.target_layer_idx]
        if not L['peak_data']:
            messagebox.showinfo("Info", "No analysis data yet. Please run 'Analyze Target Peaks' first.")
            return
        PeakListPopup(self, L['name'], L['peak_data'])

    def save_all_results(self):
        if not self.layers: return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx")
        if path:
            if ftir_core.save_all_layers_to_excel(path, self.layers):
                messagebox.showinfo("Saved", "All layer data saved to Excel.")
            else:
                messagebox.showwarning("Empty", "No analysis data found to save.")

    def plot_to_origin(self):
        if not self.layers:
            messagebox.showwarning("Warning", "Load data first.")
            return
        self.btn_origin.configure(state="disabled")
        threading.Thread(target=self._origin_thread, daemon=True).start()

    def _origin_thread(self):
        try:
            self.after(0, lambda: self.lbl_status.configure(text="Connecting to Origin..."))
            origin = ftir_core.connect_to_origin(self.origin_path, 
                                                 log_callback=lambda msg: self.after(0, lambda m=msg: self.lbl_status.configure(text=m)))
            if origin:
                ftir_core.plot_ftir_to_origin(origin, self.layers, colors=LAYER_COLORS,
                                              log_callback=lambda msg: self.after(0, lambda m=msg: self.lbl_status.configure(text=m)))
            else:
                self.after(0, lambda: messagebox.showerror("Error", "Could not connect to Origin."))
        except Exception as e:
            self.after(0, lambda err=str(e): messagebox.showerror("Error", f"Origin Error: {err}"))
        finally:
            self.after(0, lambda: self.btn_origin.configure(state="normal"))

    # ==========================================
    # Logic: Interaction
    # ==========================================
    def on_pick_event(self, event):
        if self.compare_mode: return
        ind = event.ind[0]
        L = self.layers[self.target_layer_idx]
        
        if self.edit_mode == 'delete':
            if ind < len(L['peaks']):
                # Delete peak
                wn = L['peaks'][ind]
                L['peaks'] = np.delete(L['peaks'], ind)
                L['indices'] = np.delete(L['indices'], ind)
                # Remove from peak_data if exists
                if wn in L['peak_data']:
                    del L['peak_data'][wn]
                self.redraw_graph()
            return

        if ind < len(L['peaks']):
            self.current_peak_idx = ind
            self.redraw_graph()
            self.show_peak_info(L['peaks'][ind])

    def show_peak_info(self, wn):
        L = self.layers[self.target_layer_idx]
        
        # [MODIFIED] Fuzzy Matching for Float Keys
        # Direct lookup usually fails due to small floating point differences 
        # between detected peaks and JSON response.
        info = L['peak_data'].get(wn)
        
        if not info and L['peak_data']:
            # Find closest key within 2.0 cm-1 tolerance
            closest_wn = None
            min_diff = 2.0
            for k in L['peak_data'].keys():
                diff = abs(k - wn)
                if diff < min_diff:
                    min_diff = diff
                    closest_wn = k
            
            if closest_wn is not None:
                info = L['peak_data'][closest_wn]
        
        self.lbl_peak_pos.configure(text=f"Pos: {wn:.1f} cm-1")
        self.txt_peak_desc.configure(state="normal")
        self.txt_peak_desc.delete("1.0", "end")
        
        if info:
            text = f"- Material: {info.get('material', '-')}\n\n"
            text += f"- Assignment: {info.get('assignment', '-')}\n\n"
            text += f"- Description: {info.get('description', '-')}\n"
            
            if info.get('other_possibilities'):
                text += f"\n- Other Possibilities: {info.get('other_possibilities')}\n"
            
            self.txt_peak_desc.insert("1.0", text)
        else:
            self.txt_peak_desc.insert("1.0", "No analysis data.")
        self.txt_peak_desc.configure(state="disabled")

    # ==========================================
    # Logic: Comparison
    # ==========================================
    def run_auto_compare(self):
        """Automatically compare Target vs Ref using detected peaks"""
        if not self.layers: return
        
        if self.target_layer_idx == self.ref_layer_idx:
            messagebox.showwarning("Warning", "Target and Reference are the same layer.")
            return

        # [STEP 1] Python-based Peak Finding (Refresh Peaks)
        self.lbl_status.configure(text="Finding Peaks (Python)...")
        self.update_idletasks()
        
        try:
            for idx in [self.target_layer_idx, self.ref_layer_idx]:
                L = self.layers[idx]
                # Re-detect peaks using core logic
                peaks, indices = ftir_core.detect_peaks(L['wavenumbers'], L['intensities'])
                L['peaks'] = peaks
                L['indices'] = indices
            
            # Enable Compare Mode for visualization
            self.compare_mode = True
            self.compare_step = 2 # Skip manual selection steps
            self.compare_indices = [self.target_layer_idx, self.ref_layer_idx]
            
            self.redraw_graph()
            self.lbl_status.configure(text="Peaks found. Ready for AI.")
            self.btn_ai_compare.configure(state="normal")
        except Exception as e:
            print(f"Peak detection error: {e}")
            self.lbl_status.configure(text="Error finding peaks")

    def run_ai_compare(self):
        self.run_compare_thread()

    def on_canvas_click(self, event):
        if self.toolbar.mode != "": return
        if event.key == 'control': return 
        if event.inaxes != self.ax: return
        
        if self.edit_mode == 'add':
            L = self.layers[self.target_layer_idx]
            idx = (np.abs(L['wavenumbers'] - event.xdata)).argmin()
            self.temp_peak_idx = idx
            self.draw_temp_marker()
            return

    def on_enter_press(self, event):
        if self.edit_mode == 'add' and self.temp_peak_idx is not None:
            L = self.layers[self.target_layer_idx]
            new_idx = self.temp_peak_idx
            new_wn = L['wavenumbers'][new_idx]
            
            if new_idx not in L['indices']:
                L['indices'] = np.append(L['indices'], new_idx)
                sort_mask = np.argsort(L['indices'])
                L['indices'] = L['indices'][sort_mask]
                L['peaks'] = L['wavenumbers'][L['indices']]
                
                self.cleanup_temp_marker()
                self.redraw_graph()
            return

        # [NEW] Single Peak Analysis Trigger (Normal Mode)
        if self.edit_mode is None and self.layers and self.current_peak_idx != -1:
             self.analyze_single_peak_thread()

    def run_compare_thread(self):
        self.btn_ai_compare.configure(text="Analyzing...", fg_color="#252525")
        api_key = self.api_key_var.get()
        model = self.model_var.get()
        threading.Thread(target=self._run_compare, args=(api_key, model), daemon=True).start()
        self.show_loading()

    def _run_compare(self, api_key, model):
        try:
            idx_a = self.target_layer_idx
            idx_b = self.ref_layer_idx
            L_a, L_b = self.layers[idx_a], self.layers[idx_b]
            
            # Build context including Sample Info from both layers
            combined_context = f"Sample A ({L_a['name']}) Info: {L_a['context']}\nSample B ({L_b['name']}) Info: {L_b['context']}"
            
            # [MODIFIED] Use automated comparison of peak lists
            res = ftir_core.compare_spectra_with_gemini(
                api_key, model, 
                combined_context, 
                L_a['name'], L_a['peaks'], L_a['intensities'][L_a['indices']],
                L_b['name'], L_b['peaks'], L_b['intensities'][L_b['indices']]
            )
            self.after(0, lambda: self.show_compare_result(res))
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error", err_msg))
            self.after(0, self.hide_loading)

    def show_compare_result(self, res):
        self.hide_loading()
        self.btn_ai_compare.configure(text="2. AI Compare", fg_color="#3182F6", text_color="white")
        self.lbl_status.configure(text="Ready")
        
        # Format JSON result to text
        content = f"■ Summary:\n{res.get('summary', '-')}\n\n"
        content += "■ Key Differences:\n"
        for diff in res.get('differences', []):
            content += f"- {diff}\n"
        content += f"\n■ Chemical Implications:\n{res.get('chemical_implications', '-')}\n\n"
        content += f"■ Conclusion:\n{res.get('conclusion', '-')}"
        
        ResultPopup(self, "Comparison Result", content, save_data=res)
        
    def batch_compare_all(self):
        if not self.layers: return
        ref_layer = self.layers[self.ref_layer_idx]
        msg = f"Batch comparing all layers against {ref_layer['name']}...\n(Feature placeholder)"
        messagebox.showinfo("Info", msg)

    def get_idx(self, combo):
        return int(combo.get().split(" ")[1]) - 1
    def show_loading(self):
        if not self.loading_popup: self.loading_popup = LoadingPopup(self)
    def hide_loading(self):
        if self.loading_popup:
            self.loading_popup.destroy()
            self.loading_popup = None
    def on_esc_press(self, e):
        if self.edit_mode:
            self.edit_mode = None
            self.cleanup_temp_marker()
            self.update_mode_ui()
        self.compare_mode = False
        self.redraw_graph()

    # ==========================================
    # Logic: Editing
    # ==========================================
    def toggle_add_mode(self):
        if self.edit_mode == 'add':
            self.edit_mode = None
            self.cleanup_temp_marker()
        else:
            self.edit_mode = 'add'
            self.compare_mode = False
        self.update_mode_ui()

    def toggle_delete_mode(self):
        if self.edit_mode == 'delete':
            self.edit_mode = None
        else:
            self.edit_mode = 'delete'
            self.compare_mode = False
            self.cleanup_temp_marker()
        self.update_mode_ui()

    def update_mode_ui(self):
        self.btn_add.configure(fg_color="#10B981" if self.edit_mode == 'add' else "#8B8B8B")
        self.btn_del.configure(fg_color="#EF4444" if self.edit_mode == 'delete' else "#8B8B8B")
        
        if self.edit_mode == 'add':
            self.lbl_edit_status.configure(text="Click graph to add peak (Arrow keys to adjust, Enter to save)", text_color="#10B981")
        elif self.edit_mode == 'delete':
            self.lbl_edit_status.configure(text="Click peak marker to delete", text_color="#EF4444")
        else:
            self.lbl_edit_status.configure(text="Ready", text_color="#8B8B8B")

    def on_key_press(self, event):
        if self.edit_mode == 'add' and self.temp_peak_idx is not None:
            L = self.layers[self.target_layer_idx]
            if event.keysym == 'Left':
                if self.temp_peak_idx < len(L['wavenumbers']) - 1:
                    self.temp_peak_idx += 1
            elif event.keysym == 'Right':
                if self.temp_peak_idx > 0:
                    self.temp_peak_idx -= 1
            self.draw_temp_marker()
            return

        # Navigation Logic (Normal Mode)
        if self.edit_mode is None and not self.compare_mode and self.layers:
            L = self.layers[self.target_layer_idx]
            if len(L['peaks']) > 0:
                if event.keysym == 'Right':
                    self.current_peak_idx = (self.current_peak_idx + 1) % len(L['peaks'])
                    self.redraw_graph()
                    self.show_peak_info(L['peaks'][self.current_peak_idx])
                elif event.keysym == 'Left':
                    self.current_peak_idx = (self.current_peak_idx - 1) % len(L['peaks'])
                    self.redraw_graph()
                    self.show_peak_info(L['peaks'][self.current_peak_idx])

    def draw_temp_marker(self):
        if self.temp_marker: self.temp_marker.remove()
        L = self.layers[self.target_layer_idx]
        x = L['wavenumbers'][self.temp_peak_idx]
        y = L['intensities'][self.temp_peak_idx]
        
        is_dip = False
        idx = self.temp_peak_idx
        if 0 < idx < len(L['intensities']) - 1:
            if L['intensities'][idx] < L['intensities'][idx-1] and L['intensities'][idx] < L['intensities'][idx+1]:
                is_dip = True
        
        color = '#00FF00' if is_dip else '#FF00FF' 
        marker = 'v' if is_dip else 'x'
        
        self.temp_marker, = self.ax.plot(x, y, marker=marker, color=color, ms=12, markeredgewidth=2)
        self.lbl_edit_status.configure(text=f"Pos: {x:.1f} | Int: {y:.4f} | {'Dip (Peak)' if is_dip else 'Point'}", text_color=color)
        self.canvas.draw()

    def cleanup_temp_marker(self):
        if self.temp_marker:
            self.temp_marker.remove()
            self.temp_marker = None
        self.temp_peak_idx = None
        self.canvas.draw()

    # ==========================================
    # Logic: Zoom & Pan
    # ==========================================
    def on_scroll(self, event):
        if event.key != 'control': return
        if event.inaxes != self.ax: return
        base_scale = 1.2
        if event.button == 'up': scale = 1/base_scale
        elif event.button == 'down': scale = base_scale
        else: return
        
        cur_xlim = self.ax.get_xlim()
        xdata = event.xdata
        self.ax.set_xlim([xdata - (xdata - cur_xlim[0]) * scale, xdata + (cur_xlim[1] - xdata) * scale])
        
        cur_ylim = self.ax.get_ylim()
        ydata = event.ydata
        self.ax.set_ylim([ydata - (ydata - cur_ylim[0]) * scale, ydata + (cur_ylim[1] - ydata) * scale])
        
        self.canvas.draw_idle()

    def on_mouse_press(self, event):
        if event.button == 1 and event.key == 'control':
             bbox = self.ax.get_window_extent()
             # Click inside the graph: Pan mode
             if event.inaxes == self.ax:
                 self.pan_start = dict(mode='pan', x=event.x, y=event.y, xlim=self.ax.get_xlim(), ylim=self.ax.get_ylim())
             # Click below the graph (X-axis area): X-axis zoom mode
             elif bbox.x0 <= event.x <= bbox.x1 and event.y < bbox.y0:
                 self.pan_start = dict(mode='x_zoom', x=event.x, y=event.y, xlim=self.ax.get_xlim(), ylim=self.ax.get_ylim())

    def on_mouse_release(self, event):
        self.pan_start = None

    def on_mouse_move(self, event):
        if self.pan_start:
             dx = event.x - self.pan_start['x']
             
             if self.pan_start['mode'] == 'pan' and event.inaxes == self.ax:
                 dy = event.y - self.pan_start['y']
                 bbox = self.ax.get_window_extent()
                 xlim = self.pan_start['xlim']
                 scale_x = (xlim[1] - xlim[0]) / bbox.width
                 self.ax.set_xlim(xlim[0] - dx * scale_x, xlim[1] - dx * scale_x)
                 
                 ylim = self.pan_start['ylim']
                 scale_y = (ylim[1] - ylim[0]) / bbox.height
                 self.ax.set_ylim(ylim[0] - dy * scale_y, ylim[1] - dy * scale_y)
                 self.canvas.draw_idle()
                 
             elif self.pan_start['mode'] == 'x_zoom':
                 scale_factor = 1.0 - (dx / 300.0)
                 cur_xlim = self.pan_start['xlim']
                 center = (cur_xlim[0] + cur_xlim[1]) / 2
                 half_range = (cur_xlim[1] - cur_xlim[0]) / 2
                 new_half_range = half_range * scale_factor
                 self.ax.set_xlim(center - new_half_range, center + new_half_range)
                 self.canvas.draw_idle()

if __name__ == "__main__":
    root = ctk.CTk()
    AnalysisWindow(root, "", "")
    root.mainloop()
