Spectra Processor v4

Physics-constrained Spectral Analysis Platform for XRD and PL.

Overview
Spectra Processor v4 is a modular, physics-aware analysis platform designed for XRD and PL experimental data.
The system integrates deterministic constraints, statistical model selection, and AI-assisted reasoning into a unified workflow.

Key Features
- Unified GUI for XRD / PL
- Deterministic peak fitting with Voigt profiles
- Noise-adaptive peak detection (MAD-based)
- AIC-based peak-number selection for PL
- Human-in-the-loop validation
- Batch processing + Excel / CSV export
- Dark-mode research-oriented UI

Project Structure
spectra_processor_v4/
  app.py                 # Application entry point
  core/
    config.py            # Global pipeline configuration
    baseline.py          # AsLS baseline correction
    peak_detect.py       # Noise-adaptive peak detection
    fit_common.py        # Generic Voigt fitting utilities
    report.py            # AI peak interpretation & report generation
    utils.py             # Shared helper functions
  pipelines/
    run_xrd.py           # XRD analysis pipeline
    run_pl.py            # PL analysis pipeline
  gui/
    tab_dashboard.py     # Unified GUI tab logic

Installation
pip install numpy pandas scipy matplotlib pybaselines lmfit pydantic openpyxl
# Optional (AI features)
pip install google-genai

Run
python app.py
