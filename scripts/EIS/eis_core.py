"""Impedance spectroscopy: equivalent-circuit fit (complex non-linear least
squares), the linear Kramers-Kronig validity test and the distribution of
relaxation times (DRT).

Circuits (series resistance plus one or two parallel arcs)
    R(RC)        Rs + R1 || C1
    R(RQ)        Rs + R1 || CPE1                Z_CPE = 1 / (Q (j w)^alpha)
    R(RC)(RC)    Rs + R1 || C1 + R2 || C2
    R(RQ)(RQ)    Rs + R1 || CPE1 + R2 || CPE2

Each residual is divided by |Z| (modulus weighting), so every decade of
frequency counts equally. Parameters are fitted in log10 space, alpha is
bounded to [0.4, 1], and the standard errors come from the Jacobian at the
optimum. The circuit is chosen with AICc among those whose arcs are
separable (time constants a factor 3 apart, each resistance determined).

Per arc:  tau = (R Q)^(1/alpha),  f_peak = 1 / (2 pi tau),
          C_eff = Q^(1/alpha) R^((1 - alpha)/alpha)       (Hsu and Mansfeld)

Linear Kramers-Kronig test: the spectrum is fitted with a chain of M RC
elements at fixed, logarithmically spaced time constants, which is a linear
problem. A spectrum that this chain cannot reproduce is not a linear,
causal, time-invariant response - the sample drifted during the sweep or
was driven non-linearly - and no equivalent circuit should be fitted to it.
M is the smallest number of elements whose rms residual is within 10 % of
the lowest residual any M reaches; the criterion mu of Schoenleber is
reported with it (mu < 0.85 marks an over-fitted chain).

Distribution of relaxation times: Z = R_inf + j w L + integral gamma(ln tau)
/ (1 + j w tau) d ln tau, solved for gamma >= 0 by Tikhonov-regularised
non-negative least squares (second-derivative penalty, modulus weighting);
the regularisation is the largest whose residual stays within 5 % of the
least regularised fit. It shows how many relaxation processes the spectrum
holds without choosing a circuit first; a peak's area is its resistance.

Sign convention: capacitive Z'' is negative. Files that store -Z'' (most
positive values) are detected and converted.

References
    Boukamp, J. Electrochem. Soc. 142, 1885 (1995)                  linear KK test
    Schoenleber, Klotz, Ivers-Tiffee, Electrochim. Acta 131, 20 (2014)
    Hsu, Mansfeld, Corrosion 57, 747 (2001)                          C_eff of a CPE
    Guerrero, Bisquert, Garcia-Belmonte, Chem. Rev. 121, 14430 (2021)
    von Hauff, Klotz, J. Mater. Chem. C 10, 742 (2022)
    Ebadi et al., Nat. Commun. 10, 1574 (2019)                       negative capacitance
    Wan, Saccoccio, Chen, Ciucci, Electrochim. Acta 184, 483 (2015)  DRT by regularised regression
    Hansen, Rank-Deficient and Discrete Ill-Posed Problems (SIAM, 1998), ch. 7   choice of lambda
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares

EPS0 = 8.8541878128e-12
MODELS: Dict[str, Tuple[str, ...]] = {"R(RC)": ("C",), "R(RQ)": ("Q",), "R(RC)(RC)": ("C", "C"), "R(RQ)(RQ)": ("Q", "Q")}
MIN_TAU_RATIO, ALPHA_MIN = 3.0, 0.4

COLUMN_SPEC = [
    ("f", [r"freq", r"^f\b", r"\bhz\b"], 0),
    ("zre", [r"z'?\s*\(?re", r"re\s*\(?z", r"z'(?!')", r"zreal", r"z_re", r"real"], 1),
    ("zim", [r"z''", r"im\s*\(?z", r"zimag", r"z_im", r"imag"], 2),
]


def prepare(f, zre, zim, convention: str = "auto", f_min: Optional[float] = None,
            f_max: Optional[float] = None) -> Dict[str, Any]:
    """Clean and sort a spectrum (high to low frequency); returns complex Z
    with capacitive Z'' negative."""
    f, zr, zi = (np.asarray(a, float) for a in (f, zre, zim))
    ok = np.isfinite(f) & np.isfinite(zr) & np.isfinite(zi) & (f > 0)
    if f_min is not None:
        ok &= f >= f_min
    if f_max is not None:
        ok &= f <= f_max
    f, zr, zi = f[ok], zr[ok], zi[ok]
    if len(f) < 8:
        raise ValueError("impedance analysis needs at least 8 frequencies")
    order = np.argsort(-f, kind="stable")
    f, zr, zi = f[order], zr[order], zi[order]
    flipped = False
    if convention == "-Z''" or (convention == "auto" and np.median(zi) > 0):
        zi, flipped = -zi, True
    return {"f": f, "z": zr + 1j * zi, "flipped": flipped}


def z_model(name: str, p: Sequence[float], f) -> np.ndarray:
    """Impedance of a circuit; p in natural units [Rs, (R, C) | (R, Q, alpha), ...]."""
    s = 2j * np.pi * np.asarray(f, float)
    z = np.full(s.shape, complex(p[0]))
    k = 1
    for kind in MODELS[name]:
        if kind == "C":
            z = z + p[k] / (1.0 + s * p[k] * p[k + 1])
            k += 2
        else:
            z = z + p[k] / (1.0 + p[k] * p[k + 1] * np.power(s, p[k + 2]))
            k += 3
    return z


def _unpack(name: str, x) -> np.ndarray:
    out, k = [10.0 ** x[0]], 1
    for kind in MODELS[name]:
        out += [10.0 ** x[k], 10.0 ** x[k + 1]]
        k += 2
        if kind == "Q":
            out.append(x[k])
            k += 1
    return np.array(out)


def param_names(name: str) -> List[str]:
    names = ["Rs"]
    for i, kind in enumerate(MODELS[name], 1):
        names += [f"R{i}", f"{kind}{i}"] + ([f"alpha{i}"] if kind == "Q" else [])
    return names


def _starts(name: str, f, z) -> List[np.ndarray]:
    zr, zi = z.real, -z.imag
    rs = max(float(zr.min()), 1e-3 * float(np.abs(z).max()), 1e-6)
    rtot = max(float(zr.max()) - rs, 1e-3 * rs)
    f_pk = float(f[int(np.argmax(zi))])
    kinds = MODELS[name]
    out = []
    if len(kinds) == 1:
        for scale in (1.0, 0.3, 3.0):
            x = [np.log10(rs), np.log10(rtot), np.log10(1.0 / (2 * np.pi * f_pk * scale * rtot))]
            out.append(np.array(x + ([0.9] if kinds[0] == "Q" else [])))
        return out
    for share in (0.5, 0.2, 0.8):
        for sep in (30.0, 1000.0, 3.0):
            r1, r2 = share * rtot, (1 - share) * rtot
            f1, f2 = f_pk * np.sqrt(sep), f_pk / np.sqrt(sep)
            x = [np.log10(rs)]
            for r, fp, kind in ((r1, f1, kinds[0]), (r2, f2, kinds[1])):
                x += [np.log10(r), np.log10(1.0 / (2 * np.pi * fp * r))] + ([0.9] if kind == "Q" else [])
            out.append(np.array(x))
    return out


def _bounds(name: str) -> Tuple[List[float], List[float]]:
    lo, hi = [-6.0], [12.0]
    for kind in MODELS[name]:
        lo += [-6.0, -15.0]
        hi += [12.0, 3.0]
        if kind == "Q":
            lo.append(ALPHA_MIN)
            hi.append(1.0)
    return lo, hi


def _arcs(name: str, p, perr) -> List[Dict[str, float]]:
    arcs, k = [], 1
    for kind in MODELS[name]:
        r, q = p[k], p[k + 1]
        a = p[k + 2] if kind == "Q" else 1.0
        arc = {"kind": kind, "R": float(r), "R_err": float(perr[k]), "Q": float(q), "Q_err": float(perr[k + 1]),
               "alpha": float(a), "alpha_err": float(perr[k + 2]) if kind == "Q" else 0.0}
        tau = (r * q) ** (1.0 / a)
        arc.update({"tau_s": float(tau), "f_peak_Hz": float(1.0 / (2 * np.pi * tau)),
                    "C_eff_F": float(q ** (1.0 / a) * r ** ((1.0 - a) / a))})
        arcs.append(arc)
        k += 3 if kind == "Q" else 2
    return arcs


def fit_model(name: str, f, z) -> Dict[str, Any]:
    f, z = np.asarray(f, float), np.asarray(z, complex)
    mod = np.abs(z)
    lo, hi = _bounds(name)

    def resid(x):
        d = z_model(name, _unpack(name, x), f) - z
        return np.r_[d.real / mod, d.imag / mod]

    best = None
    for x0 in _starts(name, f, z):
        try:
            sol = least_squares(resid, np.clip(x0, lo, hi), bounds=(lo, hi), method="trf", x_scale="jac", max_nfev=800)
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"the {name} fit did not converge")
    x = best.x
    n, k = 2 * len(f), len(x)
    rss = float((best.fun ** 2).sum())
    s2 = rss / max(n - k, 1)
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * s2
    except Exception:
        cov = np.full((k, k), np.nan)
    xerr = np.sqrt(np.clip(np.diag(cov), 0, None))
    p = _unpack(name, x)
    names = param_names(name)
    perr = np.array([xe if nm.startswith("alpha") else np.log(10.0) * xe * pv for nm, xe, pv in zip(names, xerr, p)])
    arcs = sorted(_arcs(name, p, perr), key=lambda a: a["tau_s"])
    aicc = n * np.log(max(rss, 1e-300) / n) + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n > k + 1 else np.inf)
    out = {"model": name, "p": p, "perr": perr, "names": names, "arcs": arcs, "Rs": float(p[0]), "Rs_err": float(perr[0]),
           "rss": rss, "rms_pct": float(100.0 * np.sqrt(rss / n)), "aicc": float(aicc), "k": k, "valid": True, "reason": ""}
    rtot = sum(a["R"] for a in arcs)
    if any(not np.isfinite(a["R_err"]) or a["R_err"] > a["R"] for a in arcs):
        out.update({"valid": False, "reason": "a resistance is not determined (relative error above 100 %)"})
    elif len(arcs) == 2 and arcs[1]["tau_s"] / arcs[0]["tau_s"] < MIN_TAU_RATIO:
        out.update({"valid": False, "reason": "the two time constants are closer than a factor 3"})
    elif len(arcs) == 2 and min(a["R"] for a in arcs) < 0.01 * rtot:
        out.update({"valid": False, "reason": "one arc carries less than 1 % of the resistance"})
    elif any(a["kind"] == "Q" and a["alpha"] <= ALPHA_MIN + 0.01 for a in arcs):
        out.update({"valid": False, "reason": "a CPE exponent ran into its lower bound"})
    return out


def choose_model(fits: Dict[str, Dict[str, Any]]) -> str:
    cand = [v for v in fits.values() if v.get("valid") and "p" in v]
    if not cand:
        cand = [v for v in fits.values() if "p" in v]
    best = min(c["aicc"] for c in cand)
    for c in sorted(cand, key=lambda c: c["k"]):
        if c["aicc"] - best <= 2.0:
            return c["model"]
    return cand[0]["model"]


def lin_kk(f, z, mu_limit: float = 0.85, max_m: Optional[int] = None) -> Dict[str, Any]:
    """Linear Kramers-Kronig test. Residuals in % of |Z|.

    The number of RC elements M is the smallest one whose rms residual is
    within 10 % of the lowest residual any M reaches (up to four elements
    per decade), so the chain is neither too coarse to follow a valid
    spectrum nor free to follow the noise. Schoenleber's mu (1 = no
    oscillating resistances, small = over-fitting) is reported with it."""
    f, z = np.asarray(f, float), np.asarray(z, complex)
    w = 2 * np.pi * f
    mod = np.abs(z)
    n = len(f)
    decades = np.log10(f.max() / f.min())
    max_m = int(max_m or max(4, min(n - 3, int(np.ceil(4 * decades)))))
    trials = []
    for m in range(3, max_m + 1):
        tau = 1.0 / np.geomspace(w.max(), w.min(), m)
        cols = [np.ones(n, complex)] + [1.0 / (1.0 + 1j * w * t) for t in tau] + [1j * w]
        a = np.column_stack(cols)
        aw = np.vstack([a.real / mod[:, None], a.imag / mod[:, None]])
        bw = np.r_[z.real / mod, z.imag / mod]
        scale = np.linalg.norm(aw, axis=0)
        scale[scale == 0] = 1.0
        x = np.linalg.lstsq(aw / scale, bw, rcond=None)[0] / scale
        r = x[1:1 + m]
        neg, pos = np.abs(r[r < 0]).sum(), np.abs(r[r >= 0]).sum()
        zf = a @ x
        re, im = 100.0 * (z.real - zf.real) / mod, 100.0 * (z.imag - zf.imag) / mod
        trials.append({"M": m, "mu": float(1.0 - neg / pos) if pos > 0 else 0.0, "zfit": zf, "res_re_pct": re,
                       "res_im_pct": im, "rms_pct": float(np.sqrt(np.mean(np.r_[re, im] ** 2)))})
    floor = min(t["rms_pct"] for t in trials)
    out = next(t for t in trials if t["rms_pct"] <= 1.1 * floor + 1e-9)
    both = np.r_[out["res_re_pct"], out["res_im_pct"]]
    out["max_pct"] = float(np.abs(both).max())
    low = f <= f.min() * 10.0
    out["low_f_rms_pct"] = float(np.sqrt(np.mean(np.r_[out["res_re_pct"][low], out["res_im_pct"][low]] ** 2)))
    out["over_fitted"] = bool(out["mu"] < mu_limit)
    return out


# ---------------------------------------------------------------------------
# distribution of relaxation times
# ---------------------------------------------------------------------------
DRT_PER_DECADE, DRT_EXTEND_DEC = 10, 1.0
DRT_LAMBDAS = np.logspace(-7, 2, 37)
DRT_DISCREPANCY = 1.05              # allowed rms residual, relative to the least regularised fit
DRT_PEAK_PROMINENCE = 0.05          # of the largest gamma
DRT_MINOR = 0.05                    # a peak below this fraction of R_pol is merged into the nearest larger one


def _drt_design(f, tau) -> Tuple[np.ndarray, float]:
    """Columns R_inf, L (j w), gamma_m dln(tau) / (1 + j w tau_m)."""
    w = 2 * np.pi * np.asarray(f, float)
    dln = float(np.log(tau[1] / tau[0]))
    k = dln / (1.0 + 1j * w[:, None] * tau[None, :])
    return np.column_stack([np.ones(len(w), complex), 1j * w, k]), dln


def _nnls_tikhonov(a_rows: np.ndarray, b: np.ndarray, lam: float, n_gamma: int, cols: Sequence[int]) -> np.ndarray:
    """min ||a x - b||^2 + lam ||D2 gamma||^2 with x >= 0 over the chosen
    columns (the others are zero); columns are scaled to unit norm first."""
    from scipy.optimize import nnls
    cols = list(cols)
    a = a_rows[:, cols]
    scale = np.linalg.norm(a, axis=0)
    scale[scale == 0] = 1.0
    a = a / scale
    n_extra = len(cols) - n_gamma
    d2 = np.zeros((n_gamma - 2, len(cols)))
    for i in range(n_gamma - 2):
        d2[i, n_extra + i:n_extra + i + 3] = (1.0, -2.0, 1.0)
    d2 = d2 / scale                     # the penalty acts on gamma itself, not on the scaled unknowns
    d2 = d2 * (np.linalg.norm(a[:, n_extra:]) / max(np.linalg.norm(d2), 1e-300))
    m = np.vstack([a, np.sqrt(lam) * d2])
    rhs = np.r_[b, np.zeros(n_gamma - 2)]
    x = nnls(m, rhs, maxiter=50 * m.shape[1])[0] / scale
    out = np.zeros(a_rows.shape[1])
    out[cols] = x
    return out


def drt(f, z, lam: Optional[float] = None, per_decade: int = DRT_PER_DECADE,
        extend_dec: float = DRT_EXTEND_DEC) -> Dict[str, Any]:
    """Distribution of relaxation times by Tikhonov-regularised non-negative
    least squares.

        Z(w) = R_inf + j w L + integral gamma(ln tau) / (1 + j w tau) d ln tau

    gamma is collocated on `per_decade` points per decade, `extend_dec`
    decades beyond 1 / w at both ends of the spectrum, with a second-
    derivative penalty and modulus weighting. lam (relative to the scale of
    the data) is the largest value of a logarithmic grid whose rms residual
    stays within 5 % of the residual of the least regularised fit
    (discrepancy principle, with the noise level taken from the spectrum
    itself). Peaks with a prominence of at least 5 % of the largest gamma
    are processes; the resistance of each is the area of gamma between the
    minima around it, and a peak below 5 % of the total area is merged into
    the nearest larger one."""
    f, z = np.asarray(f, float), np.asarray(z, complex)
    w = 2 * np.pi * f
    mod = np.abs(z)
    tau = np.geomspace(1.0 / w.max() / 10 ** extend_dec, 1.0 / w.min() * 10 ** extend_dec,
                       int(round(np.log10(w.max() / w.min()) + 2 * extend_dec) * per_decade) + 1)
    a, dln = _drt_design(f, tau)
    n_g = len(tau)
    a_w = np.vstack([a.real / mod[:, None], a.imag / mod[:, None]])
    b_w = np.r_[z.real / mod, z.imag / mod]
    cols = [0, 1] + list(range(2, 2 + n_g))

    def solve(lm):
        x = _nnls_tikhonov(a_w, b_w, lm, n_g, cols)
        zf = a @ x
        r = np.r_[100.0 * (z.real - zf.real) / mod, 100.0 * (z.imag - zf.imag) / mod]
        return x, zf, r

    if lam is None:
        trials = [solve(lm) for lm in DRT_LAMBDAS]
        rms = np.array([float(np.sqrt(np.mean(t[2] ** 2))) for t in trials])
        ok = np.where(rms <= DRT_DISCREPANCY * rms[0] + 1e-12)[0]
        i = int(ok[-1])
        lam_best, (x, zfit, res_pct) = float(DRT_LAMBDAS[i]), trials[i]
        at_edge = i == len(DRT_LAMBDAS) - 1
    else:
        lam_best, at_edge = float(lam), False
        x, zfit, res_pct = solve(lam_best)
        rms = np.array([float(np.sqrt(np.mean(res_pct ** 2)))])
    gamma = x[2:]
    r_pol = float(gamma.sum() * dln)
    peaks = _merge_minor(_drt_peaks(tau, gamma, dln), r_pol)
    inside = (tau >= 1.0 / w.max()) & (tau <= 1.0 / w.min())
    return {"tau": tau, "gamma": gamma, "dln_tau": dln, "R_inf": float(x[0]), "L": float(x[1]), "R_pol": r_pol,
            "lam": lam_best, "lam_at_edge": bool(at_edge), "lambdas": DRT_LAMBDAS.copy() if lam is None else np.array([lam_best]),
            "rms_curve": rms, "zfit": zfit, "rms_pct": float(np.sqrt(np.mean(res_pct ** 2))),
            "max_pct": float(np.abs(res_pct).max()), "peaks": peaks,
            "n_processes": len(peaks),
            "outside_R": float(gamma[~inside].sum() * dln)}


def _merge_minor(peaks: List[Dict[str, float]], r_pol: float) -> List[Dict[str, Any]]:
    """A peak holding less than DRT_MINOR of the polarisation resistance is
    not resolved as a process of its own (regularisation side lobes of a
    broad distribution look like this): its area is added to the nearest
    larger peak in ln tau."""
    for pk in peaks:
        pk["minor"] = bool(r_pol > 0 and pk["R"] < DRT_MINOR * r_pol)
        pk["merged"] = 0
    major = [pk for pk in peaks if not pk["minor"]]
    if not major:
        return peaks
    for pk in peaks:
        if pk["minor"]:
            near = min(major, key=lambda q: abs(np.log(q["tau_s"] / pk["tau_s"])))
            near["R"] += pk["R"]
            near["merged"] += 1
    return major


def _drt_peaks(tau, gamma, dln: float) -> List[Dict[str, float]]:
    from scipy.signal import find_peaks
    if not np.any(gamma > 0):
        return []
    g = np.r_[0.0, gamma, 0.0]                 # a peak at the edge of the grid counts too
    idx, _ = find_peaks(g, prominence=DRT_PEAK_PROMINENCE * float(gamma.max()))
    idx = idx - 1
    out: List[Dict[str, float]] = []
    bounds = [0]
    for a_, b_ in zip(idx[:-1], idx[1:]):
        bounds.append(int(a_ + np.argmin(gamma[a_:b_ + 1])))
    bounds.append(len(gamma) - 1)
    lt = np.log(tau)
    for k, i in enumerate(idx):
        lo, hi = bounds[k], bounds[k + 1]
        r = float(gamma[lo:hi + 1].sum() * dln) if k == len(idx) - 1 else float(gamma[lo:hi].sum() * dln)
        if 0 < i < len(gamma) - 1:
            y0, y1, y2 = gamma[i - 1], gamma[i], gamma[i + 1]
            den = y0 - 2 * y1 + y2
            shift = 0.5 * (y0 - y2) / den if den != 0 else 0.0
            lpk = lt[i] + float(np.clip(shift, -0.5, 0.5)) * (lt[1] - lt[0])
        else:
            lpk = lt[i]
        t_pk = float(np.exp(lpk))
        out.append({"tau_s": t_pk, "f_Hz": 1.0 / (2 * np.pi * t_pk), "R": r, "gamma_max": float(gamma[i])})
    return out


def capacitance_spectrum(f, z) -> np.ndarray:
    """C(f) = Im(1 / Z) / w, the capacitance of the parallel representation."""
    return (1.0 / np.asarray(z, complex)).imag / (2 * np.pi * np.asarray(f, float))


def analyse(f, zre, zim, model: str = "auto", convention: str = "auto", f_min: Optional[float] = None,
            f_max: Optional[float] = None, area_cm2: float = 0.0, thickness_nm: float = 0.0) -> Dict[str, Any]:
    d = prepare(f, zre, zim, convention, f_min, f_max)
    f, z = d["f"], d["z"]
    names = tuple(MODELS) if model == "auto" else (model,)
    fits: Dict[str, Dict[str, Any]] = {}
    for name in names:
        if name not in MODELS:
            raise ValueError(f"unknown circuit: {name}")
        try:
            fits[name] = fit_model(name, f, z)
        except Exception as exc:
            if model != "auto":
                raise
            fits[name] = {"model": name, "valid": False, "reason": str(exc), "aicc": np.inf, "k": 99}
    chosen = choose_model(fits) if model == "auto" else model
    fit = fits[chosen]
    f_dense = np.geomspace(f.max(), f.min(), 400)
    zfit = z_model(chosen, fit["p"], f)
    mod = np.abs(z)
    lim = 0.01 * mod
    n_edge = max(2, len(f) // 10)
    res: Dict[str, Any] = {"f": f, "z": z, "flipped": d["flipped"], "model": chosen, "requested": model,
                           "candidates": fits, "zfit": zfit, "f_dense": f_dense, "z_dense": z_model(chosen, fit["p"], f_dense),
                           "res_re_pct": 100.0 * (z.real - zfit.real) / mod, "res_im_pct": 100.0 * (z.imag - zfit.imag) / mod,
                           "kk": lin_kk(f, z), "C_spectrum_F": capacitance_spectrum(f, z),
                           "area_cm2": float(area_cm2), "thickness_nm": float(thickness_nm),
                           "lf_inductive": int((z.imag[-n_edge:] > lim[-n_edge:]).sum()),
                           "hf_inductive": int((z.imag[:n_edge] > lim[:n_edge]).sum()),
                           "decades": float(np.log10(f.max() / f.min()))}
    for k in ("p", "perr", "names", "arcs", "Rs", "Rs_err", "rms_pct", "aicc", "valid", "reason"):
        res[k] = fit[k]
    res["R_total"] = float(sum(a["R"] for a in fit["arcs"]))
    try:
        res["drt"] = drt(f, z)
    except Exception as exc:                       # noqa: BLE001 - the DRT is an addition to the circuit fit
        res["drt"] = None
        res["drt_error"] = str(exc)
    res["eps_r"] = np.nan
    if area_cm2 > 0 and thickness_nm > 0:
        res["eps_r"] = float(fit["arcs"][0]["C_eff_F"] * thickness_nm * 1e-9 / (EPS0 * area_cm2 * 1e-4))
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    kk = r["kk"]
    if kk["max_pct"] > 2.0 or kk["rms_pct"] > 1.0:
        w.append(f"Kramers-Kronig residuals reach {kk['max_pct']:.1f} % (rms {kk['rms_pct']:.2f} %): the spectrum is "
                 "not a stationary linear response, so circuit parameters fitted to it are not meaningful. Check for "
                 "drift during the sweep and reduce the perturbation amplitude.")
    elif kk["low_f_rms_pct"] > 3.0 * max(kk["rms_pct"], 0.05) and kk["low_f_rms_pct"] > 0.5:
        w.append(f"Kramers-Kronig residuals grow at low frequency ({kk['low_f_rms_pct']:.2f} % against "
                 f"{kk['rms_pct']:.2f} % overall): the sample changed during the slow part of the sweep.")
    if r["rms_pct"] > 2.0:
        w.append(f"The {r['model']} circuit leaves {r['rms_pct']:.1f} % rms residuals: the spectrum has a feature "
                 "this circuit does not contain.")
    if not r["valid"] and r["reason"]:
        w.append(f"The {r['model']} circuit is not supported by the data: {r['reason']}.")
    if r["lf_inductive"] >= 2:
        w.append("Z'' is positive at the lowest frequencies (inductive loop, negative capacitance). In perovskite "
                 "cells this comes from ion-modulated injection or recombination, not from an inductor; the series "
                 "R||C circuits here do not describe it, so restrict the fit to frequencies above the loop.")
    if r["hf_inductive"] >= 2:
        w.append("Z'' is positive at the highest frequencies: lead inductance. Set an upper frequency limit below it.")
    if r["decades"] < 3.0:
        w.append(f"The spectrum covers {r['decades']:.1f} decades of frequency; arcs outside it are not seen.")
    for i, a in enumerate(r["arcs"], 1):
        if a["kind"] == "Q" and a["alpha"] < 0.7:
            w.append(f"CPE exponent of arc {i} is {a['alpha']:.2f}: the arc is strongly depressed and its effective "
                     "capacitance has no simple meaning (two overlapping processes, or diffusion).")
        if a["f_peak_Hz"] > r["f"].max() or a["f_peak_Hz"] < r["f"].min():
            w.append(f"The characteristic frequency of arc {i} ({a['f_peak_Hz']:.3g} Hz) lies outside the measured "
                     "range: the arc is only partly seen and its resistance is an extrapolation.")
    d = r.get("drt")
    if d:
        if r["lf_inductive"] >= 2 or d["rms_pct"] > max(2.0, 3.0 * r["kk"]["rms_pct"]):
            w.append(f"The distribution of relaxation times leaves {d['rms_pct']:.1f} % rms residuals: a non-negative "
                     "DRT cannot represent an inductive loop or a negative capacitance, so read it only for the "
                     "capacitive processes.")
        if d["outside_R"] > 0.1 * max(d["R_pol"], 1e-300):
            w.append(f"{100 * d['outside_R'] / d['R_pol']:.0f} % of the DRT area lies at time constants outside the "
                     "measured frequency range: a process there is extrapolated, extend the sweep to see it.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    rows: List[Tuple[str, Any, str]] = [("Circuit", r["model"], ""), ("Frequencies", len(r["f"]), ""),
                                        ("Rs", r["Rs"], "Ohm"), ("Rs std. error", r["Rs_err"], "Ohm")]
    a_cm2 = r["area_cm2"]
    for i, a in enumerate(r["arcs"], 1):
        rows += [(f"R{i}", a["R"], "Ohm"), (f"R{i} std. error", a["R_err"], "Ohm")]
        if a_cm2 > 0:
            rows.append((f"R{i} x area", a["R"] * a_cm2, "Ohm cm2"))
        if a["kind"] == "Q":
            rows += [(f"Q{i}", a["Q"], "S s^alpha"), (f"alpha{i}", a["alpha"], ""), (f"alpha{i} std. error", a["alpha_err"], "")]
        rows += [(f"C{i} (effective)" if a["kind"] == "Q" else f"C{i}", a["C_eff_F"], "F")]
        if a_cm2 > 0:
            rows.append((f"C{i} / area", 1e9 * a["C_eff_F"] / a_cm2, "nF/cm2"))
        rows += [(f"tau{i}", a["tau_s"], "s"), (f"f_peak{i}", a["f_peak_Hz"], "Hz")]
    rows += [("R total (arcs)", r["R_total"], "Ohm"), ("Fit residual (rms)", r["rms_pct"], "% of |Z|"),
             ("Kramers-Kronig residual (rms)", r["kk"]["rms_pct"], "% of |Z|"),
             ("Kramers-Kronig residual (max)", r["kk"]["max_pct"], "% of |Z|"), ("Kramers-Kronig RC elements", r["kk"]["M"], "")]
    if np.isfinite(r["eps_r"]):
        rows.append(("Relative permittivity (high-frequency arc)", r["eps_r"], ""))
    d = r.get("drt")
    if d:
        rows.append(("DRT processes", d["n_processes"], ""))
        for i, pk in enumerate(d["peaks"], 1):
            rows += [(f"DRT peak {i}: tau", pk["tau_s"], "s"), (f"DRT peak {i}: f", pk["f_Hz"], "Hz"),
                     (f"DRT peak {i}: R" + (" (with merged side peaks)" if pk["merged"] else ""), pk["R"], "Ohm")]
        rows += [("DRT R_inf", d["R_inf"], "Ohm"), ("DRT R_pol (area)", d["R_pol"], "Ohm"),
                 ("DRT lambda", d["lam"], ""), ("DRT residual (rms)", d["rms_pct"], "% of |Z|")]
    return rows


def simulate(model: str = "R(RQ)(RQ)", params: Optional[Sequence[float]] = None, f=None, noise: float = 0.003,
             seed: int = 0, drift: float = 0.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthetic spectrum (f, Z', Z''); `drift` scales the arc resistances
    linearly during the sweep to break Kramers-Kronig consistency."""
    f = np.asarray(f if f is not None else np.geomspace(1e6, 0.1, 71), float)
    p = np.asarray(params if params is not None else (10.0, 200.0, 2e-8, 0.95, 1500.0, 5e-6, 0.85), float)
    if drift:
        z = np.empty(len(f), complex)
        names = param_names(model)
        for i, fi in enumerate(f):
            q = p.copy()
            for k, nm in enumerate(names):
                if nm.startswith("R") and nm != "Rs":
                    q[k] *= 1.0 + drift * i / (len(f) - 1)
            z[i] = z_model(model, q, np.array([fi]))[0]
    else:
        z = z_model(model, p, f)
    if noise:
        rng = np.random.default_rng(seed)
        z = z + np.abs(z) * noise * (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f)))
    return f, z.real, z.imag
