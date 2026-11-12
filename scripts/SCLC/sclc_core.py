"""Space-charge-limited current (SCLC) analysis of single-carrier devices.

The dark J-V curve of an electron-only or hole-only device is analysed on
log-log axes. Three regimes are located from the local slope
m = d log J / d log V:

    ohmic        m ~ 1     J = sigma V / L
    trap filling m > 2     steep rise once the traps fill
    Child        m ~ 2     J = (9/8) eps0 epsr mu V^2 / L^3   (Mott-Gurney)

and the usual quantities follow:

    V1   crossing of the ohmic and trap-filling tangents (the conventional V_TFL)
    V2   crossing of the trap-filling and Child tangents
    Vinf voltage of the steepest slope
    n_t  = 2 eps0 epsr V_TFL / (q L^2)
    mu   from the Child regime with the slope fixed to 2
    sigma from the ohmic regime, n0 = sigma / (q mu)

Le Corre et al. (ACS Energy Lett. 6, 1087, 2021) show with drift-diffusion
simulations that V2 reproduces the trap density better than V1, that a trap
density below n_diff = 4 pi^2 kT eps / (q^2 L^2) cannot produce a
trap-filling regime at all, and that with mobile ions the voltage measures
the net charge rather than the traps. The module reports all three voltages,
the resolution limit and, when the file holds an up and a down sweep, the
hysteresis between them, so that those cases can be recognised.

References
    Mott, Gurney, Electronic Processes in Ionic Crystals (1940)
    Lampert, Phys. Rev. 103, 1648 (1956)                      trap-filled limit
    Murgatroyd, J. Phys. D 3, 151 (1970)                      field-dependent mobility
    Röhr et al., J. Phys.: Condens. Matter 30, 105901 (2018)  validity of Mott-Gurney
    Le Corre et al., ACS Energy Lett. 6, 1087 (2021)          perovskites, V2, n_diff
    Duijnstee et al., ACS Energy Lett. 5, 376 (2020)          pulsed SCLC, ions
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from scripts.common.curve_io import linfit

EPS0 = 8.8541878128e-12      # F/m
Q = 1.602176634e-19          # C
KB = 1.380649e-23            # J/K

OHMIC_RANGE = (0.7, 1.35)    # local-slope windows that define the regimes
CHILD_RANGE = (1.65, 2.45)
TFL_MIN_SLOPE = 2.6
MIN_POINTS = 3


def read_curve(path: str, area_cm2: float) -> Tuple[np.ndarray, np.ndarray, str]:
    """(V [V], J [mA/cm2], how the columns were read) of a dark J-V file.

    A source-meter export with a Vmeas / Imeas block is read in full - the
    solar-cell reader keeps only -3 ... 3 V, which would cut the Child regime -
    and any other table goes through the column-name rules of the J-V tools.
    Only magnitudes are used afterwards, so the sign convention does not matter."""
    from scripts.common import textio
    try:
        lines = [] if path.lower().endswith((".xlsx", ".xls")) else textio.read_text(path).splitlines()
    except Exception:
        lines = []                                    # a workbook: handled below
    start = next((i + 1 for i, ln in enumerate(lines) if "Vmeas" in ln and "Imeas" in ln), None)
    if start is not None:
        if area_cm2 <= 0:
            raise ValueError("the device area must be positive")
        v, j = [], []
        for ln in lines[start:]:
            parts = ln.replace(",", "\t").split("\t")
            if len(parts) < 2:
                continue
            try:
                vv, ii = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            v.append(vv)
            j.append(ii * 1000.0 / area_cm2)
        return np.asarray(v, float), np.asarray(j, float), (
            f"instrument Vmeas/Imeas block, current in A divided by {area_cm2:g} cm2")
    from scripts.common.iv_io import read_generic_iv
    return read_generic_iv(path, area_cm2)


def split_sweeps(v: np.ndarray, j: np.ndarray) -> List[Dict[str, np.ndarray]]:
    """Split a record at the turning points of |V| into monotonic sweeps."""
    v, j = np.asarray(v, float), np.asarray(j, float)
    a = np.abs(v)
    if len(a) < 4:
        return [{"v": v, "j": j, "direction": "up"}]
    d = np.sign(np.diff(a))
    d[d == 0] = 1
    cuts = [0]
    for i in range(1, len(d)):
        if d[i] != d[i - 1]:
            cuts.append(i)
    cuts.append(len(a) - 1)
    out = []
    for s, e in zip(cuts[:-1], cuts[1:]):
        if e - s + 1 < 4:
            continue
        seg_v, seg_j = v[s:e + 1], j[s:e + 1]
        out.append({"v": seg_v, "j": seg_j, "direction": "up" if abs(seg_v[-1]) > abs(seg_v[0]) else "down"})
    return out or [{"v": v, "j": j, "direction": "up"}]


def prepare(v, j, branch: str = "auto", v_bi: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """|J| against |V| - V_bi of one polarity, sorted by voltage, duplicate
    voltages averaged, non-positive values dropped. `branch`: positive,
    negative or auto (the polarity with the larger voltage span)."""
    v, j = np.asarray(v, float), np.asarray(j, float)
    ok = np.isfinite(v) & np.isfinite(j)
    v, j = v[ok], j[ok]
    pos, neg = v > 0, v < 0
    if branch == "auto":
        span_p = v[pos].max() if pos.any() else 0.0
        span_n = -v[neg].min() if neg.any() else 0.0
        branch = "negative" if span_n > span_p else "positive"
    sel = neg if branch == "negative" else pos
    vv = np.abs(v[sel]) - float(v_bi)
    jj = np.abs(j[sel])
    keep = (vv > 0) & (jj > 0)
    vv, jj = vv[keep], jj[keep]
    if len(vv) == 0:
        return vv, jj
    order = np.argsort(vv)
    vv, jj = vv[order], jj[order]
    uv, inv = np.unique(np.round(vv, 9), return_inverse=True)
    if len(uv) < len(vv):      # average repeated voltages in log space
        lj = np.zeros(len(uv))
        cnt = np.zeros(len(uv))
        np.add.at(lj, inv, np.log(jj))
        np.add.at(cnt, inv, 1.0)
        vv, jj = uv, np.exp(lj / cnt)
    return vv, jj


def local_slope(v: np.ndarray, j: np.ndarray, window: int = 5) -> np.ndarray:
    """d log J / d log V from a moving straight-line fit over `window` points."""
    lv, lj = np.log10(v), np.log10(j)
    n = len(lv)
    h = max(1, int(window) // 2)
    m = np.full(n, np.nan)
    for i in range(n):
        a, b = max(0, i - h), min(n, i + h + 1)
        if b - a >= 3 and np.ptp(lv[a:b]) > 0:
            m[i] = np.polyfit(lv[a:b], lj[a:b], 1)[0]
    return m


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    out, start = [], None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def _longest(runs, lv, lo=None, hi=None):
    """Longest run (in decades of voltage) inside the index window [lo, hi]."""
    best, best_len = None, -1.0
    for a, b in runs:
        if lo is not None:
            a = max(a, lo)
        if hi is not None:
            b = min(b, hi)
        if b - a + 1 < MIN_POINTS:
            continue
        span = lv[b] - lv[a]
        if span > best_len:
            best, best_len = (a, b), span
    return best


def find_regimes(v: np.ndarray, j: np.ndarray, window: int = 5) -> Dict[str, Any]:
    """Locate the ohmic, trap-filling and Child regimes from the local slope
    and fit a straight line (log-log) to each."""
    lv, lj = np.log10(v), np.log10(j)
    m = local_slope(v, j, window)
    fin = np.isfinite(m)
    regs: Dict[str, Optional[Tuple[int, int]]] = {"ohmic": None, "tfl": None, "child": None}

    tfl_mask = fin & (m > TFL_MIN_SLOPE)
    if tfl_mask.any():
        i_max = int(np.nanargmax(np.where(tfl_mask, m, -np.inf)))
        thr = max(TFL_MIN_SLOPE, 0.6 * m[i_max])
        for a, b in _runs(fin & (m >= thr)):
            if a <= i_max <= b and b - a + 1 >= MIN_POINTS:
                regs["tfl"] = (a, b)
        if regs["tfl"] is None:
            for a, b in _runs(tfl_mask):
                if a <= i_max <= b and b - a + 1 >= MIN_POINTS:
                    regs["tfl"] = (a, b)

    ohmic_runs = _runs(fin & (m >= OHMIC_RANGE[0]) & (m <= OHMIC_RANGE[1]))
    child_runs = _runs(fin & (m >= CHILD_RANGE[0]) & (m <= CHILD_RANGE[1]))
    if regs["tfl"] is not None:
        regs["ohmic"] = _longest(ohmic_runs, lv, hi=regs["tfl"][0])
        regs["child"] = _longest(child_runs, lv, lo=regs["tfl"][1])
    else:
        regs["ohmic"] = _longest(ohmic_runs, lv)
        regs["child"] = _longest(child_runs, lv, lo=regs["ohmic"][1] if regs["ohmic"] else None)

    out: Dict[str, Any] = {"local_slope": m}
    for name, rng in regs.items():
        if rng is None:
            out[name] = None
            continue
        a, b = rng
        fit = linfit(lv[a:b + 1], lj[a:b + 1])
        fit.update({"i0": a, "i1": b, "v_lo": float(v[a]), "v_hi": float(v[b])})
        out[name] = fit
    return out


def _crossing(f1: Dict[str, float], f2: Dict[str, float]) -> float:
    """Voltage where two log-log lines meet."""
    dm = f1["slope"] - f2["slope"]
    if not np.isfinite(dm) or abs(dm) < 1e-6:
        return np.nan
    return float(10 ** ((f2["intercept"] - f1["intercept"]) / dm))


def trap_density_cm3(v_tfl: float, thickness_nm: float, eps_r: float) -> float:
    """n_t = 2 eps0 epsr V_TFL / (q L^2), in cm^-3."""
    L = thickness_nm * 1e-9
    return float(2.0 * EPS0 * eps_r * v_tfl / (Q * L ** 2) * 1e-6)


def resolution_limit_cm3(thickness_nm: float, eps_r: float, temperature_k: float = 300.0) -> float:
    """Smallest trap density that can give a trap-filling regime,
    n_diff = 4 pi^2 kT eps / (q^2 L^2) (Le Corre 2021), in cm^-3."""
    L = thickness_nm * 1e-9
    return float(4.0 * np.pi ** 2 * KB * temperature_k * EPS0 * eps_r / (Q ** 2 * L ** 2) * 1e-6)


def mott_gurney_mobility(v: np.ndarray, j_ma_cm2: np.ndarray, thickness_nm: float, eps_r: float
                         ) -> Tuple[float, float]:
    """Mobility (cm2/Vs) and its standard error from J = (9/8) eps mu V^2 / L^3
    with the slope fixed to 2 (least squares on log J)."""
    L = thickness_nm * 1e-9
    y = np.log(j_ma_cm2 * 10.0) - 2.0 * np.log(v)      # ln of A/m2 over V^2
    a = float(np.mean(y))
    se = float(np.std(y, ddof=1) / np.sqrt(len(y))) if len(y) > 1 else np.nan
    mu = 8.0 * np.exp(a) * L ** 3 / (9.0 * EPS0 * eps_r) * 1e4
    return float(mu), float(mu * se) if np.isfinite(se) else np.nan


def murgatroyd(v: np.ndarray, j_ma_cm2: np.ndarray, thickness_nm: float, eps_r: float) -> Dict[str, float]:
    """Field-dependent mobility mu = mu0 exp(gamma sqrt(E)):
    J = (9/8) eps mu0 V^2 / L^3 exp(0.891 gamma sqrt(V / L)).
    ln(J / V^2) against sqrt(V) is a line; mu0 in cm2/Vs, gamma in (cm/V)^0.5."""
    L = thickness_nm * 1e-9
    fit = linfit(np.sqrt(v), np.log(j_ma_cm2 * 10.0 / v ** 2))
    mu0 = 8.0 * np.exp(fit["intercept"]) * L ** 3 / (9.0 * EPS0 * eps_r) * 1e4
    gamma_si = fit["slope"] * np.sqrt(L) / 0.891          # (m/V)^0.5
    return {"mu0_cm2_Vs": float(mu0), "gamma_cm_V_05": float(gamma_si * 10.0), "r2": fit["r2"], "n": fit["n"]}


def hysteresis_decades(v, j, branch: str = "auto", v_bi: float = 0.0) -> float:
    """Mean |log10(J_up / J_down)| over the common voltage range of the first
    up and down sweeps; NaN when the record holds a single sweep."""
    sweeps = split_sweeps(v, j)
    up = next((s for s in sweeps if s["direction"] == "up"), None)
    down = next((s for s in sweeps if s["direction"] == "down"), None)
    if up is None or down is None:
        return np.nan
    vu, ju = prepare(up["v"], up["j"], branch, v_bi)
    vd, jd = prepare(down["v"], down["j"], branch, v_bi)
    if len(vu) < 4 or len(vd) < 4:
        return np.nan
    lo, hi = max(vu.min(), vd.min()), min(vu.max(), vd.max())
    if hi <= lo:
        return np.nan
    grid = np.logspace(np.log10(lo), np.log10(hi), 40)
    lu = np.interp(np.log10(grid), np.log10(vu), np.log10(ju))
    ld = np.interp(np.log10(grid), np.log10(vd), np.log10(jd))
    return float(np.mean(np.abs(lu - ld)))


def analyse(v, j_ma_cm2, thickness_nm: float, eps_r: float, temperature_k: float = 300.0,
            branch: str = "auto", sweep: str = "up", v_bi: float = 0.0, window: int = 5,
            field_dependent: bool = False) -> Dict[str, Any]:
    """Full SCLC analysis of one curve. J in mA/cm2, V in volts.

    `sweep`: "up" (first sweep of rising |V|), "down" or "all" (every point,
    repeated voltages averaged)."""
    v_raw, j_raw = np.asarray(v, float), np.asarray(j_ma_cm2, float)
    hyst = hysteresis_decades(v_raw, j_raw, branch, v_bi)
    if sweep in ("up", "down"):
        seg = next((s for s in split_sweeps(v_raw, j_raw) if s["direction"] == sweep), None)
        if seg is not None:
            v_raw, j_raw = seg["v"], seg["j"]
    vv, jj = prepare(v_raw, j_raw, branch, v_bi)
    if len(vv) < 8:
        raise ValueError("SCLC needs at least 8 points with V > 0 and J > 0 on one polarity")
    reg = find_regimes(vv, jj, window)
    res: Dict[str, Any] = {
        "v": vv, "j": jj, "local_slope": reg["local_slope"],
        "ohmic": reg["ohmic"], "tfl": reg["tfl"], "child": reg["child"],
        "thickness_nm": float(thickness_nm), "eps_r": float(eps_r), "temperature_K": float(temperature_k),
        "hysteresis_dec": hyst, "decades_V": float(np.log10(vv.max() / vv.min())),
        "V1": np.nan, "V2": np.nan, "Vinf": np.nan, "V_TFL": np.nan, "V_TFL_from": "",
        "n_t_cm3": np.nan, "n_t_V1_cm3": np.nan, "n_t_V2_cm3": np.nan,
        "mobility_cm2_Vs": np.nan, "mobility_err": np.nan, "child_slope": np.nan,
        "sigma_S_cm": np.nan, "n0_cm3": np.nan, "V_x": np.nan, "murgatroyd": None,
        "max_slope": float(np.nanmax(reg["local_slope"])) if np.isfinite(reg["local_slope"]).any() else np.nan,
    }
    res["n_t_min_cm3"] = resolution_limit_cm3(thickness_nm, eps_r, temperature_k)
    L_cm = thickness_nm * 1e-7
    oh, tf, ch = reg["ohmic"], reg["tfl"], reg["child"]
    if tf is not None:
        res["Vinf"] = float(vv[int(np.nanargmax(reg["local_slope"]))])
        if oh is not None:
            res["V1"] = _crossing(oh, tf)
            res["n_t_V1_cm3"] = trap_density_cm3(res["V1"], thickness_nm, eps_r)
        if ch is not None:
            res["V2"] = _crossing(tf, ch)
            res["n_t_V2_cm3"] = trap_density_cm3(res["V2"], thickness_nm, eps_r)
        if np.isfinite(res["V2"]):
            res["V_TFL"], res["V_TFL_from"], res["n_t_cm3"] = res["V2"], "V2 (trap filling / Child)", res["n_t_V2_cm3"]
        elif np.isfinite(res["V1"]):
            res["V_TFL"], res["V_TFL_from"], res["n_t_cm3"] = res["V1"], "V1 (ohmic / trap filling)", res["n_t_V1_cm3"]
    if ch is not None:
        a, b = ch["i0"], ch["i1"]
        res["child_slope"] = ch["slope"]
        res["mobility_cm2_Vs"], res["mobility_err"] = mott_gurney_mobility(vv[a:b + 1], jj[a:b + 1], thickness_nm, eps_r)
    if oh is not None:
        a, b = oh["i0"], oh["i1"]
        # sigma = J L / V with the slope fixed to 1 (mean of log(J/V))
        g = np.exp(np.mean(np.log(jj[a:b + 1] * 1e-3 / vv[a:b + 1])))      # A/cm2 per V
        res["sigma_S_cm"] = float(g * L_cm)
        if np.isfinite(res["mobility_cm2_Vs"]) and res["mobility_cm2_Vs"] > 0:
            res["n0_cm3"] = float(res["sigma_S_cm"] / (Q * res["mobility_cm2_Vs"]))
        if ch is not None and tf is None:
            res["V_x"] = _crossing(oh, ch)
    if field_dependent:
        lo = (tf or oh or {"i1": 0})["i1"]
        if len(vv) - lo >= 5:
            res["murgatroyd"] = murgatroyd(vv[lo:], jj[lo:], thickness_nm, eps_r)
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    """Plain-language validity checks of one result."""
    w: List[str] = []
    if r["child"] is None:
        w.append("No region with slope near 2 was found: the Mott-Gurney mobility is not reported. "
                 "The voltage range may end before the Child regime, or the current is injection limited.")
    elif abs(r["child_slope"] - 2.0) > 0.25:
        w.append(f"The Child-region slope is {r['child_slope']:.2f}, not 2: a field-dependent mobility "
                 "(Murgatroyd) or residual trap filling changes the mobility by more than its fit error.")
    if r["tfl"] is None:
        w.append("No trap-filling rise (slope above 2.6) was found: no trap density is reported.")
    elif np.isfinite(r["n_t_cm3"]) and r["n_t_cm3"] < r["n_t_min_cm3"]:
        w.append(f"The trap density from V_TFL ({r['n_t_cm3']:.2e} cm-3) is below the resolution limit of this "
                 f"thickness ({r['n_t_min_cm3']:.2e} cm-3, Le Corre 2021): a trap-filling regime is not expected to be "
                 "resolvable, so the rise may have another origin (mobile ions, an injection barrier).")
    if np.isfinite(r["hysteresis_dec"]) and r["hysteresis_dec"] > 0.1:
        w.append(f"Up and down sweeps differ by {r['hysteresis_dec']:.2f} decades on average: mobile ions or slow "
                 "traps respond during the scan, so V_TFL measures a net charge and depends on the scan rate. "
                 "Pulsed SCLC is the appropriate measurement.")
    if r["decades_V"] < 1.5:
        w.append(f"The curve spans only {r['decades_V']:.1f} decades of voltage; regimes located on less than "
                 "about two decades are uncertain.")
    if r["ohmic"] is None:
        w.append("No ohmic region (slope near 1) was found at low voltage: V1 and the conductivity are not reported.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    def reg(name):
        f = r[name]
        return "-" if f is None else f"{f['v_lo']:.3g} - {f['v_hi']:.3g}"

    def slope(name):
        f = r[name]
        return np.nan if f is None else f["slope"]

    return [
        ("Ohmic region", reg("ohmic"), "V"), ("Ohmic slope", slope("ohmic"), ""),
        ("Trap-filling region", reg("tfl"), "V"), ("Maximum slope", r["max_slope"], ""),
        ("Child region", reg("child"), "V"), ("Child slope", r["child_slope"], ""),
        ("V1 (ohmic / TFL)", r["V1"], "V"), ("V2 (TFL / Child)", r["V2"], "V"), ("Vinf (steepest)", r["Vinf"], "V"),
        ("V_TFL used", r["V_TFL"], "V"), ("Trap density n_t", r["n_t_cm3"], "cm-3"),
        ("n_t from V1", r["n_t_V1_cm3"], "cm-3"), ("Resolution limit n_diff", r["n_t_min_cm3"], "cm-3"),
        ("Mobility (Mott-Gurney)", r["mobility_cm2_Vs"], "cm2/Vs"), ("Mobility std. error", r["mobility_err"], "cm2/Vs"),
        ("Conductivity (ohmic)", r["sigma_S_cm"], "S/cm"), ("Carrier density n0", r["n0_cm3"], "cm-3"),
        ("Ohmic / Child crossover", r["V_x"], "V"), ("Sweep hysteresis", r["hysteresis_dec"], "decades"),
    ]


def simulate(thickness_nm=500.0, eps_r=25.0, mobility_cm2_Vs=1.0, n_t_cm3=5e15, n0_cm3=1e9,
             v=None, tfl_slope=8.0) -> Tuple[np.ndarray, np.ndarray]:
    """Piecewise SCLC curve (ohmic, trap-filling, Child) in mA/cm2 for tests
    and for the validation report."""
    v = np.logspace(-2, 1.3, 80) if v is None else np.asarray(v, float)
    L = thickness_nm * 1e-9
    eps = EPS0 * eps_r
    mu = mobility_cm2_Vs * 1e-4
    j_ohm = Q * (n0_cm3 * 1e6) * mu * v / L
    j_child = 9.0 / 8.0 * eps * mu * v ** 2 / L ** 3
    if n_t_cm3:
        v_tfl = Q * (n_t_cm3 * 1e6) * L ** 2 / (2.0 * eps)
        # steep power law that meets the Child law at V_TFL
        j_tfl = (9.0 / 8.0 * eps * mu * v_tfl ** 2 / L ** 3) * (v / v_tfl) ** tfl_slope
        j = np.maximum(j_ohm, np.minimum(j_tfl, j_child))
    else:
        j = np.maximum(j_ohm, j_child)
    return v, j / 10.0     # A/m2 -> mA/cm2
