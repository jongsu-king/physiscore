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
