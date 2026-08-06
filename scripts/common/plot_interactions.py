# ============================================================
# scripts/common/plot_interactions.py
# Shared convenience features ported from the original JV_Analysis.exe:
#   - smart_legend(): overflow-safe legend (fixes long-legend errors)
#   - enable_wheel_zoom(): wheel zoom at cursor (Ctrl = X only, Shift = Y only)
#   - enable_drag_pan(): left-drag panning
#   - double-click on a plot: auto range
#   - add_canvas_context_menu(): right-click menu on every plot
#   - attach_tree_context_menu(): right-click menu + Ctrl+C on tables
# All helpers are defensive: they never raise into the GUI event loop.
# ============================================================
from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, messagebox


# ------------------------------------------------------------
# Legend
# ------------------------------------------------------------
def smart_legend(ax, loc="upper left", max_items=10, max_chars=24, fontsize=8.5):
    """Overflow-safe replacement for ax.legend().

    The original tools passed every sample name straight to ax.legend(); with
    many samples or long file names the legend covered the whole plot (and on
    small windows spilled outside). This helper:
      - deduplicates labels,
      - truncates long labels with an ellipsis,
      - caps the number of entries and appends '+N more',
      - switches to 2 columns when more than 5 entries.
    Returns the legend (or None if there is nothing to show).
    """
    try:
        handles, labels = ax.get_legend_handles_labels()
    except Exception:
        return None
    if not handles:
        return None

    # dedupe, keep order
    seen = set()
    h2, l2 = [], []
    for h, l in zip(handles, labels):
        if not l or l.startswith("_") or l in seen:
            continue
        seen.add(l)
        h2.append(h)
        l2.append(l)
    if not h2:
        return None

    hidden = 0
    if len(h2) > max_items:
        hidden = len(h2) - max_items
        h2, l2 = h2[:max_items], l2[:max_items]

    l2 = [(s[: max_chars - 1] + "…") if len(s) > max_chars else s for s in l2]
    if hidden:
        l2[-1] = f"{l2[-1]}  (+{hidden} more)"

    ncol = 2 if len(h2) > 5 else 1
    try:
        leg = ax.legend(h2, l2, loc=loc, fontsize=fontsize, ncol=ncol,
                        framealpha=0.85, borderaxespad=0.4,
                        handlelength=1.4, columnspacing=0.9,
                        labelspacing=0.35)
        return leg
    except Exception:
        try:
            return ax.legend(loc=loc, fontsize=fontsize)
        except Exception:
            return None


# ------------------------------------------------------------
# Axis helpers
# ------------------------------------------------------------
def auto_range(ax):
    """Autoscale an axes to its data (safe for log axes)."""
    try:
        ax.relim(visible_only=True)
        ax.autoscale(enable=True, axis="both")
        ax.autoscale_view()
    except Exception:
        pass


def _zoom_axis(lo, hi, center, scale, is_log):
    import math
    if is_log and lo > 0 and hi > 0 and center > 0:
        llo, lhi, lc = math.log10(lo), math.log10(hi), math.log10(center)
        nlo = lc - (lc - llo) * scale
        nhi = lc + (lhi - lc) * scale
        return 10 ** nlo, 10 ** nhi
    return center - (center - lo) * scale, center + (hi - center) * scale


# ------------------------------------------------------------
# Mouse navigation (wheel zoom / drag pan / double-click reset)
# ------------------------------------------------------------
def enable_wheel_zoom(canvas, base_scale=1.2):
    """Wheel zoom centered at the cursor, JV_Analysis.exe style.

    plain wheel = zoom both axes, Ctrl+wheel = X axis only,
    Shift+wheel = Y axis only. Works on whichever axes is under the cursor.
    """
    def on_scroll(event):
        ax = event.inaxes
        if ax is None or event.xdata is None or event.ydata is None:
            return
        try:
            scale = 1.0 / base_scale if event.button == "up" else base_scale
            key = (event.key or "")
            do_x = "shift" not in key
            do_y = "control" not in key and "ctrl" not in key
            if do_x:
                lo, hi = ax.get_xlim()
                ax.set_xlim(_zoom_axis(lo, hi, event.xdata, scale,
                                       ax.get_xscale() == "log"))
            if do_y:
                lo, hi = ax.get_ylim()
                ax.set_ylim(_zoom_axis(lo, hi, event.ydata, scale,
                                       ax.get_yscale() == "log"))
            canvas.draw_idle()
        except Exception:
            pass

    return canvas.mpl_connect("scroll_event", on_scroll)


def enable_drag_pan(canvas, button=1):
    """Left-drag panning + double-click auto range (JV_Analysis.exe style).

    Only use on plots WITHOUT a SpanSelector bound to the same button.
    """
    state = {}

    def on_press(event):
        if event.button != button or event.inaxes is None:
            return
        if getattr(event, "dblclick", False):
            auto_range(event.inaxes)
            canvas.draw_idle()
            state.clear()
            return
        state.update(ax=event.inaxes, x=event.x, y=event.y,
                     xlim=event.inaxes.get_xlim(), ylim=event.inaxes.get_ylim())

    def on_move(event):
        ax = state.get("ax")
        if ax is None or event.x is None:
            return
        try:
            dx_px = event.x - state["x"]
            dy_px = event.y - state["y"]
            bbox = ax.get_window_extent()
            if bbox.width <= 1 or bbox.height <= 1:
                return
            (x0, x1), (y0, y1) = state["xlim"], state["ylim"]
            if ax.get_xscale() == "log" and x0 > 0 and x1 > 0:
                import math
                span = math.log10(x1) - math.log10(x0)
                shift = -dx_px / bbox.width * span
                ax.set_xlim(10 ** (math.log10(x0) + shift), 10 ** (math.log10(x1) + shift))
            else:
                shift = -dx_px / bbox.width * (x1 - x0)
                ax.set_xlim(x0 + shift, x1 + shift)
            if ax.get_yscale() == "log" and y0 > 0 and y1 > 0:
                import math
                span = math.log10(y1) - math.log10(y0)
                shift = -dy_px / bbox.height * span
                ax.set_ylim(10 ** (math.log10(y0) + shift), 10 ** (math.log10(y1) + shift))
            else:
                shift = -dy_px / bbox.height * (y1 - y0)
                ax.set_ylim(y0 + shift, y1 + shift)
            canvas.draw_idle()
        except Exception:
            pass

    def on_release(_event):
        state.clear()

    ids = [canvas.mpl_connect("button_press_event", on_press),
           canvas.mpl_connect("motion_notify_event", on_move),
           canvas.mpl_connect("button_release_event", on_release)]
    return ids


# ------------------------------------------------------------
# Right-click context menu on a plot canvas
# ------------------------------------------------------------
def add_canvas_context_menu(owner, canvas, fig, extra_items=None,
                            on_after_change=None):
    """Right-click menu on a matplotlib canvas: Auto Range / Toggle Legend /
    Toggle Grid / Save Figure (publication style). `extra_items` is an
    optional list of (label, callback) appended at the top.
    """
    widget = canvas.get_tk_widget()

    def _redraw():
        try:
            canvas.draw_idle()
        except Exception:
            pass
        if on_after_change:
            try:
                on_after_change()
            except Exception:
                pass

    def do_auto_range():
        for ax in fig.axes:
            auto_range(ax)
        _redraw()

    def do_toggle_legend():
        for ax in fig.axes:
            leg = ax.get_legend()
            if leg is not None:
                leg.set_visible(not leg.get_visible())
            else:
                smart_legend(ax)
        _redraw()

    def do_toggle_grid():
        for ax in fig.axes:
            try:
                on = any(l.get_visible() for l in ax.get_xgridlines())
                ax.grid(not on, linestyle="--", alpha=0.3)
            except Exception:
                pass
        _redraw()

    def do_save_fig():
        try:
            from scripts.common import analysis_shell as _shell
            # reuse the shared publication-style export (works on any window
            # object exposing .fig)
            class _Holder:
                pass
            h = _Holder()
            h.fig = fig
            _shell.save_fig_png(h)
        except Exception as e:
            try:
                messagebox.showerror("Export", str(e))
            except Exception:
                pass

    menu = tk.Menu(widget, tearoff=0)
    if extra_items:
        for label, cb in extra_items:
            if label == "-":
                menu.add_separator()
            else:
                menu.add_command(label=label, command=cb)
        menu.add_separator()
    menu.add_command(label="Auto Range", command=do_auto_range)
    menu.add_command(label="Toggle Legend", command=do_toggle_legend)
    menu.add_command(label="Toggle Grid", command=do_toggle_grid)
    menu.add_separator()
    menu.add_command(label="Save Figure (Publication)...", command=do_save_fig)

    def popup(ev):
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    widget.bind("<Button-3>", popup, add="+")
    return menu


# ------------------------------------------------------------
# Table (ttk.Treeview) context menu: copy / rename
# ------------------------------------------------------------
def _tree_rows_as_text(tree, items):
    cols = tree["columns"]
    header = "\t".join(str(tree.heading(c).get("text", c)) for c in cols)
    lines = [header]
    for it in items:
        vals = tree.item(it, "values")
        lines.append("\t".join(str(v) for v in vals))
    return "\n".join(lines)


def _copy_to_clipboard(widget, text):
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
    except Exception:
        pass


def attach_tree_context_menu(owner, tree, on_rename=None):
    """JV_Analysis.exe-style table conveniences:
       - right-click: Copy selected rows / Copy whole table
       - Ctrl+C copies the selection
       - optional Rename (F2 + menu) via on_rename(old_name, new_name)
    """
    menu = tk.Menu(tree, tearoff=0)

    def copy_selected():
        items = tree.selection() or tree.get_children()
        _copy_to_clipboard(tree, _tree_rows_as_text(tree, items))

    def copy_all():
        _copy_to_clipboard(tree, _tree_rows_as_text(tree, tree.get_children()))

    def rename_selected():
        sel = tree.selection()
        if not sel or on_rename is None:
            return
        vals = tree.item(sel[0], "values")
        if not vals:
            return
        old = str(vals[0])
        new = simpledialog.askstring("Rename sample", f"New name for '{old}':",
                                     initialvalue=old, parent=owner)
        if not new or new == old:
            return
        try:
            on_rename(old, new.strip())
        except Exception as e:
            try:
                messagebox.showerror("Rename", str(e), parent=owner)
            except Exception:
                pass

    if on_rename is not None:
        menu.add_command(label="Rename sample...  (F2)", command=rename_selected)
        menu.add_separator()
    menu.add_command(label="Copy selected rows  (Ctrl+C)", command=copy_selected)
    menu.add_command(label="Copy whole table", command=copy_all)

    def popup(ev):
        row = tree.identify_row(ev.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    tree.bind("<Button-3>", popup, add="+")
    tree.bind("<Control-c>", lambda e: (copy_selected(), "break")[1], add="+")
    if on_rename is not None:
        tree.bind("<F2>", lambda e: (rename_selected(), "break")[1], add="+")
    return menu
