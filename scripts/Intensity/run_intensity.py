"""Light-intensity dependence window: ideality factor from Voc(I), the Jsc
power law, the Suns-Voc pseudo J-V curve and the transport loss in FF.

Input is either a table (irradiance, Voc, optionally Jsc, FF, PCE) or a set of
J-V files measured at different intensities, the irradiance being read from
the file names. All numbers come from `intensity_core`.
"""
from __future__ import annotations

import os
from tkinter import filedialog

import numpy as np

from scripts.Intensity import intensity_core as core
from scripts.common import app_config, curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (SET_PREFIX, CurveToolWindow, data_kw, fit_kw, legend, note_box, other_kw,
                                       ref_line, run_standalone)


def _has(a) -> bool:
    return a is not None and len(a) > 0 and bool(np.isfinite(np.asarray(a, float)).any())


def _x_label(data) -> str:
    """The irradiance axis carries the unit of the file: the column name of a
    table, mW/cm2 for a J-V set (irradiance parsed from the file names)."""
    name = (data.get("_columns") or {}).get("intensity", "") if isinstance(data, dict) else ""
    name = name.replace(" (by position)", "").strip()
    return name if name and not name.isdigit() else "Irradiance (mW/cm²)"


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "Light intensity"
    SLUG = "intensity"
    CORE = core
    FILE_HINT = ("A table with irradiance and Voc columns (Jsc, FF, PCE optional), or 'J-V set': several J-V "
                 "files whose names carry the irradiance (0.1sun, 53mW, 10pct, OD1.0).")
    FIELDS = [
        dict(key="temperature_k", label="Temperature (K)", default=300.0, min=1.0, group="Fit"),
        dict(key="i_min", label="Lowest irradiance", default="", optional=True, group="Fit"),
        dict(key="i_max", label="Highest irradiance", default="", optional=True, group="Fit"),
        dict(key="area_cm2", label="Area (cm²)", default=app_config.cell_area_cm2, min=1e-6, group="J-V sets"),
        dict(key="sweep", label="Sweep", kind="choice", choices=["reverse", "forward", "combined"],
             default="reverse", group="J-V sets"),
    ]
    VIEWS = ["Voc", "Jsc", "FF and PCE", "Pseudo J-V", "Local ideality"]
    BATCH = curve_batch.batch_columns("intensity")
    METHOD_SECTION = "18."
    NOTES = ("The ideality factor is the slope of Voc against ln(irradiance) in units of kT/q and alpha the slope "
             "of log Jsc against log irradiance. The pseudo J-V curve places each (Jsc_ref - Jsc_i, Voc_i) pair "
             "on a series-resistance-free characteristic (Sinton and Cuevas, 2000); the difference between its "
             "fill factor and the measured one is the transport loss. Intervals are 95 % confidence intervals of "
             "the regression (Tress et al., Energy Environ. Sci. 11, 151 (2018); Caprioglio et al., Adv. Energy "
             "Mater. 10, 2000502 (2020)).")

    # ---- data ----------------------------------------------------------------------
    def open_actions(self):
        return [("J-V set", self.add_jv_set)]

    def add_jv_set(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="J-V files measured at different intensities",
            initialdir=self.directory_path or None,
            filetypes=[("J-V files", "*.txt *.csv *.dat *.tsv *.xlsx *.xls"), ("All files", "*.*")])
        if paths:
            self.add_jv_files(list(paths))

    def add_jv_files(self, paths, run: bool = True):
        """One series from several J-V files (also used by the launcher)."""
        self.directory_path = os.path.dirname(paths[0])
        folder = os.path.basename(self.directory_path) or "J-V"
        self.add_memory(SET_PREFIX, f"{folder} ({len(paths)} J-V files)", {"_jv_files": list(paths)})
        if run:
            self.run()

    def resolve(self, path, params):
        held = self._memory.get(path)
        if isinstance(held, dict) and "_jv_files" in held:
            return curve_batch.load_jv_set(held["_jv_files"], params)
        return super().resolve(path, params)

    def demo(self):
        d = core.simulate()
        return ("n_id = 1.5, alpha = 0.97, Rs = 3 Ohm cm2", d, {"temperature_k": 300.0, "i_min": "", "i_max": ""})

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        inten, mask = result["intensity"], np.asarray(result["fit_mask"], bool)
        xl = _x_label(data)
        if view == "FF and PCE":
            self._draw_ff(fig, result, xl)
            return
        ax = fig.add_subplot(111)
        if view == "Jsc":
            if not _has(result.get("jsc")):
                raise ValueError("this series has no Jsc column")
            for k, (name, _d, r) in enumerate(others):
                if _has(r.get("jsc")):
                    ax.loglog(r["intensity"], np.abs(r["jsc"]), marker="o", ms=3, **other_kw(k, name))
            jsc = np.abs(result["jsc"])
            ax.loglog(inten[mask], jsc[mask], **data_kw(0, "measured"))
            if (~mask).any():
                ax.loglog(inten[~mask], jsc[~mask], ls="none", marker="o", ms=4.5, mfc="none",
                          mec=_pal.PLOT_REF, label="not fitted")
            f = result.get("jsc_fit")
            if f:
                x = np.logspace(np.log10(inten.min()), np.log10(inten.max()), 50)
                ax.loglog(x, 10.0 ** (f["log_prefactor"] + f["alpha"] * np.log10(x)), **fit_kw("power law"))
                note_box(ax, f"alpha = {f['alpha']:.3f} ± {f.get('alpha_ci', float('nan')):.3f}\n"
                             f"R² = {f['r2']:.4f}", "lower right")
            ax.set_xlabel(xl)
            ax.set_ylabel(r"$J_{sc}$ (mA/cm$^2$)")
            legend(ax, "upper left")
            return
        if view == "Pseudo J-V":
            ps = result.get("pseudo")
            if not ps:
                raise ValueError("the pseudo J-V curve needs a Jsc column")
            order = np.argsort(ps["v"])
            pv, pj = np.asarray(ps["v"], float)[order], np.asarray(ps["j"], float)[order]
            j_ref = float(np.nanmax(np.abs(result["jsc"])))
            # short-circuit point of the reference intensity, as in the pFF calculation
            ax.plot(np.r_[0.0, pv], np.r_[j_ref, pj], color=_pal.series_color(0), lw=1.0)
            ax.plot(pv, pj, **data_kw(0, "pseudo J-V (Suns-Voc)"))
            if np.isfinite(ps.get("p_vmpp", np.nan)):
                ax.plot([ps["p_vmpp"]], [ps["p_jmpp"]], ls="none", marker="s", ms=7, mfc=_pal.RED, mec=_pal.RED,
                        label="pseudo MPP")
            lines = [f"pFF = {ps['pFF'] * 100:.1f} %" if np.isfinite(ps.get("pFF", np.nan)) else "pFF: not defined"]
            if np.isfinite(result.get("FF_at_max", np.nan)):
                lines.append(f"FF at the highest irradiance = {result['FF_at_max']:.1f} %")
            if np.isfinite(result.get("transport_loss_FF", np.nan)):
                lines.append(f"transport loss = {result['transport_loss_FF']:.1f} % abs")
            if not ps.get("covers_mpp", False):
                lines.append("series does not reach the maximum power point")
            note_box(ax, "\n".join(lines), "lower left")
            ax.set_xlabel("Voltage (V)")
            ax.set_ylabel("J (mA/cm²)")
            ax.set_ylim(bottom=0)
            ax.set_xlim(left=0)
            legend(ax, "upper right")
            return
        if view == "Local ideality":
            loc = result.get("n_local")
            if loc is None or len(loc[0]) == 0:
                raise ValueError("too few points for a local ideality factor")
            ax.semilogx(loc[0], loc[1], **data_kw(0, "local slope", line=True))
            ref_line(ax, y=1.0, text="1  radiative / band-to-band")
            ref_line(ax, y=2.0, text="2  SRH in the bulk")
            n = (result.get("voc_fit") or {}).get("n_id", np.nan)
            if np.isfinite(n):
                ax.axhline(n, color=_pal.RED, lw=1.5, label=f"range fit, n = {n:.2f}")
            ax.set_xlabel(xl)
            ax.set_ylabel("Ideality factor")
            ax.set_ylim(0.5, max(2.6, float(np.nanmax(loc[1])) * 1.1))
            legend(ax, "upper right")
            return
        # Voc against irradiance
        for k, (name, _d, r) in enumerate(others):
            ax.semilogx(r["intensity"], r["voc"], marker="o", ms=3, **other_kw(k, name))
        ax.semilogx(inten[mask], result["voc"][mask], **data_kw(0, "measured"))
        if (~mask).any():
            ax.semilogx(inten[~mask], result["voc"][~mask], ls="none", marker="o", ms=4.5, mfc="none",
                        mec=_pal.PLOT_REF, label="not fitted")
        f = result.get("voc_fit")
        if f:
            x = np.logspace(np.log10(inten.min()), np.log10(inten.max()), 50)
            ax.semilogx(x, f["intercept_V"] + f["slope_mV_per_decade"] / 1000.0 * np.log10(x), **fit_kw("fit"))
            note_box(ax, f"n_id = {f['n_id']:.3f} ± {f.get('n_id_ci', float('nan')):.3f}\n"
                         f"{f['slope_mV_per_decade']:.1f} mV per decade\nR² = {f['r2']:.4f}", "lower right")
        else:
            note_box(ax, "fewer than three Voc points in the fit range", "lower right")
        ax.set_xlabel(xl)
        ax.set_ylabel(r"$V_{oc}$ (V)")
        legend(ax, "upper left")

    def _draw_ff(self, fig, result, xl):
        have_ff, have_pce = _has(result.get("ff")), _has(result.get("pce"))
        if not (have_ff or have_pce):
            raise ValueError("this series has neither an FF nor a PCE column")
        n = int(have_ff) + int(have_pce)
        k = 1
        first = None
        for key, label, have in (("ff", "FF (%)", have_ff), ("pce", "PCE (%)", have_pce)):
            if not have:
                continue
            ax = fig.add_subplot(n, 1, k, sharex=first) if first is not None else fig.add_subplot(n, 1, k)
            first = first or ax
            ax.semilogx(result["intensity"], result[key], **data_kw(k - 1, label, line=True))
            if key == "ff" and np.isfinite(result.get("FF0", np.nan)):
                ref_line(ax, y=result["FF0"], text="FF0, ideal diode without resistance", side="left")
                vals = np.asarray(result["ff"], float)
                lo, hi = float(np.nanmin(vals)), max(float(np.nanmax(vals)), float(result["FF0"]))
                ax.set_ylim(lo - 0.08 * (hi - lo), hi + 0.22 * (hi - lo))
            ax.set_ylabel(label)
            if k == n:
                ax.set_xlabel(xl)
            else:
                ax.tick_params(labelbottom=False)
            k += 1


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
