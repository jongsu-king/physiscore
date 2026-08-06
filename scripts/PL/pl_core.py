"""
pl_core.py - Fixed Origin Connection & Gaussian Fit Visualization
"""
import pandas as pd
import numpy as np
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    genai = None
    GENAI_AVAILABLE = False
from scipy.signal import find_peaks, savgol_filter
from scipy.integrate import simpson
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.optimize import curve_fit
import os
import subprocess
import time

# --- 1. Origin Connection Logic (Same as XRD) ---
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

def connect_to_origin(origin_exe_path: str = "", log_callback=None):
    """
    Connect to Origin application using XRD-style robust logic.
    """
    if not WIN32COM_AVAILABLE:
        if log_callback: log_callback("Error: 'pywin32' library not installed.")
        return None

    # 1. Try connecting to existing instance
    try:
        origin = win32com.client.Dispatch("Origin.ApplicationSI")
        origin.Visible = 1
        if log_callback: log_callback("Connected to running Origin instance.")
        return origin
    except: pass
        
    # 2. Try launching new instance
    if origin_exe_path and os.path.exists(origin_exe_path):
        if log_callback: log_callback(f"Launching Origin from: {origin_exe_path}...")
        try:
            subprocess.Popen([origin_exe_path])
            # Wait loop (max 60s)
            for i in range(60):
                time.sleep(1)
                try:
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1
                    if log_callback: log_callback("New Origin instance started.")
                    return origin
                except:
                    if i % 5 == 0 and log_callback: log_callback("Waiting for Origin...")
        except Exception as e:
            if log_callback: log_callback(f"Failed to launch Origin: {e}")
    else:
        if log_callback: log_callback("Origin EXE path not found or invalid.")
            
    return None

def plot_all_pl_to_origin(origin, x, data_dict, title="PL_Data"):
    """
    Plot multiple PL curves to Origin.
    data_dict: { "SampleName": y_array, ... }
    """
    if not origin: return
        
    try:
        # Create Workbook
        name = title[:10]
        wb = origin.CreatePage(2, name, "Origin")
        
        # Setup Columns
        num_cols = 1 + len(data_dict) # X + N * Y
        origin.Execute(f"page.active$ = {wb};")
        origin.Execute(f"wks.ncols = {num_cols};")
        
        # Col 1: X (Wavelength)
        origin.PutWorksheet(f"[{wb}]Sheet1", x.tolist(), 0, 0)
        origin.Execute('wks.col1.lname$ = "Wavelength";')
        origin.Execute('wks.col1.units$ = "nm";')
        origin.Execute("wks.col1.type = 4;")
        
        col_idx = 1
        for label, y_data in data_dict.items():
            label_str = str(label).strip()
            if not label_str or label_str.lower().startswith("unnamed"):
                label_str = str(col_idx)
            # Put Y Data
            origin.PutWorksheet(f"[{wb}]Sheet1", y_data.tolist(), 0, col_idx)

            # Set Column Properties (Ensure Workbook is active)
            origin.Execute(f"page.active$ = {wb};")
            origin.Execute(f'wks.col{col_idx+1}.lname$ = "{label_str}";')
            origin.Execute(f"wks.col{col_idx+1}.type = 1;")

            col_idx += 1

        # Plot all Y columns at once (Dark_JV style)
        origin.Execute(f"plotxy iy:=[{wb}]Sheet1!(1,2:{num_cols}) plot:=200;")

        # Increment colors per plot + match Dark_JV line width
        color_indices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        for plot_idx in range(1, num_cols):
            color = color_indices[(plot_idx - 1) % len(color_indices)]
            origin.Execute(f"layer -p {plot_idx};")
            origin.Execute(f"set %C -c {color};")
            origin.Execute("set %C -w 1500;")

        # Style
        origin.Execute("xb.fsize = 40;")
        origin.Execute("yl.fsize = 40;")
        origin.Execute("layer.x.label.pt = 30;")
        origin.Execute("layer.y.label.pt = 30;")
        origin.Execute("layer.x.showAxes = 3;")
        origin.Execute("layer.y.showAxes = 3;")
        origin.Execute("layer.x.showLabels = 1;")
        origin.Execute("label -xl Wavelength (nm);")
        origin.Execute("label -yl Intensity (a.u.);")
        origin.Execute("layer.y.showLabels = 0;")
        origin.Execute("layer.y.ticks = 0;")
        origin.Execute("layer.x2.ticks = 0;")
        origin.Execute("layer.y2.ticks = 0;")
        # X-axis range based on data
        x_min = float(np.nanmin(x))
        x_max = float(np.nanmax(x))
        origin.Execute(f"layer.x.from = {x_min};")
        origin.Execute(f"layer.x.to = {x_max};")
        origin.Execute("doc -uw;") # Update window
        
    except Exception as e:
        print(f"Origin Plot Error: {e}")

# --- Data Processing Logic ---

def load_data_preview(file_path):
    """
    Load PL data with smart sheet and column detection.
    - Sheet Priority: 'pl' in name > Content check (nm/wave) > 'Sheet1' > first sheet.
    - Column Priority: Finds 'nm'/'wave'/'energy' for X-axis, treats others as Y.
    """
    try:
        filename = os.path.basename(file_path)
        
        # 1. Load data from Excel or CSV
        if file_path.endswith(('.xlsx', '.xls')):
            xl = pd.ExcelFile(file_path)
            sheet_names = xl.sheet_names
            
            # 1. Name Match
            target_sheet = next((s for s in sheet_names if "pl" in s.lower()), None)
            
            # 2. Content Match (If name match fails)
            if target_sheet is None:
                for s in sheet_names:
                    try:
                        # Read just the header to check columns
                        df_tmp = pd.read_excel(file_path, sheet_name=s, nrows=1)
                        cols_str = " ".join([str(c).lower() for c in df_tmp.columns])
                        if any(k in cols_str for k in ['nm', 'wave', 'lambda', 'length', 'energy']):
                            target_sheet = s
                            break
                    except: continue
            
            # 3. Fallback
            if target_sheet is None:
                target_sheet = "Sheet1" if "Sheet1" in sheet_names else sheet_names[0]
            df = pd.read_excel(file_path, sheet_name=target_sheet)
        else:
            try: 
                # Try to read with separator auto-detection
                df = pd.read_csv(file_path, sep=None, engine='python')
                # If header is numeric, re-read without header
                if len(df.columns) > 0 and str(df.columns[0]).replace('.','',1).isdigit():
                     df = pd.read_csv(file_path, sep=None, engine='python', header=None)
            except: 
                df = pd.read_csv(file_path, sep=None, engine='python', header=None)
        
        # 2. Clean and find X-axis column
        df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
        df.columns = [str(c) for c in df.columns] # Ensure column names are strings
        
        cols_lower = [c.lower() for c in df.columns]
        x_col_name = None
        x_col_idx = -1
        
        # Find X column by keyword
        for i, c in enumerate(cols_lower):
            if any(k in c for k in ['nm', 'wave', 'lambda', 'length', 'energy']):
                x_col_name = df.columns[i]
                x_col_idx = i
                break
        
        # Fallback to first column if no keyword match
        if x_col_name is None:
            x_col_name = df.columns[0]
            x_col_idx = 0
            
        # 3. Reorganize DataFrame
        y_col_names = [c for i, c in enumerate(df.columns) if i != x_col_idx]
        
        new_df = pd.DataFrame()
        new_df[x_col_name] = pd.to_numeric(df[x_col_name], errors='coerce')
        
        for y_col in y_col_names:
            new_df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
            
        new_df = new_df.dropna().sort_values(by=x_col_name).reset_index(drop=True)
        
        if new_df.shape[1] < 2:
            raise ValueError("Data must have at least 2 numeric columns (Wavelength, Intensity)")
            
        return new_df, filename
        
    except Exception as e:
        raise ValueError(f"Data Load Error: {e}")

def process_spectrum(x, y, filter_width, rigidity, protection):
    # Smoothing
    w = int(filter_width)
    if w % 2 == 0: w += 1
    w = max(3, min(w, len(y) - (1 if len(y)%2==0 else 0)))
    y_smooth = savgol_filter(y, w, 2)

    # Baseline (ALS, Eilers & Boelens)
    L = len(y)
    if rigidity <= 0:
        baseline = np.zeros_like(y)
    else:
        # Asymmetry parameter p must stay in (0, 1); p=0 (the GUI slider default)
        # degenerates the weights so the "baseline" becomes an UPPER envelope of
        # the spectrum and the corrected signal collapses to zero. Clamp to the
        # physically sensible ALS range.
        p = float(min(max(protection, 1e-3), 0.5))
        D = sparse.diags([1,-2,1],[0,-1,-2], shape=(L,L-2))
        w_vec = np.ones(L)
        lam = 10 ** rigidity
        for _ in range(10):
            W = sparse.spdiags(w_vec, 0, L, L)
            Z = W + lam * D.dot(D.transpose())
            z = spsolve(Z, w_vec*y_smooth)
            w_vec = p * (y_smooth > z) + (1-p) * (y_smooth < z)
        baseline = z

    y_corr = np.maximum(y_smooth - baseline, 0)
    return y_smooth, baseline, y_corr

def gaussian(x, amp, cen, sigma):
    return amp * np.exp(-(x - cen)**2 / (2 * sigma**2))

def fit_peak_gaussian(x, y):
    """
    Fit the main PL peak with a Gaussian to get center and FWHM.

    The fit is restricted to a window around the main peak (out to where the
    signal falls to ~10% of the maximum). Fitting the whole spectrum biased the
    result whenever a secondary peak, defect band, or residual baseline was
    present. The initial sigma is estimated from the observed half-max width
    instead of a fixed 15 nm.
    Returns dictionary including 'y_fit' curve (over the full x) for plotting.
    """
    try:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        peak_idx = int(np.argmax(y))
        amp_guess = float(y[peak_idx])
        cen_guess = float(x[peak_idx])
        if amp_guess <= 0:
            raise ValueError("non-positive peak")

        # estimate half-max width for sigma init
        half = amp_guess / 2.0
        i_lo = peak_idx
        while i_lo > 0 and y[i_lo] > half:
            i_lo -= 1
        i_hi = peak_idx
        while i_hi < len(y) - 1 and y[i_hi] > half:
            i_hi += 1
        fwhm_est = abs(x[i_hi] - x[i_lo])
        sigma_guess = max(fwhm_est / 2.3548, 1e-3) if fwhm_est > 0 else 15.0

        # fit window: contiguous region around the peak, bounded by whichever
        # comes first going outwards --
        #   (a) the signal falling below 10% of the maximum, or
        #   (b) the valley before a neighbouring band.
        # Criterion (b) matters: a defect band or shoulder that never drops
        # below the 10% line used to drag the entire spectrum into the fit,
        # which is precisely the bias this window exists to prevent.
        i_lo10 = peak_idx
        while i_lo10 > 0 and y[i_lo10] > 0.1 * amp_guess:
            i_lo10 -= 1
        i_hi10 = peak_idx
        while i_hi10 < len(y) - 1 and y[i_hi10] > 0.1 * amp_guess:
            i_hi10 += 1

        # Local minima of prominence >= 2% of the peak height mark the valleys
        # between the main peak and any neighbouring band. Cutting there is
        # what keeps a defect band out of the fit; the 10% rule alone cannot,
        # because such a band holds the signal above 10% indefinitely.
        valleys, _ = find_peaks(-y, prominence=0.02 * amp_guess)
        left = valleys[valleys < peak_idx]
        right = valleys[valleys > peak_idx]
        valley_lo = len(left) > 0 and left[-1] > i_lo10
        valley_hi = len(right) > 0 and right[0] < i_hi10
        if valley_lo:
            i_lo10 = int(left[-1])
        if valley_hi:
            i_hi10 = int(right[0])

        # pad outward by ~1 FWHM, but never back across a valley into the
        # neighbouring band we just excluded
        step_x = abs(float(np.median(np.diff(x)))) if len(x) > 1 else 1.0
        pad = max(fwhm_est, 3 * step_x)
        lo_edge = x[i_lo10] - (0.0 if valley_lo else pad)
        hi_edge = x[i_hi10] + (0.0 if valley_hi else pad)
        m = (x >= lo_edge) & (x <= hi_edge)
        if int(np.sum(m)) < 5:
            m = np.ones_like(x, dtype=bool)

        popt, _ = curve_fit(gaussian, x[m], y[m],
                            p0=[amp_guess, cen_guess, sigma_guess], maxfev=5000)
        amp, cen, sigma = popt

        fwhm = 2.3548 * abs(sigma)  # Gaussian FWHM
        y_fit = gaussian(x, *popt)  # fitted curve over full range

        return {"amp": amp, "center": cen, "fwhm": fwhm, "y_fit": y_fit, "success": True}
    except Exception:
        return {"amp": 0, "center": 0, "fwhm": 0, "y_fit": np.zeros_like(y), "success": False}

def calculate_quenching_efficiency(y_sample, y_ref):
    """Peak-based PL quenching efficiency: eta = 1 - I_sample_max / I_ref_max."""
    I_ref = np.max(y_ref)
    I_sample = np.max(y_sample)
    if I_ref == 0: return 0.0, I_sample, I_ref
    eta = (I_ref - I_sample) / I_ref
    return eta, I_sample, I_ref


def calculate_quenching_efficiency_integral(x, y_sample, y_ref):
    """Integral-based PL quenching efficiency: eta = 1 - A_sample / A_ref,
    where A = integral of PL over wavelength (Simpson's rule).
    More robust when peak position or width changes between samples."""
    x = np.asarray(x, dtype=float)
    ys = np.clip(np.asarray(y_sample, dtype=float), 0, None)
    yr = np.clip(np.asarray(y_ref, dtype=float), 0, None)
    order = np.argsort(x)
    xs = x[order]
    A_ref = float(simpson(yr[order], x=xs))
    A_sample = float(simpson(ys[order], x=xs))
    if A_ref == 0:
        return 0.0, A_sample, A_ref
    eta = (A_ref - A_sample) / A_ref
    return eta, A_sample, A_ref

def analyze_pl_with_gemini(api_key, model_name, context, data_summary):
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = f"""
    You are an expert in semiconductor photoluminescence (PL). Analyze the
    following PL analysis results and provide a concise interpretation.

    User context: {context}

    Data (per-sample peak position, FWHM, max intensity, and quenching
    efficiency computed both by peak height and by integrated area):
    {data_summary}

    Please cover:
    1. Peak position and any shifts (band gap / defect / strain implications).
    2. FWHM changes (crystallinity / disorder).
    3. Quenching efficiency: compare the peak-based and integral-based values;
       if they differ notably, explain why (peak shift or width change) and
       which is more reliable here.
    4. Overall interpretation for solar-cell / thin-film quality.

    Keep the answer clear and well-structured in English.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI analysis failed: {e}"
