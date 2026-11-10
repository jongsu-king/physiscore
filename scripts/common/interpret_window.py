"""Window that shows a rule-based interpretation (scripts.common.interpret.Report)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk

from scripts.common import palette as _pal
from scripts.common import theme as _theme
from scripts.common.interpret import LEVEL_LABEL, Report

LEVEL_COLOR = {"problem": _pal.RED, "warning": _pal.ORANGE, "note": _pal.TXT_SUB, "good": _pal.GREEN}


class InterpretationWindow(ctk.CTkToplevel):
    def __init__(self, parent, report: Report, title: str = "Interpretation"):
        super().__init__(parent)
        self.report = report
        self.title(f"{title} - {report.technique} - Physiscore")
        self.geometry("1060x700")
        self.minsize(820, 520)
        self.configure(fg_color=_pal.BG_WINDOW)
        try:
            self.transient(parent)
        except Exception:
            pass

        top = _theme.card(self)
        top.pack(fill="x", padx=10, pady=(10, 6))
        h = ctk.CTkLabel(top, text="Summary", font=_pal.font(11, "bold"))
        h.pack(fill="x")
        _theme.panel_header(h, top)
        subject = f"{report.technique}" + (f": {report.subject}" if report.subject else "")
        ctk.CTkLabel(top, text=subject, font=_pal.font(13, "bold"), text_color=_pal.TXT, anchor="w"
                     ).pack(fill="x", padx=12)
        ctk.CTkLabel(top, text=report.summary(), font=_pal.font(12), text_color=_pal.TXT, anchor="w",
                     justify="left", wraplength=1000).pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(top, text="Rule-based: every statement follows from a stated rule, threshold and reference "
                               "(methods document, section 16). Nothing is sent over the network.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

        mid = _theme.card(self)
        mid.pack(fill="both", expand=True, padx=10, pady=6)
        h2 = ctk.CTkLabel(mid, text="Findings", font=_pal.font(11, "bold"))
        h2.pack(fill="x")
        _theme.panel_header(h2, mid)
        _theme.style_treeview(rowheight=24)
        frame = ctk.CTkFrame(mid, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=("level", "topic", "text"), show="headings", selectmode="browse")
        for c, t, w, st in (("level", "Level", 80, False), ("topic", "Topic", 210, False), ("text", "Finding", 700, True)):
            self.tree.heading(c, text=t, anchor="w")
            self.tree.column(c, width=w, anchor="w", stretch=st)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        for lv, col in LEVEL_COLOR.items():
            self.tree.tag_configure(lv, foreground=col)
        self._rows = {}
        for f in report.sorted():
            iid = self.tree.insert("", "end", values=(LEVEL_LABEL.get(f.level, f.level), f.topic, f.text),
                                   tags=(f.level,))
            self._rows[iid] = f
        self.tree.bind("<<TreeviewSelect>>", self._show)

        det = _theme.card(self)
        det.pack(fill="x", padx=10, pady=6)
        h3 = ctk.CTkLabel(det, text="Detail", font=_pal.font(11, "bold"))
        h3.pack(fill="x")
        _theme.panel_header(h3, det)
        self.detail = _theme.kv_table(det, height=4, key_width=120, value_width=860)
        self.detail.heading("k", text="Item")
        self.detail.heading("v", text="Value")
        self.detail.column("v", anchor="w")
        self.detail.pack(fill="x", padx=8, pady=(0, 8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        for text, cmd in (("Close", self.destroy), ("Save report (Markdown)", self._save), ("Copy as text", self._copy)):
            ctk.CTkButton(btns, text=text, width=150 if "Save" in text else 110, height=26, command=cmd,
                          fg_color=_pal.BG_PANEL, hover_color=_pal.BG_HOVER, text_color=_pal.TXT,
                          border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                          corner_radius=_pal.R_PILL).pack(side="right", padx=(6, 0))
        self.lbl = ctk.CTkLabel(btns, text=f"{len(report.findings)} findings", font=_pal.font(10),
                                text_color=_pal.TXT_SUB)
        self.lbl.pack(side="left")
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self._show()
        self.after(100, self.lift)

    def _show(self, _event=None):
        sel = self.tree.selection()
        f = self._rows.get(sel[0]) if sel else None
        if f is None:
            return
        _theme.fill_kv(self.detail, [("Evidence", f.evidence or "-"), ("Rule", f.rule or "-"),
                                     ("Reference", f.ref or "-"), ("Next step", f.action or "-")])

    def _copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.report.to_text())
            self.lbl.configure(text="Copied to the clipboard")
        except tk.TclError:
            pass

    def _save(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".md",
                                            initialfile=f"interpretation_{self.report.technique.replace(' ', '_')}.md",
                                            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.report.to_markdown() if path.endswith(".md") else self.report.to_text())
        self.lbl.configure(text=f"Saved {path}")


def show(parent, report: Report, title: str = "Interpretation"):
    """Open the window (or tell the user there is nothing to interpret yet)."""
    if not report.findings:
        from tkinter import messagebox
        messagebox.showinfo("Interpretation", "Run the analysis first: there is no result to interpret yet.",
                            parent=parent)
        return None
    return InterpretationWindow(parent, report, title)
