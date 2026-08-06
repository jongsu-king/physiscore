# ============================================================
# scripts/common/sample_naming.py
# Full sample-naming convenience set ported from JV_Analysis.exe:
#   right-click on the sample table ->
#     Rename (F2) | Rename to preset > | Compose name from presets... |
#     Add current name to presets | Edit presets... | Batch rename... |
#     Revert to original name | Copy rows / Copy table (Ctrl+C)
# Presets are stored globally in physisfera_config.json ("name_presets")
# so every tool shares the same preset list, like the original exe.
# ============================================================
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import simpledialog, messagebox

import customtkinter as ctk

_CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                       "physisfera_config.json"))


# ------------------------------------------------------------
# Preset storage (shared, merge-preserving)
# ------------------------------------------------------------
def load_presets():
    try:
        with open(_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        p = data.get("name_presets", [])
        return [str(x) for x in p if str(x).strip()]
    except Exception:
        return []


def save_presets(presets):
    data = {}
    try:
        if os.path.exists(_CONFIG):
            with open(_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    data["name_presets"] = list(dict.fromkeys(str(p).strip() for p in presets if str(p).strip()))
    try:
        with open(_CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _tree_names(tree):
    """All first-column values (sample names) in order."""
    out = []
    for it in tree.get_children():
        vals = tree.item(it, "values")
        if vals:
            out.append(str(vals[0]))
    return out


def _selected_name(tree):
    sel = tree.selection()
    if not sel:
        return None
    vals = tree.item(sel[0], "values")
    return str(vals[0]) if vals else None


def _rows_as_text(tree, items):
    cols = tree["columns"]
    header = "\t".join(str(tree.heading(c).get("text", c)) for c in cols)
    lines = [header]
    for it in items:
        lines.append("\t".join(str(v) for v in tree.item(it, "values")))
    return "\n".join(lines)


def _clip(widget, text):
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
    except Exception:
        pass


class _Renamer:
    """Wraps the tool's on_rename callback and tracks original names so
    'Revert to original name' works across chained renames."""

    def __init__(self, owner, on_rename):
        self.owner = owner
        self.on_rename = on_rename
        if not hasattr(owner, "_naming_originals"):
            owner._naming_originals = {}

    def rename(self, old, new):
        new = str(new).strip()
        if not new or new == old:
            return False
        orig = self.owner._naming_originals.pop(old, old)
        self.on_rename(old, new)
        if new != orig:
            self.owner._naming_originals[new] = orig
        return True

    def original_of(self, name):
        return self.owner._naming_originals.get(name)


# ------------------------------------------------------------
# Dialogs (dark theme, JV exe style)
# ------------------------------------------------------------
_D_BG, _D_CARD, _D_SUB, _D_ACC = "#0A0A0A", "#1E1E1E", "#252525", "#3182F6"


class BatchRenameDialog(ctk.CTkToplevel):
    """Find/replace over all sample names with live preview + common-prefix strip."""

    def __init__(self, parent, names, renamer):
        super().__init__(parent)
        self.title("Batch Rename")
        self.geometry("560x520")
        self.configure(fg_color=_D_BG)
        self.transient(parent)
        self.names = list(names)
        self.renamer = renamer

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(14, 4))
        ctk.CTkLabel(row, text="Find:", width=60, anchor="w").pack(side="left")
        self.e_find = ctk.CTkEntry(row)
        self.e_find.pack(side="left", fill="x", expand=True)
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row2, text="Replace:", width=60, anchor="w").pack(side="left")
        self.e_repl = ctk.CTkEntry(row2)
        self.e_repl.pack(side="left", fill="x", expand=True)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=4)
        ctk.CTkButton(btns, text="Strip common prefix", height=28, fg_color=_D_SUB,
                      hover_color="#303030",
                      command=self._fill_common_prefix).pack(side="left")
        ctk.CTkLabel(btns, text="(preview updates as you type)",
                     text_color="#8B8B8B").pack(side="right")

        self.preview = ctk.CTkTextbox(self, font=("Consolas", 12), fg_color=_D_CARD)
        self.preview.pack(fill="both", expand=True, padx=14, pady=8)

        act = ctk.CTkFrame(self, fg_color="transparent")
        act.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(act, text="Apply", height=36, fg_color=_D_ACC, hover_color="#2563EB",
                      command=self._apply).pack(side="right")
        ctk.CTkButton(act, text="Cancel", height=36, fg_color=_D_SUB, hover_color="#303030",
                      command=self.destroy).pack(side="right", padx=8)

        self.e_find.bind("<KeyRelease>", lambda e: self._update_preview())
        self.e_repl.bind("<KeyRelease>", lambda e: self._update_preview())
        self._update_preview()
        self.after(120, lambda: self.e_find.focus_set())

    def _common_prefix(self):
        if len(self.names) < 2:
            return ""
        pref = os.path.commonprefix(self.names)
        return pref

    def _fill_common_prefix(self):
        pref = self._common_prefix()
        self.e_find.delete(0, "end")
        self.e_find.insert(0, pref)
        self._update_preview()

    def _pairs(self):
        find = self.e_find.get()
        repl = self.e_repl.get()
        out = []
        if not find:
            return out
        for n in self.names:
            if find in n:
                new = n.replace(find, repl).strip()
                if new and new != n:
                    out.append((n, new))
        return out

    def _update_preview(self):
        pairs = self._pairs()
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        if not pairs:
            self.preview.insert("end", "(no changes)")
        else:
            for old, new in pairs:
                self.preview.insert("end", f"{old}\n  -> {new}\n")
        self.preview.configure(state="disabled")

    def _apply(self):
        pairs = self._pairs()
        # duplicate check after rename
        finals = [p[1] for p in pairs] + [n for n in self.names if n not in {p[0] for p in pairs}]
        if len(finals) != len(set(finals)):
            messagebox.showerror("Batch Rename", "Rename would create duplicate names.", parent=self)
            return
        done = 0
        for old, new in pairs:
            try:
                if self.renamer.rename(old, new):
                    done += 1
            except Exception as e:
                messagebox.showerror("Batch Rename", f"{old}: {e}", parent=self)
                break
        self.destroy()
        if done:
            messagebox.showinfo("Batch Rename", f"Renamed {done} sample(s).")


class PresetEditDialog(ctk.CTkToplevel):
    """Add/remove entries of the global preset list."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Edit Name Presets")
        self.geometry("420x460")
        self.configure(fg_color=_D_BG)
        self.transient(parent)

        self.lst = tk.Listbox(self, bg=_D_CARD, fg="#E8E8E8", selectbackground=_D_ACC,
                              relief="flat", font=("Segoe UI", 11), activestyle="none")
        self.lst.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        for p in load_presets():
            self.lst.insert("end", p)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=4)
        self.e_new = ctk.CTkEntry(row, placeholder_text="new preset...")
        self.e_new.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="Add", width=70, height=28, fg_color=_D_SUB,
                      hover_color="#303030", command=self._add).pack(side="left")
        ctk.CTkButton(row, text="Remove", width=70, height=28, fg_color=_D_SUB,
                      hover_color="#303030", command=self._remove).pack(side="left", padx=(6, 0))

        act = ctk.CTkFrame(self, fg_color="transparent")
        act.pack(fill="x", padx=14, pady=(4, 14))
        ctk.CTkButton(act, text="Save", height=36, fg_color=_D_ACC, hover_color="#2563EB",
                      command=self._save).pack(side="right")
        ctk.CTkButton(act, text="Cancel", height=36, fg_color=_D_SUB, hover_color="#303030",
                      command=self.destroy).pack(side="right", padx=8)

    def _add(self):
        v = self.e_new.get().strip()
        if v:
            self.lst.insert("end", v)
            self.e_new.delete(0, "end")

    def _remove(self):
        for i in reversed(self.lst.curselection()):
            self.lst.delete(i)

    def _save(self):
        save_presets(list(self.lst.get(0, "end")))
        self.destroy()


class ComposeDialog(ctk.CTkToplevel):
    """Compose a name by joining presets with ' / ' (e.g. 'ZnO / PDINN')."""

    def __init__(self, parent, renamer, target_name):
        super().__init__(parent)
        self.title("Compose Name From Presets")
        self.geometry("420x480")
        self.configure(fg_color=_D_BG)
        self.transient(parent)
        self.renamer = renamer
        self.target = target_name

        ctk.CTkLabel(self, text=f"Target: {target_name}",
                     text_color="#8B8B8B").pack(anchor="w", padx=14, pady=(12, 2))
        self.lst = tk.Listbox(self, bg=_D_CARD, fg="#E8E8E8", selectbackground=_D_ACC,
                              relief="flat", font=("Segoe UI", 11), activestyle="none",
                              selectmode="extended")
        self.lst.pack(fill="both", expand=True, padx=14, pady=6)
        for p in load_presets():
            self.lst.insert("end", p)

        self.e_out = ctk.CTkEntry(self, placeholder_text="composed name")
        self.e_out.pack(fill="x", padx=14, pady=4)
        self.lst.bind("<<ListboxSelect>>", self._compose)

        act = ctk.CTkFrame(self, fg_color="transparent")
        act.pack(fill="x", padx=14, pady=(4, 14))
        ctk.CTkButton(act, text="Apply", height=36, fg_color=_D_ACC, hover_color="#2563EB",
                      command=self._apply).pack(side="right")
        ctk.CTkButton(act, text="Cancel", height=36, fg_color=_D_SUB, hover_color="#303030",
                      command=self.destroy).pack(side="right", padx=8)

    def _compose(self, _e=None):
        parts = [self.lst.get(i) for i in self.lst.curselection()]
        self.e_out.delete(0, "end")
        self.e_out.insert(0, " / ".join(parts))

    def _apply(self):
        new = self.e_out.get().strip()
        if not new:
            return
        try:
            self.renamer.rename(self.target, new)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Rename", str(e), parent=self)


# ------------------------------------------------------------
# Main entry: attach the full menu to a sample tree
# ------------------------------------------------------------
def attach_full_naming_menu(owner, tree, on_rename):
    """Attach the complete JV_Analysis.exe naming/copy menu to a Treeview
    whose first column is the sample/condition name.
    on_rename(old, new) must apply the rename to the tool's data + refresh.
    """
    renamer = _Renamer(owner, on_rename)
    menu = tk.Menu(tree, tearoff=0)
    preset_menu = tk.Menu(menu, tearoff=0)

    def rename_dialog():
        old = _selected_name(tree)
        if not old:
            return
        new = simpledialog.askstring("Rename sample", f"New name for '{old}':",
                                     initialvalue=old, parent=owner)
        if new:
            try:
                renamer.rename(old, new)
            except Exception as e:
                messagebox.showerror("Rename", str(e), parent=owner)

    def rebuild_preset_menu():
        preset_menu.delete(0, "end")
        presets = load_presets()
        old = _selected_name(tree)
        if not presets:
            preset_menu.add_command(label="(no presets - use 'Edit presets...')",
                                    state="disabled")
        for p in presets:
            preset_menu.add_command(
                label=p,
                command=lambda p=p, o=old: _apply_preset(o, p))

    def _apply_preset(old, preset):
        if not old:
            return
        try:
            renamer.rename(old, preset)
        except Exception as e:
            messagebox.showerror("Rename", str(e), parent=owner)

    def add_current_to_presets():
        name = _selected_name(tree)
        if not name:
            return
        ps = load_presets()
        if name not in ps:
            ps.append(name)
            save_presets(ps)

    def compose():
        old = _selected_name(tree)
        if old:
            ComposeDialog(owner, renamer, old)

    def batch():
        names = _tree_names(tree)
        if names:
            BatchRenameDialog(owner, names, renamer)

    def revert():
        cur = _selected_name(tree)
        if not cur:
            return
        orig = renamer.original_of(cur)
        if not orig or orig == cur:
            messagebox.showinfo("Revert", "This sample still has its original name.",
                                parent=owner)
            return
        try:
            renamer.rename(cur, orig)
        except Exception as e:
            messagebox.showerror("Revert", str(e), parent=owner)

    def copy_selected():
        items = tree.selection() or tree.get_children()
        _clip(tree, _rows_as_text(tree, items))

    def copy_all():
        _clip(tree, _rows_as_text(tree, tree.get_children()))

    menu.add_command(label="Rename...  (F2)", command=rename_dialog)
    menu.add_cascade(label="Rename to preset", menu=preset_menu)
    menu.add_command(label="Compose name from presets...", command=compose)
    menu.add_command(label="Add current name to presets", command=add_current_to_presets)
    menu.add_command(label="Edit presets...", command=lambda: PresetEditDialog(owner))
    menu.add_separator()
    menu.add_command(label="Batch rename...", command=batch)
    menu.add_command(label="Revert to original name", command=revert)
    menu.add_separator()
    menu.add_command(label="Copy selected rows  (Ctrl+C)", command=copy_selected)
    menu.add_command(label="Copy whole table", command=copy_all)

    def popup(ev):
        row = tree.identify_row(ev.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
        rebuild_preset_menu()
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    tree.bind("<Button-3>", popup, add="+")
    tree.bind("<Control-c>", lambda e: (copy_selected(), "break")[1], add="+")
    tree.bind("<F2>", lambda e: (rename_dialog(), "break")[1], add="+")
    return menu
