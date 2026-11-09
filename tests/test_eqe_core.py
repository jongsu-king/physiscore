"""EQE: Jsc integration, band gap from the edge, Urbach energy and the
detailed-balance quantities (J0,rad, Voc,rad, Shockley-Queisser limits,
voltage-loss decomposition).

The step-function absorber is the one case with closed-form answers, so it
anchors every detailed-balance test; smooth edges then check the
derivative-distribution estimator against the parameters that built them.
"""
import math

import numpy as np
import pytest
from scipy.special import erf

from scripts.EQE import eqe_core as ec

Q, KB, H, C = ec.Q_E, ec.K_B, ec.H_PLANCK, ec.C_LIGHT


def sigmoid_edge(e, eg, sigma, height=0.9):
    """EQE whose derivative is a Gaussian centred at eg with width sigma."""
    return height * 0.5 * (1.0 + erf((e - eg) / (sigma * math.sqrt(2.0))))


WL = np.arange(300.0, 1100.0 + 1e-9, 1.0)
E = ec.HC_EV_NM / WL


# ---------------------------------------------------------------------------
# Reference spectrum and Jsc
# ---------------------------------------------------------------------------
def test_reference_spectrum_integrates_to_one_sun():
    wl, irr = ec.get_am15g_spectrum()
    assert len(wl) > 1000, "full-resolution ASTM G173-03 table expected"
    assert ec._trapz(irr, wl) == pytest.approx(1000.4, abs=1.0)


def test_photon_flux_per_ev_conserves_photon_number():
    wl, irr = ec.get_am15g_spectrum()
    e_j = H * C / (wl * 1e-9)
    n_per_nm = ec._trapz(irr / e_j, wl)
    e, flux = ec.am15g_photon_flux_per_ev()
    assert ec._trapz(flux, e) == pytest.approx(n_per_nm, rel=1e-3)


def test_jsc_of_unit_eqe_over_the_visible_window():
    """EQE = 1 between 300 and 1100 nm: Jsc must equal q times the photon
    flux in that window, computed here independently from the raw table."""
    wl, irr = ec.get_am15g_spectrum()
    m = (wl >= 300) & (wl <= 1100)
    flux = irr[m] / (H * C / (wl[m] * 1e-9))
    expected = Q * ec._trapz(flux, wl[m]) * 0.1
    assert ec.calculate_jsc(WL, np.ones_like(WL)) == pytest.approx(expected, rel=2e-3)
    assert ec.calculate_jsc(WL, 100.0 * np.ones_like(WL)) == pytest.approx(expected, rel=2e-3)


def test_jsc_is_linear_in_eqe_and_cumulative_integral_matches():
    eqe = sigmoid_edge(E, 1.6, 0.03)
    j1 = ec.calculate_jsc(WL, eqe)
    j2 = ec.calculate_jsc(WL, 0.5 * eqe)
    assert j2 == pytest.approx(0.5 * j1, rel=1e-9)
    _, _, cum = ec.compute_am15_integrals(WL, eqe)
    assert cum.max() == pytest.approx(j1, rel=0.01)


# ---------------------------------------------------------------------------
# Band gap
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("eg,sigma", [(1.60, 0.02), (1.60, 0.05), (1.35, 0.03), (2.0, 0.04)])
def test_rau_bandgap_recovers_centre_and_width_of_the_edge(eg, sigma):
    eqe = sigmoid_edge(E, eg, sigma)
    r = ec.bandgap_rau(E, eqe)
    assert r["Eg"] == pytest.approx(eg, abs=0.005)
    # P(E) is a Gaussian of width sigma; its std over the half-maximum window
    # is sigma * 0.59 (truncated normal at +-1.177 sigma)
    assert r["sigma"] == pytest.approx(0.59 * sigma, rel=0.15)
    assert r["E_inflection"] == pytest.approx(eg, abs=0.01)


def test_rau_bandgap_ignores_the_high_energy_fall_off():
    """Real EQE spectra drop again at high energy (parasitic absorption); that
    negative-slope region must not be mistaken for the band edge."""
    eqe = sigmoid_edge(E, 1.6, 0.03) * sigmoid_edge(-E, -3.2, 0.2)
    assert ec.bandgap_rau(E, eqe)["Eg"] == pytest.approx(1.6, abs=0.01)
    assert ec.bandgap_inflection(E, eqe) == pytest.approx(1.6, abs=0.01)


def test_bandgap_on_degenerate_input_is_nan():
    assert np.isnan(ec.bandgap_rau([1, 2], [0.1, 0.2])["Eg"])
    assert np.isnan(ec.bandgap_inflection([], []))


# ---------------------------------------------------------------------------
# Urbach
# ---------------------------------------------------------------------------
def test_urbach_energy_from_an_exponential_tail():
    eu = 0.020      # 20 meV
    eg = 1.6
    eqe = np.where(E < eg, 0.9 * np.exp((E - eg) / eu), 0.9)
    lo, hi = ec.auto_urbach_window(E, eqe)
    assert lo < hi < eg
    r = ec.urbach_energy(E, eqe, lo, hi)
    assert r["Eu_meV"] == pytest.approx(20.0, rel=0.02)
    assert r["R2"] > 0.9999


def test_urbach_rejects_rising_or_short_windows():
    assert np.isnan(ec.urbach_energy(E, np.ones_like(E), 1.4, 1.5)["Eu_meV"])
    assert ec.urbach_energy([1, 2], [0.1, 0.2], 1, 2)["n_points"] < 3


# ---------------------------------------------------------------------------
# Detailed balance
# ---------------------------------------------------------------------------
def test_blackbody_flux_has_the_planck_form():
    e = np.array([0.5, 1.0, 1.5])
    got = ec.blackbody_photon_flux(e, 300.0)
    ej = e * Q
    expected = 2 * math.pi * ej ** 2 / (H ** 3 * C ** 2) / np.expm1(ej / (KB * 300.0)) * Q
    assert np.allclose(got, expected, rtol=1e-12)


def test_shockley_queisser_limit_at_1p34_ev():
    """The SQ optimum under AM1.5G is 33.7% at Eg ~ 1.34 eV (Rühle 2016):
    Jsc 35.4 mA/cm^2, Voc 1.08 V."""
    sq = ec.shockley_queisser(1.34, 300.0)
    assert sq["Jsc_SQ"] == pytest.approx(35.4, abs=0.6)
    assert sq["Voc_SQ"] == pytest.approx(1.08, abs=0.02)
    assert sq["FF_SQ"] == pytest.approx(0.89, abs=0.01)
    assert sq["PCE_SQ"] == pytest.approx(33.7, abs=0.8)


def test_shockley_queisser_limit_at_perovskite_gap():
    sq = ec.shockley_queisser(1.60, 300.0)
    assert sq["Jsc_SQ"] == pytest.approx(25.4, abs=0.6)
    assert sq["Voc_SQ"] == pytest.approx(1.31, abs=0.03)
    assert sq["PCE_SQ"] == pytest.approx(30.1, abs=1.0)


def test_step_absorber_radiative_voc_equals_the_sq_voltage():
    """A step EQE = 1 above Eg is exactly the SQ absorber, so Voc,rad from
    the generic integral must reproduce Voc,SQ."""
    eg = 1.6
    eqe = (E >= eg).astype(float)
    rad = ec.radiative_limit(E, eqe, 300.0, extend_tail=False)
    sq = ec.shockley_queisser(eg, 300.0)
    assert rad["J0_rad_mA_cm2"] == pytest.approx(sq["J0_SQ"], rel=0.02)
    assert rad["Voc_rad_V"] == pytest.approx(sq["Voc_SQ"], abs=0.003)


def test_tail_states_lower_the_radiative_voc():
    eg = 1.6
    sharp = sigmoid_edge(E, eg, 0.01)
    broad = sigmoid_edge(E, eg, 0.06)
    v_sharp = ec.radiative_limit(E, sharp, extend_tail=False)["Voc_rad_V"]
    v_broad = ec.radiative_limit(E, broad, extend_tail=False)["Voc_rad_V"]
    assert v_broad < v_sharp


def test_tail_extrapolation_increases_j0rad_for_a_truncated_measurement():
    eg, eu = 1.6, 0.02
    eqe = np.where(E < eg, 0.9 * np.exp((E - eg) / eu), 0.9)
    m = E > eg - 0.15                         # measurement stops 150 meV below Eg
    a = ec.radiative_limit(E[m], eqe[m], extend_tail=False)
    b = ec.radiative_limit(E[m], eqe[m], extend_tail=True)
    assert b["tail_extended"]
    assert b["J0_rad_mA_cm2"] > a["J0_rad_mA_cm2"]
    assert b["Eu_meV"] == pytest.approx(20.0, rel=0.05)


def test_voltage_loss_decomposition_adds_up():
    eg, voc_rad, voc = 1.60, 1.25, 1.10
    vl = ec.voltage_losses(eg, voc, voc_rad, 300.0)
    assert vl["dV1_SQ"] + vl["dV2_rad"] + vl["dV3_nonrad"] == pytest.approx(eg - voc, abs=1e-9)
    assert vl["dV3_nonrad"] == pytest.approx(0.15)
    kt = KB * 300.0 / Q
    assert vl["EQE_EL"] == pytest.approx(math.exp(-0.15 / kt), rel=1e-9)


def test_green_fill_factor_limits():
    assert ec.green_fill_factor(1.2) == pytest.approx(0.90, abs=0.01)
    assert np.isnan(ec.green_fill_factor(-0.1))


def test_analyze_eqe_returns_a_consistent_summary():
    eqe = 100.0 * sigmoid_edge(E, 1.6, 0.03)         # percent input
    r = ec.analyze_eqe(WL, eqe, voc_measured_v=1.10)
    assert r["Eg_Rau_eV"] == pytest.approx(1.6, abs=0.01)
    assert r["Jsc_mA_cm2"] == pytest.approx(ec.calculate_jsc(WL, eqe), rel=1e-9)
    assert r["Voc_rad_V"] < r["Voc_SQ"] < r["Eg_Rau_eV"]
    assert r["dV3_nonrad"] == pytest.approx(r["Voc_rad_V"] - 1.10, abs=1e-9)
