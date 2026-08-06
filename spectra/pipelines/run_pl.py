import os, json
import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_widths
from spectra.core.config import PipelineConfig


def run_pl_pipeline(x, y, outdir, cfg: PipelineConfig, log_cb=None):
    """
    Simplified PL pipeline: Direct peak detection from raw data
    
    Returns:
        proc: DataFrame with processed data (x, y_raw)
        cand: DataFrame with peak candidates  
        fitted: DataFrame with main peak (center, height, bandgap_eV, peak_type)
    """
    os.makedirs(outdir, exist_ok=True)
    
    def log(s):
        if log_cb:
            log_cb(s)
    
    log("PL Analysis: Direct peak detection from raw data...")
    
    # Step 1: Find peaks using scipy (no complex baseline needed)
    # Height threshold: at least 5% of max intensity
    height_threshold = np.max(y) * 0.05
    peaks, properties = find_peaks(y, height=height_threshold, distance=5)

    # FWHM (in x units) using peak_widths at half maximum
    widths_res = peak_widths(y, peaks, rel_height=0.5)
    widths_pts = widths_res[0]  # width in number of samples
    
    if len(peaks) == 0:
        log("⚠ No peaks found")
        proc = pd.DataFrame({"x": x, "y_raw": y})
        proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)
        return proc, pd.DataFrame(), pd.DataFrame()
    
    # Step 2: Extract peak information
    fitted_data = []
    for peak_idx in peaks:
        x_peak = float(x[peak_idx])
        y_peak = float(y[peak_idx])

        # Convert width (points) -> x units (approx)
        try:
            dx = float(np.median(np.diff(x)))
            fwhm_x = float(widths_pts[list(peaks).index(peak_idx)] * dx)
        except Exception:
            fwhm_x = 0.0
        
        # Calculate Bandgap from wavelength (nm)
        # E(eV) = 1240.8 / λ(nm)
        bandgap_ev = 1240.8 / x_peak if x_peak > 0 else 0
        
        fitted_data.append({
            "center": x_peak,
            "height": y_peak,
            "bandgap_eV": bandgap_ev,
            "fwhm_x": fwhm_x,
            "peak_type": "Emission"
        })
    
    # Sort by intensity (descending)
    fitted = pd.DataFrame(fitted_data).sort_values("height", ascending=False).reset_index(drop=True)
    
    # Store main peak info
    if not fitted.empty:
        log(f"✓ Peak at {fitted.iloc[0]['center']:.1f}nm (E={fitted.iloc[0]['bandgap_eV']:.2f}eV)")
    
    # Save outputs
    proc = pd.DataFrame({"x": x, "y_raw": y})
    proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)
    fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)
    
    # Store metadata
    try:
        with open(os.path.join(outdir, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump({
                "technique": "PL",
                "n_peaks_found": len(fitted),
                "main_peak_wavelength_nm": float(fitted.iloc[0]["center"]) if not fitted.empty else None,
                "main_peak_bandgap_eV": float(fitted.iloc[0]["bandgap_eV"]) if not fitted.empty else None
            }, f, indent=2)
    except Exception:
        pass
    
    log("Done.")
    return proc, fitted, fitted

