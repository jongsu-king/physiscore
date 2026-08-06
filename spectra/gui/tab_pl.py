# gui/tab_pl.py
# PL Analysis Tab - Multi-layer support with Quenching Efficiency
# (FIX: removed pack/grid mixing -> avoid recursion depth)

from __future__ import annotations
import os
import threading
from typing import Optional, List, Dict

import numpy as np
import pandas as pd
import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from tkinter import filedialog, messagebox

from spectra.core.config import PipelineConfig
from spectra.core.utils import safe_sorted_xy, robust_read_csv
from spectra.pipelines.run_pl import run_pl_pipeline
from spectra.core.report import generate_ai_peak_report


def _resolve_api_key() -> str | None:
    """Resolve Gemini API key from environment or config file."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
        cfg_path = os.path.join(project_root, "physisfera_config.json")
        if os.path.exists(cfg_path):
            import json
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("gemini_api_key") or data.get("GEMINI_API_KEY")
            if key:
                os.environ.setdefault("GEMINI_API_KEY", key)
                os.environ.setdefault("GOOGLE_API_KEY", key)
                return key
    except Exception:
        pass
    return None

# Theme
COL_BG = "#0b0f16"
COL_CARD = "#0f1520"
COL_STROKE = "#1e2a3a"
COL_TXT = "#e8eefc"
COL_MUT = "#9fb0c7"
COL_ACC = "#2b7fff"
COL_OK = "#3ee089"
COL_ERR = "#ff4d4d"

COLORS = ["#3182F6", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#06B6D4", "#F97316", "#14B8A6"]


class PLAnalysisTab(ctk.CTkFrame):
    def __init__(self, master, defaults: PipelineConfig):
        super().__init__(master, fg_color=COL_BG)
        self.cfg_default = defaults

        # Multi-layer data
        self.file_path: Optional[str] = None
        self.df: Optional[pd.DataFrame] = None
        self.layers: List[Dict] = []
        self.selected_layers: List[int] = []
        self.ref_layer_idx: Optional[int] = None

        # Layer Mode
        self.var_layer_mode = ctk.StringVar(value="Bulk")

        # Gemini AI - Load API key
        api_key = _resolve_api_key()
        use_gemini = bool(api_key) and getattr(self.cfg_default, "use_gemini", False)
        self.var_use_gemini = ctk.IntVar(value=1 if use_gemini else 0)
        self.var_model = ctk.StringVar(value=getattr(self.cfg_default, "gemini_model", "gemini-2.5-flash"))
        self._gemini_api_key = api_key

        self._build_layout()
        self._plot_empty()

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # LEFT panel
        self.left = ctk.CTkScrollableFrame(self, width=320, fg_color="transparent")
        self.left.grid(row=0, column=0, sticky="nsew", padx=(12, 10), pady=12)
        self.left.grid_columnconfigure(0, weight=1)

        self._build_actions()
        self._build_params()
        self._build_status()

        # CENTER panel
        self.center = ctk.CTkFrame(self, fg_color="transparent")
        self.center.grid(row=0, column=1, sticky="nsew", padx=10, pady=12)
        self.center.grid_rowconfigure(1, weight=1)
        self.center.grid_columnconfigure(0, weight=1)

        self._build_plot()

        # RIGHT panel
        self.right = ctk.CTkFrame(self, fg_color="transparent", width=280)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(10, 12), pady=12)
        self.right.grid_rowconfigure(1, weight=1)

        self._build_summary()
        self._build_log()

    def _card(self, parent, title):
        card = ctk.CTkFrame(parent, fg_color=COL_CARD, corner_radius=16, border_width=1, border_color=COL_STROKE)
        hdr = ctk.CTkFrame(card, fg_color="transparent", height=32)
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(hdr, text=title, text_color=COL_TXT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        return card, body

    def _build_actions(self):
        card, body = self._card(self.left, "Actions")
        card.pack(fill="x", pady=(0, 12))
        body.grid_columnconfigure(0, weight=1)

        self.btn_load = ctk.CTkButton(body, text="📂 Load Data", command=self._load_file, fg_color=COL_ACC, height=36)
        self.btn_load.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.btn_run = ctk.CTkButton(
            body, text="▶ RUN",
            command=self._run_analysis,
            fg_color="#e53935", hover_color="#c62828",
            height=40
        )
        self.btn_run.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.btn_run.configure(state="disabled")

        # Export
        self.btn_export = ctk.CTkButton(body, text="💾 Export Excel", command=self._export_excel, fg_color="gray", height=36)
        self.btn_export.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.btn_export.configure(state="disabled")

        # AI options
        ai_row = ctk.CTkFrame(body, fg_color="transparent")
        ai_row.grid(row=3, column=0, sticky="ew", pady=(6, 6))
        ai_row.grid_columnconfigure(1, weight=1)

        self.chk_ai = ctk.CTkCheckBox(ai_row, text="Gemini AI", variable=self.var_use_gemini, onvalue=1, offvalue=0)
        self.chk_ai.grid(row=0, column=0, sticky="w")

        self.ent_ai_model = ctk.CTkEntry(ai_row)
        self.ent_ai_model.insert(0, self.var_model.get())
        self.ent_ai_model.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.btn_ai = ctk.CTkButton(body, text="🤖 AI Comment", command=self._ai_comment, fg_color=COL_ACC, height=36)
        self.btn_ai.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.btn_ai.configure(state="disabled")

    def _build_params(self):
        card, body = self._card(self.left, "Analysis Settings")
        card.pack(fill="x", pady=(0, 12))
        body.grid_columnconfigure(0, weight=1)

        # Layer Mode
        ctk.CTkLabel(body, text="Layer Mode", text_color=COL_TXT, font=ctk.CTkFont(weight="bold")).pack(fill="x", pady=(0, 4))
        mode_frame = ctk.CTkFrame(body, fg_color="transparent")
        mode_frame.pack(fill="x", pady=(0, 8))
        ctk.CTkRadioButton(mode_frame, text="Bulk", variable=self.var_layer_mode, value="Bulk", command=self._on_layer_mode).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(mode_frame, text="Interface", variable=self.var_layer_mode, value="Interface", command=self._on_layer_mode).pack(side="left")

        # Layer selection checkboxes
        ctk.CTkLabel(body, text="Select Layers:", text_color=COL_MUT, font=ctk.CTkFont(size=11)).pack(fill="x", pady=(8, 4))
        self.layer_selection_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.layer_selection_frame.pack(fill="x", pady=(0, 8))

        # Reference selector (FIX: use pack only, no grid_remove)
        ctk.CTkLabel(body, text="Reference Sample:", text_color=COL_MUT, font=ctk.CTkFont(size=11)).pack(fill="x", pady=(8, 4))
        self.ref_selector_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.ref_selector_frame.pack(fill="x")
        self.ref_selector_frame.pack_forget()  # hidden by default

        self.ref_column_menu = ctk.CTkOptionMenu(
            self.ref_selector_frame,
            values=["Load data first"],
            command=self._on_ref_column_change,
            fg_color=COL_ACC
        )
        self.ref_column_menu.pack(fill="x")

    def _on_layer_mode(self):
        # FIX: toggle with pack / pack_forget only
        if self.var_layer_mode.get() == "Interface" and self.layers:
            self.ref_selector_frame.pack(fill="x")
        else:
            self.ref_selector_frame.pack_forget()

    def _on_ref_column_change(self, choice):
        if choice and self.layers:
            for i, layer in enumerate(self.layers):
                if layer["name"] == choice:
                    self.ref_layer_idx = i
                    self._log(f"✓ Reference set: {choice}")
                    if any((l.get("fitted") is not None and not l.get("fitted").empty) for l in self.layers):
                        self._calc_bandgap_plqe()
                        self._update_summary()
                        self._plot()
                    break

    def _build_status(self):
        card, body = self._card(self.left, "Status")
        card.pack(fill="x", pady=(0, 12))
        self.lbl_status = ctk.CTkLabel(body, text="Ready", text_color=COL_MUT, anchor="w")
        self.lbl_status.pack(fill="x")

    def _build_plot(self):
        title_bar = ctk.CTkFrame(self.center, fg_color="transparent")
        title_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        title_bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_bar, text="PL Spectrum", text_color=COL_TXT, font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w")

        plot_card = ctk.CTkFrame(self.center, fg_color=COL_CARD, corner_radius=16, border_width=1, border_color=COL_STROKE)
        plot_card.grid(row=1, column=0, sticky="nsew")
        plot_card.grid_rowconfigure(0, weight=1)
        plot_card.grid_columnconfigure(0, weight=1)

        self.fig = Figure(figsize=(7, 5), dpi=100)
        self.fig.patch.set_facecolor(COL_CARD)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_card)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

    def _build_summary(self):
        card, body = self._card(self.right, "Summary")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.summary_frame = ctk.CTkScrollableFrame(body, fg_color=COL_CARD, height=200)
        self.summary_frame.pack(fill="both", expand=True)

    def _build_log(self):
        card, body = self._card(self.right, "Log")
        card.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(body, fg_color=COL_CARD, height=200, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _log(self, msg: str):
        # Thread-safe logging: _log is used as log_cb inside pipeline worker
        # threads. The old direct insert + update_idletasks() from a worker
        # thread is a classic intermittent tkinter crash/freeze.
        def _append():
            try:
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _append()
            self.update_idletasks()
        else:
            try:
                self.after(0, _append)
            except Exception:
                pass

    def _plot_empty(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111, facecolor=COL_CARD)
        ax.axis("off")
        ax.text(0.5, 0.5, "Please Load Data", ha="center", va="center", color=COL_MUT, fontsize=14)
        self.canvas.draw()

    def _plot(self):
        if not self.layers:
            self._plot_empty()
            return

        self.fig.clear()
        ax = self.fig.add_subplot(111, facecolor=COL_CARD)
        ax.grid(True, color=COL_STROKE, linestyle="--", linewidth=0.5, alpha=0.5)

        if self.var_layer_mode.get() == "Interface" and self.ref_layer_idx is not None:
            if 0 <= self.ref_layer_idx < len(self.layers):
                ref_layer = self.layers[self.ref_layer_idx]
                ax.plot(ref_layer["x"], ref_layer["y"], color="#ffffff", alpha=0.25, ls="--", lw=1.2, label=f"Ref: {ref_layer['name']}")

        for i, layer in enumerate(self.layers):
            if i not in self.selected_layers:
                continue

            color = COLORS[i % len(COLORS)]
            proc = layer.get("proc")

            if proc is not None and not proc.empty:
                if "y_raw" in proc.columns:
                    ax.plot(proc["x"], proc["y_raw"], color=color, alpha=0.3, lw=1, label=f"{layer['name']} (raw)")
                if "y_corr" in proc.columns:
                    ax.plot(proc["x"], proc["y_corr"], color=color, lw=2, label=f"{layer['name']} (corrected)")
                if "baseline" in proc.columns:
                    ax.plot(proc["x"], proc["baseline"], color=color, ls="--", lw=0.8, alpha=0.5)
            else:
                ax.plot(layer["x"], layer["y"], color=color, lw=1.5, label=layer["name"])

            fitted = layer.get("fitted")
            if fitted is not None and not fitted.empty:
                for _, row in fitted.iterrows():
                    if "center" in row:
                        ax.axvline(row["center"], color=color, ls=":", lw=1, alpha=0.7)

        ax.set_xlabel("Wavelength (nm)", color=COL_TXT, fontsize=11)
        ax.set_ylabel("Intensity (a.u.)", color=COL_TXT, fontsize=11)
        ax.tick_params(colors=COL_TXT, labelsize=9)
        ax.spines["bottom"].set_color(COL_STROKE)
        ax.spines["left"].set_color(COL_STROKE)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            by_label = dict(zip(labels, handles))
            ax.legend(by_label.values(), by_label.keys(), loc="upper right", fontsize=8, framealpha=0.9, facecolor=COL_CARD)

        self.canvas.draw()

    def _load_file(self):
        path = filedialog.askopenfilename(title="Load PL Data", filetypes=[("CSV/Excel", "*.csv *.xlsx"), ("All", "*.*")])
        if not path:
            return

        try:
            if path.endswith(".xlsx"):
                xl_file = pd.ExcelFile(path)
                sheet_names = xl_file.sheet_names

                target_sheet = None
                for sname in sheet_names:
                    if "pl" in sname.lower():
                        target_sheet = sname
                        break
                if target_sheet is None:
                    target_sheet = sheet_names[0]

                self.df = pd.read_excel(path, sheet_name=target_sheet)
                self._log(f"Loaded sheet: {target_sheet}")
            else:
                # robust: handles instrument exports with metadata preamble
                self.df = robust_read_csv(path)

            self.df = self.df.apply(pd.to_numeric, errors="coerce").dropna()
            if self.df.shape[1] < 2:
                raise ValueError("At least 2 columns required")

            self.layers = []
            x_col = self.df.columns[0]

            for i, col in enumerate(self.df.columns[1:]):
                x_data = self.df[x_col].values
                y_data = self.df[col].values
                x_sorted, y_sorted = safe_sorted_xy(x_data, y_data)
                layer_name = str(col) if "Unnamed" not in str(col) else f"Layer {i+1}"

                self.layers.append({
                    "name": layer_name,
                    "x": x_sorted,
                    "y": y_sorted,
                    "proc": None,
                    "fitted": None,
                })

            self.selected_layers = list(range(len(self.layers)))
            self._update_layer_selection_ui()

            if len(self.layers) > 1:
                layer_names = [layer["name"] for layer in self.layers]
                self.ref_column_menu.configure(values=layer_names)
                self.ref_column_menu.set(layer_names[-1])
                self.ref_layer_idx = len(self.layers) - 1

            self.file_path = path
            self.btn_run.configure(state="normal")
            self.lbl_status.configure(text=f"Loaded: {os.path.basename(path)}", text_color=COL_OK)
            self._log(f"✓ Loaded {len(self.layers)} layers")
            self._on_layer_mode()
            self._plot()

        except Exception as e:
            messagebox.showerror("Load Error", str(e))
            self.lbl_status.configure(text="Load failed", text_color=COL_ERR)
            self._log(f"✗ Error: {e}")

    def _update_layer_selection_ui(self):
        for widget in self.layer_selection_frame.winfo_children():
            widget.destroy()
        if not self.layers:
            return

        for i, layer in enumerate(self.layers):
            var = ctk.BooleanVar(value=(i in self.selected_layers))
            cb = ctk.CTkCheckBox(
                self.layer_selection_frame,
                text=layer["name"],
                variable=var,
                command=lambda idx=i, v=var: self._on_layer_select(idx, v)
            )
            cb.pack(anchor="w", pady=2)

    def _on_layer_select(self, idx: int, var):
        if var.get():
            if idx not in self.selected_layers:
                self.selected_layers.append(idx)
        else:
            if idx in self.selected_layers:
                self.selected_layers.remove(idx)
        self._plot()

    def _validate_data(self) -> bool:
        if not self.layers:
            messagebox.showerror("Error", "Load Excel data first.")
            return False
        if not self.selected_layers:
            messagebox.showerror("Error", "Select at least one layer to analyze.")
            return False
        if self.var_layer_mode.get() == "Interface":
            if self.ref_layer_idx is None or self.ref_layer_idx >= len(self.layers):
                messagebox.showerror("Error", "Specify a reference layer.")
                return False
        return True

    def _run_analysis(self):
        if not self._validate_data():
            return

        def task():
            try:
                self.lbl_status.configure(text="Running...", text_color="#ffb020")
                self._log("Starting PL analysis...")

                cfg = PipelineConfig(technique="PL", sg_window=31, sg_poly=3, als_lam=1e5, als_p=0.01)

                outdir_base = os.path.splitext(self.file_path)[0] + "_PL_output"
                os.makedirs(outdir_base, exist_ok=True)

                for i in self.selected_layers:
                    layer = self.layers[i]
                    layer_name = layer["name"]
                    self._log(f"Processing {layer_name}...")

                    outdir = os.path.join(outdir_base, f"{i+1}_{layer_name.replace(' ', '_')}")
                    proc, cand, fitted = run_pl_pipeline(layer["x"], layer["y"], outdir, cfg, log_cb=self._log)

                    layer["proc"] = proc
                    layer["fitted"] = fitted
                    self._log(f"✓ {layer_name} done")

                self._calc_bandgap_plqe()

                self.lbl_status.configure(text="Done", text_color=COL_OK)
                self._log("✓ Analysis complete")
                self.btn_export.configure(state="normal")
                self.btn_ai.configure(state="normal")
                self._plot()
                self._update_summary()

            except Exception as e:
                self.lbl_status.configure(text="Error", text_color=COL_ERR)
                self._log(f"✗ Error: {e}")
                import traceback
                traceback.print_exc()
                messagebox.showerror("Analysis Error", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _calc_bandgap_plqe(self):
        ref_val = None
        is_interface = (self.var_layer_mode.get() == "Interface")

        if is_interface and self.ref_layer_idx is not None:
            ref_layer = self.layers[self.ref_layer_idx]
            ref_fitted = ref_layer.get("fitted")
            if ref_fitted is not None and not ref_fitted.empty:
                ref_val = ref_fitted["Integrated_Area"].sum() if "Integrated_Area" in ref_fitted.columns else float(ref_fitted["height"].max())

        for i, layer in enumerate(self.layers):
            fitted = layer.get("fitted")
            if fitted is None or fitted.empty:
                continue

            brightest_idx = fitted["height"].idxmax()
            brightest_peak = fitted.loc[brightest_idx]

            wavelength_nm = float(brightest_peak["center"])
            bandgap_ev = 1240.8 / wavelength_nm if wavelength_nm > 0 else 0.0

            layer["bandgap_ev"] = bandgap_ev
            layer["peak_wavelength"] = wavelength_nm

            try:
                layer["fwhm_nm"] = float(brightest_peak.get("fwhm_x", 0.0))
            except Exception:
                layer["fwhm_nm"] = 0.0

            if is_interface and ref_val is not None and ref_val > 0:
                sample_val = fitted["Integrated_Area"].sum() if "Integrated_Area" in fitted.columns else float(fitted["height"].max())
                raw_plqe = (1 - (sample_val / ref_val)) * 100
                plqe = max(0.0, min(100.0, float(raw_plqe)))
                layer["plqe"] = plqe
                self._log(f"{layer['name']}: Quenching={plqe:.1f}%  Bandgap={bandgap_ev:.2f} eV  FWHM={layer['fwhm_nm']:.2f} nm")

    def _on_summary_row_click(self, idx: int):
        self.selected_layers = [idx]
        self._update_layer_selection_ui()
        self._plot()
        self._update_summary()

    def _update_summary(self):
        for widget in self.summary_frame.winfo_children():
            widget.destroy()
        if not self.layers:
            ctk.CTkLabel(self.summary_frame, text="No data", text_color=COL_MUT).pack()
            return

        header_frame = ctk.CTkFrame(self.summary_frame, fg_color=COL_STROKE)
        header_frame.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(header_frame, text="Layer", width=80, anchor="w", text_color=COL_TXT, font=ctk.CTkFont(weight="bold", size=12)).pack(side="left", padx=4, pady=4)
        ctk.CTkLabel(header_frame, text="λ (nm)", width=70, text_color=COL_TXT, font=ctk.CTkFont(weight="bold", size=12)).pack(side="left", padx=4)
        ctk.CTkLabel(header_frame, text="Eg (eV)", width=70, text_color=COL_TXT, font=ctk.CTkFont(weight="bold", size=12)).pack(side="left", padx=4)
        ctk.CTkLabel(header_frame, text="FWHM (nm)", width=85, text_color=COL_TXT, font=ctk.CTkFont(weight="bold", size=12)).pack(side="left", padx=4)
        if self.var_layer_mode.get() == "Interface":
            ctk.CTkLabel(header_frame, text="Quenching (%)", width=90, text_color=COL_TXT, font=ctk.CTkFont(weight="bold", size=12)).pack(side="left", padx=4)

        for i, layer in enumerate(self.layers):
            fitted = layer.get("fitted")
            bg_col = "#1e2a3a" if i in self.selected_layers else "transparent"
            row_frame = ctk.CTkFrame(self.summary_frame, fg_color=bg_col)
            row_frame.pack(fill="x", pady=2)

            def bind_click(w, idx_):
                w.bind("<Button-1>", lambda e: self._on_summary_row_click(idx_))

            bind_click(row_frame, i)

            lbl = ctk.CTkLabel(row_frame, text=layer["name"][:12], width=80, anchor="w", text_color=COL_MUT, font=ctk.CTkFont(size=12))
            lbl.pack(side="left", padx=4)
            bind_click(lbl, i)

            if fitted is not None and not fitted.empty:
                wavelength = layer.get("peak_wavelength", None)
                bandgap = layer.get("bandgap_ev", None)
                fwhm_nm = layer.get("fwhm_nm", None)

                ctk.CTkLabel(row_frame, text=f"{wavelength:.1f}" if wavelength else "-", width=70, text_color=COL_TXT).pack(side="left", padx=4)
                ctk.CTkLabel(row_frame, text=f"{bandgap:.2f}" if bandgap else "-", width=70, text_color=COL_TXT).pack(side="left", padx=4)
                ctk.CTkLabel(row_frame, text=f"{float(fwhm_nm):.2f}" if fwhm_nm is not None else "-", width=85, text_color=COL_TXT).pack(side="left", padx=4)

                if self.var_layer_mode.get() == "Interface":
                    plqe = layer.get("plqe", None)
                    ctk.CTkLabel(row_frame, text=f"{plqe:.1f}" if plqe is not None else "-", width=90, text_color=COL_TXT, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
            else:
                ctk.CTkLabel(row_frame, text="-", width=70, text_color=COL_MUT).pack(side="left", padx=4)
                ctk.CTkLabel(row_frame, text="-", width=70, text_color=COL_MUT).pack(side="left", padx=4)
                ctk.CTkLabel(row_frame, text="-", width=85, text_color=COL_MUT).pack(side="left", padx=4)
                if self.var_layer_mode.get() == "Interface":
                    ctk.CTkLabel(row_frame, text="-", width=90, text_color=COL_MUT).pack(side="left", padx=4)

    def _ai_comment(self):
        try:
            if not self.layers:
                messagebox.showwarning("AI", "No data loaded.")
                return

            idx = self.selected_layers[0] if self.selected_layers else 0
            layer = self.layers[idx]
            fitted = layer.get("fitted")
            proc = layer.get("proc")
            if fitted is None or fitted.empty or proc is None or proc.empty:
                messagebox.showwarning("AI", "Run analysis first.")
                return

            # Ensure API key is available
            api_key = _resolve_api_key()
            if not api_key:
                messagebox.showwarning("AI", "Gemini API key not found. Set in Setup page.")
                return
            
            self.cfg_default.use_gemini = bool(self.var_use_gemini.get())
            self.cfg_default.gemini_model = self.ent_ai_model.get().strip() or self.var_model.get()

            outdir_base = os.path.join(os.path.dirname(self.file_path) if self.file_path else os.getcwd(), "_pl_ai_report")
            report_path = generate_ai_peak_report(
                proc=proc,
                cand=fitted,
                fitted=fitted,
                cfg=self.cfg_default,
                outdir=outdir_base,
                file_label=f"PL:{layer.get('name','')}",
                log_cb=self._log,
                topn=8,
            )

            preview = ""
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    preview = f.read()
            except Exception:
                preview = f"Report written: {report_path}"

            self._show_ai_report_popup(preview)

        except Exception as e:
            messagebox.showerror("AI Error", str(e))

    def _export_excel(self):
        if not self.layers:
            messagebox.showwarning("Export", "No data to export")
            return

        path = filedialog.asksaveasfilename(title="Save Excel", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return

        try:
            used = set()
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                for i, layer in enumerate(self.layers):
                    fitted = layer.get("fitted")
                    if fitted is not None and not fitted.empty:
                        # Excel sheet titles: max 31 chars, no []:*?/\ and
                        # must be unique (duplicates raise in openpyxl)
                        raw = str(layer["name"])
                        for ch in '[]:*?/\\':
                            raw = raw.replace(ch, "_")
                        sheet_name = raw[:31] or f"Layer{i+1}"
                        base = sheet_name
                        k = 2
                        while sheet_name in used:
                            suffix = f"_{k}"
                            sheet_name = base[:31 - len(suffix)] + suffix
                            k += 1
                        used.add(sheet_name)
                        fitted.to_excel(writer, sheet_name=sheet_name, index=False)

            self._log(f"✓ Exported: {os.path.basename(path)}")
            messagebox.showinfo("Export", "Excel exported successfully")

        except Exception as e:
            messagebox.showerror("Export Error", str(e))
    def _show_ai_report_popup(self, text: str):
        """Show AI report in a large, readable popup window."""
        popup = ctk.CTkToplevel(self)
        popup.title("🤖 AI Peak Explanation Report")
        popup.geometry("1000x700")
        popup.resizable(True, True)
        
        # Header
        header = ctk.CTkFrame(popup, fg_color=COL_ACC, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, 
            text="AI Peak Explanation Report", 
            text_color="black",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=10)
        
        # Main content frame
        content = ctk.CTkFrame(popup, fg_color=COL_BG)
        content.pack(fill="both", expand=True, padx=10, pady=10)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        
        # Textbox with scrollbar
        txt = ctk.CTkTextbox(
            content,
            fg_color=COL_CARD,
            text_color=COL_TXT,
            font=ctk.CTkFont(family="Courier", size=11),
            corner_radius=8,
            border_width=1,
            border_color=COL_STROKE,
            wrap="word"
        )
        txt.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        
        # Button frame
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(
            btn_frame,
            text="📋 Copy to Clipboard",
            command=lambda: self._copy_to_clipboard(text),
            fg_color=COL_ACC,
            text_color="black",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=36
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_frame,
            text="✓ Close",
            command=popup.destroy,
            fg_color="gray",
            height=36,
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="right", padx=5)
        
        popup.grab_set()
        popup.focus()

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._log("✓ Report copied to clipboard")
            messagebox.showinfo("Success", "Report copied to clipboard!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy: {e}")