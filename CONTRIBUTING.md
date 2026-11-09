# Contributing

Bug reports, data files that break something, and new analyses are welcome.

## Reporting a problem

Open an issue with the version (Help → About), the platform, the tool, what you expected
and what happened. Attach the `.analysis.json` side-car of the export: it lists the inputs
and every parameter of the analysis. If you can share the data file, attach it too.

## Development setup

```bash
git clone https://github.com/jongsu-king/physiscore.git
cd physiscore
python -m venv .venv && source .venv/bin/activate      # Python 3.10-3.12 with Tk
pip install -r requirements.txt pytest
pytest -q tests
python Physiscore_Launcher.py
```

## Rules for changes

- Physics goes into a GUI-free `*_core.py` (or `scripts/common/`), never into a window.
- Every estimator gets a test that recovers the inputs of a closed-form model
  (see `tests/conftest.py`) and, for reported quantities, a row in
  `tools/validation_report.py`.
- State defaults as arguments and document them in `docs/METHODS.md` with a reference.
- GUI colours and fonts come from `scripts/common/palette.py`.
- Run `pytest -q tests` and `python tools/gui_smoke.py` before opening a pull request.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout, the threading rule
and how to add a tool.

## Licence

Contributions are accepted under the MIT licence of the project.
