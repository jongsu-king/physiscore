"""TRPL window: tail fit of a photoluminescence decay.

Mono-, bi-, tri-exponential or stretched-exponential model with Poisson
weights for counting data, model choice by AICc, amplitude- and
intensity-weighted mean lifetimes, the differential lifetime and, with an
entered mobility, the diffusion length. All numbers come from `trpl_core`.
"""
from __future__ import annotations

import numpy as np

from scripts.TRPL import trpl_core as core
from scripts.common import curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw, ref_line,
                                       run_standalone)

_NAMES = {"exp1": "mono-exponential", "exp2": "bi-exponential", "exp3": "tri-exponential",
          "stretched": "stretched exponential"}


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "TRPL"
    SLUG = "trpl"
    CORE = core
    FILE_HINT = ("Decay trace with a time column and a counts (or intensity) column. The fit starts at the peak; "
                 "'Skip after peak' moves the start past the instrument response.")
    FIELDS = [
        dict(key="model", label="Model", kind="choice", choices=["auto"] + list(core.MODELS), default="auto",
             group="Fit"),
        dict(key="background", label="Background", kind="text", default="auto", group="Fit"),
        dict(key="skip", label="Skip after peak", default=0.0, min=0.0, group="Fit"),
        dict(key="t_end", label="Fit until", default="", optional=True, group="Fit"),
        dict(key="time_unit", label="Time unit", kind="choice", choices=list(core.TIME_UNITS), default="ns",
             group="Fit"),
        dict(key="irf_fwhm", label="IRF FWHM", default=0.0, min=0.0, group="Fit"),
        dict(key="mobility_cm2_Vs", label="Mobility (cm²/Vs)", default=0.0, min=0.0, group="Diffusion length"),
        dict(key="temperature_k", label="Temperature (K)", default=300.0, min=1.0, group="Diffusion length"),
    ]
    VIEWS = ["Decay (log)", "Decay (linear)", "Differential lifetime", "Components"]
    BATCH = curve_batch.batch_columns("trpl")
    METHOD_SECTION = "19."
    NOTES = ("The decay was fitted from the peak (plus the entered skip) with Poisson weights for counting data; "
             "the model was chosen by the corrected Akaike criterion among the valid fits when 'auto' was "
             "selected. <tau> amplitude weighted = sum(A_i tau_i) / sum(A_i); intensity weighted = "
             "sum(A_i tau_i^2) / sum(A_i tau_i) (Lakowicz, Principles of Fluorescence Spectroscopy, 3rd ed., "
             "ch. 4). The differential lifetime is -1 / (d ln I / dt) (Kirchartz et al., Adv. Energy Mater. 10, "
             "1904134 (2020)); no reconvolution with the instrument response is performed.")

    # ---- data ----------------------------------------------------------------------
    def demo(self):
        t, y = core.simulate()
        return ("bi-exponential, 5 ns (70 %) and 80 ns (30 %), 10 000 counts", {"t": t, "y": y},
                {"model": "auto", "background": "auto", "skip": 0.0, "t_end": "", "time_unit": "ns"})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        u = result["time_unit"]
        t, y, mask = result["t"], result["y"], np.asarray(result["mask"], bool)
        if view == "Differential lifetime":
            ax = fig.add_subplot(111)
            td, tau = result["tau_diff"]
            if not len(td):
                raise ValueError("the decay is too short or too noisy for a differential lifetime")
            ax.plot(td, tau, **data_kw(0, "differential lifetime", line=True, ms=3))
            if np.isfinite(result["tau_diff_late"]):
                ref_line(ax, y=result["tau_diff_late"], text=f"late value {result['tau_diff_late']:.3g} {u}", side="left")
            ax.set_xlabel(f"Time after the peak ({u})")
            ax.set_ylabel(f"-1 / (d ln I / dt)  ({u})")
            ax.set_ylim(bottom=0)
            legend(ax, "lower right")
            return
        if view == "Components":
            ax = fig.add_subplot(111)
            pos = mask & (y > 0)
            ax.semilogy(t[pos], y[pos], **data_kw(0, "measured", ms=3))
            tt = result["t_fit"]
            taus, amps = np.atleast_1d(result["taus"]), np.atleast_1d(result["amps"])
            if result["model"] != "stretched":
                for i, (a, tau) in enumerate(zip(amps, taus)):
                    ax.semilogy(tt, a * np.exp(-tt / tau), color=_pal.series_color(i + 1), lw=1.4, ls="--",
                                label=f"tau{i + 1} = {tau:.3g} {u}")
            ax.semilogy(tt, result["fit"], **fit_kw("sum"))
            ax.set_ylim(max(result["noise_floor"] * 0.3, float(y[pos].min()) * 0.5), float(y.max()) * 2.0)
            ax.set_xlabel(f"Time after the peak ({u})")
            ax.set_ylabel("Signal - background")
            legend(ax, "upper right")
            return
        gs = fig.add_gridspec(2, 1, height_ratios=[3.4, 1.0], hspace=0.06)
        ax = fig.add_subplot(gs[0])
        rx = fig.add_subplot(gs[1], sharex=ax)
        log = view == "Decay (log)"
        plot = ax.semilogy if log else ax.plot
        for k, (name, _d, r) in enumerate(others):
            sel = r["y"] > 0 if log else np.ones(len(r["y"]), bool)
            plot(r["t"][sel], r["y"][sel] / max(r["peak"], 1e-300) * result["peak"], **other_kw(k, name))
        shown = (y > 0) if log else np.ones(len(y), bool)
        plot(t[shown & ~mask], y[shown & ~mask], ls="none", marker="o", ms=3, mfc="none", mec=_pal.PLOT_REF,
             label="outside the fit window")
        plot(t[shown & mask], y[shown & mask], **data_kw(0, "measured", ms=3))
        plot(result["t_fit"], result["fit"], **fit_kw(_NAMES.get(result["model"], result["model"])))
        if log:
            ref_line(ax, y=result["noise_floor"], text="noise floor", side="right")
            ax.set_ylim(result["noise_floor"] * 0.3, float(y.max()) * 2.0)
        lines = []
        taus = np.atleast_1d(result["taus"])
        fr = np.atleast_1d(result["amp_fracs"])
        for i, tau in enumerate(taus):
            lines.append(f"tau{i + 1} = {tau:.3g} {u}" + (f"  ({100 * fr[i]:.0f} %)" if len(taus) > 1 else ""))
        if result["model"] == "stretched":
            lines.append(f"beta = {result['beta']:.2f}")
        if len(taus) > 1 or result["model"] == "stretched":
            lines.append(f"<tau> = {result['tau_amp']:.3g} {u}")
        lines.append(f"chi² red. = {result['chi2_red']:.2f}")
        note_box(ax, "\n".join(lines), "upper right")
        ax.set_ylabel("Counts - background" if result["counts"] else "Signal - background")
        ax.tick_params(labelbottom=False)
        legend(ax, "lower left" if log else "center right")
        rx.plot(result["t_fit"], result["residuals"], color=_pal.series_color(0), lw=0.8)
        rx.axhline(0.0, color=_pal.PLOT_REF, lw=0.9, ls="--")
        lim = max(3.5, float(np.nanpercentile(np.abs(result["residuals"]), 99)) * 1.2)
        rx.set_ylim(-lim, lim)
        rx.set_ylabel("Residual / σ")
        rx.set_xlabel(f"Time after the peak ({u})")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
