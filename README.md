# Physiscore

[![Tests](https://github.com/jongsu-king/physiscore/actions/workflows/ci.yml/badge.svg)](https://github.com/jongsu-king/physiscore/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22267588.svg)](https://doi.org/10.5281/zenodo.22267588)

**Physics-constrained analysis of thin-film photovoltaic device and material
characterisation: ten measurement techniques, one set of conventions, cross-checks between
them, and every number traceable to an equation, a test and a side-car file.**

Physiscore recomputes device and material parameters from the measured curves rather
than copying an instrument's summary block, applies the standard physical models
(one-diode equivalent circuit, detailed balance, Tauc/Urbach, Scherrer/Williamson–Hall,
Shirley background …) with stated defaults, and reports each quantity with its fit
quality. The algorithms are documented with equations and references in
[docs/METHODS.md](docs/METHODS.md) and validated against closed-form synthetic data in
[docs/VALIDATION.md](docs/VALIDATION.md).

| Technique | Derived quantities |
|---|---|
| **J–V (light)** | Voc, Jsc, FF, PCE, Vmpp, Rs, Rsh from the curve; one-diode fit (Jph, J0, n, Rs, Rsh); forward/reverse hysteresis index; group statistics; Jsc mismatch vs EQE |
| **J–V (dark)** | ideality factor n and J0 (sliding window), Rsh,dark, full one-diode fit with Rs, Cheung dV/dlnJ |
| **EQE** | AM1.5G-integrated Jsc (ASTM G173-03), Eg from dEQE/dE (Rau), Urbach energy, J0,rad, Voc,rad, Shockley–Queisser limits, ΔV1/ΔV2/ΔV3 loss breakdown |
| **Absorbance** | Tauc band gap with automatic linear region and standard error, derivative Eg, Urbach energy; A or α basis |
| **XRD** | ALS background, simultaneous pseudo-Voigt fitting, d-spacing, Scherrer (instrument-corrected), Williamson–Hall with uncertainties, Kα2 stripping, crystallinity index, cubic lattice parameter (Nelson–Riley) |
| **PL** | Savitzky–Golay + ALS, Gaussian/Voigt single or AIC-selected multi-component fits, energy axis with Jacobian, FWHM in nm and meV, quenching efficiency |
| **Raman / FTIR** | arPLS/ALS baselines, band detection and Lorentzian/Gaussian fitting, peak-shift tables, band library, T↔A |
| **SEM** | watershed grain segmentation, size distribution with D10/D50/D90 and log-normal fit |
| **XPS** | Shirley background, Voigt singlet/doublet fitting, charge referencing, atomic concentration |
| **Device summary** | J-V + EQE (+ absorbance, PL) of one device: Jsc cross-check, band gap from three techniques, Voc vs Voc,rad and Voc,SQ with the loss breakdown, fractions of the SQ limits |

Many files at once: *Compare files* in the spectroscopy tools and `physiscore batch` on the
command line tabulate whole series; XRD patterns can be matched against reference peak
lists; J-V curves can come from instrument text exports or from CSV/Excel files.

## Documentation

| Document | Content |
|---|---|
| [USER_GUIDE.md](docs/USER_GUIDE.md) | every window step by step, outputs, settings, troubleshooting |
| [METHODS.md](docs/METHODS.md) | equation, procedure, defaults and reference of every reported quantity |
| [VALIDATION.md](docs/VALIDATION.md) | each estimator against closed-form synthetic data |
| [FILE_FORMATS.md](docs/FILE_FORMATS.md) | accepted input layouts and the files Physiscore writes |
| [CLI.md](docs/CLI.md) | command-line reference |
| [INSTALL.md](docs/INSTALL.md) | installers, first start, checksums, automatic updates |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | module layout, principles, adding a tool, release checks |
| [CHANGELOG.md](CHANGELOG.md) | changes by version |

## Download

Ready-to-run programs (no Python needed) are attached to the
[latest release](https://github.com/jongsu-king/physiscore/releases/latest):

| System | File |
|---|---|
| Windows 10/11 (64-bit) | `Physiscore-<version>-windows-x64-setup.exe` (installer) or `…-windows-x64-portable.zip` |
| macOS, Apple silicon | `Physiscore-<version>-macos-arm64.dmg` |
| macOS, Intel | `Physiscore-<version>-macos-x86_64.dmg` |
| Ubuntu / Debian | `physiscore_<version>_amd64.deb` |
| Other Linux | `Physiscore-<version>-linux-x86_64.tar.gz` (run `install.sh`) |

Installation steps, first-start prompts of unsigned builds, checksums and uninstalling:
**[docs/INSTALL.md](docs/INSTALL.md)**. Installed copies update themselves (Tools →
Updates: download and install, only notify, or off).

## Installation from source

Python 3.10 or newer.

```bash
git clone https://github.com/jongsu-king/physiscore.git
cd physiscore
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python Physiscore_Launcher.py
```

`python Physiscore_Launcher.py --tool "J-V Curve"` opens one analysis window directly;
`--spectra XRD|PL|XPS` opens the auto-fit workspace.

## Command line

The same cores run without the GUI, for batch processing and scripts:

```bash
python physiscore_cli.py jv  measurements/2026-01-20 --area 0.04        # Excel + statistics + hysteresis
python physiscore_cli.py eqe device_A_eqe.csv --voc 1.12 --json          # Eg, Eu, Voc,rad, SQ, ΔV1..3
python physiscore_cli.py abs film.xlsx --sheet UV --mode direct          # Tauc Eg ± error, Urbach
python physiscore_cli.py xrd pattern.txt --instrument-fwhm 0.06 --strip-ka2
python physiscore_cli.py pl  spectrum.csv --max-peaks 3
python physiscore_cli.py vib raman.csv --technique raman
python physiscore_cli.py device --jv cell.txt --eqe cell_eqe.csv         # cross-technique summary
python physiscore_cli.py batch abs series/ --all-columns --out gaps.xlsx  # one row per spectrum
python physiscore_cli.py sq 1.60                                         # Shockley-Queisser limit
python physiscore_cli.py validate                                        # regenerate the validation table
```

`--json` prints the full result for other programs; `pip install .` also installs a
`physiscore` console command.

## Library use

```python
import numpy as np
from scripts.JV.jv_core import compute_jv_parameters, fit_single_diode
from scripts.EQE.eqe_core import analyze_eqe
from scripts.XRD.xrd_core import detect_peaks_and_fit, williamson_hall

p = compute_jv_parameters(v, j, pin_mw_cm2=100.0)      # Voc, Jsc, FF, PCE, Rs, Rsh ...
d = fit_single_diode(v, j)                               # Jph, J0, n, Rs, Rsh, R2
e = analyze_eqe(wavelength_nm, eqe_percent, voc_measured_v=1.10)
peaks, y_fit = detect_peaks_and_fit(two_theta, intensity, instrumental_fwhm_deg=0.05)
wh = williamson_hall(peaks["2Theta"], peaks["FWHM"], instrumental_fwhm_deg=0.05)
```

Shared primitives (baselines, line shapes, multi-peak fitting with AICc model
selection, Jacobian nm→eV conversion) live in `scripts/common/spectral.py`.

## Configuration

Settings are kept in `physisfera_config.json` (next to the source checkout, or in the
per-user settings folder of an installed copy: `%APPDATA%\Physiscore`,
`~/Library/Application Support/Physiscore`, `~/.config/Physiscore`). The main window's
**Settings** dialog edits them:

| Key | Meaning | Default |
|---|---|---|
| `cell_area_cm2` | device area for the current-density conversion (scales Jsc and PCE linearly; re-read for every analysis) | `0.04` |
| `theme` | `light` or `dark` appearance (applies after restart) | `light` |
| `origin_path` | OriginLab executable for the optional Origin export (Windows) | `""` |
| `gemini_api_key` | optional; enables the "Interpretation" commentary panels only | `""` |

No numerical result depends on the API key; the commentary is produced after the
physics and is never part of an exported table. See [CONFIG.md](CONFIG.md).

## Tests and validation

```bash
pip install pytest
pytest -q                          # 239 tests on closed-form synthetic data
python tools/validation_report.py  # the table in docs/VALIDATION.md
python tools/gui_smoke.py          # every window, the launcher and a session (needs a display)
```

Measured example files (a perovskite XRD pattern, XPS region scans) live in a local
`rawdata/` folder that is not published; the tests that need them are skipped when it is
absent.

## Citing

A software paper is in preparation; please cite the archived release in the meantime:

> Kim, K., Shin, J., Lim, J., Ji, H., Lee, S.-E., & Lee, J. (2026). *Physiscore*
> (Version 3.1.1) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22267588

The concept DOI always resolves to the latest archived release. Full metadata is in
`CITATION.cff`; the methods and their references are in [docs/METHODS.md](docs/METHODS.md).

## License

MIT — see `LICENSE`.

Copyright © 2026 [Hybrid Materials and Optoelectronics Laboratory (H-MOL)](https://sites.google.com/view/h-mol),
Incheon National University.
