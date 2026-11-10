"""Band assignment and comparison for Raman/FTIR (3.4, replaces the Gemini requests)."""
import pandas as pd
import pytest

from scripts.common import vib_interpret as V


def layer(name, peaks, widths=None):
    fits = None
    if widths is not None:
        fits = pd.DataFrame({"center": peaks, "fwhm": widths})
    return {"name": name, "peaks": peaks, "fits": fits}


def test_library_assigns_known_ftir_bands():
    data = V.library_peak_data([1650.0, 2100.0], "FTIR")
    assert set(data) == {1650.0, 2100.0}
    for v in data.values():
        assert {"material", "assignment", "confidence"} <= set(v)


def test_pair_compare_reads_direction_and_width():
    a = layer("A", [520.0], [4.0])
    b = layer("B", [516.5], [6.0])
    out = V.pair_compare("Raman", a, 520.0, b, 516.5)
    assert out["shift_value"] == pytest.approx(-3.5)
    assert "lower wavenumber" in out["cause"]
    assert "+50 %" in out["detailed_explanation"] and "broadening" in out["detailed_explanation"]
    same = V.pair_compare("Raman", a, 520.0, b, 520.4)
    assert "No significant shift" in same["cause"]


def test_spectra_compare_counts_matched_new_and_missing_bands():
    a = layer("sample", [1000.0, 1460.0, 2950.0])
    b = layer("reference", [1003.0, 1600.0, 2950.0])
    out = V.spectra_compare("FTIR", a, b, tolerance=8.0)
    assert out["summary"].startswith("2 bands in common")
    joined = " ".join(out["differences"])
    assert "new band at 1460" in joined and "band at 1600" in joined


def test_interpret_layers_builds_a_report_with_shifts():
    layers = [layer("ref", [1000.0, 1600.0], [10.0, 12.0]), layer("film", [1004.0, 1600.0], [14.0, 12.0])]
    rep = V.interpret_layers("FTIR", layers, target=1, reference=0)
    assert rep.technique == "FTIR" and rep.findings
