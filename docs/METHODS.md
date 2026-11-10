# Methods and algorithms

This document states, for every quantity Physiscore reports, the equation that is
evaluated, the numerical procedure, its defaults, and the primary reference. It is
written so that the methods section of a paper can cite it (or copy from it) and so
that a reviewer can check a number against the code. File references are to the
3.4.0 source tree; all functions are GUI-free and importable.

Conventions: J in mA cm⁻², V in V, R in Ω cm², E in eV, T = 298.15 K unless stated.
Constants: q = 1.602176634×10⁻¹⁹ C, k = 1.380649×10⁻²³ J K⁻¹, hc = 1239.84198 eV nm.

---

## 1. Illuminated J–V (`scripts/JV/jv_core.py`)

**Curve-derived parameters** — `compute_jv_parameters`. The sweep is sorted, repeated
voltages are averaged, and the sign is chosen so that the photocurrent is positive at
short circuit. J_sc = J(0) by linear interpolation; V_oc is the first positive-to-negative
zero crossing at V > 0 (linear interpolation between the bracketing points); the maximum
power point is searched on a 2000-point grid between 0 and V_oc; FF = P_max/(J_sc V_oc);
PCE = P_max/P_in with P_in = 100 mW cm⁻² (one sun, user-adjustable). R_s is |dV/dJ|
from a local straight line (window ±5 % of V_oc, at least 3 points) around V_oc and
R_sh the same quantity around V = 0 (slope method; Hegedus & Shafarman, Prog.
Photovolt. 12, 155 (2004)).

**One-diode equivalent circuit** — `single_diode_current`, `fit_single_diode`.

  J = J_ph − J₀ [exp((V + J R_s)/(n V_t)) − 1] − (V + J R_s)/R_sh,  V_t = kT/q

is evaluated explicitly with the Lambert W function (Jain & Kapoor, Sol. Energy Mater.
Sol. Cells 81, 269 (2004)); for arguments where exp overflows, W(e^z) is obtained by
Newton iteration on w + ln w = z. The five parameters are fitted by bounded
trust-region least squares (scipy `least_squares`, residuals scaled by J_sc) in
log₁₀ for J_ph, J₀, R_s and R_sh, starting from the curve-derived J_sc, V_oc, R_s and
R_sh and trying n₀ ∈ {1, 1.5, 2}; the lowest-cost solution is kept. Points up to
V_oc + 0.15 V are used. Reported: J_ph, J₀, n, R_s, R_sh, R², RMSE.

**Hysteresis** — `split_scan_directions`, `analyze_scan_hysteresis`. The file is read in
measurement order and split into monotonic segments; forward (J_sc → V_oc) and reverse
segments are analysed separately and HI = (PCE_rev − PCE_fwd)/PCE_rev × 100 % (Snaith
et al., J. Phys. Chem. Lett. 5, 1511 (2014)).

**Statistics** — per condition (cells sharing a name stem): mean, sample standard
deviation (N − 1) and best value over *all* devices, N; box charts of V_oc, J_sc, FF, PCE.

**J_sc mismatch** — `jsc_mismatch`: (J_sc,JV − J_sc,EQE)/J_sc,EQE × 100 %.

## 2. Dark J–V (`scripts/Dark_JV/dark_jv_core.py`)

**Sliding-window ideality** — `analyze_dark_diode`: ln J = ln J₀ + V/(n V_t). The 0.25 V
window (V ≥ 0.15 V, step 0.02 V) with the highest linear R² and a physical n ∈ [0.5, 10]
is chosen; it moves up the sweep until it clears a shunt-dominated region. R_sh,dark from
the ohmic slope for |V| ≤ 0.15 V.

**Full fit with series resistance** — `fit_dark_diode`: J = J₀[exp((V − J R_s)/(n V_t)) − 1]
+ (V − J R_s)/R_sh (the illuminated model with J_ph = 0, Lambert-W form), fitted in
log₁₀ J so every decade carries equal weight; returns J₀, n, R_s, R_sh and R² in log space.

**Cheung analysis** — `cheung_analysis`: dV/d(ln J) = R_s J + n V_t for J ≥ 5 % of the
maximum; slope → R_s, intercept → n (Cheung & Cheung, Appl. Phys. Lett. 49, 85 (1986)).

## 3. EQE (`scripts/EQE/eqe_core.py`)

**Reference spectrum** — ASTM G173-03 global tilt, 2002 points, 280–4000 nm (integral
1000.4 W m⁻²), bundled as `scripts/EQE/astm_g173_global.csv`.

**J_sc** — `calculate_jsc`: J_sc = q ∫ EQE(λ) Φ_AM1.5G(λ) dλ, Φ = E_λ λ/(hc), trapezoidal
on the union of the data and reference grids over their overlap. Percent and fraction
inputs are recognised automatically (max > 1.5 → percent).

**Band gap** — `bandgap_rau`: with P(E) = dEQE/dE on the low-energy side of the EQE
maximum, E_g = ∫E P dE / ∫P dE over the connected window where P ≥ ½ P_max; σ is the
standard deviation of P over that window (Rau, Blank, Müller & Kirchartz, Phys. Rev.
Applied 7, 044016 (2017)). `bandgap_inflection` returns the position of max P.

**Urbach energy** — `urbach_energy`: ln EQE = const + E/E_u in a window chosen
automatically where EQE lies between 1 % and 30 % of its maximum on the low-energy side
(`auto_urbach_window`); E_u = 1/slope (Urbach, Phys. Rev. 92, 1324 (1953)).

**Detailed balance** — `blackbody_photon_flux`, `radiative_limit`, `shockley_queisser`,
`voltage_losses`:

  Φ_BB(E) = 2πE²/(h³c²) / (exp(E/kT) − 1)
  J₀,rad = q ∫ EQE(E) Φ_BB(E) dE,  V_oc,rad = (kT/q) ln(J_sc/J₀,rad + 1)

Because Φ_BB falls exponentially, J₀,rad is dominated by the sub-gap tail; with
`extend_tail` (default) the fitted Urbach exponential is extrapolated 0.6 eV below the
measured range so a finite measurement window does not truncate the integral (Rau, Phys.
Rev. B 76, 085303 (2007); Rau et al. 2017). The Shockley–Queisser limit uses a step
absorber at the derived E_g: J_sc,SQ = q∫_{E_g}^∞ Φ_AM1.5G dE, J₀,SQ = q∫_{E_g}^∞ Φ_BB dE,
V_oc,SQ = (kT/q) ln(J_sc,SQ/J₀,SQ + 1), FF from Green's expression
FF = (v − ln(v + 0.72))/(v + 1), v = V_oc/V_t (Green, Solid-State Electron. 24, 788
(1981)), PCE_SQ = J_sc V_oc FF / 100 mW cm⁻² (33.7 % at 1.34 eV, 300 K; Rühle, Sol. Energy
130, 139 (2016)). The open-circuit deficit is split into ΔV₁ = E_g/q − V_oc,SQ,
ΔV₂ = V_oc,SQ − V_oc,rad and ΔV₃ = V_oc,rad − V_oc (non-radiative), with the implied
electroluminescence yield EQE_EL = exp(−qΔV₃/kT).

## 4. Absorbance (`scripts/Abs/abs_core.py`)

**Tauc plot** — `tauc_transform`: (X hν)^{1/r} vs hν with X = A or α = ln(10)·A/d, r = ½
(allowed direct), 2 (allowed indirect), 3/2 and 3 (forbidden) (Tauc, Grigorovici & Vancu,
Phys. Status Solidi 15, 627 (1966)). A and α differ by a constant, so E_g does not depend
on the choice.

**Automatic linear region** — `auto_linear_region`: local slope and local R² by moving
regression (window = max(7, 4 % of the points)); the steepest locally linear
(R² ≥ 0.8) point above the onset is the anchor (restricted to ±0.6 eV around an expected
gap when given); the region grows while the slope stays ≥ 60 % of the anchor slope and
is trimmed until the straight-line R² ≥ 0.98. E_g = −b/m with a standard error propagated
from the fit covariance (Makuła, Pacia & Macyk, J. Phys. Chem. Lett. 9, 6814 (2018)).

**Cross-checks** — `derivative_bandgap`: energy of max dA/dE (Savitzky–Golay smoothed);
`urbach_from_absorbance`: ln A vs E below the edge (baseline = minimum A subtracted).

## 5. XRD (`scripts/XRD/xrd_core.py`)

**Background and fitting** — `detect_peaks_and_fit`: asymmetric-least-squares background
over the whole pattern (λ = 10⁷, p = 0.01; Eilers & Boelens 2005); peaks by prominence
(5 % of the net range); reflections whose windows (3 FWHM, ≥ 0.25°) overlap are fitted
simultaneously with a sum of pseudo-Voigt profiles (height, centre, FWHM, η; Thompson,
Cox & Hastings, J. Appl. Cryst. 20, 79 (1987)); per cluster R².

**Scherrer** — `scherrer_size`: τ = Kλ/(β cos θ), K = 0.9, Cu Kα 1.5406 Å, β = (FWHM² −
FWHM_inst²)^{1/2} (Gaussian approximation; a linear correction is available) (Scherrer
1918; Langford & Wilson, J. Appl. Cryst. 11, 102 (1978)).

**Williamson–Hall** — `williamson_hall`: β cos θ = Kλ/D + 4ε sin θ (uniform deformation
model) with standard errors of D and ε from the fit covariance (Williamson & Hall, Acta
Metall. 1, 22 (1953)).

**Kα₂ stripping** — `strip_kalpha2`: Rachinger's method, I₂/I₁ = 0.5, λ₁ = 1.540562 Å,
λ₂ = 1.544390 Å; processed from low to high angle on the already-stripped pattern. A flat
background becomes B/(1 + r), as it should (Rachinger, J. Sci. Instrum. 25, 254 (1948)).

**Crystallinity index** — `crystallinity_index`: A_crystalline/A_total with the amorphous
contribution taken as the ALS background (area method, after Segal et al. 1959).

**Lattice parameter (cubic)** — `lattice_parameter_cubic`: a = d(h²+k²+l²)^{1/2}; mean ±
std and the Nelson–Riley extrapolation of a against ½(cos²θ/sin θ + cos²θ/θ) to θ = 90°
(Nelson & Riley, Proc. Phys. Soc. 57, 160 (1945)). `texture_coefficient`: Harris TC(hkl).

## 6. Photoluminescence (`scripts/PL/pl_core.py`, `scripts/common/spectral.py`)

**Processing** — Savitzky–Golay smoothing; ALS baseline with the asymmetry clamped to
(0, 0.5] (p = 0 would make the baseline the upper envelope).

**Energy axis** — `to_energy_axis`: I(E) = I(λ) λ²/(hc); the Jacobian is applied by
default so that the integrated intensity is conserved and broad bands are not shifted
(Mooney & Kambhampati, J. Phys. Chem. Lett. 4, 3316 (2013)).

**Fitting** — `fit_peak_gaussian` (single band) and `fit_multi_peak`. The single-band
window runs out to 10 % of the maximum and is cut earlier at the valley to a neighbouring
band; a valley counts only if it is deeper than 2 % of the peak height and than 6 noise
standard deviations, the noise being the median-absolute-deviation spread of the signal
around a copy smoothed over half the band width, taken where the signal exceeds 10 % of the
maximum (3.1.2; before, noise dips beside a weak band were taken as valleys and the FWHM came
out too small). `fit_multi_peak`: bounded least-squares sums of Gaussian,
Lorentzian, pseudo-Voigt or Voigt components, the number of components chosen by the
corrected Akaike criterion AICc = n ln(RSS/n) + 2k + 2k(k+1)/(n−k−1) (Akaike 1974;
Burnham & Anderson 2002). Voigt FWHM from the Olivero–Longbothum approximation.

**Quenching** — η = 1 − I_sample/I_reference from peak heights and from integrated areas.

## 7. Raman and FTIR (`scripts/common/vibrational.py`)

Baselines: arPLS (Baek, Park, Ahn & Choo, Analyst 140, 250 (2015); no asymmetry
parameter), ALS, end-point line, or minimum. Transmittance → absorbance A = −log₁₀ T.
Bands by prominence with a MAD-based noise floor; Lorentzian (Raman) or Gaussian (FTIR)
fits, overlapping bands together; peak-shift tables pair bands one-to-one within a
tolerance (8 cm⁻¹ default). The band library (`scripts/common/band_library.json`, 70
entries) lists typical literature positions with tolerances; its suggestions are
indicative and carry the distance to the library value.

## 8. SEM grain size (`scripts/SEM/sem_core.py`)

Grains are segmented by Otsu threshold → distance transform → marker watershed (seeded
automatically from an edge map or by a click); the equivalent circular diameter is
d = 2(A/π)^{1/2} after a two-point or scale-bar calibration. Statistics: mean, sample
standard deviation, median, D10/D50/D90, coefficient of variation, and the maximum-
likelihood log-normal parameters (μ, σ of ln d; geometric mean e^μ, geometric standard
deviation e^σ, mode e^{μ−σ²}); histogram bins by Freedman–Diaconis.

## 9. XPS (`spectra/core/xps.py`, `spectra/pipelines/run_xps.py`)

Shirley background (iterative, Shirley, Phys. Rev. B 5, 4709 (1972); Proctor &
Sherwood 1982) or AsLS; charge referencing by shifting C 1s to 284.8 eV (a convention,
see Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020)); singlet Voigt fits for
s levels and constrained spin–orbit doublets (fixed split, area ratio 1:2, 2:3, 3:4;
widths shared) for p, d, f levels (lmfit). In the auto-fit workspace, singlet candidates
closer than twice the fit window are fitted together as one cluster (3.1.2), and every
component's centre is bounded to its seed ± max(FWHM, 3 grid steps) and its width to three
times the seed FWHM, so that a small peak beside a large one keeps its own component;
atomic concentrations c_i = (A_i/S_i)/Σ(A_j/S_j)
with Scofield cross sections relative to C 1s (Scofield, J. Electron Spectrosc. 8, 129
(1976)) or user-supplied instrument factors.

## 10. Shared numerical details

- All fits are bounded least squares (scipy `curve_fit` / `least_squares`, trust-region
  reflective); parameter uncertainties are the square roots of the covariance diagonal.
- R² = 1 − RSS/TSS; AICc and BIC as above.
- Baselines: ALS and arPLS solve (W + λ D'D) z = W y with a sparse second-difference
  operator D; λ is the stiffness (10⁴ flexible … 10⁹ straight).
- Peak finding: scipy `find_peaks` with prominence = max(fraction of range, k × MAD noise).
- Figures (screen and export) follow OriginLab's default graph: white page, black 1.5 pt
  axis box, ticks in on all four sides (major 6 pt, minor 3 pt, one minor between majors),
  no grid, Arial, 1.5 pt lines, square black-framed legend, Origin's colour order
  (`palette.originize`); exports at 600 dpi raster or SVG/PDF vector.

## 11. Cross-technique device summary (`scripts/common/device_summary.py`)

For one device, the per-technique results are combined:

- **Jsc mismatch** = (J_sc,JV − J_sc,EQE)/J_sc,EQE × 100 %, with J_sc,EQE the AM1.5G
  integral of §3. A warning is raised above 5 % (adjustable): beyond that the usual causes
  are the solar simulator's spectral mismatch factor, the lamp calibration or the device
  area (Snaith, Energy Environ. Sci. 5, 9296 (2012); Zimmermann et al., Nat. Energy 1,
  16114 (2016)).
- **Band gap from three techniques**: the derivative-distribution gap of the EQE (§3, the
  reference value), the Tauc gap of the absorber film (§4) and the PL peak energy on the
  Jacobian-corrected energy axis (§6). The spread (max − min) is reported and a warning
  raised above 60 meV; the Stokes shift is E_g,EQE − E_PL.
- **Detailed balance at the reference gap**: SQ limits (§3) and the ratios J_sc/J_sc,SQ,
  FF/FF_SQ, PCE/PCE_SQ; the V_oc deficit E_g/q − V_oc = ΔV₁ + ΔV₂ + ΔV₃ with
  ΔV₁ = E_g/q − V_oc,SQ, ΔV₂ = V_oc,SQ − V_oc,rad (radiative loss from the non-step edge)
  and ΔV₃ = V_oc,rad − V_oc (non-radiative), and EQE_EL = exp(−qΔV₃/kT). A V_oc above
  V_oc,SQ is flagged as an inconsistent gap or temperature.
- The J-V sweep used can be the forward, the reverse or both directions (§1).

## 12. XRD reference matching (`scripts/XRD/xrd_core.py`)

`load_reference_peaks` reads a reference list (2θ or d, optional hkl and relative
intensity; d is converted with Bragg's law for Cu Kα). `match_reference` pairs each fitted
reflection with the nearest reference line within a tolerance (0.15° by default), one to
one and closest pairs first. Reported per pair: Δ2θ, d_obs, d_ref and the lattice strain
(d_obs − d_ref)/d_ref; overall: the coverage (matched reference lines with I_rel ≥ 5 %
divided by their number), the fraction of observed reflections that were assigned, the
mean shift and strain, and the unassigned reflections, which point to a second phase.

## 13. Generic I–V files and summaries from the curve (`scripts/common/iv_io.py`)

Voltage and current columns of CSV/TSV/DAT/Excel files are recognised by their headers
(current density in mA cm⁻², current in mA or A divided by the device area). Without a
recognisable header, column 1 is voltage and column 2 current density. The sign is
normalised to a negative photocurrent at short circuit. When an instrument file has no
summary block, its V_oc, J_sc, FF and PCE are taken from the curve (§1) and labelled
*curve* in the summary table.

## 14. Provenance (`scripts/common/provenance.py`)

Each Excel export writes `<name>.analysis.json`: program version, ISO time stamp with time
zone, Python version and platform, absolute input paths, all analysis parameters and the
main results (NaN written as null). Folder scans skip files that have such a side-car, so
an export is never analysed as data.

## 15. Validation

`docs/VALIDATION.md` tabulates each estimator against closed-form inputs; the same cases
are unit tests (`pytest`). Known limitations stated there: ALS cannot follow a strongly
curved background exactly (a few percent bias), a single-Gaussian PL fit is biased by an
unresolved neighbouring band (the multi-component fit removes most of it), and the
detailed-balance quantities inherit the uncertainty of the sub-gap tail extrapolation.

## 16. Rule-based interpretation (`scripts/common/interpret.py`)

Every window's **Interpretation** action (toolbar, or *Analysis → Interpretation*) turns
results that are already computed into findings. A finding has a level, a topic, a
sentence, the evidence (the numbers it was drawn from), the rule (threshold or formula),
a reference and a suggested next step. The rules are explicit code, so the same result
always gives the same text and nothing leaves the computer; the text never feeds back
into a number. It replaced the Gemini commentary of versions up to 3.3.

Levels: **problem** (limits the device or invalidates a number), **warning** (worth
acting on), **note** (context worth reporting), **good** (within the expected range).
The window lists the findings worst first, with Copy and Save Markdown. Thresholds are
the conventional ones of the cited literature; they are screening values, not
pass/fail criteria for every material system.

### 16.1 Illuminated J-V

| Topic | Rule | Reference |
|---|---|---|
| Fill-factor losses | FF₀ = (v_oc − ln(v_oc + 0.72))/(v_oc + 1), v_oc = Voc/(n kT/q); FF_s = FF₀(1 − 1.1 r_s) + r_s²/5.4; FF_sh = FF_s[1 − (v_oc + 0.7)/v_oc · FF_s/r_sh]; r_s = Rs Jsc/Voc, r_sh = Rsh Jsc/Voc. The FF gap to the ideal (n = 1, no resistance) splits into recombination, series and shunt parts; the largest part > 3 FF points is a warning | Green, Solid-State Electron. 24, 788 (1981); Green, *Solar Cells* (1982) |
| Ideality factor | n < 0.95 problem; 1-1.3 good; 1.3-1.8 note; 1.8-2.2 warning; > 2.2 problem | Tress et al., Energy Environ. Sci. 11, 151 (2018) |
| Series resistance | r_s > 0.05 warning, > 0.1 problem | Green (1982) |
| Shunt resistance | r_sh < 50 warning, < 10 problem | Green (1982) |
| Voc consistency | \|n kT/q ln(Jsc/J0 + 1) − Voc\| > 20 mV note | - |
| Diode model | fit R² < 0.995 warning; Rs(slope at Voc)/Rs(fit) > 3 warning (S-shape, extraction barrier) | Wagenpfahl et al., Phys. Rev. B 82, 115306 (2010) |
| Hysteresis | HI = (PCE_rev − PCE_fwd)/PCE_rev: \|HI\| > 5 % warning, > 15 % problem; HI < −5 % inverted (note) | Snaith et al., J. Phys. Chem. Lett. 5, 1511 (2014); Tress et al., Energy Environ. Sci. 8, 995 (2015) |

### 16.2 Batch statistics (J-V conditions)

| Topic | Rule | Reference |
|---|---|---|
| Reproducibility | CV = sd/mean of PCE > 10 % warning; fewer than 3 cells: note | - |
| Outliers | modified z-score \|0.6745 (x − median)/MAD\| > 3.5 | Iglewicz & Hoaglin, *How to Detect and Handle Outliers* (1993) |
| Condition vs reference | Welch's t-test on PCE, Voc, Jsc, FF; Holm correction over the four; Hedges' g as effect size; significant if adjusted p < 0.05 (good if better, warning if worse); a significant difference below 1 % of the reference value is a note (practically negligible) | Welch, Biometrika 34, 28 (1947); Holm, Scand. J. Stat. 6, 65 (1979); Hedges, J. Educ. Stat. 6, 107 (1981) |

### 16.3 Dark J-V

| Topic | Rule | Reference |
|---|---|---|
| Ideality (dark) | n ≤ 1.5 good, ≤ 2 note, > 2 warning; \|n(local) − n(full fit)\| > 0.3 note | Sze & Ng, *Physics of Semiconductor Devices* (2007) |
| Leakage | Rsh,dark < 10³ Ω cm² problem, < 10⁴ warning | - |
| Series resistance | Rs > 5 Ω cm² warning | - |
| Fit quality | R² < 0.99 warning | - |

### 16.4 EQE and voltage losses

| Topic | Rule | Reference |
|---|---|---|
| Urbach energy | Eu ≤ 18 meV good, ≤ 25 note, > 25 warning | De Wolf et al., J. Phys. Chem. Lett. 5, 1035 (2014) |
| Current vs limit | Jsc(EQE)/Jsc,SQ ≥ 85 % good, < 75 % warning | Rühle, Sol. Energy 130, 139 (2016) |
| Spectral losses | lost current ∫ q Φ_AM1.5G (1 − EQE) dλ split into < 450 nm, the middle, and the 50 nm below the edge; the largest region is named with its usual cause | ASTM G173-03 |
| Peak EQE | max EQE < 80 % warning | - |
| Radiative loss | ΔV₂ = Voc,SQ − Voc,rad > 50 mV note | Rau et al., Phys. Rev. Applied 7, 044016 (2017) |
| Non-radiative loss | EQE_EL = exp(−ΔV₃ q/kT): ≥ 10⁻² good, ≥ 10⁻⁴ note, < 10⁻⁴ warning | Rau, Phys. Rev. B 76, 085303 (2007) |
| Band-gap spread | σ(Eg) > 40 meV note | Rau et al. (2017) |

### 16.5 Absorbance (Tauc)

| Topic | Rule | Reference |
|---|---|---|
| Band gap | x-intercept of the straight Tauc region (note, with its error and range) | Tauc, Grigorovici & Vancu, Phys. Status Solidi 15, 627 (1966) |
| Linearity | R² of the linear region < 0.99 warning; region narrower than 0.05 eV warning | Makuła, Pacia & Macyk, J. Phys. Chem. Lett. 9, 6814 (2018) |
| Edge position | Tauc gap and the steepest point of the edge differ by > 40 meV: note (tail or excitonic feature) | Makuła et al. (2018) |
| Transition type | the other transition (direct/indirect) fits better by ΔR² > 0.005: warning | - |
| Tail | Eu > 25 meV note | De Wolf et al. (2014) |

### 16.6 Photoluminescence

| Topic | Rule | Reference |
|---|---|---|
| Line width | FWHM > 100 meV note, > 130 meV warning (also given in units of kT) | - |
| Second emission | AICc prefers more than one band: note | Akaike, IEEE Trans. Autom. Control 19, 716 (1974) |
| Quenching | η = 1 − A/A_ref: ≥ 90 % good, 50-90 % note, < −20 % enhancement (good, passivation) | - |
| Peak shift | \|E − E_ref\| > 10 meV note | - |
| Stokes shift | Eg − E_PL > 60 meV warning | - |

### 16.7 XRD

| Topic | Rule | Reference |
|---|---|---|
| Crystallite size | Scherrer τ = Kλ/(β cos θ); without the instrument width the sizes are lower bounds; > 150 nm beyond resolution (note) | Langford & Wilson, J. Appl. Cryst. 11, 102 (1978) |
| Williamson-Hall | β cos θ = Kλ/D + 4ε sin θ; ε < 0 warning (unphysical), ε > 0.1 % note; D(W-H) and median τ differ by > 2× note | Williamson & Hall, Acta Metall. 1, 22 (1953) |
| Phase identification | reference-line coverage ≥ 80 % good, < 50 % warning; mean shift \|Δ2θ\| > 0.05° note | - |
| Unassigned / known lines | unassigned reflections are compared with a list of common secondary phases and substrates (PbI₂ 12.7°, δ-FAPbI₃ 11.8°, FTO, ITO, Si, Au, Ag, TiO₂, ZnO; Cu Kα) | - |
| Texture | Harris coefficient TC(hkl) = (I/I₀)/⟨I/I₀⟩ > 1.5 note | Harris, Philos. Mag. 43, 113 (1952) |
| Crystallinity | index < 50 % note | - |

### 16.8 FE-SEM grain size

| Topic | Rule | Reference |
|---|---|---|
| Sample size | N < 50 note | - |
| Width | CV < 0.3 narrow (good), > 0.5 broad (warning); geometric SD reported | - |
| Bimodality | bimodality coefficient BC = (g² + 1)/(κ + 3(n−1)²/((n−2)(n−3))), g skewness, κ excess kurtosis, n ≥ 20; BC > 0.555 (the value of a uniform distribution) warning | Pfister et al., Front. Psychol. 4, 700 (2013) |
| Log-normal shape | Kolmogorov-Smirnov test on ln d, p < 0.05 note | - |
| Small grains | fraction below half the median > 20 % note | - |

### 16.9 Raman and FTIR

Bands are assigned from the built-in library (nearest entries with a confidence and the
other candidates); FTIR bands are also grouped by functional-group window (O-H
3200-3600, N-H 3050-3200, C-H 2840-2960, C=O 1690-1760, C=N/N-H 1600-1720, C-O/C-N
1000-1150 cm⁻¹). Against the reference layer: \|shift\| > 3 cm⁻¹ note (direction read as
strain or bonding), width change > 20 % note (disorder or crystallite size). *Compare*
on two selected bands gives the shift and width change; on two band lists (FTIR) the
matched, new and missing bands within an 8 cm⁻¹ tolerance.

### 16.10 XPS

| Topic | Rule | Reference |
|---|---|---|
| Broad component | FWHM > 2.5 eV warning (merged chemical states) | - |
| Metallic lead | a Pb 4f component 1.3-2.2 eV below the main Pb²⁺ 4f₇/₂ (137.8-139.3 eV): warning, with its area fraction | Sadoughi et al., ACS Appl. Mater. Interfaces 7, 13440 (2015) |
| Spin-orbit doublet | Pb 4f₅/₂ : 4f₇/₂ area ratio within 0.75 ± 0.1 good; split expected 4.87 eV | Moulder et al., *Handbook of XPS* (1992) |
| Stoichiometry | I/Pb 2.7-3.3 good, otherwise warning | - |
| Surface carbon | C > 40 at.% note | Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020) |
| Charge reference | main C 1s component \|E − 284.8\| > 0.3 eV note, with the shift to enter | Greczynski & Hultman (2020) |
| O 1s | area fraction at 530.8-532.3 eV is reported as hydroxyl/carbonate/adsorbed species, not as oxygen vacancies | Idriss, Surf. Sci. 712, 121894 (2021) |

### 16.11 Auto-fit peak tables (XRD, PL, XPS workspaces)

`interpret_peak_fit` reads the fitted table of `spectra/pipelines`:

| Topic | Rule | Reference |
|---|---|---|
| Detection limit | S/N = height/σ_noise < 3 warning | Currie, Anal. Chem. 40, 586 (1968) |
| Quantification limit | 3 ≤ S/N < 10 note | Currie (1968) |
| Unresolved peaks | neighbours with Δx < (w₁ + w₂)/2 note (correlated areas and widths) | - |
| Fit residual | χ²_ν/σ²_noise > 4 in a fit region warning (missing component or wrong line shape) | Bevington & Robinson, *Data Reduction and Error Analysis* (2003) |

then the technique rules: XRD Scherrer sizes (K = 0.9, Cu Kα₁ 0.15406 nm), a
Williamson-Hall fit when three or more reflections exist, and the known-line list; PL
in eV (nm converted with E = hc/λ, FWHM_E = hc Δλ/λ²) with the line-width and
second-band rules; XPS with the rules of 16.10.

### 16.12 Device summary

J-V and EQE currents: \|mismatch\| ≤ 5 % good, > 10 % problem (Snaith, Energy Environ.
Sci. 5, 9296 (2012)); EQE, Tauc and PL gaps agree within 30 meV good, > 60 meV warning
(Rau et al. 2017); Voc, Jsc and FF as fractions of the detailed-balance limit; the
voltage loss split into radiative and non-radiative parts, non-radiative > 150 mV
warning.
