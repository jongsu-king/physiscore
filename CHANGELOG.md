# Changelog

All notable changes to Physiscore. Versions follow semantic versioning; dates are the
release dates. Detailed release notes are in `docs/release-notes/`.

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
