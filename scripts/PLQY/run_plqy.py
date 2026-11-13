"""PLQY and QFLS window: absolute photoluminescence quantum yield from
integrating-sphere spectra (de Mello), or a PLQY series against intensity;
the quasi-Fermi-level splitting, the non-radiative loss, the implied ideality
factor and the implied J-V curve. All numbers come from `plqy_core`.
"""
from __future__ import annotations

from tkinter import filedialog

import numpy as np

from scripts.PLQY import plqy_core as core
from scripts.common import curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (EXAMPLE_PREFIX, CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw,
                                       ref_line, run_standalone)

_SERIES_ONLY = "an intensity series (several excitation intensities) is needed for this view"


def _vrad(result, suns):
    """Radiative-limit voltage kT ln(X J_G / J0 + 1) at the intensities `suns`."""
    j0, jg = result["J0_rad"], result["J_G_1sun"]
    if not (np.isfinite(j0) and np.isfinite(jg) and j0 > 0):
        return None
    kt = core.KB_EV * result["temperature_K"]
    return kt * np.log(np.asarray(suns, float) * jg / j0 + 1.0)


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "PLQY and QFLS"
    SLUG = "plqy"
    CORE = core
    FILE_HINT = ("Integrating-sphere spectra: wavelength, A (empty sphere), B (sample out of the beam, optional), "
                 "C (sample in the beam), named or in that order. Or a series: intensity and PLQY columns "
                 "(Voc, Jsc, FF optional). For the QFLS give the EQE of the same stack, its band gap or J0,rad.")
    FIELDS = [
        dict(key="input", label="File holds", kind="choice", choices=list(core.INPUTS), default="auto", group="Input"),
        dict(key="units", label="Spectra in", kind="choice", choices=list(core.SPECTRUM_UNITS), default="photons",
             group="Integrating sphere"),
        dict(key="laser_lo", label="Laser window from (nm)", default="", optional=True, group="Integrating sphere"),
        dict(key="laser_hi", label="Laser window to (nm)", default="", optional=True, group="Integrating sphere"),
        dict(key="em_lo", label="Emission from (nm)", default="", optional=True, group="Integrating sphere"),
        dict(key="em_hi", label="Emission to (nm)", default="", optional=True, group="Integrating sphere"),
        dict(key="power_mw_cm2", label="Laser power (mW/cm²)", default=0.0, min=0.0, group="Integrating sphere"),
        dict(key="excitation_suns", label="Else excitation (suns)", default=1.0, min=1e-9, group="Integrating sphere"),
        dict(key="voc_v", label="Device Voc (V)", default="", optional=True, group="Integrating sphere"),
        dict(key="intensity_unit", label="Intensity unit", kind="choice", choices=list(core.INTENSITY_UNITS),
             default="suns", group="Series"),
        dict(key="i_min", label="Lowest intensity", default="", optional=True, group="Series"),
        dict(key="i_max", label="Highest intensity", default="", optional=True, group="Series"),
        dict(key="radiative", label="J0,rad from", kind="choice", choices=list(core.RADIATIVE), default="none",
             group="QFLS"),
        dict(key="eqe_file", label="EQE file", kind="text", default="", group="QFLS"),
        dict(key="eg_ev", label="Band gap (eV)", default=0.0, min=0.0, group="QFLS"),
        dict(key="j0_rad", label="J0,rad (mA/cm²)", default=0.0, min=0.0, group="QFLS"),
        dict(key="jsc_1sun", label="One-sun J_G (mA/cm², 0 = ref.)", default=0.0, min=0.0, group="QFLS"),
        dict(key="temperature_k", label="Temperature (K)", default=300.0, min=1.0, group="QFLS"),
    ]
    VIEWS = ["PLQY", "QFLS", "Implied J-V", "Voltage losses"]
    BATCH = curve_batch.batch_columns("plqy")
    METHOD_SECTION = "24."
    NOTES = ("PLQY by the three-measurement method of de Mello, Wittmann and Friend (Adv. Mater. 9, 230 (1997)): "
             "A = 1 - L_C/L_B, PLQY = [P_C - (1 - A) P_B]/(L_A A), with the empty-sphere spectrum subtracted in the "
             "emission window. The quasi-Fermi-level splitting follows from detailed balance, QFLS = kT ln(PLQY J_G / "
             "J0,rad) (Ross, J. Chem. Phys. 46, 4590 (1967)); the non-radiative loss is -kT ln(PLQY). Over an "
             "intensity series the slope of QFLS against ln(intensity) is the implied ideality factor and the points "
             "(QFLS(X)/q, J_G(1 - X)) form the implied J-V curve (Stolterfoht et al., Nat. Energy 3, 847 (2018)); "
             "QFLS/q - Voc is the voltage lost at the contacts (Caprioglio et al., Adv. Energy Mater. 9, 1901631 "
             "(2019)).")

    # ---- data ----------------------------------------------------------------------
    _EXAMPLE_PARAMS = {"input": "auto", "radiative": "j0", "j0_rad": 1e-21, "jsc_1sun": 24.0, "eg_ev": 0.0,
                       "eqe_file": "", "intensity_unit": "suns", "i_min": "", "i_max": "", "units": "photons",
                       "laser_lo": "", "laser_hi": "", "em_lo": "", "em_hi": "", "power_mw_cm2": 0.0,
                       "excitation_suns": 1.0, "voc_v": ""}

    def demo(self):
        d = core.simulate_series()
        data = {"_kind": "series", "intensity": d["intensity"], "plqy": d["plqy"], "voc": d["voc"],
                "jsc": d["jsc"], "ff": d["ff"], "_columns": {"intensity": "suns", "plqy": "PLQY", "voc": "Voc",
                                                            "jsc": "Jsc", "ff": "FF"}}
        return ("PLQY series, 2 % at 1 sun, n_id 1.3, Voc 30 mV below the QFLS", data, dict(self._EXAMPLE_PARAMS))

    def load_example(self):
        """Two examples: integrating-sphere spectra and an intensity series."""
        name, data, params = self.demo()
        for k, v in params.items():
            self.set_param(k, v)
        s = core.simulate_sphere()
        self.add_memory(EXAMPLE_PREFIX, "integrating sphere, PLQY 5 %, absorptance 80 %",
                        {"_kind": "sphere", "wl": s["wl"], "a": s["a"], "b": s["b"], "c": s["c"],
                         "_columns": {"wl": "nm", "a": "A empty", "b": "B out of beam", "c": "C in beam"}})
        self.add_memory(EXAMPLE_PREFIX, name, data)
        self.run()

    def open_actions(self):
        return [("EQE file for J0,rad...", self.choose_eqe)]

    def choose_eqe(self):
        """The EQE (or absorptance) of the same stack, for J0,rad and the one-sun generation current."""
        path = filedialog.askopenfilename(parent=self, title="PLQY: EQE or absorptance of the stack",
                                          initialdir=self.directory_path or None,
                                          filetypes=[("Data files", "*.csv *.txt *.dat *.tsv *.xlsx *.xls"),
                                                     ("All files", "*.*")])
        if not path:
            return
        self.set_param("eqe_file", path)
        self.set_param("radiative", "eqe")

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        ax = fig.add_subplot(111)
        series = result["kind"] == "series"
        if view == "PLQY":
            if not series:
                self._draw_sphere(ax, result)
                return
            for k, (name, _d, r) in enumerate(others):
                if r["kind"] == "series":
                    ax.loglog(r["suns"], 100.0 * r["plqy"], **other_kw(k, name))
            m = np.asarray(result["fit_mask"], bool)
            x, y = result["suns"], 100.0 * result["plqy"]
            ax.loglog(x[m], y[m], **data_kw(0, "PLQY"))
            if (~m).any():
                ax.loglog(x[~m], y[~m], **data_kw(0, "not fitted", hollow=False, ms=3))
            k_exp = result["plqy_exponent"]
            if np.isfinite(k_exp) and m.sum() >= 3:
                xx = np.geomspace(x[m].min(), x[m].max(), 50)
                b = np.mean(np.log(y[m]) - k_exp * np.log(x[m]))
                ax.loglog(xx, np.exp(b) * xx ** k_exp, **fit_kw(f"slope {k_exp:.3f}"))
            ref_line(ax, x=1.0, text="1 sun")
            lines = [f"PLQY(1 sun) = {100 * result['PLQY_1sun']:.3g} %" if np.isfinite(result["PLQY_1sun"]) else
                     f"PLQY = {100 * result['PLQY_ref']:.3g} % at {result['suns_ref']:.3g} sun",
                     f"-kT ln PLQY = {1000 * result['dV_nr_ref']:.0f} mV"]
            note_box(ax, "\n".join(lines), "lower right")
            ax.set_xlabel("Excitation (suns)")
            ax.set_ylabel("PLQY (%)")
            legend(ax, "upper left")
            return
        if view == "QFLS":
            q = np.asarray(result["qfls"], float)
            if not np.isfinite(q).any():
                raise ValueError("no QFLS: choose how J0,rad is obtained (EQE file, band gap or J0,rad)")
            x = np.asarray(result["suns"], float)
            for k, (name, _d, r) in enumerate(others):
                if np.isfinite(np.asarray(r["qfls"], float)).any():
                    ax.semilogx(r["suns"], r["qfls"], **other_kw(k, name))
            ax.semilogx(x, q, **data_kw(0, "QFLS / q"))
            voc = np.asarray(result["voc"], float)
            if np.isfinite(voc).any():
                ax.semilogx(x, voc, **data_kw(1, "Voc (device)"))
            span = np.geomspace(min(x.min(), 1.0) / 1.5, max(x.max(), 1.0) * 1.5, 60)
            vr = _vrad(result, span)
            if vr is not None:
                ax.semilogx(span, vr, color=_pal.PLOT_REF, lw=1.0, ls="--", label="PLQY = 1")
            qf = result.get("qfls_fit")
            lines = []
            if qf is not None:
                m = np.asarray(result["fit_mask"], bool) & np.isfinite(q)
                xx = np.geomspace(x[m].min(), x[m].max(), 50)
                kt = core.KB_EV * result["temperature_K"]
                ax.semilogx(xx, qf["intercept_V"] + qf["n_id"] * kt * np.log(xx), **fit_kw("fit"))
                lines.append(f"implied n_id = {qf['n_id']:.2f}")
            if np.isfinite(result["QFLS_1sun"]):
                lines.append(f"QFLS(1 sun) = {result['QFLS_1sun']:.3f} eV" +
                             (" (extrap.)" if result["extrapolated_1sun"] else ""))
            elif np.isfinite(result["QFLS_ref"]):
                lines.append(f"QFLS = {result['QFLS_ref']:.3f} eV at {result['suns_ref']:.3g} sun")
            if np.isfinite(result["dV_int_ref"]):
                lines.append(f"QFLS/q - Voc = {1000 * result['dV_int_ref']:.0f} mV")
            if lines:
                note_box(ax, "\n".join(lines), "lower right")
            if len(x) == 1:
                ax.margins(y=0.25)
            ax.set_xlabel("Excitation (suns)")
            ax.set_ylabel("Energy / q (V)")
            legend(ax, "upper left")
            return
        if view == "Implied J-V":
            imp = result.get("implied")
            if not series:
                raise ValueError(_SERIES_ONLY)
            if imp is None:
                raise ValueError("an implied J-V curve needs four intensities at or below one sun and a QFLS")
            v, j = np.asarray(imp["v"], float), np.asarray(imp["j"], float)
            j_ref = float(np.max(j)) if len(j) else float("nan")
            jg = result["J_G_1sun"] * result.get("implied_ref_suns", 1.0)
            vv = np.r_[0.0, v]
            jj = np.r_[jg, j]
            o = np.argsort(vv)
            ax.plot(vv[o], jj[o], color=_pal.series_color(0), lw=1.2, label="implied J-V")
            ax.plot(v, j, **data_kw(0, "intensities"))
            if np.isfinite(imp["p_vmpp"]):
                ax.plot([imp["p_vmpp"]], [imp["p_jmpp"]], marker="s", ms=7, color=_pal.RED, ls="none",
                        label="maximum power", zorder=6)
            lines = [f"implied Voc = {result['iVoc']:.3f} V", f"implied FF = {result['iFF']:.1f} %",
                     f"implied PCE = {result['iPCE']:.1f} %"]
            if np.isfinite(result["transport_loss_FF"]):
                lines.append(f"measured FF {result['iFF'] - result['transport_loss_FF']:.1f} %")
            note_box(ax, "\n".join(lines), "lower left")
            ax.set_xlim(0.0, float(np.nanmax(v)) * 1.03)
            ax.set_ylim(0.0, max(jg, j_ref) * 1.08)
            ax.set_xlabel("Voltage = QFLS / q (V)")
            ax.set_ylabel("Current density (mA/cm²)")
            legend(ax, "center left")
            return
        # Voltage losses: from the radiative limit to the measured Voc at the reference intensity
        self._draw_ladder(ax, result)

    def _draw_sphere(self, ax, r):
        s = r["sphere"]
        wl = s["wl"]
        floor = max(float(np.nanmax(s["a"])) * 1e-5, 1e-3)
        for key, label, k in (("a", "A empty sphere", 2), ("b", "B out of beam", 1), ("c", "C in beam", 0)):
            y = s[key]
            if y is None:
                continue
            ax.semilogy(wl, np.clip(y, floor, None), color=_pal.series_color(k), lw=1.1, label=label)
        ax.axvspan(*s["laser"], color=_pal.ACCENT, alpha=0.10, lw=0, label="laser window")
        ax.axvspan(*s["emission"], color=_pal.RED, alpha=0.08, lw=0, label="emission window")
        lines = [f"PLQY = {100 * s['plqy']:.3g} %", f"absorptance = {100 * s['absorptance']:.1f} %",
                 "de Mello (A, B, C)" if s["method"] == "three" else "two measurements (A, C)"]
        if np.isfinite(r["QFLS_ref"]):
            lines.append(f"QFLS = {r['QFLS_ref']:.3f} eV")
        note_box(ax, "\n".join(lines), "upper right")
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Signal (" + ("photon counts" if r.get("units") == "photons" else "energy units") + ")")
        legend(ax, "lower left")

    def _draw_ladder(self, ax, r):
        x = r["suns_ref"]
        vr = _vrad(r, [x])
        steps = []
        eg = r["Eg_eV"]
        if np.isfinite(eg):
            steps.append(("Eg / q", float(eg)))
        if vr is not None:
            steps.append(("Voc,rad", float(vr[0])))
        if np.isfinite(r["QFLS_ref"]):
            steps.append(("QFLS / q", float(r["QFLS_ref"])))
        if np.isfinite(r["Voc_ref"]):
            steps.append(("Voc", float(r["Voc_ref"])))
        if len(steps) < 2:
            raise ValueError("the loss ladder needs the radiative reference (and a Voc for the contact loss)")
        names = [n for n, _ in steps]
        vals = [v for _, v in steps]
        ypos = np.arange(len(steps))[::-1]
        ax.barh(ypos, vals, color=[_pal.series_color(i) for i in range(len(steps))], height=0.55, alpha=0.85)
        for yy, v in zip(ypos, vals):
            ax.text(v, yy, f" {v:.3f} V", va="center", ha="left", fontsize=9, color=_pal.PLOT_FG)
        for i in range(1, len(steps)):
            d = vals[i - 1] - vals[i]
            label = {"Voc,rad": "radiative (edge, tail)", "QFLS / q": "non-radiative in the stack",
                     "Voc": "contacts"}.get(names[i], "")
            ax.annotate(f"-{1000 * d:.0f} mV  {label}", xy=(vals[i], ypos[i] + 0.5), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=8.5, color=_pal.PLOT_TICK)
        ax.set_yticks(ypos)
        ax.set_yticklabels(names)
        lo = min(vals) - 0.15
        ax.set_xlim(max(0.0, lo), max(vals) + 0.12)
        ax.set_xlabel(f"Voltage at {x:.3g} sun (V)" if np.isfinite(x) else "Voltage (V)")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
