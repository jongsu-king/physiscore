"""The shared runner of the six curve analyses (SCLC, light intensity, TRPL,
impedance, C-V, stability): one code path for the windows and the command line.

The files are written the way an instrument exports them, from the forward model
of each analysis, so every number checked here has a known value.
"""
import importlib
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

from conftest import single_diode_jv, write_measurement
from scripts.common import curve_batch as cb
from scripts.common import curve_io, provenance

import physiscore_cli as cli

TOOLS = ("sclc", "intensity", "trpl", "eis", "cv", "stability")
WINDOWS = {"sclc": "scripts.SCLC.run_sclc", "intensity": "scripts.Intensity.run_intensity",
           "trpl": "scripts.TRPL.run_trpl", "eis": "scripts.EIS.run_eis", "cv": "scripts.CV.run_cv",
           "stability": "scripts.Stability.run_stability"}
# parameters a measurement needs beyond the defaults (the cell area comes from the settings in the app)
GIVEN = {"sclc": {"area_cm2": 0.04}, "intensity": {"area_cm2": 0.04}, "cv": {"area_cm2": 0.1, "thickness_nm": 500.0}}


def run(capsys, argv):
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if "--json" in argv else out)


def stem(path):
    """A file is named in the tables without its extension."""
    return os.path.splitext(os.path.basename(path))[0]


# ------------------------------------------------------------------ registry
def test_registry_names_the_six_analyses():
    assert tuple(cb.TOOLS) == TOOLS
    for tool in TOOLS:
        entry = cb.TOOLS[tool]
        assert cb.tool_name(tool) == entry["name"]
        assert hasattr(cb.core(tool), "analyse") and hasattr(cb.core(tool), "simulate")
        assert cb.batch_columns(tool), "a batch table needs columns"


@pytest.mark.parametrize("tool", TOOLS)
def test_defaults_are_arguments_of_the_core(tool):
    """A default that the analysis does not take would be silently ignored."""
    import inspect
    core = cb.core(tool)
    accepted = set(inspect.signature(core.analyse).parameters)
    if tool == "intensity":
        accepted |= set(inspect.signature(core.from_jv_files).parameters)
    accepted |= set(inspect.signature(getattr(core, "read_curve", core.analyse)).parameters)
    unknown = set(cb.TOOLS[tool]["defaults"]) - accepted
    assert not unknown, f"{tool}: {sorted(unknown)} are not arguments of the analysis"


@pytest.mark.parametrize("tool", TOOLS)
def test_window_fields_are_the_parameters_of_the_runner(tool):
    """The window and the command line must offer the same parameters, choices and defaults."""
    pytest.importorskip("customtkinter")
    window = importlib.import_module(WINDOWS[tool]).AnalysisWindow
    assert window.SLUG == tool
    assert window.TOOL_NAME == cb.tool_name(tool)
    defaults, choices = cb.TOOLS[tool]["defaults"], cb.choices(tool)
    assert {f["key"] for f in window.FIELDS} == set(defaults)
    for field in window.FIELDS:
        key, default = field["key"], field.get("default")
        if field.get("kind") == "choice":
            assert list(field["choices"]) == list(choices[key]), key
        if callable(default):                          # the cell area of the settings
            assert key == "area_cm2" and tool in cb.AREA_FROM_SETTINGS
        elif defaults[key] is None:
            assert default in ("", None), key
        else:
            assert default == defaults[key], key
    assert window.BATCH == cb.batch_columns(tool)


def test_parameters_are_validated():
    p = cb.parameters("trpl")
    assert p == cb.TOOLS["trpl"]["defaults"] and p is not cb.TOOLS["trpl"]["defaults"]
    assert cb.parameters("trpl", {"model": "exp2", "skip": 2.0})["model"] == "exp2"
    with pytest.raises(ValueError, match="no parameter named nope"):
        cb.parameters("trpl", {"nope": 1})
    with pytest.raises(ValueError, match="not one of"):
        cb.parameters("trpl", {"model": "exp9"})
    assert cb.parse_background("auto") == "auto"
    assert cb.parse_background("none") == "none"
    assert cb.parse_background("3.5") == pytest.approx(3.5)
    assert cb.parse_background("") == "auto"


def test_values_are_formatted_for_tables():
    assert cb.fmt_value(1.23456e17) == "1.235e+17"
    assert cb.fmt_value(0.5) == "0.5"
    assert cb.fmt_value(float("nan")) == "-"
    assert cb.fmt_value(None) == "-"
    assert cb.fmt_value(True) == "yes"
    assert cb.fmt_value("exp2") == "exp2"


# ------------------------------------------------------------------- run_file
EXPECTED = {
    "sclc": lambda r: r["n_t_cm3"] == pytest.approx(5e16, rel=0.02),
    "intensity": lambda r: r["jscvoc_fit"]["n_id"] == pytest.approx(1.5, rel=0.01),
    "trpl": lambda r: r["model"] == "exp2" and r["tau_amp"] == pytest.approx(27.5, rel=0.04),
    "eis": lambda r: r["model"] == "R(RQ)(RQ)" and r["R_total"] == pytest.approx(1700.0, rel=0.02),
    "cv": lambda r: r["N_cm3"] == pytest.approx(1e17, rel=0.01),
    "stability": lambda r: r["T_measured"] == pytest.approx(800.0, rel=0.03),
}


@pytest.mark.parametrize("tool", TOOLS)
def test_run_file_reads_an_instrument_table_and_recovers_the_answer(tool, tmp_path):
    path = write_measurement(tmp_path, tool)
    params = cb.parameters(tool, GIVEN.get(tool))
    item = cb.run_file(tool, path, params)
    assert item["error"] == ""
    assert item["file"] == stem(path) and item["path"] == path
    assert EXPECTED[tool](item["result"])
    # the right file in the right tool gets no wrong-file remark
    assert not any("check that the right file was opened" in c for c in item["checks"])
    rows = cb.summary_rows(tool, item["result"])
    assert rows and all(len(row) == 3 for row in rows)
    report = cb.interpret(tool, item["result"], item["file"])
    assert report.findings and report.subject == item["file"]
    for name, table in cb.tables(tool, item["data"], item["result"]).items():
        assert len(name) <= 31, "an Excel sheet name holds 31 characters"
        assert len(table) > 0


def test_run_file_reports_a_plain_error_and_goes_on(tmp_path):
    params = cb.parameters("trpl")
    missing = cb.run_file("trpl", str(tmp_path / "none.csv"), params)
    assert missing["result"] is None and "file not found" in missing["error"]
    folder = cb.run_file("trpl", str(tmp_path), params)
    assert folder["result"] is None and "this is a folder" in folder["error"]
    notes = tmp_path / "notes.txt"
    notes.write_text("spin 4000 rpm 30 s\nanneal 150 C 15 min\n")
    assert cb.run_file("trpl", str(notes), params)["result"] is None
    good = write_measurement(tmp_path, "trpl")
    items = cb.run_files("trpl", [str(notes), good], params)
    assert [it["result"] is not None for it in items] == [False, True]
    frame = cb.summary_frame("trpl", items)
    assert list(frame["File"]) == ["notes", stem(good)]
    assert frame["Error"].iloc[0] and not frame["Error"].iloc[1]


def test_a_file_of_another_measurement_gets_a_remark(tmp_path):
    spectrum = write_measurement(tmp_path, "eis")
    decay = write_measurement(tmp_path, "trpl")
    assert cb.file_check("eis", spectrum) == []
    remark = cb.file_check("trpl", spectrum)
    assert len(remark) == 1 and "Impedance spectrum" in remark[0] and "TRPL" in remark[0]
    assert "Time-resolved PL" in cb.file_check("eis", decay)[0]
    # a single-carrier J-V curve looks like any other J-V curve: no remark for the SCLC window
    plain_jv = write_measurement(tmp_path, "sclc", "device3.csv")
    assert cb.file_check("sclc", plain_jv) == []
    # a file that cannot be read gives no remark either (the error is reported by the analysis)
    assert cb.file_check("trpl", str(tmp_path / "none.csv")) == []


# ------------------------------------------------------------------- workbook
def test_workbook_and_its_side_car(tmp_path):
    a = write_measurement(tmp_path, "trpl", "film_A_TRPL.csv")
    b = write_measurement(tmp_path, "trpl", "film_B_TRPL.csv")
    params = cb.parameters("trpl", {"mobility_cm2_Vs": 2.0})
    items = cb.run_files("trpl", [a, b, str(tmp_path / "none.csv")], params)
    out = str(tmp_path / "out" / "trpl.xlsx")
    os.makedirs(os.path.dirname(out))
    assert cb.write_excel("trpl", items, out, params) == out
    book = pd.ExcelFile(out)
    assert book.sheet_names[:4] == ["Summary", "Results", "Checks", "Parameters"]
    assert len(book.sheet_names) > 4                    # the curves of the files follow
    summary = pd.read_excel(out, sheet_name="Summary")
    assert list(summary["File"]) == ["film_A_TRPL", "film_B_TRPL", "none"]
    assert summary["<tau> amp."].iloc[0] == pytest.approx(27.5, rel=0.04)
    assert "file not found" in str(summary["Error"].iloc[2])
    results = pd.read_excel(out, sheet_name="Results")
    assert set(results.columns) == {"File", "Quantity", "Value", "Unit"}
    record = provenance.read_sidecar(provenance.sidecar_path(out))
    assert record["tool"] == "TRPL"
    assert record["parameters"]["mobility_cm2_Vs"] == 2.0
    assert [os.path.basename(p) for p in record["inputs"]] == ["film_A_TRPL.csv", "film_B_TRPL.csv", "none.csv"]
    files = record["results"]["files"]
    assert [f["File"] for f in files][:2] == ["film_A_TRPL", "film_B_TRPL"]
    assert files[0]["<tau> amp."] == pytest.approx(27.5, rel=0.04)
    assert record["physiscore_version"] == provenance.app_version()


# ------------------------------------------------------------------- curve_io
def test_text_table_with_comments_semicolons_and_decimal_commas(tmp_path):
    path = tmp_path / "decay.txt"
    path.write_text("# TCSPC export\n# detector: SPAD\nTime (ns);Counts\n0,5;10\n1,0;20\n1,5;30\n", encoding="utf-8")
    df = curve_io.read_text_table(str(path))
    assert list(df.columns) == ["Time (ns)", "Counts"]
    assert df.to_numpy().tolist() == [[0.5, 10.0], [1.0, 20.0], [1.5, 30.0]]
    from scripts.TRPL import trpl_core
    data, used = curve_io.pick_columns(df, trpl_core.COLUMN_SPEC)
    assert used == {"t": "Time (ns)", "y": "Counts"}
    assert data["y"].tolist() == [10.0, 20.0, 30.0]


def test_headerless_table_is_read_by_position(tmp_path):
    path = tmp_path / "run_0012.txt"
    t = np.linspace(0.0, 10.0, 21)
    np.savetxt(path, np.column_stack([t, 100.0 * np.exp(-t / 3.0)]), fmt="%.6g", delimiter="\t")
    df = curve_io.read_numeric_table(str(path))
    assert df.shape == (21, 2)
    from scripts.TRPL import trpl_core
    data, _ = curve_io.pick_columns(df, trpl_core.COLUMN_SPEC)
    assert data["t"][-1] == pytest.approx(10.0)


def test_columns_are_found_by_name_whatever_their_order(tmp_path):
    from scripts.EIS import eis_core
    f, zre, zim = eis_core.simulate()
    path = tmp_path / "eis.csv"
    pd.DataFrame({"Z'' (Ohm)": zim, "Point": np.arange(len(f)), "Z' (Ohm)": zre, "Frequency (Hz)": f}).to_csv(path, index=False)
    item = cb.run_file("eis", str(path), cb.parameters("eis"))
    assert item["error"] == ""
    assert item["result"]["Rs"] == pytest.approx(10.0, rel=0.03)


def test_straight_line_fit_and_student_factor():
    x = np.arange(10.0)
    fit = curve_io.linfit(x, 2.0 * x + 1.0)
    assert fit["slope"] == pytest.approx(2.0) and fit["intercept"] == pytest.approx(1.0)
    assert fit["r2"] == pytest.approx(1.0) and fit["n"] == 10
    rng = np.random.default_rng(1)
    noisy = curve_io.linfit(x, 2.0 * x + 1.0 + 0.1 * rng.standard_normal(10))
    assert abs(noisy["slope"] - 2.0) < 4.0 * noisy["slope_err"]
    assert curve_io.t_factor(10) == pytest.approx(2.306, abs=1e-3)      # 8 degrees of freedom, 95 %
    assert curve_io.t_factor(1000) == pytest.approx(1.962, abs=1e-3)
    a, b = curve_io.finite_rows(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, np.inf]))
    assert a.tolist() == [1.0] and b.tolist() == [1.0]


# --------------------------------------------------------------- command line
CLI_ARGS = {"sclc": ["--area", "0.04"], "intensity": [], "trpl": [], "eis": [],
            "cv": ["--area", "0.1", "--thickness", "500"], "stability": []}
CLI_QUANTITY = {"sclc": 5e16, "intensity": 1.5, "trpl": 27.5, "eis": 1700.0, "cv": 1e17, "stability": 800.0}


@pytest.mark.parametrize("tool", TOOLS)
def test_cli_runs_each_curve_analysis(tool, tmp_path, capsys):
    path = write_measurement(tmp_path, tool)
    rc, r = run(capsys, [tool, path, "--interpret", "--json"] + CLI_ARGS[tool])
    assert rc == 0
    assert r["tool"] == cb.tool_name(tool)
    (entry,) = r["files"]
    assert entry["error"] == "" and entry["summary"]
    assert "## " in entry["interpretation"] or "**" in entry["interpretation"]
    values = [row["value"] for row in entry["summary"] if isinstance(row["value"], (int, float))]
    target = CLI_QUANTITY[tool]
    assert any(math.isfinite(v) and abs(v - target) <= 0.05 * target for v in values), \
        f"{tool}: {target} is not among the reported values"
    rc, text = run(capsys, [tool, path] + CLI_ARGS[tool])
    assert rc == 0 and cb.tool_name(tool) in text and "1 of 1 file analysed" in text


def test_cli_writes_a_workbook_and_fails_when_nothing_could_be_analysed(tmp_path, capsys):
    a = write_measurement(tmp_path, "stability", "A_MPPT.csv")
    b = write_measurement(tmp_path, "stability", "B_MPPT.csv")
    out = str(tmp_path / "stability.xlsx")
    rc, text = run(capsys, ["stability", a, b, "--out", out, "--protocol", "ISOS-L-1"])
    assert rc == 0 and "Summary:" in text
    assert os.path.isfile(out) and os.path.isfile(provenance.sidecar_path(out))
    assert provenance.read_sidecar(provenance.sidecar_path(out))["parameters"]["protocol"] == "ISOS-L-1"
    rc, r = run(capsys, ["stability", str(tmp_path / "none.csv"), "--json"])
    assert rc == 1
    assert "file not found" in r["files"][0]["error"]
    with pytest.raises(SystemExit):
        cli.main(["stability"])


def test_cli_says_when_a_file_belongs_to_another_tool(tmp_path, capsys):
    spectrum = write_measurement(tmp_path, "eis")
    _, r = run(capsys, ["trpl", spectrum, "--json"])
    assert any("Impedance spectrum" in c for c in r["files"][0]["checks"])


def test_cli_light_intensity_from_a_set_of_jv_files(tmp_path, capsys):
    """Voc, Jsc and FF are taken from J-V curves whose names state the irradiance."""
    v = np.round(np.arange(-0.1, 1.2501, 0.005), 4)
    files = []
    for suns in (0.01, 0.03, 0.1, 0.3, 1.0):
        j = single_diode_jv(v, jph=24.0 * suns, j0=1e-10, n=1.5, rs=1.0, rsh=1e6, temperature_k=300.0)
        path = tmp_path / f"cell_{suns:g}sun.csv"
        pd.DataFrame({"Voltage (V)": v, "Current density (mA/cm2)": j}).to_csv(path, index=False)
        files.append(str(path))
    rc, r = run(capsys, ["intensity", "--jv-set"] + files + ["--json"])
    assert rc == 0
    (entry,) = r["files"]
    assert entry["error"] == "" and len(entry["inputs"]) == 5
    result = entry["result"]
    assert result["voc_fit"]["n_id"] == pytest.approx(1.5, rel=0.03)
    assert result["jsc_fit"]["alpha"] == pytest.approx(1.0, abs=0.01)


def test_cli_detect_names_the_measurement(tmp_path, capsys):
    decay = write_measurement(tmp_path, "trpl")
    write_measurement(tmp_path, "eis")
    (tmp_path / "notes.txt").write_text("spin 4000 rpm 30 s\n")
    rc, r = run(capsys, ["detect", decay, "--json"])
    assert rc == 0
    assert r["files"][0]["kind"] == "trpl" and r["files"][0]["tool"] == "TRPL"
    assert r["files"][0]["confidence"] == "high"
    rc, r = run(capsys, ["detect", str(tmp_path), "--json"])
    kinds = {os.path.basename(f["path"]): f["kind"] for f in r["files"]}
    assert kinds == {"Ref_TRPL.csv": "trpl", "Ref_EIS_0V_dark.csv": "eis", "notes.txt": ""}
    _, text = run(capsys, ["detect", str(tmp_path)])
    assert "Impedance spectrum (high) -> Impedance" in text and "notes.txt: not recognised" in text
    with pytest.raises(SystemExit):
        cli.main(["detect", str(tmp_path / "none.csv")])


def test_cli_collect_gathers_the_exports_of_a_folder(tmp_path, capsys):
    decay = write_measurement(tmp_path / "PL", "trpl")
    spectrum = write_measurement(tmp_path / "EIS", "eis")
    run(capsys, ["trpl", decay, "--out", str(tmp_path / "PL" / "trpl.xlsx")])
    run(capsys, ["eis", spectrum, "--out", str(tmp_path / "EIS" / "eis.xlsx")])
    out = str(tmp_path / "results_index.xlsx")
    rc, r = run(capsys, ["collect", str(tmp_path), "--out", out, "--json"])
    assert rc == 0
    assert sorted(row["Tool"] for row in r["exports"]) == ["Impedance", "TRPL"]
    assert {row["Tool"] for row in r["values"]} == {"Impedance", "TRPL"}
    assert pd.ExcelFile(out).sheet_names[0] == "Index"
    # the index is not itself an export: collecting twice gives the same two records
    _, again = run(capsys, ["collect", str(tmp_path), "--json"])
    assert len(again["exports"]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit):
        cli.main(["collect", str(empty), "--out", str(empty / "index.xlsx")])
