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
| `sq EG` | band gap | Shockley-Queisser limit |
| `validate` | - | the validation table of docs/VALIDATION.md |

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
                   [--thickness NM] [--expected-eg EV] [--json]
```

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

## sq

```
physiscore sq 1.60 [--temperature 300] [--json]
```

## validate

```
physiscore validate [--csv]
```

Regenerates the table in [VALIDATION.md](VALIDATION.md) from closed-form synthetic data.

## Exit status

0 on success; a non-zero status with a message on unreadable input (`jv`/`dark` when a
folder holds no curve, `batch` when no file is found).
