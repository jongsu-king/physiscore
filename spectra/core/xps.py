"""XPS-specific physics: Shirley background, charge referencing, relative
sensitivity factors and atomic concentrations.

References
----------
- Shirley, Phys. Rev. B 5, 4709 (1972); Proctor & Sherwood, Anal. Chem. 54,
  13 (1982) for the iterative form.
- Scofield, J. Electron Spectrosc. Relat. Phenom. 8, 129 (1976): photo-
  ionisation cross sections at Al Kalpha (1486.6 eV), relative to C 1s = 1.
- Wagner et al., Surf. Interface Anal. 3, 211 (1981): empirical sensitivity
  factors (instrument dependent - prefer the values supplied with your
  spectrometer).
- Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020): on the limits
  of C 1s = 284.8 eV charge referencing.
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np

from scripts.common.spectral import baseline_shirley

ADVENTITIOUS_C1S_EV = 284.8

# Scofield cross sections relative to C 1s = 1.00 (Al Kalpha), full subshell
# unless the spin-orbit component is named. Indicative values; sensitivity
# factors supplied by the instrument manufacturer (which include transmission
# and escape-depth corrections) should be used for quantitative work.
SCOFIELD_RSF: Dict[str, float] = {
    "C1s": 1.00, "N1s": 1.80, "O1s": 2.93, "F1s": 4.43, "Na1s": 8.52,
    "Si2p": 0.817, "P2p": 1.19, "S2p": 1.68, "Cl2p": 2.29, "K2p": 3.98,
    "Ti2p": 7.81, "Zn2p3/2": 12.7, "Cu2p3/2": 16.7, "Ni2p3/2": 14.6,
    "Br3d": 2.84, "Sn3d5/2": 14.8, "I3d5/2": 19.9, "Cs3d5/2": 20.0,
    "Pb4f": 22.7, "Pb4f7/2": 13.0, "Bi4f7/2": 14.7, "Au4f7/2": 9.58,
    "Ag3d5/2": 10.7, "Mo3d": 9.50, "W4f7/2": 5.45,
}

# Spin-orbit splitting (eV) and area ratio (minor/major) of common doublets.
DOUBLETS: Dict[str, Dict[str, float]] = {
    "p": {"ratio": 0.5},   # p1/2 : p3/2 = 1 : 2
    "d": {"ratio": 2.0 / 3.0},
    "f": {"ratio": 3.0 / 4.0},
    "Pb4f": {"split": 4.87, "ratio": 0.75},
    "I3d": {"split": 11.5, "ratio": 2.0 / 3.0},
    "Sn3d": {"split": 8.41, "ratio": 2.0 / 3.0},
    "Ti2p": {"split": 5.7, "ratio": 0.5},
    "Zn2p": {"split": 23.1, "ratio": 0.5},
    "Cu2p": {"split": 19.8, "ratio": 0.5},
    "Ni2p": {"split": 17.3, "ratio": 0.5},
    "S2p": {"split": 1.18, "ratio": 0.5},
    "Cl2p": {"split": 1.6, "ratio": 0.5},
    "Br3d": {"split": 1.04, "ratio": 2.0 / 3.0},
    "Cs3d": {"split": 14.0, "ratio": 2.0 / 3.0},
    "Bi4f": {"split": 5.31, "ratio": 0.75},
    "Mo3d": {"split": 3.13, "ratio": 2.0 / 3.0},
    "W4f": {"split": 2.18, "ratio": 0.75},
    "Au4f": {"split": 3.67, "ratio": 0.75},
    "Ag3d": {"split": 6.0, "ratio": 2.0 / 3.0},
}


def shirley_background(binding_energy, intensity, lo: Optional[float] = None,
                       hi: Optional[float] = None, max_iter: int = 100) -> np.ndarray:
    """Iterative Shirley background on the input grid (any axis order)."""
    return baseline_shirley(binding_energy, intensity, lo=lo, hi=hi, max_iter=max_iter)


def charge_correction_shift(measured_c1s_ev: float, reference_ev: float = ADVENTITIOUS_C1S_EV) -> float:
    """Shift to ADD to every binding energy so that the adventitious C 1s
    line sits at `reference_ev` (284.8 eV by convention; see Greczynski &
    Hultman 2020 for why this is a convention and not a calibration)."""
    return float(reference_ev) - float(measured_c1s_ev)


def apply_charge_correction(binding_energy, shift_ev: float) -> np.ndarray:
    return np.asarray(binding_energy, dtype=float) + float(shift_ev)


def peak_area(binding_energy, intensity, lo: float, hi: float, background: str = "shirley") -> Dict[str, float]:
    """Integrated area of a region after background subtraction (shirley |
    linear | none). Returns area (counts·eV), the background end points and
    the number of points used."""
    x = np.asarray(binding_energy, dtype=float)
    y = np.asarray(intensity, dtype=float)
    m = (x >= min(lo, hi)) & (x <= max(lo, hi)) & np.isfinite(y)
    out = {"area": float("nan"), "n_points": int(np.sum(m)), "bg_lo": float("nan"), "bg_hi": float("nan")}
    if out["n_points"] < 5:
        return out
    xs, ys = x[m], y[m]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if background == "shirley":
        bg = baseline_shirley(xs, ys)
    elif background == "linear":
        bg = np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]])
    else:
        bg = np.zeros_like(ys)
    trap = getattr(np, "trapezoid", None) or np.trapz
    out.update(area=float(trap(np.clip(ys - bg, 0, None), xs)), bg_lo=float(bg[0]), bg_hi=float(bg[-1]))
    return out


def atomic_concentration(areas: Mapping[str, float], rsf: Optional[Mapping[str, float]] = None) -> Dict[str, float]:
    """Atomic percent from region areas: c_i = (A_i / S_i) / sum_j (A_j / S_j).

    `rsf` maps the same keys to sensitivity factors; keys missing from it
    fall back to SCOFIELD_RSF (matching on the core-level name, e.g. a key
    "O1s_oxide" uses O1s). Keys with no factor at all raise.
    """
    rsf = dict(rsf or {})
    norm: Dict[str, float] = {}
    for key, area in areas.items():
        s = rsf.get(key)
        if s is None:
            base = key.split("_")[0]
            s = SCOFIELD_RSF.get(base)
        if s is None or s <= 0:
            raise ValueError(f"no sensitivity factor for {key!r}")
        norm[key] = float(area) / float(s)
    total = sum(v for v in norm.values() if np.isfinite(v))
    if total <= 0:
        return {k: float("nan") for k in areas}
    return {k: 100.0 * v / total for k, v in norm.items()}


def doublet_parameters(line: str) -> Dict[str, float]:
    """Spin-orbit split (eV) and minor/major area ratio for a core level such
    as 'Pb4f'; falls back to the subshell ratio alone when the split is not
    tabulated. 's' levels return split 0 (singlet)."""
    if line in DOUBLETS and "split" in DOUBLETS[line]:
        return dict(DOUBLETS[line])
    sub = next((ch for ch in line if ch in "spdf"), "s")
    if sub == "s":
        return {"split": 0.0, "ratio": 0.0}
    return {"split": float("nan"), **DOUBLETS[sub]}


def kinetic_to_binding(kinetic_ev, source_ev: float = 1486.6, work_function_ev: float = 4.5) -> np.ndarray:
    """BE = h nu - KE - phi_spectrometer (Al Kalpha 1486.6 eV by default)."""
    return float(source_ev) - np.asarray(kinetic_ev, dtype=float) - float(work_function_ev)
