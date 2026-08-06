"""Regenerate the quantitative validation table.

Every row compares a parameter recovered by Physiscore against the value that
was put into a closed-form model, so the deviation column is the extraction
error and nothing else. Run from the project root:

    python tools/validation_report.py            # markdown to stdout
    python tools/validation_report.py --csv      # machine-readable
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from conftest import (dark_diode_jv, gaussian, pseudo_voigt,  # noqa: E402
                      single_diode_jv, single_diode_reference)
from scripts.Dark_JV.dark_jv_core import analyze_dark_diode  # noqa: E402
from scripts.JV.jv_core import compute_jv_parameters  # noqa: E402
from scripts.PL.pl_core import fit_peak_gaussian, process_spectrum  # noqa: E402
from scripts.XRD.xrd_core import LAMBDA_CU, detect_peaks_and_fit  # noqa: E402

rows = []


def record(technique, quantity, reference, recovered, unit, note=""):
    if reference == 0:
        deviation = float("nan")
    else:
        deviation = 100.0 * (recovered - reference) / abs(reference)
    rows.append(dict(technique=technique, quantity=quantity, unit=unit,
                     reference=reference, recovered=recovered,
                     deviation=deviation, note=note))


# ---------------------------------------------------------------------------
def illuminated_jv():
    params = dict(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0)
    v = np.round(np.arange(-0.20, 1.1001, 0.01), 4)
    truth = single_diode_reference(**params)
    got = compute_jv_parameters(v, single_diode_jv(v, **params))
    note = "single-diode model, 10 mV steps"
    for key, unit in (("Voc", "V"), ("Jsc", "mA/cm2"), ("FF", "%"),
                      ("PCE", "%"), ("Vmpp", "V")):
        record("J-V (light)", key, truth[key], got[key], unit, note)
    record("J-V (light)", "Rsh", params["rsh"], got["Rsh"], "Ohm cm2",
           "from dV/dJ slope at Jsc")


def dark_jv():
    v = np.round(np.arange(0.0, 1.2001, 0.005), 4)
    for n_true in (1.0, 1.5, 1.85, 2.5):
        j = dark_diode_jv(v, j0=1e-9, n=n_true, rsh=1.0e12)
        record("J-V (dark)", f"ideality n (input {n_true})", n_true,
               analyze_dark_diode(v, j)["n"], "-", "shunt negligible")

    j = dark_diode_jv(v, j0=1e-9, n=1.85, rsh=5.0e4)
    out = analyze_dark_diode(v, j)
    record("J-V (dark)", "ideality n, shunted device", 1.85, out["n"], "-",
           f"auto window {out['fit_Vmin']:.2f}-{out['fit_Vmax']:.2f} V")
    record("J-V (dark)", "Rsh (dark)", 5.0e4, out["Rsh_dark_Ohm_cm2"],
           "Ohm cm2", "low-bias ohmic slope")
    record("J-V (dark)", "log10 J0", -9.0,
           float(np.log10(analyze_dark_diode(
               v, dark_diode_jv(v, j0=1e-9, n=1.85, rsh=1.0e12))["J0_mA_cm2"])),
           "log10(mA/cm2)", "")


def xrd():
    x = np.round(np.arange(10.0, 40.0 + 1e-9, 0.02), 4)
    truth = [dict(height=1000.0, center=28.20, fwhm=0.150, eta=0.5),
             dict(height=700.0, center=28.60, fwhm=0.180, eta=0.5)]
    y = 300.0 * np.exp(-(x - 10.0) / 25.0) + 40.0
    for peak in truth:
        y = y + pseudo_voigt(x, **peak)

    df, _ = detect_peaks_and_fit(x, y, scherrer_k=0.9)
    note = "overlapping doublet, dtheta = 0.40 deg, ALS background"
    for peak in truth:
        hit = df[(df["2Theta"] - peak["center"]).abs() < 0.2].iloc[0]
        record("XRD", f"2theta @ {peak['center']} deg", peak["center"],
               float(hit["2Theta"]), "deg", note)
        record("XRD", f"FWHM @ {peak['center']} deg", peak["fwhm"],
               float(hit["FWHM"]), "deg", note)
        theta = np.radians(peak["center"] / 2.0)
        tau = (0.9 * LAMBDA_CU / 10.0) / (np.radians(peak["fwhm"]) * np.cos(theta))
        record("XRD", f"Scherrer tau @ {peak['center']} deg", tau,
               float(hit["Crystallite_nm"]), "nm", "K = 0.9, Cu Kalpha")


def photoluminescence():
    x = np.round(np.arange(600.0, 900.0 + 1e-9, 0.5), 4)
    y = gaussian(x, 1000.0, 750.0, 40.0) + 80.0 + 0.35 * (x - x[0])
    _, _, corr = process_spectrum(x, y, filter_width=5, rigidity=8,
                                  protection=0.01)
    fit = fit_peak_gaussian(x, corr)
    record("PL", "peak centre", 750.0, fit["center"], "nm",
           "ALS baseline (lam = 1e8) + sloping background")
    record("PL", "FWHM", 40.0, fit["fwhm"], "nm", "isolated peak")

    y2 = gaussian(x, 1000.0, 750.0, 40.0) + gaussian(x, 350.0, 830.0, 70.0)
    fit2 = fit_peak_gaussian(x, y2)
    record("PL", "peak centre, overlapping band", 750.0, fit2["center"], "nm",
           "defect band at 830 nm; valley-bounded window")
    record("PL", "FWHM, overlapping band", 40.0, fit2["fwhm"], "nm",
           "residual bias: single-Gaussian model")


def as_markdown():
    head = ("| Technique | Quantity | Reference | Recovered | Unit | Dev. (%) | Conditions |\n"
            "|---|---|---:|---:|---|---:|---|\n")
    body = ""
    for r in rows:
        body += (f"| {r['technique']} | {r['quantity']} | {r['reference']:.6g} | "
                 f"{r['recovered']:.6g} | {r['unit']} | {r['deviation']:+.3f} | "
                 f"{r['note']} |\n")
    return head + body


def as_csv():
    out = "technique,quantity,reference,recovered,unit,deviation_percent,conditions\n"
    for r in rows:
        out += (f"\"{r['technique']}\",\"{r['quantity']}\",{r['reference']!r},"
                f"{r['recovered']!r},\"{r['unit']}\",{r['deviation']!r},"
                f"\"{r['note']}\"\n")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    illuminated_jv()
    dark_jv()
    xrd()
    photoluminescence()

    sys.stdout.write(as_csv() if args.csv else as_markdown())

    worst = max(rows, key=lambda r: abs(r["deviation"]))
    sys.stderr.write(f"\n{len(rows)} quantities; largest deviation "
                     f"{worst['deviation']:+.3f}% "
                     f"({worst['technique']} / {worst['quantity']})\n")


if __name__ == "__main__":
    main()
