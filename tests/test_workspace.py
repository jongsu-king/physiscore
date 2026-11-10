"""Measurement detection, the results index and the graph tools (3.5.0).

The detector decides which tool a file opens in; a wrong decision has to be a
visible suggestion, never a silent one, so the confidence levels are tested as
strictly as the kinds.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from conftest import MEASUREMENT_NAMES, single_diode_jv, write_measurement
from scripts.common import curve_batch, detect, provenance
from scripts.common import results_index as index


# ------------------------------------------------------------------ detection
@pytest.mark.parametrize("kind", sorted(MEASUREMENT_NAMES))
def test_instrument_export_is_recognised_with_high_confidence(kind, tmp_path):
    d = detect.detect_file(write_measurement(tmp_path, kind))
    assert d.kind == kind
    assert d.confidence == "high"
    assert d.tool == detect.KINDS[kind][0] and d.label == detect.KINDS[kind][1]
    assert d.evidence and d.why()                      # every decision states what it rests on
    assert d.columns and d.shape[0] > 5
    assert d.error == ""


@pytest.mark.parametrize("kind", ["trpl", "eis", "cv", "stability", "eqe", "xrd", "ftir"])
def test_columns_alone_identify_a_file_with_a_neutral_name(kind, tmp_path):
    d = detect.detect_file(write_measurement(tmp_path, kind, "export_0012.csv"))
    assert d.kind == kind and d.confidence in ("high", "medium")


def test_name_alone_gives_a_kind_without_reading_the_file(tmp_path):
    path = tmp_path / "PEAI_EIS_0V.csv"
    path.write_text("not a table at all\n")
    by_name = detect.detect_file(str(path), read=False)
    assert by_name.kind == "eis" and by_name.columns == []
    assert detect.name_scores("EOD_Ref_sclc.csv").keys() == {"sclc"}
    assert detect.name_scores("x.csv") == {}
    assert "eis" in detect.column_scores(["Frequency (Hz)", "Z' (Ohm)", "Z'' (Ohm)"])
    assert detect.column_scores(["A", "B", "C"]) == {}


def test_numbers_alone_are_only_a_suggestion(tmp_path):
    """Without a telling name or header the detector may guess, but never with confidence."""
    from scripts.EIS import eis_core
    f, zre, zim = eis_core.simulate(model="R(RQ)")
    path = tmp_path / "sample_07.csv"
    pd.DataFrame({"A": f, "B": zre, "C": zim}).to_csv(path, index=False)
    d = detect.detect_file(str(path))
    assert d.kind == "eis" and d.confidence == "low"
    v = np.round(np.arange(-0.2, 1.2501, 0.01), 4)
    jv = tmp_path / "device3.dat"
    np.savetxt(jv, np.column_stack([v, single_diode_jv(v)]), fmt="%.6g", delimiter="\t")
    d = detect.detect_file(str(jv))
    assert d.kind == "jv" and d.confidence == "low"


def test_text_that_is_not_a_measurement_is_not_recognised(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("spin 4000 rpm 30 s\nanneal 150 C 15 min\n")
    d = detect.detect_file(str(notes))
    assert d.kind == "" and d.confidence == "none" and d.tool == "" and d.label == "Not recognised"
    assert "no block of numeric rows" in d.error      # and says why, in words a user can act on
    missing = detect.detect_file(str(tmp_path / "none.csv"))
    assert missing.kind == "" and missing.confidence == "none"


def test_confidence_follows_the_score():
    d = detect.Detection(path="a.csv", kind="eis", score=detect.HIGH)
    assert d.confidence == "high"
    d.score = detect.MEDIUM
    assert d.confidence == "medium"
    d.score = detect.MEDIUM - 0.01
    assert d.confidence == "low"
    assert detect.Detection(path="a.csv").confidence == "none"
    assert detect.MEDIUM < detect.HIGH


def make_project(root):
    """A small project folder: data in sub-folders, an export, clutter that is not data."""
    paths = {k: write_measurement(os.path.join(root, sub), k)
             for k, sub in (("trpl", "PL"), ("eis", "EIS"), ("cv", "CV"), ("stability", "Stability"))}
    paths["trpl2"] = write_measurement(os.path.join(root, "PL"), "trpl", "PEAI_TRPL.csv")
    with open(os.path.join(root, "notes.txt"), "w") as f:
        f.write("spin 4000 rpm 30 s\n")
    with open(os.path.join(root, ".hidden.csv"), "w") as f:
        f.write("Time (ns),Counts\n0,1\n")
    with open(os.path.join(root, "PL", "~$Ref_TRPL.csv"), "w") as f:
        f.write("lock\n")
    with open(os.path.join(root, "readme.md"), "w") as f:
        f.write("# batch\n")
    deep = os.path.join(root, "a", "b", "c")
    write_measurement(deep, "eis", "deep_EIS.csv")
    return paths


def test_folder_scan_lists_data_files_only(tmp_path):
    root = str(tmp_path)
    paths = make_project(root)
    # an export of the program is a result, not a measurement to analyse again
    out = os.path.join(root, "PL", "trpl_results.xlsx")
    params = curve_batch.parameters("trpl")
    curve_batch.write_excel("trpl", curve_batch.run_files("trpl", [paths["trpl"]], params), out, params)
    assert detect.is_export(out) and not detect.is_export(paths["trpl"])

    found = detect.scan_folder(root, max_depth=2)
    names = sorted(os.path.relpath(d.path, root).replace(os.sep, "/") for d in found)
    assert names == ["CV/Ref_MottSchottky_10kHz.csv", "EIS/Ref_EIS_0V_dark.csv", "PL/PEAI_TRPL.csv",
                     "PL/Ref_TRPL.csv", "Stability/Ref_MPPT_ISOS-L-1.csv", "notes.txt"]
    deeper = detect.scan_folder(root, max_depth=4)
    assert any(d.name == "deep_EIS.csv" for d in deeper)
    assert len(detect.list_candidates(root, max_depth=4, limit=3)) == 3

    groups = detect.group_by_tool(found)
    assert list(groups) == ["Stability", "Impedance", "C-V (Mott-Schottky)", "TRPL", ""]
    assert [d.name for d in groups["TRPL"]] == ["PEAI_TRPL.csv", "Ref_TRPL.csv"]
    assert [d.name for d in groups[""]] == ["notes.txt"]
    text = detect.summary(found)
    assert text.startswith("6 files:") and "2 Time-resolved PL" in text and "1 not recognised" in text


def test_folder_scan_reports_progress_and_can_be_cancelled(tmp_path):
    make_project(str(tmp_path))
    seen = []
    detect.scan_folder(str(tmp_path), progress=lambda i, n: seen.append((i, n)))
    assert seen == [(i, 6) for i in range(1, 7)]
    partial = detect.scan_folder(str(tmp_path), cancelled=lambda: True)
    assert len(partial) == 1
    steps = list(detect.iter_folder(str(tmp_path), read=False))
    assert [s[0] for s in steps] == list(range(1, 7)) and all(s[1] == 6 for s in steps)


def test_a_picture_that_is_not_a_micrograph_is_left_out(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (64, 48), (200, 30, 30)).save(tmp_path / "figure_3.png")
    assert detect.scan_folder(str(tmp_path)) == []
    Image.new("L", (64, 48), 90).save(tmp_path / "Ref_SEM_50kx.tif")
    found = detect.scan_folder(str(tmp_path))
    assert [d.kind for d in found] == ["sem"] and found[0].tool == "FE-SEM"


def test_every_kind_opens_an_existing_tool():
    pytest.importorskip("customtkinter")
    import Physiscore_Launcher as launcher
    tools = {t[0] for t in launcher.TOOLS}
    for kind, (tool, label) in detect.KINDS.items():
        assert tool in tools, f"{kind} points to a tool the launcher does not have"
        assert label
    assert set(detect.FOLDER_TOOLS) <= tools
    # each of the six curve analyses is a tool of the launcher under the name the runner uses
    for slug in curve_batch.TOOLS:
        assert curve_batch.tool_name(slug) in tools
        assert detect.KINDS[slug][0] == curve_batch.tool_name(slug)
    for name in tools:
        assert name in launcher.TOOL_DETAILS, f"{name} has no description in the launcher"


# -------------------------------------------------------------- results index
def export_two(root):
    paths = make_project(root)
    for tool, key, out in (("trpl", "trpl", "PL/trpl.xlsx"), ("eis", "eis", "EIS/eis.xlsx")):
        params = curve_batch.parameters(tool)
        items = curve_batch.run_files(tool, [paths[key]], params)
        curve_batch.write_excel(tool, items, os.path.join(root, out), params)
    return paths


def test_results_index_lists_every_export_with_its_headline(tmp_path):
    root = str(tmp_path)
    export_two(root)
    entries = index.scan(root)
    assert sorted(e.tool for e in entries) == ["Impedance", "TRPL"]
    trpl = next(e for e in entries if e.tool == "TRPL")
    assert trpl.name == "trpl.xlsx" and os.path.isfile(trpl.export)
    assert trpl.sample == "Ref_TRPL"
    assert trpl.when is not None and trpl.date.startswith(str(trpl.when.year))
    assert trpl.version == provenance.app_version()
    assert trpl.error == ""
    head = index.headline(trpl)
    assert head.startswith("Ref_TRPL:") and "<tau> amp. 27." in head
    assert index.summary(entries) == "2 exports: 1 Impedance, 1 TRPL"

    table = index.index_table(entries, root)
    assert list(table.columns) == ["Date", "Tool", "Sample", "Headline", "Export", "Inputs", "Version", "Side-car"]
    assert sorted(table["Export"].str.replace("\\", "/", regex=False)) == ["EIS/eis.xlsx", "PL/trpl.xlsx"]
    long = index.long_table(entries, root)
    assert {"Tool", "Sample", "Quantity", "Value"} <= set(long.columns)
    tau = long[(long["Tool"] == "TRPL") & (long["Quantity"] == "<tau> amp.")]["Value"]
    assert float(tau.iloc[0]) == pytest.approx(27.5, rel=0.04)
    per_tool = index.tool_tables(entries, root)
    assert set(per_tool) == {"Impedance", "TRPL"} and len(per_tool["TRPL"]) == 1


def test_results_index_workbook_is_not_indexed_itself(tmp_path):
    root = str(tmp_path)
    export_two(root)
    entries = index.scan(root)
    out = os.path.join(root, "results_index.xlsx")
    assert index.write_excel(entries, out, root) == out
    assert pd.ExcelFile(out).sheet_names == ["Index", "Impedance", "TRPL", "All values"]
    record = provenance.read_sidecar(provenance.sidecar_path(out))
    assert record["tool"] == index.INDEX_TOOL
    assert len(index.scan(root)) == 2                   # the index would otherwise count itself


def test_results_index_survives_a_damaged_side_car(tmp_path):
    root = str(tmp_path)
    export_two(root)
    with open(os.path.join(root, "broken.analysis.json"), "w") as f:
        f.write("{ not json")
    with open(os.path.join(root, "list.analysis.json"), "w") as f:
        json.dump([1, 2, 3], f)
    entries = index.scan(root)
    assert len(entries) == 4
    damaged = [e for e in entries if e.error]
    assert len(damaged) == 2 and all("unreadable side-car" in e.error for e in damaged)
    assert index.index_table(entries, root).shape[0] == 4
    assert index.scan(root, cancelled=lambda: True) == []
    assert index.scan(str(tmp_path / "PL"), max_depth=0)[0].tool == "TRPL"


def test_results_are_flattened_into_rows():
    rows = index.flatten({"n_id": 1.5, "fit": {"slope": 2, "points": [1, 2]}, "note": "ok"})
    assert ("summary", "", "n_id", 1.5) in rows
    assert ("fit", "", "slope", 2) in rows and ("fit", "", "points", "1, 2") in rows
    assert ("summary", "", "note", "ok") in rows
    files = index.flatten({"files": [{"File": "A", "Voc": 1.1}, {"File": "B", "Voc": 1.0}]})
    assert ("files", "A", "Voc", 1.1) in files and ("files", "B", "Voc", 1.0) in files
    assert index.fmt(1.23456e-7) == "1.235e-07" and index.fmt(3) == "3" and index.fmt("s") == "s"


def test_input_of_a_record_is_a_path_or_the_label_it_was(tmp_path):
    real = tmp_path / "a.csv"
    real.write_text("x\n")
    assert provenance._input_name(str(real)) == os.path.abspath(str(real))
    assert provenance._input_name("synthetic example") == "synthetic example"
    out = str(tmp_path / "x.xlsx")
    side = provenance.write_sidecar(out, "TRPL", inputs=[str(real), "synthetic example"],
                                    parameters={"model": "auto"}, results={"tau": 1.0})
    assert side == provenance.sidecar_path(out) and side.endswith(provenance.SIDECAR_SUFFIX)
    record = provenance.read_sidecar(side)
    assert record["inputs"] == [os.path.abspath(str(real)), "synthetic example"]


def test_record_window_rows_read_in_order(tmp_path):
    pytest.importorskip("customtkinter")
    from scripts.common import workspace_panel
    root = str(tmp_path)
    export_two(root)
    entry = next(e for e in index.scan(root) if e.tool == "TRPL")
    rows = workspace_panel.record_rows(entry)
    sections = [r[0] for r in rows]
    assert sections[:5] == ["Record"] * 5
    assert ("Record", "Tool", "TRPL") in rows
    assert any(s == "Input" for s in sections) and any(s == "Parameter" for s in sections)
    assert any(s.startswith("Result") and "<tau> amp." in item for s, item, _ in rows)
    assert sections.index("Input") < sections.index("Parameter") < next(
        i for i, s in enumerate(sections) if s.startswith("Result"))
    assert set(workspace_panel.COMPARE_KINDS) <= set(detect.KINDS)


# ---------------------------------------------------------------- graph tools
@pytest.fixture()
def figure():
    pytest.importorskip("customtkinter")
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(4, 3))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    x = np.linspace(0.0, 1.0, 11)
    ax.plot(x, x ** 2, label="a")
    ax.plot(x, 2.0 * x, label="b")
    ax.axvline(0.5)                                     # a guide line is not data
    ax.set_xlabel("V (V)")
    ax.set_ylabel("J")
    fig.canvas.draw()
    return fig


def test_graph_curves_and_worksheet(figure):
    from scripts.common import plot_tools
    ax = figure.axes[0]
    curves = plot_tools.curves(ax, min_points=3)
    assert [c["label"] for c in curves] == ["a", "b"]
    table = plot_tools.figure_table(figure)
    assert list(table.columns) == ["a | V (V)", "a | J", "b | V (V)", "b | J"]
    assert table.shape == (11, 4)
    assert table["b | J"].iloc[-1] == pytest.approx(2.0)
    assert plot_tools.column_letters(3) == ["A(X)", "B(Y)", "C(X)"]
    assert plot_tools.column_letters(28)[-2:] == ["AA(X)", "AB(Y)"]


def test_graph_data_reader_snaps_to_measured_points(figure):
    from scripts.common import plot_tools
    ax = figure.axes[0]
    px = ax.transData.transform((0.5, 0.25))
    point = plot_tools.nearest_point(figure, px[0], px[1])
    assert point["label"] == "a" and point["index"] == 5
    assert (point["x"], point["y"]) == pytest.approx((0.5, 0.25))
    assert "x = 0.5" in plot_tools.point_text(point) and "point 6" in plot_tools.point_text(point)
    assert plot_tools.nearest_point(figure, -500.0, -500.0) is None      # nothing within reach
    p1 = plot_tools.nearest_point(figure, *ax.transData.transform((0.2, 0.4)))
    p2 = plot_tools.nearest_point(figure, *ax.transData.transform((0.8, 1.6)))
    text = plot_tools.two_point_text(p1, p2)
    assert "dx = 0.6" in text and "dy/dx = 2" in text


@pytest.mark.parametrize("ext", [".png", ".pdf", ".svg", ".tif"])
def test_graph_export_at_a_journal_column_width(figure, ext, tmp_path):
    from scripts.common import plot_tools
    assert ext in plot_tools.FORMATS.values()
    before = tuple(figure.get_size_inches())
    out = str(tmp_path / ("figure" + ext))
    info = plot_tools.export_figure(figure, out, width_mm=85.0, height_mm=60.0, dpi=600)
    assert os.path.getsize(out) > 0
    assert info["width_mm"] == pytest.approx(85.0) and info["height_mm"] == pytest.approx(60.0)
    assert info["pixels"] == plot_tools.pixel_size(85.0, 60.0, 600) == (2007, 1417)
    assert tuple(figure.get_size_inches()) == pytest.approx(before)     # the window is left as it was
    if ext == ".png":
        Image = pytest.importorskip("PIL.Image")
        with Image.open(out) as im:
            assert im.size == info["pixels"]            # the size reported is the size written
