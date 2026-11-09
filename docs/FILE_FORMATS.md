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

## 9. Files Physiscore writes

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
| Compare files | chosen name | Results + one sheet per spectrum |
| every Excel export | `<name>.analysis.json` | version, date, inputs, parameters, results |
| Report (any tool) | `<name>.md` + `<name>.png` | tables, figure, methods note |
