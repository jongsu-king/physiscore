"""Algorithmic band assignment and comparison for the Raman and FTIR windows
(3.4; replaces the Gemini requests). Built on the band library and the peak
matching of scripts.common.vibrational."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from scripts.common import vibrational as _vib
from scripts.common import interpret as _interp


def library_peak_data(peaks, technique: str) -> Dict[float, dict]:
    """peak position -> {wavenumber, material, assignment, description, confidence, other_possibilities}
    from the built-in band library (nearest entry first)."""
    out: Dict[float, dict] = {}
    pos = [float(p) for p in peaks]
    if not pos:
        return out
    tab = _vib.assign_bands(pos, technique.lower())
    for p in pos:
        sub = tab[np.isclose(tab["position"], p)]
        hits = sub[sub["assignment"].astype(str) != ""]
        if len(hits):
            b = hits.iloc[0]
            d = float(b["distance"])
            out[p] = {"wavenumber": p, "material": b["material"] or "-", "assignment": b["assignment"] or "-",
                      "description": (f"Library band at {float(b['library_position']):.0f} cm⁻¹ "
                                      f"({d:+.1f} cm⁻¹ from it). {b['note'] or ''} Indicative: confirm with the "
                                      "literature for your material.").strip(),
                      "confidence": "close (≤ 5 cm⁻¹)" if abs(d) <= 5 else "approximate",
                      "other_possibilities": "; ".join(f"{r.material} {r.assignment} ({r.library_position:.0f})"
                                                       for r in hits.iloc[1:].itertuples())}
        else:
            out[p] = {"wavenumber": p, "material": "-", "assignment": "no library match",
                      "description": "No entry of the band library within its tolerance; check the literature.",
                      "confidence": "-", "other_possibilities": ""}
    return out


def _width_at(layer: dict, position: float) -> float:
    fits = layer.get("fits")
    if fits is None or getattr(fits, "empty", True):
        return float("nan")
    cols = {c.lower(): c for c in fits.columns}
    cpos = cols.get("center") or cols.get("position")
    cw = cols.get("fwhm")
    if not cpos or not cw:
        return float("nan")
    i = int(np.argmin(np.abs(fits[cpos].to_numpy(float) - position)))
    if abs(float(fits[cpos].iloc[i]) - position) > 10:
        return float("nan")
    return float(fits[cw].iloc[i])


def pair_compare(technique: str, layer_a: dict, pa: float, layer_b: dict, pb: float) -> dict:
    """One band in two layers: shift and width change, with the usual physical readings."""
    shift = float(pb) - float(pa)
    wa, wb = _width_at(layer_a, pa), _width_at(layer_b, pb)
    raman = technique.lower() == "raman"
    if abs(shift) < 1.0:
        cause = "No significant shift (below about 1 cm⁻¹, the usual spectral resolution)."
    elif shift > 0:
        cause = ("Shift to higher wavenumber: compressive strain, a smaller lattice constant or stiffer bonds."
                 if raman else "Shift to higher wavenumber: weaker hydrogen bonding or a stronger bond.")
    else:
        cause = ("Shift to lower wavenumber: tensile strain, heating by the laser, a larger lattice or phonon "
                 "confinement in small crystallites." if raman else
                 "Shift to lower wavenumber: hydrogen bonding or coordination (e.g. C=O to a metal ion).")
    details = [f"{layer_a['name']}: {pa:.1f} cm⁻¹; {layer_b['name']}: {pb:.1f} cm⁻¹; shift {shift:+.1f} cm⁻¹."]
    if np.isfinite(wa) and np.isfinite(wb) and wa > 0:
        change = 100 * (wb - wa) / wa
        details.append(f"Width (FWHM) {wa:.1f} -> {wb:.1f} cm⁻¹ ({change:+.0f} %)" +
                       ("; broadening points to disorder or smaller crystallites." if change > 20 else
                        "; narrowing points to better crystallinity." if change < -20 else "."))
    else:
        details.append("Fit the bands (Fit bands) to compare their widths as well.")
    lib = library_peak_data([pa], technique).get(float(pa), {})
    if lib.get("assignment") not in (None, "", "no library match"):
        details.append(f"Library assignment of the band: {lib['material']} {lib['assignment']}.")
    return {"shift_value": shift, "cause": cause, "detailed_explanation": "\n".join(details),
            "summary": f"{shift:+.1f} cm⁻¹ from {layer_a['name']} to {layer_b['name']}. {cause}"}


def spectra_compare(technique: str, layer_a: dict, layer_b: dict, tolerance: float = 8.0) -> dict:
    """Whole band lists: matched bands with their shifts, new bands, vanished bands."""
    tab = _vib.peak_shift_table(list(layer_b.get("peaks", [])), list(layer_a.get("peaks", [])), tolerance,
                                reference_name=layer_b["name"], sample_name=layer_a["name"])
    matched = tab.dropna(subset=["shift"])
    new = tab[tab["reference"].isna()]["sample"].dropna()
    gone = tab[tab["sample"].isna()]["reference"].dropna()
    diffs: List[str] = []
    for _, r in matched.iterrows():
        if abs(float(r["shift"])) >= 2:
            diffs.append(f"{float(r['reference']):.0f} -> {float(r['sample']):.0f} cm⁻¹ ({float(r['shift']):+.1f})")
    diffs += [f"new band at {float(v):.0f} cm⁻¹ in {layer_a['name']}" for v in new]
    diffs += [f"band at {float(v):.0f} cm⁻¹ of {layer_b['name']} absent in {layer_a['name']}" for v in gone]
    mean_shift = float(matched["shift"].mean()) if len(matched) else float("nan")
    summary = (f"{len(matched)} bands in common (mean shift {mean_shift:+.1f} cm⁻¹), {len(new)} new, "
               f"{len(gone)} absent, comparing {layer_a['name']} with {layer_b['name']} "
               f"(tolerance {tolerance:g} cm⁻¹).")
    return {"summary": summary, "differences": diffs or ["no shift of 2 cm⁻¹ or more and no new or missing band"],
            "table": tab}


def interpret_layers(technique: str, layers: List[dict], target: int, reference: Optional[int] = None):
    """Report for the target layer: bands, library assignments, shifts against the reference layer."""
    L = layers[target]
    peaks = [float(p) for p in L.get("peaks", [])]
    data = L.get("peak_data") or library_peak_data(peaks, technique)
    assignments = [{"position": p, "material": v.get("material"), "mode": v.get("assignment"),
                    "library": "-", "distance": float("nan")}
                   for p, v in data.items() if v.get("assignment") not in (None, "", "no library match", "-")]
    shifts = []
    if reference is not None and reference != target and 0 <= reference < len(layers):
        R = layers[reference]
        tab = _vib.peak_shift_table(list(R.get("peaks", [])), peaks)
        for _, r in tab.dropna(subset=["shift"]).iterrows():
            wa, wb = _width_at(R, float(r["reference"])), _width_at(L, float(r["sample"]))
            shifts.append({"reference": r["reference"], "shift": r["shift"],
                           "width_change": 100 * (wb - wa) / wa if np.isfinite(wa) and np.isfinite(wb) and wa > 0
                           else float("nan")})
    return _interp.interpret_vibrational(technique, peaks, assignments, shifts, subject=L.get("name", ""))
