# Methods and algorithms

This document states, for every quantity Physiscore reports, the equation that is
evaluated, the numerical procedure, its defaults, and the primary reference. It is
written so that the methods section of a paper can cite it (or copy from it) and so
that a reviewer can check a number against the code. File references are to the
3.3.1 source tree; all functions are GUI-free and importable.

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
