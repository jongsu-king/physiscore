"""XPS: Shirley background, charge referencing, region areas and atomic
concentration."""
import numpy as np
import pytest

from scripts.common import spectral as sp
from spectra.core import xps


def synthetic_region(center=285.0, height=1000.0, fwhm=1.4, step=300.0, offset=100.0):
    be = np.linspace(center - 8, center + 8, 321)
    peak = sp.gaussian(be, height, center, fwhm)
    cum = np.cumsum(peak) * (be[1] - be[0])
    bg = offset + step * cum / cum[-1]
    return be, bg + peak, bg, peak


def test_shirley_background_recovers_the_step():
    be, y, bg, peak = synthetic_region()
    b = xps.shirley_background(be, y)
    assert np.max(np.abs(b - bg)) < 0.02 * 300.0
    b_desc = xps.shirley_background(be[::-1], y[::-1])
    assert np.allclose(b_desc[::-1], b)


def test_charge_correction_moves_c1s_to_the_reference():
    be = np.array([283.9, 530.2])
    shift = xps.charge_correction_shift(283.9)
    assert shift == pytest.approx(0.9)
    corrected = xps.apply_charge_correction(be, shift)
    assert corrected[0] == pytest.approx(284.8)
    assert corrected[1] == pytest.approx(531.1)


def test_region_area_after_shirley_equals_the_peak_area():
    be, y, bg, peak = synthetic_region()
    trap = getattr(np, "trapezoid", None) or np.trapz
    expected = trap(peak, be)
    got = xps.peak_area(be, y, be.min(), be.max(), background="shirley")
    assert got["area"] == pytest.approx(expected, rel=0.03)
    none = xps.peak_area(be, y, be.min(), be.max(), background="none")
    assert none["area"] > got["area"]
    assert xps.peak_area(be, y, 285.0, 285.01)["n_points"] < 5


def test_atomic_concentration_with_scofield_and_user_factors():
    # equal numbers of C and O atoms: A_O / A_C = RSF_O / RSF_C
    areas = {"C1s": 1000.0, "O1s": 2930.0}
    c = xps.atomic_concentration(areas)
    assert c["C1s"] == pytest.approx(50.0)
    assert c["O1s"] == pytest.approx(50.0)
    c2 = xps.atomic_concentration({"C1s_ref": 1000.0, "O1s_oxide": 2930.0, "Pb4f": 22700.0})
    assert c2["Pb4f"] == pytest.approx(100.0 / 3.0)
    user = xps.atomic_concentration({"A": 10.0, "B": 10.0}, rsf={"A": 1.0, "B": 4.0})
    assert user["A"] == pytest.approx(80.0) and user["B"] == pytest.approx(20.0)
    with pytest.raises(ValueError):
        xps.atomic_concentration({"Xx9z": 1.0})


def test_doublet_parameters_and_energy_conversion():
    pb = xps.doublet_parameters("Pb4f")
    assert pb["split"] == pytest.approx(4.87) and pb["ratio"] == pytest.approx(0.75)
    assert xps.doublet_parameters("O1s")["split"] == 0.0
    generic_d = xps.doublet_parameters("Zr3d")
    assert generic_d["ratio"] == pytest.approx(2 / 3) and np.isnan(generic_d["split"])
    assert xps.kinetic_to_binding(1200.0, 1486.6, 4.5) == pytest.approx(282.1)


def test_autofit_keeps_a_small_peak_next_to_a_large_one(tmp_path):
    """Pb 4f with a metallic shoulder: four singlet components, fitted by cluster.
    Up to 3.1.1 each candidate got its own window with one Voigt: the small peaks'
    components either migrated onto the large ones or dropped to zero amplitude."""
    import numpy as np
    from spectra.app import build_default_configs
    from spectra.pipelines.run_xps import run_xps_pipeline

    be = np.arange(132.0, 150.0, 0.05)
    rng = np.random.default_rng(19)

    def gl(c, fwhm, area, m=0.3):
        s = fwhm / 2.355
        gauss = np.exp(-((be - c) ** 2) / (2 * s * s)) / (s * np.sqrt(2 * np.pi))
        lor = (fwhm / 2) / np.pi / ((be - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * gauss + m * lor)
    peaks = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
    step = 900 + 0.12 * np.cumsum(peaks[::-1])[::-1] * 0.05
    y = rng.poisson(np.clip(peaks + step, 1, None)).astype(float)

    _, _, cfg = build_default_configs()
    _, _, fitted = run_xps_pipeline(be, y, str(tmp_path), cfg, log_cb=lambda m: None)
    assert len(fitted) == 4
    centers = np.sort(fitted["center"].to_numpy())
    assert np.all(np.abs(centers - np.array([136.85, 138.60, 141.72, 143.47])) < 0.5)
    assert (fitted["height"] > 100).all()

    def area_at(c):
        return float(fitted.iloc[(fitted["center"] - c).abs().argmin()]["area_amplitude"])
    assert area_at(143.47) / area_at(138.60) == pytest.approx(0.75, rel=0.05)
    assert area_at(136.85) / area_at(138.60) == pytest.approx(0.095, rel=0.35)


def test_autofit_interpretation_and_report_flag_metallic_lead(tmp_path):
    """The rule engine reads the auto-fit table: the Pb0 shoulder 1.75 eV below
    Pb2+ is reported, the 4f doublet ratio is in range, and the peak report holds
    the rule-based findings (3.4: no Gemini section any more)."""
    import numpy as np
    from scripts.common.interpret import interpret_peak_fit
    from spectra.app import build_default_configs
    from spectra.core.report import generate_peak_report
    from spectra.pipelines.run_xps import run_xps_pipeline

    be = np.arange(132.0, 150.0, 0.05)
    rng = np.random.default_rng(7)

    def gl(c, fwhm, area, m=0.3):
        s = fwhm / 2.355
        gauss = np.exp(-((be - c) ** 2) / (2 * s * s)) / (s * np.sqrt(2 * np.pi))
        lor = (fwhm / 2) / np.pi / ((be - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * gauss + m * lor)
    peaks = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
    step = 900 + 0.12 * np.cumsum(peaks[::-1])[::-1] * 0.05
    y = rng.poisson(np.clip(peaks + step, 1, None)).astype(float)

    _, _, cfg = build_default_configs()
    proc, cand, fitted = run_xps_pipeline(be, y, str(tmp_path), cfg, log_cb=lambda m: None)
    lv = {f.topic: f.level for f in interpret_peak_fit("XPS", fitted).findings}
    assert lv["Metallic lead"] == "warning"
    assert lv["Spin-orbit doublet"] == "good"

    md = generate_peak_report(proc=proc, cand=cand, fitted=fitted, cfg=cfg, outdir=str(tmp_path),
                              file_label="Pb4f.csv")
    text = open(md, encoding="utf-8").read()
    assert "## Rule-based findings" in text and "Metallic lead" in text
    assert "Gemini" not in text
