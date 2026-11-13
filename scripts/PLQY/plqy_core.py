"""Absolute photoluminescence quantum yield and the quasi-Fermi-level
splitting it implies (GUI-free).

Two kinds of input file:

* sphere  - spectra recorded in an integrating sphere (de Mello, Wittmann
  and Friend 1997): wavelength, A (empty sphere, laser only), B (sample in
  the sphere but out of the beam; optional) and C (sample in the beam).
  Integrals over the laser window L and over the emission window P give

      absorptance   A = 1 - L_C / L_B              (two measurements: 1 - L_C / L_A)
      PLQY          = [P_C - (1 - A) P_B] / (L_A A)   (two measurements: P_C / (L_A A))

  P is integrated after subtracting the empty-sphere spectrum, so stray
  light and a dark offset in the emission window cancel. Spectra in energy
  units (W/nm) are converted to photon numbers by the factor lambda.

* series  - a table of excitation intensity (suns, mW/cm2 or per cent of
  one sun) and PLQY, optionally with Voc, Jsc and FF of the device measured
  at the same intensities.

The quasi-Fermi-level splitting follows from detailed balance (Ross 1967):
the emitted photon flux is PLQY times the absorbed flux, and a body with
splitting QFLS emits (J0,rad / q) exp(QFLS / kT), so

      QFLS = kT ln(PLQY J_G / J0,rad) = q Voc,rad + kT ln(PLQY)
      dV_nr = -(kT / q) ln(PLQY)                     non-radiative loss

with the generation current J_G (q times the absorbed photon flux) and the
radiative saturation current J0,rad from the EQE or absorptance of the same
stack (scripts.EQE.eqe_core.radiative_limit), from a step absorptance at
the band gap (Shockley-Queisser; an upper estimate of the QFLS) or entered
by hand. Over an intensity series, QFLS against ln(suns) gives the implied
ideality factor and, as Suns-Voc does for Voc, an implied J-V curve without
transport losses: each intensity X is one point (QFLS(X)/q, J_G (1 - X)),
whose fill factor is the implied FF (Stolterfoht et al. 2018). A Voc
measured at the same intensity shows how much of the splitting the
contacts lose: QFLS/q - Voc (Caprioglio et al. 2019).

References
    de Mello, Wittmann, Friend, Adv. Mater. 9, 230 (1997)
    Ross, J. Chem. Phys. 46, 4590 (1967)
    Stolterfoht et al., Nat. Energy 3, 847 (2018)
    Stolterfoht et al., Energy Environ. Sci. 12, 2778 (2019)
    Caprioglio et al., Adv. Energy Mater. 9, 1901631 (2019)
    Kirchartz, Marquez, Stolterfoht, Unold, Adv. Energy Mater. 10, 1904134 (2020)
    Rau, Phys. Rev. B 76, 085303 (2007)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from scripts.EQE import eqe_core
from scripts.Intensity import intensity_core

K_B = eqe_core.K_B
Q_E = eqe_core.Q_E
HC_EV_NM = eqe_core.HC_EV_NM
KB_EV = K_B / Q_E                      # eV/K

INPUTS = ("auto", "series", "sphere")
INTENSITY_UNITS = ("suns", "mW/cm2", "percent")
RADIATIVE = ("eqe", "bandgap", "j0", "none")
SPECTRUM_UNITS = ("photons", "energy")

SERIES_SPEC = [
    ("intensity", [r"intens", r"\bsuns?\b", r"irradi", r"excit", r"power", r"fluen", r"light"], 0),
    ("plqy", [r"plqy", r"quantum", r"yield", r"\bqy\b", r"\beta_?pl\b"], 1),
    ("voc", [r"voc", r"v_oc", r"open"], None),
    ("jsc", [r"jsc", r"j_sc", r"short"], None),
    ("ff", [r"\bff\b", r"fill"], None),
]
_WL = [r"wave", r"lambda", r"\bnm\b", r"\bwl\b"]
_SPHERE_NAMES = {
    "a": [r"empty", r"blank", r"no.?sample", r"without", r"\bref", r"^a\b", r"\(a\)", r"[_ ]a$"],
    "b": [r"out.?of.?beam", r"out.?beam", r"indirect", r"off.?beam", r"^b\b", r"\(b\)", r"[_ ]b$"],
    "c": [r"in.?beam", r"\bdirect", r"on.?beam", r"^c\b", r"\(c\)", r"[_ ]c$"],
}
EQE_SPEC = [("wl", _WL, 0), ("eqe", [r"eqe", r"ipce", r"\bqe\b", r"quantum", r"absorpt", r"respons"], 1)]

LASER_FRACTION = 0.01                  # laser window: where the empty-sphere line is above 1 % of its peak
EMISSION_FRACTION = 0.01               # emission window: where C - A is above 1 % of the PL peak
EMISSION_PAD = 0.15                    # the emission window is widened by 15 % of its width on each side


# --------------------------------------------------------------------------- reading
def read_table(df, kind: str = "auto") -> Dict[str, Any]:
    """Columns of one table -> {'_kind': 'series' | 'sphere', arrays, '_columns', '_how'}."""
    from scripts.common import curve_io
    if kind not in INPUTS:
        raise ValueError(f"input must be one of {', '.join(INPUTS)}")
    named_plqy = curve_io.find_column(df, SERIES_SPEC[1][1]) is not None
    if kind == "series" or (kind == "auto" and named_plqy):
        data, names = curve_io.pick_columns(df, SERIES_SPEC)
        if "intensity" not in data or "plqy" not in data:
            raise ValueError("a PLQY series needs an intensity column and a PLQY column")
        pct = "%" in names.get("plqy", "") or "percent" in names.get("plqy", "").lower()
        data.update({"_kind": "series", "_columns": names, "_plqy_percent": pct})
        return data
    return _read_sphere(df, curve_io)


def _read_sphere(df, curve_io) -> Dict[str, Any]:
    cols = list(df.columns)
    if len(cols) < 3:
        raise ValueError("integrating-sphere spectra need a wavelength column and at least two spectra "
                         "(A: empty sphere, C: sample in the beam; B: sample out of the beam is optional)")
    used: List[str] = []
    names: Dict[str, str] = {}
    wl = curve_io.find_column(df, _WL)
    wl = wl if wl is not None else cols[0]
    used.append(wl)
    names["wl"] = wl
    for key in ("a", "b", "c"):
        c = curve_io.find_column(df, _SPHERE_NAMES[key], exclude=used)
        if c is not None:
            used.append(c)
            names[key] = c
    free = [c for c in cols if c not in used]
    order = [k for k in ("a", "b", "c") if k not in names]
    if len(free) == 2 and order == ["a", "b", "c"]:
        order = ["a", "c"]                     # three columns without names: wavelength, A, C
    for key, c in zip(order, free):
        if key == "b" and "c" not in names and len(free) < 3:
            continue
        names[key] = f"{c} (by position)"
        used.append(c)
    if "a" not in names or "c" not in names:
        raise ValueError("could not tell the empty-sphere (A) and in-beam (C) spectra apart; name the columns "
                         "'empty', 'out of beam', 'in beam' or give them in the order wavelength, A, B, C")
    raw = {k: df[v.replace(" (by position)", "")].to_numpy(float) for k, v in names.items()}
    ok = np.isfinite(raw["wl"]) & np.isfinite(raw["a"]) & np.isfinite(raw["c"])
    if "b" in raw:
        ok &= np.isfinite(raw["b"])
    order_idx = np.argsort(raw["wl"][ok])
    data = {k: v[ok][order_idx] for k, v in raw.items()}
    if np.nanmax(data["wl"]) < 5.0:            # micrometres
        data["wl"] = data["wl"] * 1000.0
    data.update({"_kind": "sphere", "_columns": names})
    return data


def read_eqe(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """Wavelength (nm) and EQE (fraction) of the reference file for J0,rad."""
    from scripts.common import curve_io
    if not path:
        raise ValueError("J0,rad from the EQE needs an EQE (or absorptance) file of the same stack")
    df = curve_io.read_numeric_table(path)
    data, _ = curve_io.pick_columns(df, EQE_SPEC)
    wl, q = curve_io.finite_rows(data["wl"], data["eqe"])
    if wl.max() < 5.0:
        wl = wl * 1000.0
    order = np.argsort(wl)
    return wl[order], eqe_core.eqe_to_fraction(q[order])


# --------------------------------------------------------------------------- sphere
def _integral(x, y, lo: float, hi: float) -> float:
    m = (x >= lo) & (x <= hi)
    if int(m.sum()) < 2:
        return float("nan")
    return float(np.trapezoid(y[m], x[m]))


def _smooth(y, n: int = 5) -> np.ndarray:
    if len(y) < n:
        return np.asarray(y, float)
    k = np.ones(n) / n
    return np.convolve(np.pad(y, n // 2, mode="edge"), k, mode="valid")


def laser_window(wl, a, lo: Optional[float] = None, hi: Optional[float] = None) -> Tuple[float, float]:
    """Window around the excitation line of the empty sphere: where the line
    stays above 1 % of its height (above the median floor), two points wider."""
    if lo is not None and hi is not None:
        return float(min(lo, hi)), float(max(lo, hi))
    a = np.asarray(a, float)
    floor = float(np.median(a))
    k = int(np.argmax(a))
    thr = floor + LASER_FRACTION * (a[k] - floor)
    i0 = k
    while i0 > 0 and a[i0 - 1] > thr:
        i0 -= 1
    i1 = k
    while i1 < len(a) - 1 and a[i1 + 1] > thr:
        i1 += 1
    i0, i1 = max(i0 - 2, 0), min(i1 + 2, len(a) - 1)
    return float(wl[i0]), float(wl[i1])


def emission_window(wl, a, c, laser: Tuple[float, float], lo: Optional[float] = None,
                    hi: Optional[float] = None) -> Dict[str, Any]:
    """Window of the emission in C - A outside the laser window: the band
    above 1 % of its peak, widened by 15 % of its width on each side (not
    into the laser window). `truncated` names a side where the band still
    carries more than 5 % of its peak at the end of the recorded range."""
    wl = np.asarray(wl, float)
    s = _smooth(np.asarray(c, float) - np.asarray(a, float))
    outside = (wl < laser[0]) | (wl > laser[1])
    out = {"lo": float("nan"), "hi": float("nan"), "peak_nm": float("nan"), "truncated": "", "auto": lo is None}
    if not outside.any():
        return out
    cand = np.where(outside, s, -np.inf)
    k = int(np.argmax(cand))
    peak = float(s[k])
    out["peak_nm"] = float(wl[k])
    if lo is not None and hi is not None:
        out.update(lo=float(min(lo, hi)), hi=float(max(lo, hi)))
    else:
        if peak <= 0:
            return out
        i0 = k
        while i0 > 0 and outside[i0 - 1] and s[i0 - 1] > EMISSION_FRACTION * peak:
            i0 -= 1
        i1 = k
        while i1 < len(s) - 1 and outside[i1 + 1] and s[i1 + 1] > EMISSION_FRACTION * peak:
            i1 += 1
        width = wl[i1] - wl[i0]
        e_lo, e_hi = wl[i0] - EMISSION_PAD * width, wl[i1] + EMISSION_PAD * width
        if wl[k] > laser[1]:
            e_lo = max(e_lo, laser[1])
        else:
            e_hi = min(e_hi, laser[0])
        out.update(lo=float(max(e_lo, wl[0])), hi=float(min(e_hi, wl[-1])))
    m = (wl >= out["lo"]) & (wl <= out["hi"])
    if m.sum() >= 3 and peak > 0:
        edge, idx, sides = 0.05 * peak, np.where(m)[0], []
        if idx[0] == 0 and s[idx[0]] > edge:
            sides.append("short")
        if idx[-1] == len(wl) - 1 and s[idx[-1]] > edge:
            sides.append("long")
        out["truncated"] = " and ".join(sides)
    return out


def de_mello(wl, a, b, c, laser: Tuple[float, float], emission: Tuple[float, float],
             units: str = "photons") -> Dict[str, float]:
    """Laser and emission integrals, absorptance and PLQY of one sample."""
    wl = np.asarray(wl, float)
    w = wl if units == "energy" else np.ones_like(wl)
    a, c = np.asarray(a, float) * w, np.asarray(c, float) * w
    b = None if b is None else np.asarray(b, float) * w
    la, lc = _integral(wl, a, *laser), _integral(wl, c, *laser)
    pa = _integral(wl, a, *emission)
    pc = _integral(wl, c, *emission) - pa
    out = {"L_A": la, "L_C": lc, "P_C": pc, "L_B": float("nan"), "P_B": float("nan"), "method": "two"}
    if b is not None:
        lb = _integral(wl, b, *laser)
        pb = _integral(wl, b, *emission) - pa
        absorb = 1.0 - lc / lb if lb > 0 else float("nan")
        plqy = (pc - (1.0 - absorb) * pb) / (la * absorb) if la > 0 and absorb > 0 else float("nan")
        out.update(L_B=lb, P_B=pb, method="three")
    else:
        absorb = 1.0 - lc / la if la > 0 else float("nan")
        plqy = pc / (la * absorb) if la > 0 and absorb > 0 else float("nan")
    out.update(absorptance=float(absorb), plqy=float(plqy))
    return out


def generation_current(power_mw_cm2: float, laser_nm: float, absorptance: float) -> float:
    """q times the absorbed photon flux of a laser of the given power density (mA/cm2)."""
    if not (power_mw_cm2 > 0 and laser_nm > 0 and absorptance > 0):
        return float("nan")
    photons = power_mw_cm2 * 1e-3 * laser_nm * 1e-9 / (eqe_core.H_PLANCK * eqe_core.C_LIGHT)   # cm-2 s-1
    return float(1e3 * Q_E * photons * absorptance)


# --------------------------------------------------------------------------- radiative reference
def radiative_reference(kind: str = "none", eqe_file: str = "", eg_ev: float = 0.0, j0_rad: float = 0.0,
                        jsc_1sun: float = 0.0, temperature_k: float = 300.0,
                        eqe: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> Dict[str, Any]:
    """J0,rad and the one-sun generation current J_G,1sun (both mA/cm2).

    eqe      J0,rad from the EQE or absorptance of the same stack (tail
             extrapolated, eqe_core.radiative_limit); J_G,1sun = its AM1.5G
             integral unless `jsc_1sun` is entered
    bandgap  step absorptance at Eg (J0,SQ, Jsc,SQ): the QFLS is an upper
             estimate unless the absorption edge is abrupt
    j0       J0,rad as entered; J_G,1sun must be entered
    none     no QFLS
    """
    if kind not in RADIATIVE:
        raise ValueError(f"radiative reference must be one of {', '.join(RADIATIVE)}")
    out = {"kind": kind, "J0_rad": float("nan"), "J_G_1sun": float("nan"), "Eg_eV": float("nan"),
           "Voc_rad_1sun": float("nan"), "source": "no radiative reference: QFLS not computed"}
    if kind == "eqe":
        wl, q = eqe if eqe is not None else read_eqe(eqe_file)
        e = HC_EV_NM / wl
        rad = eqe_core.radiative_limit(e, q, temperature_k)
        rau = eqe_core.bandgap_rau(e, q)
        out.update(J0_rad=rad["J0_rad_mA_cm2"], J_G_1sun=rad["Jsc_mA_cm2"], Eg_eV=rau["Eg"],
                   tail_extended=bool(rad["tail_extended"]),
                   source="J0,rad from the EQE" + (" (Urbach tail extrapolated)" if rad["tail_extended"] else ""))
    elif kind == "bandgap":
        if not eg_ev > 0.3:
            raise ValueError("J0,rad from the band gap needs the band gap (eV)")
        sq = eqe_core.shockley_queisser(float(eg_ev), temperature_k)
        out.update(J0_rad=sq["J0_SQ"], J_G_1sun=sq["Jsc_SQ"], Eg_eV=float(eg_ev),
                   source=f"J0,rad of a step absorptance at {eg_ev:.3f} eV (upper estimate of the QFLS)")
    elif kind == "j0":
        if not j0_rad > 0:
            raise ValueError("enter J0,rad (mA/cm2)")
        out.update(J0_rad=float(j0_rad), source="J0,rad as entered")
    if jsc_1sun and jsc_1sun > 0:
        out["J_G_1sun"] = float(jsc_1sun)
        out["source"] += f"; one-sun generation current {jsc_1sun:g} mA/cm2 as entered"
    if np.isfinite(out["J0_rad"]) and np.isfinite(out["J_G_1sun"]) and out["J0_rad"] > 0:
        out["Voc_rad_1sun"] = float(KB_EV * temperature_k * math.log(out["J_G_1sun"] / out["J0_rad"] + 1.0))
    return out


def qfls_ev(plqy, j_g, j0_rad: float, temperature_k: float = 300.0) -> np.ndarray:
    """QFLS = kT ln(PLQY J_G / J0,rad) in eV."""
    plqy, j_g = np.asarray(plqy, float), np.asarray(j_g, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = plqy * j_g / j0_rad
        return np.where((x > 0) & np.isfinite(x), KB_EV * temperature_k * np.log(np.where(x > 0, x, 1.0)), np.nan)


def nonradiative_loss_v(plqy, temperature_k: float = 300.0) -> np.ndarray:
    plqy = np.asarray(plqy, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(plqy > 0, -KB_EV * temperature_k * np.log(np.where(plqy > 0, plqy, 1.0)), np.nan)


# --------------------------------------------------------------------------- analysis
def _to_suns(i, unit: str) -> np.ndarray:
    if unit not in INTENSITY_UNITS:
        raise ValueError(f"intensity unit must be one of {', '.join(INTENSITY_UNITS)}")
    i = np.asarray(i, float)
    return i if unit == "suns" else i / 100.0


def _log_interp(x0: float, x, y, log_y: bool = False) -> float:
    """y at x0 by interpolation in ln x (and ln y); NaN outside the range."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & ((y > 0) if log_y else True)
    if ok.sum() == 0:
        return float("nan")
    x, y = x[ok], y[ok]
    if ok.sum() == 1:
        return float(y[0]) if abs(math.log(x[0] / x0)) < 1e-9 else float("nan")
    if not (x.min() * (1 - 1e-9) <= x0 <= x.max() * (1 + 1e-9)):
        return float("nan")
    o = np.argsort(x)
    yy = np.log(y[o]) if log_y else y[o]
    v = float(np.interp(math.log(x0), np.log(x[o]), yy))
    return math.exp(v) if log_y else v


def _base(kind: str, ref: Dict[str, Any], temperature_k: float) -> Dict[str, Any]:
    nan = float("nan")
    return {"kind": kind, "reference": ref, "temperature_K": float(temperature_k),
            "J0_rad": ref["J0_rad"], "J_G_1sun": ref["J_G_1sun"], "Voc_rad_1sun": ref["Voc_rad_1sun"],
            "Eg_eV": ref["Eg_eV"], "PLQY_ref": nan, "suns_ref": nan, "QFLS_ref": nan, "dV_nr_ref": nan,
            "dV_int_ref": nan, "Voc_ref": nan, "QFLS_1sun": nan, "PLQY_1sun": nan, "dV_int_1sun": nan,
            "qfls_fit": None, "voc_fit": None, "plqy_exponent": nan, "implied": None, "iFF": nan, "iVoc": nan,
            "iPCE": nan, "FF_ref": nan, "transport_loss_FF": nan, "decades": 0.0, "sphere": None,
            "extrapolated_1sun": False}


def analyse_series(intensity, plqy, voc=None, jsc=None, ff=None, intensity_unit: str = "suns",
                   reference: Optional[Dict[str, Any]] = None, temperature_k: float = 300.0,
                   i_min: Optional[float] = None, i_max: Optional[float] = None,
                   plqy_percent: Optional[bool] = None) -> Dict[str, Any]:
    """PLQY (and Voc) against excitation intensity -> QFLS, losses, implied
    ideality, implied J-V. Intensities in suns (1 sun = the absorbed photon
    flux of AM1.5G), mW/cm2 or per cent of one sun."""
    ref = reference or radiative_reference("none")
    suns = _to_suns(intensity, intensity_unit)
    y = np.asarray(plqy, float)
    n = len(suns)
    cols = {k: (np.asarray(v, float) if v is not None else np.full(n, np.nan)) for k, v in
            (("voc", voc), ("jsc", jsc), ("ff", ff))}
    ok = np.isfinite(suns) & (suns > 0) & np.isfinite(y)
    if ok.sum() == 0:
        raise ValueError("no row has both a positive intensity and a PLQY")
    order = np.argsort(suns[ok])
    suns, y = suns[ok][order], y[ok][order]
    cols = {k: v[ok][order] for k, v in cols.items()}
    percent = bool(plqy_percent) or float(np.nanmax(y)) > 1.0
    if percent:
        y = y / 100.0
    if np.isfinite(cols["ff"]).any() and np.nanmax(cols["ff"]) <= 1.0:
        cols["ff"] = cols["ff"] * 100.0
    res = _base("series", ref, temperature_k)
    jg = suns * ref["J_G_1sun"]
    q = qfls_ev(y, jg, ref["J0_rad"], temperature_k) if np.isfinite(ref["J0_rad"]) else np.full(len(y), np.nan)
    sel = np.ones(len(suns), bool)
    if i_min is not None:
        sel &= suns >= _to_suns(i_min, intensity_unit)
    if i_max is not None:
        sel &= suns <= _to_suns(i_max, intensity_unit)
    res.update({"suns": suns, "plqy": y, "plqy_percent_input": percent, "qfls": q, "j_g": jg,
                "dv_nr": nonradiative_loss_v(y, temperature_k), "voc": cols["voc"], "jsc": cols["jsc"],
                "ff": cols["ff"], "dv_int": q - cols["voc"], "fit_mask": sel,
                "decades": float(np.log10(suns.max() / suns.min())) if len(suns) > 1 else 0.0,
                "intensity_unit": intensity_unit})
    # reference point: one sun when the series covers it, else the intensity closest to it
    k = int(np.argmin(np.abs(np.log(suns))))
    res.update(suns_ref=float(suns[k]), PLQY_ref=float(y[k]), QFLS_ref=float(q[k]),
               dV_nr_ref=float(res["dv_nr"][k]), Voc_ref=float(cols["voc"][k]), dV_int_ref=float(q[k] - cols["voc"][k]),
               FF_ref=float(cols["ff"][k]))
    res["PLQY_1sun"] = _log_interp(1.0, suns, y, log_y=True)
    res["QFLS_1sun"] = _log_interp(1.0, suns, q)
    res["dV_int_1sun"] = _log_interp(1.0, suns, q - cols["voc"])
    good = sel & (y > 0)
    if good.sum() >= 3:
        from scripts.common.curve_io import linfit
        res["plqy_exponent"] = float(linfit(np.log(suns[good]), np.log(y[good]))["slope"])   # d ln PLQY / d ln I
        if np.isfinite(q[good]).sum() >= 3:
            m = good & np.isfinite(q)
            res["qfls_fit"] = intensity_core.fit_voc(suns[m], q[m], temperature_k)
            if not np.isfinite(res["QFLS_1sun"]):
                lo, hi = suns[m].min(), suns[m].max()
                if lo / 3.0 <= 1.0 <= hi * 3.0:
                    qf = res["qfls_fit"]
                    res["QFLS_1sun"] = float(qf["intercept_V"])     # QFLS = intercept + n kT ln(suns)
                    res["extrapolated_1sun"] = True
        mv = sel & np.isfinite(cols["voc"]) & (cols["voc"] > 0)
        if mv.sum() >= 3:
            res["voc_fit"] = intensity_core.fit_voc(suns[mv], cols["voc"][mv], temperature_k)
    # implied J-V: points up to (just above) one sun, referenced to the highest of them
    up = np.isfinite(q) & (suns <= 1.05)
    if up.sum() >= 4 and np.isfinite(ref["J_G_1sun"]):
        x, v = suns[up], q[up]
        p = intensity_core.pseudo_jv(x, v, x * ref["J_G_1sun"])
        res["implied"] = p
        top = float(x.max())
        res["implied_ref_suns"] = top
        if np.isfinite(p["pFF"]):
            res["iFF"] = float(100.0 * p["pFF"])
            res["iVoc"] = float(v[np.argmax(x)])
            res["iPCE"] = float(ref["J_G_1sun"] * res["iVoc"] * p["pFF"])     # mA/cm2 * V = mW/cm2 of 100
            kk = int(np.argmax(x))
            ff_top = cols["ff"][up][kk]
            if np.isfinite(ff_top):
                res["transport_loss_FF"] = float(res["iFF"] - ff_top)
    res["warnings"] = checks(res)
    return res


def analyse_sphere(wl, a, c, b=None, units: str = "photons", laser_lo: Optional[float] = None,
                   laser_hi: Optional[float] = None, em_lo: Optional[float] = None, em_hi: Optional[float] = None,
                   power_mw_cm2: float = 0.0, excitation_suns: float = 1.0, voc_v: Optional[float] = None,
                   reference: Optional[Dict[str, Any]] = None, temperature_k: float = 300.0) -> Dict[str, Any]:
    """de Mello PLQY of one sample, its absorptance at the laser, and the QFLS
    at the excitation (laser power entered, or stated in equivalent suns)."""
    if units not in SPECTRUM_UNITS:
        raise ValueError(f"spectrum units must be one of {', '.join(SPECTRUM_UNITS)}")
    ref = reference or radiative_reference("none")
    wl = np.asarray(wl, float)
    a, c = np.asarray(a, float), np.asarray(c, float)
    b = None if b is None else np.asarray(b, float)
    if len(wl) < 10:
        raise ValueError("the spectra have fewer than 10 points")
    laser = laser_window(wl, a, laser_lo, laser_hi)
    em = emission_window(wl, a, c, laser, em_lo, em_hi)
    if not np.isfinite(em["lo"]):
        raise ValueError("no emission was found outside the laser window (C is not above A anywhere)")
    dm = de_mello(wl, a, b, c, laser, (em["lo"], em["hi"]), units)
    laser_nm = float(wl[int(np.argmax(a))])
    # sensitivity of the result to the windows: laser window 1 nm wider, emission window 10 % wider
    wider_laser = (laser[0] - 1.0, laser[1] + 1.0)
    pad = 0.1 * (em["hi"] - em["lo"])
    lo, hi = max(em["lo"] - pad, float(wl[0])), min(em["hi"] + pad, float(wl[-1]))
    if em["peak_nm"] > laser[1]:
        lo = max(lo, wider_laser[1])
    else:
        hi = min(hi, wider_laser[0])
    alt = de_mello(wl, a, b, c, wider_laser, (lo, hi), units)
    res = _base("sphere", ref, temperature_k)
    if power_mw_cm2 and power_mw_cm2 > 0:
        jg = generation_current(power_mw_cm2, laser_nm, dm["absorptance"])
        suns = jg / ref["J_G_1sun"] if np.isfinite(ref["J_G_1sun"]) and ref["J_G_1sun"] > 0 else float("nan")
        how = f"{power_mw_cm2:g} mW/cm2 at {laser_nm:.0f} nm"
    else:
        suns = float(excitation_suns) if excitation_suns and excitation_suns > 0 else 1.0
        jg = suns * ref["J_G_1sun"]
        how = f"{suns:g} sun equivalent (as stated; no laser power entered)"
    plqy = dm["plqy"]
    q = float(qfls_ev(plqy, jg, ref["J0_rad"], temperature_k)) if np.isfinite(ref["J0_rad"]) else float("nan")
    voc = float(voc_v) if voc_v is not None and np.isfinite(voc_v) and voc_v > 0 else float("nan")
    res.update({"suns": np.array([suns]), "plqy": np.array([plqy]), "qfls": np.array([q]), "j_g": np.array([jg]),
                "dv_nr": nonradiative_loss_v([plqy], temperature_k), "voc": np.array([voc]),
                "dv_int": np.array([q - voc]), "fit_mask": np.array([True]), "units": units,
                "sphere": {**dm, "laser": laser, "emission": (em["lo"], em["hi"]), "emission_peak_nm": em["peak_nm"],
                           "truncated": em["truncated"], "laser_nm": laser_nm, "excitation": how,
                           "power_mw_cm2": float(power_mw_cm2 or 0.0),
                           "auto_windows": laser_lo is None and em_lo is None,
                           "plqy_window_change": (alt["plqy"] / plqy - 1.0) if plqy and np.isfinite(alt["plqy"]) else float("nan"),
                           "floor_fraction": float(np.median(a) / a.max()) if a.max() > 0 else float("nan"),
                           "wl": wl, "a": a, "b": b, "c": c}})
    res.update(suns_ref=float(suns), PLQY_ref=float(plqy), QFLS_ref=q, dV_nr_ref=float(res["dv_nr"][0]),
               Voc_ref=voc, dV_int_ref=float(q - voc))
    if np.isfinite(suns) and abs(math.log(suns)) < 1e-6:
        res.update(PLQY_1sun=float(plqy), QFLS_1sun=q, dV_int_1sun=float(q - voc))
    res["warnings"] = checks(res)
    return res


def read_curve(path: str, input: str = "auto") -> Dict[str, Any]:
    """One file -> `read_table` of its numeric block; `input` forces the kind."""
    import os
    from scripts.common import curve_io
    data = read_table(curve_io.read_numeric_table(path), input)
    names = data["_columns"]
    if data["_kind"] == "sphere":
        parts = [f"{k.upper()} = {names[k]}" for k in ("a", "b", "c") if k in names]
        data["_how"] = f"integrating-sphere spectra, wavelength = {names['wl']}; " + ", ".join(parts)
    else:
        data["_how"] = "PLQY series, " + ", ".join(f"{k} = {v}" for k, v in names.items())
    data["_file"] = os.path.basename(path)
    return data


def analyse(data: Dict[str, Any], input: str = "auto", intensity_unit: str = "suns", radiative: str = "none",
            eqe_file: str = "", eg_ev: float = 0.0, j0_rad: float = 0.0, jsc_1sun: float = 0.0,
            temperature_k: float = 300.0, i_min: Optional[float] = None, i_max: Optional[float] = None,
            units: str = "photons", laser_lo: Optional[float] = None, laser_hi: Optional[float] = None,
            em_lo: Optional[float] = None, em_hi: Optional[float] = None, power_mw_cm2: float = 0.0,
            excitation_suns: float = 1.0, voc_v: Optional[float] = None,
            reference: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One file read by `read_curve` -> the result of its kind. `input` is
    used when reading; the radiative reference is built from `radiative` and
    its inputs unless `reference` is given."""
    t = float(temperature_k)
    ref = reference or radiative_reference(radiative, eqe_file, float(eg_ev or 0.0), float(j0_rad or 0.0),
                                           float(jsc_1sun or 0.0), t)
    if data["_kind"] == "series":
        return analyse_series(data["intensity"], data["plqy"], data.get("voc"), data.get("jsc"), data.get("ff"),
                              intensity_unit=intensity_unit, reference=ref, temperature_k=t, i_min=i_min,
                              i_max=i_max, plqy_percent=data.get("_plqy_percent"))
    return analyse_sphere(data["wl"], data["a"], data["c"], data.get("b"), units=units, laser_lo=laser_lo,
                          laser_hi=laser_hi, em_lo=em_lo, em_hi=em_hi, power_mw_cm2=float(power_mw_cm2 or 0.0),
                          excitation_suns=float(excitation_suns or 1.0), voc_v=voc_v, reference=ref,
                          temperature_k=t)


# --------------------------------------------------------------------------- checks and rows
def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    y = np.asarray(r["plqy"], float)
    if (y <= 0).any():
        w.append("A PLQY at or below zero: the emission integral is not above the empty-sphere spectrum, or the "
                 "windows are wrong. No QFLS can be given for it.")
    if (y > 1.0).any():
        w.append(f"A PLQY above 100 % ({100 * float(np.nanmax(y)):.1f} %) is not physical: check the spectral "
                 "calibration of the sphere and spectrometer and the windows.")
    ref = r["reference"]
    if ref["kind"] == "none":
        w.append("No radiative reference (EQE file, band gap or J0,rad) was given, so only the PLQY and the "
                 "non-radiative loss -kT ln(PLQY) are reported, not the QFLS.")
    elif ref["kind"] == "bandgap":
        w.append("J0,rad was taken from a step absorptance at the band gap. A real absorption edge has a tail "
                 "that raises J0,rad, so the QFLS is an upper estimate; give the EQE or absorptance of the stack.")
    if ref["kind"] in ("j0", "bandgap", "eqe") and not np.isfinite(ref["J_G_1sun"]):
        w.append("The one-sun generation current is not known (enter Jsc): the QFLS cannot be placed on the "
                 "intensity scale.")
    s = r.get("sphere")
    if s is not None:
        ab = s["absorptance"]
        if np.isfinite(ab) and ab < 0.1:
            w.append(f"The sample absorbs {100 * ab:.1f} % of the laser: the PLQY is divided by the absorptance, "
                     "so its error grows as 1/A. Use a wavelength the film absorbs strongly.")
        if not np.isfinite(ab) or ab <= 0:
            w.append("The laser peak in C is not below the one in B (or A): no absorptance. Check the column order "
                     "and the stability of the laser.")
        if np.isfinite(s["L_B"]) and s["L_B"] > 1.02 * s["L_A"]:
            w.append(f"The laser peak with the sample out of the beam (B) is {100 * (s['L_B'] / s['L_A'] - 1):.1f} % "
                     "above the empty sphere (A): the laser power drifted between the measurements or the columns "
                     "are swapped.")
        if np.isfinite(s["P_B"]) and np.isfinite(s["P_C"]) and s["P_B"] > s["P_C"]:
            w.append("More emission out of the beam (B) than in the beam (C): the B and C columns may be swapped.")
        if s["truncated"]:
            w.append(f"The emission band is cut at the {s['truncated']}-wavelength end of the recorded range: the "
                     "emission integral and the PLQY are too low. Record a wider range.")
        ch = s["plqy_window_change"]
        if np.isfinite(ch) and abs(ch) > 0.05:
            w.append(f"Widening the windows (laser +1 nm per side, emission +10 %) changes the PLQY by "
                     f"{100 * ch:+.1f} %: the windows do not hold the whole line and band, or the background is "
                     "not flat. Set them by hand.")
        if np.isfinite(s["floor_fraction"]) and s["floor_fraction"] > 0.01:
            w.append(f"The empty-sphere spectrum has a floor of {100 * s['floor_fraction']:.1f} % of the laser peak: "
                     "the spectra may not be dark-corrected, which enters the laser integrals.")
        if "sun equivalent (as stated" in s["excitation"] and ref["kind"] != "none":
            w.append("No laser power density was entered: the excitation was taken as the stated sun equivalent. "
                     "The QFLS changes by kT ln(10) = 60 mV per decade of intensity.")
    if r["kind"] == "series":
        n_pts = len(r["suns"])
        if n_pts >= 3 and r["decades"] < 1.0:
            w.append(f"The intensities span {r['decades']:.2f} decades; the implied ideality factor needs at least "
                     "one decade.")
        qf = r.get("qfls_fit")
        if qf is not None and qf["r2"] < 0.99:
            w.append(f"QFLS against ln(intensity) is not a straight line (R2 = {qf['r2']:.3f}): the recombination "
                     "changes with intensity (look at the PLQY view).")
        if qf is not None and not 0.9 <= qf["n_id"] <= 2.2:
            w.append(f"The implied ideality factor {qf['n_id']:.2f} is outside 0.9-2.2: check the intensity "
                     "calibration (filters) and the linearity of the detector.")
        if r["extrapolated_1sun"]:
            w.append("The series does not reach one sun: the one-sun QFLS was extrapolated along the ideality fit.")
        imp = r.get("implied")
        if imp is not None:
            if not imp["covers_mpp"]:
                w.append("The lowest intensity does not reach below the implied maximum-power voltage: the implied "
                         "fill factor is interpolated to the short-circuit point and is an upper estimate.")
            top = r.get("implied_ref_suns", 1.0)
            if top < 0.8:
                w.append(f"The implied J-V curve is referenced to {top:.2g} sun, the highest intensity at or below "
                         "one sun, so the implied Voc, FF and efficiency belong to that intensity.")
        elif n_pts >= 3 and np.isfinite(r["J0_rad"]):
            w.append("Fewer than four intensities at or below one sun: no implied J-V curve.")
    dv = np.asarray(r["dv_int"], float)
    if np.isfinite(dv).any() and float(np.nanmin(dv)) < -0.01:
        w.append(f"The measured Voc is above the QFLS by {-1000 * float(np.nanmin(dv)):.0f} mV, which detailed "
                 "balance does not allow: the PLQY is too low (calibration, windows) or J0,rad too high, or the Voc "
                 "was measured at another intensity or on another sample.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    ref = r["reference"]
    rows: List[Tuple[str, Any, str]] = [("Input", "integrating sphere" if r["kind"] == "sphere" else "intensity series", "")]
    s = r.get("sphere")
    if s is not None:
        rows += [("Method", "de Mello, A B C" if s["method"] == "three" else "two spectra, A C", ""),
                 ("Laser line", s["laser_nm"], "nm"), ("Laser window", f"{s['laser'][0]:.1f}-{s['laser'][1]:.1f}", "nm"),
                 ("Emission window", f"{s['emission'][0]:.1f}-{s['emission'][1]:.1f}", "nm"),
                 ("Emission peak", s["emission_peak_nm"], "nm"),
                 ("Absorptance at the laser", 100.0 * s["absorptance"], "%"),
                 ("Laser power", s["power_mw_cm2"] if s["power_mw_cm2"] > 0 else "not given", "mW/cm2")]
    rows += [("PLQY", 100.0 * r["PLQY_ref"], "%"), ("at", r["suns_ref"], "suns"),
             ("Non-radiative loss -kT ln(PLQY)", 1000.0 * r["dV_nr_ref"], "mV"),
             ("J0,rad from", {"eqe": "EQE of the stack", "bandgap": "step at Eg", "j0": "entered",
                              "none": "not given"}[ref["kind"]], ""), ("J0,rad", ref["J0_rad"], "mA/cm2"),
             ("One-sun generation current", ref["J_G_1sun"], "mA/cm2"), ("Voc,rad (1 sun)", ref["Voc_rad_1sun"], "V"),
             ("QFLS", r["QFLS_ref"], "eV"), ("QFLS at 1 sun", r["QFLS_1sun"], "eV"),
             ("PLQY at 1 sun", 100.0 * r["PLQY_1sun"], "%")]
    if np.isfinite(r["Voc_ref"]):
        rows += [("Voc", r["Voc_ref"], "V"), ("QFLS/q - Voc", 1000.0 * r["dV_int_ref"], "mV")]
    if r["kind"] == "series":
        qf, vf = r.get("qfls_fit") or {}, r.get("voc_fit") or {}
        rows += [("Intensities", len(r["suns"]), ""), ("Range", r["decades"], "decades"),
                 ("Implied ideality factor", qf.get("n_id", np.nan), ""),
                 ("Implied n_id 95 % interval (+-)", qf.get("n_id_ci", np.nan), ""),
                 ("d ln PLQY / d ln I", r["plqy_exponent"], ""),
                 ("n_id from Voc", vf.get("n_id", np.nan), ""),
                 ("Implied Voc", r["iVoc"], "V"), ("Implied FF", r["iFF"], "%"), ("Implied efficiency", r["iPCE"], "%"),
                 ("Transport loss (iFF - FF)", r["transport_loss_FF"], "% abs")]
    return rows


# --------------------------------------------------------------------------- synthetic data
def _gauss(x, x0, fwhm):
    s = fwhm / 2.3548200450309493
    return np.exp(-0.5 * ((x - x0) / s) ** 2)


def simulate_sphere(plqy: float = 0.05, absorptance: float = 0.8, indirect: float = 0.15,
                    laser_nm: float = 532.0, laser_fwhm_nm: float = 2.0, pl_peak_ev: float = 1.60,
                    pl_fwhm_ev: float = 0.09, laser_peak_counts: float = 2e5, wl=None, noise: bool = True,
                    seed: int = 0, units: str = "photons", dark: float = 20.0) -> Dict[str, np.ndarray]:
    """Three sphere spectra of a sample with the given PLQY and absorptance.

    B (out of the beam): the sample absorbs the fraction `indirect` of the
    diffuse laser light; C (in the beam): it absorbs `absorptance` of the
    direct beam and `indirect` of what it scatters or transmits. The
    emission band is Gaussian in energy (with the Jacobian to wavelength).
    Poisson noise on dark-corrected counts."""
    wl = np.arange(450.0, 950.0 + 1e-9, 0.5) if wl is None else np.asarray(wl, float)
    line = _gauss(wl, laser_nm, laser_fwhm_nm)
    e = HC_EV_NM / wl
    band = _gauss(e, pl_peak_ev, pl_fwhm_ev) * e ** 2 / HC_EV_NM
    line_area = np.trapezoid(line, wl)
    band = band / np.trapezoid(band, wl)                  # unit photon integral
    la = laser_peak_counts * line_area
    lb, lc = la * (1 - indirect), la * (1 - absorptance) * (1 - indirect)
    pb, pc = plqy * indirect * la, plqy * la * (absorptance + indirect * (1 - absorptance))
    spec = {"a": la * line / line_area, "b": lb * line / line_area + pb * band,
            "c": lc * line / line_area + pc * band}
    rng = np.random.default_rng(seed)
    out = {"wl": wl}
    for k, v in spec.items():
        counts = rng.poisson(v + dark) - dark if noise else v
        out[k] = counts / wl * 500.0 if units == "energy" else counts.astype(float)
    return out


def simulate_series(plqy_1sun: float = 0.02, n_id: float = 1.3, j_g_1sun: float = 24.0, j0_rad: float = 1e-21,
                    dv_int: float = 0.03, suns=None, temperature_k: float = 300.0, transport_ff_loss: float = 4.0
                    ) -> Dict[str, np.ndarray]:
    """PLQY ~ suns^(n_id - 1) (so QFLS rises n_id kT per e-fold of intensity),
    Voc = QFLS - dv_int, FF = implied FF - transport loss at one sun."""
    x = np.logspace(-3, 0, 16) if suns is None else np.asarray(suns, float)
    y = plqy_1sun * x ** (n_id - 1.0)
    q = qfls_ev(y, x * j_g_1sun, j0_rad, temperature_k)
    ff = np.full(len(x), np.nan)
    k = int(np.argmin(np.abs(np.log(x))))
    ff[k] = 100.0 * ideal_ff(float(q[k]), n_id, temperature_k) - transport_ff_loss
    return {"intensity": x, "plqy": y, "voc": q - dv_int, "jsc": x * j_g_1sun, "ff": ff, "qfls": q}


def simulate(**kw) -> Dict[str, np.ndarray]:
    """The three sphere spectra of `simulate_sphere` (the tool's example)."""
    return simulate_sphere(**kw)


def ideal_ff(voc_v: float, n_id: float, temperature_k: float = 300.0) -> float:
    """Fill factor of J = J_G (1 - exp((V - Voc) / (n kT))), the curve the
    implied J-V construction samples, on a fine grid."""
    v = np.linspace(0.0, voc_v, 200001)
    p = v * (1.0 - np.exp((v - voc_v) / (n_id * KB_EV * temperature_k)))
    return float(p.max() / voc_v)
