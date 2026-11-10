# Configuration

All configuration files are git-ignored: they hold machine-specific paths. Copy the template and edit your local copy.

```bash
cp physisfera_config.example.json physisfera_config.json
```

## `physisfera_config.json` (project root)

| Key | Meaning | Default |
|---|---|---|
| `cell_area_cm2` | Device area used to convert measured current to current density. **Set this before analysing any J–V data** — it scales Jsc and therefore PCE linearly. | `0.04` |
| `origin_path` | Path to `Origin.exe` for optional plot export. Empty disables Origin export. | `""` |
| `theme` | `light` or `dark` appearance of every window; applies after a restart. `PHYSISCORE_THEME` overrides it for one run. | `light` |
| `name_presets` | Sample-name presets shared by every tool's rename menu. Written by the application. | `[]` |
| `workspace_folder` | The project folder listed in the Workspace and Results tabs. Written when a folder is chosen. | `""` |
| `tool_params` | The parameters last used in the SCLC, light-intensity, TRPL, impedance, C-V and stability windows (thickness, permittivity, model, ...), one entry per tool. Written when an analysis runs. | `{}` |

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

## Interpretation needs no key (3.4)

Up to 3.3 the interpretation panels called the Gemini API with a key stored here
(`gemini_api_key`). 3.4 replaced them with rule-based interpretation
(`scripts/common/interpret.py`, METHODS §16): nothing is sent anywhere and the same
result always gives the same text. A `gemini_api_key` written by an older version is
no longer read and is removed from the file the next time the Settings dialog saves.
If such a key was ever committed to a repository, revoke it in Google AI Studio —
removing the file in a later commit does not remove it from the history.
