"""
xrd_core.py - XRD Core with Total Fitting & Origin Fit Export
"""
import pandas as pd
import numpy as np
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    genai = None
    GENAI_AVAILABLE = False
import json, re
from scipy.signal import find_peaks, peak_widths
import os
import subprocess
import time

# [physical constants]
LAMBDA_CU = 1.5406

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

try:
    from lmfit.models import VoigtModel, LinearModel
    LMFIT_AVAILABLE = True
except ImportError:
    LMFIT_AVAILABLE = False

def load_data(file_path):
    """
    Load XRD data from CSV/Excel/Text.
    Expected columns: 2Theta, Intensity
    """
    try:
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            df = pd.read_excel(file_path)
        else:
            try:
                df = pd.read_csv(file_path)
                if df.shape[1] < 2:
                    df = pd.read_csv(file_path, sep=None, engine='python')
            except:
                df = pd.read_csv(file_path, sep=None, engine='python', header=None)
        
        df = df.apply(pd.to_numeric, errors='coerce').dropna()
        if df.shape[1] < 2:
            raise ValueError("Data must have at least 2 columns (2Theta, Intensity)")
            
        x = df.iloc[:, 0].values
        y = df.iloc[:, 1].values
        idx = np.argsort(x)
        return x[idx], y[idx]
    except Exception as e:
        raise ValueError(f"Failed to load data: {e}")

def _als_baseline(y, lam=1e7, p=0.01, niter=10):
    """Asymmetric Least Squares baseline (Eilers & Boelens 2005).
    Standard choice for diffraction/spectroscopy background estimation."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    y = np.asarray(y, dtype=float)
    L = len(y)
    if L < 10:
        return np.full_like(y, np.min(y))
    D = sparse.diags([1, -2, 1], [0, -1, -2], shape=(L, L - 2))
    w = np.ones(L)
    z = y.copy()
    for _ in range(niter):
        W = sparse.spdiags(w, 0, L, L)
        Z = W + lam * D.dot(D.transpose())
        z = spsolve(Z, w * y)
        w = p * (y > z) + (1 - p) * (y < z)
    return z


def _pseudo_voigt(x, height, center, fwhm, eta):
    """Pseudo-Voigt profile parametrized by height, center, FWHM and mixing eta.
    eta=0 -> Gaussian, eta=1 -> Lorentzian."""
    dx = (x - center) / max(fwhm, 1e-9)
    gauss = np.exp(-4.0 * np.log(2.0) * dx ** 2)
    lorentz = 1.0 / (1.0 + 4.0 * dx ** 2)
    return height * (eta * lorentz + (1.0 - eta) * gauss)


def _multi_pseudo_voigt(x, *params):
    """Sum of N pseudo-Voigt profiles; params = N x (height, center, fwhm, eta)."""
    y = np.zeros_like(np.asarray(x, dtype=float))
    for i in range(0, len(params), 4):
        y += _pseudo_voigt(x, params[i], params[i + 1], params[i + 2], params[i + 3])
    return y


def _cluster_peaks(centers, half_windows):
    """Group peaks whose fit windows overlap so they are fitted simultaneously."""
    clusters = []
    current = [0]
    for i in range(1, len(centers)):
        prev_hi = centers[current[-1]] + half_windows[current[-1]]
        this_lo = centers[i] - half_windows[i]
        if this_lo <= prev_hi:
            current.append(i)
        else:
            clusters.append(current)
            current = [i]
    clusters.append(current)
    return clusters


def detect_peaks_and_fit(x, y, prominence_factor=0.05, instrumental_fwhm_deg=0.0,
                         scherrer_k=0.9):
    """
    Publication-grade XRD peak analysis.

    Steps:
      1. ALS background estimation over the full pattern (replaces the previous
         per-peak local-minimum offsets, which double-counted overlapping tails).
      2. Peak detection on the background-subtracted signal.
      3. Peaks with overlapping windows are fitted SIMULTANEOUSLY with a sum of
         pseudo-Voigt profiles (correct treatment of overlapping reflections).
      4. Reports per peak: 2Theta, height, FWHM, d-spacing (Bragg), and Scherrer
         crystallite size  tau = K*lambda / (beta*cos(theta))  with beta corrected
         for instrumental broadening in quadrature when instrumental_fwhm_deg > 0.

    Returns: (peaks_df, y_fit_total) where y_fit_total = background + sum of fits.
    """
    from scipy.optimize import curve_fit
    from scipy.signal import peak_widths

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 5 or len(y) < 5:
        # empty/degenerate input (e.g. a file whose rows all failed to parse)
        return pd.DataFrame(), y.copy()

    # ---- 1) Global background ----
    try:
        baseline = _als_baseline(y)
    except Exception:
        baseline = np.full_like(y, np.min(y))
    y_net = y - baseline

    # ---- 2) Peak detection ----
    y_range = float(np.max(y_net) - np.min(y_net)) if len(y_net) else 0.0
    # A featureless pattern leaves only the float residual of the baseline
    # solve. Without this guard that residual has a non-zero range, so peaks
    # were "detected" in numerical noise and reported with a Scherrer size.
    noise_floor = 1e-6 * float(np.max(np.abs(y))) if len(y) else 0.0
    if y_range <= 0 or y_range <= noise_floor:
        return pd.DataFrame(), y.copy()
    peaks_idx, _props = find_peaks(y_net, prominence=y_range * prominence_factor)
    if len(peaks_idx) == 0:
        return pd.DataFrame(), baseline.copy()

    # Initial FWHM estimates from half-prominence widths
    step = float(np.median(np.diff(x))) if len(x) > 1 else 0.01
    try:
        widths_pts = peak_widths(y_net, peaks_idx, rel_height=0.5)[0]
        fwhm_est = np.clip(widths_pts * step, 2 * step, 2.0)
    except Exception:
        fwhm_est = np.full(len(peaks_idx), 0.15)

    centers0 = x[peaks_idx]
    heights0 = y_net[peaks_idx]
    half_win = np.maximum(3.0 * fwhm_est, 0.25)

    # ---- 3) Cluster + simultaneous fit ----
    order = np.argsort(centers0)
    centers0, heights0, fwhm_est, half_win = (
        centers0[order], heights0[order], fwhm_est[order], half_win[order])
    clusters = _cluster_peaks(centers0, half_win)

    y_fit_total = baseline.copy()
    peak_data = []

    for cl in clusters:
        lo = centers0[cl[0]] - half_win[cl[0]]
        hi = centers0[cl[-1]] + half_win[cl[-1]]
        m = (x >= lo) & (x <= hi)
        x_sub, y_sub = x[m], y_net[m]

        fitted = False
        if len(x_sub) >= 4 * len(cl) + 2:
            p0, lb, ub = [], [], []
            for i in cl:
                p0 += [max(heights0[i], 1e-9), centers0[i], fwhm_est[i], 0.5]
                lb += [0.0, centers0[i] - fwhm_est[i], step, 0.0]
                ub += [np.inf, centers0[i] + fwhm_est[i], (hi - lo), 1.0]
            try:
                popt, _ = curve_fit(_multi_pseudo_voigt, x_sub, y_sub, p0=p0,
                                    bounds=(lb, ub), maxfev=20000)
                # goodness of fit for this cluster
                resid = y_sub - _multi_pseudo_voigt(x_sub, *popt)
                ss_tot = float(np.sum((y_sub - np.mean(y_sub)) ** 2))
                r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else np.nan

                y_fit_total += _multi_pseudo_voigt(x, *popt)
                for k, i in enumerate(cl):
                    h_f, c_f, w_f, eta_f = popt[4 * k: 4 * k + 4]
                    peak_data.append(_make_peak_row(
                        c_f, h_f + float(np.interp(c_f, x, baseline)), w_f,
                        eta_f, r2, instrumental_fwhm_deg, scherrer_k))
                fitted = True
            except Exception:
                fitted = False

        if not fitted:
            # Raw fallback for this cluster only
            for i in cl:
                peak_data.append(_make_peak_row(
                    centers0[i], heights0[i] + float(np.interp(centers0[i], x, baseline)),
                    fwhm_est[i], np.nan, np.nan, instrumental_fwhm_deg, scherrer_k))
                y_fit_total += _pseudo_voigt(x, heights0[i], centers0[i], fwhm_est[i], 0.5)

    df = pd.DataFrame(peak_data).sort_values(by="Intensity", ascending=False).reset_index(drop=True)
    return df, y_fit_total


def _make_peak_row(center, height, fwhm_deg, eta, r2, instrumental_fwhm_deg, scherrer_k):
    """Build one result row: Bragg d-spacing + Scherrer crystallite size."""
    theta_rad = np.radians(center / 2.0)
    sin_t = np.sin(theta_rad)
    d_spacing = LAMBDA_CU / (2.0 * sin_t) if sin_t > 0 else np.nan

    # Instrumental broadening correction (quadrature, Gaussian approximation)
    beta_deg = fwhm_deg
    if instrumental_fwhm_deg and fwhm_deg > instrumental_fwhm_deg:
        beta_deg = float(np.sqrt(fwhm_deg ** 2 - instrumental_fwhm_deg ** 2))
    beta_rad = np.radians(beta_deg)
    cos_t = np.cos(theta_rad)
    # Scherrer: tau = K*lambda/(beta*cos(theta)); LAMBDA_CU is in Angstrom -> /10 for nm
    size_nm = (scherrer_k * LAMBDA_CU / 10.0) / (beta_rad * cos_t) if beta_rad > 0 and cos_t > 0 else np.nan

    return {
        "2Theta": float(center),
        "Intensity": float(height),
        "FWHM": float(fwhm_deg),
        "d_spacing": float(d_spacing),
        "Crystallite_nm": float(size_nm) if np.isfinite(size_nm) else np.nan,
        "eta_pV": float(eta) if np.isfinite(eta) else np.nan,
        "Fit_R2": float(r2) if np.isfinite(r2) else np.nan,
    }

def analyze_with_gemini(api_key, model_name, context, peaks_df):
    """
    Generate an expert Gemini comment based on the measured peaks_df
    """
    if peaks_df.empty:
        return "No peak data to analyze."

    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    # 1. Data summary (for Gemini)
    peak_summary = peaks_df.to_dict('records')
    
    # 2. Prompt design
    prompt = f"""
    You are an expert in Crystallography and XRD Analysis. Analyze the following XRD data.

    [Sample Context]
    {context}

    [Peak Data (Top Peaks)]
    {json.dumps(peak_summary, indent=2)}

    [Analysis Request]
    Please provide a professional report in **English** covering:
    1. **Phase Identification**: Identify the material phases based on 2-Theta peaks.
    2. **Crystallinity**: Evaluate crystal quality using FWHM, Intensity, and the
       Scherrer crystallite size (Crystallite_nm column, K=0.9, Cu K-alpha).
    3. **Lattice Strain**: Discuss any d-spacing shifts indicating strain.
    4. **Action Items**: Suggest next steps for validation.

    **Format**: Use Markdown with clear bullet points.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error during AI analysis: {str(e)}"

def connect_to_origin(origin_exe_path: str = "", log_callback=None):
    """Connect to Origin application."""
    if not WIN32COM_AVAILABLE:
        if log_callback: log_callback("pywin32 not installed")
        return None

    try:
        origin = win32com.client.Dispatch("Origin.ApplicationSI")
        origin.Visible = 1
        if log_callback: log_callback("Connected to existing Origin")
        return origin
    except: pass

    if origin_exe_path and os.path.exists(origin_exe_path):
        if log_callback: log_callback(f"Launching Origin: {origin_exe_path}")
        try:
            subprocess.Popen([origin_exe_path])
            for _ in range(30):
                time.sleep(1)
                try:
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1
                    if log_callback: log_callback("New Origin instance started")
                    return origin
                except: continue
        except Exception as e:
            if log_callback: log_callback(f"Origin launch error: {e}")
    return None

def plot_xrd_to_origin(origin, x, y, y_fit, peaks_df=None, log_callback=None):
    """
    Exports Raw Data, Fitted Curve, and Peaks to Origin.
    """
    if log_callback: log_callback("Sending data (Raw + Fit) to Origin...")
    
    wb_name = origin.CreatePage(2, "XRD_Full_Analysis", "Origin")
    origin.Execute(f"page.active$ = {wb_name};")
    origin.Execute(f"wks.ncols = 5;")
    
    # Col 1: X (2Theta)
    origin.Execute(f'wks.col1.lname$ = "2Theta"; wks.col1.units$ = "degrees"; wks.col1.type = 4;')
    origin.PutWorksheet(f"[{wb_name}]Sheet1", x.tolist(), 0, 0)
    
    # Col 2: Y Raw
    origin.Execute(f'wks.col2.lname$ = "Raw Intensity"; wks.col2.type = 1;')
    origin.PutWorksheet(f"[{wb_name}]Sheet1", y.tolist(), 0, 1)
    
    # Col 3: Y Fit (fitted curve)
    origin.Execute(f'wks.col3.lname$ = "Fitted Curve"; wks.col3.type = 1;')
    origin.PutWorksheet(f"[{wb_name}]Sheet1", y_fit.tolist(), 0, 2)

    # Graphing
    gp_name = origin.CreatePage(3, "XRD_Graph_Fit", "Origin")
    
    # 1. Plot Raw (Scatter/Line Black)
    origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(1,2) plot:=200 o:=[{gp_name}]1!;")
    origin.Execute("set %C -cl color(black); set %C -w 500;") # Thin line or Scatter

    # 2. Plot Fit (Line Red)
    origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(1,3) plot:=200 o:=[{gp_name}]1!;")
    origin.Execute("set %C -cl color(red); set %C -w 1500;") # Thick Red Line

    # 3. Mark Peaks if available
    if peaks_df is not None and not peaks_df.empty:
        # Col 4, 5 for Peaks
        origin.Execute(f'wks.col4.lname$ = "Peak X"; wks.col4.type = 4;')
        origin.PutWorksheet(f"[{wb_name}]Sheet1", peaks_df["2Theta"].tolist(), 0, 3)
        origin.Execute(f'wks.col5.lname$ = "Peak Y"; wks.col5.type = 1;')
        origin.PutWorksheet(f"[{wb_name}]Sheet1", peaks_df["Intensity"].tolist(), 0, 4)
        
        origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(4,5) plot:=201 o:=[{gp_name}]1!;") # Scatter
        origin.Execute("set %C -k 2; set %C -z 9; set %C -c 3;") # Green Triangles
    
    origin.Execute(f"win -a {gp_name};")
    origin.Execute("layer.x.showAxes = 3; layer.y.showAxes = 3;") # Box frame
    origin.Execute("label -xl 2\g(h) (degrees);")
    origin.Execute("label -yl Intensity (a.u.);")
    origin.Execute("doc -uw;")
    
    if log_callback: log_callback("Origin plotting with Fit complete.")