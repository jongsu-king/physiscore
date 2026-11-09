"""3.1.0 additions: generic J-V files, curve-derived summaries, side-car
files, XRD reference matching and the cross-technique device summary."""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest
from scipy.special import erf

from conftest import pseudo_voigt, single_diode_jv
from scripts.common import device_summary as ds
from scripts.common import iv_io, provenance
from scripts.EQE import eqe_core
from scripts.JV import jv_core
from scripts.Dark_JV import dark_jv_core
from scripts.XRD import xrd_core

V = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
J = single_diode_jv(V)            # photocurrent positive


# ---------------------------------------------------------------------------
# generic I-V files
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("header,scale,expect", [
    (["Voltage (V)", "J (mA/cm2)"], 1.0, "density"),
    (["V", "Current (A)"], 0.04 / 1000.0, "A"),
    (["Bias", "I (mA)"], 0.04, "mA"),
])
def test_generic_reader_recognises_columns_and_units(tmp_path, header, scale, expect):
    f = tmp_path / "cell.csv"
    pd.DataFrame({header[0]: V, header[1]: J * scale}).to_csv(f, index=False)
    v, j, how = iv_io.read_generic_iv(str(f), area_cm2=0.04)
    assert np.allclose(v, V)
    assert np.allclose(np.abs(j), np.abs(J), rtol=1e-9)
    assert float(np.interp(0.0, v, j)) < 0          # plotting convention
    assert expect in how or ("density" in how and expect == "density")


def test_generic_reader_without_headers_and_with_preamble(tmp_path):
    f = tmp_path / "cell.dat"
    rows = "\n".join(f"{a}\t{b}" for a, b in zip(V, -J))
    f.write_text("instrument XYZ\noperator: test\n\n" + rows + "\n", encoding="utf-8")
    v, j, _ = iv_io.read_generic_iv(str(f), 0.04)
    assert len(v) == len(V) and np.allclose(j, -J)


def test_xlsx_input_and_result_workbooks_are_skipped(tmp_path):
    pd.DataFrame({"V (V)": V, "J (mA/cm2)": -J}).to_excel(tmp_path / "Cell A 1.xlsx", index=False)
    pd.DataFrame({"V (V)": V, "J (mA/cm2)": -0.9 * J}).to_csv(tmp_path / "Cell B 1.csv", index=False)
    data = jv_core.process_jv_directory(str(tmp_path), area_cm2=0.04, diode_fit=False)
    assert data["total_files"] == 2
    out = tmp_path / f"{tmp_path.name}.xlsx"
    jv_core.save_to_excel(data, str(out))
    assert iv_io.is_result_workbook(str(out))
    again = jv_core.process_jv_directory(str(tmp_path), area_cm2=0.04, diode_fit=False)
    assert again["total_files"] == 2                # the result workbook is not re-read
    sd = again["summary_df"].set_index("Filename")
    pce = jv_core.compute_jv_parameters(V, J)["PCE"]
    assert float(sd.loc["Cell A 1", "PCE (%)"]) == pytest.approx(pce, abs=0.02)
    assert set(sd["Summary source"]) == {"curve"}


def test_dark_core_reads_generic_files(tmp_path):
    vd = np.round(np.arange(0.0, 1.2001, 0.005), 4)
    jd = dark_jv_core.dark_diode_current(vd, 2e-9, 1.8, 5.0, 5e4)
    pd.DataFrame({"Voltage": vd, "J (mA/cm2)": jd}).to_csv(tmp_path / "dark 1.csv", index=False)
    data = dark_jv_core.process_dark_jv_directory(str(tmp_path), area_cm2=0.04)
    assert data["summary_df"].iloc[0]["n (full fit)"] == pytest.approx(1.8, abs=0.05)


# ---------------------------------------------------------------------------
# side-cars
# ---------------------------------------------------------------------------
def test_excel_export_writes_a_sidecar(tmp_path):
    rows = "\n".join(f"{a:.4f}\t{-b * 0.04 / 1000:.9f}" for a, b in zip(V, J))
    (tmp_path / "Ref 1.txt").write_text("Vmeas\tImeas\n" + rows + "\n", encoding="utf-8")
    data = jv_core.process_jv_directory(str(tmp_path), area_cm2=0.04)
    out = jv_core.save_to_excel(data, str(tmp_path / "res.xlsx"))
    side = provenance.sidecar_path(out)
    rec = provenance.read_sidecar(side)
    assert rec["tool"] == "J-V (light)"
    assert rec["parameters"]["cell_area_cm2"] == 0.04
    assert rec["inputs"] == [str(tmp_path.resolve())] or rec["inputs"][0].endswith(tmp_path.name)
    assert rec["results"]["total_files"] == 1
    assert "physiscore_version" in rec and "timestamp" in rec


def test_sidecar_serialises_numpy_and_nan(tmp_path):
    target = tmp_path / "x.xlsx"
    target.write_bytes(b"")
    path = provenance.write_sidecar(str(target), "test", parameters={"a": np.float64(1.5), "b": float("nan")},
                                    results={"arr": np.arange(3), "df": pd.DataFrame({"q": [1.0, np.nan]})})
    rec = json.loads(open(path, encoding="utf-8").read())
    assert rec["parameters"] == {"a": 1.5, "b": None}
    assert rec["results"]["arr"] == [0, 1, 2]
    assert rec["results"]["df"] == [{"q": 1.0}, {"q": None}]


# ---------------------------------------------------------------------------
# XRD reference matching
# ---------------------------------------------------------------------------
def _cubic_reference(a0=6.28, path=None):
    hkl = [(1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0), (2, 1, 1), (2, 2, 0)]
    d = a0 / np.sqrt(np.sum(np.asarray(hkl, float) ** 2, axis=1))
    tt = 2 * np.degrees(np.arcsin(xrd_core.LAMBDA_CU / (2 * d)))
    df = pd.DataFrame({"2theta": tt, "h": [h for h, _, _ in hkl], "k": [k for _, k, _ in hkl],
                       "l": [l for _, _, l in hkl], "I": [100, 60, 20, 40, 15, 25, 30]})
    if path is not None:
        df.to_csv(path, index=False)
    return df


def test_reference_loader_accepts_2theta_or_d(tmp_path):
    _cubic_reference(path=tmp_path / "ref.csv")
    ref = xrd_core.load_reference_peaks(str(tmp_path / "ref.csv"))
    assert list(ref["hkl"][:3]) == ["100", "110", "111"]
    assert ref["I_rel"].max() == pytest.approx(100.0)
    d_only = pd.DataFrame({"d (A)": ref["d"], "hkl": ref["hkl"]})
    d_only.to_csv(tmp_path / "ref_d.csv", index=False)
    ref2 = xrd_core.load_reference_peaks(str(tmp_path / "ref_d.csv"))
    assert np.allclose(ref2["2Theta"], ref["2Theta"], atol=1e-9)


def test_reference_matching_finds_phase_strain_and_impurity(tmp_path):
    a_film = 6.28 * 1.003                        # 0.3 % tensile strain
    ref_df = _cubic_reference(6.28, tmp_path / "ref.csv")
    ref = xrd_core.load_reference_peaks(str(tmp_path / "ref.csv"))
    film = _cubic_reference(a_film)
    x = np.round(np.arange(10.0, 50.0, 0.01), 4)
    y = 50.0 + sum(pseudo_voigt(x, h * 10, t, 0.12, 0.5) for t, h in zip(film["2theta"], film["I"]))
    y = y + pseudo_voigt(x, 600, 12.7, 0.10, 0.5)      # PbI2-like impurity reflection
    peaks, _ = xrd_core.detect_peaks_and_fit(x, y)
    m = xrd_core.match_reference(peaks, ref, tolerance_deg=0.3)
    assert m["n_matched"] == m["n_reference_lines"] == 7
    assert m["coverage"] == pytest.approx(1.0)
    assert m["mean_strain"] == pytest.approx(0.003, rel=0.05)
    assert m["mean_shift_deg"] < 0                     # larger d -> lower angle
    assert len(m["unassigned"]) == 1
    assert m["unassigned"].iloc[0]["2Theta"] == pytest.approx(12.7, abs=0.02)


def test_pattern_normalisation():
    x = np.linspace(0, 10, 101)
    pats = xrd_core.normalize_patterns([(x, 2 * np.ones_like(x)), (x, np.linspace(0, 4, 101))], "max")
    assert pats[0][1].max() == pytest.approx(1.0) and pats[1][1].max() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# device summary
# ---------------------------------------------------------------------------
WL = np.arange(300.0, 1100.0, 1.0)
E = eqe_core.HC_EV_NM / WL


def _eqe(eg=1.60, sigma=0.03, height=0.85):
    return 100 * height * 0.5 * (1 + erf((E - eg) / (sigma * math.sqrt(2))))


def test_device_summary_combines_techniques_consistently():
    jv = jv_core.compute_jv_parameters(V, J)
    eqe = _eqe()
    s = ds.summarize_device(jv, WL, eqe, eg_abs_ev=1.61, pl_peak_ev=1.58,
                            diode_fit=jv_core.fit_single_diode(V, J))
    jsc_eqe = eqe_core.calculate_jsc(WL, eqe)
    assert s["EQE_Jsc"] == pytest.approx(jsc_eqe)
    assert s["Jsc_mismatch_percent"] == pytest.approx(100 * (jv["Jsc"] - jsc_eqe) / jsc_eqe)
    assert s["Eg_reference_source"] == "EQE (dEQE/dE)"
    assert s["Eg_spread_meV"] == pytest.approx(1000 * (1.61 - 1.58), abs=5)
    assert s["Stokes_shift_meV"] == pytest.approx(1000 * (s["EQE_Eg"] - 1.58))
    total = s["dV1_SQ"] + s["dV2_rad"] + s["dV3_nonrad"]
    assert total == pytest.approx(s["Voc_deficit"], abs=1e-9)
    assert 0 < s["PCE_fraction_of_SQ"] < 1
    assert s["diode_n"] == pytest.approx(1.5, abs=0.05)
    tbl = ds.summary_table(s)
    assert {"Quantity", "Value", "Unit", "Origin"} <= set(tbl.columns)
    assert (tbl["Quantity"] == "Jsc mismatch (J-V vs EQE)").any()
    lb = ds.loss_breakdown(s)
    assert sum(lb.values()) == pytest.approx(s["Voc_deficit"], abs=1e-9)


def test_device_summary_warns_on_mismatch_and_gap_spread():
    jv = jv_core.compute_jv_parameters(V, J)
    s = ds.summarize_device(jv, WL, _eqe(height=0.5), eg_abs_ev=1.75)
    texts = " ".join(s["warnings"])
    assert "differ by" in texts and "Band gaps" in texts


def test_device_summary_with_partial_inputs():
    s = ds.summarize_device(jv=jv_core.compute_jv_parameters(V, J))
    assert math.isnan(s["Jsc_mismatch_percent"])
    assert "SQ_PCE" not in s
    s2 = ds.summarize_device(eg_abs_ev=1.6)
    assert s2["SQ_PCE"] == pytest.approx(eqe_core.shockley_queisser(1.6)["PCE_SQ"])
