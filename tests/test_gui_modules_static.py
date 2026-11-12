"""Static checks on the GUI modules: paths that only run with data loaded are not
reached by the window smoke test, so a missing import there goes unnoticed."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_sem_window_binds_its_core_module():
    # 3.1.1 used sem_core.size_statistics / histogram_with_fit without importing the
    # module: the histogram, the Excel export and the report failed once grains existed.
    run_sem = pytest.importorskip("scripts.SEM.run_sem")
    stats = run_sem.sem_core.size_statistics([100.0, 120.0, 140.0, 160.0])
    assert stats["n"] == 4
    counts, edges = run_sem.sem_core.histogram_with_fit([100.0, 120.0, 140.0, 160.0, 150.0])[1:3]
    assert len(edges) == len(counts) + 1


def test_no_undefined_names():
    api = pytest.importorskip("pyflakes.api")
    from pyflakes import messages, reporter

    class Collect(reporter.Reporter):
        def __init__(self):
            super().__init__(None, None)
            self.found = []

        def flake(self, message):
            if isinstance(message, (messages.UndefinedName, messages.UndefinedLocal)):
                self.found.append(str(message))

        def unexpectedError(self, filename, msg):
            self.found.append(f"{filename}: {msg}")

        def syntaxError(self, filename, msg, lineno, offset, text):
            self.found.append(f"{filename}:{lineno}: {msg}")

    rep = Collect()
    files = [ROOT / "Physiscore_Launcher.py", ROOT / "physiscore_cli.py", ROOT / "selfupdate.py"]
    for folder in ("scripts", "spectra", "tools"):
        files += sorted((ROOT / folder).rglob("*.py"))
    for f in files:
        api.checkPath(str(f), rep)
    assert rep.found == []


def test_to_excel_sheet_names_are_keywords():
    """pandas 3 makes every to_excel argument after the writer keyword-only.  The
    auto-fit workspace passed the sheet name positionally, so Export Excel and the
    Batch Folder summary raised TypeError in the published 3.5.2 installers, which
    bundle pandas 3.1.1."""
    import ast
    bad = []
    for path in list(ROOT.glob("scripts/**/*.py")) + list(ROOT.glob("spectra/**/*.py")) + [ROOT / "physiscore_cli.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "to_excel" and len(node.args) > 1):
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not bad, bad

