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
from scripts.Dark_JV.dark_jv_core import (analyze_dark_diode, cheung_analysis,  # noqa: E402
                                          dark_diode_current, fit_dark_diode)
from scripts.JV.jv_core import (analyze_scan_hysteresis, compute_jv_parameters,  # noqa: E402
                                fit_single_diode, hysteresis_index)
from scripts.PL.pl_core import fit_multi_peak, fit_peak_gaussian, process_spectrum, to_energy_axis  # noqa: E402
from scripts.XRD.xrd_core import (LAMBDA_CU, LAMBDA_CU_KA1, LAMBDA_CU_KA2, detect_peaks_and_fit,  # noqa: E402
                                  lattice_parameter_cubic, strip_kalpha2, williamson_hall)
from scripts.EQE import eqe_core  # noqa: E402
from scripts.Abs import abs_core  # noqa: E402
from scripts.common import spectral, vibrational  # noqa: E402
from scripts.SEM.sem_core import size_statistics  # noqa: E402
from spectra.core import xps  # noqa: E402

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


def diode_fit():
    params = dict(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0)
    v = np.round(np.arange(-0.20, 1.1001, 0.01), 4)
    fit = fit_single_diode(v, single_diode_jv(v, **params))
    note = "one-diode fit (Lambert-W), 10 mV steps"
    record("J-V (light)", "Jph, diode fit", params["jph"], fit["Jph"], "mA/cm2", note)
    record("J-V (light)", "n, diode fit", params["n"], fit["n"], "-", note)
    record("J-V (light)", "log10 J0, diode fit", -9.0, float(np.log10(fit["J0"])), "log10(mA/cm2)", note)
    record("J-V (light)", "Rs, diode fit", params["rs"], fit["Rs"], "Ohm cm2", note)
    record("J-V (light)", "Rsh, diode fit", params["rsh"], fit["Rsh"], "Ohm cm2", note)
    # hysteresis
    j_f = single_diode_jv(v, **params)
    j_r = single_diode_jv(v, jph=22.0, j0=3e-10, n=1.5, rs=1.5, rsh=4000.0)
    h = analyze_scan_hysteresis(np.concatenate([v, v[::-1]]), np.concatenate([j_f, j_r[::-1]]))
    pf, pr = compute_jv_parameters(v, j_f), compute_jv_parameters(v, j_r)
    record("J-V (light)", "hysteresis index", hysteresis_index(pr["PCE"], pf["PCE"]), h["HI"], "%",
           "forward + reverse sweep split automatically")
    # dark full fit and Cheung
    vd = np.round(np.arange(0.0, 1.2001, 0.005), 4)
    jd = dark_diode_current(vd, 2e-9, 1.8, 5.0, 5e4)
    full = fit_dark_diode(vd, jd)
    record("J-V (dark)", "n, full fit with Rs", 1.8, full["n"], "-", "log-space residuals")
    record("J-V (dark)", "Rs, full fit", 5.0, full["Rs_Ohm_cm2"], "Ohm cm2", "")
    record("J-V (dark)", "Rsh, full fit", 5.0e4, full["Rsh_Ohm_cm2"], "Ohm cm2", "")
    ch = cheung_analysis(vd, dark_diode_current(vd, 2e-9, 1.8, 5.0, 1e9))
    record("J-V (dark)", "Rs, Cheung dV/dlnJ", 5.0, ch["Rs_Ohm_cm2"], "Ohm cm2", "J > 5% of maximum")
    record("J-V (dark)", "n, Cheung intercept", 1.8, ch["n"], "-", "")


def eqe():
    from scipy.special import erf
    wl = np.arange(300.0, 1100.0 + 1e-9, 1.0)
    e = eqe_core.HC_EV_NM / wl
    eg, sigma = 1.60, 0.03
    q = 0.9 * 0.5 * (1 + erf((e - eg) / (sigma * np.sqrt(2))))
    r = eqe_core.bandgap_rau(e, q)
    record("EQE", "Eg from dEQE/dE distribution", eg, r["Eg"], "eV", "error-function edge, sigma 30 meV")
    record("EQE", "edge width sigma", 0.59 * sigma, r["sigma"], "eV", "std over the half-maximum window")
    eu = 0.020
    q2 = np.where(e < eg, 0.9 * np.exp((e - eg) / eu), 0.9)
    lo, hi = eqe_core.auto_urbach_window(e, q2)
    record("EQE", "Urbach energy", 20.0, eqe_core.urbach_energy(e, q2, lo, hi)["Eu_meV"], "meV", "exponential tail, auto window")
    step = (e >= eg).astype(float)
    rad = eqe_core.radiative_limit(e, step, 300.0, extend_tail=False)
    sq = eqe_core.shockley_queisser(eg, 300.0)
    record("EQE", "Voc,rad of a step absorber", sq["Voc_SQ"], rad["Voc_rad_V"], "V", "must equal Voc,SQ")
    record("EQE", "SQ efficiency at 1.34 eV", 33.7, eqe_core.shockley_queisser(1.34, 300.0)["PCE_SQ"], "%",
           "literature 33.7% (Ruhle 2016)")
    record("EQE", "SQ Jsc at 1.34 eV", 35.4, eqe_core.shockley_queisser(1.34, 300.0)["Jsc_SQ"], "mA/cm2", "")
    wl_i, irr = eqe_core.get_am15g_spectrum()
    record("EQE", "AM1.5G integral", 1000.4, float(np.trapz(irr, wl_i) if not hasattr(np, "trapezoid") else np.trapezoid(irr, wl_i)),
           "W/m2", "ASTM G173-03 table")


def absorbance():
    wl = np.arange(350.0, 1000.0 + 1e-9, 1.0)
    e = abs_core.HC_EV_NM / wl
    eg, eps, eu = 1.60, 0.002, 0.02
    a = np.where(e >= eg, 1.2 * np.sqrt(np.clip(e - eg + eps, 0, None)) / e,
                 1.2 * np.sqrt(eps) / eg * np.exp((e - eg) / eu)) + 0.02
    r = abs_core.analyze_absorbance(wl, a, "direct")
    record("Abs", "Eg, automatic Tauc region", eg - eps, r["Eg_Tauc_eV"], "eV", "direct edge with Urbach tail")
    record("Abs", "Eg, derivative", eg, r["Eg_derivative_eV"], "eV", "max dA/dE")
    a2 = np.where(e >= eg, 1.2 * np.sqrt(np.clip(e - eg + eps, 0, None)) / e, 1.2 * np.sqrt(eps) / eg * np.exp((e - eg) / 0.025))
    record("Abs", "Urbach energy", 25.0, abs_core.urbach_from_absorbance(wl, a2, eg - 0.2, eg - 0.03)["Eu_meV"], "meV", "ln A vs E")


def xrd_extra():
    d_nm, eps = 40.0, 2.0e-3
    tt = np.array([14.1, 20.0, 24.5, 28.4, 31.9, 35.0, 40.6, 43.2])
    th = np.radians(tt / 2)
    beta = (0.9 * LAMBDA_CU / 10 / d_nm) / np.cos(th) + 4 * eps * np.tan(th)
    wh = williamson_hall(tt, np.degrees(beta))
    record("XRD", "Williamson-Hall D", d_nm, wh["D_nm"], "nm", "8 reflections")
    record("XRD", "Williamson-Hall strain", eps, wh["strain"], "-", "")
    a0 = 6.28
    hkl = [(1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0), (2, 1, 1), (2, 2, 0)]
    d = a0 / np.sqrt(np.sum(np.asarray(hkl, float) ** 2, axis=1))
    two_theta = 2 * np.degrees(np.arcsin(LAMBDA_CU / (2 * d)))
    shifted = two_theta + 0.08 * np.cos(np.radians(two_theta / 2))
    lp = lattice_parameter_cubic(shifted, hkl)
    record("XRD", "cubic a, Nelson-Riley (displaced specimen)", a0, lp["a_NR_A"], "A", "0.08 cos(theta) deg displacement error")
    record("XRD", "cubic a, plain mean (same data)", a0, lp["a_mean_A"], "A", "for comparison")
    x = np.round(np.arange(60.0, 70.0 + 1e-9, 0.01), 4)
    c1 = 65.0
    dd = LAMBDA_CU_KA1 / (2 * np.sin(np.radians(c1 / 2)))
    c2 = 2 * np.degrees(np.arcsin(LAMBDA_CU_KA2 / (2 * dd)))
    y = pseudo_voigt(x, 1000.0, c1, 0.08, 0.5) + pseudo_voigt(x, 500.0, c2, 0.08, 0.5) + 20.0
    st = strip_kalpha2(x, y)
    flat = (x > 61.0) & (x < 63.5)
    bg = float(np.median(st[flat]))
    i2 = int(np.argmin(np.abs(x - c2)))
    record("XRD", "Kalpha2 residual after stripping", 0.0, float(st[i2] - bg) / 500.0 * 100.0, "% of satellite", "Rachinger")


def spectroscopy():
    x = np.linspace(0.0, 100.0, 1001)
    y = spectral.gaussian(x, 10.0, 48.0, 6.0) + spectral.gaussian(x, 6.0, 55.0, 5.0)
    res = spectral.fit_peaks(x, y, [47.0, 56.0])
    pk = sorted(res.peaks, key=lambda p: p.center)
    record("Spectral", "overlapping Gaussian centre 1", 48.0, pk[0].center, "x", "two components fitted together")
    record("Spectral", "overlapping Gaussian FWHM 2", 5.0, pk[1].fwhm, "x", "")
    rng = np.random.default_rng(2)
    doublet = spectral.gaussian(x, 10.0, 45.0, 6.0) + spectral.gaussian(x, 5.0, 58.0, 6.0) + rng.normal(0, 0.05, len(x))
    record("Spectral", "components chosen by AICc", 2, len(spectral.select_n_peaks(x, doublet, max_peaks=4).peaks), "-", "noisy doublet")
    wl = np.linspace(600.0, 900.0, 3001)
    yy = spectral.gaussian(wl, 1000.0, 750.0, 40.0)
    e, ye = spectral.spectrum_to_energy(wl, yy)
    record("PL", "integrated intensity after nm->eV (Jacobian)", spectral.integrate(wl, yy), spectral.integrate(e, ye), "a.u.", "area conserved")
    wl2 = np.round(np.arange(600.0, 900.0 + 1e-9, 0.5), 4)
    y2 = gaussian(wl2, 1000.0, 750.0, 40.0) + gaussian(wl2, 300.0, 820.0, 80.0) + np.random.default_rng(0).normal(0, 3.0, len(wl2))
    m = fit_multi_peak(wl2, y2, max_peaks=3)
    main = min(m.peaks, key=lambda p: abs(p.center - 750))
    record("PL", "FWHM, multi-component fit with defect band", 40.0, main.fwhm, "nm", "AICc, 2 components")
    xr = np.arange(100.0, 2000.0 + 1e-9, 1.0)
    raman = 30.0 + 40.0 * np.exp(-((xr - 1200.0) / 900.0) ** 2) + spectral.lorentzian(xr, 100.0, 520.5, 6.0)
    prep = vibrational.preprocess(xr, raman, baseline="arpls", lam=1e5)
    i = int(np.argmin(np.abs(xr - 520.5)))
    record("Raman", "band height after arPLS baseline", 100.0, float(prep["corrected"][i]), "a.u.", "fluorescence background")
    fits = vibrational.fit_bands(xr, prep["corrected"], [520.5], shape="lorentzian")
    record("Raman", "Lorentzian FWHM", 6.0, float(fits.iloc[0]["fwhm"]), "cm-1", "")
    be = np.linspace(280.0, 295.0, 301)
    peak = spectral.gaussian(be, 1000.0, 285.0, 1.4)
    cum = np.cumsum(peak) * (be[1] - be[0])
    bg = 100.0 + 300.0 * cum / cum[-1]
    b = xps.shirley_background(be, bg + peak)
    record("XPS", "Shirley background error (max)", 0.0, float(np.max(np.abs(b - bg))) / 300.0 * 100.0, "% of step", "")
    c = xps.atomic_concentration({"C1s": 1000.0, "O1s": 2930.0})
    record("XPS", "atomic % O for equal C and O", 50.0, c["O1s"], "at.%", "Scofield factors")
    d = np.random.default_rng(0).lognormal(np.log(300.0), 0.35, 5000)
    st = size_statistics(d)
    record("SEM", "log-normal sigma", 0.35, st["lognorm_sigma"], "-", "5000 grains, sample s.d. of ln d")
    record("SEM", "geometric mean", 300.0, st["geo_mean"], "nm", "")


def autofit():
    """Voigt fits of the auto-fit workspace (spectra/). Up to 3.5.1 the
    Lorentzian width gamma was never fitted; these rows hold the fix (3.5.2)."""
    import tempfile
    from scipy.special import voigt_profile
    from spectra.app import build_default_configs
    from spectra.core.fit_common import fit_windows_to_midpoints, voigt_fwhm
    from spectra.core.fit_xps import fit_xps_doublet_voigts
    from spectra.pipelines.run_xps import run_xps_pipeline
    import pandas as pd

    be = np.arange(132.0, 150.0001, 0.05)
    for name, s_, g_ in (("Gaussian-dominated", 0.36, 0.22), ("mixed", 0.25, 0.30), ("Lorentzian-dominated", 0.10, 0.45)):
        rng = np.random.default_rng(1)
        y = 1000.0 * voigt_profile(be - 138.6, s_, g_) + 750.0 * voigt_profile(be - 143.47, s_, g_) + rng.normal(0, 1.0, be.size)
        fw = voigt_fwhm(s_, g_)
        d = fit_xps_doublet_voigts(be, y, (135.5, 147.0), 138.6, float(y.max()), fw, 4.87, 0.75)[0]
        cond = f"Voigt doublet, sigma {s_} / gamma {g_} eV, split and 3:4 ratio fixed"
        record("XPS auto-fit", f"Pb 4f7/2 area, {name}", 1000.0, float(d["area_amplitude"].iloc[0]), "counts eV", cond)
        if name == "mixed":
            record("XPS auto-fit", "Lorentzian half-width gamma", g_, float(d["gamma"].iloc[0]), "eV", cond)
            record("XPS auto-fit", "Voigt FWHM", fw, float(d["fwhm"].iloc[0]), "eV", cond)
    # pipeline: Pb 4f with a metallic shoulder, GL(30) lines, Shirley step, Poisson noise
    bx = np.arange(132.0, 150.0, 0.05)

    def gl(c, fwhm, area, m=0.3):
        sg = fwhm / 2.355
        g = np.exp(-((bx - c) ** 2) / (2 * sg * sg)) / (sg * np.sqrt(2 * np.pi))
        lo = (fwhm / 2) / np.pi / ((bx - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * g + m * lo)
    _, _, cfg = build_default_configs()
    main, metal = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for seed in range(12):
            pk = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
            yy = np.random.default_rng(seed).poisson(np.clip(pk + 900 + 0.12 * np.cumsum(pk[::-1])[::-1] * 0.05, 1, None)).astype(float)
            _, _, f = run_xps_pipeline(bx, yy, os.path.join(tmp, str(seed)), cfg, log_cb=lambda m: None)

            def area_at(c):
                return float(f.iloc[(f["center"] - c).abs().argmin()]["area_amplitude"])
            main.append(area_at(138.60))
            metal.append(area_at(136.85) / area_at(138.60))
    cond = "pipeline, GL(30) lines + Shirley step, Poisson, median of 12"
    record("XPS auto-fit", "Pb 4f7/2 area with metallic shoulder", 4000.0, float(np.median(main)), "counts eV", cond)
    record("XPS auto-fit", "Pb0 / Pb2+ area ratio", 0.095, float(np.median(metal)), "-", cond)
    # XRD: two lines 3.5 deg apart, default 3.5 deg window, fit only (no smoothing or baseline)
    tt = np.arange(10.0, 60.0, 0.02)
    lines = [(14.1, 0.18, 0.06, 800.0), (28.4, 0.12, 0.10, 500.0), (31.9, 0.05, 0.14, 300.0), (43.2, 0.20, 0.02, 400.0)]
    y = sum(a * voigt_profile(tt - c, s, g) for c, s, g, a in lines)
    cand = pd.DataFrame({"x": [c for c, *_ in lines], "height": [float(y[np.abs(tt - c).argmin()]) for c, *_ in lines],
                         "fwhm_x": [voigt_fwhm(s, g) for _, s, g, _ in lines]})
    f = pd.concat(fit_windows_to_midpoints(tt, y, cand, 3.5), ignore_index=True)
    for c, s, g, a in lines[1:3]:
        r = f.iloc[(f["center"] - c).abs().argmin()]
        record("XRD auto-fit", f"Voigt area, line at {c} deg", a, float(r["area_amplitude"]), "counts deg",
               "neighbour 3.5 deg away, window to the midpoint, no smoothing")


def cross_technique():
    from scipy.special import erf
    from scripts.common import device_summary as ds
    from scripts.XRD import xrd_core as xc
    import pandas as pd
    v = np.round(np.arange(-0.20, 1.1001, 0.01), 4)
    j = single_diode_jv(v)
    jv = compute_jv_parameters(v, j)
    wl = np.arange(300.0, 1100.0 + 1e-9, 1.0)
    e = eqe_core.HC_EV_NM / wl
    q = 85.0 * 0.5 * (1 + erf((e - 1.60) / (0.03 * np.sqrt(2))))
    s = ds.summarize_device(jv, wl, q, eg_abs_ev=1.61, pl_peak_ev=1.58)
    jsc_eqe = eqe_core.calculate_jsc(wl, q)
    record("Device", "Jsc mismatch", 100 * (jv["Jsc"] - jsc_eqe) / jsc_eqe, s["Jsc_mismatch_percent"], "%",
           "single-diode J-V vs error-function EQE")
    record("Device", "dV1 + dV2 + dV3", s["Voc_deficit"], s["dV1_SQ"] + s["dV2_rad"] + s["dV3_nonrad"], "V",
           "loss terms close the Voc deficit")
    record("Device", "band-gap spread", 30.0, s["Eg_spread_meV"], "meV", "EQE 1.60, Tauc 1.61, PL 1.58 eV")
    # reference matching on a strained cubic film
    hkl = [(1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0), (2, 1, 1), (2, 2, 0)]
    def lines(a):
        d = a / np.sqrt(np.sum(np.asarray(hkl, float) ** 2, axis=1))
        return d, 2 * np.degrees(np.arcsin(LAMBDA_CU / (2 * d)))
    d0, t0 = lines(6.28)
    _, t1 = lines(6.28 * 1.003)
    ref = pd.DataFrame({"2Theta": t0, "d": d0, "hkl": ["".join(map(str, h)) for h in hkl], "I_rel": 100.0})
    x = np.round(np.arange(10.0, 50.0, 0.01), 4)
    y = 50.0 + sum(pseudo_voigt(x, 1000.0, t, 0.12, 0.5) for t in t1)
    peaks, _ = xc.detect_peaks_and_fit(x, y)
    m = xc.match_reference(peaks, ref, tolerance_deg=0.3)
    record("XRD", "lattice strain from reference match", 0.003, m["mean_strain"], "-", "7 reflections, a = 1.003 a0")
    record("XRD", "reference coverage", 1.0, m["coverage"], "-", "")


def transport():
    """The six curve tools of 3.5, each against the model its own `simulate` draws."""
    import math
    from scripts.CV import cv_core
    from scripts.EIS import eis_core
    from scripts.Intensity import intensity_core
    from scripts.SCLC import sclc_core
    from scripts.Stability import stability_core
    from scripts.TRPL import trpl_core

    # SCLC: ohmic, trap-filling and Child regimes of a 500 nm single-carrier device
    truth = dict(thickness_nm=500.0, eps_r=25.0, mobility_cm2_Vs=1.0, n_t_cm3=5e16, n0_cm3=1e13)
    v, j = sclc_core.simulate(**truth)
    r = sclc_core.analyse(v, j, truth["thickness_nm"], truth["eps_r"])
    v_tfl = sclc_core.Q * truth["n_t_cm3"] * 1e6 * (truth["thickness_nm"] * 1e-9) ** 2 / (2 * sclc_core.EPS0 * truth["eps_r"])
    note = "piecewise ohmic / trap-filling / Child curve, 500 nm, eps_r 25"
    record("SCLC", "V_TFL", v_tfl, r["V_TFL"], "V", note)
    record("SCLC", "trap density", truth["n_t_cm3"], r["n_t_cm3"], "cm-3", "n_t = 2 eps V_TFL / (q L^2)")
    record("SCLC", "mobility (Mott-Gurney)", truth["mobility_cm2_Vs"], r["mobility_cm2_Vs"], "cm2/Vs", "fit of J = 9/8 eps mu V^2 / L^3")
    record("SCLC", "background carrier density", truth["n0_cm3"], r["n0_cm3"], "cm-3", "ohmic region with the fitted mobility")

    # light intensity: one-diode cell over two decades
    d = intensity_core.simulate(n_id=1.5, alpha=0.97, rs_ohm_cm2=3.0)
    r = intensity_core.analyse(**d)
    note = "one-diode cell, 1-100 mW/cm2, Rs 3 Ohm cm2"
    record("Light intensity", "ideality factor from Jsc-Voc", 1.5, r["jscvoc_fit"]["n_id"], "-", note)
    record("Light intensity", "Jsc exponent alpha", 0.97, r["jsc_fit"]["alpha"], "-", note)
    record("Light intensity", "Voc slope", 1.5 * 0.97 * intensity_core.KB_EV * 300.0 * math.log(10) * 1e3,
           r["voc_fit"]["slope_mV_per_decade"], "mV/decade", "n_id alpha kT/q ln 10")

    # TRPL: Poisson counting trace, two exponentials on a background
    t, y = trpl_core.simulate(taus=(5.0, 80.0), amps=(0.7, 0.3), peak_counts=10000.0, background=5.0, seed=0)
    r = trpl_core.analyse(t, y)
    note = "bi-exponential, 10^4 peak counts, Poisson noise, background 5"
    record("TRPL", "tau 1", 5.0, r["taus"][0], "ns", note)
    record("TRPL", "tau 2", 80.0, r["taus"][1], "ns", note)
    record("TRPL", "amplitude-weighted lifetime", 0.7 * 5.0 + 0.3 * 80.0, r["tau_amp"], "ns", "sum A_i tau_i / sum A_i")
    record("TRPL", "intensity-weighted lifetime", (0.7 * 25.0 + 0.3 * 6400.0) / 27.5, r["tau_int"], "ns", "sum A_i tau_i^2 / sum A_i tau_i")
    record("TRPL", "decay terms chosen by AICc", 2, len(r["taus"]), "-", "model = auto")
    t, y = trpl_core.simulate(taus=(40.0,), amps=(1.0,), beta=0.6, seed=0)
    r = trpl_core.analyse(t, y, model="stretched")
    record("TRPL", "stretching exponent beta", 0.6, r["beta"], "-", "stretched exponential, tau 40 ns")

    # impedance: Rs + two R-CPE arcs, 0.3 % noise
    f, zre, zim = eis_core.simulate()
    r = eis_core.analyse(f, zre, zim)
    note = "R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise"
    record("Impedance", "Rs", 10.0, r["Rs"], "Ohm", note)
    record("Impedance", "R of the high-frequency arc", 200.0, r["arcs"][0]["R"], "Ohm", note)
    record("Impedance", "R of the low-frequency arc", 1500.0, r["arcs"][1]["R"], "Ohm", note)
    record("Impedance", "CPE exponent, high-frequency arc", 0.95, r["arcs"][0]["alpha"], "-", note)
    record("Impedance", "CPE exponent, low-frequency arc", 0.85, r["arcs"][1]["alpha"], "-", note)

    # C-V: one-sided abrupt junction
    v, c = cv_core.simulate(n_cm3=1e17, v_bi=0.9, eps_r=25.0, area_cm2=0.1)
    r = cv_core.analyse(v, c, 0.1, 25.0)
    note = "one-sided junction, 0.1 cm2, eps_r 25"
    record("C-V", "doping density (Mott-Schottky)", 1e17, r["N_cm3"], "cm-3", note)
    record("C-V", "built-in potential", 0.9, r["V_bi"], "V", "intercept + kT/q")

    # stability: burn-in plus linear loss, 0.4 % noise
    t, y = stability_core.simulate(a1=0.12, tau1=40.0, rate_per_h=1e-4, t_end=1000.0, seed=0)
    r = stability_core.analyse(t, y)
    note = "12 % burn-in (tau 40 h) + 10 %/1000 h, 0.4 % noise"
    record("Stability", "T80 (measured crossing)", 800.0, r["T_measured"], "h", note)
    record("Stability", "T80 (fitted model)", 800.0, r["T_model"], "h", note)
    record("Stability", "burn-in loss", 12.0, r["burn_in_loss_pct"], "% of initial", "back-extrapolated linear part")
    record("Stability", "loss rate after burn-in", 10.0, r["rate_pct_per_1000h"], "%/1000 h", note)


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
    diode_fit()
    dark_jv()
    eqe()
    absorbance()
    xrd()
    xrd_extra()
    photoluminescence()
    spectroscopy()
    autofit()
    cross_technique()
    transport()

    sys.stdout.write(as_csv() if args.csv else as_markdown())

    worst = max(rows, key=lambda r: abs(r["deviation"]))
    sys.stderr.write(f"\n{len(rows)} quantities; largest deviation "
                     f"{worst['deviation']:+.3f}% "
                     f"({worst['technique']} / {worst['quantity']})\n")


if __name__ == "__main__":
    main()
