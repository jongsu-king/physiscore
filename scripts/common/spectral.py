"""Shared spectral-analysis primitives (GUI-free).

Every spectroscopic tool in Physiscore (PL, Raman, FTIR, XRD, Abs, XPS) needs
the same building blocks: a baseline estimate, a smoothing step, analytical
line shapes, a bounded multi-peak least-squares fit and a way to decide how
many components the data support. Before this module each tool carried its
own partial copy (three different ALS implementations, two Gaussian
definitions, no shared model-selection rule). Keeping them here means a fix
or an improvement applies to every technique at once and can be validated by
one test suite.

Units are whatever the caller passes in; nothing here assumes nm, eV, cm^-1 or
degrees. The only physical constant is hc (nm·eV) for the wavelength <-> energy
conversion.

References
----------
- Eilers & Boelens, "Baseline correction with asymmetric least squares
  smoothing" (2005).                                           -> baseline_als
- Baek, Park, Ahn & Choo, Analyst 140, 250 (2015).             -> baseline_arpls
- Shirley, Phys. Rev. B 5, 4709 (1972).                        -> baseline_shirley
- Thompson, Cox & Hastings, J. Appl. Cryst. 20, 79 (1987).     -> pseudo-Voigt
- Olivero & Longbothum, JQSRT 17, 233 (1977).                  -> Voigt FWHM
- Akaike (1974); Burnham & Anderson (2002) for AICc.           -> model selection
- Mooney & Kambhampati, J. Phys. Chem. Lett. 4, 3316 (2013).   -> Jacobian nm->eV
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import sparse
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, peak_widths, savgol_filter
from scipy.sparse.linalg import spsolve
from scipy.special import voigt_profile

HC_EV_NM = 1239.84198          # h*c in eV*nm (CODATA 2018)
_SQRT_2LN2 = math.sqrt(2.0 * math.log(2.0))
_G_AREA = math.sqrt(math.pi / (4.0 * math.log(2.0)))   # Gaussian area / (height*FWHM)
_L_AREA = math.pi / 2.0                                 # Lorentzian area / (height*FWHM)

SHAPES = ("gaussian", "lorentzian", "pvoigt", "voigt")


# ---------------------------------------------------------------------------
# Noise and smoothing
# ---------------------------------------------------------------------------
def robust_noise_sigma(y) -> float:
    """Noise standard deviation from the median absolute deviation of the
    first difference. Insensitive to peaks, which a plain std is not."""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 10:
        return float(np.std(y)) if len(y) > 1 else 1.0
    dy = np.diff(y)
    mad = np.median(np.abs(dy - np.median(dy)))
    sigma = (mad / 0.6745) / math.sqrt(2.0) if mad > 0 else float(np.std(dy)) / math.sqrt(2.0)
    return float(sigma) if sigma > 0 else 1.0


def smooth_savgol(y, window: int, poly: int = 2) -> np.ndarray:
    """Savitzky-Golay smoothing with a window forced odd and clipped to the
    data length. window <= 1 returns the input unchanged."""
    y = np.asarray(y, dtype=float)
    w = int(window)
    if w <= 1 or len(y) < 5:
        return y.copy()
    if w % 2 == 0:
        w += 1
    w = min(w, len(y) if len(y) % 2 == 1 else len(y) - 1)
    if w < 3:
        return y.copy()
    p = max(0, min(int(poly), w - 1))
    return savgol_filter(y, w, p)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def _second_difference(n: int):
    D = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(n, n - 2), dtype=float)
    return (D @ D.transpose()).tocsc()


def baseline_als(y, lam: float = 1e6, p: float = 0.01, niter: int = 10) -> np.ndarray:
    """Asymmetric least squares baseline (Eilers & Boelens 2005).

    lam controls stiffness (1e4 flexible ... 1e9 almost straight), p the
    asymmetry (fraction of points allowed above the baseline). p is clamped
    to (0, 0.5]: p = 0 degenerates the weights so the "baseline" becomes the
    upper envelope and the corrected spectrum collapses to zero.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 10:
        return np.full_like(y, np.nanmin(y) if n else 0.0)
    p = float(min(max(p, 1e-4), 0.5))
    DDT = _second_difference(n)
    w = np.ones(n)
    z = y.copy()
    for _ in range(max(1, int(niter))):
        W = sparse.diags(w, 0, shape=(n, n), format="csc")
        z = spsolve((W + lam * DDT).tocsc(), w * y)
        w = p * (y > z) + (1.0 - p) * (y < z)
    return np.asarray(z, dtype=float)


def baseline_arpls(y, lam: float = 1e5, ratio: float = 1e-6, niter: int = 50) -> np.ndarray:
    """Asymmetrically reweighted penalised least squares (Baek et al. 2015).

    Unlike ALS there is no asymmetry parameter to tune: the weights come from
    a logistic function of the residual relative to the noise of the points
    below the baseline, so peaks are excluded automatically while noise
    around the baseline is treated symmetrically. Preferred for Raman/FTIR
    with fluorescence or scattering backgrounds.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 10:
        return np.full_like(y, np.nanmin(y) if n else 0.0)
    DDT = _second_difference(n)
    w = np.ones(n)
    z = y.copy()
    for _ in range(max(1, int(niter))):
        W = sparse.diags(w, 0, shape=(n, n), format="csc")
        z = spsolve((W + lam * DDT).tocsc(), w * y)
        d = y - z
        dn = d[d < 0]
        if len(dn) < 2:
            break
        m, s = float(np.mean(dn)), float(np.std(dn))
        if s <= 0:
            break
        arg = np.clip(2.0 * (d - (-m + 2.0 * s)) / s, -500, 500)
        wt = 1.0 / (1.0 + np.exp(arg))
        if np.linalg.norm(w - wt) / max(np.linalg.norm(w), 1e-12) < ratio:
            w = wt
            break
        w = wt
    return np.asarray(z, dtype=float)


def baseline_shirley(x, y, lo: Optional[float] = None, hi: Optional[float] = None,
                     max_iter: int = 100, tol: float = 1e-7) -> np.ndarray:
    """Iterative Shirley background (Shirley 1972; Proctor & Sherwood 1982).

    The background at a point is proportional to the integrated peak
    intensity on the high-kinetic-energy (low-binding-energy) side of it:

        B(E) = I_right + (I_left - I_right) * A_right(E) / A_total

    where I_left/I_right are the spectrum values at the chosen end points and
    A are areas of (I - B). The result is independent of whether x is stored
    ascending or descending; `lo`/`hi` select the end points in x units
    (default: first and last point). Returned on the input grid.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 5:
        return np.full_like(y, np.nanmin(y) if len(y) else 0.0)
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    i0 = 0 if lo is None else int(np.argmin(np.abs(xs - lo)))
    i1 = len(xs) - 1 if hi is None else int(np.argmin(np.abs(xs - hi)))
    if i0 > i1:
        i0, i1 = i1, i0
    if i1 - i0 < 3:
        return np.full_like(y, np.nanmin(y))
    xr, yr = xs[i0:i1 + 1], ys[i0:i1 + 1]
    yl, yh = float(yr[0]), float(yr[-1])
    # Convention: the side with the LOWER intensity end point is the
    # "zero-background" side; the background rises towards the other end.
    # Work on an orientation where the background rises left -> right.
    flip = yl > yh
    if flip:
        xr, yr = xr[::-1], yr[::-1]
        yl, yh = yh, yl
    b = np.full_like(yr, yl)
    dx = np.abs(np.gradient(xr))
    for _ in range(max_iter):
        net = np.clip(yr - b, 0.0, None)
        cum = np.cumsum(net * dx)
        total = cum[-1]
        if total <= 0:
            break
        b_new = yl + (yh - yl) * cum / total
        if np.max(np.abs(b_new - b)) < tol * max(abs(yh - yl), 1e-12):
            b = b_new
            break
        b = b_new
    if flip:
        b = b[::-1]
    out = np.empty_like(ys)
    out[:i0] = b[0]
    out[i1 + 1:] = b[-1]
    out[i0:i1 + 1] = b
    result = np.empty_like(out)
    result[order] = out
    return result


# ---------------------------------------------------------------------------
# Line shapes (height-parametrised)
# ---------------------------------------------------------------------------
def gaussian(x, height, center, fwhm):
    x = np.asarray(x, dtype=float)
    fwhm = max(float(fwhm), 1e-12)
    return height * np.exp(-4.0 * math.log(2.0) * ((x - center) / fwhm) ** 2)


def lorentzian(x, height, center, fwhm):
    x = np.asarray(x, dtype=float)
    fwhm = max(float(fwhm), 1e-12)
    return height / (1.0 + 4.0 * ((x - center) / fwhm) ** 2)


def pseudo_voigt(x, height, center, fwhm, eta):
    """Linear pseudo-Voigt: eta=0 Gaussian, eta=1 Lorentzian (same FWHM)."""
    eta = float(min(max(eta, 0.0), 1.0))
    return eta * lorentzian(x, height, center, fwhm) + (1.0 - eta) * gaussian(x, height, center, fwhm)


def voigt(x, height, center, sigma, gamma):
    """True Voigt profile (Gaussian sigma convolved with Lorentzian HWHM
    gamma), scaled so that its maximum equals `height`."""
    x = np.asarray(x, dtype=float)
    sigma = max(float(sigma), 1e-12)
    gamma = max(float(gamma), 0.0)
    peak = voigt_profile(0.0, sigma, gamma)
    if peak <= 0:
        return np.zeros_like(x)
    return height * voigt_profile(x - center, sigma, gamma) / peak


def voigt_fwhm(sigma: float, gamma: float) -> float:
    """Olivero-Longbothum approximation (accurate to 0.02%)."""
    fg = 2.0 * _SQRT_2LN2 * sigma
    fl = 2.0 * gamma
    return 0.5346 * fl + math.sqrt(0.2166 * fl ** 2 + fg ** 2)


def peak_area(shape: str, height: float, fwhm: float, eta: float = 0.5,
              sigma: Optional[float] = None, gamma: Optional[float] = None) -> float:
    """Analytic area under one line shape."""
    if shape == "gaussian":
        return float(height * fwhm * _G_AREA)
    if shape == "lorentzian":
        return float(height * fwhm * _L_AREA)
    if shape == "pvoigt":
        return float(height * fwhm * (eta * _L_AREA + (1.0 - eta) * _G_AREA))
    if shape == "voigt":
        if sigma is None or gamma is None:
            raise ValueError("voigt area needs sigma and gamma")
        peak = voigt_profile(0.0, max(sigma, 1e-12), max(gamma, 0.0))
        return float(height / peak) if peak > 0 else float("nan")
    raise ValueError(f"unknown shape {shape!r}")


# ---------------------------------------------------------------------------
# Goodness of fit and information criteria
# ---------------------------------------------------------------------------
def r_squared(y, y_fit) -> float:
    y = np.asarray(y, dtype=float)
    y_fit = np.asarray(y_fit, dtype=float)
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot <= 0:
        return float("nan")
    return 1.0 - float(np.sum((y - y_fit) ** 2)) / ss_tot


def aic(n: int, rss: float, k: int, corrected: bool = True) -> float:
    """Akaike information criterion for a Gaussian-error least-squares fit,
    with the small-sample correction (AICc) by default."""
    if n <= 0 or rss <= 0:
        return float("inf")
    value = n * math.log(rss / n) + 2 * k
    if corrected and n - k - 1 > 0:
        value += 2 * k * (k + 1) / (n - k - 1)
    return float(value)


def bic(n: int, rss: float, k: int) -> float:
    if n <= 0 or rss <= 0:
        return float("inf")
    return float(n * math.log(rss / n) + k * math.log(n))


# ---------------------------------------------------------------------------
# Multi-peak fitting
# ---------------------------------------------------------------------------
@dataclass
class PeakResult:
    center: float
    height: float
    fwhm: float
    area: float
    eta: float = float("nan")      # pseudo-Voigt mixing
    sigma: float = float("nan")    # Voigt Gaussian width
    gamma: float = float("nan")    # Voigt Lorentzian HWHM
    center_err: float = float("nan")
    height_err: float = float("nan")
    fwhm_err: float = float("nan")

    def as_dict(self) -> Dict[str, float]:
        return {"center": self.center, "height": self.height, "fwhm": self.fwhm,
                "area": self.area, "eta": self.eta, "sigma": self.sigma, "gamma": self.gamma,
                "center_err": self.center_err, "height_err": self.height_err,
                "fwhm_err": self.fwhm_err}


@dataclass
class FitResult:
    shape: str
    peaks: List[PeakResult]
    baseline: Tuple[float, float]          # (offset, slope) of the fitted linear baseline
    y_fit: np.ndarray
    components: List[np.ndarray]
    r2: float
    rss: float
    n_points: int
    n_params: int
    aic: float
    bic: float
    success: bool = True
    message: str = ""

    @property
    def redchi(self) -> float:
        dof = max(self.n_points - self.n_params, 1)
        return self.rss / dof

    def table(self) -> List[Dict[str, float]]:
        return [p.as_dict() for p in self.peaks]


def _n_shape_params(shape: str) -> int:
    return {"gaussian": 3, "lorentzian": 3, "pvoigt": 4, "voigt": 4}[shape]


def _component(shape: str, x, params):
    if shape == "gaussian":
        return gaussian(x, *params)
    if shape == "lorentzian":
        return lorentzian(x, *params)
    if shape == "pvoigt":
        return pseudo_voigt(x, *params)
    return voigt(x, *params)


def _model_factory(shape: str, n_peaks: int, baseline: str):
    npar = _n_shape_params(shape)

    def model(x, *theta):
        y = np.zeros_like(np.asarray(x, dtype=float))
        for i in range(n_peaks):
            y = y + _component(shape, x, theta[i * npar:(i + 1) * npar])
        if baseline == "const":
            y = y + theta[-1]
        elif baseline == "linear":
            y = y + theta[-2] + theta[-1] * (np.asarray(x, dtype=float) - float(np.mean(x)))
        return y

    return model


def fit_peaks(x, y, centers: Sequence[float], shape: str = "gaussian",
              fwhm0: Optional[Sequence[float]] = None, baseline: str = "none",
              center_window: Optional[float] = None, max_fwhm: Optional[float] = None,
              share_fwhm: bool = False, maxfev: int = 20000) -> FitResult:
    """Fit a sum of line shapes (plus an optional constant/linear baseline)
    with bounded least squares.

    centers      initial peak positions; the number of peaks is len(centers)
    shape        gaussian | lorentzian | pvoigt | voigt
    fwhm0        initial widths; estimated from the data when None
    baseline     none | const | linear
    center_window  each center may move at most this far from its start
                   (default: half the distance to the nearest neighbour,
                   or 10% of the x range for an isolated peak)
    max_fwhm     upper bound on FWHM (default: the x range)
    share_fwhm   constrain all peaks to one common width (useful for
                 instrument-limited line shapes)

    Returns a FitResult; `success` is False and the peaks are left at their
    initial guesses when the optimiser fails.
    """
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}")
    if baseline not in ("none", "const", "linear"):
        raise ValueError("baseline must be none | const | linear")

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x)
    x, y = x[order], y[order]
    n = len(x)
    centers = [float(c) for c in centers]
    k = len(centers)
    if k == 0:
        raise ValueError("at least one center is required")
    npar = _n_shape_params(shape)
    n_base = {"none": 0, "const": 1, "linear": 2}[baseline]
    if n < k * npar + n_base + 2:
        # not enough finite points to constrain the model: report, do not raise
        empty = np.full(n, np.nan)
        return FitResult(shape=shape, peaks=[], baseline=(0.0, 0.0), y_fit=empty, components=[],
                         r2=float("nan"), rss=float("nan"), n_points=n, n_params=k * npar + n_base,
                         aic=float("inf"), bic=float("inf"), success=False,
                         message="too few finite points for the requested model")
    x_range = float(x.max() - x.min()) if n > 1 else 1.0
    step = float(np.median(np.diff(x))) if n > 1 else 1e-3
    if max_fwhm is None:
        max_fwhm = x_range

    # ---- initial guesses --------------------------------------------------
    if fwhm0 is None:
        fwhm0 = []
        for c in centers:
            fwhm0.append(_estimate_fwhm(x, y, c, step, x_range))
    fwhm0 = [float(max(w, 2 * step)) for w in fwhm0]
    y_floor = float(np.min(y))
    heights0 = []
    for c in centers:
        i = int(np.argmin(np.abs(x - c)))
        heights0.append(max(float(y[i]) - (y_floor if baseline != "none" else 0.0), 1e-9 * max(abs(y).max(), 1.0)))

    sorted_c = sorted(centers)
    def _window(c):
        if center_window is not None:
            return float(center_window)
        if k == 1:
            return 0.10 * x_range
        idx = sorted_c.index(c)
        neigh = []
        if idx > 0:
            neigh.append(c - sorted_c[idx - 1])
        if idx < k - 1:
            neigh.append(sorted_c[idx + 1] - c)
        return max(0.5 * min(neigh), 2 * step)

    p0, lo, hi = [], [], []
    for c, h, w in zip(centers, heights0, fwhm0):
        win = _window(c)
        if shape in ("gaussian", "lorentzian"):
            p0 += [h, c, w]
            lo += [0.0, c - win, step]
            hi += [np.inf, c + win, max_fwhm]
        elif shape == "pvoigt":
            p0 += [h, c, w, 0.5]
            lo += [0.0, c - win, step, 0.0]
            hi += [np.inf, c + win, max_fwhm, 1.0]
        else:  # voigt: sigma, gamma from an equal-split FWHM
            p0 += [h, c, w / (2.0 * _SQRT_2LN2) * 0.7, w / 2.0 * 0.5]
            lo += [0.0, c - win, step / 10.0, 0.0]
            hi += [np.inf, c + win, max_fwhm, max_fwhm]
    if baseline == "const":
        p0 += [y_floor]
        lo += [-np.inf]
        hi += [np.inf]
    elif baseline == "linear":
        p0 += [y_floor, 0.0]
        lo += [-np.inf, -np.inf]
        hi += [np.inf, np.inf]

    model = _model_factory(shape, k, baseline)
    if share_fwhm and k > 1 and shape in ("gaussian", "lorentzian", "pvoigt"):
        model, p0, lo, hi = _shared_width_model(shape, k, baseline, p0, lo, hi)

    n_params = len(p0)
    try:
        popt, pcov = curve_fit(model, x, y, p0=p0, bounds=(lo, hi), maxfev=maxfev)
        success, message = True, ""
    except Exception as exc:  # noqa: BLE001 - fit failures are reported, not raised
        popt, pcov = np.asarray(p0, dtype=float), None
        success, message = False, str(exc)

    if share_fwhm and k > 1 and shape in ("gaussian", "lorentzian", "pvoigt"):
        popt_full, perr_full = _expand_shared(shape, k, baseline, popt, pcov)
    else:
        popt_full = np.asarray(popt, dtype=float)
        perr_full = (np.sqrt(np.clip(np.diag(pcov), 0, None))
                     if pcov is not None and np.all(np.isfinite(pcov)) else np.full(len(popt), np.nan))

    y_fit = _model_factory(shape, k, baseline)(x, *popt_full)
    comps, peaks = [], []
    for i in range(k):
        theta = popt_full[i * npar:(i + 1) * npar]
        err = perr_full[i * npar:(i + 1) * npar]
        comps.append(_component(shape, x, theta))
        if shape in ("gaussian", "lorentzian"):
            h, c, w = theta
            peaks.append(PeakResult(center=float(c), height=float(h), fwhm=float(w),
                                    area=peak_area(shape, h, w),
                                    center_err=float(err[1]), height_err=float(err[0]), fwhm_err=float(err[2])))
        elif shape == "pvoigt":
            h, c, w, eta = theta
            peaks.append(PeakResult(center=float(c), height=float(h), fwhm=float(w), eta=float(eta),
                                    area=peak_area(shape, h, w, eta),
                                    center_err=float(err[1]), height_err=float(err[0]), fwhm_err=float(err[2])))
        else:
            h, c, s, g = theta
            peaks.append(PeakResult(center=float(c), height=float(h), fwhm=voigt_fwhm(s, g),
                                    sigma=float(s), gamma=float(g),
                                    area=peak_area("voigt", h, float("nan"), sigma=s, gamma=g),
                                    center_err=float(err[1]), height_err=float(err[0])))
    if baseline == "const":
        base = (float(popt_full[-1]), 0.0)
    elif baseline == "linear":
        base = (float(popt_full[-2]), float(popt_full[-1]))
    else:
        base = (0.0, 0.0)

    rss = float(np.sum((y - y_fit) ** 2))
    result = FitResult(shape=shape, peaks=peaks, baseline=base, y_fit=y_fit, components=comps,
                       r2=r_squared(y, y_fit), rss=rss, n_points=n, n_params=n_params,
                       aic=aic(n, rss, n_params), bic=bic(n, rss, n_params),
                       success=success, message=message)
    # restore caller order (peaks sorted by center for determinism)
    result.peaks.sort(key=lambda p: p.center)
    return result


def _estimate_fwhm(x, y, c, step, x_range):
    """Half-maximum width of the local feature around c (above the local floor)."""
    i = int(np.argmin(np.abs(x - c)))
    span = max(int(0.1 * len(x)), 5)
    lo, hi = max(0, i - span), min(len(x), i + span + 1)
    seg_y = y[lo:hi]
    floor = float(np.min(seg_y))
    half = floor + 0.5 * (float(y[i]) - floor)
    l = i
    while l > lo and y[l] > half:
        l -= 1
    r = i
    while r < hi - 1 and y[r] > half:
        r += 1
    w = abs(float(x[r] - x[l]))
    if not np.isfinite(w) or w < 2 * step:
        w = max(5 * step, 0.01 * x_range)
    return w


def _shared_width_model(shape, k, baseline, p0, lo, hi):
    """Re-parametrise so that one width is shared by all peaks."""
    npar = _n_shape_params(shape)
    widths = [p0[i * npar + 2] for i in range(k)]
    w0 = float(np.median(widths))
    new_p0, new_lo, new_hi = [], [], []
    for i in range(k):
        base = i * npar
        idx = [base, base + 1] + ([base + 3] if shape == "pvoigt" else [])
        new_p0 += [p0[j] for j in idx]
        new_lo += [lo[j] for j in idx]
        new_hi += [hi[j] for j in idx]
    new_p0.append(w0)
    new_lo.append(lo[2])
    new_hi.append(hi[2])
    nb = {"none": 0, "const": 1, "linear": 2}[baseline]
    if nb:
        new_p0 += p0[-nb:]
        new_lo += lo[-nb:]
        new_hi += hi[-nb:]
    full = _model_factory(shape, k, baseline)

    def model(x, *theta):
        return full(x, *_expand_shared(shape, k, baseline, np.asarray(theta), None)[0])

    return model, new_p0, new_lo, new_hi


def _expand_shared(shape, k, baseline, theta, pcov):
    npar = _n_shape_params(shape)
    per = 2 + (1 if shape == "pvoigt" else 0)
    nb = {"none": 0, "const": 1, "linear": 2}[baseline]
    w = float(theta[k * per])
    out, err = [], []
    perr = (np.sqrt(np.clip(np.diag(pcov), 0, None)) if pcov is not None else np.full(len(theta), np.nan))
    for i in range(k):
        h, c = theta[i * per], theta[i * per + 1]
        he, ce = perr[i * per], perr[i * per + 1]
        if shape == "pvoigt":
            out += [h, c, w, theta[i * per + 2]]
            err += [he, ce, perr[k * per], perr[i * per + 2]]
        else:
            out += [h, c, w]
            err += [he, ce, perr[k * per]]
    if nb:
        out += list(theta[-nb:])
        err += list(perr[-nb:])
    return np.asarray(out, dtype=float), np.asarray(err, dtype=float)


def select_n_peaks(x, y, max_peaks: int = 4, shape: str = "gaussian", baseline: str = "none",
                   criterion: str = "aic", min_height_frac: float = 0.03,
                   seeds: Optional[Sequence[float]] = None) -> FitResult:
    """Choose the number of components by an information criterion.

    Components are added one at a time at the position of the largest
    positive residual of the previous fit (or taken from `seeds` first), and
    the model with the lowest AICc (or BIC) is returned. A new component is
    only accepted when its height exceeds `min_height_frac` of the data range,
    which stops the search fitting noise.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 8:
        raise ValueError("need at least 8 points")
    y_range = float(np.max(y) - np.min(y))
    seeds = list(seeds) if seeds else [float(x[int(np.argmax(y))])]
    centers = [seeds[0]]
    best: Optional[FitResult] = None
    for k in range(1, max_peaks + 1):
        res = fit_peaks(x, y, centers, shape=shape, baseline=baseline)
        score = res.aic if criterion == "aic" else res.bic
        best_score = (best.aic if criterion == "aic" else best.bic) if best is not None else float("inf")
        if res.success and (best is None or score < best_score - 1e-9):
            best = res
        elif best is not None:
            break
        if k == max_peaks:
            break
        resid = y - res.y_fit
        if k < len(seeds):
            centers.append(seeds[k])
            continue
        # next seed: largest positive residual away from existing centers
        mask = np.ones_like(x, dtype=bool)
        for c in centers:
            w = max(_estimate_fwhm(x, y, c, float(np.median(np.diff(x))), float(x.max() - x.min())), 1e-9)
            mask &= np.abs(x - c) > 0.5 * w
        if not np.any(mask):
            break
        j = int(np.argmax(np.where(mask, resid, -np.inf)))
        if resid[j] < min_height_frac * y_range:
            break
        centers.append(float(x[j]))
    if best is None:
        best = fit_peaks(x, y, centers[:1], shape=shape, baseline=baseline)
    return best


# ---------------------------------------------------------------------------
# Peak finding and matching
# ---------------------------------------------------------------------------
def find_peaks_robust(x, y, prominence_frac: float = 0.02, noise_k: float = 0.0,
                      min_separation: float = 0.0, invert: bool = False):
    """Peak positions from scipy.find_peaks with a prominence threshold taken
    as the larger of a fraction of the data range and `noise_k` times the MAD
    noise. Returns (positions, indices, prominences)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return np.array([]), np.array([], dtype=int), np.array([])
    yy = -y if invert else y
    rng = float(np.max(yy) - np.min(yy))
    prom = prominence_frac * rng
    if noise_k > 0:
        prom = max(prom, noise_k * robust_noise_sigma(yy))
    kwargs = {"prominence": prom}
    if min_separation > 0 and len(x) > 1:
        dx = float(np.median(np.abs(np.diff(x))))
        if dx > 0:
            kwargs["distance"] = max(1, int(round(min_separation / dx)))
    idx, props = find_peaks(yy, **kwargs)
    return x[idx], idx, props.get("prominences", np.full(len(idx), np.nan))


def numeric_fwhm(x, y, index: Optional[int] = None) -> float:
    """FWHM of the feature at `index` (default: global maximum) by linear
    interpolation of the half-maximum crossings. Baseline is the minimum of
    the data; subtract a baseline first for a cleaner value."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3:
        return float("nan")
    i = int(np.argmax(y)) if index is None else int(index)
    floor = float(np.min(y))
    half = floor + 0.5 * (y[i] - floor)
    l = i
    while l > 0 and y[l] > half:
        l -= 1
    r = i
    while r < len(y) - 1 and y[r] > half:
        r += 1
    if l == i or r == i:
        return float("nan")
    xl = np.interp(half, [y[l], y[l + 1]], [x[l], x[l + 1]]) if y[l + 1] != y[l] else x[l]
    xr = np.interp(half, [y[r], y[r - 1]], [x[r], x[r - 1]]) if y[r - 1] != y[r] else x[r]
    return float(abs(xr - xl))


def match_peaks(reference: Sequence[float], sample: Sequence[float], tolerance: float):
    """Pair each reference peak with the nearest sample peak within
    `tolerance` (one-to-one, greedy by distance). Returns a list of dicts
    with reference, sample, shift (sample - reference) and unmatched lists."""
    ref = sorted(float(v) for v in reference)
    smp = sorted(float(v) for v in sample)
    pairs = []
    for i, r in enumerate(ref):
        for j, s in enumerate(smp):
            d = abs(s - r)
            if d <= tolerance:
                pairs.append((d, i, j))
    pairs.sort()
    used_r, used_s, out = set(), set(), []
    for d, i, j in pairs:
        if i in used_r or j in used_s:
            continue
        used_r.add(i)
        used_s.add(j)
        out.append({"reference": ref[i], "sample": smp[j], "shift": smp[j] - ref[i]})
    out.sort(key=lambda m: m["reference"])
    return {"matched": out,
            "unmatched_reference": [ref[i] for i in range(len(ref)) if i not in used_r],
            "unmatched_sample": [smp[j] for j in range(len(smp)) if j not in used_s]}


# ---------------------------------------------------------------------------
# Axis conversion and normalisation
# ---------------------------------------------------------------------------
def nm_to_ev(wavelength_nm):
    return HC_EV_NM / np.asarray(wavelength_nm, dtype=float)


def ev_to_nm(energy_ev):
    return HC_EV_NM / np.asarray(energy_ev, dtype=float)


def spectrum_to_energy(wavelength_nm, intensity, jacobian: bool = True):
    """Convert an intensity-per-wavelength spectrum to intensity per energy.

    I(E) dE = I(lambda) dlambda  =>  I(E) = I(lambda) * lambda^2 / (h c).
    Omitting the Jacobian (a common error) shifts broad PL peaks to higher
    energy and distorts their width (Mooney & Kambhampati 2013). Returns
    (energy_eV ascending, intensity_per_eV) with the normalisation such that
    the integrated intensity is preserved.
    """
    wl = np.asarray(wavelength_nm, dtype=float)
    y = np.asarray(intensity, dtype=float)
    ok = np.isfinite(wl) & np.isfinite(y) & (wl > 0)
    wl, y = wl[ok], y[ok]
    e = HC_EV_NM / wl
    ye = y * wl ** 2 / HC_EV_NM if jacobian else y
    order = np.argsort(e)
    return e[order], ye[order]


def normalize(y, mode: str = "max"):
    """max | area | minmax | vector | none"""
    y = np.asarray(y, dtype=float)
    if mode == "none" or len(y) == 0:
        return y.copy()
    if mode == "max":
        m = float(np.nanmax(np.abs(y)))
        return y / m if m > 0 else y.copy()
    if mode == "minmax":
        lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
        return (y - lo) / (hi - lo) if hi > lo else np.zeros_like(y)
    if mode == "area":
        a = float(np.nansum(np.abs(y)))
        return y / a if a > 0 else y.copy()
    if mode == "vector":
        n = float(np.sqrt(np.nansum(y ** 2)))
        return y / n if n > 0 else y.copy()
    raise ValueError(f"unknown normalisation {mode!r}")


def integrate(x, y) -> float:
    """Trapezoidal integral over x (sorted internally)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 2:
        return float("nan")
    order = np.argsort(x)
    trap = getattr(np, "trapezoid", None) or np.trapz
    return float(trap(y[order], x=x[order]))


def centroid(x, y) -> float:
    """Intensity-weighted mean position (first moment)."""
    x = np.asarray(x, dtype=float)
    y = np.clip(np.asarray(y, dtype=float), 0, None)
    s = float(np.sum(y))
    return float(np.sum(x * y) / s) if s > 0 else float("nan")
