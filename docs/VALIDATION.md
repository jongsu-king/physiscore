# Validation against closed-form synthetic data

Every row compares a quantity recovered by Physiscore 3.5.3 with the value that was
put into an analytical model (single-diode J-V curves, error-function EQE edges,
Tauc edges with Urbach tails, pseudo-Voigt reflections, Gaussian/Lorentzian bands,
Voigt spin-orbit doublets,
Shirley-type XPS backgrounds, log-normal grain sizes, strained cubic lattices,
piecewise space-charge-limited curves, one-diode intensity series, multi-exponential
decays with counting noise, equivalent-circuit impedance spectra, one-sided-junction
capacitance, burn-in plus linear degradation traces). The
deviation column is therefore the extraction error alone; for the cross-technique rows
the "reference" is the independent calculation the summary must reproduce. The table is
regenerated with

```bash
python tools/validation_report.py          # or: python physiscore_cli.py validate
```

and the same cases are enforced as unit tests in `tests/` (`pytest`, 455 tests).
Measured-data checks (a perovskite XRD pattern, XPS region scans) run when a local
`rawdata/` folder is present and are skipped otherwise, because those measurements
are unpublished.

Known, documented limitations visible in the table: a single Gaussian fitted to a PL band
with an unresolved neighbour is biased (+7 % FWHM; the multi-component fit removes most of
it), the plain mean of a lattice parameter keeps a specimen-displacement error that the
Nelson-Riley extrapolation removes, and the Rau band gap of an error-function edge sits
within 1 meV of its centre. The transport rows with noise show what the noise allows, not
a bias of the method: TRPL lifetimes within about 1 % at 10^4 peak counts, impedance
parameters within 0.1 % at 0.3 % noise, and the burn-in loss and the loss rate of a
stability trace within 4 % at 0.4 % noise (the two trade against each other in the fit,
while T80 itself stays within 1 %). The XPS auto-fit rows with a metallic shoulder fit
Voigt profiles to GL(30) lines under Poisson noise and give the median of 12 noise
realisations; a single spectrum scatters more (Pb0/Pb2+ from 0.074 to 0.144 for the
10th to 90th percentile of 40 realisations, true 0.095). Up to 3.5.1 the auto-fit never
fitted the Lorentzian width; the same rows then gave +35.5, +20.6 and +3.1 % for the
three doublet areas, gamma 0.486 eV for 0.300, and +40 % (4f7/2 area) and -33 %
(Pb0/Pb2+) for the shoulder case. The XRD auto-fit pipeline rows (smoothing, AsLS
baseline, lines fitted to the unsmoothed counts minus the baseline) keep one limitation:
the areas come out 5 to 10 % low because the baseline follows part of the Lorentzian
tails (the row for the line at 14.1 deg; with the true background the areas are within
1 %). Up to 3.5.2 the auto-fit fitted the smoothed curve: FWHM +2 to +29 % on the same
pattern and +174 % for the 0.11 deg line at 50.5 deg, and on a 0.2 eV XPS scan +7.5 %;
the doublet mode then returned four doublets for the two of the Pb 4f example.

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
| SEM | log-normal sigma | 0.35 | 0.348423 | - | -0.451 | 5000 grains, sample s.d. of ln d |
| SEM | geometric mean | 300 | 299.524 | nm | -0.159 |  |
| XPS auto-fit | Pb 4f7/2 area, Gaussian-dominated | 1000 | 999.462 | counts eV | -0.054 | Voigt doublet, sigma 0.36 / gamma 0.22 eV, split and 3:4 ratio fixed |
| XPS auto-fit | Pb 4f7/2 area, mixed | 1000 | 999.44 | counts eV | -0.056 | Voigt doublet, sigma 0.25 / gamma 0.3 eV, split and 3:4 ratio fixed |
| XPS auto-fit | Lorentzian half-width gamma | 0.3 | 0.299936 | eV | -0.021 | Voigt doublet, sigma 0.25 / gamma 0.3 eV, split and 3:4 ratio fixed |
| XPS auto-fit | Voigt FWHM | 0.97233 | 0.97228 | eV | -0.005 | Voigt doublet, sigma 0.25 / gamma 0.3 eV, split and 3:4 ratio fixed |
| XPS auto-fit | Pb 4f7/2 area, Lorentzian-dominated | 1000 | 999.653 | counts eV | -0.035 | Voigt doublet, sigma 0.1 / gamma 0.45 eV, split and 3:4 ratio fixed |
| XPS auto-fit | Pb 4f7/2 area with metallic shoulder | 4000 | 3939.7 | counts eV | -1.507 | pipeline, GL(30) lines + Shirley step, Poisson, median of 12 |
| XPS auto-fit | Pb0 / Pb2+ area ratio | 0.095 | 0.0915749 | - | -3.605 | pipeline, GL(30) lines + Shirley step, Poisson, median of 12 |
| XRD auto-fit | Voigt area, line at 28.4 deg | 500 | 500.697 | counts deg | +0.139 | neighbour 3.5 deg away, window to the midpoint, no smoothing |
| XRD auto-fit | Voigt area, line at 31.9 deg | 300 | 300.629 | counts deg | +0.210 | neighbour 3.5 deg away, window to the midpoint, no smoothing |
| XRD auto-fit | Voigt FWHM, line at 50.5 deg | 0.108039 | 0.106875 | deg | -1.077 | pipeline, 5 Voigt lines on a broad hump, Poisson, median of 4 |
| XRD auto-fit | Voigt FWHM, line at 31.9 deg | 0.325313 | 0.333512 | deg | +2.520 | pipeline, 5 Voigt lines on a broad hump, Poisson, median of 4 |
| XRD auto-fit | Voigt area, line at 14.1 deg | 800 | 720.032 | counts deg | -9.996 | pipeline, 5 Voigt lines on a broad hump, Poisson, median of 4; AsLS baseline takes part of the tails |
| XPS auto-fit | Pb 4f7/2 FWHM, 0.2 eV steps | 0.95 | 0.947342 | eV | -0.280 | pipeline, GL(30) lines + Shirley step, Poisson, median of 8 |
| XPS auto-fit | Pb 4f7/2 area, doublet mode | 4000 | 3950.38 | counts eV | -1.241 | doublet mode (4.87 eV, 3:4), GL(30) lines + Shirley step, Poisson, median of 40 |
| XPS auto-fit | Pb0 / Pb2+ area ratio, doublet mode | 0.095 | 0.100279 | - | +5.557 | doublet mode (4.87 eV, 3:4), GL(30) lines + Shirley step, Poisson, median of 40 |
| Device | Jsc mismatch | 1.21803 | 1.21803 | % | +0.000 | single-diode J-V vs error-function EQE |
| Device | dV1 + dV2 + dV3 | 0.682769 | 0.682769 | V | +0.000 | loss terms close the Voc deficit |
| Device | band-gap spread | 30 | 30 | meV | +0.000 | EQE 1.60, Tauc 1.61, PL 1.58 eV |
| XRD | lattice strain from reference match | 0.003 | 0.00299999 | - | -0.000 | 7 reflections, a = 1.003 a0 |
| XRD | reference coverage | 1 | 1 | - | +0.000 |  |
| SCLC | V_TFL | 4.52378 | 4.52378 | V | +0.000 | piecewise ohmic / trap-filling / Child curve, 500 nm, eps_r 25 |
| SCLC | trap density | 5e+16 | 5e+16 | cm-3 | +0.000 | n_t = 2 eps V_TFL / (q L^2) |
| SCLC | mobility (Mott-Gurney) | 1 | 1 | cm2/Vs | +0.000 | fit of J = 9/8 eps mu V^2 / L^3 |
| SCLC | background carrier density | 1e+13 | 1e+13 | cm-3 | -0.000 | ohmic region with the fitted mobility |
| Light intensity | ideality factor from Jsc-Voc | 1.5 | 1.5 | - | -0.000 | one-diode cell, 1-100 mW/cm2, Rs 3 Ohm cm2 |
| Light intensity | Jsc exponent alpha | 0.97 | 0.97 | - | -0.000 | one-diode cell, 1-100 mW/cm2, Rs 3 Ohm cm2 |
| Light intensity | Voc slope | 86.611 | 86.611 | mV/decade | -0.000 | n_id alpha kT/q ln 10 |
| TRPL | tau 1 | 5 | 4.94316 | ns | -1.137 | bi-exponential, 10^4 peak counts, Poisson noise, background 5 |
| TRPL | tau 2 | 80 | 79.4221 | ns | -0.722 | bi-exponential, 10^4 peak counts, Poisson noise, background 5 |
| TRPL | amplitude-weighted lifetime | 27.5 | 27.365 | ns | -0.491 | sum A_i tau_i / sum A_i |
| TRPL | intensity-weighted lifetime | 70.4545 | 70.0185 | ns | -0.619 | sum A_i tau_i^2 / sum A_i tau_i |
| TRPL | decay terms chosen by AICc | 2 | 2 | - | +0.000 | model = auto |
| TRPL | stretching exponent beta | 0.6 | 0.60287 | - | +0.478 | stretched exponential, tau 40 ns |
| Impedance | Rs | 10 | 10.0082 | Ohm | +0.082 | R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise |
| Impedance | R of the high-frequency arc | 200 | 200.025 | Ohm | +0.012 | R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise |
| Impedance | R of the low-frequency arc | 1500 | 1499.52 | Ohm | -0.032 | R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise |
| Impedance | CPE exponent, high-frequency arc | 0.95 | 0.949539 | - | -0.049 | R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise |
| Impedance | CPE exponent, low-frequency arc | 0.85 | 0.850861 | - | +0.101 | R(RQ)(RQ), 1 MHz - 0.1 Hz, 0.3 % noise |
| C-V | doping density (Mott-Schottky) | 1e+17 | 1e+17 | cm-3 | +0.000 | one-sided junction, 0.1 cm2, eps_r 25 |
| C-V | built-in potential | 0.9 | 0.9 | V | +0.000 | intercept + kT/q |
| Stability | T80 (measured crossing) | 800 | 794.475 | h | -0.691 | 12 % burn-in (tau 40 h) + 10 %/1000 h, 0.4 % noise |
| Stability | T80 (fitted model) | 800 | 793.031 | h | -0.871 | 12 % burn-in (tau 40 h) + 10 %/1000 h, 0.4 % noise |
| Stability | burn-in loss | 12 | 12.4455 | % of initial | +3.712 | back-extrapolated linear part |
| Stability | loss rate after burn-in | 10 | 10.3627 | %/1000 h | +3.627 | 12 % burn-in (tau 40 h) + 10 %/1000 h, 0.4 % noise |

_Generated 2026-11-12 with Physiscore 3.5.3, numpy 2.4.6, scipy 1.17.1._
