# Methods and algorithms

This document states, for every quantity Physiscore reports, the equation that is
evaluated, the numerical procedure, its defaults, and the primary reference. It is
written so that the methods section of a paper can cite it (or copy from it) and so
that a reviewer can check a number against the code. File references are to the
3.5.3 source tree; all functions are GUI-free and importable.

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
Limits found on synthetic edges (3.5.3): a constant sub-gap absorbance A₀ (reflection,
scattering, substrate) bends the transformed edge, (A + A₀)²hν² containing a term
∝ A₀√(hν − E_g), so the direct gap comes out 10 meV low at A₀ = 0.02 and 23 meV at 0.05
(indirect: 87 and 177 meV), the same for Urbach energies of 15 to 50 meV. `subgap_offset`
estimates A₀ as the median absorbance of the lowest-energy 5 % of the spectrum (at least 5
points, valid only if they end ≥ 0.15 eV below the derivative band gap); subtracting it
before the transform (*Sub-gap offset: Subtract*, `analyze_absorbance(subtract_offset=True)`;
default Keep) returns both gaps within 1 meV (VALIDATION). With interference fringes the
median lands on a fringe and the correction does not help. A background that rises towards short wavelengths
(0.05·(500 nm/λ)⁴) or interference fringes can move the steepest point, and so the
region, above the edge (+0.4 to +0.8 eV for a direct edge); the edge-position rule (§16)
then warns. Give the expected gap or set the range by hand in such cases.

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

**Auto-fit workspace** (`spectra/pipelines/run_xrd.py`): Savitzky–Golay smoothing
(31 points, cubic) and an AsLS baseline (λ = 10⁶, p = 0.01) on the smoothed curve; peak
candidates are found on the smoothed curve minus the baseline, and each line is fitted to
the unsmoothed counts minus the baseline (3.5.3). One Voigt per candidate with both widths
free and the seed and bounds of §9, in a window of ±3.5° that stops at the midpoint to any
neighbouring candidate of at least 10 % of its height (never closer than 3 seed FWHM;
3.5.2 — with the full window a neighbouring line had no component and lowered the areas,
−18 and −35 % for two lines 3.5° apart on noise-free data). A component that ends nearer
another candidate than its own seed has moved onto that candidate's line and is dropped
(weak candidates on the flank of a strong line otherwise repeat its row). Up to 3.5.2 the
lines were fitted to the smoothed curve, and the 31-point filter (0.62° on a 0.02° grid)
widened them: on a synthetic pattern of five Voigt lines on a broad hump with Poisson
noise, FWHM +2 to +29 %, and +174 % for a 0.11° line. Fitted to the unsmoothed data the
same lines come out within 3 % (VALIDATION, rows "XRD auto-fit"). The areas stay 5 to
10 % low: the AsLS baseline follows part of the Lorentzian tails (with the true
background subtracted the areas are within 1 %, and a stiffer baseline, λ = 10⁸–10⁹, helps
lines on a flat background but raises the area of a line on an amorphous hump by up to
13 %). Compare areas only between patterns processed with the same baseline settings.

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
out too small). The band is a Gaussian plus a constant (3.5.3): without the constant, an
offset left by the default "Raw" processing widened the band, by 7.6 % for an offset of 5 %
of the peak. `fit_multi_peak`: bounded least-squares sums of Gaussian,
Lorentzian, pseudo-Voigt or Voigt components, the number of components chosen by the
corrected Akaike criterion AICc = n ln(RSS/n) + 2k + 2k(k+1)/(n−k−1) (Akaike 1974;
Burnham & Anderson 2002). Voigt FWHM from the Olivero–Longbothum approximation.

**Quenching** — η = 1 − I_sample/I_reference from peak heights and from integrated areas.

## 7. Raman and FTIR (`scripts/common/vibrational.py`)

Baselines: arPLS (Baek, Park, Ahn & Choo, Analyst 140, 250 (2015); no asymmetry
parameter), ALS, end-point line, or minimum. Transmittance → absorbance A = −log₁₀ T.
Bands by prominence with a MAD-based noise floor; Lorentzian (Raman) or Gaussian (FTIR)
fits, overlapping bands together; peak-shift tables pair bands one-to-one within a
tolerance (8 cm⁻¹ default). The band library (`scripts/common/band_library.json`, 74
entries) lists typical literature positions with tolerances; its suggestions are
indicative and carry the distance to the library value.

## 8. SEM grain size (`scripts/SEM/sem_core.py`)

Grains are segmented by Otsu threshold → distance transform → marker watershed (seeded
automatically from an edge map or by a click); the equivalent circular diameter is
d = 2(A/π)^{1/2} after a two-point or scale-bar calibration. Statistics: mean, sample
standard deviation, median, D10/D50/D90, coefficient of variation, and the log-normal
parameters μ = mean of ln d (the maximum-likelihood value) and σ = sample standard
deviation of ln d (divisor N − 1, i.e. the maximum-likelihood σ times (N/(N−1))^{1/2};
0.1 % larger at N = 400); geometric mean e^μ, geometric standard deviation e^σ, mode
e^{μ−σ²}; histogram bins by Freedman–Diaconis.

## 9. XPS (`spectra/core/xps.py`, `spectra/pipelines/run_xps.py`)

Shirley background (iterative, Shirley, Phys. Rev. B 5, 4709 (1972); Proctor &
Sherwood 1982) or AsLS; charge referencing by shifting C 1s to 284.8 eV (a convention,
see Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020)); singlet Voigt fits for
s levels and constrained spin–orbit doublets (fixed split, area ratio 1:2, 2:3, 3:4;
widths shared) for p, d, f levels (lmfit). In the auto-fit workspace the lines are fitted
to the unsmoothed counts minus the background; the smoothed curve (7 points) only finds
the candidates (3.5.3; up to 3.5.2 the fit used the smoothed curve, which on a 0.2 eV scan
widened Pb 4f7/2 by 7.5 % and lowered its area by 5 %). Singlet candidates
closer than twice the fit window are fitted together as one cluster (3.1.2). In doublet
mode a candidate that lies one split above a kept candidate (within half its FWHM, at least
3 grid steps) and is no taller than twice the height the area ratio predicts (never less
than the first line's height) is that line's partner and is dropped, and doublets whose
windows (first line − fit window to partner + fit window) overlap are fitted together
(3.5.3; up to 3.5.2 every candidate was fitted as the first line of its own doublet, so a
Pb 4f spectrum with a metallic shoulder came back as four doublets). Every
component's centre is bounded to its seed ± max(FWHM, 3 grid steps) and its Gaussian and
Lorentzian FWHM each to three times the seed FWHM, so that a small peak beside a large one
keeps its own component. Every auto-fit Voigt (singlet, doublet, XRD) has both widths free,
σ and γ (3.5.2), and starts with equal Gaussian and Lorentzian FWHM, f_G = f_L =
FWHM_seed/1.6376, so that its Olivero–Longbothum FWHM equals the seed FWHM; its Gaussian
FWHM is at least min(2 grid steps, FWHM_seed/2), because a line sampled by fewer points is
not resolved and, fitted to unsmoothed data, a noise candidate's component otherwise
collapses onto one point (3.5.3). Up to 3.5.1 γ
was never fitted (lmfit's `Parameter.set(value=…)` removes the default constraint γ = σ
but leaves γ fixed), so every line was a Lorentzian of the seed width and the areas were
high by 3 % (Lorentzian-dominated lines) to 36 % (Gaussian-dominated lines); see
VALIDATION, rows "XPS auto-fit". Starting both widths at the seed FWHM (as up to 3.5.1)
makes the profile 1.64 times too wide, which once γ is free can end in a local minimum with
σ = 0 (area +28 % on a synthetic cluster, χ² 8.6 times the minimum);
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

## 16. Rule-based interpretation (`scripts/common/interpret.py`, `interpret_transport.py`)

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
| Edge position | Tauc gap > 40 meV below the steepest point of the edge: note (sub-gap offset, tail or excitonic feature); > 40 meV above it: warning (region on a rising background or a higher transition) | Makuła et al. (2018) |
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

`interpret_peak_fit` reads the fitted table of `spectra/pipelines`. σ_noise is the
noise of the data the lines were fitted to (unsmoothed minus background), estimated as
1.4826 MAD of the first differences divided by √2 (3.5.3; up to 3.5.2 it was taken from
the smoothed curve, 18 times below the counting noise on a synthetic XRD pattern, so S/N
was overstated and noise candidates passed the limits below):

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

### 16.13 SCLC (`scripts/common/interpret_transport.py`)

The six transport and recombination tools have their rules in `interpret_transport.py`
(`interpret_sclc`, `interpret_intensity`, `interpret_trpl`, `interpret_eis`,
`interpret_cv`, `interpret_stability`). Each analysis also returns its own validity
checks (sections 17-22); the interpretation repeats those it has no rule of its own for
as warnings under the topic **Check**.

| Topic | Rule | Reference |
|---|---|---|
| Mott-Gurney region | no region with local slope 1.65-2.45: problem (no mobility); \|slope − 2\| ≤ 0.25 good, otherwise warning | Röhr et al., J. Phys.: Condens. Matter 30, 105901 (2018) |
| Trap density | n_t/n_diff < 1 problem; < 3 warning; otherwise good. Without a trap-filling rise: note | Le Corre et al., ACS Energy Lett. 6, 1087 (2021) |
| Sweep hysteresis | mean \|log₁₀(J_up/J_down)\| > 0.1 decades warning (mobile ions; pulsed SCLC advised); one sweep only: note | Duijnstee et al., ACS Energy Lett. 5, 376 (2020) |
| Ohmic region | conductivity and n₀ = σ/(qμ) reported as a note | Röhr et al. (2018) |

### 16.14 Light-intensity dependence

| Topic | Rule | Reference |
|---|---|---|
| Ideality factor | 0.9-1.2 note (free-carrier recombination, or a surface where one carrier is in excess); 1.2-1.8 note (trap-assisted with unequal carrier densities; in perovskite cells usually the interfaces); 1.8-2.2 warning (Shockley-Read-Hall through deep states, bulk dominated); outside 0.9-2.2 problem | Tress et al., Energy Environ. Sci. 11, 151 (2018); Caprioglio et al., Adv. Energy Mater. 10, 2000502 (2020) |
| Ideality factor uncertainty | 95 % interval wider than ±0.15: warning | - |
| Jsc exponent | α ≥ 0.97 good; 0.9-0.97 note; < 0.9 warning (bimolecular recombination or space-charge build-up at short circuit; 0.75 is the space-charge limit) | Koster et al., Appl. Phys. Lett. 87, 203502 (2005); Mihailetchi et al., Phys. Rev. Lett. 94, 126602 (2005) |
| Transport loss in FF | pFF − FF ≤ 3 % (absolute) good; ≤ 6 % note; above warning | Sinton, Cuevas, Proc. 16th EU PVSEC, 1152 (2000) |
| Pseudo fill factor | reported as a note when no measured FF is given | Sinton, Cuevas (2000) |

### 16.15 TRPL

| Topic | Rule | Reference |
|---|---|---|
| Fit quality | counting data with 0.7 ≤ χ²_red ≤ 1.3 and Durbin-Watson ≥ 1.5: good | Lakowicz, *Principles of Fluorescence Spectroscopy*, 3rd ed. (2006), ch. 4 |
| Decay law | mono-exponential, stretched (β and mean lifetime) or n exponentials: note. For two or three exponentials the note states that the lifetimes are a parametrisation unless a fluence series supports separate channels | Kirchartz et al., Adv. Energy Mater. 10, 1904134 (2020) |
| Average lifetime | ⟨τ⟩_amp and ⟨τ⟩_int given together with what each one means: note | Lakowicz (2006) |
| Differential lifetime | median of the last third > 2 × median of the first third: note (rate falls with carrier density); otherwise good (one rate over the window). Needs 9 or more points | Krückemeier et al., Adv. Energy Mater. 11, 2003489 (2021) |
| Diffusion length | L_D from the entered mobility: note (an estimate) | Kirchartz et al. (2020) |

### 16.16 Impedance

| Topic | Rule | Reference |
|---|---|---|
| Kramers-Kronig test | residual rms ≤ 0.5 % of \|Z\| good; 0.5-1 % note; rms > 1 % or max > 2 % problem (not a linear, stationary response; circuit parameters have no meaning) | Schönleber et al., Electrochim. Acta 131, 20 (2014) |
| Circuit fit | rms residual ≤ 1 % of \|Z\|: good | Guerrero et al., Chem. Rev. 121, 14430 (2021) |
| Assignment of the arcs | two arcs: high-frequency arc = geometric capacitance with recombination and transport resistance, low-frequency arc = ionic and interfacial polarisation (note) | Guerrero et al. (2021) |
| Arc ideality | CPE exponent α ≥ 0.9: good (C_eff well defined) | Hsu, Mansfeld, Corrosion 57, 747 (2001) |
| Permittivity | ε_r from the fastest arc when area and thickness are entered: note | von Hauff, Klotz, J. Mater. Chem. C 10, 742 (2022) |

### 16.17 C-V (Mott-Schottky)

| Topic | Rule | Reference |
|---|---|---|
| Mott-Schottky region | no straight section of 1/C² with negative slope: problem, nothing further is reported | Almora et al., Appl. Phys. Lett. 109, 173903 (2016) |
| Doping density against the resolution limit | N/N_min < 1 problem (geometric capacitance plus injected charge, not doping); < 3 warning; otherwise good. Needs the thickness | Ravishankar et al., Science 371, eabd8014 (2021) |
| Built-in potential | 0.3 V ≤ V_bi ≤ 1.6 V: note, with the remark that in a fully depleted cell the intercept is not V_bi | Kirchartz et al., J. Phys. Chem. C 116, 7672 (2012) |
| Depletion width | W in the fitted window ≤ 0.9 d: good | Kirchartz et al. (2012) |
| Doping profile | N(W) varies by more than a factor 3 inside the window: note (U shape of a fully depleted layer) | Kirchartz et al. (2012) |

### 16.18 Stability

| Topic | Rule | Reference |
|---|---|---|
| T80 (or the chosen level) | reached within the measurement: good. Not reached: extrapolated value up to 2 × the measured time warning (an estimate), beyond that problem (a property of the model; report T > measured time). No crossing within 1000 × the measured time: note | Khenkin et al., Nat. Energy 5, 35 (2020) |
| Burn-in | burn-in model selected: note with the loss, the stabilised point t_s and Ts80 | Roesch et al., Adv. Energy Mater. 5, 1501407 (2015) |
| Loss rate | %/1000 h with its standard error: note | Roesch et al. (2015) |

## 17. Space-charge-limited current (`scripts/SCLC/sclc_core.py`)

For a single-carrier device (electron-only or hole-only) of thickness L and relative
permittivity ε_r. `read_curve` reads the whole voltage and current block (the solar-cell
reader of section 1 cuts at ±3 V) and divides by the device area; `split_sweeps` cuts
the trace at the turning points of |V| so that the up sweep, the down sweep or all
points can be analysed. The branch (positive, negative, or the one with more points)
and an optional built-in voltage offset V − V_bi are applied before the analysis. At
least 8 points with V > 0 and J > 0 are needed.

**Regimes** — `find_regimes`: the local slope m = d log J / d log V comes from a moving
straight-line fit over 5 points (`window`). A run of 3 or more points is ohmic for
0.7 ≤ m ≤ 1.35, a Child (Mott-Gurney) region for 1.65 ≤ m ≤ 2.45, and a trap-filling
rise for m ≥ max(2.6, 0.6 m_max) around the steepest point. Each regime is fitted with
a line in log-log space.

**Characteristic voltages** — V₁: crossing of the ohmic and trap-filling tangents;
V₂: crossing of the trap-filling and Child tangents; V_inf: voltage of the steepest
slope. V_TFL = V₂ when a Child region follows the rise, otherwise V₁ (Le Corre et al.
(2021) show that V₂ follows the trap density more closely than V₁ in perovskites).

**Trap density** — `trap_density_cm3`: n_t = 2 ε₀ ε_r V_TFL/(q L²) (Lampert 1956).
`resolution_limit_cm3`: n_diff = 4π² kT ε₀ ε_r/(q² L²), the density below which the
rise comes from diffusion of injected carriers and not from traps (Le Corre et al.
2021); for 500 nm, ε_r = 25 and 300 K it is 5.6×10¹⁵ cm⁻³. Both n_t(V_TFL) and n_t(V₁)
are reported.

**Mobility** — `mott_gurney_mobility`: J = (9/8) ε₀ ε_r μ V²/L³ fitted to the Child
region with the slope fixed at 2; the standard error follows from the scatter of
log J − 2 log V. With `field_dependent` the Murgatroyd form
J = (9/8) ε μ₀ exp(0.891 γ √(V/L)) V²/L³ is fitted as well (`murgatroyd`) and μ₀ and γ
are reported.

**Ohmic region** — σ = J L/V with the slope fixed at 1; n₀ = σ/(q μ) when a mobility
exists. Without a trap-filling rise the ohmic/Child crossover voltage is given instead.

**Hysteresis** — `hysteresis_decades`: mean |log₁₀(J_up/J_down)| over the common voltage
range of the first two sweeps.

**Validity checks** (`checks`): no Child region (no mobility); Child slope off 2 by more
than 0.25; no trap-filling rise; n_t below n_diff; hysteresis above 0.1 decades; less
than 1.5 decades of voltage; no ohmic region.

References: Mott & Gurney, *Electronic Processes in Ionic Crystals* (1940); Lampert,
Phys. Rev. 103, 1648 (1956); Murgatroyd, J. Phys. D 3, 151 (1970); Röhr et al., J.
Phys.: Condens. Matter 30, 105901 (2018); Le Corre et al., ACS Energy Lett. 6, 1087
(2021); Duijnstee et al., ACS Energy Lett. 5, 376 (2020).

## 18. Light-intensity dependence (`scripts/Intensity/intensity_core.py`)

Input is a table of intensity, Voc and optionally Jsc, FF and PCE, or a set of J-V files
measured at different intensities (`from_jv_files`: each file is analysed with the J-V
core of section 1; the intensity comes from the entered list or from the file name -
`0.1sun`, `53mW`, `10pct`, `OD1.0`/`ND2` → 10^−OD suns). Three points are needed for the
fits, four for the pseudo J-V curve. A fit window `i_min`-`i_max` restricts the fits;
points outside it are drawn but not used.

**Ideality factor** — `fit_voc`: Voc = (n_id kT/q) ln I + const, so n_id = slope/(kT/q)
from the least-squares line of Voc against ln I. The standard error and the 95 %
interval (Student t with N − 2 degrees of freedom) are reported together with the slope
in mV per decade. The same factor is also obtained from Voc against ln Jsc, which does
not depend on the intensity calibration. `local_ideality` gives n_id between
neighbouring intensities from centred differences.

**Jsc exponent** — `fit_jsc`: Jsc ∝ I^α from the line of log Jsc against log I, with the
95 % interval of α.

**Suns-Voc pseudo J-V** — `pseudo_jv`: each intensity gives one point of the curve the
cell would have without series resistance, J(Voc,i) = Jsc(I_max) − Jsc(I_i), with the
short-circuit point (0, Jsc(I_max)) added. The pseudo fill factor is
pFF = max(V J)/(Jsc(I_max) Voc(I_max)) on a 400-point interpolation; `covers_mpp` is
false when the lowest intensity lies above the pseudo maximum-power point.

**Fill-factor budget** — `ff0_green`: FF₀ = (v − ln(v + 0.72))/(v + 1), v = Voc/(n_id
kT/q) (Green 1981); transport loss = 100 pFF − FF at the highest intensity, in absolute
per cent. FF values given as fractions are converted to per cent.

**Validity checks**: fewer than 5 intensities; less than one decade of intensity; R² of
the Voc line below 0.99; n_id < 0.9 or > 2.2; n_id from Voc(I) and from Voc(Jsc)
differing by more than 0.1 (intensity calibration); α > 1.03; pseudo maximum-power point
not covered.

References: Koster et al., Appl. Phys. Lett. 86, 123509 (2005); Koster et al., Appl.
Phys. Lett. 87, 203502 (2005); Mihailetchi et al., Phys. Rev. Lett. 94, 126602 (2005);
Sinton & Cuevas, Proc. 16th EU PVSEC, 1152 (2000); Tress et al., Energy Environ. Sci.
11, 151 (2018); Caprioglio et al., Adv. Energy Mater. 10, 2000502 (2020); Green,
Solid-State Electron. 24, 788 (1981).

## 19. Time-resolved photoluminescence (`scripts/TRPL/trpl_core.py`)

A tail fit: the decay is fitted from its maximum (plus an optional `skip`) to `t_end`,
without deconvolution of the instrument response. Lifetimes shorter than the response
are therefore not resolved, and a check says so when the response width is entered. At
least 12 points, 10 of them inside the window.

**Background** — `prepare`: `auto` takes the median of the points before the pulse (5 or
more points ahead of the rise), otherwise the median of a flat tail below 5 % of the
peak; a number or `none` can be entered instead. The source is recorded in the result.

**Models** — `exp1`, `exp2`, `exp3`: Σ A_i exp(−t/τ_i); `stretched`:
A exp(−(t/τ)^β), 0.2 ≤ β ≤ 1. Parameters are fitted in log space from several starting
points (`fit_model`). Photon-counting data (integers with a maximum of 50 or more) are
weighted with σ = √N, which makes χ² absolute; other data use the same weight shape with
the errors scaled by the residuals.

**Model selection** — `choose_model`: the lowest AICc among the valid exponential models,
the simpler one being kept when it is within 2 AICc units. A model is not valid when two
lifetimes are closer than a factor 1.5, when a component carries less than 1 % of the
amplitude, or when the relative error of a lifetime exceeds 100 %. The stretched form is
fitted for comparison and used when requested.

**Lifetimes** — ⟨τ⟩_amp = Σ A_i τ_i/Σ A_i (proportional to the time-integrated emission);
⟨τ⟩_int = Σ A_i τ_i²/Σ A_i τ_i (mean emission time); for the stretched form
⟨τ⟩ = (τ/β) Γ(1/β). Standard errors are propagated numerically from the covariance
matrix. `tau_1e` is the model-free time at which the signal has fallen to 1/e of the
peak.

**Differential lifetime** — `differential_lifetime`: τ_diff(t) = −(d ln I/dt)⁻¹ from a
Savitzky-Golay derivative of ln I; points within 3 times the noise floor are left out.
It shows whether the rate changes during the decay without assuming a model
(Krückemeier et al. 2021).

**Diffusion length** — `diffusion_length_um`: L_D = √(D τ), D = μ kT/q, with the entered
mobility and ⟨τ⟩_amp.

**Fit diagnostics and checks**: reduced χ² (outside 0.7-1.3 flagged for counting data),
Durbin-Watson statistic of the weighted residuals (< 1.5 flagged), shortest lifetime
below 3 time bins or below the response FWHM, longest lifetime above half the fit
window, dynamic range below 1.5 decades, stretched form better than exp2/exp3 by more
than 10 AICc units, background taken from a flat tail, requested model not supported.

References: Lakowicz, *Principles of Fluorescence Spectroscopy*, 3rd ed. (2006), ch. 4;
Burnham & Anderson, *Model Selection and Multimodel Inference* (2002); Kirchartz,
Márquez, Stolterfoht & Unold, Adv. Energy Mater. 10, 1904134 (2020); Krückemeier et
al., Adv. Energy Mater. 11, 2003489 (2021); Peán et al., ACS Energy Lett. 5, 3244
(2020).

## 20. Impedance spectroscopy (`scripts/EIS/eis_core.py`)

Capacitive Z″ is negative; a file that stores −Z″ is recognised (most values positive)
and converted (`prepare`, `convention`). A frequency window `f_min`-`f_max` can be set.

**Kramers-Kronig test** — `lin_kk`: the spectrum is fitted with a series resistance, an
inductance and a chain of M RC elements whose time constants are fixed and equally
spaced in log τ over the measured range. The problem is linear, so it has one solution
and needs no starting values. Residuals are weighted with 1/|Z|. M runs from 3 up to
max(4, min(N − 3, ⌈4 × decades of frequency⌉)); the M used is the smallest whose rms residual is
within 10 % of the lowest one reached. Reported: rms and maximum residual in % of |Z|,
the rms of the lowest decade, M, and Schönleber's μ = 1 − Σ|R_k<0|/Σ|R_k>0| (μ < 0.85
marks an over-fitted chain). A spectrum that the chain cannot reproduce is not a
linear, causal, time-invariant response (Boukamp 1995).

**Equivalent circuits** — `fit_model`: R(RC), R(RQ), R(RC)(RC), R(RQ)(RQ) with
Z_CPE = 1/(Q (jω)^α). Complex non-linear least squares on real and imaginary parts
together, each residual divided by |Z| so that every decade counts equally; parameters
in log₁₀ space, 0.4 ≤ α ≤ 1, several starting points, standard errors from the Jacobian
at the optimum.

**Circuit selection** — `choose_model`: AICc with 2N data, the simpler circuit kept
within 2 units. A circuit is not valid when a resistance has more than 100 % error, the
two time constants are closer than a factor 3, an arc carries less than 1 % of the
total resistance, or α sits on its lower bound.

**Per arc** — τ = (R Q)^(1/α), f_peak = 1/(2π τ), effective capacitance
C_eff = Q^(1/α) R^((1−α)/α) (Hsu & Mansfeld 2001). Arcs are ordered by time constant.
With area and thickness, ε_r = C_eff d/(ε₀ A) for the fastest arc. The capacitance
spectrum C(f) = Im(1/Z)/ω is plotted (`capacitance_spectrum`).

**Validity checks**: Kramers-Kronig residual above 2 % (maximum) or 1 % (rms); residuals
growing towards low frequency (drift during the sweep); circuit rms above 2 %; requested
circuit not supported; two or more inductive points at low frequency (negative
capacitance loop, Ebadi et al. 2019) or at high frequency (leads); fewer than 3 decades
of frequency; α < 0.7; an arc whose peak frequency lies outside the measured range.

References: Boukamp, J. Electrochem. Soc. 142, 1885 (1995); Schönleber, Klotz &
Ivers-Tiffée, Electrochim. Acta 131, 20 (2014); Hsu & Mansfeld, Corrosion 57, 747
(2001); Guerrero, Bisquert & Garcia-Belmonte, Chem. Rev. 121, 14430 (2021); von Hauff &
Klotz, J. Mater. Chem. C 10, 742 (2022); Ebadi et al., Nat. Commun. 10, 1574 (2019).

## 21. Capacitance-voltage, Mott-Schottky (`scripts/CV/cv_core.py`)

For a one-sided abrupt junction of area A: 1/C² = 2 (V_bi − V − kT/q)/(q ε₀ ε_r A² N).
Repeated voltages are averaged, the capacitance unit is set with `c_unit`, and the
voltage axis is reversed when 1/C² rises with V (the device was biased with the other
polarity). At least 8 points.

**Linear window** — `find_linear_window`: every window of max(5, n/8) or more consecutive
points is fitted (cumulative sums, so all windows cost one pass). Windows with a
negative slope that span 15 % or more of the voltage range are kept; the R² thresholds
0.999, 0.995, 0.99, 0.98, 0.95 are tried in this order and the widest window (then the
highest R²) that meets the first satisfiable threshold is taken. `v_min`/`v_max` set the
window by hand.

**Results** — N = 2/(q ε₀ ε_r A² |d(1/C²)/dV|) with the error of the slope;
V_bi = intercept + kT/q; depletion width W = ε₀ ε_r A/C at 0 V and over the window;
doping profile N(W) = −2/(q ε₀ ε_r A² d(1/C²)/dV) point by point; Debye length
√(ε kT/(q² N)).

**Resolution limit** — `resolution_limit_cm3`: with the layer thickness d,
C_geo = ε₀ ε_r A/d and N_min = 27 m kT ε₀ ε_r/(4 q² d²) with m = 2 by default
(Ravishankar et al. 2022, eq. 9). An apparent density near N_min is what an undoped,
fully depleted layer shows; it is not a doping density (Ravishankar et al. 2021).

**Validity checks**: no straight section; N outside 10¹⁰-10²⁰ cm⁻³ or W below 1 nm;
N < 3 N_min; W in the window above 0.9 d (fully depleted); no thickness entered (the
limit cannot be tested); window R² below 0.99; window narrower than 0.2 V; V_bi outside
0.3-1.6 V; axis reversed.

References: Sze & Ng, *Physics of Semiconductor Devices*, 3rd ed. (2007), ch. 2;
Kirchartz et al., J. Phys. Chem. C 116, 7672 (2012); Almora et al., Appl. Phys. Lett.
109, 173903 (2016); Ravishankar, Unold & Kirchartz, Science 371, eabd8014 (2021);
Ravishankar, Bisquert & Kirchartz, Chem. Sci. 13, 4828 (2022).

## 22. Operational stability (`scripts/Stability/stability_core.py`)

Input is a time trace of efficiency, power or normalised output. Times are converted to
hours (s, min, h, day) and counted from the first point. Normalisation: to the mean of
the first `n_initial` points (default), to the maximum, or none (values in per cent are
divided by 100). At least 6 points.

**Lifetime at a level** — `crossing_time`: T80 (level 0.8 by default) is the first time
the trace falls below the level and stays below it for the next 3 points, with linear
interpolation between the two samples; traces of 15 or more points are smoothed with a
5-point running median first, so a single noisy sample does not set the lifetime.

**Models** — linear E = a − b t; exponential a exp(−t/τ); burn-in
a₁ exp(−t/τ₁) + a₀ − b t; bi-exponential. Least squares from several starting points
(`fit_model`), selection by AICc with the simpler model kept within 2 units. A model is
not valid when the fast term is below 1 % of the output, has not finished within the
measurement (3 τ₁ longer than the trace), a time constant is not determined (error
larger than the value), or the two time constants are closer than a factor 3.

**Extrapolation** — when the level is not reached, the fitted model is followed up to
1000 times the measured time (`extrapolate_crossing`). The result is stored separately
(`T_extrapolated`) and labelled as extrapolated wherever it is shown; when the level was
reached, `T_model` is the same level read from the fitted curve for comparison.

**Burn-in** — with the burn-in model: stabilised point t_s = 3 τ₁, stabilised output
E_s = E(t_s), burn-in loss = 100 (E(0) − E_s) in absolute per cent, and Ts80 = time from
t_s until the output falls to 0.8 E_s, measured or extrapolated (Roesch et al. 2015).

**Rates and totals** — linear loss rate in %/1000 h with its standard error, over the
stabilised part (burn-in model) or the whole trace; final output (mean of the last 5 %
of the points); maximum and its time; mean output over the test. The ISOS protocol
chosen in the window (ISOS-D-1/2/3, L-1/2/3, T-1, O-1, V-1, LC-1, MPP tracking, or not
stated) is written into the report and the side-car.

**Validity checks**: level never reached within 1000 times the measured time (no
lifetime can be stated); lifetime extrapolated, with the ratio to the measured time;
output rising more than 3 % above the first value with initial normalisation (light
soaking - normalise to the maximum and say so); protocol not stated; fewer than 15
points; requested model not supported; fit rmse above 2 %.

References: Reese et al., Sol. Energy Mater. Sol. Cells 95, 1253 (2011); Roesch et
al., Adv. Energy Mater. 5, 1501407 (2015); Khenkin et al., Nat. Energy 5, 35 (2020);
Burnham & Anderson (2002).

## 23. Measurement detection and the results index

**Detection** (`scripts/common/detect.py`) decides which tool a data file belongs to. It
is a list of scored rules; nothing is learned from the files and nothing leaves the
computer. Three kinds of evidence add up to one score per measurement kind:

| Evidence | Weight | Example |
|---|---|---|
| File name (`name_scores`) | 2.5-4.5 | `trpl`, `tcspc`, `eqe`, `ipce`, `uv-vis`, `xrd`, `raman`, `ftir`, `xps`, `sclc`, `electron-only`, `eis`, `nyquist`, `mott`, `c-v`, `mppt`, `isos`, `suns-voc`, `dark`, `jv`, `sem` |
| Column names (`column_scores`) | 2.5-4.5 | frequency with Z′/Z″; voltage with capacitance; time with counts; time with PCE; intensity with Voc; wavelength with EQE; a 2θ column; a binding-energy column |
| Numbers (`numeric_scores`) | 0.8-2.5 | log-spaced first column over three decades with three columns (impedance); voltage axis and a current that changes sign (illuminated J-V); current over decades without photocurrent (dark J-V or SCLC); angle axis with fine steps (XRD); wavelength, wavenumber or time axis with the matching shape |

A score of 5 or more is **high** confidence, 3 or more **medium**, anything lower
**low**; a kind that scores below 0.8 is dropped, and a file with no kind left is listed
as not recognised. Numbers alone never exceed 2.5, so a file without a telling name or
header is at most a suggestion, and the launcher asks before opening a low-confidence
file. The sentence behind every score is kept (`Detection.evidence`) and shown in the
Workspace list, together with the alternative kinds that score 1.5 or more. Three rules settle the cases that the scores leave open: `dark` in
the name moves a current-voltage score to the dark J-V tool, `sclc` (or
`electron-only`, `hole-only`) in the name takes half of the J-V scores, and a decay
trace with `PL` in its name counts as TRPL when the time-axis score is at least as
large. Images are offered to the FE-SEM tool only when they are TIFF files or carry
`sem` or a magnification in the name. Files above 30 MB are classified by name only.

`scan_folder` walks a folder two levels deep (2000 files at most), skips hidden files,
office lock files and every table that has a side-car next to it (section 14), and
reports progress so that the window can show it and cancel.

**Results index** (`scripts/common/results_index.py`) reads the side-cars below a folder
(four levels, 5000 at most) and lists what was exported: date, tool, sample, a headline
value per tool, the export file, the inputs and the program version. `write_excel`
writes the index, one sheet per tool with one row per export and one column per
result, and an `All values` sheet in long form (one row per value) for pivoting. A
side-car that cannot be read is listed with its error instead of stopping the scan,
and the index workbook is not indexed itself.
