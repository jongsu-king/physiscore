"""Rule-based interpretation of the transport, dynamics and stability tools
added in 3.5 (SCLC, intensity dependence, TRPL, impedance, C-V, stability).

Same contract as scripts.common.interpret: each finding states the evidence,
the rule and a reference. The plain-language checks each core already
produced are passed through as warnings; the rules here add the grading of
values inside their normal range and raise to "problem" the cases where a
number must not be reported as it stands."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from scripts.common.interpret import Report, _f, _ok

REF_LECORRE = "Le Corre et al., ACS Energy Lett. 6, 1087 (2021)"
REF_DUIJNSTEE = "Duijnstee et al., ACS Energy Lett. 5, 376 (2020)"
REF_ROHR = "Röhr et al., J. Phys.: Condens. Matter 30, 105901 (2018)"
REF_TRESS = "Tress et al., Energy Environ. Sci. 11, 151 (2018)"
REF_CAPRIOGLIO = "Caprioglio et al., Adv. Energy Mater. 10, 2000502 (2020)"
REF_KOSTER = "Koster et al., Appl. Phys. Lett. 86, 123509 (2005)"
REF_KOSTER_JSC = "Koster et al., Appl. Phys. Lett. 87, 203502 (2005)"
REF_MIHAILETCHI = "Mihailetchi et al., Phys. Rev. Lett. 94, 126602 (2005)"
REF_SINTON = "Sinton, Cuevas, Proc. 16th EU PVSEC, 1152 (2000)"
REF_LAKOWICZ = "Lakowicz, Principles of Fluorescence Spectroscopy, 3rd ed. (2006), ch. 4"
REF_OCONNOR = "O'Connor, Phillips, Time-Correlated Single Photon Counting (Academic Press, 1984), ch. 7"
REF_KRUECKEMEIER = "Krückemeier et al., Adv. Energy Mater. 11, 2003489 (2021)"
REF_KIRCHARTZ_PL = "Kirchartz et al., Adv. Energy Mater. 10, 1904134 (2020)"
REF_SCHOENLEBER = "Schönleber et al., Electrochim. Acta 131, 20 (2014)"
REF_WAN_DRT = "Wan, Saccoccio, Chen, Ciucci, Electrochim. Acta 184, 483 (2015)"
REF_GUERRERO = "Guerrero et al., Chem. Rev. 121, 14430 (2021)"
REF_VONHAUFF = "von Hauff, Klotz, J. Mater. Chem. C 10, 742 (2022)"
REF_HSU = "Hsu, Mansfeld, Corrosion 57, 747 (2001)"
REF_RAVISHANKAR = "Ravishankar et al., Science 371, eabd8014 (2021)"
REF_KIRCHARTZ_CV = "Kirchartz et al., J. Phys. Chem. C 116, 7672 (2012)"
REF_ALMORA = "Almora et al., Appl. Phys. Lett. 109, 173903 (2016)"
REF_KHENKIN = "Khenkin et al., Nat. Energy 5, 35 (2020)"
REF_ROESCH = "Roesch et al., Adv. Energy Mater. 5, 1501407 (2015)"


def _pass_checks(rep: Report, warnings: Sequence[str], skip: Sequence[str] = (), ref: str = "") -> None:
    for w in warnings or []:
        if not any(s in w for s in skip):
            rep.add("warning", "Check", str(w), "", "analysis checks", ref)


# --------------------------------------------------------------------------- SCLC
def interpret_sclc(r: dict, subject: str = "") -> Report:
    rep = Report("SCLC", subject)
    ch, mu = r.get("child"), r.get("mobility_cm2_Vs")
    if ch is None or not _ok(mu):
        rep.add("problem", "Mott-Gurney region", "No region with J proportional to V² was found, so the mobility "
                "cannot be read from this curve.", f"largest local slope {_f(r.get('max_slope'), '.2f')}",
                "slope d log J / d log V within 1.65-2.45 over at least 3 points", REF_ROHR,
                "Extend the voltage range, or check that the device is single-carrier with injecting contacts.")
    else:
        dev = abs(float(r["child_slope"]) - 2.0)
        rep.add("good" if dev <= 0.25 else "warning", "Mott-Gurney region",
                f"A space-charge-limited region is present; the mobility from the Mott-Gurney law is "
                f"{float(mu):.3g} cm²/Vs.",
                f"slope {float(r['child_slope']):.2f} from {ch['v_lo']:.3g} to {ch['v_hi']:.3g} V, "
                f"std. error {_f(r.get('mobility_err'), '.2g')} cm²/Vs",
                "J = (9/8) eps mu V² / L³ with the slope fixed at 2; |slope - 2| <= 0.25", REF_ROHR,
                "" if dev <= 0.25 else "A slope away from 2 means a field-dependent mobility, traps or a barrier; "
                "the Mott-Gurney value is then only an effective number.")
    nt, nmin = r.get("n_t_cm3"), r.get("n_t_min_cm3")
    if _ok(nt) and _ok(nmin):
        ratio = float(nt) / float(nmin)
        lvl = "problem" if ratio < 1 else "warning" if ratio < 3 else "good"
        text = {"problem": "The trap density read from the trap-filling onset is below what a layer of this "
                           "thickness can resolve; it must not be reported as a trap density.",
                "warning": "The trap density is within a factor 3 of the resolution limit of this thickness; "
                           "treat it as an upper bound.",
                "good": "The trap density is clearly above the resolution limit of this thickness."}[lvl]
        v1 = r.get("n_t_V1_cm3")
        rep.add(lvl, "Trap density", text,
                f"n_t = {float(nt):.2e} cm⁻³ from {r.get('V_TFL_from', 'V_TFL')} = {_f(r.get('V_TFL'), '.3g')} V; "
                f"limit {float(nmin):.2e} cm⁻³" + (f"; the ohmic/TFL crossing V1 would give {float(v1):.2e} cm⁻³" if _ok(v1) else ""),
                "n_t = 2 eps V_TFL / (q L²); limit n = 4 pi² kT eps / (q² L²); V2 (TFL/Child crossing) preferred",
                REF_LECORRE, "" if lvl == "good" else "Use a thicker layer, or fit a drift-diffusion model.")
    elif r.get("tfl") is None:
        rep.add("note", "Trap density", "The curve has no steep trap-filling rise, so no trap density is derived.",
                f"largest local slope {_f(r.get('max_slope'), '.2f')}", "trap-filling regime needs slope > 2.6",
                REF_LECORRE)
    hy = r.get("hysteresis_dec")
    if _ok(hy):
        big = float(hy) > 0.1
        rep.add("warning" if big else "good", "Sweep hysteresis",
                "Up and down sweeps differ: mobile ions are redistributing during the scan, and the voltage "
                "the carriers see is not the applied one." if big else "Up and down sweeps coincide.",
                f"mean |log10 J_up - log10 J_down| = {float(hy):.2f} decades", "<= 0.1 decades", REF_DUIJNSTEE,
                "Use a pulsed-voltage SCLC measurement, which outruns the ions." if big else "")
    else:
        rep.add("note", "Sweep hysteresis", "Only one sweep direction is in the file, so ion-induced hysteresis "
                "could not be checked.", "", "needs an up and a down sweep", REF_DUIJNSTEE,
                "Record both directions; in halide perovskites they usually differ.")
    if _ok(r.get("n0_cm3")):
        rep.add("note", "Ohmic region", f"The low-voltage ohmic region gives a conductivity of "
                f"{float(r['sigma_S_cm']):.2e} S/cm and, with the mobility above, a free-carrier density of "
                f"{float(r['n0_cm3']):.2e} cm⁻³.", f"slope {r['ohmic']['slope']:.2f}",
                "sigma = J L / V; n0 = sigma / (q mu)", REF_ROHR)
    _pass_checks(rep, r.get("warnings"), skip=("resolution", "resolvable", "hysteresis", "No region with"), ref=REF_LECORRE)
    return rep


# --------------------------------------------------------------------------- intensity dependence
def interpret_intensity(r: dict, subject: str = "") -> Report:
    rep = Report("Intensity dependence", subject)
    vf = r.get("voc_fit")
    if vf:
        n, ci = float(vf["n_id"]), vf.get("n_id_ci")
        if 0.9 <= n < 1.2:
            lvl, text = "note", ("close to 1: recombination of free electrons with free holes (radiative), or "
                                 "recombination at a surface where one carrier type is in excess")
        elif 1.2 <= n < 1.8:
            lvl, text = "note", ("between 1 and 2: trap-assisted recombination with unequal carrier densities; in "
                                 "perovskite cells this range is usually set by the interfaces, not by a mixture "
                                 "of bulk mechanisms")
        elif 1.8 <= n <= 2.2:
            lvl, text = "warning", ("close to 2: Shockley-Read-Hall recombination through deep states with both "
                                    "carrier densities rising together (bulk dominated)")
        else:
            lvl, text = "problem", "outside the range 0.9-2.2 that recombination alone can give"
        rep.add(lvl, "Ideality factor", f"n_id = {n:.2f}, {text}.",
                f"{vf['slope_mV_per_decade']:.1f} mV/decade, R² {vf['r2']:.4f}, {vf['n']} points"
                + (f", 95 % interval ±{float(ci):.2f}" if _ok(ci) else ""),
                "n_id = (q / kT) dVoc / d ln I", REF_CAPRIOGLIO if 1.2 <= n < 1.8 else REF_TRESS)
        if _ok(ci) and float(ci) > 0.15:
            rep.add("warning", "Ideality factor uncertainty", f"The 95 % interval of n_id is ±{float(ci):.2f}, too "
                    "wide to separate the cases above.", f"{vf['n']} points over {r.get('decades', float('nan')):.1f} decades",
                    "interval <= 0.15", REF_TRESS, "Add intensities, especially at the low end.")
    jf = r.get("jsc_fit")
    if jf:
        a = float(jf["alpha"])
        lvl = "good" if a >= 0.97 else "note" if a >= 0.9 else "warning"
        text = {"good": "The photocurrent is linear in intensity: no intensity-dependent loss at short circuit.",
                "note": "The photocurrent is slightly sub-linear: a small bimolecular loss at short circuit.",
                "warning": "The photocurrent is clearly sub-linear: bimolecular recombination or space-charge "
                           "build-up at short circuit (0.75 is the space-charge limit)."}[lvl]
        rep.add(lvl, "Jsc exponent", text, f"alpha = {a:.3f}" + (f" ± {float(jf['alpha_ci']):.3f}" if _ok(jf.get("alpha_ci")) else ""),
                "Jsc ∝ I^alpha; >= 0.97 good, < 0.9 warning", REF_MIHAILETCHI if a < 0.9 else REF_KOSTER_JSC,
                "" if lvl == "good" else "Check the mobility balance and the thickness of the absorber.")
    p, tl = r.get("pseudo"), r.get("transport_loss_FF")
    if p and _ok(p.get("pFF")):
        if _ok(tl):
            lvl = "good" if float(tl) <= 3 else "note" if float(tl) <= 6 else "warning"
            rep.add(lvl, "Transport loss in FF", f"The pseudo fill factor, which has no series-resistance loss, is "
                    f"{100 * float(p['pFF']):.1f} %; the measured fill factor is {float(tl):.1f} % (absolute) below it.",
                    f"FF {float(r['FF_at_max']):.1f} %, ideal-diode FF0 {_f(r.get('FF0'), '.1f')} %",
                    "pFF from the Suns-Voc pseudo J-V curve; loss <= 3 % good, > 6 % warning", REF_SINTON,
                    "" if lvl == "good" else "The gap is resistive (contacts, transport layers, electrode sheet "
                    "resistance), not recombination.")
        else:
            rep.add("note", "Pseudo fill factor", f"The Suns-Voc pseudo fill factor is {100 * float(p['pFF']):.1f} %, "
                    "the fill factor this cell would have without series resistance.", "", "Suns-Voc pseudo J-V", REF_SINTON)
    _pass_checks(rep, r.get("warnings"), skip=("is below 1,", "is above 2:"), ref=REF_TRESS)
    return rep


# --------------------------------------------------------------------------- TRPL
def interpret_trpl(r: dict, subject: str = "") -> Report:
    rep = Report("TRPL", subject)
    u = r.get("time_unit", "ns")
    taus = np.atleast_1d(r["taus"])
    chi, dw = r.get("chi2_red"), r.get("dw")
    if r.get("counts") and _ok(chi) and 0.7 <= float(chi) <= 1.3 and (not _ok(dw) or float(dw) >= 1.5):
        rep.add("good", "Fit quality", "The model describes the decay within the counting noise.",
                f"reduced chi-square {float(chi):.2f}, Durbin-Watson {_f(dw, '.2f')}",
                "0.7 <= chi-square <= 1.3 and Durbin-Watson >= 1.5 (Poisson weights)", REF_LAKOWICZ)
    irf = r.get("irf", "none")
    fw = r.get("irf_fwhm")
    if irf != "none":
        tl = r.get("tail") or {}
        t_tail = float(np.nanmin(np.atleast_1d(tl.get("taus", [np.nan]))))
        if irf == "gaussian":
            how = (f"a Gaussian response of {float(fw):.3g} {u} FWHM ("
                   + ("entered" if r.get("irf_fixed") else "fitted to the rising edge") + ")")
        else:
            how = (f"the measured response ({float(fw):.3g} {u} FWHM, moved by {float(r.get('irf_shift', 0.0)):.3g} "
                   f"{u})")
        rep.add("note", "Instrument response", f"The decay was fitted by reconvolution with {how}. The shortest "
                f"lifetime is {taus.min():.3g} {u}; a tail fit of the same trace gives {t_tail:.3g} {u}.",
                f"tail-fit model {tl.get('model', '-')}", "I(t) = IRF(t) (x) sum A_i exp(-t / tau_i)", REF_OCONNOR,
                "Record the response with a scatterer at the excitation wavelength and fit with it: a Gaussian "
                "has no slow tail, which a real detector response has." if irf == "gaussian" else "")
    elif _ok(fw) and float(fw) > 0 and taus.min() < 1.5 * float(fw):
        rep.add("note", "Instrument response", f"The shortest lifetime ({taus.min():.3g} {u}) is within 1.5 response "
                f"widths ({float(fw):.3g} {u} FWHM). A tail fit overestimates a lifetime of that size.", "",
                "tail-fit error about +5 % at tau = FWHM, +20 % at FWHM / 2 (validation)", REF_OCONNOR,
                "Fit with the response: Response gaussian with this FWHM, or measured with the IRF file.")
    if r["model"] == "exp1":
        rep.add("note", "Decay law", f"The decay is mono-exponential with tau = {taus[0]:.3g} {u}: a single "
                "first-order channel, as for trap-assisted recombination at low injection.",
                f"tau std. error {np.atleast_1d(r['tau_errs'])[0]:.2g} {u}", "AICc prefers one exponential",
                REF_KIRCHARTZ_PL)
    elif r["model"] == "stretched":
        rep.add("note", "Decay law", f"Stretched exponential with beta = {float(r['beta']):.2f}: a continuous "
                f"distribution of rates with a mean lifetime of {float(r['tau_amp']):.3g} {u}.",
                f"tau = {taus[0]:.3g} {u}", "<tau> = (tau / beta) Gamma(1 / beta)", REF_KIRCHARTZ_PL)
    else:
        fr = np.atleast_1d(r["amp_fracs"])
        rep.add("note", "Decay law", f"{len(taus)} exponentials are needed. Without a fluence series the "
                "lifetimes are a parametrisation: in a perovskite film a non-exponential decay also follows from "
                "radiative recombination and from carrier redistribution, not only from separate channels.",
                ", ".join(f"tau{i + 1} = {t:.3g} {u} ({100 * f:.0f} %)" for i, (t, f) in enumerate(zip(taus, fr))),
                "AICc; components need a factor 1.5 in tau and 1 % of the amplitude", REF_KIRCHARTZ_PL,
                "Measure at two or more excitation fluences before assigning the components.")
        rep.add("note", "Average lifetime", f"The amplitude-weighted average is {float(r['tau_amp']):.3g} {u} and "
                f"the intensity-weighted one {float(r['tau_int']):.3g} {u}. The first is proportional to the "
                "time-integrated emission and is the one to compare with quantum yields; the second is the mean "
                "emission time and is dominated by the slow tail. State which one is reported.",
                f"<tau>_amp std. error {_f(r.get('tau_amp_err'), '.2g')} {u}",
                "sum A tau / sum A  and  sum A tau² / sum A tau", REF_LAKOWICZ)
    td, tv = r.get("tau_diff", (np.array([]), np.array([])))
    if len(tv) >= 9:
        k = max(3, len(tv) // 3)
        early, late = float(np.median(tv[:k])), float(np.median(tv[-k:]))
        if late > 2.0 * early:
            rep.add("note", "Differential lifetime", f"The differential lifetime grows from {early:.3g} to "
                    f"{late:.3g} {u} during the decay: the recombination rate falls with the carrier density "
                    "(higher-order recombination or early-time extraction and trapping). The late value is the "
                    "one closest to the low-injection lifetime.", "", "tau_diff = -(d ln I / dt)^-1", REF_KRUECKEMEIER,
                    "Quote the lifetime together with the time or signal level at which it was read.")
        else:
            rep.add("good", "Differential lifetime", f"The differential lifetime is constant within a factor 2 "
                    f"({early:.3g} to {late:.3g} {u}): the decay has one rate over the fitted window.", "",
                    "tau_diff = -(d ln I / dt)^-1", REF_KRUECKEMEIER)
    if _ok(r.get("L_D_um")):
        rep.add("note", "Diffusion length", f"With the entered mobility of {float(r['mobility_cm2_Vs']):.3g} cm²/Vs the "
                f"average lifetime corresponds to a diffusion length of {float(r['L_D_um']):.2f} µm. It is an "
                "estimate: the mobility comes from another experiment and the film lifetime includes surface "
                "recombination.", "", "L_D = sqrt(mu kT tau / q)", REF_KIRCHARTZ_PL)
    _pass_checks(rep, r.get("warnings"), ref=REF_LAKOWICZ)
    return rep


# --------------------------------------------------------------------------- impedance
def interpret_eis(r: dict, subject: str = "") -> Report:
    rep = Report("Impedance", subject)
    kk = r["kk"]
    bad = kk["max_pct"] > 2.0 or kk["rms_pct"] > 1.0
    lvl = "problem" if bad else "note" if kk["rms_pct"] > 0.5 else "good"
    rep.add(lvl, "Kramers-Kronig test",
            {"problem": "The spectrum fails the Kramers-Kronig test: it is not a linear, stationary response, and "
                        "circuit parameters fitted to it have no meaning.",
             "note": "The spectrum passes the Kramers-Kronig test with residuals above the usual noise level.",
             "good": "The spectrum is Kramers-Kronig consistent: linear and stationary during the sweep."}[lvl],
            f"residuals rms {kk['rms_pct']:.2f} %, max {kk['max_pct']:.2f} % of |Z| with {kk['M']} RC elements",
            "rms <= 0.5 % good; rms > 1 % or max > 2 % fails", REF_SCHOENLEBER,
            "Let the cell stabilise at the bias and light level first, shorten the sweep, and lower the "
            "perturbation amplitude." if bad else "")
    if r["rms_pct"] <= 1.0:
        rep.add("good", "Circuit fit", f"The {r['model']} circuit reproduces the spectrum.",
                f"rms residual {r['rms_pct']:.2f} % of |Z|", "rms <= 1 % with modulus weighting; AICc selection", REF_GUERRERO)
    d = r.get("drt")
    if d and d["peaks"]:
        major = d["peaks"]
        n_arc = len(r["arcs"])
        ev = "; ".join(f"tau = {pk['tau_s']:.3g} s (f = {pk['f_Hz']:.3g} Hz), R = {pk['R']:.3g} Ohm" for pk in major)
        if d["n_processes"] == n_arc:
            rep.add("good", "Distribution of relaxation times", f"The DRT, which assumes no circuit, finds "
                    f"{d['n_processes']} process" + ("es" if d["n_processes"] != 1 else "") + f", as many as the "
                    f"{r['model']} circuit has arcs.", ev, "peaks with a prominence of 5 % of the largest; "
                    "Tikhonov-regularised non-negative least squares", REF_WAN_DRT)
        else:
            rep.add("note", "Distribution of relaxation times", f"The DRT finds {d['n_processes']} process"
                    + ("es" if d["n_processes"] != 1 else "") + f" while the {r['model']} circuit has {n_arc} arc"
                    + ("s" if n_arc != 1 else "") + ". " + ("The circuit merges processes that the DRT separates."
                    if d["n_processes"] > n_arc else "The circuit uses more arcs than the spectrum resolves."),
                    ev, "peaks with a prominence of 5 % of the largest; a peak below 5 % of the area is merged "
                    "into the nearest larger one", REF_WAN_DRT,
                    "Choose the circuit by the DRT peaks, or restrict the frequency range to the processes of "
                    "interest." if d["n_processes"] > n_arc else "")
    arcs = r["arcs"]
    a_cm2 = r.get("area_cm2", 0.0)
    if len(arcs) == 2:
        hf, lf = arcs
        rep.add("note", "Assignment of the arcs", f"High-frequency arc ({hf['f_peak_Hz']:.3g} Hz): the geometric "
                f"capacitance in parallel with the recombination and transport resistance. Low-frequency arc "
                f"({lf['f_peak_Hz']:.3g} Hz): in halide perovskite cells this is ionic and interfacial polarisation, "
                "and its capacitance is not a density of electronic states.",
                f"C_hf = {hf['C_eff_F']:.3g} F, C_lf = {lf['C_eff_F']:.3g} F (ratio {lf['C_eff_F'] / hf['C_eff_F']:.3g})",
                "arcs ordered by time constant", REF_GUERRERO,
                "Follow both resistances with bias or light intensity before assigning them.")
    for i, a in enumerate(arcs, 1):
        if a["kind"] == "Q" and a["alpha"] >= 0.9:
            rep.add("good", f"Arc {i} ideality", f"The CPE exponent {a['alpha']:.2f} is close to 1, so the effective "
                    "capacitance is well defined.", f"C_eff = {a['C_eff_F']:.3g} F"
                    + (f" = {1e9 * a['C_eff_F'] / a_cm2:.3g} nF/cm²" if a_cm2 > 0 else ""),
                    "C_eff = Q^(1/alpha) R^((1 - alpha)/alpha); alpha >= 0.9", REF_HSU)
    if _ok(r.get("eps_r")):
        rep.add("note", "Permittivity", f"If the high-frequency capacitance is geometric, the relative permittivity "
                f"of the {r['thickness_nm']:.0f} nm layer is {float(r['eps_r']):.1f}.", "", "eps_r = C d / (eps0 A)",
                REF_VONHAUFF, "Compare with the known value of the absorber; a much larger number means the arc "
                "is not geometric.")
    _pass_checks(rep, r.get("warnings"), skip=("Kramers-Kronig residuals reach",), ref=REF_VONHAUFF)
    return rep


# --------------------------------------------------------------------------- Mott-Schottky
def interpret_cv(r: dict, subject: str = "") -> Report:
    rep = Report("Mott-Schottky", subject)
    if r.get("window") is None or not _ok(r.get("N_cm3")):
        rep.add("problem", "Mott-Schottky region", "1/C² has no straight section with a negative slope, so no "
                "doping density or built-in potential can be read.", "", "R² >= 0.95 over 15 % of the voltage range",
                REF_ALMORA, "Check the frequency: C-V must be taken on the capacitance plateau, not in the "
                "low-frequency ionic rise.")
        return rep
    n, nmin = float(r["N_cm3"]), r.get("N_min_cm3")
    if _ok(nmin):
        ratio = n / float(nmin)
        lvl = "problem" if ratio < 1 else "warning" if ratio < 3 else "good"
        rep.add(lvl, "Doping density against the resolution limit",
                {"problem": "The apparent density is below the limit a layer of this thickness can show; it is the "
                            "signature of geometric capacitance plus injected charge, not of doping.",
                 "warning": "The apparent density is within a factor 3 of the resolution limit; it cannot be "
                            "told apart from an undoped layer.",
                 "good": "The density is clearly above the resolution limit and can be a real doping or "
                         "charged-defect density."}[lvl],
                f"N = {n:.2e} cm⁻³, N_min = {float(nmin):.2e} cm⁻³ (ratio {ratio:.2g})",
                "N_min = 27 m kT eps / (4 q² d²); N >= 3 N_min", REF_RAVISHANKAR,
                "" if lvl == "good" else "Report the layer as fully depleted and give N_min as the upper bound.")
    vbi = r.get("V_bi")
    if _ok(vbi) and 0.3 <= float(vbi) <= 1.6:
        rep.add("note", "Built-in potential", f"V_bi = {float(vbi):.2f} V from the intercept. In a fully depleted "
                "cell the intercept follows the onset of injected charge and is not the built-in potential.",
                f"intercept {float(r['V_intercept']):.3f} V + kT/q, window R² {r['window']['r2']:.4f}",
                "1/C² = 2 (V_bi - V - kT/q) / (q eps A² N)", REF_KIRCHARTZ_CV)
    w = r.get("W_window_nm", (np.nan, np.nan))
    if _ok(w[0]) and r.get("thickness_nm", 0) > 0 and w[1] <= 0.9 * r["thickness_nm"]:
        rep.add("good", "Depletion width", f"The depletion edge moves from {w[0]:.0f} to {w[1]:.0f} nm inside the "
                f"{r['thickness_nm']:.0f} nm layer in the fitted window.", f"Debye length {_f(r.get('debye_nm'), '.3g')} nm",
                "W = eps A / C below 90 % of the thickness", REF_KIRCHARTZ_CV)
    win = r["window"]
    prof = np.asarray(r["n_profile_cm3"])[win["i0"]:win["i1"]]
    prof = prof[np.isfinite(prof) & (prof > 0)]
    if len(prof) >= 5 and prof.max() / prof.min() > 3.0:
        rep.add("note", "Doping profile", "The profile N(W) varies by more than a factor 3 inside the fitted "
                "window. A U-shaped profile rising toward both contacts is what a fully depleted layer gives.",
                f"{prof.min():.2e} to {prof.max():.2e} cm⁻³", "N(W) = -2 / (q eps A² d(1/C²)/dV)", REF_KIRCHARTZ_CV)
    _pass_checks(rep, r.get("warnings"), skip=("resolution limit of a",), ref=REF_ALMORA)
    return rep


# --------------------------------------------------------------------------- stability
def interpret_stability(r: dict, subject: str = "") -> Report:
    rep = Report("Stability", subject)
    pct = f"{100 * r['threshold']:.0f}"
    if r["T_reached"]:
        rep.add("good", f"T{pct}", f"T{pct} = {r['T_measured']:.3g} h was reached within the measurement.",
                f"final output {100 * r['final']:.1f} % after {r['duration_h']:.3g} h; on the fitted curve "
                f"{_f(r.get('T_model'), '.3g')} h", "first lasting crossing of the 5-point running median", REF_KHENKIN)
    else:
        x = r["T_extrapolated"]
        if not np.isfinite(x):
            rep.add("note", f"T{pct}", f"The output stays above {pct} % and the fitted trend does not reach it: "
                    f"T{pct} exceeds the {r['duration_h']:.3g} h measured.", f"final output {100 * r['final']:.1f} %",
                    "no crossing within 1000 times the measured time", REF_KHENKIN)
        else:
            far = x / r["duration_h"] > 2.0
            rep.add("problem" if far else "warning", f"T{pct}",
                    f"T{pct} = {x:.3g} h is an extrapolation of the {r['model']} model, {x / r['duration_h']:.1f} "
                    "times the measured time" + (": it is a property of the model, not a measured lifetime." if far else "."),
                    f"measured {r['duration_h']:.3g} h, final output {100 * r['final']:.1f} %",
                    "extrapolation up to twice the measured time is an estimate, beyond that not reportable",
                    REF_KHENKIN, f"Report T{pct} > {r['duration_h']:.3g} h, or continue the test.")
    if r["burn_in"]:
        ts = r["Ts_measured"] if r["Ts_reached"] else r["Ts_extrapolated"]
        rep.add("note", "Burn-in", f"A fast initial loss of {r['burn_in_loss_pct']:.1f} % (absolute, time constant "
                f"{r['p'][1]:.3g} h) is followed by a slower trend. Counted from the stabilised point at "
                f"{r['t_s']:.3g} h, Ts{pct} = {ts:.3g} h" + ("." if r["Ts_reached"] else " (extrapolated)."),
                f"stabilised output {100 * r['E_s']:.1f} %", "t_s = 3 tau of the fast term; Ts from 80 % of E_s",
                REF_ROESCH, "State whether a lifetime includes the burn-in.")
    rate = r.get("rate_pct_per_1000h")
    if _ok(rate):
        rep.add("note", "Loss rate", (f"The output falls by {float(rate):.2f} % per 1000 h" if float(rate) >= 0 else
                                     f"The output rises by {-float(rate):.2f} % per 1000 h")
                + (" after the burn-in." if r["burn_in"] else " over the test."),
                f"std. error {_f(r.get('rate_err'), '.2g')} %/1000 h; mean output {100 * r['mean_output']:.1f} %",
                "linear regression of the normalised trace", REF_ROESCH)
    _pass_checks(rep, r.get("warnings"), skip=("is extrapolated",), ref=REF_KHENKIN)
    return rep
