# Configuration

All configuration files are git-ignored: they hold machine-specific paths and an
optional API key. Copy the template and edit your local copy.

```bash
cp physisfera_config.example.json physisfera_config.json
```

## `physisfera_config.json` (project root)

| Key | Meaning | Default |
|---|---|---|
| `cell_area_cm2` | Device area used to convert measured current to current density. **Set this before analysing any J–V data** — it scales Jsc and therefore PCE linearly. | `0.04` |
| `origin_path` | Path to `Origin.exe` for optional plot export. Empty disables Origin export. | `""` |
| `gemini_api_key` | Optional. Enables the AI commentary panels only. | `""` |
| `name_presets` | Sample-name presets shared by every tool's rename menu. Written by the application. | `[]` |

The file is read when an analysis runs, not when the application starts, so a
corrected `cell_area_cm2` applies to the next folder you process — no restart.
A value that is missing, zero, negative or unparseable falls back to `0.04`
rather than producing an infinite conversion factor. Set `PHYSISCORE_CONFIG` to
point every tool at a different file (useful for a second device geometry).

Callers may also pass the area explicitly and bypass the file entirely:

```python
from scripts.JV.jv_core import process_jv_directory
data = process_jv_directory("2026-01-20/light", area_cm2=0.09)
```

The per-tool files (`scripts/JV/jv_config.json`, `scripts/Dark_JV/dark_jv_config.json`,
`scripts/SEM/sem_config.json`, …) store view state — axis ranges, recent folders,
sample-name presets — and are written by the application. They are not required to
exist; each tool recreates its own with defaults.

## The AI features are optional

With `gemini_api_key` empty, every numerical result, plot and export is byte-for-byte
identical. Nothing in the physics path calls the model — it only produces
natural-language commentary alongside results that were already computed. This
separation is deliberate, so that published numbers never depend on a model version
or a network round-trip.

## Do not commit your key

`physisfera_config.json` and `scripts/*/…_config.json` are listed in `.gitignore`
because a working configuration contains a live API key in plain text. If a key is
ever committed, rotate it — removing the file in a later commit does not remove it
from the history.
