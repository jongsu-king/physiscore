# Accepted file formats

Physiscore reads plain text (CSV, TSV, TXT, DAT, XY) and Excel (XLSX, XLS). In text
files a metadata preamble above the numbers is skipped; the separator (comma, tab,
semicolon, space) is detected automatically. Unless stated otherwise the first column is
the x axis and the first numeric column after it the y axis; the comparison windows and
the batch command can also read every numeric column of a file.

## 1. J-V curves (light and dark)

**Instrument text export** (the source-meter format the lab uses):

```
...                                   <- any header lines
Voc V   Voc_mA   Jsc mA/cm2  ...  Fill Factor  Efficiency     <- optional summary block (light)
0.912   ...      22.10       ...  77.3         15.6
...
RShunt ohms ...                                               <- optional (dark)
Vmeas   Imeas                                                 <- required
-0.200  0.000889
...
```

- `Vmeas` in V, `Imeas` in A with the instrument's sign; Physiscore divides by the device
  area (Settings) and converts to mA/cm².
- Without the summary block the summary values are computed from the curve.
- A file swept forward and back is split automatically for the hysteresis analysis.

**Generic curve files** (CSV/TSV/DAT/XLSX), recognised by their headers:

| Header contains | Interpreted as |
|---|---|
| `V`, `Volt`, `Bias` | voltage in V |
| `mA/cm`, starts with `J`, `density` | current density in mA/cm² (used as is) |
| `(mA)` | current in mA, divided by the area |
| `I`, `Current`, `(A)` | current in A, divided by the area |
| no recognisable header | column 1 = voltage, column 2 = current density |

The sign is normalised so that the photocurrent is negative at short circuit (the
plotting convention); the analysis itself does not depend on the sign.

**File names** become sample names: `Ref 3.txt` is cell 3 of condition `Ref`; the
instrument timestamp (`... 2026-01-20 18-35-48`) and a leading index (`01. `) are
removed, `_` becomes a space and `110C` becomes `110°C`.

## 2. EQE

Wavelength (nm) and EQE (% or fraction; values above 1.5 are taken as %). Ascending or
descending order. Excel: choose the sheet.

## 3. Absorbance

Wavelength (nm) in column 1; one or more absorbance columns (choose one in the window).
Absorbance, not transmittance.

## 4. PL

One wavelength column (found by a header containing `nm`, `wave`, `lambda`, `length` or
`energy`, otherwise column 1) and any number of sample columns. In Excel the sheet whose
name contains `pl` is used first.

## 5. XRD

Two columns, 2θ in degrees and intensity (counts). Instrument text exports with a header
block work.

**Reference peak list** (for *Reference* matching), CSV/TXT/XLSX with:

| Column (any of these names) | Content |
|---|---|
| `2theta`, `2θ`, `two_theta`, `angle` | peak position in degrees (Cu Kα) |
| or `d`, `d (A)`, `d-spacing` | lattice spacing in Å (converted to 2θ) |
| `hkl`, or `h`, `k`, `l` | Miller indices (optional) |
| `I`, `intensity`, `I_rel` | relative intensity (optional; scaled to 100) |

Example (cubic perovskite):

```
2theta,h,k,l,I
14.10,1,0,0,100
19.97,1,1,0,15
24.51,1,1,1,20
28.43,2,0,0,60
```

## 6. Raman and FTIR

Column 1 wavenumber (cm⁻¹ or Raman shift); up to ten spectrum columns. The column header
is used as the layer name. FTIR may be transmittance (% or fraction) or absorbance.

## 7. SEM

Images: TIF, PNG, JPG, BMP (8- or 16-bit, grey or colour). An instrument data bar at the
bottom is detected and excluded.

## 8. XPS (auto-fit workspace)

Binding energy (eV) and counts. Thermo Avantage region exports with a few metadata lines
before the numbers are read directly. Either axis order works.

## 9. Transport and recombination tools

The six tools added in 3.5, and PLQY and the spectral mismatch (3.7), read a table by
**column name first and position second**.
Each tool lists the quantities it needs; a column whose header contains one of the listed
words is taken for that quantity, and a quantity without a matching header is taken from
the stated position. The window, the report and the CLI state which column was read as
what (`read as: t = Time (h), y = PCE (%)`), and a column taken by position is marked
*(by position)*.

The text reader of these tools:

- skips any metadata above the numbers; the one or two lines directly above the numeric
  block with the same number of fields are the column names (a second line is read as the
  units), also when they start with `#` or `%`;
- detects the separator (tab, semicolon, comma, blanks) as the one that yields the most
  numeric rows, and accepts a decimal comma when the separator is not a comma
  (`0,912;22,10` reads as 0.912 and 22.10);
- reads UTF-8, CP949 and Latin-1;
- drops columns with fewer than three numbers and rows without any number;
- reads Excel workbooks (first sheet) the same way.

A file without a header line is read by position alone.

### 9.1 SCLC

A dark J-V curve of a single-carrier device.

- **Instrument export** with a `Vmeas / Imeas` block: read in full (the solar-cell reader
  of section 1 keeps only -3 to 3 V, which would cut the Child region). The current in A
  is divided by the device area (parameter *Area*, by default the area of the Settings).
- **Any other table**: the header rules of the generic curve files of section 1.
- Only magnitudes are used, so the sign convention does not matter. A cyclic sweep is
  split into its up and down parts (parameter *Sweep*).

### 9.2 Light intensity

Either **one table** with one row per intensity:

| Quantity | Header contains | Position without a header |
|---|---|---|
| irradiance | `intens`, `irradi`, `sun`/`suns`, `mw`, `power`, `light` | column 1 |
| Voc (V) | `voc`, `v_oc`, `open` | column 2 |
| Jsc | `jsc`, `j_sc`, `isc`, `short` | column 3 |
| FF (optional) | `ff`, `fill` | - |
| PCE (optional) | `pce`, `eff`, `eta` | - |

The irradiance may be in any unit (suns, mW/cm², percent): the ideality factor and the
Jsc exponent depend only on ratios. Without a Jsc column the Jsc exponent and the pseudo
J-V are not computed.

Or **a set of J-V files of one cell**, one per intensity, with the irradiance in each file
name:

| In the name | Read as |
|---|---|
| `0.1sun`, `0p5 suns` | 0.1 and 0.5 suns = 10 and 50 mW/cm² |
| `53mW` | 53 mW/cm² |
| `10%`, `10pct`, `10percent` | 10 mW/cm² (10 % of one sun) |
| `OD1.0`, `ND2`, `od_0p3` | neutral-density filter: 100 x 10^-OD mW/cm² |

Voc, Jsc and FF are taken from each curve with the J-V reader of section 1. At least three
files must carry an irradiance.

### 9.3 TRPL

| Quantity | Header contains | Position without a header |
|---|---|---|
| time | `time`, `delay`, `t`, a unit `ps`/`ns`/`us`/`ms`/`s` | column 1 |
| counts or intensity | `count`, `intens`, `pl`, `signal`, `decay`, `y` | column 2 |

The unit of the time column is a parameter (ps, ns, us, ms, s; ns by default). Raw
counts are fitted with Poisson weights (sigma = sqrt(N)); a normalised decay is weighted
with the same shape on a relative scale, and its reduced chi-square is then labelled
*(relative weights)*.

### 9.4 Impedance

| Quantity | Header contains | Position without a header |
|---|---|---|
| frequency (Hz) | `freq`, `f`, `hz` | column 1 |
| Z' (Ohm) | `z'`, `re(z)`, `zreal`, `z_re`, `real` | column 2 |
| Z'' (Ohm) | `z''`, `im(z)`, `zimag`, `z_im`, `imag` | column 3 |

The third column may hold Z'' (negative for a capacitive arc) or -Z'': the sign convention
is detected, and can be set with the parameter *Convention*. The frequency order does not
matter.

### 9.5 C-V

| Quantity | Header contains | Position without a header |
|---|---|---|
| voltage (V) | `volt`, `bias`, `v`, `vdc` | column 1 |
| capacitance | `cap`, `c`, `cp`, `cs`, `C (` | column 2 |

The unit of the capacitance column is a parameter (F, mF, uF, nF, pF; F by default). The
capacitance is the total capacitance of the device, not per area: the area is a parameter.

### 9.6 Stability

| Quantity | Header contains | Position without a header |
|---|---|---|
| time | `time`, `t`, `hour`, `elapsed`, `duration` | column 1 |
| tracked value | `pce`, `eff`, `power`, `pmax`, `pmpp`, `norm`, `eta` | column 2 |

The unit of the time column is a parameter (s, min, h, day; h by default). The value may
be an absolute efficiency or power or an already normalised trace; the normalisation is a
parameter.

### 9.7 PLQY and QFLS

**Integrating-sphere spectra** (one file per sample):

| Quantity | Header contains | Position without a header |
|---|---|---|
| wavelength (nm; µm is converted) | `wave`, `lambda`, `nm`, `wl` | 1st column |
| A: empty sphere, laser only | `empty`, `blank`, `no sample`, `without`, `ref`, `A` | 2nd |
| B: sample in the sphere, out of the beam (optional) | `out of beam`, `indirect`, `off beam`, `B` | 3rd of four |
| C: sample in the beam | `in beam`, `direct`, `on beam`, `C` | last |

```
# integrating sphere, 532 nm laser, spectra corrected for the system response
Wavelength (nm),Empty sphere (A),Out of beam (B),In beam (C)
450.0,2,9,5
...
532.0,200035,170837,33892
...
775.0,0,70,408
...
```

The spectra must be corrected for the spectral response of sphere and spectrometer and
dark-subtracted; counts (photons) by default, W/nm with *Spectra in = energy*.

**PLQY series** (one row per excitation intensity):

| Quantity | Header contains | Position without a header |
|---|---|---|
| intensity (suns, mW/cm² or per cent of one sun) | `intens`, `suns`, `irradi`, `excit`, `power`, `fluen`, `light` | 1st column |
| PLQY (fraction, or per cent when the header says `%` or a value exceeds 1) | `plqy`, `quantum`, `yield`, `qy` | 2nd |
| Voc (V), optional | `voc`, `open` | - |
| Jsc, optional | `jsc`, `short` | - |
| FF, optional (% or fraction) | `ff`, `fill` | - |

The EQE or absorptance file for J0,rad has a wavelength and a value column (`eqe`,
`ipce`, `qe`, `quantum`, `absorpt`, `respons`), % or fraction.

### 9.8 Spectral mismatch

Three kinds of two-column table (wavelength in nm, or µm converted):

- **test cell** (the files of the list): EQE in % or as a fraction, or the spectral
  responsivity in A/W - an EQE export of the EQE tool is read as it is;
- **simulator spectrum** (*Simulator spectrum* field): irradiance in any scale, in energy
  units (W m⁻² nm⁻¹) or photon flux (*Spectrum units = photons*); it should cover the
  whole response range of both cells (300-1200 nm for the 2020 class);
- **reference cell** (*Reference cell* field): its calibrated responsivity in A/W, or its
  EQE.

A header with `A/W`, `SR` or `responsivity` marks a responsivity, one with `EQE`,
`IPCE`, `QE` or `%` an EQE; without a telling header test files are read as EQE and
reference files as responsivities (*Test files hold*, *Reference holds* override it).

## 10. What the automatic detection looks at

*Open data*, the *Workspace* tab and `physiscore detect` (METHODS section 23) consider:

- tables with the extensions `.txt`, `.csv`, `.tsv`, `.dat`, `.xy`, `.asc`, `.prn`,
  `.xlsx`, `.xls` and images with `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp`;
- files up to 30 MB; a folder is searched two levels deep and up to 2000 files.

They skip names that start with `.` or `~$` (hidden files, lock files of an open
workbook), folders that start with `.` or `__`, the `*.analysis.json` side-cars, and
workbooks that Physiscore wrote itself (a table with a side-car next to it).

A decision uses the file name, the column headers and the numbers. A descriptive name
(`Ref_EIS_0V_dark.csv`, `PEAI_TRPL.txt`, `cell3_SCLC.csv`) and a header line raise the
confidence from *low* to *high*; a file with neither is still recognised from the shape of
its numbers when that is unambiguous.

## 11. Files Physiscore writes

| Tool | File | Sheets / content |
|---|---|---|
| J-V | `<folder>.xlsx` | CombinedData, SummaryTable, BestPerformance, BestCombinedData, CurveAnalysis, Statistics, Hysteresis, *_BoxChart |
| J-V dark | `<folder>_Dark.xlsx` | CombinedData, SummaryTable (with window fit, full fit) |
| EQE | `<file>_result.xlsx` | Result, EQE_Data, Urbach_Data, DetailedBalance |
| Absorbance | `<file>_result.xlsx` | Result, UV-Vis, Tauc_Data |
| PL | chosen name | PL_Results, Processed |
| XRD | chosen name | Peaks, Pattern, WilliamsonHall, ReferenceMatch, Crystallinity |
| SEM | chosen name | Grains, Statistics |
| Device summary | chosen name | Summary, AllValues, Checks, Inputs |
| SCLC | chosen name | Summary, Results, Checks, Parameters, Curve |
| Light intensity | chosen name | Summary, Results, Checks, Parameters, Series, Pseudo J-V |
| TRPL | chosen name | Summary, Results, Checks, Parameters, Decay, Fit, Differential lifetime |
| Impedance | chosen name | Summary, Results, Checks, Parameters, Spectrum |
| C-V | chosen name | Summary, Results, Checks, Parameters, Curve |
| Stability | chosen name | Summary, Results, Checks, Parameters, Trace |
| Results tab / `collect` | chosen name | Index, one sheet per tool, All values |
| Compare files | chosen name | Results + one sheet per spectrum |
| every Excel export | `<name>.analysis.json` | version, date, inputs, parameters, results |
| Report (any tool) | `<name>.md` + `<name>.png` | tables, figure, methods note |

The workbooks of the curve tools (section 9) hold one row per file in `Summary`, one row per
quantity in `Results`, and the curve sheets of up to 20 files; with several files the
curve sheets are numbered (`1 Decay`, `2 Decay`, ...) in the order of `Summary`.
