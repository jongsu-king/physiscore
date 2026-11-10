"""Impedance spectroscopy: equivalent-circuit fit (complex non-linear least
squares) and the linear Kramers-Kronig validity test.

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

Sign convention: capacitive Z'' is negative. Files that store -Z'' (most
positive values) are detected and converted.

References
    Boukamp, J. Electrochem. Soc. 142, 1885 (1995)                  linear KK test
    Schoenleber, Klotz, Ivers-Tiffee, Electrochim. Acta 131, 20 (2014)
    Hsu, Mansfeld, Corrosion 57, 747 (2001)                          C_eff of a CPE
    Guerrero, Bisquert, Garcia-Belmonte, Chem. Rev. 121, 14430 (2021)
    von Hauff, Klotz, J. Mater. Chem. C 10, 742 (2022)
    Ebadi et al., Nat. Commun. 10, 1574 (2019)                       negative capacitance
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
