import numpy as np
import pandas as pd
from pathlib import Path
import os
import time
import subprocess
import matplotlib.pyplot as plt
from matplotlib.widgets import RangeSlider, Button, SpanSelector, RadioButtons, TextBox
import tkinter as tk
from tkinter import messagebox, filedialog
from scipy.signal import savgol_filter
from scipy.constants import h, c, e

# Win32com 라이브러리 체크 (Origin 연동용)
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

# -----------------------------------------------------------
# [함수 1] Origin 경로 자동 검색 (기존 로직 유지)
# -----------------------------------------------------------
def find_origin_path():
    search_dirs = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    ]
    
    for base_dir in search_dirs:
        origin_lab_dir = os.path.join(base_dir, "OriginLab")
        if os.path.exists(origin_lab_dir):
            try:
                subdirs = [d for d in os.listdir(origin_lab_dir) if d.lower().startswith("origin")]
                subdirs.sort(reverse=True) # 최신 버전 우선
                
                for d in subdirs:
                    exe_path = os.path.join(origin_lab_dir, d, "Origin64.exe")
                    if os.path.exists(exe_path):
                        return exe_path
            except Exception:
                continue
    return r"C:\Program Files\OriginLab\Origin2024\Origin64.exe" # 못 찾으면 기본값

# -----------------------------------------------------------
# [함수 2] 수동 피팅 UI (수정됨: 레이아웃 및 잔상 해결)
# -----------------------------------------------------------
def get_am15g_spectrum():
    """
    Returns AM1.5G standard spectrum (ASTM G173-03 Global Tilt).
    Returns: (wavelength_nm, irradiance_W_m2_nm)
    """
    # Simplified dataset for standalone operation (approx. 10-20nm steps)
    # Wavelength (nm), Irradiance (W/m^2/nm)
    # Updated to ASTM G173-03 Global Tilt (W/m^2/nm) - Standard 280-4000nm range
    # Corrected values to W/m^2/nm (Standard values are roughly 0.5~1.6 W/m2/nm in visible)
    # Data points selected to represent the spectrum shape accurately
    # PREVIOUS DATA WAS SCALED BY 100. FIXED TO STANDARD SI UNITS.
    am15_values = np.array([
        0.00102, 0.05094, 0.20527, 0.47139, 0.5018, 0.52798, 0.59817, 0.75507,
        0.70077, 0.79699, 1.1141, 1.0485, 1.1232, 0.87462, 1.3499, 1.5595,
        1.5291, 1.5077, 1.6181, 1.6224, 1.5451, 1.5481, 1.5236, 1.5446,
        1.4825, 1.5399, 1.474, 1.4816, 1.502, 1.3709, 1.4753, 1.4686,
        1.4739, 1.3924, 1.434, 1.3594, 1.3992, 1.4196, 1.3969, 1.1821,
        1.2823, 1.3175, 0.9855, 1.1285, 1.2195, 1.2341, 0.26604, 1.1608,
        1.1636, 1.091, 1.0725, 1.0559, 0.86188, 0.91601, 1.0157, 0.89372,
        0.98816, 0.96755, 0.93957, 0.92393, 0.7426, 0.62467, 0.74414,
        0.4321, 0.47181, 0.14726, 0.42066, 0.63461, 0.60468, 0.73227,
        0.73532
    ], dtype=float)

    wl = 290 + 10*np.arange(len(am15_values), dtype=float)
    return wl, am15_values

def compute_am15_integrals(wavelength_nm, eqe_percent):
    am15_lam, am15_irr = get_am15g_spectrum()

    wl = np.asarray(wavelength_nm, dtype=float)
    eqe = np.asarray(eqe_percent, dtype=float)

    # EQE % -> fraction
    eqe_frac = eqe if np.nanmax(eqe) > 1.0 else eqe

    # AM1.5G를 EQE 파장에 맞춰 보간
    am15_interp = np.interp(wl, am15_lam, am15_irr)

    # 너가 구상한 D열 식
    D = wl * eqe_frac * am15_interp / 1240.0 / 1000.0

    # 누적 적분 E (trapezoid cumulative)
    dlam = np.diff(wl)
    E = np.zeros_like(D)
    if len(wl) >= 2:
        E[1:] = np.cumsum(0.5*(D[1:] + D[:-1]) * dlam)

    return am15_interp, D, E

def calculate_jsc(wavelength_nm, eqe_percent):
    """
    Calculate Integrated Jsc (mA/cm^2) using AM1.5G spectrum.
    Jsc = q * integral(EQE * Phi_photon) dlambda
    """
    am15_lam, am15_irr = get_am15g_spectrum()
    
    # 1. EQE Unit Correction (Percent -> Decimal)
    if np.max(eqe_percent) > 1.0:
        eqe_decimal = eqe_percent / 100.0
    else:
        eqe_decimal = eqe_percent

    # [수정] EQE 데이터를 AM1.5G 파장(고해상도)에 맞춰 보간
    # 1. 적분 구간 설정 (EQE 측정 범위와 AM1.5G 범위의 교집합)
    min_w = max(np.min(wavelength_nm), np.min(am15_lam))
    max_w = min(np.max(wavelength_nm), np.max(am15_lam))
    
    # 2. 해당 구간의 AM1.5G 데이터 추출
    mask = (am15_lam >= min_w) & (am15_lam <= max_w)
    w_interp = am15_lam[mask]
    irr_interp = am15_irr[mask]
    
    # 3. EQE를 AM1.5G 파장으로 보간
    eqe_interp = np.interp(w_interp, wavelength_nm, eqe_decimal)
    
    # 4. Irradiance (W/m2/nm) -> Photon Flux (#/s/m2/nm)
    # lambda in meters
    lambda_m = w_interp * 1e-9
    photon_energy = h * c / lambda_m  # Joules
    photon_flux = irr_interp / photon_energy # (#/s/m^2/nm)
    
    # 5. Jsc Integral (A/m^2)
    # Jsc = e * integral(EQE * Photon_Flux) dlambda
    integrand = eqe_interp * photon_flux
    
    # NumPy 2.0 호환성: np.trapz가 제거되고 np.trapezoid로 변경됨
    if hasattr(np, 'trapezoid'):
        jsc_A_m2 = e * np.trapezoid(integrand, x=w_interp)
    else:
        jsc_A_m2 = e * np.trapz(integrand, x=w_interp)
    
    # 6. Convert to mA/cm^2
    # 1 A/m^2 = 1000 mA / 10000 cm^2 = 0.1 mA/cm^2
    jsc_mA_cm2 = jsc_A_m2 * 0.1
    
    return jsc_mA_cm2


def manual_fit_with_ui(hv, eqe, raw_x, raw_y, target_file, sheet_name):
    """
    개선 사항:
    EQE 분석 모드:
    1. Graph 1: Wavelength vs EQE (X-axis adjustable)
    2. Graph 2: Energy vs ln(EQE) (Linear fit for Urbach & Eg)
    3. Calculate Jsc, Urbach Energy, Eg
    """
    # 정렬/유효값 처리
    # EQE가 0 이하인 경우 로그 계산을 위해 제외하거나 작은 값으로 대체
    mask = np.isfinite(hv) & np.isfinite(eqe) & (eqe > 0)
    hv = hv[mask]
    eqe = eqe[mask]
    idx = np.argsort(hv)
    hv = hv[idx]
    eqe = eqe[idx]

    # Jsc 계산 (전체 데이터 사용)
    jsc_val = calculate_jsc(raw_x, raw_y)

    # 데이터 상태 관리
    data_state = {
        "x": hv,
        "y": np.log(eqe),  # Natural Log of EQE
        "y_label": r"$\ln(EQE)$"
    }

    state = {"result": None}

    # 1. Figure 생성 및 레이아웃 조정 (여백 확보가 핵심)
    fig, (ax_abs, ax, ax_deriv) = plt.subplots(1, 3, figsize=(16, 8))
    fig.subplots_adjust(top=0.80, bottom=0.35, wspace=0.3, left=0.05, right=0.98)

    # [Graph 1] EQE Spectrum (Wavelength vs EQE)
    ax_abs.plot(raw_x, raw_y, label="EQE Data", color='tab:blue', linewidth=1.5)

    # --- Add AM1.5G based cumulative curve on right axis ---
    am15_interp, D_int, E_cum = compute_am15_integrals(raw_x, raw_y)
    # ax_abs2 = ax_abs.twinx()
    # ax_abs2.plot(raw_x, E_cum, linestyle="--", linewidth=1.5, color="tab:red")
    # ax_abs2.set_ylabel("Integrated (a.u.)", fontsize=10)

    # 기존 ax_abs 위에 오른쪽 축 생성
    ax_abs2 = ax_abs.twinx()
    ax_abs2.plot(raw_x, E_cum, linestyle="--", linewidth=1.5, color="tab:red", label="Integrated")
    ax_abs2.set_ylabel(r"Intergrated $J_{sc}$ (mA/cm$^2$)",rotation=270, fontsize=10, labelpad=15)


    ax_abs2.tick_params(axis='y', labelsize=9)
    
    

    ax_abs.set_xlabel("Wavelength (nm)", fontsize=10)
    ax_abs.set_ylabel("EQE (%)", fontsize=10)
    ax_abs.set_title(f"EQE Spectrum", fontsize=12, pad=10)
    ax_abs.grid(True, linestyle='--', alpha=0.5)
    
    # X축 초기 설정 (300nm ~ Max)
    default_xmax = np.max(raw_x)
    ax_abs.set_xlim(300, default_xmax)

    # [Graph 2] Energy vs ln(EQE)
    line_tauc, = ax.plot(data_state["x"], data_state["y"], "o", markersize=4, label="Data", color='tab:orange', alpha=0.6)
    ax.set_xlabel("hν (eV)", fontsize=10)
    ax.set_ylabel(data_state["y_label"], fontsize=10)
    
    title_text = ax.set_title("Drag range to Fit", fontsize=12, color='blue', fontweight='bold', pad=10)
    ax.grid(True, linestyle='--', alpha=0.5)

    # [Graph 3] Derivative Plot
    # 초기에는 빈 그래프로 시작 (사용자 요청: 지정할 때마다 보여줘야 함)
    line_deriv, = ax_deriv.plot([], [], color='tab:green', label="Derivative")
    ax_deriv.set_xlabel("Energy (eV)", fontsize=10)
    ax_deriv.set_ylabel("d(ln EQE) / dE", fontsize=10)
    ax_deriv.set_title("Derivative Plot", fontsize=12, pad=10)
    ax_deriv.grid(True, linestyle='--', alpha=0.5)
    
    # Annotation for peak (initially hidden)
    annot_peak = ax_deriv.annotate("", xy=(0,0), xytext=(0, 15), textcoords='offset points',
                                   ha='center', va='bottom',
                                   bbox=dict(boxstyle='round,pad=0.3', fc='yellow', alpha=0.5),
                                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    annot_peak.set_visible(False)

    # 초기 뷰 범위 설정
    ax.set_xlim(np.min(data_state["x"]), np.max(data_state["x"]))
    ax_deriv.set_xlim(np.min(data_state["x"]), np.max(data_state["x"]))

    # Y축 자동 스케일링 함수
    def autoscale_y_to_visible():
        x = data_state["x"]
        y = data_state["y"]
        xmin, xmax = ax.get_xlim()
        vis = (x >= xmin) & (x <= xmax)
        if np.any(vis):
            ymin = np.min(y[vis])
            ymax = np.max(y[vis])
            ax.set_ylim(0, 1.1 * ymax if ymax > 0 else 1)
            margin = (ymax - ymin) * 0.1 if (ymax - ymin) > 0 else 1.0
            ax.set_ylim(ymin - margin, ymax + margin)

    autoscale_y_to_visible()

    # 피팅 라인 (초기엔 빈 값)
    fit_line, = ax.plot([], [], 'r-', linewidth=2.5, label="Fit")
    
    # 범위 표시용 수직선
    v1 = ax.axvline(np.nan, linestyle="--", color='gray', alpha=0.8)
    v2 = ax.axvline(np.nan, linestyle="--", color='gray', alpha=0.8)

    # 결과 테이블 (Figure 하단 우측)
    # [Sample, Jsc, Eu, Eg(Fit), Eg(Deriv)]
    table_ax = fig.add_axes([0.05, 0.02, 0.55, 0.20])
    table_ax.axis('off')

    # ---------------- UI 컨트롤 배치 ----------------

    # (1) Wavelength Max Input (좌측 상단)
    wave_ax = fig.add_axes([0.07, 0.22, 0.22, 0.045])                                         # (left, bottom, width, height)
    wave_box = TextBox(wave_ax, "WL max: ", initial=str(int(default_xmax)), label_pad=0.2)

    def update_wave_max(text):
        try:
            val = float(text)
            ax_abs.set_xlim(300, val)
            fig.canvas.draw_idle()
        except ValueError:
            pass
    
    wave_box.on_submit(update_wave_max)

    # (2) Origin Path Input (중앙 상단)
    path_ax = fig.add_axes([0.25, 0.85, 0.40, 0.05])
    auto_path = find_origin_path()
    origin_path_box = TextBox(path_ax, "Origin Path: ", initial=auto_path, label_pad=0.1)

    # (3) Browse Button (우측 상단)
    browse_ax = fig.add_axes([0.67, 0.85, 0.10, 0.05])
    browse_btn = Button(browse_ax, "Browse", hovercolor='0.9')

    

    def on_browse(event):
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.askopenfilename(
            title="Select Origin Executable",
            filetypes=[("Executable", "*.exe"), ("All Files", "*.*")]
        )
        root.destroy()
        if file_path:
            origin_path_box.set_val(file_path)

    browse_btn.on_clicked(on_browse)

    # (추가) Open File 버튼 (Browse 버튼 옆/오른쪽에 배치)
    open_ax = fig.add_axes([0.79, 0.85, 0.18, 0.05])
    open_btn = Button(open_ax, "Open File", hovercolor='0.9')

    def load_data_from_file(file_path: str):
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(str(p))

        local_sheet = p.stem

        if p.suffix.lower() in [".xlsx", ".xls"]:
            engine = 'xlrd' if p.suffix.lower() == '.xls' else None
            xls = pd.ExcelFile(p, engine=engine)
            sheets = xls.sheet_names
            # 일단 첫 시트 사용 (원하면 시트 선택창도 추가 가능)
            local_sheet = sheets[0]
            df_local = pd.read_excel(xls, sheet_name=local_sheet)
        else:
            df_local = pd.read_csv(p, sep=None, engine="python")

        lam = df_local.iloc[:, 0].to_numpy(dtype=float)
        y = df_local.iloc[:, 1].to_numpy(dtype=float)
        hv_local = 1240.0 / lam
        return p, local_sheet, lam, y, hv_local

    def apply_new_dataset(new_target_file, new_sheet_name, lam_nm, eqe_percent, hv_local):
        nonlocal target_file, sheet_name, raw_x, raw_y, hv, eqe, jsc_val

        # 1) 상태 변수 갱신
        target_file = new_target_file
        sheet_name = new_sheet_name
        raw_x = lam_nm
        raw_y = eqe_percent

        # 2) hv/eqe 재정렬 + ln(EQE) 업데이트
        mask = np.isfinite(hv_local) & np.isfinite(eqe_percent) & (eqe_percent > 0)
        hv = hv_local[mask]
        eqe = eqe_percent[mask]
        idx = np.argsort(hv)
        hv = hv[idx]
        eqe = eqe[idx]

        data_state["x"] = hv
        data_state["y"] = np.log(eqe)

        # 3) Jsc 재계산
        jsc_val = calculate_jsc(raw_x, raw_y)

        # 4) 그래프1(EQE 스펙트럼) 갱신: axis clear 후 재그림
        ax_abs.cla()
        ax_abs.plot(raw_x, raw_y, label="EQE Data", color='tab:blue', linewidth=1.5)
        ax_abs.set_xlabel("Wavelength (nm)", fontsize=10)
        ax_abs.set_ylabel("EQE (%)", fontsize=10)
        ax_abs.set_title("EQE Spectrum", fontsize=12, pad=10)
        ax_abs.grid(True, linestyle='--', alpha=0.5)

        # WL 박스 값으로 xlim 적용
        try:
            wlmax = float(wave_box.text)
        except:
            wlmax = float(np.max(raw_x))
            wave_box.set_val(str(int(wlmax)))
        ax_abs.set_xlim(300, wlmax)

        # 5) 그래프2(lnEQE) 갱신
        line_tauc.set_data(data_state["x"], data_state["y"])
        ax.set_xlim(float(np.min(data_state["x"])), float(np.max(data_state["x"])))
        autoscale_y_to_visible()

        # 6) 미분 그래프 초기화
        line_deriv.set_data([], [])
        annot_peak.set_visible(False)
        ax_deriv.set_xlim(float(np.min(data_state["x"])), float(np.max(data_state["x"])))

        # 7) fit line / vlines / title 초기화
        fit_line.set_data([], [])
        v1.set_xdata([np.nan, np.nan])
        v2.set_xdata([np.nan, np.nan])
        title_text.set_text("Drag range to Fit")
        title_text.set_color('blue')

        # 8) 슬라이더 범위 재설정 (중요)
        x_slider.valmin = float(np.min(data_state["x"]))
        x_slider.valmax = float(np.max(data_state["x"]))
        x_slider.set_val((x_slider.valmin, x_slider.valmax))

        # 9) 테이블 초기화
        table_ax.clear()
        table_ax.axis('off')
        table_data = [
            ["Sample", sheet_name],
            ["Jsc (mA/cm²)", f"{jsc_val:.2f}"],
            ["Urbach Eu (meV)", "-"],
            ["Eg (Fit) (eV)", "-"],
            ["Eg (Deriv Peak)", "-"]
        ]
        table = table_ax.table(cellText=table_data, loc='center', cellLoc='left', colWidths=[0.4, 0.6])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.5)

        # 10) 결과 초기화 (Confirm 전에 다시 span 선택해야 함)
        state["result"] = None

        

        fig.canvas.draw_idle()

    def on_open_file(event):
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.askopenfilename(
            title="Select EQE data file",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("CSV/TSV", "*.csv *.tsv *.txt"), ("All files", "*.*")]
        )
        root.destroy()

        if not file_path:
            return

        try:
            p, sh, lam, y, hv_local = load_data_from_file(file_path)
            apply_new_dataset(p, sh, lam, y, hv_local)
        except Exception as ex:
            messagebox.showerror("Load Error", str(ex))

    open_btn.on_clicked(on_open_file)

    # (4) View Range Slider (하단)
    slider_ax = fig.add_axes([0.38, 0.22, 0.26, 0.03])  # 가운데(ax) 폭에 맞춤
    x_slider = RangeSlider(
        ax=slider_ax,
        label="X-Axis View",
        valmin=float(np.min(data_state["x"])),
        valmax=float(np.max(data_state["x"])),
        valinit=(np.min(data_state["x"]), np.max(data_state["x"]))
    )

    def on_slider_change(val):
        ax.set_xlim(val[0], val[1])
        ax_deriv.set_xlim(val[0], val[1])
        autoscale_y_to_visible()
        fig.canvas.draw_idle()

    x_slider.on_changed(on_slider_change)

    # ---------------- 피팅 로직 (SpanSelector) ----------------

    def on_span_select(xmin, xmax):
        x = data_state["x"]
        y = data_state["y"]
        if xmin == xmax: return # 클릭만 했을 경우 무시
        
        fitMin, fitMax = (min(xmin, xmax), max(xmin, xmax))
        sel = (x >= fitMin) & (x <= fitMax)
        
        if np.sum(sel) < 2:
            title_text.set_text("Not enough points selected!")
            fig.canvas.draw_idle()
            return

        # 선형 회귀 (Linear Fit)
        try:
            m, b = np.polyfit(x[sel], y[sel], 1)
        except Exception:
            return

        if m == 0: return

        # Urbach Energy (Eu)
        # Slope m = d(ln EQE) / dE
        # Eu = 1 / m (if natural log) -> result in eV. Convert to meV.
        Eu_meV = (1.0 / abs(m)) * 1000.0

        # Bandgap (Eg) - Linear Fit
        # Definition: Intersection of fit line with ln(Max EQE)
        # y_max = ln(max_eqe) = m * Eg + b  => Eg = (ln(max_eqe) - b) / m
        max_log_eqe = np.max(data_state["y"])
        Eg = (max_log_eqe - b) / m

        # Bandgap (Eg) - Derivative Method
        # Calculate d(lnEQE)/dE in the selected range and find peak
        # Smoothing first to avoid noise
        try:
            # Smoothing window based on selection size
            wl = min(11, len(y[sel]))
            if wl % 2 == 0: wl -= 1
            if wl < 3: wl = 3
            
            y_smooth = savgol_filter(y[sel], window_length=wl, polyorder=2)
            dy = np.gradient(y_smooth, x[sel])
            idx_max = np.argmax(dy)
            Eg_deriv = x[sel][idx_max]
            val_max = dy[idx_max]
            
            # Update Derivative Plot (Graph 3)
            line_deriv.set_data(x[sel], dy)
            ax_deriv.relim()
            ax_deriv.autoscale_view()
            
            # Update annotation to show peak in selected range
            annot_peak.set_text(f"Peak: {Eg_deriv:.3f} eV")
            annot_peak.xy = (Eg_deriv, val_max)

            # ✅ 아래로 20pt 내리기 (항상 아래)
            annot_peak.set_position((0, -20))          # offset points
            annot_peak.set_ha("center")
            annot_peak.set_va("top")
            annot_peak.set_visible(True)

            
            
        except:
            Eg_deriv = 0.0
            line_deriv.set_data([], [])
            annot_peak.set_visible(False)
        
        # R2 계산
        yfit = m*x[sel] + b
        SSres = np.sum((y[sel] - yfit)**2)
        SStot = np.sum((y[sel] - np.mean(y[sel]))**2)
        R2 = 1 - SSres / SStot if SStot != 0 else np.nan

        # 그래프 업데이트
        xline = np.linspace(fitMin, fitMax, 200)
        fit_line.set_data(xline, m*xline + b)
        v1.set_xdata([fitMin, fitMin])
        v2.set_xdata([fitMax, fitMax])
        
        # [핵심] 결과값을 Title에 표시하여 가독성 확보
        title_text.set_text(f"Eg(Fit)={Eg:.3f} eV | Eg(Deriv)={Eg_deriv:.3f} eV")
        title_text.set_color('red')

        # 테이블 업데이트
        table_ax.clear()
        table_ax.axis('off')
        table_data = [
            ["Sample", sheet_name],
            ["Jsc (mA/cm²)", f"{jsc_val:.2f}"],
            ["Urbach Eu (meV)", f"{Eu_meV:.1f}"],
            ["Eg (Fit) (eV)", f"{Eg:.3f}"],
            ["Eg (Deriv Peak)", f"{Eg_deriv:.3f} eV"]
        ]
        table = table_ax.table(cellText=table_data, loc='center', cellLoc='left', colWidths=[0.4, 0.6])
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.5)

        # 현재 뷰 상태 저장 (Origin Export용)
        tauc_xlim = ax.get_xlim()
        tauc_ylim = ax.get_ylim()
        abs_xlim = ax_abs.get_xlim()
        abs_ylim = ax_abs.get_ylim()

        # 결과 튜플 저장
        state["result"] = (Eg, Eg_deriv, Eu_meV, jsc_val, R2, m, b, x[sel], y[sel], (fitMin, fitMax), 
                           data_state["x"], data_state["y"], data_state["y_label"], 
                           origin_path_box.text, raw_x, raw_y,
                           tauc_xlim, tauc_ylim, abs_xlim, abs_ylim)
        fig.canvas.draw_idle()

    # [핵심 수정] useblit=False로 설정하여 화면 잔상(Ghosting) 현상 제거
    span = SpanSelector(
        ax, on_span_select, "horizontal",
        useblit=False,  # <-- 이것이 잔상 해결의 열쇠입니다.
        interactive=True, 
        props=dict(alpha=0.2, facecolor='red')
    )

    # (5) Confirm Button (우측 하단)
    btn_ax = fig.add_axes([0.80, 0.10, 0.15, 0.05])
    btn = Button(btn_ax, "Confirm", hovercolor='0.95')

    def on_confirm(event):
        if state["result"] is None:
            # 피팅하지 않고 눌렀을 때 경고
            title_text.set_text("Please SELECT range first!")
            fig.canvas.draw_idle()
            return
        
        # Confirm 시점의 최신 상태(경로, 줌 상태 등) 업데이트
        res_list = list(state["result"])
        res_list[13] = origin_path_box.text  # 경로 업데이트
        res_list[16] = ax.get_xlim()         # 줌 상태 업데이트
        res_list[17] = ax.get_ylim()
        res_list[18] = ax_abs.get_xlim()
        res_list[19] = ax_abs.get_ylim()
        state["result"] = tuple(res_list)

        # Export 창 호출
        show_export_dialog(target_file, sheet_name, state["result"])

    btn.on_clicked(on_confirm)

    def _on_fig_close(event):
        # 열려있는 모든 figure 닫기
        plt.close('all')
        # 혹시 떠있는 tk 루트가 있으면 정리 (있을 때만)
        try:
            import tkinter as _tk
            _tk._default_root and _tk._default_root.destroy()
        except:
            pass

    fig.canvas.mpl_connect("close_event", _on_fig_close)

    plt.show()
    return state["result"]

# -----------------------------------------------------------
# [함수 3] 결과 내보내기 UI (기존 기능 유지)
# -----------------------------------------------------------
def show_export_dialog(target_file, sheet_name, result_data):
    # 데이터 언패킹
    Eg_m, Eg_deriv_m, Eu_m, Jsc_m, R2_m, m_m, b_m, x_sel, y_sel, (fitMin, fitMax), x_full, y_full, y_label_str, origin_path, raw_x, raw_y, tauc_xlim, tauc_ylim, abs_xlim, abs_ylim = result_data
    

    # Derivation Data Calculation (Shared for Excel and Origin)
    # d(lnEQE)/dE
    try:
        y_smooth_full = savgol_filter(y_full, window_length=min(11, len(y_full)), polyorder=2)
        deriv_y = np.gradient(y_smooth_full, x_full)
    except:
        deriv_y = np.zeros_like(y_full)

    def save_excel():
        am15_interp, D_int, E_cum = compute_am15_integrals(raw_x, raw_y)
        # --- Result summary ---
        res_data = {
            "Sample": [sheet_name],
            "Integrated Jsc (mA/cm2)": [Jsc_m],
            "Urbach Energy (meV)": [Eu_m],
            "Eg (Fit) (eV)": [Eg_m],
            "Eg (Deriv) (eV)": [Eg_deriv_m],
            "R2": [R2_m],
            "Slope": [m_m],
            "Intercept": [b_m],
            "Fit Range Min (eV)": [fitMin],
            "Fit Range Max (eV)": [fitMax]
        }
        df_res = pd.DataFrame(res_data)

        

        # --- Sheet A: EQE spectrum data ---
        df_eqe = pd.DataFrame({
            "Wavelength (nm)": raw_x,
            "EQE (%)": raw_y,
            "AM1.5G (W/m2/nm)": am15_interp,
            "Integrand(col(A)*col(B)*col(C)/1240/1000)": D_int,
            "Integrated": E_cum
        })

        # Fit line을 전체 Energy 범위로 길게 생성
        x_min_all = float(np.nanmin(x_full))
        x_max_all = float(np.nanmax(x_full))
        fit_x_line = np.linspace(x_min_all, x_max_all, 200)
        fit_y_line = m_m * fit_x_line + b_m

        # --- Selected (linear) region marker ---
        # x_full, y_full = (Energy, ln(EQE)) full data
        sel_mask = (x_full >= fitMin) & (x_full <= fitMax)

        # --- Sheet B: Urbach analysis data ---
        df_urbach = pd.DataFrame({
            "Energy (eV)": x_full,
            "ln(EQE)": y_full,
            
            #"d(lnEQE)/dE": deriv_y,
            #"In_Linear_Range (0/1)": sel_mask.astype(int)
        
        })

        # 선택 구간만 따로 보고 싶으면 컬럼 추가(빈칸 포함)
        #df_urbach["Linear_E (eV)"] = np.where(sel_mask, x_full, np.nan)
        #df_urbach["Linear_ln(EQE)"] = np.where(sel_mask, y_full, np.nan)

        # Fit line도 같이 넣기 (길이가 다르므로 별도 컬럼으로 붙임)
        # 길이 맞추려고 최대 길이에 맞춰 NaN padding
        max_len = max(len(df_urbach), len(fit_x_line))

        def pad(arr, n):
            arr = np.asarray(arr, dtype=float)
            if len(arr) < n:
                return np.concatenate([arr, np.full(n - len(arr), np.nan)])
            return arr

        df_urbach2 = pd.DataFrame({
            "Fit_X (eV)": pad(fit_x_line, max_len),
            "Fit_Y (lnEQE)": pad(fit_y_line, max_len),
        })

        # 두 DataFrame을 가로로 합치되 index 길이 통일
        df_urbach = df_urbach.reindex(range(max_len))
        df_urbach = pd.concat([df_urbach, df_urbach2], axis=1)

        out_excel = target_file.parent / f"{target_file.stem}_result.xlsx"
        try:
            with pd.ExcelWriter(out_excel, engine="openpyxl") as writer:
                df_res.to_excel(writer, sheet_name="Result", index=False)
                df_eqe.to_excel(writer, sheet_name="EQE_Data", index=False)
                df_urbach.to_excel(writer, sheet_name="Urbach_Data", index=False)

            messagebox.showinfo("Success", f"Saved to Excel:\n{out_excel}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save Excel:\n{e}")


    def export_origin():
        am15_interp, D_int, E_cum = compute_am15_integrals(raw_x, raw_y)

        # -------------------------
        # 0) 데이터 준비 (여기서 반드시 정의되어 있어야 함)
        # -------------------------
        lam = np.asarray(raw_x, dtype=float)          # wavelength (nm)
        eqe = np.asarray(raw_y, dtype=float)          # EQE (%)
        am15 = np.asarray(am15_interp, dtype=float)   # AM1.5G (W/m2/nm)
        dint = np.asarray(D_int, dtype=float)         # integrand (D열)
        cum  = np.asarray(E_cum, dtype=float)         # cumulative integral (E열)

        if not WIN32COM_AVAILABLE:
            messagebox.showerror("Error", "pywin32 module not installed.\n(pip install pywin32)")
            return

        try:
            # 1) Origin 연결
            origin = None
            try:
                origin = win32com.client.Dispatch("Origin.ApplicationSI")
                origin.Visible = 1
            except:
                if os.path.exists(origin_path):
                    subprocess.Popen([origin_path])
                    for _ in range(30):
                        time.sleep(1)
                        try:
                            origin = win32com.client.Dispatch("Origin.ApplicationSI")
                            origin.Visible = 1
                            break
                        except:
                            pass

            if origin is None:
                messagebox.showerror("Error", f"Could not connect to Origin.\nCheck path: {origin_path}")
                return

            # 2) 워크북 생성 (2 = Workbook)
            wb_name = origin.CreatePage(2, f"EQE_{sheet_name}"[:10], "Origin")
            origin.Execute(f"page.active$ = {wb_name};")

            # 안전: 첫 시트 이름/개수 맞추기
            # 시트 2개 필요: EQE_Data, Urbach_Data
            origin.Execute("wks.name$ = \"EQE_Data\";")         # 첫 시트 rename
            origin.Execute("page.nlayers = 2;")                # 시트 2개
            origin.Execute("layer2.name$ = \"Urbach_Data\";")  # 두 번째 시트 rename

            # ---------- 유틸: NaN/inf 제거해서 리스트로 ----------
            def clean_list(arr):
                arr = np.asarray(arr, dtype=float)
                arr = np.where(np.isfinite(arr), arr, np.nan)
                # Origin PutWorksheet는 None/NaN도 대체로 괜찮지만, 안전하게 NaN 유지
                return [float(x) if np.isfinite(x) else np.nan for x in arr]

            # =========================
            # Sheet 1) EQE_Data
            # =========================
            origin.Execute("layer -s 1;")       # 1번 시트 활성화
            origin.Execute("wks.ncols = 5;")    # 5열
            origin.Execute("wks.col1.type = 4; wks.col2.type = 1;")  # X, Y

            origin.Execute("wks.col1.lname$ = \"Wavelength\"; wks.col1.units$ = \"nm\";")
            origin.Execute("wks.col2.lname$ = \"EQE\"; wks.col2.units$ = \"%\";")
            origin.Execute('wks.col3.type=1; wks.col3.lname$="AM1.5G";     wks.col3.units$="W/m2/nm";')
            origin.Execute('wks.col4.type=1; wks.col4.lname$="Integrand";  wks.col4.units$="(a.u.)";')
            origin.Execute('wks.col5.type=1; wks.col5.lname$="CumJsc";     wks.col5.units$="(a.u.)";')

            origin.PutWorksheet(f"[{wb_name}]EQE_Data", clean_list(raw_x), 0, 0)
            origin.PutWorksheet(f"[{wb_name}]EQE_Data", clean_list(raw_y), 0, 1)
            origin.PutWorksheet(f"[{wb_name}]EQE_Data", clean_list(am15), 0, 2)
            origin.PutWorksheet(f"[{wb_name}]EQE_Data", clean_list(dint), 0, 3)
            origin.PutWorksheet(f"[{wb_name}]EQE_Data", clean_list(cum), 0, 4)

            # =========================
            # Sheet 2) Urbach_Data
            #   Energy, ln(EQE), Fit_X, Fit_Y
            # =========================
            origin.Execute("layer -s 2;")       # 2번 시트 활성화
            origin.Execute("wks.ncols = 4;")    # 4열
            
            #이거 x1y1x2y2 하는 코드
            origin.Execute("wks.col1.type = 4; wks.col2.type = 1;")
            origin.Execute("wks.col3.type = 4; wks.col4.type = 1;")

            # 타입
            #origin.Execute("wks.col1.type = 4;")  # X
            #origin.Execute("wks.col2.type = 1;")  # Y
            #origin.Execute("wks.col3.type = 1;")  # Y

            origin.Execute("wks.col1.lname$ = \"Energy\"; wks.col1.units$ = \"eV\";")
            origin.Execute("wks.col2.lname$ = \"ln(EQE)\"; wks.col2.units$ = \"a.u.\";")
            origin.Execute("wks.col3.lname$ = \"Fit_X\"; wks.col3.units$ = \"eV\";")
            origin.Execute("wks.col4.lname$ = \"Fit_Y\"; wks.col4.units$ = \"a.u.\";")

            # Fit line (엑셀 저장 때처럼)
            x_min_all = float(np.nanmin(x_full))
            x_max_all = float(np.nanmax(x_full))
            fit_x_line = np.linspace(x_min_all, x_max_all, 200)
            fit_y_line = m_m * fit_x_line + b_m

            # 길이 다르니까 Origin은 각 열에 각자 길이 넣어도 되지만,
            # PutWorksheet는 "열 단위"로 들어가므로 그냥 각각 넣으면 됨.
            origin.PutWorksheet(f"[{wb_name}]Urbach_Data", clean_list(x_full), 0, 0)
            origin.PutWorksheet(f"[{wb_name}]Urbach_Data", clean_list(y_full), 0, 1)
            origin.PutWorksheet(f"[{wb_name}]Urbach_Data", clean_list(fit_x_line), 0, 2)
            origin.PutWorksheet(f"[{wb_name}]Urbach_Data", clean_list(fit_y_line), 0, 3)

            # =========================================================
            # [3] 그래프 생성 (Graph Page)
            #  - Graph 1: EQE Spectrum (Wavelength vs EQE)
            #  - Graph 2: ln(EQE) + Fit line (Energy vs ln(EQE), FitX/FitY)
            # =========================================================

            # -------------------------
            # Graph 1) EQE Spectrum
            # -------------------------
            #gp_eqe = origin.CreatePage(3, f"EQE_{sheet_name}"[:10], "Origin")
            #origin.Execute(f"page.active$ = {gp_eqe};")
            #origin.Execute("layer -n 1;")

            # [EQE_Data] sheet: col1(X)=Wavelength, col2(Y)=EQE
            origin.Execute(f"plotxy iy:=[EQESheet1]EQE_Data!(1,2) plot:=202 ogl:=[<new template:=doubleY>]")  # line
            
            origin.Execute(f"plotxy iy:=[EQESheet1]EQE_Data!(1,5) plot:=202 ogl:=2;")
            
            #origin.Execute("layer -d;")

            # ---- layer2: 오른쪽 Y2만 사용 ----
            # origin.Execute("layer -s 2;")
            # origin.Execute("layer.y.showAxes=0;")     # 왼쪽 Y off (겹침 해결 핵심)
            # origin.Execute("layer.y2.showAxes=3;")    # 오른쪽 Y2 on
            # origin.Execute("layer.y2.ticks=1;")       # 오른쪽 tick 표시(선택)



            # UI에서 저장된 축 범위 그대로 고정
            origin.Execute(f"layer.x.from = 300; layer.x.to = 800;")
            origin.Execute(f"layer.y.from = -5; layer.y.to = 100;")
            origin.Execute("layer.x.type=0; layer.y.type=0;")

            origin.Execute('label -x1 "Wavelength (nm)";')
            origin.Execute('label -y1 "EQE (%)";')

            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")
        
            origin.Execute("layer.y.inc = 10;")
            origin.Execute("layer.x.inc = 200;")
            origin.Execute("layer.y.label.pt = 30;")
            origin.Execute("layer.x.label.pt = 30;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.y2.ticks = 0;")

            origin.Execute("layer -s 2;")
            origin.Execute('label -yr Intergrated \i(J)\-(SC)')

            origin.Execute("layer.y.showAxes=2;")     # 왼쪽 Y off (겹침 해결 핵심)

            origin.Execute("layer.y.inc = 5;")
            origin.Execute("layer.x.inc = 200;")

            origin.Execute("layer.y2.label.pt = 30;")

            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.y.showAxes = 3;")

            origin.Execute("yr.fsize = 40;")
            origin.Execute("layer.y.showAxes=2;")
            origin.Execute("layer.y2.color=color(black);")
            origin.Execute("layer.x.color=color(black);")

            #origin.Execute("layer.x2.ticks = 0;")
            #origin.Execute("layer.y2.ticks = 0;")


            # -------------------------
            # Graph 2) ln(EQE) + Fit line
            # -------------------------
            gp_ln = origin.CreatePage(3, "lnEQE"[:10], "Origin")
            origin.Execute(f"page.active$ = {gp_ln};")

            # Urbach_Data 시트:
            # col1(X)=Energy, col2(Y)=ln(EQE), col3(X2)=Fit_X, col4(Y2)=Fit_Y
            # 1) scatter: (1,2)
            origin.Execute(f"plotxy iy:=[{wb_name}]Urbach_Data!(1,2) plot:=201 o:=[lnEQE]1!;")

            # 2) Fit line: (3.4) 을 같은 레이어에 추가 
            # ***이거 찾는다고 ㅈ뱅이 ㅅㅂㅋㅋ***
            origin.Execute(f"plotxy iy:=[{wb_name}]Urbach_Data!(3,4) plot:=200 o:=[lnEQE]1!;")

            #origin.Execute("layer -d;")

            # UI에서 저장된 ln(EQE) 그래프 축 범위 그대로 고정
            origin.Execute(f"layer.x.from = {tauc_xlim[0]}; layer.x.to = {tauc_xlim[1]};")
            origin.Execute(f"layer.y.from = {tauc_ylim[0]}; layer.y.to = {tauc_ylim[1]};")
            origin.Execute("layer.x.type=0; layer.y.type=0;")


            origin.Execute("layer.y.inc = 2;")
            origin.Execute("layer.x.inc = 0.2;")

            origin.Execute("xb.fsize = 40;")
            origin.Execute("yl.fsize = 40;")
            origin.Execute("layer.y.label.pt = 30;")
            origin.Execute("layer.x.label.pt = 30;")
            origin.Execute("layer.x.showAxes = 3;")
            origin.Execute("layer.y.showAxes = 3;")
            origin.Execute("layer.x2.ticks = 0;")
            origin.Execute("layer.y2.ticks = 0;")



            origin.Execute('label -x1 "Energy (eV)";')
            origin.Execute('label -y1 "ln(EQE)";')

            # Fit 선(두번째 플롯)만 두께 변경
            origin.Execute("layer.plot = 2; set %C -w 2000;")
            origin.Execute("layer.plot = 1;")

            # -------------------------
            # (선택) 창 정렬
            # -------------------------
            origin.Execute("doc -uw; tile -h;")

            origin.Visible = 1
            messagebox.showinfo("Success", "Origin workbook created (worksheets only).")

        except Exception as e:
            messagebox.showerror("Error", f"Origin Error: {e}")

    # 팝업 UI
    root = tk.Tk()
    root.title("Export")
    root.geometry("300x160")
    root.attributes('-topmost', True)
    
    lbl = tk.Label(root, text=f"Jsc: {Jsc_m:.2f} mA/cm²\nEg(Fit): {Eg_m:.3f} eV\nEg(Deriv): {Eg_deriv_m:.3f} eV", font=("Arial", 11, "bold"), pady=15)
    lbl.pack()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=5)

    btn_excel = tk.Button(btn_frame, text="Excel Save", command=save_excel, width=12, bg="#4CAF50", fg="white")
    btn_excel.pack(side=tk.LEFT, padx=5)

    btn_origin = tk.Button(btn_frame, text="Origin Plot", command=export_origin, width=12, bg="#FF9800", fg="black")
    btn_origin.pack(side=tk.LEFT, padx=5)

    def on_close():
        try:
            root.quit()
            root.destroy()
        except:
            pass
        #plt.close('all')   # matplotlib도 같이 정리

    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()

# -----------------------------------------------------------
# [메인 실행]
# -----------------------------------------------------------
def run_eqe_analysis_gui(parent=None, preset_path=None):
    """
    customtkinter 기반 GUI로 파일 선택/시트 선택 후 EQE 분석 실행
    - preset_path: 외부에서 파일 경로를 이미 알고 있으면 넣어줄 수 있음
    """

    # 1) 파일 선택 (GUI)
    if preset_path is None:
        root = parent if parent is not None else tk.Tk()
        if parent is None:
            root.withdraw()
            root.attributes('-topmost', True)

        file_path = filedialog.askopenfilename(
            title="Select EQE data file",
            filetypes=[
                ("Excel files", "*.xlsx *.xls"),
                ("CSV/TSV files", "*.csv *.tsv *.txt"),
                ("All files", "*.*")
            ]
        )

        if parent is None:
            root.destroy()

        if not file_path:
            return
        target_file = Path(file_path)
    else:
        target_file = Path(preset_path)

    if not target_file.exists():
        messagebox.showerror("Error", f"File not found:\n{target_file}")
        return

    # 2) 데이터 로드 + 시트 선택 (엑셀이면)
    df = None
    sheet_name = target_file.stem

    if target_file.suffix.lower() in [".xlsx", ".xls"]:
        try:
            engine = 'xlrd' if target_file.suffix.lower() == '.xls' else None
            xls = pd.ExcelFile(target_file, engine=engine)
            sheet_names = xls.sheet_names

            if len(sheet_names) == 1:
                sheet_name = sheet_names[0]
            else:
                # ---- customtkinter로 시트 선택 창 ----
                import customtkinter as ctk

                chosen = {"name": None}

                sheet_win = ctk.CTkToplevel(parent) if parent is not None else ctk.CTkToplevel()
                sheet_win.title("Select Sheet")
                sheet_win.geometry("360x260")
                sheet_win.attributes('-topmost', True)

                label = ctk.CTkLabel(sheet_win, text="분석할 시트를 선택하세요", font=("Segoe UI", 14))
                label.pack(pady=10)

                var = ctk.StringVar(value=sheet_names[0])
                opt = ctk.CTkOptionMenu(sheet_win, values=sheet_names, variable=var)
                opt.pack(pady=10)

                def confirm_sheet():
                    chosen["name"] = var.get()
                    sheet_win.destroy()

                btn = ctk.CTkButton(sheet_win, text="확인", command=confirm_sheet)
                btn.pack(pady=15)

                sheet_win.grab_set()
                sheet_win.wait_window()

                if chosen["name"] is None:
                    return
                sheet_name = chosen["name"]

            df = pd.read_excel(xls, sheet_name=sheet_name)

        except Exception as e:
            messagebox.showerror("Excel Load Error", f"엑셀 로드 실패:\n{e}")
            return

    else:
        # CSV/TSV/TXT
        try:
            df = pd.read_csv(target_file, sep=None, engine='python')
        except Exception as e:
            messagebox.showerror("Text Load Error", f"텍스트 파일 로드 실패:\n{e}")
            return

    # 3) 분석 실행
    try:
        lambda_nm = df.iloc[:, 0].to_numpy(dtype=float)
        EQE       = df.iloc[:, 1].to_numpy(dtype=float)
    except Exception as e:
        messagebox.showerror("Data Error", f"첫 두 컬럼을 숫자로 읽을 수 없습니다:\n{e}")
        return

    hv = 1240.0 / lambda_nm

    manual_fit_with_ui(hv, EQE, lambda_nm, EQE, target_file, sheet_name)

import customtkinter as ctk

class AnalysisWindow(ctk.CTkToplevel):
    """메인 GUI에서 호출하기 위한 래퍼 클래스"""
    def __init__(self, parent, origin_path="", api_key=""):
        super().__init__(parent)
        self.title("EQE Analysis")
        self.geometry("400x200")

        self.passed_origin_path = origin_path
        self.passed_api_key = api_key

        # 안내 라벨
        label = ctk.CTkLabel(self, text="EQE 분석을 시작합니다.\n아래 버튼을 클릭하세요.", font=("Segoe UI", 14))
        label.pack(pady=30)

        # 분석 시작 버튼
        btn = ctk.CTkButton(self, text="EQE 분석 시작", command=self.start_analysis)
        btn.pack(pady=10)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

    def start_analysis(self):
        self.destroy()
        run_eqe_analysis_gui(parent=None)  # 또는 parent=self.master

    def on_closing(self):
        # ✅ 이 창 닫을 때 mainloop까지 종료
        try:
            self.destroy()
        except:
            pass

        try:
            if self.master is not None:
                self.master.quit()      # mainloop 탈출
                self.master.destroy()   # root 제거
        except:
            pass
        self.destroy()


if __name__ == "__main__":
    import customtkinter as ctk
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()  # 메인 루트 숨김 (필요하면 지워도 됨)

    win = AnalysisWindow(root)
    win.mainloop()