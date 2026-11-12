"""Rule-based interpretation of analysis results (replaces the Gemini text, 3.4).

Every statement is produced by an explicit rule from the numbers the analysis
already computed, and carries its evidence, the rule (threshold or formula), a
literature reference and a suggested next step. Nothing is sent anywhere and the
same input always gives the same text, so the interpretation can be cited and
reproduced.

    rep = interpret_jv(summary, fit=fit, hysteresis_index=hi)
    print(rep.to_markdown())

Levels: "problem" (limits the device or invalidates a number), "warning"
(worth acting on), "note" (context), "good" (within the expected range).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

KB_EV = 8.617333262e-5          # eV/K
LEVELS = ("problem", "warning", "note", "good")
LEVEL_LABEL = {"problem": "Problem", "warning": "Warning", "note": "Note", "good": "Good"}


@dataclass
class Finding:
    level: str
    topic: str
    text: str
    evidence: str = ""
    rule: str = ""
    ref: str = ""
    action: str = ""


@dataclass
class Report:
    technique: str
    subject: str = ""
    findings: List[Finding] = field(default_factory=list)

    def add(self, level, topic, text, evidence="", rule="", ref="", action=""):
        self.findings.append(Finding(level, topic, text, evidence, rule, ref, action))
        return self.findings[-1]

    def extend(self, other: "Report"):
        self.findings.extend(other.findings)

    def sorted(self) -> List[Finding]:
        return sorted(self.findings, key=lambda f: LEVELS.index(f.level) if f.level in LEVELS else 9)

    def counts(self) -> Dict[str, int]:
        return {lv: sum(1 for f in self.findings if f.level == lv) for lv in LEVELS}

    def summary(self) -> str:
        """Two or three sentences: the count, the main limitation, the main next step."""
        c = self.counts()
        if not self.findings:
            return "No result to interpret yet."
        parts = [f"{c['problem']} problem(s), {c['warning']} warning(s), {c['note']} note(s), {c['good']} in range."]
        top = [f for f in self.sorted() if f.level in ("problem", "warning")]
        if top:
            parts.append("Main point: " + top[0].text)
            act = next((f.action for f in top if f.action), "")
            if act:
                parts.append("Suggested next step: " + act)
        elif c["note"]:
            parts.append("Nothing outside the expected ranges; the notes give context worth reporting.")
        else:
            parts.append("All checked quantities are within the expected ranges.")
        return " ".join(parts)

    def to_markdown(self) -> str:
        lines = [f"# Interpretation - {self.technique}" + (f": {self.subject}" if self.subject else ""), "",
                 self.summary(), "",
                 "Rule-based interpretation (Physiscore): every statement follows from the listed rule; "
                 "thresholds and references are in the methods document, section 16.", ""]
        for f in self.sorted():
            lines.append(f"## {LEVEL_LABEL.get(f.level, f.level)} - {f.topic}")
            lines.append("")
            lines.append(f.text)
            lines.append("")
            if f.evidence:
                lines.append(f"- Evidence: {f.evidence}")
            if f.rule:
                lines.append(f"- Rule: {f.rule}")
            if f.ref:
                lines.append(f"- Reference: {f.ref}")
            if f.action:
                lines.append(f"- Next step: {f.action}")
            lines.append("")
        return "\n".join(lines)

    def to_text(self) -> str:
        out = [self.summary(), ""]
        for f in self.sorted():
            out.append(f"[{LEVEL_LABEL.get(f.level, f.level)}] {f.topic}: {f.text}")
            if f.evidence:
                out.append(f"    evidence: {f.evidence}")
            if f.action:
                out.append(f"    next: {f.action}")
        return "\n".join(out)


def _ok(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _f(x, spec=".3g"):
    return format(float(x), spec) if _ok(x) else "-"


# =========================================================================== J-V
def ff_from_voc(voc_norm: float) -> float:
    """Green's empirical FF of an ideal diode, voc = Voc / (n kT/q)."""
    return (voc_norm - math.log(voc_norm + 0.72)) / (voc_norm + 1.0)


def ff_loss_breakdown(voc_v, jsc, ff_percent, n=1.0, rs=None, rsh=None, temperature_k=298.15) -> dict:
    """Split the FF loss into recombination (ideality), series and shunt resistance
    with Green's expressions (Green, Solar Cells 1982; Solid-State Electron. 24, 788, 1981):
        FF0 = (voc - ln(voc + 0.72)) / (voc + 1),   voc = Voc / (n kT/q)
        FFs = FF0 (1 - 1.1 rs) + rs^2 / 5.4,        rs = Rs Jsc / Voc
        FFsh = FFs [1 - (voc + 0.7)/voc * FFs / rsh], rsh = Rsh Jsc / Voc
    Jsc in mA/cm2, R in Ohm cm2. Returns FF values (in %) and the losses in FF points."""
    vt = KB_EV * temperature_k
    out = {}
    if not (_ok(voc_v) and _ok(jsc) and voc_v > 0 and jsc > 0):
        return out
    ff_ideal = 100 * ff_from_voc(voc_v / vt)
    n = float(n) if _ok(n) and n > 0 else 1.0
    ff0 = 100 * ff_from_voc(voc_v / (n * vt))
    ffs = ff0
    r_s = float(rs) * jsc / 1000.0 / voc_v if _ok(rs) and rs > 0 else 0.0
    if r_s > 0:
        ffs = ff0 * (1 - 1.1 * r_s) + 100 * r_s ** 2 / 5.4
    ffsh = ffs
    r_sh = float(rsh) * jsc / 1000.0 / voc_v if _ok(rsh) and rsh > 0 else math.inf
    voc_n = voc_v / (n * vt)
    if math.isfinite(r_sh) and r_sh > 0:
        ffsh = ffs * (1 - (voc_n + 0.7) / voc_n * (ffs / 100) / r_sh)
    out.update(FF_ideal=ff_ideal, FF0=ff0, FFs=ffs, FFsh=ffsh, rs_norm=r_s, rsh_norm=r_sh,
               loss_recombination=ff_ideal - ff0, loss_series=ff0 - ffs, loss_shunt=ffs - ffsh)
    if _ok(ff_percent):
        out["FF_measured"] = float(ff_percent)
        out["loss_unexplained"] = ffsh - float(ff_percent)
    return out


def interpret_jv(summary: dict, fit: Optional[dict] = None, hysteresis_index: Optional[float] = None,
                 temperature_k: float = 298.15, subject: str = "") -> Report:
    """summary: Voc (V), Jsc (mA/cm2, either sign), FF (%), PCE (%), Rs and Rsh from the
    curve slopes (Ohm cm2). fit: one-diode fit (n, J0, Rs, Rsh, R2). hysteresis_index in %."""
    rep = Report("J-V", subject)
    voc = summary.get("Voc")
    jsc = abs(summary["Jsc"]) if _ok(summary.get("Jsc")) else None
    ff = summary.get("FF")
    fit = fit or {}
    n = fit.get("n")
    rs = fit.get("Rs") if _ok(fit.get("Rs")) else summary.get("Rs")
    rsh = fit.get("Rsh") if _ok(fit.get("Rsh")) else summary.get("Rsh")
    vt = KB_EV * temperature_k

    if _ok(voc) and _ok(jsc) and _ok(ff):
        b = ff_loss_breakdown(voc, jsc, ff, n if _ok(n) else 1.0, rs, rsh, temperature_k)
        if b:
            losses = {"recombination (ideality factor)": b["loss_recombination"],
                      "series resistance": b["loss_series"], "shunt resistance": b["loss_shunt"]}
            main = max(losses, key=losses.get)
            ev = (f"FF {float(ff):.1f} %; ideal {b['FF_ideal']:.1f} %; losses: recombination "
                  f"{b['loss_recombination']:.1f}, series {b['loss_series']:.1f}, shunt {b['loss_shunt']:.1f}, "
                  f"unexplained {round(b.get('loss_unexplained', float('nan')), 1) + 0.0:.1f} FF points "
                  f"(rs = {b['rs_norm']:.3f}, rsh = {b['rsh_norm']:.0f})")
            level = "warning" if losses[main] > 3 else "good"
            rep.add(level, "Fill factor losses",
                    f"The largest fill-factor loss is from {main} ({losses[main]:.1f} FF points of "
                    f"{b['FF_ideal'] - float(ff):.1f}).", ev,
                    "Green's FF0, FFs and FFsh expressions with the fitted n, Rs and Rsh",
                    "Green, Solar Cells (1982); Green, Solid-State Electron. 24, 788 (1981)",
                    {"series resistance": "Check contacts, electrode sheet resistance and transport-layer thickness.",
                     "shunt resistance": "Look for pinholes or incomplete coverage (SEM), and edge shunts.",
                     "recombination (ideality factor)": "Reduce trap-assisted recombination (passivation, "
                     "grain boundaries), see the ideality factor."}[main] if level == "warning" else "")
            unexplained = b.get("loss_unexplained", 0.0)
            if _ok(unexplained) and unexplained > 3:
                rep.add("warning", "Curve shape",
                        f"The measured FF is {unexplained:.1f} points below what n, Rs and Rsh explain.",
                        ev, "unexplained loss > 3 FF points",
                        "Wagenpfahl et al., Phys. Rev. B 82, 115306 (2010)",
                        "An S-shaped or kinked curve points to an extraction barrier at an interface.")

    if _ok(n):
        n = float(n)
        if n < 0.95:
            rep.add("problem", "Ideality factor", f"n = {n:.2f} is below 1, which a diode cannot have.",
                    f"n = {n:.3f}", "n < 0.95", "", "Check the fit range and the curve quality.")
        elif n <= 1.3:
            rep.add("good", "Ideality factor", f"n = {n:.2f}: recombination is mainly radiative or bimolecular.",
                    f"n = {n:.3f}", "1 <= n <= 1.3", "Tress et al., Energy Environ. Sci. 11, 151 (2018)")
        elif n <= 1.8:
            rep.add("note", "Ideality factor", f"n = {n:.2f}: trap-assisted (Shockley-Read-Hall) recombination "
                    "contributes.", f"n = {n:.3f}", "1.3 < n <= 1.8",
                    "Tress et al., Energy Environ. Sci. 11, 151 (2018)")
        elif n <= 2.2:
            rep.add("warning", "Ideality factor", f"n = {n:.2f}: trap-assisted recombination dominates.",
                    f"n = {n:.3f}", "1.8 < n <= 2.2", "Tress et al., Energy Environ. Sci. 11, 151 (2018)",
                    "Passivate bulk and interface traps; compare with the light-intensity dependence of Voc.")
        else:
            rep.add("problem", "Ideality factor", f"n = {n:.2f} exceeds 2: the one-diode model is not adequate "
                    "(series or shunt effects, several mechanisms).", f"n = {n:.3f}", "n > 2.2",
                    "Tress et al., Energy Environ. Sci. 11, 151 (2018)",
                    "Measure dark J-V and Voc versus light intensity to separate the mechanisms.")

    if _ok(rs) and _ok(jsc) and _ok(voc) and voc > 0:
        rsn = float(rs) * jsc / 1000.0 / float(voc)
        lvl = "problem" if rsn > 0.1 else "warning" if rsn > 0.05 else "good"
        rep.add(lvl, "Series resistance", f"Rs = {float(rs):.2f} Ω cm² (normalised rs = {rsn:.3f}) "
                + ("costs a large part of the fill factor." if lvl == "problem" else
                   "noticeably lowers the fill factor." if lvl == "warning" else "is small."),
                f"Rs = {float(rs):.3g} Ω cm², Jsc = {jsc:.2f} mA/cm², Voc = {float(voc):.3f} V",
                "rs = Rs Jsc / Voc: > 0.05 warning, > 0.1 problem", "Green, Solar Cells (1982)",
                "Check contacts and the transparent electrode." if lvl != "good" else "")
    if _ok(rsh) and _ok(jsc) and _ok(voc) and voc > 0:
        rshn = float(rsh) * jsc / 1000.0 / float(voc)
        lvl = "problem" if rshn < 10 else "warning" if rshn < 50 else "good"
        rep.add(lvl, "Shunt resistance", f"Rsh = {float(rsh):.0f} Ω cm² (normalised rsh = {rshn:.0f}) "
                + ("shunts the device." if lvl == "problem" else "leaks noticeably." if lvl == "warning"
                   else "is high enough."),
                f"Rsh = {float(rsh):.4g} Ω cm²", "rsh = Rsh Jsc / Voc: < 50 warning, < 10 problem",
                "Green, Solar Cells (1982)",
                "Inspect film coverage and pinholes (SEM); check scribing and edges." if lvl != "good" else "")

    if _ok(n) and _ok(fit.get("J0")) and _ok(jsc) and _ok(voc) and float(fit["J0"]) > 0:
        voc_pred = float(n) * vt * math.log(jsc / float(fit["J0"]) + 1)
        d = 1000 * (voc_pred - float(voc))
        if abs(d) > 20:
            rep.add("note", "Voc consistency", f"Voc predicted from n and J0 differs by {d:+.0f} mV from the "
                    "measured Voc.", f"n kT/q ln(Jsc/J0 + 1) = {voc_pred:.3f} V vs {float(voc):.3f} V",
                    "|difference| > 20 mV", "", "Check the fit range and the light intensity.")
    r2 = fit.get("R2")
    if _ok(r2) and float(r2) < 0.995:
        rep.add("warning", "Diode model", f"The one-diode fit describes the curve only roughly (R² = {float(r2):.4f}).",
                f"R² = {float(r2):.5f}", "R² < 0.995", "Wagenpfahl et al., Phys. Rev. B 82, 115306 (2010)",
                "Look for an S-shape or a kink near Voc (extraction barrier).")
    if _ok(summary.get("Rs")) and _ok(fit.get("Rs")) and float(fit["Rs"]) > 0:
        ratio = float(summary["Rs"]) / float(fit["Rs"])
        if ratio > 3 and float(summary["Rs"]) > 5:
            rep.add("warning", "Curve shape", f"The slope near Voc gives a resistance {ratio:.1f} times the fitted "
                    "Rs: the curve bends more than a resistor explains.",
                    f"Rs(slope) = {float(summary['Rs']):.3g}, Rs(fit) = {float(fit['Rs']):.3g} Ω cm²",
                    "Rs(slope) / Rs(fit) > 3", "Wagenpfahl et al., Phys. Rev. B 82, 115306 (2010)",
                    "Check for an energy barrier at the electron or hole contact.")

    if _ok(hysteresis_index):
        hi = float(hysteresis_index)
        if hi < -5:
            rep.add("note", "Hysteresis", f"Inverted hysteresis (HI = {hi:.1f} %): the forward scan gives the "
                    "higher efficiency.", f"HI = {hi:.2f} %", "HI < -5 %",
                    "Tress et al., Energy Environ. Sci. 8, 995 (2015)", "Compare scan rates and pre-biasing.")
        else:
            lvl = "problem" if hi > 15 else "warning" if hi > 5 else "good"
            rep.add(lvl, "Hysteresis", f"Hysteresis index {hi:.1f} %" +
                    (": strong ion migration or trapping." if lvl == "problem" else
                     ": noticeable hysteresis." if lvl == "warning" else ": small."),
                    f"HI = (PCE_rev - PCE_fwd)/PCE_rev = {hi:.2f} %", "|HI| > 5 % warning, > 15 % problem",
                    "Snaith et al., J. Phys. Chem. Lett. 5, 1511 (2014)",
                    "Report the stabilised power output (maximum-power-point tracking)." if lvl != "good" else "")
    return rep


def robust_outliers(values: Sequence[float], threshold: float = 3.5) -> List[int]:
    """Indices whose modified z-score 0.6745 (x - median) / MAD exceeds the threshold
    (Iglewicz & Hoaglin 1993)."""
    x = np.asarray([v for v in values], dtype=float)
    ok = np.isfinite(x)
    if ok.sum() < 4:
        return []
    med = np.median(x[ok])
    mad = np.median(np.abs(x[ok] - med))
    if mad == 0:
        return []
    z = 0.6745 * (x - med) / mad
    return [i for i, v in enumerate(z) if np.isfinite(v) and abs(v) > threshold]


def hedges_g(a: Sequence[float], b: Sequence[float]) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    sp = math.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    if sp == 0:
        return float("nan")
    d = (a.mean() - b.mean()) / sp
    return d * (1 - 3 / (4 * (na + nb) - 9))


def holm(pvalues: Sequence[float]) -> List[float]:
    """Holm-Bonferroni adjusted p-values (same order as given)."""
    p = list(pvalues)
    order = sorted(range(len(p)), key=lambda i: p[i])
    adj = [1.0] * len(p)
    running = 0.0
    m = len(p)
    for rank, i in enumerate(order):
        val = min(1.0, (m - rank) * p[i])
        running = max(running, val)
        adj[i] = running
    return adj


def interpret_statistics(groups: Dict[str, Dict[str, Sequence[float]]], reference: Optional[str] = None,
                         names: Optional[Dict[str, Sequence[str]]] = None) -> Report:
    """groups: condition -> {"PCE": [...], "Voc": [...], "Jsc": [...], "FF": [...]} (one value per cell).
    Reproducibility (coefficient of variation), robust outliers, and each condition against the
    reference condition with Welch's t-test (Holm-corrected over the four parameters) and Hedges' g."""
    from scipy import stats
    rep = Report("J-V statistics")
    if not groups:
        return rep
    conds = list(groups)
    ref = reference if reference in groups else next(
        (c for c in conds if any(k in c.lower() for k in ("ref", "control", "pristine", "base"))), conds[0])
    for c in conds:
        pce = np.asarray(groups[c].get("PCE", []), float)
        pce = pce[np.isfinite(pce)]
        if len(pce) >= 3 and pce.mean() > 0:
            cv = 100 * pce.std(ddof=1) / pce.mean()
            lvl = "warning" if cv > 10 else "good"
            rep.add(lvl, f"Reproducibility - {c}", f"{c}: PCE {pce.mean():.2f} ± {pce.std(ddof=1):.2f} % "
                    f"(n = {len(pce)}, CV = {cv:.1f} %).", f"CV = sd/mean = {cv:.2f} %", "CV > 10 % warning",
                    "", "Check film uniformity and the area definition (mask)." if lvl == "warning" else "")
        elif len(pce):
            rep.add("note", f"Reproducibility - {c}", f"{c}: only {len(pce)} cell(s); statistics need three or more.",
                    f"n = {len(pce)}", "n < 3")
        out = robust_outliers(groups[c].get("PCE", []))
        if out:
            labels = [(names or {}).get(c, [])[i] if i < len((names or {}).get(c, [])) else f"#{i + 1}" for i in out]
            rep.add("warning", f"Outliers - {c}", f"{c}: {len(out)} cell(s) far from the others: {', '.join(labels)}.",
                    "modified z-score |0.6745 (x - median)/MAD| > 3.5", "Iglewicz & Hoaglin outlier test",
                    "Iglewicz & Hoaglin, How to Detect and Handle Outliers (1993)",
                    "Inspect those cells (shunt, contact) before averaging.")
    params = ("PCE", "Voc", "Jsc", "FF")
    units = {"PCE": "%", "Voc": "V", "Jsc": "mA/cm²", "FF": "%"}
    for c in conds:
        if c == ref:
            continue
        tests = []
        for p in params:
            a = np.asarray(groups[c].get(p, []), float)
            b = np.asarray(groups[ref].get(p, []), float)
            a, b = a[np.isfinite(a)], b[np.isfinite(b)]
            if len(a) >= 3 and len(b) >= 3:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)   # nearly identical values
                    t = stats.ttest_ind(a, b, equal_var=False)
                if np.isfinite(t.pvalue):
                    tests.append((p, a, b, float(t.pvalue)))
        if not tests:
            continue
        adj = holm([t[3] for t in tests])
        for (p, a, b, pv), pa in zip(tests, adj):
            diff = a.mean() - b.mean()
            g = hedges_g(a, b)
            sig = pa < 0.05
            if p == "PCE" or sig:
                rel = 100 * abs(diff) / abs(b.mean()) if b.mean() != 0 else float("inf")
                small = sig and rel < 1.0          # statistically clear but practically negligible
                lvl = ("note" if small else "good" if (sig and diff > 0) else
                       "warning" if (sig and diff < 0) else "note")
                shown = f"{1000 * diff:+.0f} mV" if p == "Voc" else f"{diff:+.3g} {units[p]}"
                verdict = ("(significant, but below 1 % of the reference: practically negligible)." if small else
                           "(significant)." if sig else "(not significant).")
                rep.add(lvl, f"{c} vs {ref}: {p}", f"{p} of {c} is {shown} against {ref} {verdict}",
                        f"{a.mean():.4g} ± {a.std(ddof=1):.2g} vs {b.mean():.4g} ± {b.std(ddof=1):.2g} "
                        f"(n = {len(a)}, {len(b)}); Welch p = {pv:.3g}, Holm-adjusted {pa:.3g}; Hedges g = {g:.2f}; "
                        f"relative difference {rel:.2g} %",
                        "Welch's t-test, Holm-corrected over PCE/Voc/Jsc/FF; significant if adjusted p < 0.05; "
                        "a significant difference below 1 % of the reference is reported as a note",
                        "Welch, Biometrika 34, 28 (1947); Holm, Scand. J. Stat. 6, 65 (1979); "
                        "Hedges, J. Educ. Stat. 6, 107 (1981)")
    return rep


# =========================================================================== dark J-V
def interpret_dark(row: dict, subject: str = "") -> Report:
    """row: keys of the dark J-V summary (Ideality n, J0, Rsh_dark, n (full fit), Rs fit, Rsh fit,
    Full fit R2, Cheung n / Rs if present)."""
    rep = Report("J-V dark", subject)
    n = row.get("Ideality n")
    nf = row.get("n (full fit)")
    if _ok(n):
        n = float(n)
        lvl = "good" if n <= 1.5 else "note" if n <= 2.0 else "warning"
        rep.add(lvl, "Ideality factor (dark)", f"Dark ideality n = {n:.2f} "
                + ("(close to band-to-band recombination)." if lvl == "good" else
                   "(trap-assisted recombination contributes)." if lvl == "note" else
                   "(above 2: shunt, series or several mechanisms)."),
                f"n = {n:.3f} from the steepest straight part of ln J", "<= 1.5 good, <= 2 note, > 2 warning",
                "Sze & Ng, Physics of Semiconductor Devices (2007)")
    if _ok(n) and _ok(nf) and abs(float(n) - float(nf)) > 0.3:
        rep.add("note", "Model consistency", f"The window estimate (n = {float(n):.2f}) and the full fit "
                f"(n = {float(nf):.2f}) disagree: series or shunt resistance shapes the window.",
                f"|Δn| = {abs(float(n) - float(nf)):.2f}", "|Δn| > 0.3")
    rsh = row.get("Rsh_dark (Ohm cm2)", row.get("Rsh fit (Ohm cm2)"))
    if _ok(rsh):
        r = float(rsh)
        lvl = "problem" if r < 1e3 else "warning" if r < 1e4 else "good"
        rep.add(lvl, "Leakage", f"Dark shunt resistance {r:.3g} Ω cm² "
                + ("means strong leakage." if lvl == "problem" else "means some leakage." if lvl == "warning"
                   else "means low leakage."),
                f"Rsh,dark = {r:.4g} Ω cm²", "< 1e3 problem, < 1e4 warning",
                "", "Look for pinholes and edge shunts." if lvl != "good" else "")
    rs = row.get("Rs fit (Ohm cm2)")
    if _ok(rs) and float(rs) > 5:
        rep.add("warning", "Series resistance (dark)", f"Rs = {float(rs):.2f} Ω cm² from the full fit.",
                f"Rs = {float(rs):.3g} Ω cm²", "> 5 Ω cm²", "", "Check contacts and electrode resistance.")
    r2 = row.get("Full fit R2 (log)")
    if _ok(r2) and float(r2) < 0.99:
        rep.add("warning", "Fit quality", f"The full diode fit matches log J only roughly (R² = {float(r2):.3f}).",
                f"R² = {float(r2):.4f}", "R² < 0.99", "", "Restrict the voltage range or check the curve.")
    return rep


# =========================================================================== EQE
def _am15_flux(wl_nm):
    """AM1.5G photon flux (photons s^-1 m^-2 nm^-1) on the given grid."""
    import os
    import pandas as pd
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "EQE", "astm_g173_global.csv")
    df = pd.read_csv(path)
    lam = df.iloc[:, 0].to_numpy(float)
    irr = df.iloc[:, -1].to_numpy(float)          # W m^-2 nm^-1
    flux = irr * lam * 1e-9 / (6.62607015e-34 * 2.99792458e8)
    return np.interp(wl_nm, lam, flux, left=0.0, right=0.0)


def spectral_losses(wl_nm, eqe_frac, eg_ev) -> dict:
    wl = np.asarray(wl_nm, float)
    e = np.clip(np.asarray(eqe_frac, float), 0, 1)
    order = np.argsort(wl)
    wl, e = wl[order], e[order]
    lam_g = 1239.84198 / float(eg_ev)
    q = 1.602176634e-19
    flux = _am15_flux(wl)
    lost = (1 - e) * flux * q * 0.1          # A m^-2 -> mA cm^-2 per nm (x0.1)
    regions = {"short wavelengths (< 450 nm)": (wl.min(), 450.0),
               "the middle of the spectrum": (450.0, lam_g - 50.0),
               "the 50 nm below the absorption edge": (lam_g - 50.0, lam_g)}
    out = {}
    for name, (lo, hi) in regions.items():
        m = (wl >= lo) & (wl < hi)
        out[name] = float(np.trapezoid(lost[m], wl[m])) if m.sum() > 1 else 0.0
    return out


def interpret_eqe(res: dict, wl_nm=None, eqe=None, subject: str = "") -> Report:
    """res: analyze_eqe output (Jsc_mA_cm2, Eg_Rau_eV, Eg_sigma_eV, Eu_meV, Voc_rad_V, Jsc_SQ,
    dV2_rad, dV3_nonrad, EQE_EL ...); wl_nm/eqe (% or fraction) for the spectral loss split."""
    rep = Report("EQE", subject)
    eu = res.get("Eu_meV")
    if _ok(eu):
        eu = float(eu)
        lvl = "good" if eu <= 18 else "note" if eu <= 25 else "warning"
        rep.add(lvl, "Urbach energy", f"Urbach energy {eu:.1f} meV: "
                + ("sharp absorption edge, little energetic disorder." if lvl == "good" else
                   "moderate tail." if lvl == "note" else "broad tail of sub-gap states (disorder, defects)."),
                f"Eu = {eu:.2f} meV from ln EQE below the edge", "<= 18 good, <= 25 note, > 25 warning",
                "De Wolf et al., J. Phys. Chem. Lett. 5, 1035 (2014)",
                "Improve crystallinity or composition homogeneity." if lvl == "warning" else "")
    jsc, jsq = res.get("Jsc_mA_cm2"), res.get("Jsc_SQ")
    if _ok(jsc) and _ok(jsq) and float(jsq) > 0:
        frac = 100 * float(jsc) / float(jsq)
        lvl = "good" if frac >= 85 else "note" if frac >= 75 else "warning"
        rep.add(lvl, "Current collection", f"Jsc reaches {frac:.0f} % of the Shockley-Queisser value.",
                f"Jsc = {float(jsc):.2f} of {float(jsq):.2f} mA/cm²", ">= 85 % good, < 75 % warning",
                "Rühle, Sol. Energy 130, 139 (2016)")
    if wl_nm is not None and eqe is not None and _ok(res.get("Eg_Rau_eV")):
        e = np.asarray(eqe, float)
        if np.nanmax(e) > 1.5:
            e = e / 100.0
        try:
            loss = spectral_losses(wl_nm, e, float(res["Eg_Rau_eV"]))
            main = max(loss, key=loss.get)
            ev = "; ".join(f"{k}: {v:.2f} mA/cm²" for k, v in loss.items())
            advice = {"short wavelengths (< 450 nm)": "Parasitic absorption in the glass, the transparent electrode "
                      "or the front transport layer; try a thinner or wider-gap front layer.",
                      "the middle of the spectrum": "Reflection or incomplete collection; consider an anti-reflection coating and check "
                      "the internal quantum efficiency.",
                      "the 50 nm below the absorption edge": "Weak absorption near the band gap; a thicker absorber or light "
                      "trapping helps if the diffusion length allows it."}[main]
            rep.add("note", "Where current is lost", f"Most current is lost at {main} ({loss[main]:.2f} mA/cm²).",
                    ev, "∫(1 - EQE) Φ_AM1.5G dλ per region", "ASTM G173-03", advice)
        except Exception:
            pass
    emax = np.nanmax(np.asarray(eqe, float)) if eqe is not None and len(eqe) else res.get("EQE_max")
    if _ok(emax):
        emax = float(emax) if float(emax) > 1.5 else 100 * float(emax)
        if emax < 80:
            rep.add("warning", "Peak EQE", f"The EQE never exceeds {emax:.0f} %.", f"max EQE = {emax:.1f} %",
                    "< 80 %", "", "Check reflection losses and the collection of carriers (IQE).")
    dv2 = res.get("dV2_rad")
    if _ok(dv2) and float(dv2) > 0.05:
        rep.add("note", "Radiative voltage loss", f"The non-step absorption edge costs {1000 * float(dv2):.0f} mV.",
                f"ΔV2 = Voc,SQ - Voc,rad = {1000 * float(dv2):.0f} mV", "> 50 mV",
                "Rau et al., Phys. Rev. Applied 7, 044016 (2017)", "A sharper edge (lower Eu) reduces it.")
    dv3, el = res.get("dV3_nonrad"), res.get("EQE_EL")
    if _ok(dv3):
        el = float(el) if _ok(el) else math.exp(-float(dv3) / (KB_EV * 300))
        lvl = "good" if el >= 1e-2 else "note" if el >= 1e-4 else "warning"
        rep.add(lvl, "Non-radiative voltage loss", f"Non-radiative recombination costs {1000 * float(dv3):.0f} mV "
                f"(implied EQE_EL = {el:.1e}).", f"ΔV3 = Voc,rad - Voc = {1000 * float(dv3):.0f} mV",
                "EQE_EL >= 1e-2 good, >= 1e-4 note, < 1e-4 warning", "Rau, Phys. Rev. B 76, 085303 (2007)",
                "Passivate surfaces and interfaces; check energy-level alignment of the contacts."
                if lvl == "warning" else "")
    sig = res.get("Eg_sigma_eV")
    if _ok(sig) and float(sig) > 0.04:
        rep.add("note", "Band-gap distribution", f"The band-gap distribution is broad (σ = {1000 * float(sig):.0f} meV).",
                f"σ = {1000 * float(sig):.0f} meV", "> 40 meV", "Rau et al., Phys. Rev. Applied 7, 044016 (2017)",
                "Look for compositional inhomogeneity (PL mapping, XRD peak splitting).")
    return rep


# =========================================================================== absorbance
def interpret_absorbance(res: dict, other_mode_r2: Optional[float] = None, subject: str = "") -> Report:
    """res: Tauc result (Eg, Eg_err, R2, lo, hi, mode) plus Eg_derivative and Eu_meV if known."""
    rep = Report("Absorbance", subject)
    eg, r2 = res.get("Eg"), res.get("R2")
    if _ok(eg):
        rep.add("note", "Band gap", f"Tauc band gap {float(eg):.3f} eV ({res.get('mode', 'direct')} transition).",
                f"Eg = {float(eg):.4f} ± {_f(res.get('Eg_err'), '.4f')} eV, region {_f(res.get('lo'), '.3f')}-"
                f"{_f(res.get('hi'), '.3f')} eV", "x-intercept of the straight Tauc region",
                "Tauc, Grigorovici & Vancu, Phys. Status Solidi 15, 627 (1966)")
    if _ok(r2) and float(r2) < 0.99:
        rep.add("warning", "Linearity", f"The Tauc region is not very straight (R² = {float(r2):.4f}).",
                f"R² = {float(r2):.5f}", "< 0.99", "Makuła, Pacia & Macyk, J. Phys. Chem. Lett. 9, 6814 (2018)",
                "Check the transition type and drag the range by hand.")
    if _ok(res.get("lo")) and _ok(res.get("hi")) and float(res["hi"]) - float(res["lo"]) < 0.05:
        rep.add("warning", "Fit range", "The linear region is narrower than 50 meV; the intercept is uncertain.",
                f"{float(res['hi']) - float(res['lo']):.3f} eV", "< 0.05 eV")
    egd = res.get("Eg_derivative")
    if _ok(eg) and _ok(egd):
        d = 1000 * (float(egd) - float(eg))
        ev = f"Eg(Tauc) = {float(eg):.3f}, dA/dE max = {float(egd):.3f} eV"
        ref = "Makuła, Pacia & Macyk, J. Phys. Chem. Lett. 9, 6814 (2018)"
        if d > 40:
            rep.add("note", "Tauc versus derivative", f"The Tauc gap is {d:.0f} meV below the steepest point of "
                    "the edge: a sub-gap absorbance offset (reflection, scattering, substrate), a tail or an "
                    "excitonic feature bends the edge and lowers the extrapolation.", ev, "difference > 40 meV", ref,
                    "Set Sub-gap offset to Subtract (Absorbance window) and fit again; quote both values, or use "
                    "the EQE band gap (Rau) of a device.")
        elif d < -40:
            # synthetic direct edge on a scattering background 0.05 (500 nm/λ)^4: the
            # steepest point of the Tauc curve, and so the region, moved to 2.9-3.5 eV
            rep.add("warning", "Tauc versus derivative", f"The Tauc gap is {-d:.0f} meV above the steepest point "
                    "of the edge: the automatic region sits above the edge, on a background that rises towards "
                    "short wavelengths (scattering, interference fringes) or on a higher transition.", ev,
                    "difference < -40 meV", ref, "Enter the expected gap, or drag the fit range onto the edge.")
    if _ok(other_mode_r2) and _ok(r2) and float(other_mode_r2) > float(r2) + 0.005:
        rep.add("warning", "Transition type", "The other transition type gives a straighter Tauc plot.",
                f"R² = {float(r2):.4f} (chosen) vs {float(other_mode_r2):.4f} (other)", "ΔR² > 0.005",
                "", "Check whether the material is a direct or an indirect absorber.")
    eu = res.get("Eu_meV")
    if _ok(eu) and float(eu) > 25:
        rep.add("note", "Urbach tail", f"Urbach energy {float(eu):.0f} meV from the absorbance (includes scattering).",
                f"Eu = {float(eu):.1f} meV", "> 25 meV", "De Wolf et al., J. Phys. Chem. Lett. 5, 1035 (2014)")
    return rep


# =========================================================================== PL
def interpret_pl(rows: Sequence[dict], reference: str = "", eg_ev: Optional[float] = None,
                 temperature_k: float = 298.15, subject: str = "") -> Report:
    """rows: one dict per sample with Sample, Peak (eV), FWHM (meV), Quench eta (peak) [%],
    Quench eta (integral) [%], Components."""
    rep = Report("PL", subject)
    kt = 1000 * KB_EV * temperature_k
    peaks = {}
    for r in rows:
        name = str(r.get("Sample", "?"))
        pe = _num(r.get("Peak (eV)"))
        fw = _num(r.get("FWHM (meV)"))
        if _ok(pe):
            peaks[name] = pe
        if _ok(fw):
            lvl = "warning" if fw > 130 else "note" if fw > 100 else "good"
            rep.add(lvl, f"Line width - {name}", f"{name}: FWHM {fw:.0f} meV ({fw / kt:.1f} kT)"
                    + (", broad: inhomogeneity or several emitting phases." if lvl == "warning" else
                       ", somewhat broad." if lvl == "note" else ", typical of a band-edge emission."),
                    f"FWHM = {fw:.1f} meV, kT = {kt:.1f} meV", "> 100 meV note, > 130 meV warning", "",
                    "Fit several components or check for phase segregation." if lvl == "warning" else "")
        comps = _num(r.get("Components"))
        if _ok(comps) and comps >= 2:
            rep.add("note", f"Second emission - {name}", f"{name}: {int(comps)} components needed (AICc).",
                    f"components = {int(comps)}", "AICc prefers more than one band",
                    "Akaike, IEEE Trans. Autom. Control 19, 716 (1974)",
                    "A low-energy band often comes from defects or halide segregation.")
        if name != reference:
            q = _num(r.get("Quench eta (integral)", r.get("Quench eta (peak)")))
            if _ok(q):
                if q >= 90:
                    rep.add("good", f"Quenching - {name}", f"{name}: PL quenched by {q:.0f} % against {reference}: "
                            "efficient charge extraction.", f"η = 1 - A/A_ref = {q:.1f} %", ">= 90 %",
                            "", "")
                elif q >= 50:
                    rep.add("note", f"Quenching - {name}", f"{name}: PL quenched by {q:.0f} %: partial extraction.",
                            f"η = {q:.1f} %", "50-90 %", "", "Check the interface and the transport-layer energy levels.")
                elif q < -20:
                    rep.add("good", f"Enhancement - {name}", f"{name}: PL {-q:.0f} % stronger than {reference}: "
                            "fewer non-radiative traps (passivation).", f"η = {q:.1f} %", "< -20 %")
    if reference in peaks:
        for name, pe in peaks.items():
            if name == reference:
                continue
            d = 1000 * (pe - peaks[reference])
            if abs(d) > 10:
                rep.add("note", f"Peak shift - {name}", f"{name}: peak {d:+.0f} meV from {reference}.",
                        f"{pe:.4f} vs {peaks[reference]:.4f} eV", "|shift| > 10 meV",
                        "", "A shift points to composition, strain or a changed defect emission.")
    if _ok(eg_ev) and peaks:
        for name, pe in peaks.items():
            st = 1000 * (float(eg_ev) - pe)
            if st > 60:
                rep.add("warning", f"Stokes shift - {name}", f"{name}: emission {st:.0f} meV below the band gap.",
                        f"Eg = {float(eg_ev):.3f}, PL = {pe:.3f} eV", "> 60 meV", "",
                        "Tail states or a lower-gap phase dominate the emission.")
    return rep


def _num(v):
    if isinstance(v, str):
        v = v.replace("%", "").strip()
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# =========================================================================== XRD
IMPURITY_LINES = [  # 2θ (Cu Kα), phase - common in perovskite and thin-film work
    (12.7, 0.25, "PbI2 (001)"), (11.8, 0.3, "δ-FAPbI3 (hexagonal)"), (15.5, 0.3, "PbBr2"),
    (26.6, 0.2, "SnO2 (110) of FTO"), (30.3, 0.2, "In2O3 (222) of ITO"), (28.44, 0.15, "Si (111)"),
    (38.2, 0.2, "Au (111)"), (44.4, 0.2, "Au (200)"), (38.1, 0.2, "Ag (111)"), (25.3, 0.2, "anatase TiO2 (101)"),
    (27.4, 0.2, "rutile TiO2 (110)"), (31.8, 0.2, "ZnO (100)"), (34.4, 0.2, "ZnO (002)"),
]


def interpret_xrd(peaks: Sequence[dict], wh: Optional[dict] = None, match: Optional[dict] = None,
                  crystallinity: Optional[float] = None, subject: str = "") -> Report:
    """peaks: rows with 2Theta, FWHM, tau (nm) [Scherrer]; wh: Williamson-Hall (D_nm, strain, R2);
    match: reference matching (coverage, unassigned rows, mean_shift_deg, mean_strain, matches)."""
    rep = Report("XRD", subject)
    if hasattr(peaks, "to_dict"):
        peaks = peaks.to_dict("records")
    sizes = [_num(p.get("Crystallite_nm", p.get("tau (nm)", p.get("Size (nm)", p.get("tau"))))) for p in peaks]
    sizes = [s for s in sizes if _ok(s)]
    if sizes:
        rep.add("note", "Crystallite size", f"Scherrer sizes {min(sizes):.0f}-{max(sizes):.0f} nm "
                f"(median {np.median(sizes):.0f} nm).", f"{len(sizes)} reflections", "τ = Kλ/(β cos θ)",
                "Langford & Wilson, J. Appl. Cryst. 11, 102 (1978)",
                "Enter the instrument FWHM: without it the sizes are lower bounds.")
        big = [s_ for s_ in sizes if s_ > 150]
        if big:
            rep.add("note", "Size limit", f"{len(big)} reflection(s) give sizes above 150 nm, beyond what line "
                    "broadening resolves.", f"max {max(sizes):.0f} nm", "> 150 nm",
                    "Langford & Wilson, J. Appl. Cryst. 11, 102 (1978)", "Quote these as '> 150 nm'.")
    if wh:
        d, eps, r2 = wh.get("D_nm"), wh.get("strain"), wh.get("R2")
        if _ok(eps):
            if float(eps) < 0:
                rep.add("warning", "Williamson-Hall", "The Williamson-Hall slope is negative (unphysical): broadening "
                        "is anisotropic or the instrument width is wrong.", f"ε = {float(eps):.2e}", "ε < 0",
                        "Williamson & Hall, Acta Metall. 1, 22 (1953)", "Check the instrument FWHM; use Scherrer sizes.")
            elif float(eps) > 1e-3:
                rep.add("note", "Microstrain", f"Microstrain {float(eps) * 100:.2f} % (Williamson-Hall).",
                        f"ε = {float(eps):.2e}, D = {_f(d, '.0f')} nm, R² = {_f(r2, '.3f')}", "ε > 0.1 %",
                        "Williamson & Hall, Acta Metall. 1, 22 (1953)")
        if _ok(d) and sizes and float(d) > 0 and (float(d) > 2 * np.median(sizes) or float(d) < 0.5 * np.median(sizes)):
            rep.add("note", "Size estimates", "Scherrer and Williamson-Hall sizes differ by more than a factor of two: "
                    "strain broadening is significant.", f"D(W-H) = {float(d):.0f} nm, median Scherrer = "
                    f"{np.median(sizes):.0f} nm", "ratio > 2")
    if match:
        cov = match.get("coverage")
        if _ok(cov):
            lvl = "good" if cov >= 0.8 else "note" if cov >= 0.5 else "warning"
            rep.add(lvl, "Phase identification", f"{100 * cov:.0f} % of the reference lines are present.",
                    f"{match.get('n_matched', '?')}/{match.get('n_reference_lines', '?')} lines", ">= 80 % good, < 50 % warning",
                    "", "Check the reference phase or the 2θ calibration." if lvl == "warning" else "")
        sh = match.get("mean_shift_deg")
        if _ok(sh) and abs(float(sh)) > 0.05:
            rep.add("note", "Peak shift", f"Peaks are shifted by {float(sh):+.3f}° on average from the reference.",
                    f"mean strain {_f(match.get('mean_strain'), '.2e')}", "|shift| > 0.05°",
                    "", "Lattice strain, composition, or sample displacement (use Nelson-Riley or an internal standard).")
        unassigned = match.get("unassigned")
        if hasattr(unassigned, "to_dict"):
            unassigned = unassigned.to_dict("records")
        for u in unassigned or []:
            tt = _num(u.get("2Theta") if isinstance(u, dict) else u)
            cand = [name for pos, tol, name in IMPURITY_LINES if _ok(tt) and abs(tt - pos) <= tol]
            rep.add("warning" if cand else "note", "Unassigned reflection",
                    f"Reflection at {tt:.2f}° belongs to no reference line" + (f"; it matches {cand[0]}." if cand else "."),
                    f"2θ = {tt:.3f}°", "no reference line within the tolerance; list of common secondary phases",
                    "", ("Secondary phase: " + cand[0] + ". Check annealing or stoichiometry.") if cand else
                    "Identify the phase with a database search.")
        tcs = _texture(match)
        if tcs:
            hkl, tc = max(tcs.items(), key=lambda kv: kv[1])
            if tc > 1.5:
                rep.add("note", "Preferred orientation", f"The ({hkl}) reflection is {tc:.1f} times stronger than "
                        "expected relative to the others: preferred orientation.", "Harris texture coefficient",
                        "TC > 1.5", "Harris, Philos. Mag. 43, 113 (1952)")
    if _ok(crystallinity):
        c = float(crystallinity)
        if c < 50:
            rep.add("note", "Crystallinity", f"Crystallinity index {c:.0f} % (area above the ALS background).",
                    f"{c:.1f} %", "< 50 %", "", "An amorphous background or the substrate contributes.")
    return rep


def _texture(match: dict) -> Dict[str, float]:
    rows = match.get("matches")
    try:
        import pandas as pd
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows or [])
    except Exception:
        return {}
    if df.empty or not {"I_obs", "I_ref"}.issubset(df.columns):
        return {}
    df = df[(df["I_ref"] > 0) & (df["I_obs"] > 0)]
    if len(df) < 3:
        return {}
    ratio = df["I_obs"] / df["I_ref"]
    tc = ratio / ratio.mean()
    key = df["hkl"].astype(str).str.strip("()") if "hkl" in df.columns else df.index.astype(str)
    return dict(zip(key, tc))


# =========================================================================== SEM
def interpret_sem(diameters_nm: Sequence[float], subject: str = "") -> Report:
    from scipy import stats
    rep = Report("FE-SEM", subject)
    d = np.asarray([x for x in diameters_nm if _ok(x) and x > 0], float)
    if len(d) == 0:
        return rep
    if len(d) < 50:
        rep.add("note", "Sample size", f"Only {len(d)} grains measured; size statistics need about 100.",
                f"N = {len(d)}", "N < 50", "", "Measure more grains or several images.")
    cv = d.std(ddof=1) / d.mean() if len(d) > 1 else float("nan")
    gsd = math.exp(np.std(np.log(d), ddof=1)) if len(d) > 1 else float("nan")
    if _ok(cv):
        lvl = "good" if cv < 0.3 else "note" if cv < 0.5 else "warning"
        rep.add(lvl, "Size distribution", f"Mean diameter {d.mean():.0f} nm, median {np.median(d):.0f} nm, "
                f"coefficient of variation {cv:.2f}.", f"geometric SD {gsd:.2f}", "CV < 0.3 narrow, > 0.5 broad",
                "", "Broad distributions often come from uneven nucleation; adjust the anti-solvent step or annealing."
                if lvl == "warning" else "")
    if len(d) >= 20:
        g1 = float(stats.skew(d))
        g2 = float(stats.kurtosis(d))
        n = len(d)
        bc = (g1 ** 2 + 1) / (g2 + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
        if bc > 0.555:
            rep.add("warning", "Bimodality", f"The size distribution looks bimodal (bimodality coefficient {bc:.2f}).",
                    f"BC = {bc:.3f}", "BC > 0.555 (uniform distribution)", "SAS Institute; Pfister et al., Front. "
                    "Psychol. 4, 700 (2013)", "Two grain populations: secondary nucleation or a second phase.")
        lnd = np.log(d)
        ks = stats.kstest((lnd - lnd.mean()) / lnd.std(ddof=1), "norm")
        if ks.pvalue < 0.05:
            rep.add("note", "Distribution shape", "The diameters do not follow a log-normal distribution well.",
                    f"Kolmogorov-Smirnov p = {ks.pvalue:.3g} on ln d", "p < 0.05",
                    "", "Report median and D10/D90 rather than the log-normal parameters.")
    small = np.mean(d < 0.5 * np.median(d))
    if small > 0.2:
        rep.add("note", "Small grains", f"{100 * small:.0f} % of the grains are smaller than half the median.",
                f"fraction = {small:.2f}", "> 20 %")
    return rep


# =========================================================================== Raman / FTIR
FTIR_GROUPS = [  # (lo, hi, group, hint)
    (3200, 3600, "O-H stretch", "adsorbed water or hydroxyl groups: check moisture exposure"),
    (3050, 3200, "N-H stretch", "organic ammonium/formamidinium cations"),
    (2840, 2960, "C-H stretch", "organic cation, ligands or residual solvent"),
    (1690, 1760, "C=O stretch", "residual solvent (DMF), ligands or oxidation products"),
    (1600, 1720, "C=N / N-H bend", "formamidinium or amine groups"),
    (1000, 1150, "C-O / C-N stretch", "organic species"),
]


def interpret_vibrational(technique: str, bands: Sequence[float], assignments: Optional[Sequence[dict]] = None,
                          shifts: Optional[Sequence[dict]] = None, subject: str = "") -> Report:
    rep = Report(technique.upper() if technique.lower() == "ftir" else technique.capitalize(), subject)
    bands = [float(b) for b in bands if _ok(b)]
    if bands:
        rep.add("note", "Bands", f"{len(bands)} bands detected: " + ", ".join(f"{b:.0f}" for b in sorted(bands)) + " cm⁻¹.",
                "", "prominence above the noise floor")
    for a in assignments or []:
        mat = a.get("material") or a.get("assignment")
        if mat:
            rep.add("note", f"Assignment {float(a.get('position', a.get('band', 0))):.0f} cm⁻¹",
                    f"Band near {float(a.get('position', a.get('band', 0))):.0f} cm⁻¹ matches {mat}"
                    + (f" ({a.get('mode')})" if a.get("mode") else "") + ".",
                    f"library value {a.get('library', '-')} cm⁻¹, distance {_f(a.get('distance'), '.1f')} cm⁻¹",
                    "within the library tolerance", "Physiscore band library (indicative)")
    if technique.lower() == "ftir":
        for lo, hi, grp, hint in FTIR_GROUPS:
            hit = [b for b in bands if lo <= b <= hi]
            if hit:
                rep.add("note", grp, f"Band at {hit[0]:.0f} cm⁻¹: {grp} - {hint}.", f"{lo}-{hi} cm⁻¹",
                        "functional-group region", "Socrates, Infrared and Raman Characteristic Group Frequencies (2001)")
    for s in shifts or []:
        sh = _num(s.get("shift"))
        if _ok(sh) and abs(sh) > 3:
            rep.add("note", "Band shift", f"Band near {_num(s.get('reference')):.0f} cm⁻¹ shifts by {sh:+.1f} cm⁻¹.",
                    "", "|shift| > 3 cm⁻¹", "", "Strain, composition, or interaction with the adjacent layer.")
        dw = _num(s.get("width_change"))
        if _ok(dw) and dw > 20:
            rep.add("note", "Band broadening", f"Band near {_num(s.get('reference')):.0f} cm⁻¹ is {dw:.0f} % broader.",
                    "", "> 20 %", "", "Disorder or a smaller crystallite size.")
    return rep


# =========================================================================== XPS
DOUBLETS = {"Pb 4f": 4.87, "I 3d": 11.5, "Sn 3d": 8.41, "Ti 2p": 5.7, "Br 3d": 1.05, "Cs 3d": 13.9}


def interpret_xps(components: Sequence[dict], atomic: Optional[Dict[str, float]] = None,
                  region: str = "", subject: str = "") -> Report:
    """components: centre (eV), area, fwhm; atomic: element -> at.% if quantified; region e.g. 'Pb 4f'."""
    rep = Report("XPS", subject)
    comps = sorted([c for c in components if _ok(c.get("center"))], key=lambda c: float(c["center"]))
    if comps:
        rep.add("note", "Components", f"{len(comps)} components at " +
                ", ".join(f"{float(c['center']):.2f}" for c in comps) + " eV.", "", "Voigt fits on the corrected spectrum")
    for c in comps:
        fw = _num(c.get("fwhm"))
        if _ok(fw) and fw > 2.5:
            rep.add("warning", "Broad component", f"Component at {float(c['center']):.2f} eV is {fw:.1f} eV wide: "
                    "several chemical states may be merged.", f"FWHM = {fw:.2f} eV", "> 2.5 eV", "",
                    "Fit with more components or a doublet constraint.")
    pb = [c for c in comps if 136.0 <= float(c["center"]) <= 144.5]
    if pb:
        main = max(pb, key=lambda c: _num(c.get("area", c.get("area_amplitude"))))
        m0 = float(main["center"])
        if 137.8 <= m0 <= 139.3:
            metal = [c for c in pb if -2.2 <= float(c["center"]) - m0 <= -1.3]
            if metal:
                a_m = _num(metal[0].get("area", metal[0].get("area_amplitude")))
                a_0 = _num(main.get("area", main.get("area_amplitude")))
                frac = 100 * a_m / (a_m + a_0) if _ok(a_m) and _ok(a_0) and (a_m + a_0) > 0 else float("nan")
                rep.add("warning", "Metallic lead", f"A Pb⁰ component {m0 - float(metal[0]['center']):.2f} eV below "
                        f"Pb²⁺ 4f7/2 ({_f(frac, '.0f')} % of Pb 4f7/2).",
                        f"Pb²⁺ {m0:.2f} eV, Pb⁰ {float(metal[0]['center']):.2f} eV", "component 1.3-2.2 eV below Pb²⁺",
                        "Sadoughi et al., ACS Appl. Mater. Interfaces 7, 13440 (2015)",
                        "Metallic lead forms by iodide loss, X-ray or light damage: check exposure and stoichiometry.")
            partner = [c for c in pb if abs(float(c["center"]) - m0 - DOUBLETS["Pb 4f"]) < 0.25]
            if partner:
                a5 = _num(partner[0].get("area", partner[0].get("area_amplitude")))
                a7 = _num(main.get("area", main.get("area_amplitude")))
                if _ok(a5) and _ok(a7) and a7 > 0:
                    ratio = a5 / a7
                    lvl = "good" if abs(ratio - 0.75) < 0.1 else "warning"
                    rep.add(lvl, "Spin-orbit doublet", f"Pb 4f5/2 : 4f7/2 area ratio {ratio:.2f} (expected 0.75).",
                            f"split {float(partner[0]['center']) - m0:.2f} eV (expected 4.87)", "|ratio - 0.75| < 0.1",
                            "Moulder et al., Handbook of XPS (1992)",
                            "Check the background and the component overlap." if lvl == "warning" else "")
    if atomic:
        i, pbv = atomic.get("I"), atomic.get("Pb")
        if _ok(i) and _ok(pbv) and float(pbv) > 0:
            r = float(i) / float(pbv)
            lvl = "good" if 2.7 <= r <= 3.3 else "warning"
            rep.add(lvl, "Stoichiometry", f"I/Pb = {r:.2f} (3 for APbI3).", f"I {float(i):.1f} at.%, Pb {float(pbv):.1f} at.%",
                    "2.7-3.3", "", "Iodide-poor surface: check annealing and storage." if r < 2.7 else
                    ("Excess iodide at the surface (PbI2-poor or I2 adsorption)." if lvl == "warning" else ""))
        c = atomic.get("C")
        if _ok(c) and float(c) > 40:
            rep.add("note", "Surface carbon", f"Carbon is {float(c):.0f} at.% of the surface.", "", "> 40 at.%",
                    "Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020)",
                    "Adventitious carbon dominates; quantify the other elements with care.")
    return rep


# =========================================================================== device summary
def interpret_device(s: dict, subject: str = "") -> Report:
    """s: scripts.common.device_summary.summarize_device output."""
    rep = Report("Device summary", subject)
    mm = s.get("Jsc_mismatch_percent")
    if _ok(mm):
        lvl = "good" if abs(mm) <= 5 else "warning" if abs(mm) <= 10 else "problem"
        rep.add(lvl, "Jsc cross-check", f"J-V and EQE currents differ by {float(mm):+.1f} %.",
                f"Jsc(J-V) {_f(s.get('JV_Jsc'), '.2f')} vs Jsc(EQE) {_f(s.get('EQE_Jsc'), '.2f')} mA/cm²",
                "|mismatch| <= 5 % good, > 10 % problem", "Snaith, Energy Environ. Sci. 5, 9296 (2012)",
                "Check the spectral mismatch factor, lamp calibration and the device area." if lvl != "good" else "")
    sp = s.get("Eg_spread_meV")
    if _ok(sp):
        lvl = "good" if sp <= 30 else "note" if sp <= 60 else "warning"
        rep.add(lvl, "Band gap agreement", f"EQE, Tauc and PL band gaps agree within {float(sp):.0f} meV.",
                f"EQE {_f(s.get('EQE_Eg'), '.3f')}, Tauc {_f(s.get('Eg_Abs'), '.3f')}, PL {_f(s.get('Eg_PL'), '.3f')} eV",
                "<= 30 meV good, > 60 meV warning", "Rau et al., Phys. Rev. Applied 7, 044016 (2017)")
    for key, label in (("Voc_fraction_of_SQ", "Voc"), ("Jsc_fraction_of_SQ", "Jsc"), ("FF_fraction_of_SQ", "FF"),
                       ("PCE_fraction_of_SQ", "PCE")):
        v = s.get(key)
        if _ok(v):
            pct = 100 * float(v) if float(v) <= 1.5 else float(v)
            rep.add("note", f"{label} versus the limit", f"{label} reaches {pct:.0f} % of its Shockley-Queisser value.",
                    f"{key} = {float(v):.3f}", "", "Rühle, Sol. Energy 130, 139 (2016)")
    dv1, dv2, dv3 = s.get("dV1_SQ"), s.get("dV2_rad"), s.get("dV3_nonrad")
    if _ok(dv3):
        parts = {"unavoidable (SQ)": dv1, "radiative (edge shape)": dv2, "non-radiative": dv3}
        parts = {k: float(v) for k, v in parts.items() if _ok(v)}
        main = max(parts, key=parts.get)
        rep.add("warning" if main == "non-radiative" and parts[main] > 0.15 else "note", "Voltage loss",
                "Of the Voc deficit, " + ", ".join(f"{k} {1000 * v:.0f} mV" for k, v in parts.items())
                + f"; the largest avoidable part is {'non-radiative' if parts.get('non-radiative', 0) >= parts.get('radiative (edge shape)', 0) else 'radiative'} recombination.",
                f"Eg/q - Voc = {1000 * sum(parts.values()):.0f} mV", "ΔV1 + ΔV2 + ΔV3 (detailed balance)",
                "Rau, Phys. Rev. B 76, 085303 (2007)",
                "Passivation and contact energy alignment address the non-radiative part.")
    for w in s.get("warnings", []) or []:
        rep.add("warning", "Check", str(w), "", "device-summary consistency checks")
    return rep


# =========================================================================== adapters (window results)
def _row_value(row, *names):
    for n in names:
        if n in row and _ok(row[n]):
            return float(row[n])
    return float("nan")


def interpret_jv_results(processed: dict, selected: Optional[str] = None) -> Report:
    """Interpret the result of jv_core.process_jv_directory: the best device of each
    condition (or the selected device), and the statistics between conditions."""
    import pandas as pd
    rep = Report("J-V", selected or "")
    if not processed:
        return rep
    ca = processed.get("curve_analysis")
    bp = processed.get("best_performance")
    hy = processed.get("hysteresis_df")
    devices = []
    if selected:
        devices = [selected]
    elif bp is not None and "Original_Filename" in getattr(bp, "columns", []):
        devices = [str(x) for x in bp["Original_Filename"].dropna()]
    if ca is not None and not ca.empty:
        for dev in devices[:6]:
            row = ca.loc[ca["Filename"] == dev]
            if not len(row):
                continue
            r = row.iloc[0]
            summary = {"Voc": _row_value(r, "Voc (V)"), "Jsc": _row_value(r, "Jsc (mA/cm2)"),
                       "FF": _row_value(r, "FF (%)"), "PCE": _row_value(r, "PCE (%)"),
                       "Rs": _row_value(r, "Rs (Ohm cm2)"), "Rsh": _row_value(r, "Rsh (Ohm cm2)")}
            fit = {"n": _row_value(r, "n (diode fit)"), "J0": _row_value(r, "J0 fit (mA/cm2)"),
                   "Rs": _row_value(r, "Rs fit (Ohm cm2)"), "Rsh": _row_value(r, "Rsh fit (Ohm cm2)"),
                   "R2": _row_value(r, "Diode fit R2")}
            hi = None
            if hy is not None and not hy.empty:
                h = hy.loc[hy["Filename"] == dev]
                if len(h) and _ok(h.iloc[0].get("HI (%)")):
                    hi = float(h.iloc[0]["HI (%)"])
            sub = interpret_jv(summary, fit=fit, hysteresis_index=hi)
            for f in sub.findings:
                f.topic = f"{dev}: {f.topic}" if len(devices) > 1 else f.topic
            rep.extend(sub)
    sd = processed.get("summary_df")
    if not selected and sd is not None and not sd.empty and "Base_Name" in sd.columns:
        groups, names = {}, {}
        for cond, g in sd.groupby("Base_Name"):
            cond = str(cond).strip()
            groups[cond] = {"PCE": pd.to_numeric(g["PCE (%)"], errors="coerce").to_list(),
                            "Voc": pd.to_numeric(g["Voc V"], errors="coerce").to_list(),
                            "Jsc": pd.to_numeric(g["Jsc mA/cm2"], errors="coerce").abs().to_list(),
                            "FF": pd.to_numeric(g["Fill Factor"], errors="coerce").to_list()}
            names[cond] = [str(x) for x in g["Filename"]]
        if len(groups) >= 1:
            rep.extend(interpret_statistics(groups, names=names))
    return rep


def interpret_dark_results(summary_df, selected: Optional[str] = None) -> Report:
    rep = Report("J-V dark", selected or "")
    if summary_df is None or summary_df.empty:
        return rep
    rows = summary_df if not selected else summary_df.loc[summary_df["Filename"] == selected]
    many = len(rows) > 1
    for _, r in rows.head(12).iterrows():
        sub = interpret_dark(r.to_dict(), subject=str(r.get("Filename", "")))
        for f in sub.findings:
            if many:
                f.topic = f"{r.get('Filename', '')}: {f.topic}"
        rep.extend(sub)
    return rep


# =========================================================================== auto-fit peak tables
CU_KA1_NM = 0.15406
HC_EV_NM = 1239.84193


def _wh_fit(two_theta_deg, beta_deg, wavelength_nm: float, k: float) -> Optional[dict]:
    """Williamson-Hall: β cos θ = Kλ/D + 4ε sin θ (β in radians)."""
    th = np.radians(np.asarray(two_theta_deg, float) / 2)
    b = np.radians(np.asarray(beta_deg, float))
    ok = np.isfinite(th) & np.isfinite(b) & (b > 0)
    if ok.sum() < 3:
        return None
    xs, ys = 4 * np.sin(th[ok]), b[ok] * np.cos(th[ok])
    slope, icept = np.polyfit(xs, ys, 1)
    pred = slope * xs + icept
    ss = float(np.sum((ys - ys.mean()) ** 2))
    r2 = 1 - float(np.sum((ys - pred) ** 2)) / ss if ss > 0 else float("nan")
    d = k * wavelength_nm / icept if icept > 0 else float("nan")
    return {"D_nm": d, "strain": float(slope), "R2": r2, "n": int(ok.sum())}


def interpret_peak_fit(technique: str, fitted, subject: str = "", wavelength_nm: float = CU_KA1_NM,
                       instrument_fwhm_deg: float = 0.0, scherrer_k: float = 0.9) -> Report:
    """Fit-quality rules for the auto-fit workspaces, then the technique rules.

    fitted: the peak table of spectra.pipelines (center, height, fwhm or fwhm_x,
    area_amplitude, snr, noise_sigma, redchi, region_xmin). XRD centres are 2θ (deg),
    PL centres are nm (or eV when below 20), XPS centres are binding energies (eV).
    """
    import pandas as pd
    tech = str(technique).upper()
    rep = Report(f"{tech} peak fit", subject)
    if fitted is None or len(fitted) == 0:
        rep.add("warning", "No peaks", "No peak survived detection and fitting.", "", "", "",
                "Lower the noise threshold k, or check the baseline and the x range.")
        return rep
    df = pd.DataFrame(fitted).copy()
    if "fwhm" not in df.columns and "fwhm_x" in df.columns:
        df["fwhm"] = df["fwhm_x"]
    df["center"] = pd.to_numeric(df["center"], errors="coerce")
    df = df[df["center"].notna()].sort_values("center").reset_index(drop=True)
    unit = {"XRD": "°", "XPS": " eV"}.get(tech, "")

    # ---- detection and quantification limits (Currie)
    if "snr" in df.columns:
        snr = pd.to_numeric(df["snr"], errors="coerce")
        weak, loq = df[snr < 3], df[(snr >= 3) & (snr < 10)]
        ref_c = "Currie, Anal. Chem. 40, 586 (1968)"
        if len(weak):
            rep.add("warning", "Detection limit", f"{len(weak)} peak(s) have S/N below 3 and may be noise: "
                    + ", ".join(f"{c:.4g}{unit}" for c in weak["center"]) + ".",
                    "S/N = height / noise σ", "S/N < 3 (limit of detection)", ref_c,
                    "Raise the noise threshold k or measure longer before reporting these.")
        if len(loq):
            rep.add("note", "Quantification limit", f"{len(loq)} peak(s) have S/N between 3 and 10: detected, but "
                    "their area and width carry large errors.", ", ".join(f"{c:.4g}{unit}" for c in loq["center"]),
                    "3 <= S/N < 10 (below the limit of quantification)", ref_c)
        good = int((snr >= 10).sum())
        if good:
            rep.add("good", "Signal", f"{good} of {len(df)} peaks have S/N >= 10.", "", "S/N >= 10", ref_c)

    # ---- resolution of neighbouring peaks
    if "fwhm" in df.columns and len(df) > 1:
        w = pd.to_numeric(df["fwhm"], errors="coerce").to_numpy(float)
        c = df["center"].to_numpy(float)
        pairs = [(c[i], c[i + 1]) for i in range(len(c) - 1)
                 if _ok(w[i]) and _ok(w[i + 1]) and (c[i + 1] - c[i]) < 0.5 * (w[i] + w[i + 1])]
        if pairs:
            rep.add("note", "Unresolved peaks", f"{len(pairs)} neighbouring pair(s) are closer than their mean FWHM, "
                    "so their areas and widths are strongly correlated: "
                    + ", ".join(f"{a:.4g}/{b:.4g}{unit}" for a, b in pairs[:4]) + ".",
                    "", "Δx < (w1 + w2)/2", "",
                    "Constrain widths (or a doublet separation) or report the summed area.")

    # ---- residual against noise
    if {"redchi", "noise_sigma"} <= set(df.columns):
        key = "region_xmin" if "region_xmin" in df.columns else "center"
        bad = []
        for _, g in df.groupby(key):
            rc, ns = _num(g["redchi"].iloc[0]), _num(g["noise_sigma"].iloc[0])
            if _ok(rc) and _ok(ns) and ns > 0 and rc / ns ** 2 > 4:
                bad.append((float(g["center"].min()), rc / ns ** 2))
        if bad:
            rep.add("warning", "Fit residual", f"In {len(bad)} region(s) the residual is more than twice the noise: "
                    "a component is missing or the line shape is wrong.",
                    ", ".join(f"{x0:.4g}{unit}: χ²ν/σ² = {r:.1f}" for x0, r in bad[:4]), "χ²ν / σ² > 4",
                    "Bevington & Robinson, Data Reduction and Error Analysis (2003)",
                    "Add a component, or switch the line shape (Gaussian/Lorentzian fraction).")

    # ---- technique rules
    if tech == "XRD":
        tt = df["center"].to_numpy(float)
        fw = pd.to_numeric(df.get("fwhm"), errors="coerce").to_numpy(float) if "fwhm" in df.columns else np.full(len(df), np.nan)
        inst = float(instrument_fwhm_deg or 0.0)
        beta = np.sqrt(np.clip(fw ** 2 - inst ** 2, 0, None)) if inst > 0 else fw
        th = np.radians(tt / 2)
        with np.errstate(divide="ignore", invalid="ignore"):
            tau = scherrer_k * wavelength_nm / (np.radians(beta) * np.cos(th))
        rows = [{"2Theta": a, "FWHM": b, "Crystallite_nm": (t if np.isfinite(t) and t > 0 else float("nan"))}
                for a, b, t in zip(tt, beta, tau)]
        rep.extend(interpret_xrd(rows, wh=_wh_fit(tt, beta, wavelength_nm, scherrer_k)))
        for a in tt:
            cand = [name for pos, tol, name in IMPURITY_LINES if abs(a - pos) <= tol]
            if cand:
                rep.add("note", "Known line", f"The peak at {a:.2f}° coincides with {cand[0]}.", f"2θ = {a:.3f}°",
                        "within the listed tolerance (Cu Kα)", "",
                        "Confirm with a second reflection of the same phase before assigning it.")
    elif tech == "PL":
        c = df["center"].to_numpy(float)
        h = pd.to_numeric(df["height"], errors="coerce").to_numpy(float)
        fw = pd.to_numeric(df.get("fwhm"), errors="coerce").to_numpy(float) if "fwhm" in df.columns else np.full(len(df), np.nan)
        in_nm = np.nanmedian(c) > 20
        e = HC_EV_NM / c if in_nm else c
        fw_mev = 1000 * (HC_EV_NM * fw / c ** 2 if in_nm else fw)
        i = int(np.nanargmax(h))
        strong = int(np.sum(h >= 0.2 * h[i]))
        rep.extend(interpret_pl([{"Sample": subject or "spectrum", "Peak (eV)": e[i], "FWHM (meV)": fw_mev[i]}]))
        if strong >= 2:
            j = [k for k in np.argsort(-h) if k != i][0]
            d = 1000 * (e[j] - e[i])
            rep.add("note", "Second band", f"The second band sits {d:+.0f} meV from the main emission "
                    f"({100 * h[j] / h[i]:.0f} % of its height).", f"{e[i]:.3f} eV and {e[j]:.3f} eV",
                    "height >= 20 % of the main peak", "",
                    "A band below the main peak points to a lower-gap phase or halide segregation; above it, "
                    "to a wider-gap phase or a hot-carrier/excitonic feature." if abs(d) > 30 else "")
    elif tech == "XPS":
        comps = [{"center": r["center"], "area": _num(r.get("area_amplitude", r.get("area"))), "fwhm": _num(r.get("fwhm"))}
                 for _, r in df.iterrows()]
        rep.extend(interpret_xps(comps))
        cs = [x for x in comps if _ok(x["area"])]
        if cs and all(280 <= x["center"] <= 296 for x in cs):
            main = max(cs, key=lambda x: x["area"])
            if 283.5 <= main["center"] <= 286.5 and abs(main["center"] - 284.8) > 0.3:
                rep.add("note", "Charge reference", f"The main C 1s component is at {main['center']:.2f} eV; a shift of "
                        f"{284.8 - main['center']:+.2f} eV brings C-C to the 284.8 eV convention.",
                        f"C 1s main {main['center']:.2f} eV", "|C-C - 284.8| > 0.3 eV",
                        "Greczynski & Hultman, Prog. Mater. Sci. 107, 100591 (2020)",
                        "Enter the shift as the charge correction; the convention itself is debated, so state it.")
        if cs and all(527 <= x["center"] <= 536 for x in cs):
            tot = sum(x["area"] for x in cs)
            mid = sum(x["area"] for x in cs if 530.8 <= x["center"] <= 532.3)
            if tot > 0 and mid > 0:
                rep.add("note", "O 1s", f"{100 * mid / tot:.0f} % of the O 1s area lies at 530.8-532.3 eV.",
                        "", "531-532 eV band",
                        "Idriss, Surf. Sci. 712, 121894 (2021)",
                        "This band is hydroxyl, carbonate or adsorbed species; do not read it as oxygen vacancies.")
    return rep
