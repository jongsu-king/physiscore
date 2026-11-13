"""Spectral mismatch factor of a solar simulator and its spectral match
class (GUI-free).

A simulator is set to one sun with a calibrated reference cell. A test cell
whose spectral response differs from the reference cell's then sees a
different share of the simulator spectrum than of AM1.5G, and its measured
current is off by the mismatch factor (IEC 60904-7; Osterwald 1986):

    M = [Int E_ref S_R  Int E_sim S_T] / [Int E_sim S_R  Int E_ref S_T]

    E_ref  AM1.5G, ASTM G173-03 global tilt (bundled with the EQE tool)
    E_sim  simulator spectrum (any scale; energy or photon units)
    S_R    spectral responsivity of the reference cell (A/W), or its EQE
    S_T    spectral responsivity of the test cell, or its EQE

so the test cell reads Jsc,sim = M Jsc,AM1.5 and the current to report is
Jsc,measured / M. M does not depend on the scale of any of the four
functions, only on their shapes; an EQE is turned into a responsivity with
SR = EQE q lambda / (h c) = EQE lambda / 1239.84 A/W (lambda in nm), which
changes the shape. The integrals run over the range of the simulator
spectrum; a response is zero outside its measured range.

Spectral match (IEC 60904-9): the share of the simulator irradiance in each
wavelength interval divided by the share of AM1.5G in it. Edition 2 (2007):
six intervals 400-1100 nm; edition 3 (2020): six intervals of about 16.7 %
each over 300-1200 nm. Classes per interval: A+ 0.875-1.125 (edition 3
only), A 0.75-1.25, B 0.6-1.4, C 0.4-2.0; the class of the simulator is
that of its worst interval. The reference shares are computed from the
bundled spectrum (edition 2: 18.4, 19.9, 18.4, 14.9, 12.5, 15.9 %, as in
the standard's table).

References
    IEC 60904-7:2019, Computation of the spectral mismatch correction
    IEC 60904-9:2007 (Ed. 2) and 2020 (Ed. 3), Solar simulator performance
    Osterwald, Solar Cells 18, 269 (1986)
    Shrotriya et al., Adv. Funct. Mater. 16, 2016 (2006)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from scripts.EQE import eqe_core

HC_EV_NM = eqe_core.HC_EV_NM
KINDS = ("auto", "eqe", "sr")
SIM_UNITS = ("energy", "photons")
AM15G = "AM1.5G"                        # simulator 'file' that is the reference spectrum itself
EXAMPLE = "<example>"                   # built-in synthetic spectra of the demo

_WL = [r"wave", r"lambda", r"\bnm\b", r"\bwl\b"]
COLUMN_SPEC = [("wl", _WL, 0),
               ("y", [r"eqe", r"ipce", r"\bqe\b", r"quantum", r"\bsr\b", r"respons", r"a/w", r"irrad", r"intens",
                      r"power", r"counts", r"signal"], 1)]
_SR_NAME = (r"a/w", r"\bsr\b", r"respons")

EDITIONS = {
    "Ed. 2 (2007)": ((400, 500, 600, 700, 800, 900, 1100), False),
    "Ed. 3 (2020)": ((300, 470, 561, 657, 772, 919, 1200), True),
}
IEC_ED2_TABLE = (18.4, 19.9, 18.4, 14.9, 12.5, 15.9)     # per cent, IEC 60904-9:2007 Table 1
CLASS_LIMITS = (("A+", 0.875, 1.125), ("A", 0.75, 1.25), ("B", 0.6, 1.4), ("C", 0.4, 2.0))
GRID_STEP_NM = 0.5


# --------------------------------------------------------------------------- reading
def read_curve(path: str, names: bool = False):
    """(wavelength nm, value, value column name) of a two-column table; with
    `names` the third item is {'wavelength': ..., 'response': ...}."""
    from scripts.common import curve_io
    df = curve_io.read_numeric_table(path)
    data, cols = curve_io.pick_columns(df, COLUMN_SPEC)
    if "y" not in data:
        raise ValueError("the file needs a wavelength column and a value column")
    wl, y = curve_io.finite_rows(data["wl"], data["y"])
    if wl.max() < 5.0:                 # micrometres
        wl = wl * 1000.0
    o = np.argsort(wl)
    if names:
        return wl[o], y[o], {"wavelength": cols.get("wl", ""), "response": cols.get("y", "")}
    return wl[o], y[o], cols.get("y", "")


def response_kind(kind: str, column: str, default: str) -> str:
    """'eqe' or 'sr': as chosen, or (auto) from the column name, else `default`."""
    if kind not in KINDS:
        raise ValueError(f"response kind must be one of {', '.join(KINDS)}")
    if kind != "auto":
        return kind
    import re
    name = (column or "").lower()
    if any(re.search(p, name) for p in _SR_NAME):
        return "sr"
    if re.search(r"eqe|ipce|\bqe\b|quantum|%", name):
        return "eqe"
    return default


def to_sr(wl, y, kind: str) -> np.ndarray:
    """Spectral responsivity (A/W) from an EQE (fraction or per cent) or as given."""
    wl, y = np.asarray(wl, float), np.asarray(y, float)
    if kind == "sr":
        return np.clip(y, 0.0, None)
    return np.clip(eqe_core.eqe_to_fraction(y), 0.0, None) * wl / HC_EV_NM


def to_energy(wl, y, units: str) -> np.ndarray:
    """Spectral irradiance (energy per wavelength, any scale) of the simulator."""
    if units not in SIM_UNITS:
        raise ValueError(f"simulator units must be one of {', '.join(SIM_UNITS)}")
    wl, y = np.asarray(wl, float), np.clip(np.asarray(y, float), 0.0, None)
    return y if units == "energy" else y * HC_EV_NM / wl


# --------------------------------------------------------------------------- synthetic spectra
def example_simulator(wl=None) -> Tuple[np.ndarray, np.ndarray]:
    """A xenon-arc-like spectrum: a 5800 K black body with the Xe lines of
    800-1000 nm on top (W m-2 nm-1, scaled to 1000 W/m2 over 280-4000 nm)."""
    wl = np.arange(280.0, 1500.0 + 1e-9, 1.0) if wl is None else np.asarray(wl, float)
    lam = wl * 1e-9
    bb = 1.0 / (lam ** 5 * np.expm1(6.62607015e-34 * 299792458.0 / (lam * 1.380649e-23 * 5800.0)))
    bb = bb / bb.max()
    lines = sum(h * np.exp(-0.5 * ((wl - c) / 4.0) ** 2)
                for c, h in ((823.0, 1.4), (828.0, 0.9), (882.0, 1.6), (904.0, 0.6), (916.0, 0.9), (980.0, 0.8),
                             (992.0, 1.0)))
    e = bb + 0.6 * lines
    e = e * 1000.0 / np.trapezoid(e, wl)
    return wl, e


def example_reference(wl=None) -> Tuple[np.ndarray, np.ndarray]:
    """Spectral responsivity (A/W) of a crystalline-silicon reference cell."""
    wl = np.arange(300.0, 1200.0 + 1e-9, 5.0) if wl is None else np.asarray(wl, float)
    eqe = 0.92 / (1 + np.exp(-(wl - 360.0) / 18.0)) / (1 + np.exp((wl - 1080.0) / 28.0))
    return wl, eqe * wl / HC_EV_NM


def example_test(edge_nm: float = 790.0, plateau: float = 0.86, wl=None) -> Tuple[np.ndarray, np.ndarray]:
    """EQE (%) of a perovskite cell with its band edge at `edge_nm`."""
    wl = np.arange(300.0, 900.0 + 1e-9, 5.0) if wl is None else np.asarray(wl, float)
    eqe = plateau / (1 + np.exp(-(wl - 340.0) / 12.0)) / (1 + np.exp((wl - edge_nm) / 9.0))
    return wl, 100.0 * eqe


def simulate(**kw) -> Tuple[np.ndarray, np.ndarray]:
    """The example test cell (the tool's example)."""
    return example_test(**kw)


def _source(path: str, kind: str) -> Tuple[np.ndarray, np.ndarray, str]:
    """(wl, value, column) of a file, the built-in example or AM1.5G itself."""
    p = (path or "").strip()
    if not p:
        raise ValueError("choose the simulator spectrum file" if kind == "sim" else "choose the reference cell file")
    if p.upper() == AM15G.upper():
        if kind != "sim":
            raise ValueError("AM1.5G is a spectrum, not a cell response")
        wl, e = eqe_core.get_am15g_spectrum()
        return wl, e, "irradiance"
    if p.startswith(EXAMPLE):
        wl, y = example_simulator() if kind == "sim" else example_reference()
        return wl, y, "irradiance" if kind == "sim" else "SR (A/W)"
    return read_curve(p)


# --------------------------------------------------------------------------- the factor
def _integrate(x, y) -> float:
    return float(np.trapezoid(y, x))


def mismatch_factor(test_wl, test_sr, ref_wl, ref_sr, sim_wl, sim_e) -> Dict[str, Any]:
    """M and the four integrals; responses are zero outside their measured
    range, the integrals run over the simulator range within 280-4000 nm."""
    ref_l, ref_e = eqe_core.get_am15g_spectrum()
    sim_wl, sim_e = np.asarray(sim_wl, float), np.asarray(sim_e, float)
    lo, hi = max(float(sim_wl.min()), float(ref_l.min())), min(float(sim_wl.max()), float(ref_l.max()))
    if hi - lo < 50.0:
        raise ValueError("the simulator spectrum covers less than 50 nm of the AM1.5G range")
    g = np.arange(lo, hi + 1e-9, GRID_STEP_NM)
    e_ref = np.interp(g, ref_l, ref_e)
    e_sim = np.interp(g, sim_wl, sim_e)
    s_t = np.interp(g, test_wl, test_sr, left=0.0, right=0.0)
    s_r = np.interp(g, ref_wl, ref_sr, left=0.0, right=0.0)
    i_rr, i_rt = _integrate(g, e_ref * s_r), _integrate(g, e_ref * s_t)
    i_sr, i_st = _integrate(g, e_sim * s_r), _integrate(g, e_sim * s_t)
    if min(i_rr, i_rt, i_sr, i_st) <= 0:
        raise ValueError("a response does not overlap the simulator spectrum")
    m = (i_rr * i_st) / (i_sr * i_rt)

    def full_current(wl, sr):
        """The cell's AM1.5G current over its own measured range."""
        gg = np.arange(max(float(np.min(wl)), float(ref_l.min())), min(float(np.max(wl)), float(ref_l.max())) + 1e-9,
                       GRID_STEP_NM)
        return _integrate(gg, np.interp(gg, ref_l, ref_e) * np.interp(gg, wl, sr))

    cov_t, cov_r = i_rt / full_current(test_wl, test_sr), i_rr / full_current(ref_wl, ref_sr)
    return {"M": float(m), "I_ref_ref": i_rr, "I_ref_test": i_rt, "I_sim_ref": i_sr, "I_sim_test": i_st,
            "range_nm": (float(lo), float(hi)), "grid": g, "e_ref": e_ref, "e_sim": e_sim, "s_test": s_t, "s_ref": s_r,
            "coverage_test": min(1.0, float(cov_t)), "coverage_ref": min(1.0, float(cov_r)),
            "Jsc_AM15_test": i_rt / 10.0, "Jsc_AM15_ref": i_rr / 10.0}       # A m-2 -> mA cm-2


def classify(ratio: float, plus: bool) -> str:
    for name, lo, hi in CLASS_LIMITS:
        if name == "A+" and not plus:
            continue
        if lo <= ratio <= hi:
            return name
    return "outside C"


_ORDER = {"A+": 0, "A": 1, "B": 2, "C": 3, "outside C": 4}


def spectral_match(sim_wl, sim_e) -> Dict[str, Optional[Dict[str, Any]]]:
    """Interval shares, ratios and classes for both editions (None where the
    simulator spectrum does not cover the edition's range)."""
    ref_l, ref_e = eqe_core.get_am15g_spectrum()
    sim_wl, sim_e = np.asarray(sim_wl, float), np.asarray(sim_e, float)
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for name, (edges, plus) in EDITIONS.items():
        if sim_wl.min() > edges[0] + 1.0 or sim_wl.max() < edges[-1] - 1.0:
            out[name] = None
            continue
        g = np.arange(edges[0], edges[-1] + 1e-9, GRID_STEP_NM)
        er, es = np.interp(g, ref_l, ref_e), np.interp(g, sim_wl, sim_e)
        tr, ts = _integrate(g, er), _integrate(g, es)
        rows = []
        for a, b in zip(edges[:-1], edges[1:]):
            m = (g >= a) & (g <= b)
            fr, fs = 100.0 * _integrate(g[m], er[m]) / tr, 100.0 * _integrate(g[m], es[m]) / ts
            r = fs / fr
            rows.append({"interval": f"{a}-{b}", "lo": a, "hi": b, "ref_pct": fr, "sim_pct": fs, "ratio": r,
                         "class": classify(r, plus)})
        worst = max(rows, key=lambda x: _ORDER[x["class"]])["class"]
        out[name] = {"rows": rows, "class": worst, "plus": plus}
    return out


def _band_edges(wl, sr, frac: float = 0.1) -> Tuple[float, float]:
    """Shortest and longest wavelength where the response is above `frac` of its maximum."""
    wl, sr = np.asarray(wl, float), np.asarray(sr, float)
    if not len(sr) or sr.max() <= 0:
        return float("nan"), float("nan")
    m = sr >= frac * sr.max()
    return float(wl[m].min()), float(wl[m].max())


def analyse(test_wl, test_y, sim_file: str = "", ref_file: str = "", test_kind: str = "auto",
            ref_kind: str = "auto", sim_units: str = "energy", test_column: str = "",
            sim: Optional[Tuple[np.ndarray, np.ndarray]] = None,
            ref: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> Dict[str, Any]:
    """One test cell (EQE or responsivity) against a simulator spectrum and a
    reference cell -> M, the expected and corrected currents, the spectral
    match class of the simulator."""
    test_wl, test_y = np.asarray(test_wl, float), np.asarray(test_y, float)
    ok = np.isfinite(test_wl) & np.isfinite(test_y)
    test_wl, test_y = test_wl[ok], test_y[ok]
    if len(test_wl) < 5:
        raise ValueError("the test cell response has fewer than 5 points")
    o = np.argsort(test_wl)
    test_wl, test_y = test_wl[o], test_y[o]
    if test_wl.max() < 5.0:
        test_wl = test_wl * 1000.0
    tk = response_kind(test_kind, test_column, "eqe")
    s_t = to_sr(test_wl, test_y, tk)
    if sim is not None:
        sim_wl, sim_raw, sim_col = np.asarray(sim[0], float), np.asarray(sim[1], float), "irradiance"
        sim_name = "given"
    else:
        sim_wl, sim_raw, sim_col = _source(sim_file, "sim")
        sim_name = sim_file
    e_sim = to_energy(sim_wl, sim_raw, "energy" if sim_name.upper() == AM15G.upper() else sim_units)
    if ref is not None:
        ref_wl, ref_raw, ref_col = np.asarray(ref[0], float), np.asarray(ref[1], float), "SR (A/W)"
    else:
        ref_wl, ref_raw, ref_col = _source(ref_file, "ref")
    rk = response_kind(ref_kind, ref_col, "sr")
    s_r = to_sr(ref_wl, ref_raw, rk)
    mm = mismatch_factor(test_wl, s_t, ref_wl, s_r, sim_wl, e_sim)
    res: Dict[str, Any] = {
        **mm, "test_kind": tk, "ref_kind": rk, "sim_units": sim_units, "sim_file": sim_name, "ref_file": ref_file,
        "test_wl": test_wl, "test_y": test_y, "test_sr": s_t, "ref_wl": ref_wl, "ref_sr": s_r,
        "sim_wl": sim_wl, "sim_e": e_sim, "match": spectral_match(sim_wl, e_sim),
        "test_edges": _band_edges(test_wl, s_t), "ref_edges": _band_edges(ref_wl, s_r),
        "sr_limit_ratio_test": float(np.max(s_t / (test_wl / HC_EV_NM))),
        "sr_limit_ratio_ref": float(np.max(s_r / (ref_wl / HC_EV_NM))),
        "tail_test": float(s_t[-1] / s_t.max()) if s_t.max() > 0 else float("nan"),
        "tail_ref": float(s_r[-1] / s_r.max()) if s_r.max() > 0 else float("nan"),
    }
    res["Jsc_expected_sim"] = res["M"] * res["Jsc_AM15_test"]
    res["current_error_pct"] = 100.0 * (res["M"] - 1.0)
    cls = res["match"].get("Ed. 3 (2020)") or res["match"].get("Ed. 2 (2007)")
    res["sim_class"] = cls["class"] if cls else ""
    res["sim_class_edition"] = ("Ed. 3 (2020)" if res["match"].get("Ed. 3 (2020)") else
                                "Ed. 2 (2007)" if res["match"].get("Ed. 2 (2007)") else "")
    res["warnings"] = checks(res)
    return res


# --------------------------------------------------------------------------- checks and rows
def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    for who, key in (("test cell", "coverage_test"), ("reference cell", "coverage_ref")):
        if r[key] < 0.99:
            w.append(f"The simulator spectrum ({r['range_nm'][0]:.0f}-{r['range_nm'][1]:.0f} nm) covers only "
                     f"{100 * r[key]:.1f} % of the {who}'s AM1.5G current: the part outside is missing from M. "
                     "Measure the simulator over the whole response range.")
    for who, key in (("test cell", "sr_limit_ratio_test"), ("reference cell", "sr_limit_ratio_ref")):
        if r[key] > 1.02:
            w.append(f"The {who} responsivity is {r[key]:.2f} times lambda/1239.84 A/W, which would need an EQE "
                     "above 100 %: the file is probably an EQE in per cent read as A/W, or the other way round. "
                     "Set the response kind.")
    for who, key in (("test cell", "tail_test"), ("reference cell", "tail_ref")):
        if np.isfinite(r[key]) and r[key] > 0.05:
            w.append(f"The {who} still responds at the long-wavelength end of its file ({100 * r[key]:.0f} % of "
                     "its maximum): its response beyond the file is taken as zero, so M misses that part.")
    if not r["match"].get("Ed. 2 (2007)") and not r["match"].get("Ed. 3 (2020)"):
        w.append("The simulator spectrum does not cover 400-1100 nm, so no IEC 60904-9 spectral match class "
                 "can be given.")
    elif not r["match"].get("Ed. 3 (2020)"):
        w.append("The simulator spectrum does not cover 300-1200 nm: the class is given for edition 2 "
                 "(400-1100 nm) only.")
    if np.isfinite(r["test_edges"][1]) and np.isfinite(r["ref_edges"][1]) and \
            abs(r["test_edges"][1] - r["ref_edges"][1]) > 150.0 and abs(r["M"] - 1.0) > 0.02:
        w.append(f"The reference cell responds to {r['ref_edges'][1]:.0f} nm and the test cell to "
                 f"{r['test_edges'][1]:.0f} nm: a reference cell matched to the test cell (filtered silicon, or "
                 "a cell of the same absorber) keeps M close to 1 and less sensitive to lamp drift.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    rows: List[Tuple[str, Any, str]] = [
        ("Mismatch factor M", r["M"], ""), ("Current error without M", r["current_error_pct"], "%"),
        ("Jsc AM1.5G (test cell)", r["Jsc_AM15_test"], "mA/cm2"),
        ("Jsc on the simulator (M Jsc)", r["Jsc_expected_sim"], "mA/cm2"),
        ("Reference cell Jsc AM1.5G", r["Jsc_AM15_ref"], "mA/cm2"),
        ("Test cell read as", "EQE" if r["test_kind"] == "eqe" else "SR (A/W)", ""),
        ("Reference cell read as", "EQE" if r["ref_kind"] == "eqe" else "SR (A/W)", ""),
        ("Integration range", f"{r['range_nm'][0]:.0f}-{r['range_nm'][1]:.0f}", "nm"),
        ("Test current in range", 100.0 * r["coverage_test"], "%"),
        ("Reference current in range", 100.0 * r["coverage_ref"], "%"),
        ("Test cell above 10 % of max", f"{r['test_edges'][0]:.0f}-{r['test_edges'][1]:.0f}", "nm"),
        ("Reference above 10 % of max", f"{r['ref_edges'][0]:.0f}-{r['ref_edges'][1]:.0f}", "nm"),
    ]
    for name, m in r["match"].items():
        short = name.split(" (")[0]
        if m is None:
            rows.append((f"Class {name}", "not covered", ""))
            continue
        rows.append((f"Class {name}", m["class"], ""))
        for row in m["rows"]:
            rows.append((f"  {short}: {row['interval']} nm", row["ratio"], row["class"]))
    return rows
