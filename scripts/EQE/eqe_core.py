"""EQE physics (GUI-free).

Jsc integration against the bundled ASTM G173-03 AM1.5G spectrum, band-gap
determination from the EQE edge (Rau's derivative-distribution method and the
inflection point), the Urbach energy, and the detailed-balance quantities a
device paper reports next to them: the radiative saturation current J0,rad,
the radiative open-circuit voltage Voc,rad, the Shockley-Queisser limits for
the extracted gap, and the decomposition of the open-circuit voltage deficit
into its thermodynamic, radiative and non-radiative parts.

References
----------
- ASTM G173-03, Standard Tables for Reference Solar Spectral Irradiances.
- Rau, Blank, Mueller & Kirchartz, Phys. Rev. Applied 7, 044016 (2017):
  Eg from the derivative distribution P(E) = dEQE/dE, Voc,rad, non-radiative
  loss.
- Shockley & Queisser, J. Appl. Phys. 32, 510 (1961); Rühle, Sol. Energy
  130, 139 (2016) for tabulated SQ values.
- Green, Solid-State Electron. 24, 788 (1981): empirical fill-factor formula.
- Vandewal et al., Nat. Mater. 8, 904 (2009); Urbach, Phys. Rev. 92, 1324
  (1953): sub-gap exponential tail.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

H_PLANCK = 6.62607015e-34      # J s
C_LIGHT = 299792458.0          # m/s
Q_E = 1.602176634e-19          # C
K_B = 1.380649e-23             # J/K
HC_EV_NM = 1239.84198          # eV nm

_AM15G_CACHE: Optional[Tuple[np.ndarray, np.ndarray]] = None


# ---------------------------------------------------------------------------
# Reference spectrum
# ---------------------------------------------------------------------------
def get_am15g_spectrum() -> Tuple[np.ndarray, np.ndarray]:
    """(wavelength_nm, spectral irradiance W m^-2 nm^-1) of ASTM G173-03
    global tilt, full resolution (2002 points, 280-4000 nm, integral
    1000.4 W/m^2). Falls back to a coarse 10 nm table if the bundled CSV is
    missing."""
    global _AM15G_CACHE
    if _AM15G_CACHE is not None:
        return _AM15G_CACHE
    csv_path = Path(__file__).resolve().parent / "astm_g173_global.csv"
    try:
        arr = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
        wl = arr[:, 0].astype(float)
        irr = arr[:, 1].astype(float)
        ok = np.isfinite(wl) & np.isfinite(irr)
        wl, irr = wl[ok], irr[ok]
        if len(wl) > 100:
            _AM15G_CACHE = (wl, irr)
            return _AM15G_CACHE
    except Exception:
        pass
    am15_values = np.array([
        0.00102, 0.05094, 0.20527, 0.47139, 0.5018, 0.52798, 0.59817, 0.75507,
        0.70077, 0.79699, 1.1141, 1.0485, 1.1232, 0.87462, 1.3499, 1.5595,
        1.5291, 1.5077, 1.6181, 1.6224, 1.5451, 1.5481, 1.5236, 1.5446,
        1.4825, 1.5399, 1.474, 1.4816, 1.502, 1.3709, 1.4753, 1.4686,
        1.4739, 1.3924, 1.434, 1.3594, 1.3992, 1.4196, 1.3969, 1.1821,
        1.2823, 1.3175, 0.9855, 1.1285, 1.2195, 1.2341, 0.26604, 1.1608,
        1.1636, 1.091, 1.0725, 1.0559, 0.86188, 0.91601, 1.0157, 0.89372,
        0.98816, 0.96755, 0.93957, 0.92393, 0.7426, 0.62467, 0.74414,
        0.4321, 0.47181, 0.14726, 0.42066, 0.63461, 0.60468, 0.73227,
        0.73532], dtype=float)
    wl = 290 + 10 * np.arange(len(am15_values), dtype=float)
    _AM15G_CACHE = (wl, am15_values)
    return _AM15G_CACHE


def am15g_photon_flux_per_ev() -> Tuple[np.ndarray, np.ndarray]:
    """AM1.5G photon flux density per unit photon energy:
    (energy_eV ascending, photons m^-2 s^-1 eV^-1)."""
    wl, irr = get_am15g_spectrum()
    e_ev = HC_EV_NM / wl
    e_j = e_ev * Q_E
    # irradiance per nm -> per eV: |dlambda/dE| = hc/E^2 ; lambda in nm, E in eV
    irr_per_ev = irr * HC_EV_NM / e_ev ** 2               # W m^-2 eV^-1
    flux = irr_per_ev / e_j                                 # photons m^-2 s^-1 eV^-1
    order = np.argsort(e_ev)
    return e_ev[order], flux[order]


def eqe_to_fraction(eqe) -> np.ndarray:
    """Percent -> fraction when the maximum exceeds 1.5 (a single-junction
    EQE fraction cannot reach that; percent data typically peaks at 20-95)."""
    eqe = np.asarray(eqe, dtype=float)
    if eqe.size == 0 or not np.any(np.isfinite(eqe)):
        return eqe
    return eqe / 100.0 if np.nanmax(eqe) > 1.5 else eqe


def _trapz(y, x):
    f = getattr(np, "trapezoid", None) or np.trapz
    return float(f(y, x=x))


# ---------------------------------------------------------------------------
# Jsc
# ---------------------------------------------------------------------------
def compute_am15_integrals(wavelength_nm, eqe):
    """(AM1.5G interpolated to the EQE grid, Jsc integrand [mA cm^-2 nm^-1],
    cumulative Jsc [mA cm^-2]) - what the EQE panel plots on its right axis."""
    am15_lam, am15_irr = get_am15g_spectrum()
    wl = np.asarray(wavelength_nm, dtype=float)
    eqe_frac = eqe_to_fraction(eqe)
    am15_interp = np.interp(wl, am15_lam, am15_irr, left=0.0, right=0.0)
    d = wl * eqe_frac * am15_interp / HC_EV_NM * 0.1          # mA cm^-2 nm^-1
    e_cum = np.zeros_like(d, dtype=float)
    if len(wl) >= 2:
        order = np.argsort(wl)
        ds, wls = d[order], wl[order]
        es = np.zeros_like(ds)
        es[1:] = np.cumsum(0.5 * (ds[1:] + ds[:-1]) * np.diff(wls))
        e_cum[order] = es
    return am15_interp, d, e_cum


def calculate_jsc(wavelength_nm, eqe) -> float:
    """Jsc [mA/cm^2] = q * Int EQE(l) * Phi_AM1.5G(l) dl over the overlap of
    the data and the reference spectrum, integrated on the union of both
    wavelength grids so neither resolution is lost."""
    am15_lam, am15_irr = get_am15g_spectrum()
    wl = np.asarray(wavelength_nm, dtype=float)
    frac = eqe_to_fraction(eqe)
    ok = np.isfinite(wl) & np.isfinite(frac)
    wl, frac = wl[ok], frac[ok]
    if len(wl) < 2:
        return float("nan")
    order = np.argsort(wl)
    wl, frac = wl[order], frac[order]
    lo, hi = max(wl.min(), am15_lam.min()), min(wl.max(), am15_lam.max())
    if lo >= hi:
        return float("nan")
    grid = np.union1d(wl, am15_lam)
    grid = grid[(grid >= lo) & (grid <= hi)]
    eqe_i = np.interp(grid, wl, frac)
    irr_i = np.interp(grid, am15_lam, am15_irr)
    photon_energy = H_PLANCK * C_LIGHT / (grid * 1e-9)
    flux = irr_i / photon_energy                       # photons s^-1 m^-2 nm^-1
    return Q_E * _trapz(eqe_i * flux, grid) * 0.1      # A/m^2 -> mA/cm^2


# ---------------------------------------------------------------------------
# Band gap from the EQE edge
# ---------------------------------------------------------------------------
def _edge_derivative(energy_ev, eqe):
    e = np.asarray(energy_ev, dtype=float)
    q = eqe_to_fraction(eqe)
    ok = np.isfinite(e) & np.isfinite(q)
    e, q = e[ok], q[ok]
    order = np.argsort(e)
    e, q = e[order], q[order]
    eu, inv = np.unique(e, return_inverse=True)
    if len(eu) != len(e):
        q = np.bincount(inv, weights=q) / np.maximum(np.bincount(inv), 1)
        e = eu
    if len(e) < 5:
        return e, q, np.array([])
    return e, q, np.gradient(q, e)


def bandgap_inflection(energy_ev, eqe, e_min: Optional[float] = None,
                       e_max: Optional[float] = None) -> float:
    """Eg as the energy of the steepest rise of the absorption edge
    (maximum of dEQE/dE on the low-energy side of the EQE maximum)."""
    e, q, dq = _edge_derivative(energy_ev, eqe)
    if dq.size == 0:
        return float("nan")
    m = np.ones_like(e, dtype=bool)
    if e_min is not None:
        m &= e >= e_min
    if e_max is not None:
        m &= e <= e_max
    m &= e <= e[int(np.argmax(q))]
    if not np.any(m):
        return float("nan")
    return float(e[int(np.argmax(np.where(m, dq, -np.inf)))])


def bandgap_rau(energy_ev, eqe, threshold: float = 0.5) -> Dict[str, float]:
    """Band gap from the derivative distribution P(E) = dEQE/dE (Rau et al.
    2017): Eg = Int E P(E) dE / Int P(E) dE over the connected region around
    the maximum of P where P exceeds `threshold` x P_max (50% by default).

    Returns Eg, sigma (standard deviation of P over that region, a measure of
    the edge broadening), E_lo/E_hi (the integration window) and E_inflection.
    """
    out = {"Eg": float("nan"), "sigma": float("nan"), "E_lo": float("nan"),
           "E_hi": float("nan"), "E_inflection": float("nan")}
    e, q, dq = _edge_derivative(energy_ev, eqe)
    if dq.size == 0:
        return out
    # low-energy side of the EQE maximum only
    i_peak = int(np.argmax(q))
    side = np.arange(len(e)) <= i_peak
    p = np.where(side, dq, -np.inf)
    i0 = int(np.argmax(p))
    if not np.isfinite(p[i0]) or p[i0] <= 0:
        return out
    cut = threshold * p[i0]
    lo = i0
    while lo > 0 and dq[lo - 1] >= cut:
        lo -= 1
    hi = i0
    while hi < len(e) - 1 and dq[hi + 1] >= cut and hi + 1 <= i_peak:
        hi += 1
    if hi - lo < 2:
        lo, hi = max(lo - 1, 0), min(hi + 1, len(e) - 1)
    ew, pw = e[lo:hi + 1], np.clip(dq[lo:hi + 1], 0, None)
    norm = _trapz(pw, ew)
    if norm <= 0:
        return out
    eg = _trapz(ew * pw, ew) / norm
    var = _trapz((ew - eg) ** 2 * pw, ew) / norm
    out.update(Eg=float(eg), sigma=float(math.sqrt(max(var, 0.0))), E_lo=float(ew[0]),
               E_hi=float(ew[-1]), E_inflection=float(e[i0]))
    return out


def urbach_energy(energy_ev, eqe, e_lo: float, e_hi: float) -> Dict[str, float]:
    """Urbach energy from ln(EQE) = ln(EQE_0) + (E - E_0)/E_u in [e_lo, e_hi]:
    Eu [meV] = 1000 / slope. Also returns the fit R^2 and the number of
    points used."""
    out = {"Eu_meV": float("nan"), "slope": float("nan"), "intercept": float("nan"),
           "R2": float("nan"), "n_points": 0}
    e = np.asarray(energy_ev, dtype=float)
    q = eqe_to_fraction(eqe)
    m = np.isfinite(e) & np.isfinite(q) & (q > 0) & (e >= min(e_lo, e_hi)) & (e <= max(e_lo, e_hi))
    if int(np.sum(m)) < 3:
        return out
    x, y = e[m], np.log(q[m])
    slope, intercept = np.polyfit(x, y, 1)
    if slope <= 0:
        return out
    yhat = slope * x + intercept
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    out.update(Eu_meV=1000.0 / float(slope), slope=float(slope), intercept=float(intercept),
               R2=1.0 - float(np.sum((y - yhat) ** 2)) / ss_tot if ss_tot > 0 else float("nan"),
               n_points=int(len(x)))
    return out


def auto_urbach_window(energy_ev, eqe, lo_frac: float = 0.01, hi_frac: float = 0.3) -> Tuple[float, float]:
    """Energy window of the exponential sub-gap tail: the low-energy side of
    the edge where EQE lies between lo_frac and hi_frac of its maximum."""
    e, q, _ = _edge_derivative(energy_ev, eqe)
    if len(e) < 5:
        return float("nan"), float("nan")
    i_peak = int(np.argmax(q))
    qmax = q[i_peak]
    m = (np.arange(len(e)) <= i_peak) & (q > lo_frac * qmax) & (q < hi_frac * qmax)
    if int(np.sum(m)) < 3:
        return float("nan"), float("nan")
    return float(e[m].min()), float(e[m].max())


# ---------------------------------------------------------------------------
# Detailed balance
# ---------------------------------------------------------------------------
def blackbody_photon_flux(energy_ev, temperature_k: float = 300.0) -> np.ndarray:
    """Photon flux of a black body at T emitted into a hemisphere, per unit
    energy: Phi_BB(E) = 2 pi E^2 / (h^3 c^2) / (exp(E/kT) - 1)
    [photons m^-2 s^-1 eV^-1]."""
    e = np.asarray(energy_ev, dtype=float) * Q_E
    kt = K_B * temperature_k
    with np.errstate(over="ignore"):
        denom = np.expm1(np.clip(e / kt, 1e-12, 700.0))
    per_joule = 2.0 * math.pi * e ** 2 / (H_PLANCK ** 3 * C_LIGHT ** 2) / denom
    return per_joule * Q_E


def radiative_limit(energy_ev, eqe, temperature_k: float = 300.0,
                    extend_tail: bool = True, jsc_mA_cm2: Optional[float] = None) -> Dict[str, float]:
    """J0,rad and Voc,rad from the measured EQE (Rau 2007; Rau et al. 2017).

        J0,rad = q Int EQE(E) Phi_BB(E, T) dE
        Voc,rad = (kT/q) ln(Jsc / J0,rad + 1)

    Phi_BB falls exponentially with energy, so J0,rad is dominated by the
    lowest energies where EQE is still measurable. With `extend_tail` the
    exponential (Urbach) tail fitted below the edge is extrapolated down to
    E = Eg - 0.6 eV so a finite measurement window does not truncate the
    integral; without it only measured points are used.
    `jsc_mA_cm2` defaults to the AM1.5G-integrated value of the same EQE.
    """
    out = {"J0_rad_mA_cm2": float("nan"), "Voc_rad_V": float("nan"), "Jsc_mA_cm2": float("nan"),
           "tail_extended": False, "Eu_meV": float("nan")}
    e, q, _ = _edge_derivative(energy_ev, eqe)
    if len(e) < 5:
        return out
    if jsc_mA_cm2 is None:
        jsc_mA_cm2 = calculate_jsc(HC_EV_NM / e, q)
    out["Jsc_mA_cm2"] = float(jsc_mA_cm2)
    e_int, q_int = e, np.clip(q, 0, None)
    if extend_tail:
        lo, hi = auto_urbach_window(e, q)
        if np.isfinite(lo):
            urb = urbach_energy(e, q, lo, hi)
            if np.isfinite(urb["Eu_meV"]) and urb["R2"] > 0.9:
                e_ext = np.linspace(max(lo - 0.6, 0.3), lo, 400, endpoint=False)
                q_ext = np.exp(urb["slope"] * e_ext + urb["intercept"])
                keep = e > lo
                e_int = np.concatenate([e_ext, e[keep]])
                q_int = np.concatenate([q_ext, np.clip(q[keep], 0, None)])
                out["tail_extended"] = True
                out["Eu_meV"] = urb["Eu_meV"]
    flux = blackbody_photon_flux(e_int, temperature_k)
    j0 = Q_E * _trapz(q_int * flux, e_int) * 0.1            # mA/cm^2
    out["J0_rad_mA_cm2"] = float(j0)
    if j0 > 0 and np.isfinite(jsc_mA_cm2) and jsc_mA_cm2 > 0:
        vt = K_B * temperature_k / Q_E
        out["Voc_rad_V"] = float(vt * math.log(jsc_mA_cm2 / j0 + 1.0))
    return out


def green_fill_factor(voc_v: float, temperature_k: float = 300.0, n: float = 1.0) -> float:
    """Green's empirical FF for an ideal diode: FF = (v - ln(v + 0.72))/(v + 1),
    v = Voc/(n kT/q). Accurate to a few 0.1% for v > 10."""
    vt = n * K_B * temperature_k / Q_E
    v = voc_v / vt
    if v <= 0:
        return float("nan")
    return float((v - math.log(v + 0.72)) / (v + 1.0))


def shockley_queisser(eg_ev: float, temperature_k: float = 300.0) -> Dict[str, float]:
    """Detailed-balance limit for a step-function absorber with gap Eg under
    AM1.5G: Jsc_SQ, J0_SQ, Voc_SQ, FF_SQ (Green formula) and PCE_SQ with
    P_in = 1000 W/m^2 (the ASTM G173 integral is 1000.4)."""
    out = {k: float("nan") for k in ("Jsc_SQ", "J0_SQ", "Voc_SQ", "FF_SQ", "PCE_SQ")}
    if not np.isfinite(eg_ev) or eg_ev <= 0.3:
        return out
    e_sun, flux_sun = am15g_photon_flux_per_ev()
    m = e_sun >= eg_ev
    if int(np.sum(m)) < 2:
        return out
    jsc = Q_E * _trapz(flux_sun[m], e_sun[m]) * 0.1
    e_bb = np.linspace(eg_ev, eg_ev + 1.5, 3000)
    j0 = Q_E * _trapz(blackbody_photon_flux(e_bb, temperature_k), e_bb) * 0.1
    vt = K_B * temperature_k / Q_E
    voc = vt * math.log(jsc / j0 + 1.0) if j0 > 0 else float("nan")
    ff = green_fill_factor(voc, temperature_k)
    out.update(Jsc_SQ=float(jsc), J0_SQ=float(j0), Voc_SQ=float(voc), FF_SQ=float(ff),
               PCE_SQ=float(jsc * voc * ff))     # mA/cm^2 * V = mW/cm^2 -> % of 100 mW/cm^2
    return out


def voltage_losses(eg_ev: float, voc_measured_v: float, voc_rad_v: float,
                   temperature_k: float = 300.0) -> Dict[str, float]:
    """Decompose the open-circuit voltage deficit Eg/q - Voc into
        dV1 = Eg/q - Voc,SQ    (thermodynamic, radiative, step absorber)
        dV2 = Voc,SQ - Voc,rad (radiative loss from the non-step edge / tail)
        dV3 = Voc,rad - Voc    (non-radiative recombination)
    and the electroluminescence quantum efficiency implied by dV3,
    EQE_EL = exp(-q dV3 / kT) (Rau 2007)."""
    out = {k: float("nan") for k in ("Eg_over_q", "Voc_SQ", "dV_total", "dV1_SQ", "dV2_rad", "dV3_nonrad", "EQE_EL")}
    sq = shockley_queisser(eg_ev, temperature_k)
    if not np.isfinite(sq["Voc_SQ"]):
        return out
    vt = K_B * temperature_k / Q_E
    out["Eg_over_q"] = float(eg_ev)
    out["Voc_SQ"] = sq["Voc_SQ"]
    out["dV1_SQ"] = float(eg_ev - sq["Voc_SQ"])
    if np.isfinite(voc_rad_v):
        out["dV2_rad"] = float(sq["Voc_SQ"] - voc_rad_v)
        if np.isfinite(voc_measured_v):
            out["dV3_nonrad"] = float(voc_rad_v - voc_measured_v)
            out["EQE_EL"] = float(math.exp(-out["dV3_nonrad"] / vt)) if out["dV3_nonrad"] > -5 * vt else float("nan")
    if np.isfinite(voc_measured_v):
        out["dV_total"] = float(eg_ev - voc_measured_v)
    return out


def analyze_eqe(wavelength_nm, eqe, temperature_k: float = 300.0,
                voc_measured_v: Optional[float] = None) -> Dict[str, float]:
    """One call that returns everything the EQE panel and the CLI report:
    Jsc, Eg (Rau, inflection), edge width sigma, Urbach energy (auto window),
    J0,rad, Voc,rad, the SQ limits for Eg and the voltage-loss breakdown
    (when Voc is given)."""
    wl = np.asarray(wavelength_nm, dtype=float)
    q = eqe_to_fraction(eqe)
    ok = np.isfinite(wl) & np.isfinite(q) & (wl > 0)
    wl, q = wl[ok], q[ok]
    e = HC_EV_NM / wl
    res: Dict[str, float] = {"Jsc_mA_cm2": calculate_jsc(wl, q)}
    rau = bandgap_rau(e, q)
    res.update({"Eg_Rau_eV": rau["Eg"], "Eg_sigma_eV": rau["sigma"],
                "Eg_inflection_eV": rau["E_inflection"],
                "Eg_window_lo_eV": rau["E_lo"], "Eg_window_hi_eV": rau["E_hi"]})
    lo, hi = auto_urbach_window(e, q)
    urb = urbach_energy(e, q, lo, hi) if np.isfinite(lo) else {"Eu_meV": float("nan"), "R2": float("nan")}
    res.update({"Eu_meV": urb["Eu_meV"], "Eu_R2": urb["R2"], "Eu_window_lo_eV": lo, "Eu_window_hi_eV": hi})
    rad = radiative_limit(e, q, temperature_k, jsc_mA_cm2=res["Jsc_mA_cm2"])
    res.update({"J0_rad_mA_cm2": rad["J0_rad_mA_cm2"], "Voc_rad_V": rad["Voc_rad_V"],
                "tail_extended": rad["tail_extended"]})
    eg = rau["Eg"] if np.isfinite(rau["Eg"]) else rau["E_inflection"]
    sq = shockley_queisser(eg, temperature_k)
    res.update(sq)
    if voc_measured_v is not None:
        res.update(voltage_losses(eg, float(voc_measured_v), rad["Voc_rad_V"], temperature_k))
    return res
