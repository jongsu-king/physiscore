"""SCLC window: dark J-V of a single-carrier device.

Regimes are found from the local slope d log J / d log V; the trap density
comes from the trap-filled-limit voltage and the mobility from the
Mott-Gurney law in the Child regime. All numbers come from `sclc_core`.
"""
from __future__ import annotations

import numpy as np

from scripts.SCLC import sclc_core as core
from scripts.common import app_config, curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw, ref_line,
                                       run_standalone)

_REGIMES = (("ohmic", "Ohmic", "GREEN"), ("tfl", "Trap filling", "ORANGE"), ("child", "Child (SCLC)", "RED"))


def _finite(x) -> bool:
    try:
        return bool(np.isfinite(x))
    except TypeError:
        return False


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "SCLC"
    SLUG = "sclc"
    CORE = core
    FILE_HINT = ("Dark J-V of an electron-only or hole-only device: a source-meter export or a table with "
                 "voltage and current (or current density) columns.")
    FIELDS = [
        dict(key="thickness_nm", label="Thickness (nm)", default=500.0, min=1.0, group="Device"),
        dict(key="eps_r", label="Relative permittivity", default=25.0, min=1.0, group="Device"),
        dict(key="area_cm2", label="Area (cm²)", default=app_config.cell_area_cm2, min=1e-6, group="Device"),
        dict(key="temperature_k", label="Temperature (K)", default=300.0, min=1.0, group="Device"),
        dict(key="branch", label="Polarity", kind="choice", choices=["auto", "positive", "negative"],
             default="auto", group="Analysis"),
        dict(key="sweep", label="Sweep", kind="choice", choices=["up", "down", "all"], default="up",
             group="Analysis"),
        dict(key="v_bi", label="Built-in voltage (V)", default=0.0, group="Analysis"),
        dict(key="window", label="Slope window (points)", kind="int", default=5, min=3, max=25, group="Analysis"),
        dict(key="field_dependent", label="Field-dependent mobility (Murgatroyd)", kind="bool", default=False,
             group="Analysis"),
    ]
    VIEWS = ["log J - log V", "Local slope", "Mott-Gurney"]
    BATCH = curve_batch.batch_columns("sclc")
    METHOD_SECTION = "17."
    NOTES = ("Regimes were assigned from the local slope d log J / d log V (Ohmic 0.7-1.35, Child 1.65-2.45, "
             "trap filling above 2.6). The trap density follows n_t = 2 eps eps0 V_TFL / (q L^2) and the mobility "
             "the Mott-Gurney law J = 9/8 eps eps0 mu V^2 / L^3 fitted in the Child regime. In mixed "
             "ionic-electronic conductors both numbers are upper-level estimates (Duijnstee et al., ACS Energy "
             "Lett. 5, 376 (2020); Le Corre et al., ACS Energy Lett. 6, 1087 (2021)).")

    # ---- data ----------------------------------------------------------------------
    def demo(self):
        v, j = core.simulate(thickness_nm=500.0, eps_r=25.0, mobility_cm2_Vs=1.0, n_t_cm3=5e16, n0_cm3=1e13)
        return ("single-carrier device, n_t = 5e16 cm-3, mu = 1 cm2/Vs", {"v": v, "j": j},
                {"thickness_nm": 500.0, "eps_r": 25.0, "branch": "auto", "sweep": "up", "v_bi": 0.0})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        ax = fig.add_subplot(111)
        v, j = result["v"], result["j"]
        if view == "Local slope":
            for k, (name, _d, r) in enumerate(others):
                ax.semilogx(r["v"], r["local_slope"], **other_kw(k, name))
            ax.semilogx(v, result["local_slope"], **data_kw(0, "local slope", line=True))
            for key, label, colour in _REGIMES:
                reg = result.get(key)
                if reg:
                    ax.axvspan(reg["v_lo"], reg["v_hi"], color=getattr(_pal, colour), alpha=0.10, lw=0, label=label)
            ref_line(ax, y=1.0, text="1  Ohmic")
            ref_line(ax, y=2.0, text="2  Child")
            ax.set_xlabel("Voltage (V)")
            ax.set_ylabel("d log J / d log V")
            top = np.nanmax(result["local_slope"]) if np.isfinite(result["local_slope"]).any() else 3.0
            ax.set_ylim(0, max(3.0, float(top) * 1.1))
            legend(ax, "upper left")
            return
        if view == "Mott-Gurney":
            ax.plot(v ** 2, j, **data_kw(0, "measured"))
            reg, mu = result.get("child"), result.get("mobility_cm2_Vs")
            if reg and _finite(mu):
                i0, i1 = int(reg["i0"]), int(reg["i1"]) + 1
                ax.plot(v[i0:i1] ** 2, j[i0:i1], **data_kw(0, "Child regime", hollow=False))
                length = result["thickness_nm"] * 1e-9
                x = np.linspace(0.0, float(v.max()) ** 2, 100)
                ax.plot(x, 9.0 / 8.0 * core.EPS0 * result["eps_r"] * (mu * 1e-4) * x / length ** 3 / 10.0,
                        **fit_kw("Mott-Gurney law"))
                note_box(ax, f"mu = {mu:.3g} cm²/Vs", "lower right")
            else:
                note_box(ax, "No Child regime (slope 2) was found", "lower right")
            ax.set_xlabel("V² (V²)")
            ax.set_ylabel("J (mA/cm²)")
            legend(ax, "upper left")
            return
        for k, (name, _d, r) in enumerate(others):
            ax.loglog(r["v"], r["j"], **other_kw(k, name))
        ax.loglog(v, j, **data_kw(0, "measured"))
        for key, label, colour in _REGIMES:
            reg = result.get(key)
            if not reg:
                continue
            x = np.logspace(np.log10(reg["v_lo"] / 1.7), np.log10(reg["v_hi"] * 1.7), 40)
            ax.loglog(x, 10.0 ** (reg["intercept"] + reg["slope"] * np.log10(x)),
                      **fit_kw(f"{label}, slope {reg['slope']:.2f}", color=getattr(_pal, colour)))
        if _finite(result.get("V_TFL")):
            ref_line(ax, x=result["V_TFL"], text="V_TFL")
        lines = []
        if _finite(result.get("V_TFL")):
            lines.append(f"V_TFL = {result['V_TFL']:.3g} V")
        if _finite(result.get("n_t_cm3")):
            lines.append(f"n_t = {result['n_t_cm3']:.2e} cm$^{{-3}}$")
        if _finite(result.get("mobility_cm2_Vs")):
            lines.append(f"mu = {result['mobility_cm2_Vs']:.3g} cm²/Vs")
        if lines:
            note_box(ax, "\n".join(lines), "lower right")
        ax.set_xlabel("Voltage (V)")
        ax.set_ylabel("J (mA/cm²)")
        legend(ax, "upper left")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
