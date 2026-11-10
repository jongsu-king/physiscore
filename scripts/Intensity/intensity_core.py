"""Light-intensity dependence of Voc, Jsc and FF.

    Voc  = (n_id kT / q) ln(I) + const     ->  ideality factor n_id
    Jsc  ~ I^alpha                         ->  alpha
    Suns-Voc pseudo J-V: J(Voc_i) = Jsc(I_max) - Jsc(I_i)  ->  pseudo fill factor

The ideality factor from Voc(I) is free of series resistance, unlike the one
from the dark J-V curve. n_id near 1 points to band-to-band (or surface)
recombination of free carriers, n_id near 2 to Shockley-Read-Hall
recombination through mid-gap states with both carrier densities rising
together; intermediate values in perovskite cells usually come from
interface recombination rather than from a mixture of the two (Caprioglio
2020). alpha below 1 indicates losses that grow with carrier density at
short circuit (bimolecular recombination, space charge; alpha = 0.75 is the
space-charge limit of Mihailetchi 2005). The pseudo J-V curve built from the
(Jsc, Voc) pairs carries no series-resistance loss, so pseudo-FF minus the
measured FF is the transport loss (Sinton and Cuevas 2000).

References
    Koster et al., Appl. Phys. Lett. 86, 123509 (2005)
    Mihailetchi et al., Phys. Rev. Lett. 94, 126602 (2005)
    Sinton, Cuevas, Proc. 16th EU PVSEC, 1152 (2000)        Suns-Voc
    Tress et al., Energy Environ. Sci. 11, 151 (2018)
    Caprioglio et al., Adv. Energy Mater. 10, 2000502 (2020)
    Green, Solid-State Electron. 24, 788 (1981)             FF0(voc)
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from scripts.common.curve_io import linfit, t_factor

KB_EV = 8.617333262e-5       # eV/K

COLUMN_SPEC = [
    ("intensity", [r"intens", r"irradi", r"\bsuns?\b", r"mw", r"power", r"light"], 0),
    ("voc", [r"voc", r"v_oc", r"open"], 1),
    ("jsc", [r"jsc", r"j_sc", r"isc", r"short"], 2),
    ("ff", [r"\bff\b", r"fill"], None),
    ("pce", [r"pce", r"eff", r"eta"], None),
]

_NAME_PATTERNS = [
    (re.compile(r"(\d+(?:[.p]\d+)?)\s*suns?", re.I), 100.0),          # 0.1sun, 0p5 suns
    (re.compile(r"(\d+(?:[.p]\d+)?)\s*mw", re.I), 1.0),               # 53mW
    (re.compile(r"(\d+(?:[.p]\d+)?)\s*(?:%|pct|percent)", re.I), 1.0),  # 10% of one sun
]
_OD_PATTERN = re.compile(r"(?:od|nd)[\s_-]?(\d+(?:[.p]\d+)?)", re.I)   # OD1.0 -> 10 %


def intensity_from_name(name: str) -> float:
    """Irradiance in mW/cm2 parsed from a file name (0.1sun, 53mW, 10pct,
    OD1.0 / ND2); NaN when the name carries none."""
    stem = os.path.splitext(os.path.basename(name))[0]
    for rx, scale in _NAME_PATTERNS:
        m = rx.search(stem)
        if m:
            return float(m.group(1).replace("p", ".")) * scale
    m = _OD_PATTERN.search(stem)
    if m:
        return 100.0 * 10.0 ** (-float(m.group(1).replace("p", ".")))
    return np.nan


def fit_voc(intensity, voc, temperature_k: float = 300.0, level: float = 0.95) -> Dict[str, float]:
    """n_id from the slope of Voc against ln(I)."""
    x, y = np.log(np.asarray(intensity, float)), np.asarray(voc, float)
    f = linfit(x, y)
    kt = KB_EV * temperature_k
    n = f["slope"] / kt
    se = f["slope_err"] / kt if np.isfinite(f["slope_err"]) else np.nan
    ci = t_factor(f["n"], level) * se if np.isfinite(se) else np.nan
    return {"n_id": float(n), "n_id_err": float(se), "n_id_ci": float(ci),
            "slope_mV_per_decade": float(1000.0 * f["slope"] * np.log(10.0)),
            "intercept_V": f["intercept"], "r2": f["r2"], "n": f["n"]}


def fit_jsc(intensity, jsc, level: float = 0.95) -> Dict[str, float]:
    """alpha from log Jsc against log I."""
    f = linfit(np.log10(np.asarray(intensity, float)), np.log10(np.abs(np.asarray(jsc, float))))
    ci = t_factor(f["n"], level) * f["slope_err"] if np.isfinite(f["slope_err"]) else np.nan
    return {"alpha": f["slope"], "alpha_err": f["slope_err"], "alpha_ci": float(ci),
            "log_prefactor": f["intercept"], "r2": f["r2"], "n": f["n"]}


def local_ideality(intensity, voc, temperature_k: float = 300.0) -> Tuple[np.ndarray, np.ndarray]:
    """Point-to-point n_id (centred differences) to show an intensity-dependent
    recombination mechanism."""
    x, y = np.log(np.asarray(intensity, float)), np.asarray(voc, float)
    if len(x) < 3:
        return np.array([]), np.array([])
    n = np.gradient(y, x) / (KB_EV * temperature_k)
    return np.exp(x), n


def ff0_green(voc_v: float, n_id: float, temperature_k: float = 300.0) -> float:
    """Fill factor of an ideal diode without resistances (Green 1981)."""
    vt = n_id * KB_EV * temperature_k
    if not np.isfinite(vt) or vt <= 0 or not np.isfinite(voc_v):
        return np.nan
    u = voc_v / vt
    if u <= 1:
        return np.nan
    return float((u - np.log(u + 0.72)) / (u + 1.0))


def pseudo_jv(intensity, voc, jsc) -> Dict[str, Any]:
    """Suns-Voc pseudo J-V curve referenced to the highest intensity."""
    I, v, j = (np.asarray(a, float) for a in (intensity, voc, jsc))
    order = np.argsort(I)
    I, v, j = I[order], v[order], np.abs(j[order])
    j_ref, v_ref = j[-1], v[-1]
    pj = j_ref - j                     # current delivered at V = Voc_i
    out = {"v": v, "j": pj, "pFF": np.nan, "p_vmpp": np.nan, "p_jmpp": np.nan, "covers_mpp": False}
    if len(v) < 4 or j_ref <= 0 or v_ref <= 0:
        return out
    # the curve runs from (Voc_min, ~Jsc) to (Voc_ref, 0); add the short-circuit point
    vv = np.r_[0.0, v]
    jj = np.r_[j_ref, pj]
    grid = np.linspace(0.0, v_ref, 400)
    p = grid * np.interp(grid, vv, jj)
    k = int(np.argmax(p))
    out.update({"pFF": float(p[k] / (j_ref * v_ref)), "p_vmpp": float(grid[k]), "p_jmpp": float(p[k] / grid[k]) if grid[k] > 0 else np.nan,
                "covers_mpp": bool(v.min() < grid[k])})
    return out


def analyse(intensity, voc, jsc=None, ff=None, pce=None, temperature_k: float = 300.0,
            i_min: Optional[float] = None, i_max: Optional[float] = None) -> Dict[str, Any]:
    """Intensity series -> n_id, alpha, pseudo-FF. Intensities in mW/cm2
    (or suns - only ratios matter), Voc in V, Jsc in mA/cm2, FF in % or
    fraction. Points outside [i_min, i_max] are shown but not fitted."""
    I = np.asarray(intensity, float)
    cols = {"voc": voc, "jsc": jsc, "ff": ff, "pce": pce}
    arr = {k: (np.asarray(v, float) if v is not None else np.full(len(I), np.nan)) for k, v in cols.items()}
    ok = np.isfinite(I) & (I > 0)
    order = np.argsort(I[ok])
    I = I[ok][order]
    arr = {k: v[ok][order] for k, v in arr.items()}
    if np.nanmax(arr["ff"]) <= 1.0 if np.isfinite(arr["ff"]).any() else False:
        arr["ff"] = arr["ff"] * 100.0
    sel = np.ones(len(I), bool)
    if i_min is not None:
        sel &= I >= i_min
    if i_max is not None:
        sel &= I <= i_max
    res: Dict[str, Any] = {"intensity": I, **arr, "fit_mask": sel, "temperature_K": float(temperature_k),
                           "decades": float(np.log10(I.max() / I.min())) if len(I) > 1 else 0.0,
                           "voc_fit": None, "jsc_fit": None, "jscvoc_fit": None, "pseudo": None, "n_local": (np.array([]), np.array([])),
                           "FF0": np.nan, "FF_at_max": np.nan, "transport_loss_FF": np.nan}
    mv = sel & np.isfinite(arr["voc"]) & (arr["voc"] > 0)
    if mv.sum() >= 3:
        res["voc_fit"] = fit_voc(I[mv], arr["voc"][mv], temperature_k)
        res["n_local"] = local_ideality(I[mv], arr["voc"][mv], temperature_k)
    mj = sel & np.isfinite(arr["jsc"]) & (np.abs(arr["jsc"]) > 0)
    if mj.sum() >= 3:
        res["jsc_fit"] = fit_jsc(I[mj], arr["jsc"][mj])
    mb = mv & mj
    if mb.sum() >= 3:
        # Jsc-Voc method: the photocurrent replaces the intensity axis, so a
        # filter calibration error or alpha != 1 does not enter
        res["jscvoc_fit"] = fit_voc(np.abs(arr["jsc"][mb]), arr["voc"][mb], temperature_k)
    both = np.isfinite(arr["voc"]) & np.isfinite(arr["jsc"]) & (arr["voc"] > 0)
    if both.sum() >= 4:
        res["pseudo"] = pseudo_jv(I[both], arr["voc"][both], arr["jsc"][both])
    if np.isfinite(arr["ff"]).any():
        k = int(np.where(np.isfinite(arr["ff"]))[0][-1])
        res["FF_at_max"] = float(arr["ff"][k])
        if res["voc_fit"] is not None and np.isfinite(arr["voc"][k]):
            res["FF0"] = 100.0 * ff0_green(arr["voc"][k], res["voc_fit"]["n_id"], temperature_k)
        if res["pseudo"] is not None and np.isfinite(res["pseudo"]["pFF"]):
            res["transport_loss_FF"] = 100.0 * res["pseudo"]["pFF"] - res["FF_at_max"]
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    n_pts = int(np.isfinite(r["voc"]).sum())
    if n_pts < 5:
        w.append(f"Only {n_pts} intensities: the slope has few degrees of freedom and a wide confidence interval.")
    if r["decades"] < 1.0:
        w.append(f"The intensities span {r['decades']:.2f} decades; at least one decade is needed for a reliable "
                 "ideality factor.")
    vf = r["voc_fit"]
    if vf is not None:
        if vf["r2"] < 0.99:
            w.append(f"Voc against ln(I) is not a straight line (R2 = {vf['r2']:.3f}): the recombination mechanism "
                     "changes with intensity, or the low-intensity points are shunt limited. See the local n_id.")
        if vf["n_id"] < 0.9:
            w.append(f"n_id = {vf['n_id']:.2f} is below 1, which bulk recombination cannot give: surface "
                     "recombination at a contact, or the cell heating up at high intensity.")
        jv = r.get("jscvoc_fit")
        if jv is not None and abs(jv["n_id"] - vf["n_id"]) > 0.1:
            w.append(f"n_id from Voc against ln(I) ({vf['n_id']:.2f}) and against ln(Jsc) ({jv['n_id']:.2f}) differ: "
                     "the photocurrent is not proportional to the stated intensity. The Jsc-based value does not "
                     "depend on the intensity calibration.")
        if vf["n_id"] > 2.2:
            w.append(f"n_id = {vf['n_id']:.2f} is above 2: a shunt at low intensity or a non-ohmic contact adds "
                     "its own intensity dependence.")
    jf = r["jsc_fit"]
    if jf is not None and jf["alpha"] > 1.03:
        w.append(f"alpha = {jf['alpha']:.3f} is above 1: check the intensity calibration (filter values) or the "
                 "linearity of the reference detector.")
    p = r["pseudo"]
    if p is not None and np.isfinite(p["pFF"]) and not p["covers_mpp"]:
        w.append("The lowest intensity does not reach below the pseudo maximum-power voltage: the pseudo fill "
                 "factor is interpolated to the short-circuit point and is an upper estimate.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    vf, jf, p = r["voc_fit"] or {}, r["jsc_fit"] or {}, r["pseudo"] or {}
    return [
        ("Intensities", len(r["intensity"]), ""), ("Range", r["decades"], "decades"),
        ("Ideality factor n_id", vf.get("n_id", np.nan), ""), ("n_id 95 % interval (+-)", vf.get("n_id_ci", np.nan), ""),
        ("Voc slope", vf.get("slope_mV_per_decade", np.nan), "mV/decade"), ("Voc fit R2", vf.get("r2", np.nan), ""),
        ("n_id from Voc against ln(Jsc)", (r.get("jscvoc_fit") or {}).get("n_id", np.nan), ""),
        ("Jsc exponent alpha", jf.get("alpha", np.nan), ""), ("alpha 95 % interval (+-)", jf.get("alpha_ci", np.nan), ""),
        ("Jsc fit R2", jf.get("r2", np.nan), ""),
        ("Pseudo fill factor", 100.0 * p.get("pFF", np.nan) if p else np.nan, "%"),
        ("FF at highest intensity", r["FF_at_max"], "%"), ("Transport loss (pFF - FF)", r["transport_loss_FF"], "% abs"),
        ("Ideal-diode FF0 (Green)", r["FF0"], "%"),
    ]


def from_jv_files(files: Sequence[str], area_cm2: float, intensities: Optional[Sequence[float]] = None,
                  sweep: str = "reverse") -> Dict[str, np.ndarray]:
    """Voc, Jsc, FF and PCE of J-V files measured at different intensities.
    The irradiance comes from `intensities` or from the file names."""
    from scripts.JV import jv_core
    from scripts.common.iv_io import GENERIC_EXTENSIONS, read_generic_iv
    rows = []
    for k, path in enumerate(files):
        pin = float(intensities[k]) if intensities is not None else intensity_from_name(path)
        if not np.isfinite(pin) or pin <= 0:
            continue
        if path.lower().endswith(GENERIC_EXTENSIONS):
            v, j, _ = read_generic_iv(path, area_cm2)
        else:
            v, j = jv_core.read_jv_curve(path, area_cm2=area_cm2)
        if sweep != "combined":
            seg = next((s for s in jv_core.split_scan_directions(v, j) if s["direction"] == sweep), None)
            if seg is not None:
                v, j = seg["v"], seg["j"]
        p = jv_core.compute_jv_parameters(v, j, pin_mw_cm2=pin)
        rows.append((pin, p.get("Voc", np.nan), p.get("Jsc", np.nan), p.get("FF", np.nan), p.get("PCE", np.nan), path))
    rows.sort(key=lambda r: r[0])
    if not rows:
        return {"intensity": np.array([]), "voc": np.array([]), "jsc": np.array([]), "ff": np.array([]),
                "pce": np.array([]), "files": []}
    a = np.array([r[:5] for r in rows], float)
    return {"intensity": a[:, 0], "voc": a[:, 1], "jsc": a[:, 2], "ff": a[:, 3], "pce": a[:, 4],
            "files": [r[5] for r in rows]}


def simulate(n_id=1.5, alpha=0.97, j0_ma=1e-10, jsc_1sun=24.0, rs_ohm_cm2=3.0, temperature_k=300.0,
             intensities=None) -> Dict[str, np.ndarray]:
    """One-diode cell at several intensities (for tests and validation)."""
    I = np.asarray(intensities if intensities is not None else [1, 2, 5, 10, 20, 50, 100], float)
    vt = n_id * KB_EV * temperature_k
    jsc = jsc_1sun * (I / 100.0) ** alpha
    voc = vt * np.log(jsc / j0_ma + 1.0)
    ff = []
    for js, vo in zip(jsc, voc):
        # parametric in the junction voltage, so the series resistance needs no iteration
        vd = np.linspace(0.0, vo, 1500)
        j = js - j0_ma * (np.exp(vd / vt) - 1.0)
        v = vd - j * 1e-3 * rs_ohm_cm2
        keep = v >= 0
        ff.append(100.0 * float((v[keep] * j[keep]).max()) / (js * vo))
    ff = np.array(ff)
    return {"intensity": I, "voc": voc, "jsc": jsc, "ff": ff, "pce": jsc * voc * ff / I}
