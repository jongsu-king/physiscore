# Validation against closed-form synthetic data

Every row compares a quantity recovered by Physiscore 3.3.0 with the value that was
put into an analytical model (single-diode J-V curves, error-function EQE edges,
Tauc edges with Urbach tails, pseudo-Voigt reflections, Gaussian/Lorentzian bands,
Shirley-type XPS backgrounds, log-normal grain sizes, strained cubic lattices). The
deviation column is therefore the extraction error alone; for the cross-technique rows
the "reference" is the independent calculation the summary must reproduce. The table is
regenerated with

```bash
python tools/validation_report.py          # or: python physiscore_cli.py validate
```

and the same cases are enforced as unit tests in `tests/` (`pytest`, 272 tests).
Measured-data checks (a perovskite XRD pattern, XPS region scans) run when a local
`rawdata/` folder is present and are skipped otherwise, because those measurements
are unpublished.

Known, documented limitations visible in the table: a single Gaussian fitted to a PL band
with an unresolved neighbour is biased (+7 % FWHM; the multi-component fit removes most of
it), the plain mean of a lattice parameter keeps a specimen-displacement error that the
Nelson-Riley extrapolation removes, and the Rau band gap of an error-function edge sits
within 1 meV of its centre.

| Technique | Quantity | Reference | Recovered | Unit | Dev. (%) | Conditions |
|---|---|---:|---:|---|---:|---|
| J-V (light) | Voc | 0.916965 | 0.916903 | V | -0.007 | single-diode model, 10 mV steps |
| J-V (light) | Jsc | 21.978 | 21.978 | mA/cm2 | +0.000 | single-diode model, 10 mV steps |
| J-V (light) | FF | 77.4396 | 77.4441 | % | +0.006 | single-diode model, 10 mV steps |
| J-V (light) | PCE | 15.6065 | 15.6063 | % | -0.001 | single-diode model, 10 mV steps |
| J-V (light) | Vmpp | 0.760572 | 0.760034 | V | -0.071 | single-diode model, 10 mV steps |
| J-V (light) | Rsh | 2000 | 2002 | Ohm cm2 | +0.100 | from dV/dJ slope at Jsc |
| J-V (light) | Jph, diode fit | 22 | 22 | mA/cm2 | -0.000 | one-diode fit (Lambert-W), 10 mV steps |
| J-V (light) | n, diode fit | 1.5 | 1.5 | - | -0.000 | one-diode fit (Lambert-W), 10 mV steps |
| J-V (light) | log10 J0, diode fit | -9 | -9 | log10(mA/cm2) | -0.000 | one-diode fit (Lambert-W), 10 mV steps |
| J-V (light) | Rs, diode fit | 2 | 2 | Ohm cm2 | +0.000 | one-diode fit (Lambert-W), 10 mV steps |
| J-V (light) | Rsh, diode fit | 2000 | 2000 | Ohm cm2 | -0.000 | one-diode fit (Lambert-W), 10 mV steps |
| J-V (light) | hysteresis index | 7.73288 | 7.73288 | % | +0.000 | forward + reverse sweep split automatically |
| J-V (dark) | n, full fit with Rs | 1.8 | 1.8 | - | +0.000 | log-space residuals |
| J-V (dark) | Rs, full fit | 5 | 5 | Ohm cm2 | -0.000 |  |
| J-V (dark) | Rsh, full fit | 50000 | 50000 | Ohm cm2 | +0.000 |  |
| J-V (dark) | Rs, Cheung dV/dlnJ | 5 | 4.98927 | Ohm cm2 | -0.215 | J > 5% of maximum |
| J-V (dark) | n, Cheung intercept | 1.8 | 1.80396 | - | +0.220 |  |
| J-V (dark) | ideality n (input 1.0) | 1 | 1 | - | -0.000 | shunt negligible |
| J-V (dark) | ideality n (input 1.5) | 1.5 | 1.5 | - | -0.000 | shunt negligible |
| J-V (dark) | ideality n (input 1.85) | 1.85 | 1.85 | - | -0.000 | shunt negligible |
| J-V (dark) | ideality n (input 2.5) | 2.5 | 2.5 | - | -0.000 | shunt negligible |
| J-V (dark) | ideality n, shunted device | 1.85 | 1.86064 | - | +0.575 | auto window 0.95-1.20 V |
| J-V (dark) | Rsh (dark) | 50000 | 49999.7 | Ohm cm2 | -0.001 | low-bias ohmic slope |
| J-V (dark) | log10 J0 | -9 | -9 | log10(mA/cm2) | -0.000 |  |
| EQE | Eg from dEQE/dE distribution | 1.6 | 1.59967 | eV | -0.021 | error-function edge, sigma 30 meV |
| EQE | edge width sigma | 0.0177 | 0.0180131 | eV | +1.769 | std over the half-maximum window |
| EQE | Urbach energy | 20 | 20 | meV | +0.000 | exponential tail, auto window |
| EQE | Voc,rad of a step absorber | 1.32442 | 1.32527 | V | +0.064 | must equal Voc,SQ |
| EQE | SQ efficiency at 1.34 eV | 33.7 | 33.6802 | % | -0.059 | literature 33.7% (Ruhle 2016) |
| EQE | SQ Jsc at 1.34 eV | 35.4 | 35.0189 | mA/cm2 | -1.077 |  |
| EQE | AM1.5G integral | 1000.4 | 1000.37 | W/m2 | -0.003 | ASTM G173-03 table |
| Abs | Eg, automatic Tauc region | 1.598 | 1.588 | eV | -0.626 | direct edge with Urbach tail |
| Abs | Eg, derivative | 1.6 | 1.60394 | eV | +0.246 | max dA/dE |
| Abs | Urbach energy | 25 | 25 | meV | +0.000 | ln A vs E |
| XRD | 2theta @ 28.2 deg | 28.2 | 28.2001 | deg | +0.000 | overlapping doublet, dtheta = 0.40 deg, ALS background |
| XRD | FWHM @ 28.2 deg | 0.15 | 0.149954 | deg | -0.031 | overlapping doublet, dtheta = 0.40 deg, ALS background |
| XRD | Scherrer tau @ 28.2 deg | 54.6071 | 54.6239 | nm | +0.031 | K = 0.9, Cu Kalpha |
| XRD | 2theta @ 28.6 deg | 28.6 | 28.5999 | deg | -0.001 | overlapping doublet, dtheta = 0.40 deg, ALS background |
| XRD | FWHM @ 28.6 deg | 0.18 | 0.17984 | deg | -0.089 | overlapping doublet, dtheta = 0.40 deg, ALS background |
| XRD | Scherrer tau @ 28.6 deg | 45.5462 | 45.5866 | nm | +0.089 | K = 0.9, Cu Kalpha |
| XRD | Williamson-Hall D | 40 | 40 | nm | -0.000 | 8 reflections |
| XRD | Williamson-Hall strain | 0.002 | 0.002 | - | -0.000 |  |
| XRD | cubic a, Nelson-Riley (displaced specimen) | 6.28 | 6.27986 | A | -0.002 | 0.08 cos(theta) deg displacement error |
| XRD | cubic a, plain mean (same data) | 6.28 | 6.26073 | A | -0.307 | for comparison |
| XRD | Kalpha2 residual after stripping | 0 | 5.32375 | % of satellite | +nan | Rachinger |
| PL | peak centre | 750 | 750 | nm | +0.000 | ALS baseline (lam = 1e8) + sloping background |
| PL | FWHM | 40 | 39.5422 | nm | -1.144 | isolated peak |
| PL | peak centre, overlapping band | 750 | 751.07 | nm | +0.143 | defect band at 830 nm; valley-bounded window |
| PL | FWHM, overlapping band | 40 | 42.8401 | nm | +7.100 | residual bias: single-Gaussian model |
| Spectral | overlapping Gaussian centre 1 | 48 | 48 | x | +0.000 | two components fitted together |
| Spectral | overlapping Gaussian FWHM 2 | 5 | 5 | x | +0.000 |  |
| Spectral | components chosen by AICc | 2 | 2 | - | +0.000 | noisy doublet |
| PL | integrated intensity after nm->eV (Jacobian) | 42578.7 | 42578.7 | a.u. | +0.000 | area conserved |
| PL | FWHM, multi-component fit with defect band | 40 | 40.0129 | nm | +0.032 | AICc, 2 components |
| Raman | band height after arPLS baseline | 100 | 97.1518 | a.u. | -2.848 | fluorescence background |
| Raman | Lorentzian FWHM | 6 | 5.97022 | cm-1 | -0.496 |  |
| XPS | Shirley background error (max) | 0 | 4.09818e-07 | % of step | +nan |  |
| XPS | atomic % O for equal C and O | 50 | 50 | at.% | +0.000 | Scofield factors |
| SEM | log-normal sigma | 0.35 | 0.348423 | - | -0.451 | 5000 grains, MLE |
| SEM | geometric mean | 300 | 299.524 | nm | -0.159 |  |
| Device | Jsc mismatch | 1.21803 | 1.21803 | % | +0.000 | single-diode J-V vs error-function EQE |
| Device | dV1 + dV2 + dV3 | 0.682769 | 0.682769 | V | +0.000 | loss terms close the Voc deficit |
| Device | band-gap spread | 30 | 30 | meV | +0.000 | EQE 1.60, Tauc 1.61, PL 1.58 eV |
| XRD | lattice strain from reference match | 0.003 | 0.00299999 | - | -0.000 | 7 reflections, a = 1.003 a0 |
| XRD | reference coverage | 1 | 1 | - | +0.000 |  |

_Generated 2026-11-10 with Physiscore 3.3.0, numpy 2.4.6, scipy 1.17.1._
