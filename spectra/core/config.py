from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple
from pydantic import BaseModel, Field, conlist

# ---- Gemini structured output models ----
class PeakInit(BaseModel):
    center: float = Field(..., description="Peak center in x units")
    height: float = Field(..., description="Approx peak height (normalized 0..1)")
    fwhm: float = Field(..., description="Approx FWHM in x units")
    kind: str = Field("voigt", description="Line shape suggestion")

class GeminiPeakHint(BaseModel):
    region: Tuple[float, float] = Field(..., description="Region [x_min, x_max]")
    peaks: conlist(PeakInit, min_length=1, max_length=10) = Field(...)
    notes: str = Field("", description="Short notes")

@dataclass
class PipelineConfig:
    technique: str = "GEN"  # "XRD" | "PL" | "GEN"
    sg_window: int = 21
    sg_poly: int = 3
    als_lam: float = 1e6
    als_p: float = 0.01
    als_max_iter: int = 50
    max_candidates: int = 50
    use_noise_based_prominence: bool = True
    noise_k: float = 8.0
    min_peak_separation_x: float = 0.20
    overlap_merge_dx: float = 0.6
    region_half_width: float = 1.5
    fit_pad: float = 2.5
    use_gemini: bool = False
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.2
    gemini_max_points: int = 600

    # PL
    pl_enable_aic: bool = True
    pl_max_peaks: int = 3
    pl_defect_fwhm_threshold: float = 0.25

    # XPS (used by pipelines/run_xps.py; these were referenced but missing,
    # which crashed the XPS pipeline on every run)
    xps_roi_min: float = 0.0        # roi_min >= roi_max -> ROI disabled
    xps_roi_max: float = 0.0
    xps_split_ev: float = 0.0       # 0 -> singlet fit (O1s/C1s/N1s); >0 -> doublet split [eV]
    xps_area_ratio: float = 0.5     # doublet area ratio (p: 1/2 of main, d: 2/3, f: 3/4)
    xps_lock_widths: bool = True
