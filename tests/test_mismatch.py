"""Spectral mismatch factor (IEC 60904-7) and spectral match class
(IEC 60904-9) of a solar simulator (3.7). The checks rest on identities of
the definition and on one case integrated by hand from the ASTM G173 table."""
import numpy as np
import pandas as pd
import pytest

from scripts.EQE import eqe_core
from scripts.Mismatch import mismatch_core as m
from scripts.common import curve_batch as cb
from scripts.common import interpret_transport

import physiscore_cli as cli


def box(lo, hi, wl=None):
    """A response of 1 between lo and hi nm, 0 elsewhere (edges 0.01 nm wide)."""
    wl = np.array([280.0, lo - 0.01, lo, hi, hi + 0.01, 1300.0])
    return wl, np.array([0.0, 0.0, 1.0, 1.0, 0.0, 0.0])


def test_the_reference_spectrum_as_simulator_gives_one():
    tw, ty = m.example_test()
    r = m.analyse(tw, ty, sim_file=m.AM15G, ref_file=m.EXAMPLE)
    assert r["M"] == pytest.approx(1.0, abs=1e-12)
    assert r["Jsc_expected_sim"] == pytest.approx(r["Jsc_AM15_test"])
    assert r["sim_class"] == "A+"


def test_identical_cells_give_one_under_any_lamp():
    rw, rs = m.example_reference()
    r = m.analyse(rw, rs, sim_file=m.EXAMPLE, ref=(rw, rs), test_kind="sr")
    assert r["M"] == pytest.approx(1.0, abs=1e-12)


def test_m_does_not_depend_on_the_scale_of_any_input():
    tw, ty = m.example_test()
    sw, se = m.example_simulator()
    rw, rs = m.example_reference()
    base = m.analyse(tw, ty, sim=(sw, se), ref=(rw, rs))["M"]
    scaled = m.analyse(tw, 0.37 * ty, sim=(sw, 12.0 * se), ref=(rw, 4.0 * rs))["M"]
    assert scaled == pytest.approx(base, rel=1e-12)
    assert base < 0.95                    # the xenon lines of 800-1000 nm inflate the silicon reference current


def test_box_responses_against_the_g173_table():
    """Simulator = AM1.5G raised by 20 % below 600 nm; test cell responds at
    400-600 nm, reference cell at 400-800 nm. Then
    M = 1.2 I(400,800) / (1.2 I(400,600) + I(600,800)) with I the AM1.5G integrals."""
    wl, e = eqe_core.get_am15g_spectrum()

    def integral(a, b):
        g = np.arange(a, b + 1e-9, 0.01)
        return np.trapezoid(np.interp(g, wl, e), g)

    expect = 1.2 * integral(400, 800) / (1.2 * integral(400, 600) + integral(600, 800))
    sim_wl = np.arange(280.0, 1300.0, 0.25)
    sim = np.interp(sim_wl, wl, e) * np.where(sim_wl < 600.0, 1.2, 1.0)
    tw, ts = box(400.0, 600.0)
    rw, rs = box(400.0, 800.0)
    r = m.analyse(tw, ts, sim=(sim_wl, sim), ref=(rw, rs), test_kind="sr", ref_kind="sr")
    assert r["M"] == pytest.approx(expect, rel=2e-3)
    assert expect == pytest.approx(1.0 + 0.2 * integral(600, 800) / (1.2 * integral(400, 600) + integral(600, 800)))


def test_eqe_is_turned_into_responsivity():
    wl = np.array([400.0, 600.0, 800.0])
    np.testing.assert_allclose(m.to_sr(wl, np.array([50.0, 50.0, 50.0]), "eqe"), 0.5 * wl / 1239.84198)
    np.testing.assert_allclose(m.to_sr(wl, np.array([0.5, 0.5, 0.5]), "eqe"), 0.5 * wl / 1239.84198)
    tw, ty = m.example_test()
    r = m.analyse(tw, ty, sim_file=m.AM15G, ref_file=m.EXAMPLE, test_column="EQE (%)")
    assert r["Jsc_AM15_test"] == pytest.approx(eqe_core.calculate_jsc(tw, ty), rel=1e-4)
    assert m.response_kind("auto", "SR (A/W)", "eqe") == "sr"
    assert m.response_kind("auto", "Responsivity", "eqe") == "sr"
    assert m.response_kind("auto", "EQE (%)", "sr") == "eqe"
    assert m.response_kind("auto", "signal", "sr") == "sr"
    assert m.response_kind("eqe", "SR (A/W)", "sr") == "eqe"


def test_spectral_match_shares_and_classes():
    wl, e = eqe_core.get_am15g_spectrum()
    match = m.spectral_match(wl, e)
    ed2, ed3 = match["Ed. 2 (2007)"], match["Ed. 3 (2020)"]
    assert [round(r["ref_pct"], 1) for r in ed2["rows"]] == pytest.approx(list(m.IEC_ED2_TABLE), abs=0.06)
    assert all(16.55 < r["ref_pct"] < 16.8 for r in ed3["rows"])     # the 2020 intervals hold equal shares
    assert ed2["class"] == "A" and ed3["class"] == "A+"                # no A+ in edition 2
    assert m.classify(1.12, True) == "A+" and m.classify(1.13, True) == "A" and m.classify(1.13, False) == "A"
    assert m.classify(0.74, True) == "B" and m.classify(1.45, True) == "C" and m.classify(2.1, True) == "outside C"
    # 60 % more light in 400-500 nm: that interval leaves class A
    tilted = e * np.where((wl >= 400) & (wl <= 500), 1.6, 1.0)
    rows = m.spectral_match(wl, tilted)["Ed. 2 (2007)"]["rows"]
    assert rows[0]["ratio"] > 1.25 and rows[0]["class"] in ("B", "C")
    assert all(r["ratio"] < 1.0 for r in rows[1:])


def test_checks_name_short_spectra_and_misread_responses():
    tw, ty = m.example_test()
    sw, se = m.example_simulator()
    short = (sw >= 400) & (sw <= 760)
    r = m.analyse(tw, ty, sim=(sw[short], se[short]), ref_file=m.EXAMPLE)
    assert r["match"]["Ed. 2 (2007)"] is None and r["sim_class"] == ""
    assert any("covers only" in w for w in r["warnings"])
    assert any("no IEC 60904-9" in w for w in r["warnings"])
    # an EQE in per cent read as A/W
    r = m.analyse(tw, ty, sim_file=m.EXAMPLE, ref_file=m.EXAMPLE, test_kind="sr")
    assert any("EQE above 100 %" in w for w in r["warnings"])
    # a reference file that stops while the cell still responds
    rw, rs = m.example_reference()
    cut = rw <= 1000
    r = m.analyse(tw, ty, sim_file=m.EXAMPLE, ref=(rw[cut], rs[cut]))
    assert any("long-wavelength end" in w for w in r["warnings"])


def test_runner_cli_and_interpretation(tmp_path, capsys):
    tw, ty = m.example_test()
    cell = tmp_path / "cell_A_EQE.csv"
    pd.DataFrame({"Wavelength (nm)": tw, "EQE (%)": ty}).to_csv(cell, index=False)
    sw, se = m.example_simulator()
    lamp = tmp_path / "lamp.csv"
    pd.DataFrame({"Wavelength (nm)": sw, "Irradiance (W m-2 nm-1)": se}).to_csv(lamp, index=False)
    rw, rs = m.example_reference()
    ref = tmp_path / "WPVS_reference.csv"
    pd.DataFrame({"Wavelength (nm)": rw, "SR (A/W)": rs}).to_csv(ref, index=False)
    p = cb.parameters("mismatch", {"sim_file": str(lamp), "ref_file": str(ref)})
    item = cb.run_file("mismatch", str(cell), p)
    assert item["error"] == "" and item["checks"] == item["result"]["warnings"]     # an EQE file is expected here
    direct = m.analyse(tw, ty, sim_file=m.EXAMPLE, ref_file=m.EXAMPLE, test_column="EQE (%)")["M"]
    assert item["result"]["M"] == pytest.approx(direct, rel=1e-9)
    rep = interpret_transport.interpret_mismatch(item["result"], "cell A")
    top = next(f for f in rep.findings if f.topic == "Mismatch factor")
    assert top.level == "warning" and "less current" in top.text
    rc = cli.main(["mismatch", str(cell), "--sim", "AM1.5G", "--ref", str(ref)])
    out = capsys.readouterr().out
    assert rc == 0 and "Mismatch factor M" in out and " 1 " in out.replace("\n", " ")
    good = interpret_transport.interpret_mismatch(m.analyse(tw, ty, sim_file=m.AM15G, ref_file=str(ref)), "x")
    assert next(f for f in good.findings if f.topic == "Mismatch factor").level == "good"
    assert next(f for f in good.findings if f.topic == "Spectral match").level == "good"


def test_device_summary_divides_the_jv_current_by_m():
    """A cell measured on a simulator with M = 0.95 reads 5 % less current; with M
    entered the cross-check with the EQE compares Jsc/M (3.7)."""
    import math
    from scipy.special import erf
    from scripts.JV import jv_core
    from scripts.common import device_summary as ds
    from conftest import single_diode_jv
    wl = np.arange(300.0, 1100.0, 1.0)
    e = eqe_core.HC_EV_NM / wl
    eqe = 100 * 0.85 * 0.5 * (1 + erf((e - 1.60) / (0.03 * math.sqrt(2))))
    jsc_eqe = eqe_core.calculate_jsc(wl, eqe)
    v = np.round(np.arange(-0.2, 1.3, 0.005), 4)
    jv = jv_core.compute_jv_parameters(v, single_diode_jv(v, jph=0.95 * jsc_eqe, j0=1e-12, n=1.5, rs=2.0, rsh=5e3))
    plain = ds.summarize_device(jv, wl, eqe)
    assert plain["Jsc_mismatch_percent"] == pytest.approx(-5.0, abs=0.1)
    fixed = ds.summarize_device(jv, wl, eqe, spectral_mismatch=0.95)
    assert fixed["JV_Jsc_corrected"] == pytest.approx(jv["Jsc"] / 0.95)
    assert fixed["JV_PCE_corrected"] == pytest.approx(jv["PCE"] / 0.95)
    assert abs(fixed["Jsc_mismatch_percent"]) < 0.1
    assert any("mismatch factor M = 0.9500" in n for n in fixed["notes"])
    assert (ds.summary_table(fixed)["Quantity"] == "Jsc / M").any()
    assert "spectral_mismatch_M" not in plain
    with pytest.raises(ValueError, match="positive"):
        ds.summarize_device(jv, wl, eqe, spectral_mismatch=0.0)
