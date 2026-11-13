"""Spectral mismatch window: the mismatch factor M of a solar simulator for
each test cell (IEC 60904-7) and the spectral match class of the simulator
(IEC 60904-9). The test cells are the files of the list (EQE or spectral
responsivity); the simulator spectrum and the reference cell are chosen once.
All numbers come from `mismatch_core`.
"""
from __future__ import annotations

from tkinter import filedialog

import numpy as np

from scripts.Mismatch import mismatch_core as core
from scripts.common import curve_batch
from scripts.common import palette as _pal
from scripts.common.curve_tool import (EXAMPLE_PREFIX, CurveToolWindow, legend, note_box, other_kw, ref_line,
                                       run_standalone)

_FILES = [("Data files", "*.csv *.txt *.dat *.tsv *.xlsx *.xls"), ("All files", "*.*")]
_CLASS_BANDS = (("A+", 0.875, 1.125, 0.16), ("A", 0.75, 1.25, 0.10), ("B", 0.6, 1.4, 0.06), ("C", 0.4, 2.0, 0.03))


class AnalysisWindow(CurveToolWindow):
    TOOL_NAME = "Spectral mismatch"
    SLUG = "mismatch"
    CORE = core
    FILE_HINT = ("Test cells: EQE (or responsivity in A/W) against wavelength, one file each. Choose the simulator "
                 "spectrum (wavelength, irradiance; 'AM1.5G' for the reference itself) and the reference cell "
                 "(wavelength, responsivity in A/W or EQE) with the buttons above.")
    FIELDS = [
        dict(key="sim_file", label="Simulator spectrum", kind="text", default="", group="Simulator"),
        dict(key="sim_units", label="Spectrum units", kind="choice", choices=list(core.SIM_UNITS), default="energy",
             group="Simulator"),
        dict(key="ref_file", label="Reference cell", kind="text", default="", group="Reference cell"),
        dict(key="ref_kind", label="Reference holds", kind="choice", choices=list(core.KINDS), default="auto",
             group="Reference cell"),
        dict(key="test_kind", label="Test files hold", kind="choice", choices=list(core.KINDS), default="auto",
             group="Test cells"),
    ]
    VIEWS = ["Weighted currents", "Spectra", "Responses", "Spectral match"]
    BATCH = curve_batch.batch_columns("mismatch")
    METHOD_SECTION = "25."
    NOTES = ("M = [Int E_ref S_R  Int E_sim S_T] / [Int E_sim S_R  Int E_ref S_T] with E_ref the ASTM G173-03 AM1.5G "
             "spectrum, E_sim the simulator spectrum and S_R, S_T the spectral responsivities of the reference and "
             "test cells (IEC 60904-7; Osterwald, Solar Cells 18, 269 (1986)). With the simulator set by the "
             "reference cell, the test cell reads M times its AM1.5G current; the current to report is the measured "
             "one divided by M. Spectral match: share of the irradiance per interval relative to AM1.5G, classes "
             "A+/A/B/C of IEC 60904-9 (2007 and 2020 editions).")

    # ---- data ----------------------------------------------------------------------
    _EXAMPLE_PARAMS = {"sim_file": core.EXAMPLE + " xenon-arc-like lamp",
                       "ref_file": core.EXAMPLE + " crystalline-silicon reference cell",
                       "sim_units": "energy", "ref_kind": "auto", "test_kind": "auto"}

    def demo(self):
        wl, y = core.example_test(790.0)
        return ("perovskite cell, band edge 790 nm (EQE)", {"wl": wl, "y": y, "_column": "EQE (%)",
                                                             "_columns": {"wavelength": "nm", "response": "EQE (%)"}},
                dict(self._EXAMPLE_PARAMS))

    def load_example(self):
        """Two test cells (band edges 790 and 690 nm) against the example lamp and reference cell."""
        name, data, params = self.demo()
        for k, v in params.items():
            self.set_param(k, v)
        wl, y = core.example_test(690.0, plateau=0.82)
        self.add_memory(EXAMPLE_PREFIX, "wide-gap cell, band edge 690 nm (EQE)",
                        {"wl": wl, "y": y, "_column": "EQE (%)", "_columns": {"wavelength": "nm", "response": "EQE (%)"}})
        self.add_memory(EXAMPLE_PREFIX, name, data)
        self.run()

    def open_actions(self):
        return [("Simulator spectrum...", self.choose_simulator), ("Reference cell...", self.choose_reference)]

    def choose_simulator(self):
        path = filedialog.askopenfilename(parent=self, title="Spectral mismatch: simulator spectrum",
                                          initialdir=self.directory_path or None, filetypes=_FILES)
        if path:
            self.set_param("sim_file", path)

    def choose_reference(self):
        path = filedialog.askopenfilename(parent=self, title="Spectral mismatch: reference cell response",
                                          initialdir=self.directory_path or None, filetypes=_FILES)
        if path:
            self.set_param("ref_file", path)

    # ---- graph ---------------------------------------------------------------------
    def draw(self, fig, data, result, view, params, others):
        ax = fig.add_subplot(111)
        g = result["grid"]
        k = result["I_ref_ref"] / result["I_sim_ref"]          # simulator scaled to give the reference its AM1.5G current
        if view == "Weighted currents":
            # current density per nm, A m-2 nm-1 -> mA cm-2 nm-1
            ax.plot(g, result["e_ref"] * result["s_test"] / 10.0, color=_pal.series_color(0), lw=1.3,
                    label="test cell, AM1.5G")
            ax.plot(g, k * result["e_sim"] * result["s_test"] / 10.0, color=_pal.series_color(0), lw=1.0, ls="--",
                    label="test cell, simulator")
            ax.plot(g, result["e_ref"] * result["s_ref"] / 10.0, color=_pal.series_color(1), lw=1.3,
                    label="reference, AM1.5G")
            ax.plot(g, k * result["e_sim"] * result["s_ref"] / 10.0, color=_pal.series_color(1), lw=1.0, ls="--",
                    label="reference, simulator")
            note_box(ax, f"M = {result['M']:.4f}\nJsc AM1.5G = {result['Jsc_AM15_test']:.2f} mA/cm²\n"
                         f"Jsc simulator = {result['Jsc_expected_sim']:.2f} mA/cm²", "upper right")
            ax.set_xlim(g[0], min(g[-1], max(result["ref_edges"][1], result["test_edges"][1]) + 150.0))
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("Current density per nm (mA cm$^{-2}$ nm$^{-1}$)")
            legend(ax, "upper left")
            return
        if view == "Spectra":
            ref_l, ref_e = g, result["e_ref"]
            sim = k * result["e_sim"]
            ax.plot(ref_l, ref_e, color=_pal.PLOT_FG, lw=1.0, label="AM1.5G (G173)")
            ax.plot(g, sim, color=_pal.RED, lw=1.0, label="simulator, scaled")
            for name, (edges, _plus) in core.EDITIONS.items():
                if name.startswith("Ed. 3"):
                    for e in edges:
                        if g[0] <= e <= g[-1]:
                            ax.axvline(e, color=_pal.PLOT_REF, lw=0.6, ls=":", zorder=1)
            ax.set_xlim(g[0], min(g[-1], 1400.0))
            ax.set_ylim(bottom=0.0)
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("Spectral irradiance (W m$^{-2}$ nm$^{-1}$)")
            legend(ax, "upper right")
            return
        if view == "Responses":
            for kk, (name, _d, r) in enumerate(others):
                ax.plot(r["test_wl"], r["test_sr"], **other_kw(kk, name))
            ax.plot(result["test_wl"], result["test_sr"], color=_pal.series_color(0), lw=1.5, label="test cell")
            ax.plot(result["ref_wl"], result["ref_sr"], color=_pal.series_color(1), lw=1.5, label="reference cell")
            lam = np.linspace(300.0, 1250.0, 50)
            ax.plot(lam, lam / core.HC_EV_NM, color=_pal.PLOT_REF, lw=0.9, ls="--", label="EQE = 100 %")
            ax.set_xlim(280.0, 1250.0)
            ax.set_ylim(bottom=0.0)
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("Spectral responsivity (A/W)")
            legend(ax, "upper left")
            return
        # spectral match class
        match = result["match"]
        if not any(match.values()):
            raise ValueError("the simulator spectrum does not cover 400-1100 nm")
        for name, lo, hi, alpha in _CLASS_BANDS:
            ax.axhspan(lo, hi, color=_pal.ACCENT, alpha=alpha, lw=0, zorder=0)
            ax.text(1.0, hi, f" {name}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=8,
                    color=_pal.PLOT_TICK)
        styles = {"Ed. 3 (2020)": dict(color=_pal.RED, lw=2.0, ls="-"),
                  "Ed. 2 (2007)": dict(color=_pal.PLOT_FG, lw=1.4, ls="--")}
        for name, m in match.items():
            if not m:
                continue
            for i, row in enumerate(m["rows"]):
                ax.plot([row["lo"], row["hi"]], [row["ratio"], row["ratio"]], **styles[name],
                        label=f"{name}: class {m['class']}" if i == 0 else None)
        ref_line(ax, y=1.0)
        ax.set_xlim(300.0, 1200.0)
        ax.set_ylim(0.3, 2.1)
        ax.set_xlabel("Wavelength interval (nm)")
        ax.set_ylabel("Simulator share / AM1.5G share")
        legend(ax, "upper left")


def main():
    run_standalone(AnalysisWindow)


if __name__ == "__main__":
    main()
