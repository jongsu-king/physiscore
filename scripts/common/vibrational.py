"""Raman / FTIR processing shared by both tools (GUI-free).

Preprocessing (baseline, smoothing, normalisation, transmittance <->
absorbance), peak detection and Lorentzian/Voigt fitting, peak matching
between a reference and a sample spectrum (shift table), and a small
reference library of common band positions used for a first, indicative
assignment. The library is a convenience, not an identification: every
suggestion carries the tolerance it was matched with and must be confirmed
against the literature for the material at hand.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from scripts.common import spectral as sp

LIBRARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "band_library.json")
_LIBRARY: Optional[List[Dict]] = None


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
def transmittance_to_absorbance(transmittance, percent: Optional[bool] = None) -> np.ndarray:
    """A = -log10(T). `percent` (default: auto when max > 1.5) treats T as %."""
    t = np.asarray(transmittance, dtype=float)
    if percent is None:
        percent = bool(np.nanmax(t) > 1.5) if t.size else False
    t = t / 100.0 if percent else t
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.log10(np.clip(t, 1e-12, None))


def absorbance_to_transmittance(absorbance, percent: bool = True) -> np.ndarray:
    a = np.asarray(absorbance, dtype=float)
    t = np.power(10.0, -a)
    return 100.0 * t if percent else t


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------
def preprocess(x, y, baseline: str = "arpls", lam: float = 1e5, smooth_window: int = 0,
               normalization: str = "none", dips: bool = False) -> Dict[str, np.ndarray]:
    """Return a dict with x (ascending), raw, smooth, baseline and corrected
    (and normalised) spectra.

    baseline  none | arpls | als | linear (end-point line) | min
    dips      True for transmittance spectra whose bands point downwards:
              the baseline is then estimated on the inverted spectrum and the
              corrected output is returned as positive band intensity.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x)
    x, y = x[order], y[order]
    ys = sp.smooth_savgol(y, smooth_window, 2) if smooth_window and smooth_window > 2 else y.copy()
    work = -ys if dips else ys
    if baseline == "arpls":
        bl = sp.baseline_arpls(work, lam=lam)
    elif baseline == "als":
        bl = sp.baseline_als(work, lam=lam, p=0.01)
    elif baseline == "linear" and len(x) > 1:
        bl = np.interp(x, [x[0], x[-1]], [work[0], work[-1]])
    elif baseline == "min":
        bl = np.full_like(work, float(np.min(work)))
    else:
        bl = np.zeros_like(work)
    corr = work - bl
    if dips:
        bl = -bl
    corr_n = sp.normalize(corr, normalization) if normalization != "none" else corr
    return {"x": x, "raw": y, "smooth": ys, "baseline": bl, "corrected": corr, "normalized": corr_n}


# ---------------------------------------------------------------------------
# Peaks
# ---------------------------------------------------------------------------
def detect_bands(x, y_corrected, prominence_frac: float = 0.02, noise_k: float = 4.0,
                 min_separation: float = 4.0):
    """Band positions on a baseline-corrected, upward-pointing spectrum."""
    pos, idx, prom = sp.find_peaks_robust(x, y_corrected, prominence_frac=prominence_frac,
                                          noise_k=noise_k, min_separation=min_separation)
    return pos, idx, prom


def fit_bands(x, y_corrected, centers: Sequence[float], shape: str = "lorentzian",
              baseline: str = "none", window: Optional[float] = None) -> pd.DataFrame:
    """Fit the listed bands (together when their windows overlap) and return a
    table: center, height, fwhm, area, errors, r2 of the group fit.

    Raman phonon lines are Lorentzian to first order (homogeneous
    broadening); FTIR bands are often better described by Gaussian or Voigt
    shapes. `window` is the half-width of the fit region around each centre
    (default 6 x the estimated FWHM); bands whose windows overlap are fitted
    simultaneously so shared tails are not double-counted.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y_corrected, dtype=float)
    centers = sorted(float(c) for c in centers)
    if not centers:
        return pd.DataFrame()
    step = float(np.median(np.diff(np.sort(x)))) if len(x) > 1 else 1.0
    half = []
    for c in centers:
        w = sp._estimate_fwhm(np.sort(x), y[np.argsort(x)], c, step, float(np.ptp(x)))
        half.append(float(window) if window else max(6.0 * w, 10 * step))
    # cluster overlapping windows
    groups, cur = [], [0]
    for i in range(1, len(centers)):
        if centers[i] - half[i] <= centers[cur[-1]] + half[cur[-1]]:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    rows = []
    for g in groups:
        lo, hi = centers[g[0]] - half[g[0]], centers[g[-1]] + half[g[-1]]
        m = (x >= lo) & (x <= hi)
        if int(np.sum(m)) < 4 * len(g) + 3:
            for i in g:
                rows.append({"center": centers[i], "height": np.nan, "fwhm": np.nan, "area": np.nan,
                             "center_err": np.nan, "fwhm_err": np.nan, "r2": np.nan, "shape": shape,
                             "fitted": False})
            continue
        res = sp.fit_peaks(x[m], y[m], [centers[i] for i in g], shape=shape, baseline=baseline)
        for p in res.peaks:
            rows.append({"center": p.center, "height": p.height, "fwhm": p.fwhm, "area": p.area,
                         "center_err": p.center_err, "fwhm_err": p.fwhm_err, "r2": res.r2,
                         "shape": shape, "fitted": bool(res.success)})
    return pd.DataFrame(rows).sort_values("center").reset_index(drop=True)


def peak_shift_table(reference_peaks: Sequence[float], sample_peaks: Sequence[float],
                     tolerance: float = 8.0, reference_name: str = "reference",
                     sample_name: str = "sample") -> pd.DataFrame:
    """Pair bands of a sample with those of a reference and tabulate the
    shifts (sample - reference, cm^-1). Unmatched bands are listed with NaN
    on the missing side so new/vanished bands are visible."""
    m = sp.match_peaks(reference_peaks, sample_peaks, tolerance)
    rows = [{"reference": r["reference"], "sample": r["sample"], "shift": r["shift"]} for r in m["matched"]]
    rows += [{"reference": r, "sample": np.nan, "shift": np.nan} for r in m["unmatched_reference"]]
    rows += [{"reference": np.nan, "sample": s, "shift": np.nan} for s in m["unmatched_sample"]]
    df = pd.DataFrame(rows, columns=["reference", "sample", "shift"])
    df.insert(0, "reference_name", reference_name)
    df.insert(1, "sample_name", sample_name)
    return df.sort_values(["reference", "sample"], na_position="last").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Reference band library
# ---------------------------------------------------------------------------
def load_library(path: Optional[str] = None) -> List[Dict]:
    global _LIBRARY
    if path is None and _LIBRARY is not None:
        return _LIBRARY
    p = path or LIBRARY_PATH
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data.get("bands", data) if isinstance(data, dict) else data
    except Exception:
        entries = []
    if path is None:
        _LIBRARY = entries
    return entries


def assign_bands(positions: Sequence[float], technique: str, tolerance: Optional[float] = None,
                 max_suggestions: int = 3, library: Optional[List[Dict]] = None) -> pd.DataFrame:
    """Indicative assignment of band positions from the built-in library.

    For each position, library entries of the same technique whose range
    (position +- tolerance, the entry's own tolerance by default) contains
    it are listed, nearest first, up to `max_suggestions`. The returned
    table carries the distance to the library value so the user can judge
    the match; it is a starting point for a literature check, not a result.
    """
    lib = library if library is not None else load_library()
    tech = technique.lower()
    rows = []
    for pos in positions:
        hits = []
        for e in lib:
            if str(e.get("technique", "")).lower() != tech:
                continue
            tol = float(tolerance) if tolerance is not None else float(e.get("tolerance", 10.0))
            if "range" in e:
                lo, hi = float(e["range"][0]), float(e["range"][1])
                center = 0.5 * (lo + hi)
                inside = lo - tol <= pos <= hi + tol
                # distance to the range, zero inside it
                dist = 0.0 if lo <= pos <= hi else min(abs(pos - lo), abs(pos - hi))
            else:
                center = float(e["position"])
                inside = abs(pos - center) <= tol
                dist = abs(pos - center)
            if inside:
                hits.append((dist, e, center))
        hits.sort(key=lambda t: t[0])
        if not hits:
            rows.append({"position": float(pos), "assignment": "", "material": "", "library_position": np.nan,
                         "distance": np.nan, "note": "no library match"})
        for dist, e, center in hits[:max_suggestions]:
            rows.append({"position": float(pos), "assignment": e.get("assignment", ""),
                         "material": e.get("material", ""), "library_position": float(center),
                         "distance": float(pos - center), "note": e.get("note", "")})
    return pd.DataFrame(rows, columns=["position", "assignment", "material", "library_position", "distance", "note"])


def analyze_layer(x, y, technique: str = "raman", dips: Optional[bool] = None,
                  baseline: str = "arpls", lam: float = 1e5, smooth_window: int = 0,
                  prominence_frac: float = 0.02, fit_shape: str = "lorentzian") -> Dict:
    """Full single-spectrum pipeline: preprocess -> detect -> fit -> assign."""
    tech = technique.lower()
    if dips is None:
        dips = tech == "ftir"
    prep = preprocess(x, y, baseline=baseline, lam=lam, smooth_window=smooth_window, dips=dips)
    pos, idx, prom = detect_bands(prep["x"], prep["corrected"], prominence_frac=prominence_frac)
    fits = fit_bands(prep["x"], prep["corrected"], pos, shape=fit_shape) if len(pos) else pd.DataFrame()
    assign = assign_bands(pos, tech) if len(pos) else pd.DataFrame()
    return {"preprocessed": prep, "positions": pos, "indices": idx, "prominences": prom,
            "fits": fits, "assignments": assign}
