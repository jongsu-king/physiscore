"""Cross-technique device summary (GUI-free).

The point of analysing J-V, EQE, absorbance and PL in one program is that
quantities measurable by more than one technique can be checked against each
other. This module takes the results the individual cores already produce and
derives the consistency checks and detailed-balance figures a device paper
reports:

* Jsc from J-V versus the AM1.5G-integrated EQE (spectral mismatch, area or
  intensity errors show up here);
* the band gap from EQE (derivative distribution), from absorbance (Tauc) and
  from the PL peak, with their spread;
* the open-circuit voltage against Voc,rad and Voc,SQ: the radiative and
  non-radiative losses and the implied electroluminescence yield;
* FF and PCE as fractions of their Shockley-Queisser values.

Nothing here re-reads files; callers pass the parsed quantities so the same
code serves the GUI, the CLI and tests.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from scripts.EQE import eqe_core
from scripts.JV.jv_core import jsc_mismatch

K_B, Q_E = eqe_core.K_B, eqe_core.Q_E


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def summarize_device(jv: Optional[Dict[str, float]] = None,
                     eqe_wavelength_nm: Optional[Sequence[float]] = None,
                     eqe_values: Optional[Sequence[float]] = None,
                     eg_abs_ev: Optional[float] = None,
                     pl_peak_ev: Optional[float] = None,
                     temperature_k: float = 300.0,
                     diode_fit: Optional[Dict[str, float]] = None,
                     mismatch_warn_percent: float = 5.0,
                     eg_spread_warn_mev: float = 60.0) -> Dict[str, object]:
    """Combine the per-technique results of one device.

    jv          dict from compute_jv_parameters (Voc, Jsc, FF, PCE, Rs, Rsh ...)
    eqe_*       the EQE spectrum (nm, % or fraction) of the same device
    eg_abs_ev   Tauc band gap of the absorber film (optional)
    pl_peak_ev  PL peak energy, Jacobian-corrected (optional)
    diode_fit   dict from fit_single_diode (optional; copied into the summary)

    Returns a flat dict of quantities plus 'warnings' (list of str) and
    'notes' (list of str). NaN marks what could not be derived.
    """
    out: Dict[str, object] = {"temperature_K": float(temperature_k)}
    warnings, notes = [], []

    # --- J-V ---------------------------------------------------------------
    voc = jsc_jv = ff = pce = float("nan")
    if jv:
        voc = float(jv.get("Voc", float("nan")))
        jsc_jv = float(jv.get("Jsc", float("nan")))
        ff = float(jv.get("FF", float("nan")))
        pce = float(jv.get("PCE", float("nan")))
        for k in ("Voc", "Jsc", "FF", "PCE", "Vmpp", "Jmpp", "Pmax", "Rs", "Rsh"):
            if k in jv:
                out[f"JV_{k}"] = float(jv[k])
    if diode_fit and diode_fit.get("success"):
        for k in ("Jph", "J0", "n", "Rs", "Rsh", "R2"):
            out[f"diode_{k}"] = float(diode_fit[k])

    # --- EQE ---------------------------------------------------------------
    eg_eqe = eg_sigma = jsc_eqe = voc_rad = j0_rad = eu = float("nan")
    if eqe_wavelength_nm is not None and eqe_values is not None and len(eqe_wavelength_nm) > 5:
        r = eqe_core.analyze_eqe(eqe_wavelength_nm, eqe_values, temperature_k=temperature_k,
                                 voc_measured_v=voc if _finite(voc) else None)
        jsc_eqe, eg_eqe, eg_sigma = r["Jsc_mA_cm2"], r["Eg_Rau_eV"], r["Eg_sigma_eV"]
        voc_rad, j0_rad, eu = r["Voc_rad_V"], r["J0_rad_mA_cm2"], r["Eu_meV"]
        out.update({"EQE_Jsc": jsc_eqe, "EQE_Eg": eg_eqe, "EQE_Eg_sigma_meV": 1000 * eg_sigma if _finite(eg_sigma) else float("nan"),
                    "EQE_Eu_meV": eu, "EQE_J0_rad": j0_rad, "EQE_Voc_rad": voc_rad,
                    "EQE_tail_extended": bool(r.get("tail_extended", False))})
        if _finite(r.get("Eg_inflection_eV")):
            out["EQE_Eg_inflection"] = r["Eg_inflection_eV"]

    # --- Jsc mismatch ------------------------------------------------------
    mm = jsc_mismatch(jsc_jv, jsc_eqe)
    out["Jsc_mismatch_percent"] = mm
    if _finite(mm) and abs(mm) > mismatch_warn_percent:
        warnings.append(f"Jsc from J-V and from EQE differ by {mm:+.1f} % (threshold {mismatch_warn_percent:g} %): "
                        "check the spectral mismatch factor, the device area and the lamp intensity.")

    # --- band gaps ---------------------------------------------------------
    gaps = {"EQE (dEQE/dE)": eg_eqe, "Absorbance (Tauc)": eg_abs_ev, "PL peak": pl_peak_ev}
    valid = {k: float(v) for k, v in gaps.items() if _finite(v)}
    out["Eg_Abs"] = float(eg_abs_ev) if _finite(eg_abs_ev) else float("nan")
    out["Eg_PL"] = float(pl_peak_ev) if _finite(pl_peak_ev) else float("nan")
    if valid:
        eg_ref = valid.get("EQE (dEQE/dE)", next(iter(valid.values())))
        out["Eg_reference"] = eg_ref
        out["Eg_reference_source"] = "EQE (dEQE/dE)" if "EQE (dEQE/dE)" in valid else next(iter(valid))
        if len(valid) > 1:
            spread = 1000.0 * (max(valid.values()) - min(valid.values()))
            out["Eg_spread_meV"] = spread
            if spread > eg_spread_warn_mev:
                warnings.append(f"Band gaps from {', '.join(valid)} differ by {spread:.0f} meV "
                                f"(threshold {eg_spread_warn_mev:g} meV).")
        if _finite(pl_peak_ev) and _finite(eg_eqe):
            out["Stokes_shift_meV"] = 1000.0 * (eg_eqe - float(pl_peak_ev))
            notes.append("Stokes shift = Eg(EQE) - E(PL peak); a PL peak below the absorption edge is expected, "
                         "a large shift points to tail states or self-absorption.")
    else:
        eg_ref = float("nan")

    # --- detailed balance against the reference gap -------------------------
    if _finite(eg_ref):
        sq = eqe_core.shockley_queisser(eg_ref, temperature_k)
        out.update({"SQ_Jsc": sq["Jsc_SQ"], "SQ_Voc": sq["Voc_SQ"], "SQ_FF": sq["FF_SQ"], "SQ_PCE": sq["PCE_SQ"]})
        if _finite(jsc_jv) and sq["Jsc_SQ"] > 0:
            out["Jsc_fraction_of_SQ"] = jsc_jv / sq["Jsc_SQ"]
        if _finite(ff) and sq["FF_SQ"] > 0:
            out["FF_fraction_of_SQ"] = (ff / 100.0) / sq["FF_SQ"]
        if _finite(pce) and sq["PCE_SQ"] > 0:
            out["PCE_fraction_of_SQ"] = pce / sq["PCE_SQ"]
        if _finite(voc):
            vl = eqe_core.voltage_losses(eg_ref, voc, voc_rad, temperature_k)
            out.update({"Voc_deficit": vl["dV_total"], "dV1_SQ": vl["dV1_SQ"], "dV2_rad": vl["dV2_rad"],
                        "dV3_nonrad": vl["dV3_nonrad"], "EQE_EL": vl["EQE_EL"]})
            if _finite(vl["dV3_nonrad"]):
                notes.append("Non-radiative voltage loss dV3 = Voc,rad - Voc; EQE_EL = exp(-q dV3/kT) is the "
                             "electroluminescence yield implied by it (Rau 2007).")
            if _finite(voc) and _finite(sq["Voc_SQ"]) and voc > sq["Voc_SQ"] + 0.01:
                warnings.append("Voc exceeds the Shockley-Queisser value for this band gap: the gap or the "
                                "temperature is probably wrong.")
    out["warnings"] = warnings
    out["notes"] = notes
    return out


def summary_table(summary: Dict[str, object]) -> pd.DataFrame:
    """Readable table (Quantity, Value, Unit, Origin) of a summarize_device result."""
    rows = []

    def add(key, label, unit, origin, fmt=".4g"):
        v = summary.get(key)
        if v is None:
            return
        if isinstance(v, bool):
            txt = "yes" if v else "no"
        elif isinstance(v, (int, float, np.floating)):
            if not math.isfinite(float(v)):
                return
            txt = format(float(v), fmt)
        else:
            txt = str(v)
        rows.append({"Quantity": label, "Value": txt, "Unit": unit, "Origin": origin})

    add("JV_Voc", "Voc", "V", "J-V curve", ".4f")
    add("JV_Jsc", "Jsc", "mA/cm²", "J-V curve", ".3f")
    add("EQE_Jsc", "Jsc, AM1.5G-integrated EQE", "mA/cm²", "EQE", ".3f")
    add("Jsc_mismatch_percent", "Jsc mismatch (J-V vs EQE)", "%", "cross-check", "+.2f")
    add("JV_FF", "Fill factor", "%", "J-V curve", ".2f")
    add("JV_PCE", "PCE", "%", "J-V curve", ".3f")
    add("JV_Rs", "Rs (slope at Voc)", "Ω cm²", "J-V curve", ".2f")
    add("JV_Rsh", "Rsh (slope at Jsc)", "Ω cm²", "J-V curve", ".1f")
    add("diode_n", "Ideality factor n", "-", "one-diode fit", ".3f")
    add("diode_J0", "J0", "mA/cm²", "one-diode fit", ".3e")
    add("diode_Rs", "Rs", "Ω cm²", "one-diode fit", ".3f")
    add("diode_Rsh", "Rsh", "Ω cm²", "one-diode fit", ".1f")
    add("EQE_Eg", "Band gap, dEQE/dE distribution", "eV", "EQE", ".4f")
    add("EQE_Eg_sigma_meV", "Edge width sigma", "meV", "EQE", ".0f")
    add("Eg_Abs", "Band gap, Tauc", "eV", "Absorbance", ".4f")
    add("Eg_PL", "PL peak energy", "eV", "PL", ".4f")
    add("Eg_spread_meV", "Spread of the band-gap values", "meV", "cross-check", ".0f")
    add("Stokes_shift_meV", "Stokes shift", "meV", "EQE - PL", ".0f")
    add("EQE_Eu_meV", "Urbach energy", "meV", "EQE", ".1f")
    add("EQE_J0_rad", "J0,rad", "mA/cm²", "EQE detailed balance", ".3e")
    add("EQE_Voc_rad", "Voc,rad", "V", "EQE detailed balance", ".4f")
    add("Eg_reference", "Reference gap for the SQ limit", "eV", summary.get("Eg_reference_source", ""), ".4f")
    add("SQ_Jsc", "Jsc, SQ limit", "mA/cm²", "detailed balance", ".2f")
    add("SQ_Voc", "Voc, SQ limit", "V", "detailed balance", ".4f")
    add("SQ_FF", "FF, SQ limit", "-", "detailed balance", ".3f")
    add("SQ_PCE", "PCE, SQ limit", "%", "detailed balance", ".2f")
    add("Jsc_fraction_of_SQ", "Jsc / Jsc,SQ", "-", "cross-check", ".3f")
    add("FF_fraction_of_SQ", "FF / FF,SQ", "-", "cross-check", ".3f")
    add("PCE_fraction_of_SQ", "PCE / PCE,SQ", "-", "cross-check", ".3f")
    add("Voc_deficit", "Voc deficit Eg/q - Voc", "V", "cross-check", ".3f")
    add("dV1_SQ", "dV1 = Eg/q - Voc,SQ", "V", "detailed balance", ".3f")
    add("dV2_rad", "dV2 = Voc,SQ - Voc,rad", "V", "detailed balance", ".3f")
    add("dV3_nonrad", "dV3 = Voc,rad - Voc (non-radiative)", "V", "detailed balance", ".3f")
    add("EQE_EL", "EQE_EL implied by dV3", "-", "detailed balance", ".2e")
    return pd.DataFrame(rows, columns=["Quantity", "Value", "Unit", "Origin"])


def loss_breakdown(summary: Dict[str, object]) -> Dict[str, float]:
    """The three voltage-loss terms as a dict ready for a bar chart."""
    return {k: float(summary.get(src, float("nan")))
            for k, src in (("Thermodynamic (Eg/q - Voc,SQ)", "dV1_SQ"),
                           ("Radiative tail (Voc,SQ - Voc,rad)", "dV2_rad"),
                           ("Non-radiative (Voc,rad - Voc)", "dV3_nonrad"))}
