"""Command-line interface: each sub-command runs on synthetic data and
produces valid JSON."""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

from conftest import single_diode_jv, gaussian, pseudo_voigt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import physiscore_cli as cli  # noqa: E402


def run(capsys, argv):
    cli.main(argv)
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in argv else out


def test_sq_command(capsys):
    r = run(capsys, ["sq", "1.34", "--json"])
    assert 32.5 < r["PCE_SQ"] < 34.5
    text = run(capsys, ["sq", "1.6"])
    assert "Shockley-Queisser" in text


def test_jv_command_writes_excel_and_json(tmp_path, capsys):
    v = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    j = single_diode_jv(v)
    for name in ("Ref 1.txt", "Ref 2.txt"):
        rows = "\n".join(f"{vv:.4f}\t{-jj * 0.04 / 1000:.9f}" for vv, jj in zip(v, j))
        (tmp_path / name).write_text("Vmeas\tImeas\n" + rows + "\n", encoding="utf-8")
    r = run(capsys, ["jv", str(tmp_path), "--area", "0.04", "--json"])
    assert os.path.exists(r["excel"])
    assert r["curve_analysis"][0]["n (diode fit)"] == pytest.approx(1.5, abs=0.05)
    assert r["cell_area_cm2"] == 0.04


def test_eqe_and_abs_commands(tmp_path, capsys):
    from scipy.special import erf
    wl = np.arange(300.0, 1100.0, 1.0)
    e = 1239.84198 / wl
    eqe = 90 * 0.5 * (1 + erf((e - 1.6) / (0.03 * np.sqrt(2))))
    f = tmp_path / "eqe.csv"
    pd.DataFrame({"Wavelength (nm)": wl, "EQE (%)": eqe}).to_csv(f, index=False)
    r = run(capsys, ["eqe", str(f), "--voc", "1.1", "--json"])
    assert r["Eg_Rau_eV"] == pytest.approx(1.6, abs=0.01)
    assert r["dV3_nonrad"] == pytest.approx(r["Voc_rad_V"] - 1.1, abs=1e-6)

    wl2 = np.arange(350.0, 1000.0, 1.0)
    e2 = 1239.84198 / wl2
    a = np.where(e2 >= 1.6, 1.2 * np.sqrt(np.clip(e2 - 1.6 + 0.002, 0, None)) / e2,
                 1.2 * np.sqrt(0.002) / 1.6 * np.exp((e2 - 1.6) / 0.02)) + 0.02
    f2 = tmp_path / "abs.xlsx"
    pd.DataFrame({"nm": wl2, "A": a}).to_excel(f2, index=False)
    r2 = run(capsys, ["abs", str(f2), "--json"])
    assert r2["Eg_Tauc_eV"] == pytest.approx(1.6, abs=0.02)


def test_xrd_pl_vib_commands(tmp_path, capsys):
    x = np.round(np.arange(10.0, 40.0, 0.02), 4)
    y = 40 + pseudo_voigt(x, 1000, 28.2, 0.15, 0.5) + pseudo_voigt(x, 700, 33.0, 0.18, 0.5)
    f = tmp_path / "xrd.csv"
    pd.DataFrame({"2theta": x, "I": y}).to_csv(f, index=False)
    out_csv = tmp_path / "peaks.csv"
    r = run(capsys, ["xrd", str(f), "--out", str(out_csv), "--json"])
    assert len(r["peaks"]) == 2 and out_csv.exists()
    assert r["williamson_hall"]["n_peaks"] == 2

    wl = np.round(np.arange(600.0, 900.0, 0.5), 4)
    pl = gaussian(wl, 1000, 750, 40) + gaussian(wl, 300, 820, 80)
    f2 = tmp_path / "pl.csv"
    pd.DataFrame({"nm": wl, "I": pl}).to_csv(f2, index=False)
    r2 = run(capsys, ["pl", str(f2), "--rigidity", "0", "--json"])
    assert r2["peak_nm"] == pytest.approx(750, abs=3)
    assert len(r2["components"]) == 2

    from scripts.common import spectral as sp
    xr = np.arange(100.0, 2000.0, 1.0)
    raman = 30 + sp.lorentzian(xr, 100, 520.5, 6) + sp.lorentzian(xr, 60, 1580, 25)
    f3 = tmp_path / "raman.csv"
    pd.DataFrame({"shift": xr, "I": raman}).to_csv(f3, index=False)
    r3 = run(capsys, ["vib", str(f3), "--technique", "raman", "--prominence", "5", "--json"])
    assert len(r3["positions"]) == 2
    assert any("Si" in str(a["material"]) for a in r3["assignments"])


def test_sem_stats_command(capsys):
    r = run(capsys, ["sem-stats", "100", "120", "140", "--json"])
    assert r["n"] == 3 and r["std"] == pytest.approx(20.0)


def test_device_and_batch_commands(tmp_path, capsys):
    from scipy.special import erf
    v = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    j = single_diode_jv(v)
    jv_f = tmp_path / "cell.csv"
    pd.DataFrame({"Voltage (V)": v, "J (mA/cm2)": -j}).to_csv(jv_f, index=False)
    wl = np.arange(300.0, 1100.0, 1.0)
    e = 1239.84198 / wl
    for i, eg in enumerate((1.55, 1.60)):
        pd.DataFrame({"nm": wl, "EQE": 85 * 0.5 * (1 + erf((e - eg) / (0.03 * np.sqrt(2))))}).to_csv(
            tmp_path / f"eqe_{i}.csv", index=False)
    out = tmp_path / "dev.xlsx"
    r = run(capsys, ["device", "--jv", str(jv_f), "--eqe", str(tmp_path / "eqe_1.csv"), "--out", str(out), "--json"])
    assert r["EQE_Eg"] == pytest.approx(1.60, abs=0.01)
    assert r["dV1_SQ"] + r["dV2_rad"] + r["dV3_nonrad"] == pytest.approx(r["Voc_deficit"], abs=1e-9)
    assert out.exists() and (tmp_path / "dev.analysis.json").exists()

    table = tmp_path / "batch.csv"
    r2 = run(capsys, ["batch", "eqe", str(tmp_path), "--out", str(table), "--json"])
    rows = r2["rows"]
    eg = sorted(round(x["Eg Rau (eV)"], 2) for x in rows if x.get("Eg Rau (eV)") is not None)
    assert eg == [1.55, 1.6]                         # cell.csv is analysed too but has no EQE edge
    assert "dev.xlsx" not in {x["File"] for x in rows}   # exports with a side-car are never re-read
    assert table.exists() and (tmp_path / "batch.analysis.json").exists()
