"""Raman / FTIR shared processing: unit conversion, baseline, band detection
and fitting, shift table and the indicative band library."""
import numpy as np
import pandas as pd
import pytest

from scripts.common import spectral as sp
from scripts.common import vibrational as vb

X = np.arange(100.0, 2000.0 + 1e-9, 1.0)


def raman_like(shifts=(520.5, 1350.0, 1580.0), heights=(100.0, 40.0, 60.0), widths=(6.0, 40.0, 25.0),
               fluorescence=True):
    y = np.zeros_like(X)
    for c, h, w in zip(shifts, heights, widths):
        y += sp.lorentzian(X, h, c, w)
    if fluorescence:
        y += 30.0 + 40.0 * np.exp(-((X - 1200.0) / 900.0) ** 2)
    return y


def test_transmittance_absorbance_round_trip():
    t = np.array([100.0, 50.0, 10.0])
    a = vb.transmittance_to_absorbance(t)
    assert a == pytest.approx([0.0, 0.30103, 1.0], abs=1e-5)
    assert vb.absorbance_to_transmittance(a) == pytest.approx(t, rel=1e-9)
    assert vb.transmittance_to_absorbance([1.0, 0.5], percent=False)[1] == pytest.approx(0.30103, abs=1e-5)


def test_preprocess_removes_fluorescence_and_keeps_bands():
    y = raman_like()
    prep = vb.preprocess(X, y, baseline="arpls", lam=1e5)
    i = int(np.argmin(np.abs(X - 520.5)))
    assert prep["corrected"][i] == pytest.approx(100.0, rel=0.08)
    off = (X > 700) & (X < 1200)
    assert np.max(np.abs(prep["corrected"][off])) < 6.0


def test_preprocess_dips_mode_for_transmittance():
    t = 95.0 - 40.0 * sp.gaussian(X, 1.0, 1700.0, 30.0) - 20.0 * sp.gaussian(X, 1.0, 1050.0, 40.0)
    prep = vb.preprocess(X, t, baseline="arpls", dips=True)
    pos, _, _ = vb.detect_bands(prep["x"], prep["corrected"], prominence_frac=0.1)
    assert sorted(np.round(pos).tolist()) == [1050.0, 1700.0]


def test_band_detection_and_lorentzian_fit():
    y = raman_like(fluorescence=False)
    pos, idx, prom = vb.detect_bands(X, y, prominence_frac=0.05)
    assert len(pos) == 3
    fits = vb.fit_bands(X, y, pos, shape="lorentzian")
    assert len(fits) == 3
    row = fits.iloc[(fits["center"] - 520.5).abs().argmin()]
    assert row["center"] == pytest.approx(520.5, abs=0.2)
    assert row["fwhm"] == pytest.approx(6.0, rel=0.05)
    assert row["fitted"]
    # overlapping D/G bands are fitted together: both widths are recovered
    d = fits.iloc[(fits["center"] - 1350).abs().argmin()]
    g = fits.iloc[(fits["center"] - 1580).abs().argmin()]
    assert d["fwhm"] == pytest.approx(40.0, rel=0.1)
    assert g["fwhm"] == pytest.approx(25.0, rel=0.1)


def test_shift_table_pairs_bands_and_lists_unmatched():
    ref = [520.5, 1350.0, 1580.0]
    smp = [518.0, 1352.5, 1700.0]
    df = vb.peak_shift_table(ref, smp, tolerance=10.0, reference_name="pristine", sample_name="annealed")
    matched = df.dropna(subset=["shift"])
    assert matched["shift"].round(1).tolist() == [-2.5, 2.5]
    assert df["reference"].isna().sum() == 1        # 1700 only in the sample
    assert df["sample"].isna().sum() == 1           # 1580 only in the reference
    assert set(df["reference_name"]) == {"pristine"}


def test_library_loads_and_assigns_known_bands():
    lib = vb.load_library()
    assert len(lib) > 40
    techs = {e["technique"] for e in lib}
    assert techs == {"raman", "ftir"}
    df = vb.assign_bands([520.3, 1582.0, 3000.0], "raman")
    si = df[df["position"] == 520.3]
    assert "Si" in " ".join(si["material"].astype(str))
    g = df[df["position"] == 1582.0]
    assert any("G band" in a for a in g["assignment"])
    none = df[df["position"] == 3000.0]
    assert none["note"].iloc[0] == "no library match"


def test_library_ranges_match_ftir_regions():
    df = vb.assign_bands([1735.0, 3400.0], "ftir")
    co = df[df["position"] == 1735.0]
    assert any("C=O" in a for a in co["assignment"])
    oh = df[df["position"] == 3400.0]
    assert any("O-H" in a or "N-H" in a for a in oh["assignment"])


def test_analyze_layer_pipeline_end_to_end():
    res = vb.analyze_layer(X, raman_like(), technique="raman")
    assert len(res["positions"]) == 3
    assert not res["fits"].empty
    assert not res["assignments"].empty
    assert isinstance(res["fits"], pd.DataFrame)
