"""
xrd_core.py - XRD Core with Total Fitting & Origin Fit Export
"""
import math
import pandas as pd
from typing import Any, Dict, Optional
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

from scripts.common.origin import WIN32COM_AVAILABLE, connect_to_origin

# [physical constants]
LAMBDA_CU = 1.5406

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
    # float dtype and CSC format are explicit: spsolve silently converts a
    # non-CSC/CSR matrix on every one of the `niter` iterations, which for a
    # full diffraction pattern is the dominant cost of the baseline.
    D = sparse.diags([1, -2, 1], [0, -1, -2], shape=(L, L - 2), dtype=float)
    DDT = (D @ D.transpose()).tocsc()
    w = np.ones(L)
    z = y.copy()
    for _ in range(niter):
        W = sparse.diags(w, 0, shape=(L, L), format="csc")
        z = spsolve((W + lam * DDT).tocsc(), w * y)
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

# connect_to_origin lives in scripts/common/origin.py (imported above); all nine
# tools share one connection routine.


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
    origin.Execute(r"label -xl 2\g(h) (degrees);")
    origin.Execute("label -yl Intensity (a.u.);")
    origin.Execute("doc -uw;")
    
    if log_callback: log_callback("Origin plotting with Fit complete.")

# =========================
# Line-broadening analysis, Kalpha2 stripping, lattice parameters, texture
# =========================
LAMBDA_CU_KA1 = 1.540562   # Angstrom
LAMBDA_CU_KA2 = 1.544390   # Angstrom
KA2_KA1_INTENSITY_RATIO = 0.5


def scherrer_size(two_theta_deg, fwhm_deg, instrumental_fwhm_deg: float = 0.0,
                  k: float = 0.9, wavelength_a: float = LAMBDA_CU, breadth: str = "fwhm") -> float:
    """Crystallite size [nm], tau = K lambda / (beta cos theta).

    beta is the sample broadening in radians: FWHM corrected for the
    instrument in quadrature (Gaussian approximation; use `breadth="linear"`
    for the Lorentzian beta = FWHM - FWHM_inst). K = 0.9 for spherical
    crystallites of unknown shape (Scherrer 1918; Langford & Wilson 1978).
    """
    fwhm_deg = float(fwhm_deg)
    inst = float(instrumental_fwhm_deg or 0.0)
    if breadth == "linear":
        beta_deg = fwhm_deg - inst
    else:
        beta_deg = math.sqrt(fwhm_deg ** 2 - inst ** 2) if fwhm_deg > inst else float("nan")
    if not np.isfinite(beta_deg) or beta_deg <= 0:
        return float("nan")
    theta = math.radians(float(two_theta_deg) / 2.0)
    return (k * wavelength_a / 10.0) / (math.radians(beta_deg) * math.cos(theta))


def williamson_hall(two_theta_deg, fwhm_deg, instrumental_fwhm_deg: float = 0.0,
                    k: float = 0.9, wavelength_a: float = LAMBDA_CU) -> Dict[str, Any]:
    """Uniform-deformation Williamson-Hall analysis (Williamson & Hall 1953):

        beta cos(theta) = K lambda / D + 4 epsilon sin(theta)

    beta is the instrument-corrected FWHM in radians. Returns D [nm],
    the microstrain epsilon (dimensionless), their standard errors from the
    fit covariance, R^2 and the plotted points. Needs >= 2 reflections; with
    exactly 2 the uncertainties are undefined.
    """
    tt = np.asarray(two_theta_deg, dtype=float)
    fw = np.asarray(fwhm_deg, dtype=float)
    inst = float(instrumental_fwhm_deg or 0.0)
    beta = np.where(fw > inst, np.sqrt(np.clip(fw ** 2 - inst ** 2, 0, None)), np.nan)
    ok = np.isfinite(tt) & np.isfinite(beta) & (beta > 0)
    out = {"D_nm": float("nan"), "strain": float("nan"), "D_err_nm": float("nan"),
           "strain_err": float("nan"), "intercept": float("nan"), "slope": float("nan"),
           "R2": float("nan"), "n_peaks": int(np.sum(ok)), "x": np.array([]), "y": np.array([])}
    if out["n_peaks"] < 2:
        return out
    theta = np.radians(tt[ok] / 2.0)
    x = 4.0 * np.sin(theta)
    y = np.radians(beta[ok]) * np.cos(theta)
    if out["n_peaks"] >= 3:
        (slope, intercept), cov = np.polyfit(x, y, 1, cov=True)
        se_slope, se_int = math.sqrt(max(cov[0, 0], 0)), math.sqrt(max(cov[1, 1], 0))
    else:
        slope, intercept = np.polyfit(x, y, 1)
        se_slope = se_int = float("nan")
    yhat = slope * x + intercept
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - yhat) ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    d_nm = (k * wavelength_a / 10.0) / intercept if intercept > 0 else float("inf")
    d_err = (k * wavelength_a / 10.0) / intercept ** 2 * se_int if intercept > 0 and np.isfinite(se_int) else float("nan")
    out.update(D_nm=float(d_nm), strain=float(slope), D_err_nm=float(d_err), strain_err=float(se_slope),
               intercept=float(intercept), slope=float(slope), R2=float(r2), x=x, y=y)
    return out


def strip_kalpha2(two_theta_deg, intensity, ratio: float = KA2_KA1_INTENSITY_RATIO,
                  lambda1: float = LAMBDA_CU_KA1, lambda2: float = LAMBDA_CU_KA2) -> np.ndarray:
    """Remove the Cu Kalpha2 contribution with the Rachinger (1948) method.

    Each point's Kalpha2 component is `ratio` times the Kalpha1 intensity at
    the angle where Kalpha1 diffracts from the same d-spacing,
    2theta_1 = 2 asin(lambda1/lambda2 sin theta). Working from low to high
    angle, the already-stripped pattern is interpolated at that angle and
    subtracted. The result is the Kalpha1-only pattern on the input grid.
    """
    x = np.asarray(two_theta_deg, dtype=float)
    y = np.asarray(intensity, dtype=float)
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    out = ys.copy()
    theta = np.radians(xs / 2.0)
    arg = np.clip(lambda1 / lambda2 * np.sin(theta), -1.0, 1.0)
    x_ka1 = 2.0 * np.degrees(np.arcsin(arg))   # angle at which Ka1 gives the same d
    for i in range(len(xs)):
        xi = x_ka1[i]
        if xi <= xs[0]:
            continue
        # interpolate the stripped (Ka1-only) pattern at xi using points already processed
        j = int(np.searchsorted(xs, xi)) - 1
        if j < 0 or j >= i:
            continue
        j2 = min(j + 1, i)
        if xs[j2] == xs[j]:
            v = out[j]
        else:
            t = (xi - xs[j]) / (xs[j2] - xs[j])
            v = out[j] + t * (out[j2] - out[j])
        out[i] = ys[i] - ratio * v
    result = np.empty_like(out)
    result[order] = out
    return result


def crystallinity_index(two_theta_deg, intensity, baseline=None, lam: float = 1e7) -> Dict[str, float]:
    """Crystallinity index CI = A_crystalline / A_total, with the amorphous
    contribution taken as the smooth (ALS) background under the reflections
    (Segal-type area method). Returns CI in %, both areas and the background
    used."""
    x = np.asarray(two_theta_deg, dtype=float)
    y = np.asarray(intensity, dtype=float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    if baseline is None:
        baseline = _als_baseline(y, lam=lam, p=0.01)
    baseline = np.asarray(baseline, dtype=float)
    trap = getattr(np, "trapezoid", None) or np.trapz
    total = float(trap(np.clip(y, 0, None), x))
    cryst = float(trap(np.clip(y - baseline, 0, None), x))
    ci = 100.0 * cryst / total if total > 0 else float("nan")
    return {"CI_percent": ci, "area_crystalline": cryst, "area_total": total, "baseline": baseline}


def d_spacing(two_theta_deg, wavelength_a: float = LAMBDA_CU):
    tt = np.asarray(two_theta_deg, dtype=float)
    return wavelength_a / (2.0 * np.sin(np.radians(tt / 2.0)))


def lattice_parameter_cubic(two_theta_deg, hkl, wavelength_a: float = LAMBDA_CU) -> Dict[str, Any]:
    """Cubic lattice parameter from indexed reflections: a = d sqrt(h^2+k^2+l^2).

    Besides the plain mean, the Nelson-Riley extrapolation (Nelson & Riley
    1945) is returned: a plotted against f(theta) = (cos^2 theta / sin theta
    + cos^2 theta / theta)/2 and extrapolated to f = 0 (theta = 90 deg),
    which cancels the systematic errors (specimen displacement, absorption)
    that scale with that function.
    """
    tt = np.asarray(two_theta_deg, dtype=float)
    hkl = np.asarray(hkl, dtype=float).reshape(-1, 3)
    if len(tt) != len(hkl):
        raise ValueError("one (h k l) triple per reflection is required")
    d = d_spacing(tt, wavelength_a)
    a = d * np.sqrt(np.sum(hkl ** 2, axis=1))
    out = {"a_mean_A": float(np.mean(a)), "a_std_A": float(np.std(a, ddof=1)) if len(a) > 1 else 0.0,
           "a_per_peak_A": a, "a_NR_A": float("nan"), "NR_R2": float("nan")}
    if len(a) >= 3:
        theta = np.radians(tt / 2.0)
        f = 0.5 * (np.cos(theta) ** 2 / np.sin(theta) + np.cos(theta) ** 2 / theta)
        slope, intercept = np.polyfit(f, a, 1)
        yhat = slope * f + intercept
        ss_tot = float(np.sum((a - a.mean()) ** 2))
        out["a_NR_A"] = float(intercept)
        out["NR_R2"] = 1.0 - float(np.sum((a - yhat) ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    return out


def lattice_strain(d_observed, d_reference) -> float:
    """Uniform lattice strain from a peak shift, (d - d0)/d0 (positive =
    tensile, larger spacing, peak at lower angle)."""
    return float((float(d_observed) - float(d_reference)) / float(d_reference))


def texture_coefficient(intensities, reference_intensities) -> np.ndarray:
    """Harris texture coefficient TC(hkl) = (I/I0) / ((1/N) sum I/I0); TC = 1
    for a random powder, TC > 1 marks preferred orientation (Harris 1952)."""
    i = np.asarray(intensities, dtype=float)
    i0 = np.asarray(reference_intensities, dtype=float)
    r = i / i0
    return r / np.mean(r)


# =========================
# Reference patterns and multi-pattern comparison
# =========================
def load_reference_peaks(path: str, wavelength_a: float = LAMBDA_CU) -> pd.DataFrame:
    """Read a reference peak list (CSV / TXT / XLSX) with columns such as
    `2theta` (or `d`), optional `hkl` (or h, k, l) and optional `I`
    (relative intensity). Column names are matched loosely and case-
    insensitively; a d-spacing column is converted to 2theta for the given
    wavelength. Returns columns: 2Theta, d, hkl, I_rel (NaN when absent)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower().replace(" ", "").replace("_", ""): c for c in df.columns}

    def pick(*names):
        for n in names:
            for key, col in low.items():
                if key == n or key.startswith(n):
                    return col
        return None

    c_tt = pick("2theta", "2θ", "twotheta", "2th", "angle")
    c_d = pick("dspacing", "d(a)", "d(å)", "d")
    c_i = pick("irel", "intensity", "i(%)", "int", "i")
    c_hkl = pick("hkl")
    if c_tt is not None:
        tt = pd.to_numeric(df[c_tt], errors="coerce").to_numpy(float)
        d = d_spacing(tt, wavelength_a)
    elif c_d is not None:
        d = pd.to_numeric(df[c_d], errors="coerce").to_numpy(float)
        with np.errstate(invalid="ignore"):
            tt = 2.0 * np.degrees(np.arcsin(np.clip(wavelength_a / (2.0 * d), -1, 1)))
    else:
        raise ValueError("reference list needs a 2theta or d column")
    if c_hkl is not None:
        hkl = df[c_hkl].astype(str).str.replace(r"[()\s,]", "", regex=True).tolist()
    elif all(pick(k) for k in ("h", "k", "l")):
        hkl = [f"{int(h)}{int(k)}{int(l)}" for h, k, l in zip(df[pick("h")], df[pick("k")], df[pick("l")])]
    else:
        hkl = [""] * len(df)
    i_rel = pd.to_numeric(df[c_i], errors="coerce").to_numpy(float) if c_i is not None else np.full(len(df), np.nan)
    if np.nanmax(i_rel) > 0 if np.any(np.isfinite(i_rel)) else False:
        i_rel = 100.0 * i_rel / np.nanmax(i_rel)
    out = pd.DataFrame({"2Theta": tt, "d": d, "hkl": hkl, "I_rel": i_rel})
    return out[np.isfinite(out["2Theta"])].sort_values("2Theta").reset_index(drop=True)


def match_reference(peaks_df: pd.DataFrame, reference: pd.DataFrame, tolerance_deg: float = 0.15,
                    min_ref_intensity: float = 5.0) -> Dict[str, Any]:
    """Pair observed reflections with a reference peak list.

    Each observed peak is matched to the nearest reference line within
    `tolerance_deg` (one-to-one, closest pairs first). Returns a table of
    matches with hkl, delta 2theta, the lattice strain (d - d0)/d0, and the
    coverage statistics: the fraction of reference lines (with I_rel >=
    `min_ref_intensity`) that were found, and the fraction of observed peaks
    that belong to the reference (unassigned peaks indicate another phase).
    """
    obs = peaks_df.sort_values("2Theta").reset_index(drop=True) if peaks_df is not None else pd.DataFrame()
    ref = reference.sort_values("2Theta").reset_index(drop=True)
    pairs = []
    for i, tt in enumerate(obs["2Theta"].to_numpy(float) if len(obs) else []):
        for j, rt in enumerate(ref["2Theta"].to_numpy(float)):
            dd = abs(tt - rt)
            if dd <= tolerance_deg:
                pairs.append((dd, i, j))
    pairs.sort()
    used_i, used_j, rows = set(), set(), []
    for dd, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        o, r = obs.iloc[i], ref.iloc[j]
        d_obs = float(o["d_spacing"]) if "d_spacing" in obs.columns else float(d_spacing(o["2Theta"]))
        rows.append({"2Theta_obs": float(o["2Theta"]), "2Theta_ref": float(r["2Theta"]),
                     "delta_2Theta": float(o["2Theta"] - r["2Theta"]), "hkl": r["hkl"],
                     "d_obs": d_obs, "d_ref": float(r["d"]), "strain": lattice_strain(d_obs, float(r["d"])),
                     "I_obs": float(o["Intensity"]) if "Intensity" in obs.columns else np.nan,
                     "I_ref": float(r["I_rel"]) if np.isfinite(r["I_rel"]) else np.nan,
                     "FWHM": float(o["FWHM"]) if "FWHM" in obs.columns else np.nan})
    matches = pd.DataFrame(rows, columns=["2Theta_obs", "2Theta_ref", "delta_2Theta", "hkl", "d_obs", "d_ref",
                                          "strain", "I_obs", "I_ref", "FWHM"]).sort_values("2Theta_obs").reset_index(drop=True)
    strong = ref[(ref["I_rel"] >= min_ref_intensity) | ~np.isfinite(ref["I_rel"])]
    n_strong = int(len(strong))
    n_found = int(sum(1 for j in used_j if j in strong.index))
    unassigned = obs[~obs.index.isin(used_i)] if len(obs) else obs
    return {"matches": matches,
            "coverage": (n_found / n_strong) if n_strong else float("nan"),
            "n_reference_lines": n_strong, "n_matched": n_found,
            "assigned_fraction": (len(used_i) / len(obs)) if len(obs) else float("nan"),
            "unassigned": unassigned.reset_index(drop=True),
            "mean_shift_deg": float(matches["delta_2Theta"].mean()) if len(matches) else float("nan"),
            "mean_strain": float(matches["strain"].mean()) if len(matches) else float("nan")}


def normalize_patterns(patterns, mode: str = "max"):
    """Scale several (x, y) patterns for a stacked overlay: 'max' divides by
    each maximum, 'area' by each integral, 'none' leaves them."""
    out = []
    for x, y in patterns:
        y = np.asarray(y, dtype=float)
        if mode == "max" and np.nanmax(y) > 0:
            y = y / np.nanmax(y)
        elif mode == "area":
            trap = getattr(np, "trapezoid", None) or np.trapz
            a = trap(np.clip(y, 0, None), x)
            y = y / a if a > 0 else y
        out.append((np.asarray(x, dtype=float), y))
    return out
