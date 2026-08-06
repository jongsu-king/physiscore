"""Configuration resolution and the cell-area plumbing that depends on it.

``cell_area_cm2`` scales Jsc and therefore PCE linearly, so the value that
reaches the parser is a physics parameter, not a UI preference. These tests pin
down that it is read when the analysis runs rather than when the module is
imported, and that a malformed entry degrades to the documented default instead
of producing an infinite conversion factor.
"""
import json
import os

import pytest

from scripts.common import app_config
from scripts.JV import jv_core
from scripts.Dark_JV import dark_jv_core


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point every consumer at a throwaway config for the duration of a test."""
    path = tmp_path / "physisfera_config.json"

    def write(**values):
        path.write_text(json.dumps(values), encoding="utf-8")
        app_config.load(refresh=True)
        return path

    monkeypatch.setenv("PHYSISCORE_CONFIG", str(path))
    write()
    yield write
    monkeypatch.delenv("PHYSISCORE_CONFIG", raising=False)
    app_config.load(refresh=True)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def test_config_lives_at_the_project_root_not_above_it():
    """The repository root owns the config; ``spectra/`` used to look one level up."""
    root = app_config.project_root()
    assert os.path.isfile(os.path.join(root, "pyproject.toml"))
    assert os.path.basename(app_config.config_path()) == "physisfera_config.json"


def test_env_override_wins(config_file, tmp_path):
    config_file(cell_area_cm2=0.09)
    assert app_config.config_path() == str(tmp_path / "physisfera_config.json")


def test_missing_or_corrupt_config_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYSISCORE_CONFIG", str(tmp_path / "absent.json"))
    assert app_config.load(refresh=True) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("PHYSISCORE_CONFIG", str(broken))
    assert app_config.load(refresh=True) == {}
    # a broken config must not take the whole J-V analysis down with it
    assert jv_core.cell_area_cm2() == app_config.DEFAULT_CELL_AREA_CM2


# ---------------------------------------------------------------------------
# Cell area
# ---------------------------------------------------------------------------
def test_edited_area_takes_effect_without_reimporting(config_file):
    """The regression this module exists for: the area used to be captured at
    import time, so a corrected value did nothing until a restart."""
    config_file(cell_area_cm2=0.04)
    assert jv_core.cell_area_cm2() == pytest.approx(0.04)
    assert jv_core.current_conversion_factor() == pytest.approx(-25000.0)

    config_file(cell_area_cm2=0.09)
    assert jv_core.cell_area_cm2() == pytest.approx(0.09)
    assert jv_core.current_conversion_factor() == pytest.approx(-1000.0 / 0.09)
    assert dark_jv_core.cell_area_cm2() == pytest.approx(0.09)


@pytest.mark.parametrize("bad", [0, -0.04, "wide", None, float("inf")])
def test_unusable_area_falls_back_to_the_default(config_file, bad):
    """A zero or negative area would make the conversion factor infinite."""
    config_file(cell_area_cm2=bad)
    assert jv_core.cell_area_cm2() == app_config.DEFAULT_CELL_AREA_CM2
    assert dark_jv_core.cell_area_cm2() == app_config.DEFAULT_CELL_AREA_CM2


def test_explicit_area_overrides_the_config(config_file):
    config_file(cell_area_cm2=0.04)
    assert jv_core.cell_area_cm2(0.25) == pytest.approx(0.25)
    assert jv_core.current_conversion_factor(0.25) == pytest.approx(-4000.0)


def test_area_scales_parsed_current_density_linearly(config_file, tmp_path):
    """Halving the area doubles J at every point -- the linear scaling the
    configuration documentation promises."""
    measurement = tmp_path / "cell 1.txt"
    measurement.write_text(
        "Vmeas\tImeas\n"
        "0.0\t-0.001\n"
        "0.5\t-0.0008\n"
        "1.0\t0.0\n",
        encoding="utf-8")

    _, wide = jv_core.parse_jv_file(str(measurement), area_cm2=0.08)
    _, narrow = jv_core.parse_jv_file(str(measurement), area_cm2=0.04)

    assert [r["Current"] for r in narrow] == pytest.approx(
        [2.0 * r["Current"] for r in wide])
    # sign convention: photocurrent positive at short circuit after conversion
    assert narrow[0]["Current"] == pytest.approx(25.0)


def test_config_area_reaches_the_parser(config_file, tmp_path):
    """No explicit area: the value must come from the config, not from a
    constant frozen at import."""
    config_file(cell_area_cm2=0.10)
    measurement = tmp_path / "cell 1.txt"
    measurement.write_text("Vmeas\tImeas\n0.0\t-0.001\n", encoding="utf-8")

    _, rows = jv_core.parse_jv_file(str(measurement))
    assert rows[0]["Current"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def test_update_preserves_keys_owned_by_other_modules(config_file):
    """The launcher owns origin_path, the naming menu owns name_presets, and the
    J-V cores own cell_area_cm2. None may drop another's key."""
    config_file(cell_area_cm2=0.09, name_presets=["Ref", "Target"])

    app_config.update({"origin_path": r"C:\Origin\Origin.exe"})

    data = app_config.load(refresh=True)
    assert data["cell_area_cm2"] == 0.09
    assert data["name_presets"] == ["Ref", "Target"]
    assert data["origin_path"] == r"C:\Origin\Origin.exe"


def test_update_is_visible_to_the_physics_path_immediately(config_file):
    config_file(cell_area_cm2=0.04)
    app_config.update({"cell_area_cm2": 0.16})
    assert jv_core.cell_area_cm2() == pytest.approx(0.16)


def test_api_key_prefers_environment_over_config(config_file, monkeypatch):
    config_file(gemini_api_key="from-config")
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert app_config.api_key() == "from-env"


def test_api_key_falls_back_to_config_and_exports_it(config_file, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    config_file(gemini_api_key="from-config")

    assert app_config.api_key() == "from-config"
    # exported so the Google SDK's own implicit lookup finds it too
    assert os.environ["GEMINI_API_KEY"] == "from-config"


def test_absent_key_is_none_not_an_exception(config_file, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    config_file()
    assert app_config.api_key() is None
