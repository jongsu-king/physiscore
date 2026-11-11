# Changelog

All notable changes to Physiscore. Versions follow semantic versioning; dates are the
release dates. Detailed release notes are in `docs/release-notes/`.

## [3.5.1] - 2026-11-11

Documentation release; the program and the numbers it computes are the same as in 3.5.0.

### Fixed
- The picture of the Updates tab in the user guide (`docs/images/updates.png`) showed a
  state that never existed: "Latest release seen 9.9.9" and "9.9.9 is available". It had
  been left on the machine that took the pictures by a local test of the updater, and the
  installers of 3.3.1, 3.4.0 and 3.5.0 carry it in their offline documentation. The
  picture is retaken from a clean state. No such release exists and the program itself
  never showed it.
- `docs/METHODS.md`, section 6: the band library holds 74 entries, not 70.

### Changed
- `tools/screenshots.py` keeps the updater's settings in the temporary folder of the run,
  so the documentation pictures no longer depend on the machine that takes them.

## [3.5.0] - 2026-11-10

### Added
- Six analysis tools (17 in total), each with a window, a command, an Excel workbook
  with side-car, rule-based interpretation and validation rows. All of them run on the
  computer; none uses a network or a model service.
  - **SCLC** (`scripts/SCLC`): ohmic, trap-filling and Child regimes from the local
    slope, V_TFL and trap density with its resolution limit, Mott-Gurney mobility
    (optionally Murgatroyd), conductivity and n0, sweep hysteresis.
  - **Light intensity** (`scripts/Intensity`): ideality factor from Voc against
    ln(irradiance) with its error, Jsc power law, Suns-Voc pseudo J-V, pseudo fill factor
    and transport loss; reads a table or a set of J-V files with the irradiance in the name.
  - **TRPL** (`scripts/TRPL`): one to three exponentials or a stretched exponential
    chosen by AICc, Poisson weights for counts, mean lifetimes, differential lifetime,
    diffusion length from an entered mobility.
  - **Impedance** (`scripts/EIS`): complex least-squares fit of R(RC), R(RQ), R(RC)(RC),
    R(RQ)(RQ) chosen by AICc, parameter errors, effective capacitance, linear
    Kramers-Kronig test, automatic sign convention of Z''.
  - **C-V (Mott-Schottky)** (`scripts/CV`): straight section of 1/C² found
    automatically, doping density, built-in voltage, depletion width, doping profile,
    full-depletion limit.
  - **Stability** (`scripts/Stability`): T80 measured or extrapolated (marked), burn-in
    model chosen by AICc, stabilised Ts80, loss rate per 1000 h, ISOS protocol on record.
- **Open data** (Ctrl+O) recognises the measurement in a file from its name, column
  headers and numbers and opens it in the right tool; **Workspace folder**
  (Ctrl+Shift+O) lists a project folder that way (Workspace tab: measurement,
  confidence, the evidence behind it, Open selected / Open with / Compare selected).
  `scripts/common/detect.py`; launcher option `--open FILE ... | FOLDER`.
- **Results** tab and File > *Collect results to Excel*: every export below the
  workspace folder with its key numbers, read from the side-cars
  (`scripts/common/results_index.py`).
- Graph tools in every window (`scripts/common/plot_tools.py`): Data reader (Ctrl+R),
  Plot details (Ctrl+P), Data worksheet (Ctrl+D), Export figure with journal presets of
  85, 114, 174 and 254 mm width (Ctrl+Shift+S); also in the graph's right-click menu.
- Help > *Methods of this tool* opens the offline methods document at the section of
  the window in use.
- Commands `sclc`, `intensity`, `trpl`, `eis`, `cv`, `stability`, `detect`, `collect`.
- Interpretation rules for the six tools (`scripts/common/interpret_transport.py`,
  METHODS §16.13-16.18); METHODS §17-§23; user guide sections 13 and 14; FILE_FORMATS
  §9-§10; "Adding a curve tool" in ARCHITECTURE.
- Tests: `test_transport.py` (49), `test_curve_batch.py` (39), `test_workspace.py` (39);
  24 new rows in the validation table.

### Changed
- Main window: toolbar with Open data and Workspace folder, the Workspace and Results
  tabs in front of Session, a new tool group *Transport and recombination*.
- Absorbance also reads text exports (`.csv .tsv .txt .dat .asc`), not only Excel; the
  XRD file dialog accepts `.xy` and `.dat`.
- The Absorbance, EQE, PL, XRD, FE-SEM, Raman and FTIR windows and the auto-fit
  workspaces accept a file handed over by the Workspace tab or the command line
  (`python -m spectra.app XPS scan.csv`).
- The new windows do their work on the main thread in short steps (one file per step,
  folder scans in 0.04 s slices) instead of worker threads.
- A side-car written for a built-in example records the example's name instead of a
  file path.

## [3.4.0] - 2026-11-10

### Changed
- Interpretation is rule-based and offline in every window. The Gemini panels, chat and
  advisor (J-V, PL, XRD, Raman, FTIR, SEM, the auto-fit workspaces) and the API-key field
  are removed; `scripts/common/interpret.py` produces findings with level, evidence, rule,
  reference and next step, shown in one window (`interpret_window.py`) with Copy and Save
  Markdown. Same input, same text; nothing is sent over the network.
- Raman/FTIR *Assign bands* and *Compare* use the band library and the peak matching
  (`vib_interpret.py`) instead of Gemini requests.
- The auto-fit peak report (`spectra/core/report.py`, `generate_peak_report`) carries the
  rule-based findings in place of the Gemini section; the XRD/PL/XPS workspaces have an
  **Interpret fit** button.
- `google-generativeai` and `pydantic` are no longer dependencies; the installers exclude
  the Google SDK. A `gemini_api_key` stored by an older version is removed from
  `physisfera_config.json` the next time the settings are saved.
- Analysis windows take `(parent, origin_path)`; the API-key argument is gone.

### Added
- Rule sets (METHODS §16): Green's FF loss split (recombination, series, shunt), ideality
  regimes, normalised Rs/Rsh, S-shape and hysteresis; batch statistics (CV, modified
  z-score outliers, Welch t-test with Holm correction, Hedges' g, practical-significance
  note); dark J-V; EQE (Urbach, Jsc vs the detailed-balance limit, AM1.5G-weighted
  spectral losses, radiative and non-radiative voltage losses with EQE_EL); Tauc
  (linearity, the other transition, edge position); PL (width in kT, quenching, shifts,
  Stokes shift); XRD (Scherrer, Williamson-Hall, coverage, secondary-phase lines, Harris
  texture); SEM (width, bimodality coefficient, log-normal KS test); FTIR functional
  groups and Raman/FTIR shifts; XPS (metallic Pb, Pb 4f doublet, I/Pb, C 1s reference,
  O 1s caution); auto-fit tables (Currie detection and quantification limits, unresolved
  neighbours, residual against noise); device summary.
- Interpretation in the Device summary window.
- Tests: `test_interpret.py` (25), `test_vib_interpret.py` (4), an end-to-end XPS
  auto-fit interpretation test, and a check that no source module imports an LLM SDK.
- User guide section 16 (Interpretation) with a screenshot.

## [3.3.1] - 2026-11-10

First published build of 3.3.0 (the program is unchanged).

### Fixed
- Tests on a headless Linux runner: a test imported `matplotlib.pyplot` before modules that
  call `matplotlib.use("TkAgg")`, which then failed. The test uses `Figure` directly and the
  modules accept a headless run.

## [3.3.0] - 2026-11-10 (tagged, not published; released as 3.3.1)

### Added
- Origin-style graphs in every window and in exported figures (`palette.originize`, applied
  before every canvas draw): black 1.5 pt box, ticks in on four sides with one minor tick,
  no grid, Arial, square black legend, Origin's colour order; *Settings → Plot colours*
  (Origin or colour-blind safe). The graph page stays white in the dark theme.
- Offline documentation bundled with every installer (`scripts/common/docs_viewer.py`):
  Help menu, F1, *User guide* and *Method notes* (at the tool's section), Windows Start-menu
  and Linux desktop actions, `Physiscore --doc NAME`, `physiscore docs NAME [--section]`;
  the build self-test checks that it is bundled.
- Updates tab in the main window (installation type, self-update ability, setting, last
  check, latest release, state; Check now, Install now and restart, What's new, Release
  page); the release notes open on the first start after an update; `physiscore update
  [--check-only]`.
- Tool panel: results, defaults and references of each tool; session, updates, recent
  folders and conventions in tabs.

### Fixed
- `physiscore` CLI returned 0 even when a command reported a failure.

### Tests
- Markdown conversion, bundled documents and section anchors, Origin pass (twin axes,
  user grid, legend), colour order, CLI docs; 272 tests.

## [3.2.0] - 2026-11-10

### Changed
- Instrument-style interface: main window as a workbench (tool tree; tool panel with
  input, output and method notes; session settings; recent folders; conventions).
- Every tool window: square group boxes with grey title strips (`theme.instrumentize`,
  applied by `attach_chrome`), compact type, grouped flat toolbar, ruled and striped
  tables, palette-coloured option menus/check boxes/sliders (customtkinter theme from the
  palette, kept when a module resets it), neutral statistic tiles, plain plot titles and
  boxed annotations in EQE and Tauc plots. Auto-fit workspaces included.

### Tests
- Design tokens, customtkinter theme hook, panel-header pass; 266 tests.

## [3.1.2] - 2026-11-10

### Fixed
- PL single-band fit: noise dips beside a weak band were taken as valleys to a neighbour,
  which narrowed the fit window and the FWHM (2-4x too small at peak/noise 15-40). A valley
  must now exceed 2 % of the peak and 6 noise standard deviations measured inside the band.
- XPS auto-fit: overlapping singlet candidates are fitted together and every component is
  bounded near its seed, so a small peak beside a large one keeps its own component.
- FE-SEM: statistics, histogram, Excel export and report failed after segmentation
  (missing module import); invisible table headers.
- Light theme: white-on-white titles in Raman/FTIR, segmented-button text, FE-SEM headers.
- PL window layout at 1440 px; EQE subplot overlaps; Device summary table columns; dark
  J-V "non" placeholder and y range; FTIR and auto-fit axis labels; XPS energy axis reversed.

### Added
- Screenshots of every window in the README and the user guide (`docs/images/`,
  `tools/screenshots.py`).
- Tests for the fixes and a static undefined-name check (pyflakes) in CI; 263 tests.

## [3.1.1] - 2026-11-09

First published build of the 3.1.0 features; the program is unchanged from 3.1.0.

### Fixed
- The updater's end-to-end tests wait for the background helper to finish its
  cleanup and write its log line, instead of checking the instant the new copy
  appears. On the slower Intel macOS runner the check failed, so the 3.1.0 tag was
  never published.

## [3.1.0] - 2026-11-09 (tagged, not published; released as 3.1.1)

### Added
- **Device summary** tool: J-V, EQE, absorbance and PL of one device in one window. Jsc
  from J-V against the AM1.5G-integrated EQE (mismatch warning above 5 %), the band gap
  from three techniques with its spread and the Stokes shift, Voc against Voc,rad and
  Voc,SQ with the ΔV1/ΔV2/ΔV3 breakdown and EQE_EL, Jsc/FF/PCE as fractions of their
  Shockley-Queisser values; four plots, Excel, report (`scripts/common/device_summary.py`,
  `scripts/Device/run_device.py`).
- **J-V from CSV/TSV/DAT/Excel** files: voltage and current columns recognised by their
  headers (current density, mA or A), sign normalised (`scripts/common/iv_io.py`); also in
  dark J-V.
- **Curve-derived summaries**: a J-V file without the instrument summary block gets Voc,
  Jsc, FF and PCE from its curve, so it enters the statistics, box charts and best-device
  selection (column *Summary source*).
- **XRD reference matching**: load a reference peak list (2θ or d, hkl, intensity); ticks
  with hkl on the plot, a match table with shifts and lattice strain, coverage, and the
  unassigned peaks of another phase; repeated after every fit.
- **XRD Excel export** (peaks, pattern with fit, Williamson-Hall, reference match,
  crystallinity).
- **Compare files** in EQE, Absorbance, PL, XRD, Raman and FTIR: many files (or every column
  of each) analysed side by side with a normalised, offset overlay and an Excel export
  (`scripts/common/compare_window.py`, `scripts/common/batch.py`).
- **Side-car files**: every Excel export writes `<name>.analysis.json` with the version,
  date, inputs, parameters and results (`scripts/common/provenance.py`); files with a
  side-car are never read back as input.
- CLI: `device` and `batch` commands.
- Documentation: USER_GUIDE, FILE_FORMATS, CLI, ARCHITECTURE, this changelog,
  CONTRIBUTING, SECURITY, issue and pull-request templates.

### Changed
- `tools/gui_smoke.py` opens each window in its own process and adds a launcher-session
  check (one launcher, every tool opened and closed as its child) and a check that no tool
  card reports *Unavailable*.
- SEM image dialog lists image formats only.

### Tests
- 239 unit tests (15 new); 13 GUI smoke checks.

## [3.0.0] - 2026-11-09

### Added
- Shared spectral module: ALS, arPLS and Shirley baselines; Gaussian, Lorentzian,
  pseudo-Voigt and Voigt line shapes; bounded multi-peak fitting with uncertainties; AICc/BIC
  model selection; Jacobian nm→eV conversion; peak matching.
- J-V: explicit Lambert-W one-diode model and five-parameter fit; forward/reverse
  splitting and hysteresis index; Jsc mismatch. Dark J-V: full fit with series resistance;
  Cheung analysis.
- EQE core: Rau band gap, automatic Urbach window, J0,rad and Voc,rad, Shockley-Queisser
  limits, voltage-loss breakdown. Absorbance core: automatic Tauc region with standard
  error, derivative band gap, Urbach energy.
- XRD: instrument-corrected Scherrer, Williamson-Hall with uncertainties, Rachinger Kα2
  stripping, crystallinity index, cubic lattice parameter (Nelson-Riley), texture
  coefficient.
- PL: energy axis with Jacobian, AIC-selected multi-component fits, peak metrics.
- Raman/FTIR: preprocessing, band fitting, shift tables, band library, T↔A.
- SEM: D10/D50/D90 and log-normal statistics. XPS: Shirley background, charge
  referencing, Scofield factors, atomic concentration, XPS auto-fit tab.
- Command-line interface; METHODS.md and VALIDATION.md; Markdown reports.

### Changed
- Instrument-style interface: light theme by default, menu bars and shortcuts, plain-text
  toolbars, cursor read-out, compact result tables; emoji and marketing labels removed.
- The Gemini commentary is optional and labelled "Interpretation".
- Old Windows-only build files moved to `_legacy/`.

### Fixed
- Worker-thread callbacks were dropped on Tk 9.0 (macOS), so tools never showed their
  results; `analysis_shell.make_thread_safe`.
- Absorbance window crashed on open (missing close handler).

## [2.1.0] - 2026-11-09 (not released separately; folded into 3.0.0)

- Installers for Windows, macOS (Apple silicon and Intel) and Linux; automatic updates
  verified against `SHA256SUMS.txt`; built-in J-V window on macOS and Linux; per-user
  settings folder for installed copies.

## [2.0.0] - 2026-09-03

- First public release: unified interface for J-V (light and dark), EQE, absorbance, XRD,
  PL, Raman, FTIR, SEM and XPS; curve-derived J-V parameters; AM1.5G Jsc with the full
  ASTM G173-03 table; ALS + simultaneous pseudo-Voigt XRD fitting with Scherrer sizes;
  windowed PL fitting; regression tests on synthetic data. Zenodo DOI
  10.5281/zenodo.22267589.
