"""Impedance: distribution of relaxation times (3.6.0), checked against
spectra whose distribution is known (ideal RC arcs: delta functions of area R
at tau = RC; an R||CPE arc: the Cole-Cole distribution)."""
import numpy as np
import pandas as pd
import pytest

from scripts.EIS import eis_core as eis
from scripts.common import curve_batch as cb
from scripts.common import interpret_transport as rules

F = np.geomspace(1e6, 0.1, 71)


def cole_cole(tau, r, tau0, alpha):
    lt = np.log(tau / tau0)
    th = (1.0 - alpha) * np.pi
    return r / (2 * np.pi) * np.sin(th) / (np.cosh(alpha * lt) - np.cos(th))


@pytest.mark.parametrize("noise,seed", [(0.003, 0), (0.003, 1), (0.01, 0)])
def test_two_rc_arcs_give_two_peaks_with_their_resistances(noise, seed):
    f, zr, zi = eis.simulate("R(RC)(RC)", (10.0, 50.0, 2e-7, 200.0, 5e-5), F, noise=noise, seed=seed)
    d = eis.drt(f, zr + 1j * zi)
    assert d["n_processes"] == 2
    p1, p2 = d["peaks"]
    assert p1["tau_s"] == pytest.approx(1e-5, rel=0.05) and p2["tau_s"] == pytest.approx(1e-2, rel=0.05)
    assert p1["R"] == pytest.approx(50.0, rel=0.03) and p2["R"] == pytest.approx(200.0, rel=0.03)
    assert d["R_inf"] == pytest.approx(10.0, abs=1.2)


def test_cpe_arc_follows_the_cole_cole_distribution():
    r, tau0, alpha = 100.0, 1e-3, 0.8
    f, zr, zi = eis.simulate("R(RQ)", (5.0, r, tau0 ** alpha / r, alpha), F, noise=0.003, seed=0)
    d = eis.drt(f, zr + 1j * zi)
    assert d["n_processes"] == 1
    assert d["peaks"][0]["tau_s"] == pytest.approx(tau0, rel=0.08)
    assert d["peaks"][0]["R"] == pytest.approx(r, rel=0.02)
    true = cole_cole(d["tau"], r, tau0, alpha)
    assert np.linalg.norm(d["gamma"] - true) / np.linalg.norm(true) < 0.15


def test_broad_arcs_are_not_split_into_extra_processes():
    """The default demo spectrum: two CPE arcs (alpha 0.95 and 0.85). A side
    lobe of the broad low-frequency distribution is merged into its peak."""
    for seed in range(3):
        f, zr, zi = eis.simulate(seed=seed)
        d = eis.drt(f, zr + 1j * zi)
        assert d["n_processes"] == 2
        assert [pk["R"] for pk in d["peaks"]] == pytest.approx([200.0, 1500.0], rel=0.03)


def test_noise_free_spectrum_is_reproduced():
    f, zr, zi = eis.simulate("R(RC)(RC)", (10.0, 50.0, 2e-7, 200.0, 5e-5), F, noise=0.0)
    d = eis.drt(f, zr + 1j * zi)
    assert d["rms_pct"] < 0.05
    assert d["R_pol"] == pytest.approx(250.0, rel=0.002)


def test_drt_in_the_analysis_rows_tables_and_interpretation(tmp_path):
    f, zr, zi = eis.simulate()
    r = eis.analyse(f, zr, zi)
    assert r["drt"]["n_processes"] == 2
    names = [row[0] for row in eis.summary_rows(r)]
    assert "DRT processes" in names and "DRT peak 2: tau" in names
    path = tmp_path / "cell.csv"
    pd.DataFrame({"Freq (Hz)": f, "Z' (Ohm)": zr, "Z'' (Ohm)": zi}).to_csv(path, index=False)
    p = cb.parameters("eis", {})
    res = cb.analyse("eis", cb.load("eis", str(path), p), p)
    tables = cb.tables("eis", {}, res)
    assert list(tables["DRT"].columns) == ["tau (s)", "f = 1/(2 pi tau) (Hz)", "gamma (Ohm)"]
    rep = rules.interpret_eis(r, "cell")
    assert any(fd.topic == "Distribution of relaxation times" and fd.level == "good" for fd in rep.findings)


def test_three_processes_against_a_two_arc_circuit():
    """A third, well separated arc the two-arc circuits cannot hold: the DRT
    counts three and the interpretation says the circuit merges them."""
    z = eis.z_model("R(RC)(RC)", (10.0, 50.0, 2e-7, 200.0, 5e-5), F)
    z = z + 400.0 / (1 + 1j * 2 * np.pi * F * 1.0)          # tau = 1 s
    rng = np.random.default_rng(0)
    z = z + np.abs(z) * 0.002 * (rng.standard_normal(len(F)) + 1j * rng.standard_normal(len(F)))
    r = eis.analyse(F, z.real, z.imag)
    assert r["drt"]["n_processes"] == 3
    rep = rules.interpret_eis(r, "cell")
    f_ = [fd for fd in rep.findings if fd.topic == "Distribution of relaxation times"][0]
    assert f_.level == "note" and "merges" in f_.text
