# Architecture and developer notes

## Layout

```
Physiscore_Launcher.py      main window, settings, --open/--tool/--spectra/--selftest/--update/--version/--doc
physiscore_cli.py           command line (same cores, no GUI)
selfupdate.py               GitHub-release updater (standard library only)

scripts/common/             shared, GUI-free unless noted
  spectral.py               baselines (ALS, arPLS, Shirley), line shapes, multi-peak fit, AICc, nm->eV
  vibrational.py            Raman/FTIR preprocessing, band fitting, shift tables, band library
  band_library.json         70 indicative band positions
  device_summary.py         cross-technique checks and detailed balance of one device
  batch.py                  table readers and per-file analysers (compare windows + CLI batch)
  iv_io.py                  generic CSV/Excel I-V reader, result-file detection
  curve_io.py               column-aware table reader of the curve tools (names first, positions second)
  curve_batch.py            the curve tools without a window: parameters, load, analyse, checks,
                            interpretation, workbook (the windows and the CLI both call it)
  detect.py                 what kind of measurement a file is (name, headers, numbers), folder scan
  results_index.py          every .analysis.json below a folder as one table / workbook
  interpret.py              rule-based interpretation (findings from existing results)
  interpret_transport.py    the rules of the curve tools (transport, PLQY, spectral mismatch)
  provenance.py             .analysis.json side-cars
  report.py                 Markdown reports
  docs_viewer.py            offline documentation: Markdown -> HTML, opened in the browser at a section
  app_config.py             physisfera_config.json (area, Origin path, theme, presets)
  naming.py                 sample-name rules shared by the J-V parsers
  palette.py                light/dark colours, fonts, matplotlib style (no Tk)
  theme.py                  customtkinter theme from the palette, widget helpers, panel headers, table stripes (GUI)
  analysis_shell.py         menu bar, toolbar, status bar, figure export, thread-safe after() (GUI)
  plot_interactions.py      zoom/pan/context menus (GUI)
  plot_tools.py             data reader, plot details, journal-preset export, data worksheet (GUI)
  curve_tool.py             CurveToolWindow: the shared window of the curve tools (GUI)
  workspace_panel.py        Workspace and Results tabs of the launcher (GUI)
  interpret_window.py       the Interpretation window (GUI)
  sample_naming.py          rename/preset menus (GUI)
  compare_window.py         multi-file comparison window (GUI)
  origin.py                 OriginPro COM connection (Windows)

scripts/<Technique>/        one package per technique
  *_core.py                 physics, GUI-free (jv_core, dark_jv_core, eqe_core, abs_core, pl_core,
                            xrd_core, raman_core, ftir_core, sem_core, sclc_core, intensity_core,
                            trpl_core, eis_core, cv_core, stability_core, plqy_core, mismatch_core)
  run_*.py                  the tool window (class AnalysisWindow)
scripts/Device/run_device.py  Device summary window

spectra/                    auto-fit workspaces (PL, XRD, XPS)
  core/                     config, baseline, peak detection, Voigt fitting, XPS (Shirley, RSF)
  pipelines/                run_pl, run_xrd, run_xps
  gui/                      dashboard tab, PL tab

tests/                      pytest; closed-form synthetic data (conftest.py generators)
tools/                      validation_report.py, gui_smoke.py, screenshots.py, make_icons.py
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
5. **The interpretation never touches numbers.** `scripts/common/interpret.py` and
   `interpret_transport.py` read results that already exist and turn them into findings by
   explicit rules (threshold, formula, reference). They are deterministic, offline and have
   their own tests (`tests/test_interpret.py`, `tests/test_transport.py`).
6. **No network, no model service.** Nothing in an analysis leaves the computer; the only
   network access of the program is the update check against the GitHub releases.

## Threading

Long work runs in a worker thread and hands results back with `self.after(0, callback)`.
Some Tk builds (seen with Tk 9.0 on macOS) silently drop an `after()` issued from another
thread. `analysis_shell.make_thread_safe(widget)` wraps `after` so calls from worker
threads are queued and dispatched by a main-thread poller; `attach_chrome` applies it to
every tool window, and the comparison window and auto-fit tabs apply it themselves. New
threaded GUI code must either live in such a window or call `make_thread_safe`. Never read
Tk variables (`StringVar.get()` etc.) inside the worker; read them before starting it.

The code added in 3.5 does not use worker threads at all. Python may collect the Tk
objects of a closed window from whichever thread happens to be running, and Tcl must only
be entered from the thread that owns it; a Tk built without thread support (Tk 9.0 on
macOS has no `tcl_platform(threaded)`) then aborts the process. So:

- the curve tools analyse **one file per `after()` step** (`CurveToolWindow.run` ->
  `_run_step`), which keeps the window responsive and the status line counting;
- the Workspace tab classifies files in **slices of `SCAN_SLICE_S` = 0.04 s per event-loop
  turn** (`workspace_panel`), from the generator `detect.iter_folder`;
- the launcher calls `gc.collect()` on the Tk thread after each tool or comparison window
  closes, so that the fonts and images of the closed window are freed there.

Prefer this pattern for new code; a single analysis of these tools takes well under a
second.

## Look and feel

All colours, radii and type sizes are tokens in `scripts/common/palette.py` (light and
dark). Importing `scripts.common.theme` replaces customtkinter's built-in blue theme by the
palette (option menus, check boxes, sliders, text boxes ...) and keeps it replaced when a
module calls `ctk.set_default_color_theme("blue")` again; it also shades alternate rows of
every `ttk.Treeview`. `attach_chrome` ends with `theme.instrumentize(window)`: every group
box (a frame in `BG_CARD`) gets square corners and a hairline border, and its bold title -
or a title row of title plus small controls - becomes a grey header strip. New windows get
the look by building group boxes the usual way (a `BG_CARD` frame whose first child is a
bold label) and calling `attach_chrome`; `theme.panel_header(label)` does the same for a
title that is not inside such a box.

Graphs: `palette.apply_mpl()` installs Origin-like rcParams (black 1.5 pt box, ticks in on
four sides, one minor tick, no grid, Arial, Origin's colour order or Okabe-Ito), and
`theme` wraps `FigureCanvasTkAgg.draw` so that `palette.originize(fig)` restyles every
figure just before it is drawn - whatever a window's plotting code set. A user's grid
(View -> Toggle grid) is kept through `ax._physiscore_grid`; twin axes keep their sides.

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

## Adding a curve tool

A tool that takes one table per sample and returns a list of quantities (SCLC, light
intensity, TRPL, impedance, C-V, stability) needs far less:

1. `scripts/<Tool>/<tool>_core.py` with `COLUMN_SPEC` (the quantities and their header
   patterns), `analyse(...)`, `summary_rows(result)`, `checks(result)` and `simulate(...)`
   for the built-in example and the tests.
2. An entry in `curve_batch.TOOLS` (name, core, default parameters, choices, the columns of
   the all-files table) and a branch in `curve_batch.analyse`. The CLI command and the
   workbook follow from it (`physiscore_cli.py`: `CURVE_OPTIONS`, `CURVE_HELP`).
3. `scripts/<Tool>/run_<tool>.py` with `class AnalysisWindow(CurveToolWindow)`: `TOOL_NAME`,
   `SLUG`, `CORE`, `FILE_HINT`, `FIELDS` (the parameter panel), `VIEWS`, `BATCH`,
   `METHOD_SECTION` (the METHODS section that *Help > Methods of this tool* opens), `NOTES`
   (the methods note of the report), `demo()` and `draw(fig, data, result, view, params,
   others)`. File list, parameter memory, run loop, tables, Excel, report, interpretation
   and graph tools come from the base class.
4. Rules in `interpret_transport.py`, a kind in `detect.KINDS` with its evidence rules, an
   icon (`tools/make_icons.py` draws the six existing ones), then the registration of
   step 4 above, tests in `tests/test_transport.py` / `test_curve_batch.py` /
   `test_workspace.py` and rows in `tools/validation_report.py`.

## Checks before a release

```bash
pytest -q tests                                   # unit tests
python Physiscore_Launcher.py --selftest          # imports + reference physics
python tools/gui_smoke.py                         # every window, the launcher, a session
python tools/validation_report.py > /dev/null     # validation table still builds
# the release notes docs/release-notes/<version>.md must exist: the self-test checks it
python tools/screenshots.py                       # (macOS) docs/images; needs pyobjc-framework-Quartz
pyinstaller --noconfirm packaging/physiscore.spec # frozen build
dist/Physiscore.app/Contents/MacOS/Physiscore --selftest   # (macOS) frozen self-test
```

Release: bump `APP_VERSION` (Physiscore_Launcher.py), `pyproject.toml`, `CITATION.cff`;
add `docs/release-notes/<version>.md` and a CHANGELOG entry; push a `v<version>` tag. The
Release workflow builds Windows (installer + portable), macOS (arm64 + Intel DMG) and
Linux (.deb + .tar.gz), self-tests each build, test-installs the Windows installer, the
.deb and the .tar.gz, and publishes the files with `SHA256SUMS.txt`, which the in-app
updater verifies. *Run workflow* on the Actions tab builds without publishing.
