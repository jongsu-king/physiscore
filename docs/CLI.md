# Command-line reference

`physiscore_cli.py` runs the same analysis cores as the GUI, for scripted and batch work.
From a source checkout run `python physiscore_cli.py ...`; after `pip install .` the
command is `physiscore ...`. Every command prints a readable summary; `--json` prints the
complete result as JSON (NaN becomes `null`) for other programs. Exports are accompanied
by a `.analysis.json` side-car.

| Command | Input | Main output |
|---|---|---|
| `jv FOLDER` | folder of J-V files | Excel workbook, statistics, curve analysis, diode fit, hysteresis |
| `dark FOLDER` | folder of dark J-V files | Excel workbook, n, J0, Rs, Rsh |
| `eqe FILE` | EQE spectrum | Jsc, Eg (Rau), Urbach, J0,rad, Voc,rad, SQ limits, voltage losses |
| `abs FILE` | absorbance spectrum | Tauc Eg ± error, region, derivative Eg, Urbach |
| `xrd FILE` | XRD pattern | peak table, Williamson-Hall, crystallinity |
| `pl FILE` | PL spectrum | peak in nm and eV, FWHM in nm and meV, components |
| `vib FILE --technique raman/ftir` | Raman/FTIR spectrum | bands, fits, library suggestions |
| `sem-stats VALUES/FILE` | diameters | D10/D50/D90, log-normal parameters |
| `device --jv --eqe [--abs --pl]` | one device | cross-technique summary and checks |
| `batch TECHNIQUE PATHS` | files or folders | one table row per spectrum |
| `sclc FILE ...` | single-carrier J-V curves | regions and slopes, V_TFL, trap density, Mott-Gurney mobility, resolution limit |
| `intensity FILE ...` or `--jv-set` | intensity series (table, or J-V files named by irradiance) | ideality factor, Jsc exponent, pseudo fill factor, transport loss |
| `trpl FILE ...` | TRPL decays | lifetimes with errors, average lifetimes, differential lifetime, fit quality |
| `eis FILE ...` | impedance spectra | Kramers-Kronig test, equivalent circuit with errors, capacitances, time constants |
| `cv FILE ...` | capacitance-voltage sweeps | Mott-Schottky doping density, built-in potential, depletion width, resolution limit |
| `stability FILE ...` | stability traces | T80, burn-in, Ts80, loss rate, extrapolation checks |
| `detect PATHS` | files or folders | what each file is and which tool opens it |
| `collect FOLDER` | a project folder | every exported result in one table or workbook |
| `sq EG` | band gap | Shockley-Queisser limit |
| `validate` | - | the validation table of docs/VALIDATION.md |
| `update [--check-only]` | - | checks GitHub for a newer release; an installed copy downloads, verifies and installs it |
| `docs NAME [--section 3.]` | USER_GUIDE, METHODS, VALIDATION, FILE_FORMATS, INSTALL, CLI or `list` | opens the offline documentation in the browser |

## jv

```
physiscore jv FOLDER [--area CM2] [--out FILE.xlsx] [--no-diode-fit] [--json]
```

`--area` overrides the configured device area. The workbook defaults to
`FOLDER/<folder name>.xlsx`. JSON keys: `statistics`, `curve_analysis`, `hysteresis`,
`excel`, `cell_area_cm2`.

## dark

```
physiscore dark FOLDER [--area CM2] [--out FILE.xlsx] [--json]
```

## eqe

```
physiscore eqe FILE [--sheet NAME] [--column NAME] [--voc V] [--temperature K] [--json]
```

`--voc` (the measured open-circuit voltage) adds the ΔV1/ΔV2/ΔV3 breakdown and EQE_EL.
JSON keys include `Jsc_mA_cm2`, `Eg_Rau_eV`, `Eg_sigma_eV`, `Eg_inflection_eV`,
`Eu_meV`, `J0_rad_mA_cm2`, `Voc_rad_V`, `Jsc_SQ`, `Voc_SQ`, `FF_SQ`, `PCE_SQ`,
`dV1_SQ`, `dV2_rad`, `dV3_nonrad`, `EQE_EL`.

## abs

```
physiscore abs FILE [--sheet NAME] [--column NAME] [--mode direct|indirect|direct_forbidden|indirect_forbidden]
                   [--thickness NM] [--expected-eg EV] [--subtract-offset] [--json]
```

`--subtract-offset` subtracts the sub-gap absorbance (median of the lowest-energy 5 % of the
spectrum, which must lie 0.15 eV or more below the edge) before the Tauc fit; a constant
offset otherwise lowers the gap (METHODS §4). Added in 3.5.3.

## xrd

```
physiscore xrd FILE [--instrument-fwhm DEG] [--k 0.9] [--strip-ka2] [--out peaks.csv] [--json]
```

## pl

```
physiscore pl FILE [--sheet NAME] [--column NAME] [--filter 5] [--rigidity 6] [--protection 0.01]
                  [--max-peaks 3] [--json]
```

`--rigidity 0` disables the baseline. `--max-peaks 1` skips the multi-component fit.

## vib

```
physiscore vib FILE --technique raman|ftir [--baseline arpls|als|linear|min|none] [--lam 1e5]
                   [--smooth 0] [--prominence 2] [--json]
```

## sem-stats

```
physiscore sem-stats 120 135 98 ...            # values in nm
physiscore sem-stats grains.xlsx               # a column with nm/size/diam in its name
```

## device

```
physiscore device --jv CELL.txt --eqe CELL_EQE.csv [--abs FILM.xlsx --mode direct] [--pl FILM_PL.csv]
                  [--sweep reverse|forward|combined] [--area CM2] [--irradiance 100] [--temperature 300]
                  [--out device.xlsx] [--json]
```

Prints the summary table (quantity, value, unit, origin) and the warnings. JSON keys
follow `scripts.common.device_summary.summarize_device` (`JV_*`, `diode_*`, `EQE_*`,
`Jsc_mismatch_percent`, `Eg_*`, `SQ_*`, `dV*`, `warnings`, `notes`).

## batch

```
physiscore batch eqe|abs|pl|xrd|raman|ftir FOLDER_OR_FILES... [--sheet NAME] [--column NAME] [--all-columns]
                 [--mode direct] [--temperature 300] [--instrument-fwhm 0] [--k 0.9] [--out table.xlsx|.csv] [--json]
```

Analyses every data file of the folders (and the files given), one row per spectrum
(`--all-columns`: every numeric column of every file). A file that cannot be read is
listed with its error instead of stopping the batch. Outputs written by Physiscore (files
with a side-car) are skipped.

Example: compare the band gaps of a composition series

```bash
physiscore batch abs data/2026-11_series --all-columns --out series_bandgaps.xlsx
```

## sclc, intensity, trpl, eis, cv, stability

The six transport and recombination commands share one form: one or more files, the
parameters of the matching window as options, and three common switches.

```
physiscore sclc      [--thickness NM] [--eps EPS_R] [--area CM2] [--temperature K]
                     [--branch auto|positive|negative] [--sweep up|down|all]
                     [--vbi V] [--window N] [--field-dependent] FILE [FILE ...]
physiscore intensity [--temperature K] [--i-min I] [--i-max I] FILE [FILE ...]
physiscore intensity --jv-set JV_FILE [JV_FILE ...] [--area CM2]
                     [--sweep reverse|forward|combined]
physiscore trpl      [--model auto|exp1|exp2|exp3|stretched] [--background auto|none|NUMBER]
                     [--skip T] [--t-end T] [--time-unit ps|ns|us|ms|s] [--irf-fwhm T]
                     [--mobility CM2_VS] [--temperature K] FILE [FILE ...]
physiscore eis       [--model auto|R(RC)|R(RQ)|R(RC)(RC)|R(RQ)(RQ)]
                     [--convention auto|Z''|-Z''] [--f-min HZ] [--f-max HZ]
                     [--area CM2] [--thickness NM] FILE [FILE ...]
physiscore cv        [--area CM2] [--eps EPS_R] [--thickness NM] [--temperature K]
                     [--c-unit F|mF|uF|nF|pF] [--m M] [--v-min V] [--v-max V] FILE [FILE ...]
physiscore stability [--time-unit s|min|h|day] [--norm initial|maximum|none]
                     [--n-initial N] [--threshold FRACTION]
                     [--model auto|linear|exponential|burn-in|bi-exponential]
                     [--protocol NAME] FILE [FILE ...]
```

Common switches of all six:

| Switch | Effect |
|---|---|
| `--out FILE.xlsx` | writes the workbook of the window (Summary, Results, Checks, Parameters and the curve sheets) and the `.analysis.json` side-car next to it |
| `--interpret` | adds the rule-based interpretation (METHODS section 16) below each file |
| `--json` | prints the complete result as JSON instead of the text report |

Defaults that matter:

| Command | Default | Note |
|---|---|---|
| `sclc` | thickness 500 nm, eps_r 25, 300 K, branch auto, sweep up, V_bi 0, window 5 points | `--area` is needed only for files that store a current instead of a current density; without it the area of the settings is used. `--field-dependent` fits the Murgatroyd law instead of Mott-Gurney. |
| `intensity` | 300 K, whole intensity range | `--i-min`/`--i-max` restrict the fits. With `--jv-set` the irradiance is read from each file name (`0.1sun`, `53mW`, `10pct`, `OD1.0`); fewer than three such names is an error. |
| `trpl` | model auto (lowest AICc among the valid fits), background auto, time unit ns | `--irf-fwhm` and `--mobility` are 0 (not stated): the shortest lifetime is not compared with the instrument response and no diffusion length is given. `--skip`, `--t-end` and `--irf-fwhm` are in the unit of `--time-unit`. |
| `eis` | circuit auto (lowest AICc among the valid fits), sign convention auto | `--area` and `--thickness` are 0 (none). The area adds the area-normalised resistances and capacitances; area and thickness together add the relative permittivity from the high-frequency arc. |
| `cv` | eps_r 25, 300 K, capacitance in F, m = 2 | the Mott-Schottky window is chosen automatically unless `--v-min`/`--v-max` are given. `--thickness` adds the geometric capacitance and the resolution limit N_min; without it a check says that the density could not be compared with the limit. The area of the settings is used unless `--area` is given. |
| `stability` | time in h, normalised to the first point, threshold 0.8 (T80), model auto | `--protocol` is one of `ISOS-D-1`, `ISOS-D-2`, `ISOS-D-3`, `ISOS-L-1`, `ISOS-L-2`, `ISOS-L-3`, `ISOS-T-1`, `ISOS-O-1`, `ISOS-V-1`, `ISOS-LC-1`, `MPP tracking`; it is recorded with the result and does not change the numbers; without it a check says that a lifetime is comparable only with its protocol. |

The text report has the same parts for every command: a header with the number of files
analysed, the parameters used, one block per file (the columns the file was read as, one
line per quantity, the check list) and a summary table over all files. A real run on two
synthetic traces:

```
$ physiscore stability Stability/*.csv --protocol ISOS-L-1
Stability: 2 of 2 files analysed
Parameters: time_unit = h, norm = initial, n_initial = 1, threshold = 0.8, model = auto, protocol = ISOS-L-1

Ref_MPPT_ISOS-L-1
  read as: t = Time (h), y = PCE (%)
  ...
  T80 (measured)                  794.5 h
  T80 (on the fitted curve)       793 h
  Linear loss rate after burn-in  10.36 %/1000 h
  Burn-in loss                    12.45 % abs
  Ts80 (extrapolated)             1656 h
  ...

Summary:
  File  Model  T measured (h)  T extrapolated (h)  Ts (h)  Loss rate (%/1000 h)  Final (%)  Checks  Error
  ...
```

A value marked *extrapolated* comes with a check that states how far beyond the measured
time it lies. A file that cannot be analysed is listed as `not analysed: <reason>` and the
run continues with the next file. An option value outside its list stops the run with
`<Tool>: key = value is not one of ...`.

JSON keys: `tool`, `parameters`, `files[]` with `file`, `path`, `inputs`, `error`,
`checks`, `summary[]` (`quantity`, `value`, `unit`), `interpretation` (with `--interpret`)
and `result` (the full result of the analysis core).

## detect

```
physiscore detect FILE_OR_FOLDER [FILE_OR_FOLDER ...] [--depth N] [--json]
```

Reports what each file is and which tool opens it, the same detection the launcher uses
for *Open data* and the *Workspace* tab (METHODS section 23). Folders are searched
`--depth` levels deep (default 2). Nothing is analysed and nothing is written.

```
$ physiscore detect unsorted EIS
unsorted: 4 files: 1 J-V (illuminated), 1 Impedance spectrum, 1 Time-resolved PL, 1 not recognised
  device3.dat: J-V (illuminated) (low) -> J-V Curve
      146 x 2  ·  col0, col1  |  voltage axis and a current that changes sign at 1.00 V
  notes.txt: not recognised
      notes.txt: no block of numeric rows
  run_0012.txt: Time-resolved PL (low) -> TRPL
      1000 x 2  ·  col0, col1  |  a peak near the start that decays by more than 1.5 decades
  sample_07.csv: Impedance spectrum (low) -> Impedance
      71 x 3  ·  A, B, C  |  log-spaced first column over 7 decades with 3 columns
EIS: 1 file: 1 Impedance spectrum
  Ref_EIS_0V_dark.csv: Impedance spectrum (high) -> Impedance
      71 x 3  ·  Frequency (Hz), Z' (Ohm), Z'' (Ohm)  |  file name (eis); frequency and impedance columns; ...
```

Each line gives the kind, the confidence (`high`, `medium`, `low`) and the tool; the line
below it gives the shape of the numeric block, the column names and the evidence the
decision rests on. A *low* confidence means the decision rests on the shape of the numbers
alone (no header, no telling file name): check it before trusting it.

JSON keys per file: `path`, `kind`, `label`, `tool`, `confidence`, `score`, `evidence`,
`alternatives`, `columns`, `shape`, `error`.

## collect

```
physiscore collect FOLDER [--out FILE.xlsx] [--depth N] [--json]
```

Gathers every `*.analysis.json` side-car below `FOLDER` (default 4 levels deep) into one
table: date, tool, sample, the first key results and the export it belongs to. This is the
*Results* tab of the launcher. With `--out` the table is written as a workbook with the
sheets `Index`, one sheet per tool and `All values` (one row per quantity, for pivot
tables and plotting); `--out` on a folder without side-cars stops with `nothing to
collect: no *.analysis.json below this folder`.

JSON keys: `folder`, `exports`, `values`.

## sq

```
physiscore sq 1.60 [--temperature 300] [--json]
```

## validate

```
physiscore validate [--csv]
```

Regenerates the table in [VALIDATION.md](VALIDATION.md) from closed-form synthetic data.

## update

```
physiscore update                 # check and, for an installed copy, install the latest release
physiscore update --check-only    # only report
```

Exit status 2 when GitHub cannot be reached (for example after 60 unauthenticated requests
in an hour from the same address).

## docs

```
physiscore docs list
physiscore docs METHODS --section 3.      # opens Methods and algorithms at section 3 (EQE)
```

## Exit status

0 on success; a non-zero status with a message on unreadable input (`jv`/`dark` when a
folder holds no curve, `batch` when no file is found). The six transport commands return
0 when at least one file was analysed and 1 when none was; `detect` returns 1 only when a
path does not exist; `collect --out` returns 1 when there is nothing to collect.
