"""Stability window: T80, burn-in, Ts80 and the long-term loss rate of an
ageing trace (PCE, or any figure of merit, against time).

Following the ISOS consensus statement the lifetime is reported as measured
when the threshold was crossed and as an extrapolation - labelled as such -
when it was not. All numbers come from `stability_core`.
"""
from __future__ import annotations

import numpy as np

from scripts.Stability import stability_core as core
from scripts.common import curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw, ref_line,
                                       run_standalone)


def _hours(x: float) -> str:
    if not np.isfinite(x):
        return "beyond the extrapolation range" if x == np.inf else "-"
    return f"{x:.0f} h" if x >= 100 else f"{x:.3g} h"


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "Stability"
    SLUG = "stability"
    CORE = core
    FILE_HINT = ("Trace with a time column and a PCE (or normalised output) column. State the protocol so "
                 "that it travels with the result.")
    FIELDS = [
        dict(key="time_unit", label="Time unit", kind="choice", choices=list(core.TIME_TO_HOURS), default="h",
             group="Trace"),
        dict(key="norm", label="Normalise to", kind="choice", choices=["initial", "maximum", "none"],
             default="initial", group="Trace"),
        dict(key="n_initial", label="Initial points averaged", kind="int", default=1, min=1, max=1000,
             group="Trace"),
        dict(key="threshold", label="Threshold (fraction)", default=0.8, min=0.05, max=0.99, group="Trace"),
        dict(key="model", label="Model", kind="choice", choices=["auto"] + list(core.MODELS), default="auto",
             group="Model"),
        dict(key="protocol", label="Protocol", kind="choice", choices=list(core.PROTOCOLS), default="not stated",
             group="Model"),
    ]
    VIEWS = ["Normalised", "Raw", "Residuals"]
    BATCH = curve_batch.batch_columns("stability")
    METHOD_SECTION = "22."
    NOTES = ("The trace was normalised as stated and the threshold time read from the data by linear "
             "interpolation; when the threshold was not reached the fitted model was extrapolated and the value "
             "is labelled as an extrapolation. With a burn-in, the stabilised time t_s is three time constants "
             "of the fast component and Ts is counted from there (Khenkin et al., Nat. Energy 5, 35 (2020); "
             "Roesch et al., Adv. Energy Mater. 5, 1501407 (2015)). Reversible losses recover in the dark and "
             "must be separated from permanent degradation (Domanski et al., Nat. Energy 3, 61 (2018)).")

    # ---- data ----------------------------------------------------------------------
    def demo(self):
        t, y = core.simulate()
        return ("burn-in 12 % (tau 40 h), then 10 % per 1000 h, 1000 h", {"t": t, "y": y},
                {"time_unit": "h", "norm": "initial", "n_initial": 1, "threshold": 0.8, "model": "auto"})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        ax = fig.add_subplot(111)
        t, e = result["t"], result["e"]
        if view == "Raw":
            for k, (name, _d, r) in enumerate(others):
                ax.plot(r["t"], r["raw"], **other_kw(k, name))
            ax.plot(t, result["raw"], **data_kw(0, "measured", ms=3.5))
            ax.plot(result["t_dense"], result["fit_dense"] * result["reference"], **fit_kw(result["model"]))
            ax.set_xlabel("Time (h)")
            ax.set_ylabel("Output (as measured)")
            legend(ax, "upper right")
            return
        if view == "Residuals":
            res = 100.0 * (e - core.model_curve(result["model"], result["p"], t))
            ax.plot(t, res, **data_kw(0, "measured - model", line=True, ms=3.5))
            ax.axhline(0.0, color=_pal.PLOT_REF, lw=0.9, ls="--")
            lim = max(1.0, float(np.nanmax(np.abs(res))) * 1.2)
            ax.set_ylim(-lim, lim)
            note_box(ax, f"{result['model']}\nrmse = {100 * result['rmse']:.2f} %", "upper right")
            ax.set_xlabel("Time (h)")
            ax.set_ylabel("Residual (% of the reference)")
            return
        for k, (name, _d, r) in enumerate(others):
            ax.plot(r["t"], r["e"], **other_kw(k, name))
        ax.plot(t, e, **data_kw(0, "measured", ms=3.5))
        ax.plot(result["t_dense"], result["fit_dense"], **fit_kw(result["model"]))
        thr = result["threshold"]
        ref_line(ax, y=thr, text=f"{100 * thr:.0f} % of the reference", side="left")
        name = f"T{100 * thr:.0f}"
        lines = []
        if result["T_reached"]:
            ax.axvline(result["T_measured"], color=_pal.RED, lw=1.0, ls=":")
            lines.append(f"{name} = {_hours(result['T_measured'])} (measured)")
        else:
            lines.append(f"{name} not reached in {_hours(result['duration_h'])}")
            lines.append(f"{name} = {_hours(result['T_extrapolated'])} (extrapolated)")
        if result["burn_in"]:
            ax.axvline(result["t_s"], color=_pal.ORANGE, lw=1.0, ls=":")
            ax.plot([result["t_s"]], [result["E_s"]], ls="none", marker="s", ms=6, mfc=_pal.ORANGE,
                    mec=_pal.ORANGE, label="end of burn-in (t_s)")
            ts = result["Ts_measured"] if result["Ts_reached"] else result["Ts_extrapolated"]
            lines.append(f"burn-in loss = {result['burn_in_loss_pct']:.1f} %")
            lines.append(f"Ts{100 * thr:.0f} = {_hours(ts)}" + (" (measured)" if result["Ts_reached"]
                                                               else " (extrapolated)"))
        if np.isfinite(result["rate_pct_per_1000h"]):
            lines.append(f"rate = {result['rate_pct_per_1000h']:.2f} % / 1000 h")
        if result["protocol"] != "not stated":
            lines.append(result["protocol"])
        note_box(ax, "\n".join(lines), "upper right")
        ax.set_ylim(min(float(e.min()), thr) - 0.05, max(1.05, float(e.max()) + 0.03))
        ax.set_xlabel("Time (h)")
        ax.set_ylabel("Normalised output")
        legend(ax, "lower left")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
