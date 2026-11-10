"""Impedance window: equivalent-circuit fit with a Kramers-Kronig test.

Complex non-linear least squares with modulus weighting, circuit choice by
AICc, the linear Kramers-Kronig test of Schoenleber et al. and the
capacitance spectrum. All numbers come from `eis_core`.
"""
from __future__ import annotations

import numpy as np

from scripts.EIS import eis_core as core
from scripts.common import curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw, ref_line,
                                       run_standalone)


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "Impedance"
    SLUG = "eis"
    CORE = core
    FILE_HINT = ("Spectrum with frequency, Z' and Z'' columns. The sign convention of Z'' is detected; set it "
                 "by hand when the file stores -Z''.")
    FIELDS = [
        dict(key="model", label="Circuit", kind="choice", choices=["auto"] + list(core.MODELS), default="auto",
             group="Fit"),
        dict(key="convention", label="Imaginary column", kind="choice", choices=["auto", "Z''", "-Z''"],
             default="auto", group="Fit"),
        dict(key="f_min", label="Lowest frequency (Hz)", default="", optional=True, min=0.0, group="Fit"),
        dict(key="f_max", label="Highest frequency (Hz)", default="", optional=True, min=0.0, group="Fit"),
        dict(key="area_cm2", label="Area (cm²)", default=0.0, min=0.0, group="Device (optional)"),
        dict(key="thickness_nm", label="Thickness (nm)", default=0.0, min=0.0, group="Device (optional)"),
    ]
    VIEWS = ["Nyquist", "Bode", "Residuals", "Capacitance"]
    BATCH = curve_batch.batch_columns("eis")
    METHOD_SECTION = "20."
    NOTES = ("The circuit was fitted to Z' and Z'' together with modulus weighting; with 'auto' the valid circuit "
             "of lowest AICc was kept. The data were tested for Kramers-Kronig compliance with the linear test "
             "(Boukamp, J. Electrochem. Soc. 142, 1885 (1995); Schoenleber et al., Electrochim. Acta 131, 20 "
             "(2014)). The effective capacitance of a constant-phase element follows C = (Q R^(1-alpha))^(1/alpha) "
             "(Hsu and Mansfeld, Corrosion 57, 747 (2001)). Low-frequency arcs of perovskite cells are ionic and "
             "must not be read as a recombination resistance (von Hauff and Klotz, J. Mater. Chem. C 10, 742 "
             "(2022)).")

    # ---- data ----------------------------------------------------------------------
    def demo(self):
        f, zre, zim = core.simulate()
        return ("R(RQ)(RQ), two arcs, 0.3 % noise", {"f": f, "zre": zre, "zim": zim},
                {"model": "auto", "convention": "auto", "f_min": "", "f_max": ""})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        f, z = result["f"], result["z"]
        if view == "Bode":
            a1 = fig.add_subplot(211)
            a2 = fig.add_subplot(212, sharex=a1)
            for k, (name, _d, r) in enumerate(others):
                a1.loglog(r["f"], np.abs(r["z"]), **other_kw(k, name))
                a2.semilogx(r["f"], -np.degrees(np.angle(r["z"])), **other_kw(k, name))
            a1.loglog(f, np.abs(z), **data_kw(0, "measured", ms=3.5))
            a1.loglog(result["f_dense"], np.abs(result["z_dense"]), **fit_kw(result["model"]))
            a2.semilogx(f, -np.degrees(np.angle(z)), **data_kw(0, "measured", ms=3.5))
            a2.semilogx(result["f_dense"], -np.degrees(np.angle(result["z_dense"])), **fit_kw(result["model"]))
            a1.set_ylabel("|Z| (Ω)")
            a1.tick_params(labelbottom=False)
            a2.set_ylabel("-Phase (°)")
            a2.set_xlabel("Frequency (Hz)")
            legend(a1, "upper right")
            return
        if view == "Residuals":
            a1 = fig.add_subplot(211)
            a2 = fig.add_subplot(212, sharex=a1)
            kk = result["kk"]
            for ax, re, im, title in ((a1, kk["res_re_pct"], kk["res_im_pct"], "Kramers-Kronig test"),
                                      (a2, result["res_re_pct"], result["res_im_pct"], f"Fit, {result['model']}")):
                ax.semilogx(f, re, **data_kw(0, "Z'", line=True, ms=3))
                ax.semilogx(f, im, **data_kw(1, "Z''", line=True, ms=3))
                ax.axhline(0.0, color=_pal.PLOT_REF, lw=0.9, ls="--")
                ref_line(ax, y=1.0)
                ref_line(ax, y=-1.0)
                top = max(2.0, float(np.nanmax(np.abs(np.r_[re, im]))) * 1.15)
                ax.set_ylim(-top, top)
                ax.set_ylabel("Residual (% of |Z|)")
                note_box(ax, title, "upper left")
            a1.tick_params(labelbottom=False)
            note_box(a1, f"rms = {kk['rms_pct']:.2f} %,  M = {kk['M']}", "lower right")
            note_box(a2, f"rms = {result['rms_pct']:.2f} %", "lower right")
            a2.set_xlabel("Frequency (Hz)")
            legend(a1, "upper right")
            return
        ax = fig.add_subplot(111)
        if view == "Capacitance":
            c = np.asarray(result["C_spectrum_F"], float)
            scale, unit = (1.0 / result["area_cm2"], "F/cm²") if result["area_cm2"] > 0 else (1.0, "F")
            pos = c > 0
            if not pos.any():
                raise ValueError("the capacitance Im(1/Z)/omega is not positive anywhere in this spectrum")
            for k, (name, _d, r) in enumerate(others):
                co = np.asarray(r["C_spectrum_F"], float)
                ax.loglog(r["f"][co > 0], co[co > 0] * scale, **other_kw(k, name))
            ax.loglog(f[pos], c[pos] * scale, **data_kw(0, "C = Im(1/Z) / ω", line=True, ms=3.5))
            for i, arc in enumerate(result["arcs"]):
                if np.isfinite(arc.get("C_eff_F", np.nan)) and arc["C_eff_F"] > 0:
                    ax.axhline(arc["C_eff_F"] * scale, color=_pal.series_color(i + 1), lw=1.2, ls="--",
                               label=f"arc {i + 1}: C = {arc['C_eff_F'] * scale:.3g} {unit}")
            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel(f"Capacitance ({unit})")
            legend(ax, "upper right")
            return
        # Nyquist
        for k, (name, _d, r) in enumerate(others):
            ax.plot(r["z"].real, -r["z"].imag, **other_kw(k, name))
        ax.plot(z.real, -z.imag, **data_kw(0, "measured"))
        zd = result["z_dense"]
        ax.plot(zd.real, -zd.imag, **fit_kw(result["model"]))
        for i, arc in enumerate(result["arcs"]):
            fp = arc.get("f_peak_Hz", np.nan)
            if np.isfinite(fp) and f.min() <= fp <= f.max():
                k = int(np.argmin(np.abs(np.log(result["f_dense"] / fp))))
                ax.annotate(f"{fp:.3g} Hz", xy=(zd.real[k], -zd.imag[k]), xytext=(0, 10),
                            textcoords="offset points", ha="center", fontsize=8.5, color=_pal.PLOT_TICK,
                            arrowprops=dict(arrowstyle="-", color=_pal.PLOT_REF, lw=0.8))
        lines = [f"Rs = {result['Rs']:.3g} Ω"]
        for i, arc in enumerate(result["arcs"]):
            lines.append(f"R{i + 1} = {arc['R']:.3g} Ω,  C{i + 1} = {arc['C_eff_F']:.2e} F")
        lines.append(f"fit rms = {result['rms_pct']:.2f} %")
        note_box(ax, "\n".join(lines), "upper right")
        ax.set_xlabel("Z' (Ω)")
        ax.set_ylabel("-Z'' (Ω)")
        ax.set_aspect("equal", adjustable="datalim")
        legend(ax, "upper left")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
