# Physiscore

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22267588.svg)](https://doi.org/10.5281/zenodo.22267588)

**An integrated, physics-constrained analysis suite for thin-film photovoltaic device and material characterization.**

Physiscore unifies nine measurement techniques behind one interface and one set of
conventions, so that every parameter reported for a device is derived from the raw
measured curve rather than from an instrument summary block — and so that quantities
measurable by more than one technique (e.g. the optical band gap) can be cross-checked
within a single workflow.

| Technique | Derived quantities |
|---|---|
| **J–V (light)** | Voc, Jsc, FF, PCE, Vmpp, Jmpp, Pmax, Rs, Rsh — all from the curve |
| **J–V (dark)** | ideality factor *n*, saturation current *J*₀, dark Rsh |
| **EQE** | AM1.5G-integrated Jsc (ASTM G173-03, 2002 points), Eg, Urbach energy |
| **Abs** | Tauc-plot band gap with automatic linear-region selection |
| **XRD** | ALS background, simultaneous pseudo-Voigt fitting of overlapping reflections, d-spacing, Scherrer size, Williamson–Hall |
| **PL** | ALS baseline, windowed Gaussian/Voigt fitting, FWHM, quenching efficiency |
| **Raman / FTIR** | multi-layer loading, peak detection, peak-shift comparison |
| **SEM** | watershed grain segmentation, size distribution statistics |
| **XPS** | singlet / spin-orbit-doublet Voigt fitting, atomic concentrations |

## Why another analysis tool

Device parameters are routinely copied from the summary block a source-meter writes into
its export file. Those numbers depend on the instrument's own fitting settings, are not
reproducible across labs, and silently hide problems in the underlying sweep. Physiscore
recomputes every quantity from the measured points, keeps the derivation explicit, and
exports both its own values and the instrument's for cross-validation.

## Installation

Requires Python 3.10 or newer.

```bash
git clone https://github.com/jongsu-king/physiscore.git
cd physiscore
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Quick start

Launch the unified interface:

```bash
python Physiscore_Launcher.py
```

Or use the analysis cores directly as a library — they are GUI-free and importable:

```python
import numpy as np
from scripts.JV.jv_core import compute_jv_parameters

v = np.linspace(-0.2, 1.1, 261)
j = ...                      # measured current density [mA/cm^2]
p = compute_jv_parameters(v, j, pin_mw_cm2=100.0)
print(p["Voc"], p["Jsc"], p["FF"], p["PCE"], p["Rs"], p["Rsh"])
```

```python
from scripts.Dark_JV.dark_jv_core import analyze_dark_diode
d = analyze_dark_diode(v_dark, j_dark_abs)   # -> n, J0_mA_cm2, Rsh_dark_Ohm_cm2, fit_R2
```

```python
from scripts.XRD.xrd_core import detect_peaks_and_fit
peaks_df, y_fit = detect_peaks_and_fit(two_theta, intensity,
                                       instrumental_fwhm_deg=0.05, scherrer_k=0.9)
```

## Configuration

Copy the templates and edit them locally — the real files are git-ignored because they
hold machine-specific paths and an optional API key:

```bash
cp physisfera_config.example.json physisfera_config.json
```

`cell_area_cm2` (default `0.04`) sets the device area used for current-density
conversion; it is re-read for every analysis, so a correction applies to the next
folder you process. The AI-report feature is **optional**: with no API key
configured, every physics computation and export path behaves identically.

## Example data

Measured example files (a perovskite XRD pattern, XPS region scans for a glass
reference and a PEI-coated sample) live in a local `rawdata/` directory that is not
published here — those measurements are unpublished. The code does not require them:
the ASTM G173-03 reference spectrum used for J–V and EQE work is bundled in the
repository, and the test suite skips its measured-file checks when `rawdata/` is
absent.

## Tests

```bash
pip install pytest
pytest -v
```

The suite encodes analytical regression checks against closed-form synthetic data with
known ground truth (single-diode J–V curves, overlapping pseudo-Voigt reflections,
Gaussian PL peaks) and against measured reference files.

## Citing

A software paper is in preparation; please cite the archived release in the meantime:

> Kim, K., Shin, J., Lim, J., Ji, H., Lee, S., & Lee, J. (2026). *Physiscore* (Version 2.0.0)
> [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22267589

The concept DOI [10.5281/zenodo.22267588](https://doi.org/10.5281/zenodo.22267588) always
resolves to the latest release. Full metadata is in `CITATION.cff`.

## License

MIT — see `LICENSE`.

Copyright © 2026 [Hybrid Materials and Optoelectronics Laboratory (H-MOL)](https://sites.google.com/view/h-mol),
Incheon National University.
