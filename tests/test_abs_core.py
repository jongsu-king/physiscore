"""UV-Vis: Tauc transform, automatic linear-region selection, Urbach tail
and derivative band gap on a synthetic direct-gap absorber."""
import numpy as np
import pytest

from scripts.Abs import abs_core as ac

WL = np.arange(350.0, 1000.0 + 1e-9, 1.0)
E = ac.HC_EV_NM / WL
EG = 1.60


def direct_gap_absorbance(eg=EG, eu=0.020, a0=1.2, offset=0.02, eps=0.002):
    """Allowed direct transition, alpha(E) = a0 sqrt(E - Eg + eps) / E above
    the gap, so that (A h nu)^2 = a0^2 (E - Eg + eps) is exactly linear with
    its intercept at Eg - eps; an exponential (Urbach) tail continues it
    below the gap. `offset` is a flat baseline (substrate / reflection)."""
    above = a0 * np.sqrt(np.clip(E - eg + eps, 0, None)) / E
    tail_amp = a0 * np.sqrt(eps) / eg
    below = tail_amp * np.exp((E - eg) / eu)
    return np.where(E >= eg, above, below) + offset


def test_tauc_transform_axes_and_exponents():
    a = direct_gap_absorbance()
    hv, y, label = ac.tauc_transform(WL, a, "direct")
    assert np.all(np.diff(hv) > 0)
    i = np.argmin(np.abs(hv - 2.0))
    assert y[i] == pytest.approx((a[np.argmin(np.abs(E - 2.0))] * hv[i]) ** 2, rel=1e-6)
    assert "2" in label
    hv2, y2, label2 = ac.tauc_transform(WL, a, "indirect")
    assert "1/2" in label2
    with pytest.raises(ValueError):
        ac.tauc_transform(WL, a, "bogus")


def test_alpha_basis_does_not_move_the_intercept():
    a = direct_gap_absorbance()
    hv, y_a, _ = ac.tauc_transform(WL, a, "direct")
    _, y_alpha, _ = ac.tauc_transform(WL, a, "direct", thickness_nm=300.0)
    fa = ac.linear_fit(hv, y_a, EG + 0.02, EG + 0.15)
    fb = ac.linear_fit(hv, y_alpha, EG + 0.02, EG + 0.15)
    assert fa["Eg"] == pytest.approx(fb["Eg"], abs=1e-6)
    assert fb["slope"] / fa["slope"] == pytest.approx((ac.LN10 / 300e-7) ** 2, rel=1e-6)


def test_linear_fit_on_the_exact_tauc_region():
    """Above Eg, (A h nu)^2 ~ (E - Eg) exactly for this model (apart from the
    constant offset), so the intercept must land on Eg."""
    a = direct_gap_absorbance(offset=0.0)
    hv, y, _ = ac.tauc_transform(WL, a, "direct")
    fit = ac.linear_fit(hv, y, EG + 0.03, EG + 0.12)
    assert fit["Eg"] == pytest.approx(EG - 0.002, abs=0.002)
    assert fit["R2"] > 0.999
    assert fit["Eg_err"] < 0.01


def test_auto_region_finds_the_edge_without_a_hint():
    a = direct_gap_absorbance()
    hv, y, _ = ac.tauc_transform(WL, a, "direct")
    reg = ac.auto_linear_region(hv, y)
    assert reg["lo"] > EG - 0.05
    assert reg["hi"] > reg["lo"] + 0.03
    assert reg["Eg"] == pytest.approx(EG, abs=0.02)
    assert reg["R2"] > 0.99


def test_auto_region_with_expected_gap_hint():
    a = direct_gap_absorbance()
    hv, y, _ = ac.tauc_transform(WL, a, "direct")
    reg = ac.auto_linear_region(hv, y, expected_eg=1.55)
    assert reg["Eg"] == pytest.approx(EG, abs=0.02)


def test_auto_region_is_robust_to_noise():
    rng = np.random.default_rng(0)
    a = direct_gap_absorbance() + rng.normal(0, 0.003, len(WL))
    hv, y, _ = ac.tauc_transform(WL, a, "direct")
    reg = ac.auto_linear_region(hv, y)
    assert reg["Eg"] == pytest.approx(EG, abs=0.03)


def test_urbach_energy_from_absorbance_tail():
    a = direct_gap_absorbance(eu=0.025, offset=0.0)
    r = ac.urbach_from_absorbance(WL, a, EG - 0.20, EG - 0.03)
    assert r["Eu_meV"] == pytest.approx(25.0, rel=0.03)
    # a flat baseline bends ln(A): the GUI subtracts it first, as here
    r2 = ac.urbach_from_absorbance(WL, direct_gap_absorbance(eu=0.025) - 0.02, EG - 0.20, EG - 0.03)
    assert r2["Eu_meV"] == pytest.approx(25.0, rel=0.03)
    assert r["R2"] > 0.999


def test_derivative_bandgap_sits_at_the_edge():
    a = direct_gap_absorbance()
    assert ac.derivative_bandgap(WL, a) == pytest.approx(EG, abs=0.03)


def test_analyze_absorbance_summary_is_self_consistent():
    r = ac.analyze_absorbance(WL, direct_gap_absorbance(), mode="direct")
    assert r["Eg_Tauc_eV"] == pytest.approx(EG, abs=0.02)
    assert r["Tauc_lo_eV"] < r["Eg_Tauc_eV"] + 0.1 < r["Tauc_hi_eV"] + 0.3
    assert abs(r["Eg_derivative_eV"] - r["Eg_Tauc_eV"]) < 0.05
    assert np.isfinite(r["Eu_meV"])


def test_degenerate_inputs_do_not_raise():
    reg = ac.auto_linear_region([1.0, 1.1], [0.0, 0.1])
    assert np.isnan(reg["Eg"])
    assert ac.linear_fit([1, 2], [1, 2], 1, 2)["n_points"] == 2
    assert np.isnan(ac.derivative_bandgap([500, 600], [0.1, 0.2]))
