"""End-to-end J-V folder processing on synthetic source-meter exports:
hysteresis sheet, diode-fit columns and Excel output."""
import os

import numpy as np
import pandas as pd
import pytest

from conftest import single_diode_jv
from scripts.JV import jv_core
from scripts.Dark_JV import dark_jv_core

AREA = 0.04


def write_export(path, v, j_mA_cm2, summary=True):
    """Mimic the instrument file: optional summary block, then Vmeas/Imeas
    rows with the current in amperes and the instrument's sign convention."""
    lines = []
    if summary:
        lines += ["Voc V\tVoc_mA\tJsc mA/cm2\tx\ty\tz\tFill Factor\tEfficiency",
                  "0.9\t0\t21.9\t0\t0\t0\t77.0\t15.2"]
    lines.append("Vmeas\tImeas")
    for vv, jj in zip(v, j_mA_cm2):
        lines.append(f"{vv:.4f}\t{-jj * AREA / 1000.0:.9f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def jv_folder(tmp_path):
    v = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    j_f = single_diode_jv(v, jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0)
    j_r = single_diode_jv(v, jph=22.0, j0=3e-10, n=1.5, rs=1.5, rsh=4000.0)
    # device 1: swept both ways (hysteresis); device 2: forward only
    write_export(tmp_path / "Ref 1.txt", np.concatenate([v, v[::-1]]), np.concatenate([j_f, j_r[::-1]]))
    write_export(tmp_path / "Ref 2.txt", v, j_f)
    write_export(tmp_path / "Target 1.txt", v, 0.9 * j_f, summary=False)
    return tmp_path, v, j_f, j_r


def test_folder_processing_reports_hysteresis_and_diode_fit(jv_folder):
    folder, v, j_f, j_r = jv_folder
    data = jv_core.process_jv_directory(str(folder), area_cm2=AREA)
    assert "error" not in data
    assert data["total_files"] == 3
    ca = data["curve_analysis"].set_index("Filename")
    assert set(ca.index) == {"Ref 1", "Ref 2", "Target 1"}
    assert "n (diode fit)" in ca.columns
    assert ca.loc["Ref 2", "n (diode fit)"] == pytest.approx(1.5, abs=0.05)
    assert ca.loc["Ref 2", "Rs fit (Ohm cm2)"] == pytest.approx(2.0, rel=0.1)
    assert "Ref 2" in data["diode_fits"]

    hy = data["hysteresis_df"]
    assert list(hy["Filename"]) == ["Ref 1"]
    row = hy.iloc[0]
    pf = jv_core.compute_jv_parameters(v, j_f)
    pr = jv_core.compute_jv_parameters(v, j_r)
    assert row["PCE fwd (%)"] == pytest.approx(pf["PCE"], abs=0.01)
    assert row["PCE rev (%)"] == pytest.approx(pr["PCE"], abs=0.01)
    assert row["HI (%)"] == pytest.approx(jv_core.hysteresis_index(pr["PCE"], pf["PCE"]), abs=0.05)

    # a file without the instrument summary gets its summary from the curve
    sd = data["summary_df"].set_index("Filename")
    assert sd.loc["Target 1", "Summary source"] == "curve"
    assert sd.loc["Ref 1", "Summary source"] == "instrument"
    assert float(sd.loc["Target 1", "PCE (%)"]) == pytest.approx(0.9 * pf["PCE"], abs=0.02)
    assert ca.loc["Target 1", "PCE (%)"] == pytest.approx(0.9 * pf["PCE"], rel=0.02)


def test_excel_export_contains_the_new_sheets(jv_folder):
    folder, *_ = jv_folder
    data = jv_core.process_jv_directory(str(folder), area_cm2=AREA)
    out = folder / "result.xlsx"
    saved = jv_core.save_to_excel(data, str(out))
    assert saved == str(out) and out.exists()
    sheets = pd.ExcelFile(out).sheet_names
    for name in ("CombinedData", "SummaryTable", "BestPerformance", "CurveAnalysis", "Statistics", "Hysteresis"):
        assert name in sheets
    hy = pd.read_excel(out, sheet_name="Hysteresis")
    assert "HI (%)" in hy.columns and len(hy) == 1


def test_diode_fit_can_be_switched_off(jv_folder):
    folder, *_ = jv_folder
    data = jv_core.process_jv_directory(str(folder), area_cm2=AREA, diode_fit=False)
    assert "n (diode fit)" not in data["curve_analysis"].columns
    assert data["diode_fits"] == {}


def test_dark_folder_processing_adds_full_fit_columns(tmp_path):
    v = np.round(np.arange(-0.5, 1.2001, 0.005), 4)
    j = dark_jv_core.dark_diode_current(v, 2e-9, 1.8, 5.0, 5e4)
    lines = ["RShunt ohms\tx", "12345\t0", "Vmeas\tImeas"]
    lines += [f"{vv:.4f}\t{-jj * AREA / 1000.0:.10f}" for vv, jj in zip(v, j)]
    (tmp_path / "dark 1.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data = dark_jv_core.process_dark_jv_directory(str(tmp_path), area_cm2=AREA)
    assert "error" not in data
    sd = data["summary_df"].iloc[0]
    assert sd["n (full fit)"] == pytest.approx(1.8, abs=0.05)
    assert sd["Rs fit (Ohm cm2)"] == pytest.approx(5.0, rel=0.1)
    assert "dark 1" in data["diode_fits"]
