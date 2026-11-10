"""Device summary window: J-V, EQE, absorbance and PL of one device in one place.

The window reads one file per technique, runs the same cores as the
individual tools and shows the cross-technique checks of
scripts.common.device_summary: Jsc from J-V against the EQE integral, the
band gap from three techniques, Voc against Voc,rad and Voc,SQ with the loss
breakdown, and FF/PCE as fractions of the Shockley-Queisser values.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg   # no pyplot, no backend switch
from matplotlib.figure import Figure

from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common import report as _report
from scripts.common import device_summary as _ds
from scripts.common import batch as _batch
from scripts.common.iv_io import GENERIC_EXTENSIONS, read_generic_iv
from scripts.common.provenance import write_sidecar
from scripts.common import app_config

try:
    from scripts.common import analysis_shell as _shell
except Exception:  # pragma: no cover
    _shell = None

FILETYPES = [("Data", "*.txt *.csv *.tsv *.dat *.xy *.xlsx *.xls"), ("All files", "*.*")]


class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path=""):
        super().__init__(parent)
        self.title("Device summary")
        self.configure(fg_color=_pal.BG_WINDOW)
        self.paths = {"jv": tk.StringVar(), "eqe": tk.StringVar(), "abs": tk.StringVar(), "pl": tk.StringVar()}
        self.summary = None
        self.data = {}
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left()
        self._build_center()
        self._build_right()
        if _shell is not None:
            _shell.attach_chrome(self, "Device summary", {
                "open": [("J-V file", lambda: self._browse("jv")), ("EQE file", lambda: self._browse("eqe"))],
                "run": ("Compute", self.compute),
                "excel": ("Excel", self.export_excel),
                "png": True,
                "report": ("Report", self.export_report),
                "ai": ("Interpretation", self._interpret),
            }, hints="One file per technique; J-V and EQE are enough for the loss analysis  |  "
                     "Absorbance and PL add band-gap cross-checks  |  Wheel: zoom  |  Right-click: plot menu")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ---------------- layout ----------------
    def _build_left(self):
        left = ctk.CTkScrollableFrame(self, width=330, fg_color=_pal.BG_PANEL, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")

        def file_row(parent, key, label):
            ctk.CTkLabel(parent, text=label, font=_pal.font(10, "bold"), text_color=_pal.TXT_SUB,
                         anchor="w").pack(fill="x", padx=4, pady=(8, 2))
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=4)
            e = _theme.entry(row, width=230, height=26, textvariable=self.paths[key])
            e.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="...", width=34, height=26, fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                          text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                          corner_radius=_pal.R_PILL, command=lambda k=key: self._browse(k)).pack(side="left", padx=(6, 0))

        f, body = _theme.group(left, "Input files")
        f.pack(fill="x", padx=10, pady=(10, 6))
        file_row(body, "jv", "J-V curve (instrument .txt, CSV or Excel)")
        sc = ctk.CTkFrame(body, fg_color="transparent")
        sc.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(sc, text="Sweep", font=_pal.font(10), text_color=_pal.TXT_SUB).pack(side="left")
        self.var_scan = ctk.StringVar(value="reverse")
        ctk.CTkSegmentedButton(sc, values=["combined", "forward", "reverse"], variable=self.var_scan, height=24,
                               font=_pal.font(10), selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT).pack(side="left", padx=6)
        file_row(body, "eqe", "EQE spectrum (nm, % or fraction)")
        file_row(body, "abs", "Absorbance of the absorber film (optional)")
        md = ctk.CTkFrame(body, fg_color="transparent")
        md.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(md, text="Transition", font=_pal.font(10), text_color=_pal.TXT_SUB).pack(side="left")
        self.var_mode = ctk.StringVar(value="direct")
        ctk.CTkOptionMenu(md, values=["direct", "indirect"], variable=self.var_mode, width=110, height=24,
                          font=_pal.font(10)).pack(side="left", padx=6)
        file_row(body, "pl", "PL spectrum (optional)")

        g, body2 = _theme.group(left, "Conditions")
        g.pack(fill="x", padx=10, pady=6)
        grid = ctk.CTkFrame(body2, fg_color="transparent")
        grid.pack(fill="x", padx=4, pady=4)
        grid.grid_columnconfigure(1, weight=1)
        items = [("Device area (cm²)", f"{app_config.cell_area_cm2():g}"), ("Irradiance (mW/cm²)", "100"),
                 ("Temperature (K)", "300"), ("Jsc mismatch warning (%)", "5"), ("Band-gap spread warning (meV)", "60")]
        self.entries = {}
        for i, (lab, val) in enumerate(items):
            ctk.CTkLabel(grid, text=lab, font=_pal.font(10), text_color=_pal.TXT_SUB).grid(row=i, column=0, sticky="w", pady=2)
            e = _theme.entry(grid, width=80, height=24)
            e.insert(0, val)
            e.grid(row=i, column=1, sticky="e", pady=2)
            self.entries[lab] = e

        ctk.CTkButton(left, text="Compute", height=30, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV,
                      text_color="white", font=_pal.font(11, "bold"), corner_radius=_pal.R_PILL,
                      command=self.compute).pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(left, text="The J-V and EQE files of the same device give the Jsc check and the voltage-loss "
                               "breakdown; absorbance and PL add band-gap cross-checks.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM, wraplength=290, justify="left"
                     ).pack(fill="x", padx=12, pady=(4, 10))

    def _build_center(self):
        center = ctk.CTkFrame(self, fg_color=_pal.BG_WINDOW, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew")
        center.grid_rowconfigure(0, weight=1)
        center.grid_columnconfigure(0, weight=1)
        holder = ctk.CTkFrame(center, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD, border_width=1,
                              border_color=_pal.BORDER)
        holder.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        _pal.apply_mpl()
        self.fig = Figure(figsize=(9, 7), dpi=100)
        self.fig.patch.set_facecolor(_pal.PLOT_BG)
        self.ax_jv = self.fig.add_subplot(2, 2, 1)
        self.ax_eqe = self.fig.add_subplot(2, 2, 2)
        self.ax_gap = self.fig.add_subplot(2, 2, 3)
        self.ax_loss = self.fig.add_subplot(2, 2, 4)
        for ax in (self.ax_jv, self.ax_eqe, self.ax_gap, self.ax_loss):
            _pal.style_axes(ax)
        self.canvas = FigureCanvasTkAgg(self.fig, master=holder)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.enable_wheel_zoom(self.canvas)
            _pi.add_canvas_context_menu(self, self.canvas, self.fig)
        except Exception:
            pass
        self._draw_empty()

    def _build_right(self):
        right = ctk.CTkFrame(self, width=500, fg_color=_pal.BG_PANEL, corner_radius=0)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_propagate(False)
        hdr_summary = ctk.CTkLabel(right, text="Summary", font=_pal.font(12, "bold"), text_color=_pal.TXT,
                                  anchor="w")
        hdr_summary.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        _theme.panel_header(hdr_summary, right)
        frame = ctk.CTkFrame(right, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD, border_width=1,
                             border_color=_pal.BORDER)
        frame.grid(row=1, column=0, sticky="nsew", padx=10)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        _theme.style_treeview(rowheight=22)
        self.tree = ttk.Treeview(frame, columns=("q", "v", "u", "o"), show="headings")
        for c, t, w, a in (("q", "Quantity", 186, "w"), ("v", "Value", 80, "e"), ("u", "Unit", 64, "w"),
                           ("o", "Origin", 108, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=c == "q")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        ys.grid(row=0, column=1, sticky="ns", pady=4)
        try:
            from scripts.common import plot_interactions as _pi
            _pi.attach_tree_context_menu(self, self.tree)
        except Exception:
            pass
        hdr_checks = ctk.CTkLabel(right, text="Checks", font=_pal.font(12, "bold"), text_color=_pal.TXT,
                                  anchor="w")
        hdr_checks.grid(row=2, column=0, sticky="ew", padx=12, pady=(10, 4))
        _theme.panel_header(hdr_checks, right)
        self.txt_checks = ctk.CTkTextbox(right, height=170, font=_pal.font(10), fg_color=_pal.BG_CARD,
                                         text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER,
                                         corner_radius=_pal.R_CARD, wrap="word")
        self.txt_checks.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.txt_checks.insert("1.0", "Load the files and press Compute.")
        self.txt_checks.configure(state="disabled")

    # ---------------- helpers ----------------
    def _browse(self, key):
        path = filedialog.askopenfilename(parent=self, title=f"Select the {key.upper()} file", filetypes=FILETYPES)
        if path:
            self.paths[key].set(path)

    def _num(self, label, default):
        try:
            return float(self.entries[label].get())
        except (ValueError, KeyError):
            return default

    def _draw_empty(self):
        for ax, txt in ((self.ax_jv, "J-V"), (self.ax_eqe, "EQE"), (self.ax_gap, "Band gap"), (self.ax_loss, "Voltage losses")):
            ax.clear()
            _pal.style_axes(ax)
            ax.text(0.5, 0.5, txt, ha="center", va="center", transform=ax.transAxes, color=_pal.TXT_DIM, fontsize=12)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _read_jv(self, path, area, scan="combined"):
        from scripts.JV import jv_core
        if path.lower().endswith(GENERIC_EXTENSIONS):
            v, j, how = read_generic_iv(path, area)
        else:
            v, j = jv_core.read_jv_curve(path, area_cm2=area)
            how = "instrument Vmeas/Imeas block"
        if len(v) < 5:
            raise ValueError("no J-V points found")
        segs = jv_core.split_scan_directions(v, j)
        if scan != "combined" and segs:
            seg = next((s for s in segs if s["direction"] == scan), None)
            if seg is not None:
                v, j = seg["v"], seg["j"]
                how += f", {scan} sweep"
            else:
                how += f", no {scan} sweep found - all points used"
        return v, j, how

    # ---------------- compute ----------------
    def compute(self):
        area = self._num("Device area (cm²)", app_config.cell_area_cm2())
        pin = self._num("Irradiance (mW/cm²)", 100.0)
        temp = self._num("Temperature (K)", 300.0)
        mm_warn = self._num("Jsc mismatch warning (%)", 5.0)
        gap_warn = self._num("Band-gap spread warning (meV)", 60.0)
        paths = {k: v.get().strip() for k, v in self.paths.items()}
        scan, mode = self.var_scan.get(), self.var_mode.get()   # Tk variables: read on the main thread
        if not paths["jv"] and not paths["eqe"]:
            messagebox.showwarning("Device summary", "Select at least a J-V or an EQE file.", parent=self)
            return
        if _shell is not None:
            _shell.set_status(self, "Computing...")

        def work():
            from scripts.JV import jv_core
            notes, data = [], {}
            jv = fit = None
            try:
                if paths["jv"]:
                    v, j, how = self._read_jv(paths["jv"], area, scan)
                    jv = jv_core.compute_jv_parameters(v, j, pin_mw_cm2=pin)
                    fit = jv_core.fit_single_diode(v, j, pin_mw_cm2=pin)
                    data["jv"] = (v, j, how, fit)
                    notes.append(f"J-V: {how}.")
                eqe_x = eqe_y = None
                if paths["eqe"]:
                    eqe_x, eqe_y, col = _batch.read_xy(paths["eqe"])
                    data["eqe"] = (eqe_x, eqe_y)
                    notes.append(f"EQE: column '{col}'.")
                eg_abs = pl_ev = None
                if paths["abs"]:
                    ax_, ay_, col = _batch.read_xy(paths["abs"])
                    r = _batch.analyse_abs(ax_, ay_, mode=mode)
                    eg_abs = r["Eg Tauc (eV)"]
                    data["abs"] = r
                    notes.append(f"Absorbance: column '{col}', {mode} Tauc region "
                                 f"{r['region lo (eV)']:.3f}-{r['region hi (eV)']:.3f} eV.")
                if paths["pl"]:
                    px, py, col = _batch.read_xy(paths["pl"])
                    r = _batch.analyse_pl(px, py)
                    pl_ev = r["Peak (eV)"]
                    data["pl"] = (px, py, r)
                    notes.append(f"PL: column '{col}', peak from a Gaussian fit on the energy axis (Jacobian applied).")
                summary = _ds.summarize_device(jv, eqe_x, eqe_y, eg_abs_ev=eg_abs, pl_peak_ev=pl_ev,
                                               temperature_k=temp, diode_fit=fit,
                                               mismatch_warn_percent=mm_warn, eg_spread_warn_mev=gap_warn)
                summary["input_notes"] = notes
                self.after(0, lambda: self._show(summary, data, paths, dict(area=area, pin=pin, temperature=temp,
                                                                              sweep=scan, transition=mode)))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: (messagebox.showerror("Device summary", str(e), parent=self),
                                             _shell.set_status(self, "Failed") if _shell else None))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, summary, data, paths, conditions):
        self.summary, self.data, self.inputs, self.conditions = summary, data, paths, conditions
        tbl = _ds.summary_table(summary)
        self.tree.delete(*self.tree.get_children())
        for _, r in tbl.iterrows():
            self.tree.insert("", "end", values=(r["Quantity"], r["Value"], r["Unit"], r["Origin"]))
        lines = []
        if summary["warnings"]:
            lines.append("Warnings")
            lines += [f"  - {w}" for w in summary["warnings"]]
        else:
            lines.append("No inconsistency above the warning thresholds.")
        lines.append("")
        lines += summary.get("input_notes", [])
        if summary["notes"]:
            lines.append("")
            lines += summary["notes"]
        self.txt_checks.configure(state="normal")
        self.txt_checks.delete("1.0", "end")
        self.txt_checks.insert("1.0", "\n".join(lines))
        self.txt_checks.configure(state="disabled")
        self._plot(summary, data)
        if _shell is not None:
            _shell.set_status(self, "Done" + (f" - {len(summary['warnings'])} warning(s)" if summary["warnings"] else ""))

    def _plot(self, s, data):
        for ax in (self.ax_jv, self.ax_eqe, self.ax_gap, self.ax_loss):
            ax.clear()
            _pal.style_axes(ax)
        # J-V
        if "jv" in data:
            v, j, _how, fit = data["jv"]
            order = np.argsort(v)
            self.ax_jv.plot(v[order], j[order], "o", ms=2.5, color=_pal.series_color(0), label="measured")
            if fit and fit.get("success") and fit.get("y_fit") is not None:
                self.ax_jv.plot(fit["voltage"], fit["y_fit"], "-", color=_pal.RED, lw=1.2,
                                label=f"one-diode fit, n = {fit['n']:.2f}")
            if np.isfinite(s.get("JV_Vmpp", np.nan)):
                sign = -1.0 if np.interp(0.0, v[order], j[order]) < 0 else 1.0
                self.ax_jv.plot([s["JV_Vmpp"]], [sign * s["JV_Jmpp"]], "s", color=_pal.ORANGE, ms=6, label="MPP")
            self.ax_jv.axhline(0, color=_pal.PLOT_REF, lw=0.8)
            self.ax_jv.axvline(0, color=_pal.PLOT_REF, lw=0.8)
            self.ax_jv.set_xlabel("Voltage (V)")
            self.ax_jv.set_ylabel("J (mA/cm²)")
            self.ax_jv.set_title(f"PCE {s.get('JV_PCE', float('nan')):.2f} %   FF {s.get('JV_FF', float('nan')):.1f} %", fontsize=10)
            self.ax_jv.legend(fontsize=8)
        # EQE + integrated Jsc
        if "eqe" in data:
            from scripts.EQE import eqe_core
            x, y = data["eqe"]
            frac = eqe_core.eqe_to_fraction(y)
            self.ax_eqe.plot(x, 100 * frac, color=_pal.series_color(1), lw=1.4)
            self.ax_eqe.set_xlabel("Wavelength (nm)")
            self.ax_eqe.set_ylabel("EQE (%)")
            tw = self.ax_eqe.twinx()
            _, _, cum = eqe_core.compute_am15_integrals(x, y)
            tw.plot(x, cum, "--", color=_pal.series_color(2), lw=1.1)
            tw.set_ylabel("Integrated Jsc (mA/cm²)", color=_pal.PLOT_FG)
            tw.tick_params(colors=_pal.PLOT_TICK, direction="in")
            if np.isfinite(s.get("JV_Jsc", np.nan)):
                tw.axhline(s["JV_Jsc"], color=_pal.ORANGE, lw=0.9, ls=":")
            self.ax_eqe.set_title(f"Jsc(EQE) {s.get('EQE_Jsc', float('nan')):.2f}   mismatch "
                                  f"{s.get('Jsc_mismatch_percent', float('nan')):+.1f} %", fontsize=10)
        # band gaps
        gaps = [("EQE dEQE/dE", s.get("EQE_Eg")), ("Tauc", s.get("Eg_Abs")), ("PL peak", s.get("Eg_PL"))]
        gaps = [(k, v) for k, v in gaps if v is not None and np.isfinite(v)]
        if gaps:
            ys = np.arange(len(gaps))
            self.ax_gap.errorbar([v for _, v in gaps], ys,
                                 xerr=[(s.get("EQE_Eg_sigma_meV", 0) or 0) / 1000.0 if k.startswith("EQE") else 0 for k, _ in gaps],
                                 fmt="o", color=_pal.series_color(3), capsize=3)
            self.ax_gap.set_yticks(ys)
            self.ax_gap.set_yticklabels([k for k, _ in gaps])
            self.ax_gap.set_ylim(-0.7, len(gaps) - 0.3)
            self.ax_gap.set_xlabel("Energy (eV)")
            title = "Band gap"
            if np.isfinite(s.get("Eg_spread_meV", np.nan)):
                title += f": spread {s['Eg_spread_meV']:.0f} meV"
            self.ax_gap.set_title(title, fontsize=10)
        else:
            self.ax_gap.text(0.5, 0.5, "no band-gap data", ha="center", va="center", transform=self.ax_gap.transAxes,
                             color=_pal.TXT_DIM)
        # voltage ladder
        eg = s.get("Eg_reference")
        if eg is not None and np.isfinite(eg) and np.isfinite(s.get("SQ_Voc", np.nan)):
            levels = [(r"$E_g/q$", eg), (r"$V_{oc}^{SQ}$", s.get("SQ_Voc")), (r"$V_{oc}^{rad}$", s.get("EQE_Voc_rad")),
                      (r"$V_{oc}$", s.get("JV_Voc"))]
            levels = [(k, v) for k, v in levels if v is not None and np.isfinite(v)]
            xs = np.arange(len(levels))
            self.ax_loss.bar(xs, [v for _, v in levels], color=[_pal.series_color(i) for i in range(len(levels))],
                             width=0.6, edgecolor="#000000", linewidth=1.0)
            for i, (k, v) in enumerate(levels):
                self.ax_loss.text(i, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=8, color=_pal.PLOT_FG)
            self.ax_loss.set_xticks(xs)
            self.ax_loss.set_xticklabels([k for k, _ in levels], fontsize=10)
            lo = min(v for _, v in levels)
            self.ax_loss.set_ylim(max(0.0, lo - 0.25), eg + 0.12)
            self.ax_loss.set_ylabel("Voltage (V)")
            t = "Voltage losses"
            if np.isfinite(s.get("dV3_nonrad", np.nan)):
                t += f": non-radiative {1000 * s['dV3_nonrad']:.0f} mV"
            self.ax_loss.set_title(t, fontsize=10)
        else:
            self.ax_loss.text(0.5, 0.5, "needs a band gap and Voc", ha="center", va="center",
                              transform=self.ax_loss.transAxes, color=_pal.TXT_DIM)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    # ---------------- export ----------------
    def _interpret(self):
        if not self.summary:
            messagebox.showinfo("Interpretation", "Compute the summary first.", parent=self)
            return
        from scripts.common.interpret import interpret_device
        from scripts.common.interpret_window import show
        show(self, interpret_device(self.summary))

    def export_excel(self):
        if not self.summary:
            messagebox.showwarning("Export", "Compute first.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".xlsx", initialfile="device_summary.xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        tbl = _ds.summary_table(self.summary)
        raw = {k: v for k, v in self.summary.items() if not isinstance(v, (list, dict))}
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            tbl.to_excel(w, sheet_name="Summary", index=False)
            pd.DataFrame(list(raw.items()), columns=["Key", "Value"]).to_excel(w, sheet_name="AllValues", index=False)
            pd.DataFrame({"Warning": self.summary["warnings"] or ["none"]}).to_excel(w, sheet_name="Checks", index=False)
            pd.DataFrame([{"Technique": k, "File": v} for k, v in self.inputs.items() if v]).to_excel(
                w, sheet_name="Inputs", index=False)
        write_sidecar(path, "Device summary", inputs=[v for v in self.inputs.values() if v],
                      parameters=self.conditions, results=raw)
        if _shell is not None:
            _shell.set_status(self, f"Saved {os.path.basename(path)}")

    def export_report(self):
        if not self.summary:
            messagebox.showwarning("Report", "Compute first.", parent=self)
            return
        path = _report.ask_report_path(self, "device_summary.md")
        if not path:
            return
        checks = "\n".join(f"- {w}" for w in self.summary["warnings"]) or "No inconsistency above the warning thresholds."
        notes = (" ".join(self.summary.get("input_notes", [])) + " " + " ".join(self.summary["notes"]) +
                 " Jsc mismatch = (Jsc,JV - Jsc,EQE)/Jsc,EQE. Band gap from EQE: mean of dEQE/dE over its half-maximum "
                 "window (Rau 2017). Detailed balance at the reference gap: SQ step absorber; Voc,rad from the measured EQE.")
        _report.write_markdown_report(path, "Device summary", [("Summary", _ds.summary_table(self.summary)),
                                                               ("Checks", checks)],
                                      figure=self.fig, inputs=[v for v in self.inputs.values() if v], notes=notes)
        if _shell is not None:
            _shell.set_status(self, f"Report saved: {os.path.basename(path)}")


def main():
    root = ctk.CTk()
    root.withdraw()
    AnalysisWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
