# Architecture and developer notes

## Layout

```
Physiscore_Launcher.py      main window, settings, --tool/--spectra/--selftest/--update/--version
physiscore_cli.py           command line (same cores, no GUI)
selfupdate.py               GitHub-release updater (standard library only)

scripts/common/             shared, GUI-free unless noted
  spectral.py               baselines (ALS, arPLS, Shirley), line shapes, multi-peak fit, AICc, nm->eV
  vibrational.py            Raman/FTIR preprocessing, band fitting, shift tables, band library
  band_library.json         70 indicative band positions
  device_summary.py         cross-technique checks and detailed balance of one device
  batch.py                  table readers and per-file analysers (compare windows + CLI batch)
  iv_io.py                  generic CSV/Excel I-V reader, result-file detection
  provenance.py             .analysis.json side-cars
  report.py                 Markdown reports
  app_config.py             physisfera_config.json (area, Origin path, API key, theme, presets)
  naming.py                 sample-name rules shared by the J-V parsers
  palette.py                light/dark colours, fonts, matplotlib style (no Tk)
  theme.py                  customtkinter widget helpers (GUI)
  analysis_shell.py         menu bar, toolbar, status bar, figure export, thread-safe after() (GUI)
  plot_interactions.py      zoom/pan/context menus (GUI)
  sample_naming.py          rename/preset menus (GUI)
  compare_window.py         multi-file comparison window (GUI)
  origin.py                 OriginPro COM connection (Windows)

scripts/<Technique>/        one package per technique
  *_core.py                 physics, GUI-free (jv_core, dark_jv_core, eqe_core, abs_core, pl_core,
                            xrd_core, raman_core, ftir_core, sem_core)
  run_*.py                  the tool window (class AnalysisWindow)
scripts/Device/run_device.py  Device summary window

spectra/                    auto-fit workspaces (PL, XRD, XPS)
  core/                     config, baseline, peak detection, Voigt fitting, XPS (Shirley, RSF)
  pipelines/                run_pl, run_xrd, run_xps
  gui/                      dashboard tab, PL tab

tests/                      pytest; closed-form synthetic data (conftest.py generators)
tools/                      validation_report.py, gui_smoke.py, screenshots.py
packaging/                  PyInstaller spec, Inno Setup script, DMG / deb / tar.gz builders
docs/                       USER_GUIDE, METHODS, VALIDATION, FILE_FORMATS, CLI, INSTALL, release notes
```

## Principles

1. **Physics in the cores, never in the windows.** A window reads files, calls a core and
   displays the result. Everything a paper reports must be reachable without Tk, so it can
   be tested, scripted and validated.
2. **Every estimator has a closed-form test.** `tests/conftest.py` generates data from
   analytical models; a new estimator comes with a test that recovers known inputs and a
   row in `tools/validation_report.py`.
3. **Defaults are stated.** Windows, thresholds and constants are function arguments with
   documented defaults (METHODS.md), not hidden literals.
4. **Outputs are traceable.** Exports carry a side-car; reports list inputs, version and
   method notes.
5. **The optional interpretation never touches numbers.** Gemini calls only produce text
   next to results that already exist.

## Threading

Long work runs in a worker thread and hands results back with `self.after(0, callback)`.
Some Tk builds (seen with Tk 9.0 on macOS) silently drop an `after()` issued from another
thread. `analysis_shell.make_thread_safe(widget)` wraps `after` so calls from worker
threads are queued and dispatched by a main-thread poller; `attach_chrome` applies it to
every tool window, and the comparison window and auto-fit tabs apply it themselves. New
threaded GUI code must either live in such a window or call `make_thread_safe`. Never read
Tk variables (`StringVar.get()` etc.) inside the worker; read them before starting it.

## Adding a tool

1. Put the physics in `scripts/<Tool>/<tool>_core.py` with tests in `tests/`.
2. Write `scripts/<Tool>/run_<tool>.py` with `class AnalysisWindow(ctk.CTkToplevel)` taking
   `(parent, origin_path="", api_key="")`; build the layout, then call
   `analysis_shell.attach_chrome(self, "<Title>", {...actions...}, hints="...")`.
3. Use `scripts.common.palette` for every colour and font; `theme.kv_table` for read-outs;
   `report.write_markdown_report` and `provenance.write_sidecar` for exports.
4. Register it in `TOOLS` of `Physiscore_Launcher.py`, in `selftest()` and in
   `tools/gui_smoke.py`. PyInstaller picks it up automatically (the spec collects every
   module under `scripts/` and `spectra/`).
5. Document it in USER_GUIDE.md and METHODS.md, add a CHANGELOG entry.

## Checks before a release

```bash
pytest -q tests                                   # unit tests
python Physiscore_Launcher.py --selftest          # imports + reference physics
python tools/gui_smoke.py                         # every window, the launcher, a session
python tools/validation_report.py > /dev/null     # validation table still builds
pyinstaller --noconfirm packaging/physiscore.spec # frozen build
dist/Physiscore.app/Contents/MacOS/Physiscore --selftest   # (macOS) frozen self-test
```

Release: bump `APP_VERSION` (Physiscore_Launcher.py), `pyproject.toml`, `CITATION.cff`;
add `docs/release-notes/<version>.md` and a CHANGELOG entry; push a `v<version>` tag. The
Release workflow builds Windows (installer + portable), macOS (arm64 + Intel DMG) and
Linux (.deb + .tar.gz), self-tests each build, test-installs the Windows installer, the
.deb and the .tar.gz, and publishes the files with `SHA256SUMS.txt`, which the in-app
updater verifies. *Run workflow* on the Actions tab builds without publishing.
