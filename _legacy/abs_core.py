import numpy as np
import pandas as pd
import os
import time
import subprocess
import matplotlib.pyplot as plt
from matplotlib.widgets import RangeSlider, Button, SpanSelector, RadioButtons, TextBox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import sys
from pathlib import Path

# Win32com check
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

class AnalysisWindow(ctk.CTkToplevel):
    def __init__(self, parent, origin_path, api_key):
        super().__init__(parent)
        self.title("Absorbance / Tauc Plot Analyzer")
        self.geometry("1300x900")
        
        self.origin_path = origin_path
        self.api_key = api_key 
        
        # Data variables
        self.df = None
        self.hv = None
        self.absorbance = None
        self.raw_x = None
        self.raw_y = None
        self.target_file = None
        self.sheet_name = None
        
        # Analysis state
        self.fit_result = None
        self.data_state = {}
        
        # UI Setup
        self._init_ui()
        
        # Bring to front
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        plt.close('all')
        self.destroy()

    def _init_ui(self):
        # Main layout
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Control Panel
        control_frame = ctk.CTkFrame(self.main_frame)
        control_frame.pack(fill="x", pady=(0, 10))
        
        range_card = ctk.CTkFrame(self.main_frame)
        range_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(range_card, text="Tauc X View (eV)", font=("Arial", 14, "bold")).pack(anchor="w", padx=10, pady=(8, 2))

        self.lbl_xrange = ctk.CTkLabel(range_card, text="--")
        self.lbl_xrange.pack(anchor="w", padx=10, pady=(0, 6))

        slider_row = ctk.CTkFrame(range_card, fg_color="transparent")
        slider_row.pack(fill="x", padx=10, pady=(0, 10))

        # ✅ 최소/최대 슬라이더 (RangeSlider 대체)
        self.xmin_slider = ctk.CTkSlider(slider_row, from_=0, to=1, number_of_steps=1000, command=self._on_xmin_slider)
        self.xmax_slider = ctk.CTkSlider(slider_row, from_=0, to=1, number_of_steps=1000, command=self._on_xmax_slider)

        ctk.CTkLabel(slider_row, text="Min", width=40).grid(row=0, column=0, sticky="w")
        self.xmin_slider.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(slider_row, text="Max", width=40).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.xmax_slider.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        slider_row.grid_columnconfigure(1, weight=1)

        # Row 1: File & Origin Path
        row1 = ctk.CTkFrame(control_frame, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkButton(row1, text="Load Excel Data", command=self.load_data, fg_color="#1E88E5").pack(side="left", padx=5)
        
        ctk.CTkLabel(row1, text="Origin Path:").pack(side="left", padx=(20, 5))
        self.entry_origin = ctk.CTkEntry(row1, width=400)
        self.entry_origin.pack(side="left", padx=5)
        if self.origin_path:
            self.entry_origin.insert(0, self.origin_path)
        else:
            self.entry_origin.insert(0, self.find_origin_path())
            
        ctk.CTkButton(row1, text="Export Result", command=self.export_result, fg_color="green").pack(side="right", padx=5)

        # Graph Frame
        self.graph_frame = ctk.CTkFrame(self.main_frame)
        self.graph_frame.pack(fill="both", expand=True)
        
        # Matplotlib Figure
        # We use the layout from manual_fit_with_ui
        self.fig, (self.ax_abs, self.ax_tauc) = plt.subplots(1, 2, figsize=(12, 6))
        self.fig.subplots_adjust(top=0.85, bottom=0.25, wspace=0.25, left=0.08, right=0.95)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        # Toolbar
        toolbar = NavigationToolbar2Tk(self.canvas, self.graph_frame)
        toolbar.update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def find_origin_path(self):
        search_dirs = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        ]
        for base_dir in search_dirs:
            origin_lab_dir = os.path.join(base_dir, "OriginLab")
            if os.path.exists(origin_lab_dir):
                try:
                    subdirs = [d for d in os.listdir(origin_lab_dir) if d.lower().startswith("origin")]
                    subdirs.sort(reverse=True)
                    for d in subdirs:
                        exe_path = os.path.join(origin_lab_dir, d, "Origin64.exe")
                        if os.path.exists(exe_path):
                            return exe_path
                except: continue
        return r"C:\Program Files\OriginLab\Origin2024\Origin64.exe"

    def load_data(self):
        file_path = filedialog.askopenfilename(filetypes=[("Excel Files", "*.xlsx *.xls")])
        if not file_path: return
        
        try:
            xls = pd.ExcelFile(file_path)
            sheet_names = xls.sheet_names
            
            if len(sheet_names) > 1:
                sheet = self.ask_sheet(sheet_names)
                if not sheet: return
            else:
                sheet = sheet_names[0]
                
            self.df = pd.read_excel(file_path, sheet_name=sheet)
            self.target_file = Path(file_path)
            self.sheet_name = sheet
            
            # Assume col 0 is Wavelength (nm), col 1 is Absorbance
            self.raw_x = self.df.iloc[:, 0].to_numpy(dtype=float)
            self.raw_y = self.df.iloc[:, 1].to_numpy(dtype=float)
            
            # Calculate Energy (eV)
            self.hv = 1240.0 / self.raw_x
            self.absorbance = self.raw_y
            
            self.init_plot()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {e}")

    def ask_sheet(self, sheets):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select Sheet")
        dialog.geometry("300x150")
        dialog.attributes('-topmost', True)
        
        selected = tk.StringVar(value=sheets[0])
        combo = ctk.CTkComboBox(dialog, values=sheets, variable=selected)
        combo.pack(pady=20, padx=20)
        
        result = [None]
        def on_ok():
            result[0] = selected.get()
            dialog.destroy()
            
        ctk.CTkButton(dialog, text="OK", command=on_ok).pack(pady=10)
        self.wait_window(dialog)
        return result[0]

    def init_plot(self):
        self.ax_abs.clear()
        self.ax_tauc.clear()
        
        mask = np.isfinite(self.hv) & np.isfinite(self.absorbance)
        self.hv = self.hv[mask]
        self.absorbance = self.absorbance[mask]
        idx = np.argsort(self.hv)
        self.hv = self.hv[idx]
        self.absorbance = self.absorbance[idx]
        
        self.data_state = {
            "x": self.hv,
            "y": (self.absorbance * self.hv) ** 2,
            "y_label": r"$(A\cdot h\nu)^2$"
        }
        
        self.ax_abs.plot(self.raw_x, self.raw_y, label="Raw Data", color='tab:blue')
        self.ax_abs.set_xlabel("Wavelength (nm)")
        self.ax_abs.set_ylabel("Absorbance")
        self.ax_abs.set_title("Absorption Spectrum")
        self.ax_abs.grid(True, linestyle='--', alpha=0.5)
        
        self.line_tauc, = self.ax_tauc.plot(self.data_state["x"], self.data_state["y"], "o", markersize=4, color='tab:orange', alpha=0.6)
        self.ax_tauc.set_xlabel("hν (eV)")
        self.ax_tauc.set_ylabel(self.data_state["y_label"])
        self.title_text = self.ax_tauc.set_title("Drag range to Fit", color='blue', fontweight='bold')
        self.ax_tauc.grid(True, linestyle='--', alpha=0.5)
        
        self.fit_line, = self.ax_tauc.plot([], [], 'r-', linewidth=2.5)
        self.v1 = self.ax_tauc.axvline(np.nan, linestyle="--", color='gray')
        self.v2 = self.ax_tauc.axvline(np.nan, linestyle="--", color='gray')
        
        self.setup_mpl_widgets()

        self.data_state["tauc_xlim"] = tuple(self.ax_tauc.get_xlim())
        self.data_state["tauc_ylim"] = tuple(self.ax_tauc.get_ylim())

        self.canvas.draw()

        # ✅ 슬라이더 범위 초기화 (hv min~max)
        x_min = float(np.min(self.data_state["x"]))
        x_max = float(np.max(self.data_state["x"]))

        self.xmin_slider.configure(from_=x_min, to=x_max)
        self.xmax_slider.configure(from_=x_min, to=x_max)

        # 초기값(원래 RangeSlider valinit 느낌)
        init_min, init_max = 1.6, 2.2
        init_min = max(x_min, min(init_min, x_max))
        init_max = max(x_min, min(init_max, x_max))
        if init_min >= init_max:
            init_min, init_max = x_min, x_max

        self.xmin_slider.set(init_min)
        self.xmax_slider.set(init_max)

        # 축 적용
        self._apply_tauc_xlim(init_min, init_max)

    def _apply_tauc_xlim(self, xmin, xmax):
        if not hasattr(self, "ax_tauc"):
            return
        if xmin > xmax:
            xmin, xmax = xmax, xmin

        self.ax_tauc.set_xlim(xmin, xmax)
        self.autoscale_y()
        self.data_state["tauc_xlim"] = tuple(self.ax_tauc.get_xlim())
        self.data_state["tauc_ylim"] = tuple(self.ax_tauc.get_ylim())

        if hasattr(self, "lbl_xrange"):
            self.lbl_xrange.configure(text=f"{xmin:.3f} ~ {xmax:.3f} eV")

        self.canvas.draw_idle()

    def _on_xmin_slider(self, val):
        try:
            xmin = float(val)
            xmax = float(self.xmax_slider.get())
            self._apply_tauc_xlim(xmin, xmax)
        except:
            pass

    def _on_xmax_slider(self, val):
        try:
            xmin = float(self.xmin_slider.get())
            xmax = float(val)
            self._apply_tauc_xlim(xmin, xmax)
        except:
            pass

    def setup_mpl_widgets(self):
        if hasattr(self, 'radio'): self.radio.disconnect_events()
        
        ax_radio = self.fig.add_axes([0.05, 0.88, 0.12, 0.10])
        ax_radio.set_facecolor('#f5f5f5')
        self.radio = RadioButtons(ax_radio, ('Direct', 'Indirect'))
        self.radio.on_clicked(self.change_bandgap_type)
        
        ax_slider = self.fig.add_axes([0.15, 0.05, 0.70, 0.03])
        self.x_slider = RangeSlider(
            ax=ax_slider,
            label="X View",
            valmin=float(np.min(self.data_state["x"])),
            valmax=float(np.max(self.data_state["x"])),
            valinit=(1.6, 2.2)
        )
        self.x_slider.on_changed(self.on_slider_change)
        
        self.span = SpanSelector(
            self.ax_tauc, self.on_span_select, "horizontal",
            useblit=False, interactive=True,
            props=dict(alpha=0.2, facecolor='red')
        )

    def change_bandgap_type(self, label):
        if label == 'Direct':
            self.data_state["y"] = (self.absorbance * self.hv) ** 2
            self.data_state["y_label"] = r"$(A\cdot h\nu)^2$"
        else:
            self.data_state["y"] = (self.absorbance * self.hv) ** 0.5
            self.data_state["y_label"] = r"$(A\cdot h\nu)^{1/2}$"
            
        self.line_tauc.set_ydata(self.data_state["y"])
        self.ax_tauc.set_ylabel(self.data_state["y_label"])
        
        self.fit_line.set_data([], [])
        self.title_text.set_text("Drag range to Fit")
        self.title_text.set_color('blue')
        self.fit_result = None
        
        self.autoscale_y()
        self.canvas.draw_idle()

    def on_slider_change(self, val):
        self.ax_tauc.set_xlim(val[0], val[1])
        self.autoscale_y()
        self.canvas.draw_idle()

    def autoscale_y(self):
        x = self.data_state["x"]
        y = self.data_state["y"]
        xmin, xmax = self.ax_tauc.get_xlim()
        vis = (x >= xmin) & (x <= xmax)
        if np.any(vis):
            ymax = np.max(y[vis])
            self.ax_tauc.set_ylim(0, 1.1 * ymax if ymax > 0 else 1)

    def on_span_select(self, xmin, xmax):
        if xmin == xmax: return
        
        x = self.data_state["x"]
        y = self.data_state["y"]
        
        fitMin, fitMax = min(xmin, xmax), max(xmin, xmax)
        sel = (x >= fitMin) & (x <= fitMax)
        
        if np.sum(sel) < 2: return
        
        try:
            m, b = np.polyfit(x[sel], y[sel], 1)
        except: return
        
        if m == 0: return
        Eg = -b / m
        
        yfit = m*x[sel] + b
        SSres = np.sum((y[sel] - yfit)**2)
        SStot = np.sum((y[sel] - np.mean(y[sel]))**2)
        R2 = 1 - SSres / SStot if SStot != 0 else np.nan
        
        xline = np.linspace(fitMin, fitMax, 200)
        self.fit_line.set_data(xline, m*xline + b)
        self.v1.set_xdata([fitMin, fitMin])
        self.v2.set_xdata([fitMax, fitMax])
        
        self.title_text.set_text(f"Eg = {Eg:.4f} eV  |  R² = {R2:.4f}")
        self.title_text.set_color('red')
        
        self.fit_result = {
            "Eg": Eg, "R2": R2, "m": m, "b": b,
            "fitMin": fitMin, "fitMax": fitMax,
            "x_full": x, "y_full": y,
            "raw_x": self.raw_x, "raw_y": self.raw_y,
            "y_label": self.data_state["y_label"]
        }
        
        self.canvas.draw_idle()

    def export_result(self):
        if not self.fit_result:
            messagebox.showwarning("Warning", "Please perform a fit first (drag on Tauc plot).")
            return
            
        dialog = ctk.CTkToplevel(self)
        dialog.title("Export")
        dialog.geometry("300x150")
        dialog.attributes('-topmost', True)
        
        ctk.CTkLabel(dialog, text=f"Eg: {self.fit_result['Eg']:.4f} eV").pack(pady=10)
        
        def save_excel():
            self.save_to_excel()
            dialog.destroy()
            
        def send_origin():
            self.send_to_origin()
            dialog.destroy()
            
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)
        ctk.CTkButton(btn_frame, text="Save Excel", command=save_excel, width=100).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="To Origin", command=send_origin, width=100).pack(side="left", padx=5)

    def save_to_excel(self):
        if not self.target_file or not self.fit_result:
            return

        out_path = self.target_file.parent / f"{self.target_file.stem}_result.xlsx"
        res = self.fit_result

        # -------------------------
        # 1) Result 시트 (요약 1행)
        # -------------------------
        df_result = pd.DataFrame([{
            "Eg (eV)": float(res["Eg"]),
            "R2": float(res["R2"]) if res["R2"] is not None else np.nan,
            "Slope": float(res["m"]),
            "Intercept": float(res["b"]),
            "Bandgap Type": res["y_label"],
            "Fit Min (eV)": float(res["fitMin"]),
            "Fit Max (eV)": float(res["fitMax"]),
        }])

        # -------------------------
        # 2) UV-Vis 시트 (원본 그대로)
        # -------------------------
        df_uvvis = pd.DataFrame({
            "Wavelength (nm)": np.asarray(res["raw_x"], dtype=float),
            "Absorbance": np.asarray(res["raw_y"], dtype=float),
        })

        # -------------------------
        # 3) Tauc 데이터 (현재 화면 xlim 범위만) + Fit line을 같은 시트로
        # -------------------------
        # 현재 화면에서 보이는 Tauc x 범위
        xmin, xmax = self.ax_tauc.get_xlim()
        xmin, xmax = (xmin, xmax) if xmin <= xmax else (xmax, xmin)

        ymin, ymax = self.ax_tauc.get_ylim()
        ymin, ymax = (ymin, ymax) if ymin <= ymax else (ymax, ymin)

        x_full = np.asarray(res["x_full"], dtype=float)
        y_full = np.asarray(res["y_full"], dtype=float)

        vis = np.isfinite(x_full) & np.isfinite(y_full) & (x_full >= xmin) & (x_full <= xmax)
        x_vis = x_full[vis]
        y_vis = y_full[vis]

        # Fit line (fitMin~fitMax) - 원래 방식 유지
        fit_left = float(res["fitMin"])
        fit_right = float(res["fitMax"])
        if fit_left > fit_right:
            fit_left, fit_right = fit_right, fit_left

        fit_x = np.linspace(fit_left, fit_right, 200)
        fit_y = res["m"] * fit_x + res["b"]

        # ✅ 길이가 다를 수 있으니, 한 시트에 "열로" 나란히 두되 index 맞춰서 붙임
        df_tauc = pd.DataFrame({
            "Energy (eV)": x_vis,
            "Tauc Value": y_vis,
        })

        df_fit = pd.DataFrame({
            "Fit X (eV)": fit_x,
            "Fit Y": fit_y
        })

        # 서로 길이가 달라도 NaN으로 채워지게 reset_index 후 concat
        df_tauc_fit = pd.concat(
            [df_tauc.reset_index(drop=True), df_fit.reset_index(drop=True)],
            axis=1
        )

        # -------------------------
        # 4) Excel 저장 (시트 3개)
        # -------------------------
        try:
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                df_result.to_excel(writer, sheet_name="Result", index=False)
                df_uvvis.to_excel(writer, sheet_name="UV-Vis", index=False)
                df_tauc_fit.to_excel(writer, sheet_name="Tauc_Data", index=False)

            messagebox.showinfo("Success", f"Saved to {out_path.name}")

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_slider_change(self, val):
        self.ax_tauc.set_xlim(val[0], val[1])
        self.autoscale_y()
        self.canvas.draw_idle()

        # ✅ 현재 화면 범위 저장 (Export/Origin에 그대로 쓰기 위해)
        self.data_state["tauc_xlim"] = tuple(self.ax_tauc.get_xlim())
        self.data_state["tauc_ylim"] = tuple(self.ax_tauc.get_ylim())





    def send_to_origin(self):
        if not WIN32COM_AVAILABLE:
            messagebox.showerror("Error", "pywin32 not installed.")
            return

        if not self.fit_result:
            messagebox.showwarning("Warning", "Please perform a fit first (drag on Tauc plot).")
            return

        origin_path = self.entry_origin.get()
        res = self.fit_result

        try:
            # -------------------------
            # Origin 연결
            # -------------------------
            origin = None
            try:
                origin = win32com.client.Dispatch("Origin.ApplicationSI")
                origin.Visible = 1
            except:
                if os.path.exists(origin_path):
                    subprocess.Popen([origin_path])
                    time.sleep(10)
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1

            if not origin:
                raise Exception("Could not connect to Origin")

            # -------------------------
            # 0) UI에서 현재 Tauc 축 범위(고정용) 가져오기
            # -------------------------
            xmin, xmax = self.ax_tauc.get_xlim()
            xmin, xmax = (xmin, xmax) if xmin <= xmax else (xmax, xmin)

            ymin, ymax = self.ax_tauc.get_ylim()
            ymin, ymax = (ymin, ymax) if ymin <= ymax else (ymax, ymin)

            # -------------------------
            # 1) UV-Vis 데이터 (원본 전체)
            # -------------------------
            uv_x = np.asarray(res["raw_x"], dtype=float)
            uv_y = np.asarray(res["raw_y"], dtype=float)

            # -------------------------
            # 2) Tauc 데이터 (현재 슬라이더 xlim 범위만)
            # -------------------------
            x_full = np.asarray(res["x_full"], dtype=float)
            y_full = np.asarray(res["y_full"], dtype=float)

            vis = np.isfinite(x_full) & np.isfinite(y_full) & (x_full >= xmin) & (x_full <= xmax)
            tauc_x = x_full[vis]
            tauc_y = y_full[vis]

            # -------------------------
            # 3) Fit (m,b) 기반: FitY를 전체 tauc_x에 대해 "쭉" 계산
            # -------------------------
            m = float(res["m"])
            b = float(res["b"])
            fit_y_full = (m * tauc_x + b).astype(float)

            # =========================================================
            # [A] 워크시트 1: UV-Vis (2컬럼)
            # =========================================================
            wb_uv = origin.CreatePage(2, f"UV_{self.sheet_name}"[:10], "Origin")
            origin.Execute(f"page.active$ = {wb_uv};")
            origin.Execute("wks.ncols = 2;")

            origin.Execute('wks.col1.lname$="Wavelength"; wks.col1.units$="nm"; wks.col1.type=4;')     # X
            origin.Execute('wks.col2.lname$="Absorbance"; wks.col2.units$="a.u."; wks.col2.type=1;')   # Y

            origin.PutWorksheet(f"[{wb_uv}]Sheet1", uv_x.tolist(), 0, 0)
            origin.PutWorksheet(f"[{wb_uv}]Sheet1", uv_y.tolist(), 0, 1)

            # =========================================================
            # [B] 워크시트 2: TaucSheet (Energy + Tauc + FitY) 3컬럼
            # =========================================================
            wb_tauc = origin.CreatePage(2, f"Tauc_{self.sheet_name}"[:10], "Origin")
            origin.Execute(f"page.active$ = {wb_tauc};")
            origin.Execute("wks.ncols = 3;")

            origin.Execute('wks.col1.lname$="Energy"; wks.col1.units$="eV";  wks.col1.type=4;')        # X
            origin.Execute('wks.col2.lname$="Tauc";   wks.col2.units$="a.u."; wks.col2.type=1;')       # Y1
            origin.Execute('wks.col3.lname$="FitY";   wks.col3.units$="a.u."; wks.col3.type=1;')       # Y2

            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", tauc_x.tolist(), 0, 0)
            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", tauc_y.tolist(), 0, 1)
            origin.PutWorksheet(f"[{wb_tauc}]Sheet1", fit_y_full.tolist(), 0, 2)

            # =========================================================
            # [C] Origin 플롯 생성
            #   - 흡수 그래프: 그대로
            #   - 타우크 플롯: UI 스케일(xlim/ylim) 그대로 고정
            # =========================================================

            # ---- Graph 1: UV-Vis (Wavelength vs Absorbance) ----
            gp_uv = origin.CreatePage(3, f"Abs_{self.sheet_name}"[:10], "Origin")
            origin.Execute(f"page.active$ = {gp_uv};")
            origin.Execute(f"plotxy iy:=[{wb_uv}]Sheet1!(1,2) plot:=200;")  # line
            origin.Execute("layer -d;")

            # UI 스케일 고정 (한 번만)
            origin.Execute(f"layer.x.from = 200; layer.x.to = 1000;")
            origin.Execute(f"layer.y.from = 0; layer.y.to = 1.5;")

            origin.Execute("label -y1 Absorbance;")
            origin.Execute("label -x1 Wavelength (nm);")

            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")

            origin.Execute("layer.y.inc = 0.5;")
            origin.Execute("layer.x.inc = 200;")
            origin.Execute("layer.y.label.pt = 30;")
            origin.Execute("layer.x.label.pt = 30;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.y2.ticks = 0;")


            # ---- Graph 2: Tauc (Energy vs Tauc + FitY) ----
            gp_tauc = origin.CreatePage(3, f"Tauc"[:10], "Origin")
            origin.Execute(f"page.active$ = {gp_tauc};")
            

            # 1) scatter
            origin.Execute(f"plotxy iy:=[{wb_tauc}]Sheet1!(1,2) plot:=201 o:=[Tauc]1!;")
            origin.Execute(f"plotxy iy:=[{wb_tauc}]Sheet1!(1,3) plot:=200 o:=[Tauc]1!;")
            

            # UI 스케일 고정 (한 번만)
            origin.Execute(f"layer.x.from = {xmin}; layer.x.to = {xmax};")
            origin.Execute(f"layer.y.from = {ymin}; layer.y.to = {ymax};")
            
            origin.Execute("label -y1 (\g(a)\i(h)\g(n))\+(2);")
            origin.Execute("label -x1 \i(h)\g(n) (eV);")  

            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")

            origin.Execute("layer.y.inc = 10;")
            origin.Execute("layer.x.inc = .1;")
            origin.Execute("layer.y.label.pt = 30;")
            origin.Execute("layer.x.label.pt = 30;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.y2.ticks = 0;")

            # (선택) Fit 선 두께
            origin.Execute("layer.plot = 2; set %C -w 2000;")
            origin.Execute("layer.plot = 1;")

            # 보기 좋게 정렬
            origin.Execute("doc -uw; tile -h;")
            origin.Visible = 1

            messagebox.showinfo(
                "Success",
                "Sent worksheets + created plots in Origin:\n"
                "- UV-Vis (Absorption)\n"
                "- Tauc plot (fixed to UI xlim/ylim)"
            )

        except Exception as e:
            messagebox.showerror("Origin Error", str(e))

if __name__ == "__main__":
    # Test mode
    root = ctk.CTk()
    AnalysisWindow(root, "", "")
    root.mainloop()