"""C-V window: Mott-Schottky analysis.

The linear part of 1/C^2 against voltage gives the apparent doping density
and the built-in voltage; the profile N(W) and the resolution limit of a thin
film show whether the number is a doping density at all. All numbers come
from `cv_core`.
"""
from __future__ import annotations

import numpy as np

from scripts.CV import cv_core as core
from scripts.common import app_config, curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw, ref_line,
                                       run_standalone)


def _scale(c_max: float):
    """Capacitance scale for the axis: (factor, unit)."""
    for factor, unit in ((1e12, "pF"), (1e9, "nF"), (1e6, "µF"), (1e3, "mF")):
        if c_max * factor < 1e3:
            return factor, unit
    return 1.0, "F"


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "C-V (Mott-Schottky)"
    SLUG = "cv"
    CORE = core
    FILE_HINT = ("Table with a voltage and a capacitance column, measured in the dark at one frequency. "
                 "Enter the thickness to test the result against the resolution limit of the film.")
    FIELDS = [
        dict(key="area_cm2", label="Area (cm²)", default=app_config.cell_area_cm2, min=1e-6, group="Device"),
        dict(key="eps_r", label="Relative permittivity", default=25.0, min=1.0, group="Device"),
        dict(key="thickness_nm", label="Thickness (nm)", default=0.0, min=0.0, group="Device"),
        dict(key="temperature_k", label="Temperature (K)", default=300.0, min=1.0, group="Device"),
        dict(key="c_unit", label="Capacitance unit", kind="choice", choices=["F", "mF", "uF", "nF", "pF"],
             default="F", group="Analysis"),
        dict(key="m", label="Resolution factor m", default=2.0, min=1.0, group="Analysis"),
        dict(key="v_min", label="Fit from (V)", default="", optional=True, group="Analysis"),
        dict(key="v_max", label="Fit to (V)", default="", optional=True, group="Analysis"),
    ]
    VIEWS = ["Mott-Schottky", "C-V", "Doping profile"]
    BATCH = curve_batch.batch_columns("cv")
    METHOD_SECTION = "21."
    NOTES = ("N = 2 / (q eps eps0 A^2 |d(1/C^2)/dV|) over the linear part of the Mott-Schottky plot, "
             "V_bi = intercept + kT/q, and the profile N(W) with W = eps eps0 A / C. A film of thickness d "
             "cannot resolve densities below N_min = m^2 2 eps eps0 kT / (q^2 d^2) (Kirchartz et al., J. Phys. "
             "Chem. C 116, 7672 (2012); Ravishankar, Unold and Kirchartz, Science 371, eabd8014 (2021)); an "
             "apparent density near that limit is the geometric capacitance and not a doping density. "
             "Injection capacitance at forward bias mimics a Mott-Schottky slope (Almora et al., Appl. Phys. "
             "Lett. 109, 173903 (2016)).")

    # ---- data ----------------------------------------------------------------------
    def demo(self):
        v, c = core.simulate(n_cm3=1e17, v_bi=0.9, eps_r=25.0, area_cm2=0.1)
        return ("one-sided junction, N = 1e17 cm-3, V_bi = 0.9 V", {"v": v, "c": c},
                {"area_cm2": 0.1, "eps_r": 25.0, "thickness_nm": 0.0, "c_unit": "F", "v_min": "", "v_max": ""})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        ax = fig.add_subplot(111)
        v, win = result["v"], result.get("window")
        sign = "" if result["polarity"] > 0 else "  (axis reversed: forward bias positive)"
        if view == "C-V":
            factor, unit = _scale(float(result["c"].max()))
            for k, (name, _d, r) in enumerate(others):
                ax.plot(r["v"], r["c"] * factor, **other_kw(k, name))
            ax.plot(v, result["c"] * factor, **data_kw(0, "measured", line=True))
            if np.isfinite(result["C_geo_F"]):
                ref_line(ax, y=result["C_geo_F"] * factor, text="geometric capacitance")
            ax.set_xlabel("Voltage (V)" + sign)
            ax.set_ylabel(f"Capacitance ({unit})")
            legend(ax, "upper left")
            return
        if view == "Doping profile":
            w, n = result["w_nm"], result["n_profile_cm3"]
            ok = np.isfinite(n) & (n > 0)
            if not ok.any():
                raise ValueError("1/C² does not fall with voltage anywhere, so there is no profile")
            ax.semilogy(w[ok], n[ok], **data_kw(0, "N(W)", line=True))
            if np.isfinite(result["N_cm3"]):
                ax.axhline(result["N_cm3"], color=_pal.RED, lw=1.5, label="Mott-Schottky slope")
            if np.isfinite(result["N_min_cm3"]):
                ref_line(ax, y=result["N_min_cm3"], text="resolution limit of the film")
            lo, hi = result["W_window_nm"]
            if np.isfinite(lo):
                ax.axvspan(lo, hi, color=_pal.ACCENT, alpha=0.10, lw=0, label="fit window")
            if result["thickness_nm"] > 0:
                ref_line(ax, x=result["thickness_nm"], text="film thickness")
            lo_n, hi_n = float(n[ok].min()), float(n[ok].max())
            if hi_n / lo_n < 30.0:                   # a flat profile still gets a readable decade scale
                mid = np.sqrt(lo_n * hi_n)
                ax.set_ylim(mid / 10.0, mid * 10.0)
            ax.set_xlabel(r"Profiling depth $W = \varepsilon\varepsilon_0 A/C$ (nm)")
            ax.set_ylabel(r"Apparent density (cm$^{-3}$)")
            legend(ax, "upper right")
            return
        # Mott-Schottky
        y = result["inv_c2"]
        scale = 10.0 ** -np.floor(np.log10(float(y.max())))
        expo = int(round(-np.log10(scale)))
        for k, (name, _d, r) in enumerate(others):
            ax.plot(r["v"], r["inv_c2"] * scale, **other_kw(k, name))
        ax.plot(v, y * scale, **data_kw(0, "measured"))
        if win is not None:
            i0, i1 = int(win["i0"]), int(win["i1"])
            ax.plot(v[i0:i1], y[i0:i1] * scale, **data_kw(0, "fit window", hollow=False))
            x1 = result["V_intercept"] if np.isfinite(result["V_intercept"]) else float(v[i1 - 1])
            x = np.linspace(float(v[i0]), max(x1, float(v[i1 - 1])), 50)
            ax.plot(x, (win["intercept"] + win["slope"] * x) * scale, **fit_kw("linear fit"))
            lines = []
            if np.isfinite(result["N_cm3"]):
                lines.append(f"N = {result['N_cm3']:.2e} cm$^{{-3}}$")
                lines.append(f"V_bi = {result['V_bi']:.3f} V")
            lines.append(f"R² = {win['r2']:.4f}")
            note_box(ax, "\n".join(lines), "upper right")
        else:
            note_box(ax, "No linear region was found", "upper right")
        ax.axhline(0.0, color=_pal.PLOT_REF, lw=0.9, ls="--")
        ax.set_ylim(bottom=min(0.0, float(y.min() * scale)) - 0.02 * float(y.max() * scale))
        ax.set_xlabel("Voltage (V)" + sign)
        ax.set_ylabel(rf"$1/C^2$ ($10^{{{expo}}}$ F$^{{-2}}$)")
        legend(ax, "lower left")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
