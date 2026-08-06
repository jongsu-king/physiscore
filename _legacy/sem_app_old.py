import os, sys
print("=== RUNNING FILE ===", __file__)
print("=== CWD ===", os.getcwd())
print("=== PYTHON ===", sys.executable)
print("=== ARGV ===", sys.argv)

import math
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional, Tuple, List, Dict

import customtkinter as ctk
import numpy as np
import pandas as pd
import cv2
from PIL import Image, ImageTk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import sem_core


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class SEMApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SEM Grain Analysis")
        self.geometry("1400x820")
        self.minsize(1200, 700)

        self.settings = sem_core.Settings()
        self.records: List[Dict] = []

        self.img_path: str = ""
        self.current_img_bgr: Optional[np.ndarray] = None
        self.current_img_rgb: Optional[np.ndarray] = None
        self.nm_per_px: Optional[float] = None

        self.calib_mode = False
        self.calib_points: List[Tuple[int, int]] = []

        self._build_layout()

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.left = ctk.CTkFrame(self, corner_radius=14)
        self.left.grid(row=0, column=0, sticky="nsw", padx=12, pady=12)

        self.center = ctk.CTkFrame(self, corner_radius=14)
        self.center.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        self.center.grid_rowconfigure(0, weight=1)
        self.center.grid_columnconfigure(0, weight=1)

        self.right = ctk.CTkFrame(self, corner_radius=14)
        self.right.grid(row=0, column=2, sticky="nse", padx=12, pady=12)

        # Left panels
        self._panel_load_data()
        self._panel_calibration()
        self._panel_auto_seed_batch()   # <-- Status 삭제하고 여기로 대체
        self._panel_actions()

        # Center viewer
        self._panel_image_viewer()

        # Right panels
        self._panel_statistics()
        self._panel_results()
        self._panel_distribution()

    # -------------------------
    # Left Panels
    # -------------------------
    def _panel_load_data(self):
        box = ctk.CTkFrame(self.left, corner_radius=14)
        box.pack(fill="x", padx=10, pady=(10, 8))

        ctk.CTkLabel(box, text="Load Data", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )
        ctk.CTkButton(box, text="Load SEM Image", command=self.on_load_image).pack(
            fill="x", padx=12, pady=(0, 12)
        )

    def _panel_calibration(self):
        box = ctk.CTkFrame(self.left, corner_radius=14)
        box.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(box, text="Calibration", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(row, text="Known (nm)").pack(side="left")

        self.known_nm_var = tk.StringVar(value="100")
        ctk.CTkEntry(row, width=90, textvariable=self.known_nm_var).pack(side="right")

        ctk.CTkButton(box, text="Calibrate", fg_color="#f59e0b", hover_color="#d97706",
                      command=self.on_calibrate_start).pack(fill="x", padx=12, pady=(4, 8))

        self.scale_label_var = tk.StringVar(value="Scale: Not set")
        ctk.CTkLabel(box, textvariable=self.scale_label_var, text_color="#a1a1aa").pack(
            anchor="w", padx=12, pady=(0, 12)
        )

    def _panel_auto_seed_batch(self):
        """
        Status 창을 없애고, 그 자리(왼쪽 아래)에
        segmenteverygrain-like seed -> batch measure 실행 패널을 둔다.
        """
        box = ctk.CTkFrame(self.left, corner_radius=14)
        box.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(box, text="Auto (Seed → Measure)", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        # Parameters row
        r1 = ctk.CTkFrame(box, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=(0, 6))

        self.max_points_var = tk.StringVar(value=str(self.settings.seed_max_points))
        self.min_dist_var = tk.StringVar(value=str(self.settings.seed_min_distance_px))

        ctk.CTkLabel(r1, text="max").pack(side="left")
        ctk.CTkEntry(r1, width=70, textvariable=self.max_points_var).pack(side="left", padx=(6, 10))
        ctk.CTkLabel(r1, text="minDist").pack(side="left")
        ctk.CTkEntry(r1, width=70, textvariable=self.min_dist_var).pack(side="left", padx=(6, 0))

        # Run button
        def run_auto():
            if self.current_img_bgr is None:
                messagebox.showerror("No Image", "Load SEM image first.")
                return
            if self.nm_per_px is None or self.nm_per_px <= 0:
                messagebox.showerror("No Calibration", "Calibrate scale (nm/px) first.")
                return

            try:
                self.settings.seed_max_points = int(float(self.max_points_var.get()))
                self.settings.seed_min_distance_px = int(float(self.min_dist_var.get()))
            except Exception:
                messagebox.showerror("Param Error", "max/minDist must be numeric.")
                return

            try:
                self.run_state_var.set("Running...")
                self.update_idletasks()

                new_records = sem_core.batch_auto_measure_from_seeds(
                    image_bgr=self.current_img_bgr,
                    nm_per_px=float(self.nm_per_px),
                    settings=self.settings,
                    existing_records=self.records
                )
                self.records.extend(new_records)

                self.refresh_results_ui()
                self.run_state_var.set("Ready")
                messagebox.showinfo("Done", f"Added {len(new_records)} grains (seed batch).")

            except Exception as e:
                self.run_state_var.set("Ready")
                messagebox.showerror("Run Failed", str(e))

        ctk.CTkButton(box, text="Run Seed Batch", command=run_auto).pack(fill="x", padx=12, pady=(6, 6))

        self.run_state_var = tk.StringVar(value="Ready")
        ctk.CTkLabel(box, textvariable=self.run_state_var, text_color="#a1a1aa").pack(
            anchor="center", padx=12, pady=(0, 12)
        )

    def _panel_actions(self):
        box = ctk.CTkFrame(self.left, corner_radius=14)
        box.pack(fill="x", padx=10, pady=(8, 10))

        ctk.CTkLabel(box, text="Actions", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        ctk.CTkButton(box, text="Export Excel", fg_color="#10b981", hover_color="#059669",
                      command=self.on_export_excel).pack(fill="x", padx=12, pady=(6, 6))
        ctk.CTkButton(box, text="Delete Selected", fg_color="#ef4444", hover_color="#dc2626",
                      command=self.on_delete_selected).pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(box, text="Send to Origin", fg_color="#8b5cf6", hover_color="#7c3aed",
                      command=self.on_send_to_origin).pack(fill="x", padx=12, pady=(0, 12))

    # -------------------------
    # Center viewer
    # -------------------------
    def _panel_image_viewer(self):
        outer = ctk.CTkFrame(self.center, corner_radius=14)
        outer.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, bg="#0b0b0f", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        vs = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        hs = tk.Scrollbar(outer, orient="horizontal", command=self.canvas.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        self._tk_img = None

    def _show_image_on_canvas(self):
        if self.current_img_rgb is None:
            return
        img = Image.fromarray(self.current_img_rgb)
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
        self.canvas.config(scrollregion=(0, 0, img.width, img.height))

    # -------------------------
    # Right panels
    # -------------------------
    def _panel_statistics(self):
        box = ctk.CTkFrame(self.right, corner_radius=14)
        box.pack(fill="x", padx=10, pady=(10, 8))

        ctk.CTkLabel(box, text="Statistics", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 12))
        grid.grid_columnconfigure((0, 1), weight=1)

        self.stat_mean = tk.StringVar(value="- nm")
        self.stat_std = tk.StringVar(value="- nm")
        self.stat_min = tk.StringVar(value="- nm")
        self.stat_max = tk.StringVar(value="- nm")

        def stat_card(r, c, title, var):
            f = ctk.CTkFrame(grid, corner_radius=12)
            f.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
            ctk.CTkLabel(f, text=title, text_color="#a1a1aa").pack(pady=(10, 2))
            ctk.CTkLabel(f, textvariable=var, font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 10))

        stat_card(0, 0, "Mean", self.stat_mean)
        stat_card(0, 1, "Std Dev", self.stat_std)
        stat_card(1, 0, "Min", self.stat_min)
        stat_card(1, 1, "Max", self.stat_max)

    def _panel_results(self):
        box = ctk.CTkFrame(self.right, corner_radius=14)
        box.pack(fill="both", expand=False, padx=10, pady=8)

        ctk.CTkLabel(box, text="Results", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        inner = tk.Frame(box, bg="#111115")
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        cols = ("#", "Size (nm)")
        self.tree = tk.ttk.Treeview(inner, columns=cols, show="headings", height=10)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, anchor="center", width=120)
        self.tree.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

    def _panel_distribution(self):
        box = ctk.CTkFrame(self.right, corner_radius=14)
        box.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        ctk.CTkLabel(box, text="Distribution", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        self.fig = Figure(figsize=(4.2, 2.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig_canvas = FigureCanvasTkAgg(self.fig, master=box)
        self.fig_canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._plot_empty()

    # -------------------------
    # Events/actions
    # -------------------------
    def on_load_image(self):
        p = filedialog.askopenfilename(
            title="Select SEM image",
            filetypes=[("Image", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("All files", "*.*")]
        )
        if not p:
            return
        try:
            bgr = sem_core.read_image_bgr(p)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception as e:
            messagebox.showerror("Load Failed", str(e))
            return

        self.img_path = p
        self.current_img_bgr = bgr
        self.current_img_rgb = rgb

        self.records = []
        self.nm_per_px = None
        self.scale_label_var.set("Scale: Not set")
        self.calib_mode = False
        self.calib_points = []
        self.refresh_results_ui()
        self._show_image_on_canvas()

    def on_calibrate_start(self):
        if self.current_img_rgb is None:
            messagebox.showerror("No Image", "Load SEM image first.")
            return
        self.calib_mode = True
        self.calib_points = []
        messagebox.showinfo("Calibration", "Click 2 endpoints of scale bar on the image.")

    def on_canvas_click(self, event):
        if self.current_img_rgb is None:
            return
        x = int(self.canvas.canvasx(event.x))
        y = int(self.canvas.canvasy(event.y))

        if self.calib_mode:
            self.calib_points.append((x, y))
            r = 4
            self.canvas.create_oval(x - r, y - r, x + r, y + r, outline="#f59e0b", width=2)
            if len(self.calib_points) >= 2:
                try:
                    known_nm = float(self.known_nm_var.get())
                    nmpp = sem_core.nm_per_px_from_two_points(self.calib_points[0], self.calib_points[1], known_nm)
                    self.nm_per_px = nmpp
                    self.scale_label_var.set(f"Scale: {nmpp:.4f} nm/px")
                except Exception as e:
                    messagebox.showerror("Calibration Failed", str(e))
                finally:
                    self.calib_mode = False
            return

    def on_export_excel(self):
        if not self.records:
            messagebox.showerror("No Data", "No results to export.")
            return
        p = filedialog.asksaveasfilename(
            title="Save Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")]
        )
        if not p:
            return

        rows = []
        for i, r in enumerate(self.records, 1):
            rows.append({
                "index": i,
                "eq_d_nm": float(r.get("eq_d_nm", 0.0)),
                "area_px2": int(r.get("area_px2", 0)),
                "area_um2": float(r.get("area_um2", 0.0)),
                "method": str(r.get("method", "")),
            })
        pd.DataFrame(rows).to_excel(p, index=False)
        messagebox.showinfo("Saved", f"Excel saved:\n{p}")

    def on_delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idxs = []
        for item in sel:
            vals = self.tree.item(item, "values")
            if not vals:
                continue
            try:
                idxs.append(int(vals[0]) - 1)
            except Exception:
                pass
        idxs = sorted(set(idxs), reverse=True)
        for idx in idxs:
            if 0 <= idx < len(self.records):
                self.records.pop(idx)
        self.refresh_results_ui()

    def on_send_to_origin(self):
        if not self.records:
            messagebox.showerror("No Data", "No results to send.")
            return
        data = [float(r.get("eq_d_nm", 0.0)) for r in self.records if float(r.get("eq_d_nm", 0.0)) > 0]
        if not data:
            messagebox.showerror("No Size Data", "eq_d_nm is empty. Calibrate first.")
            return
        ok = sem_core.try_origin_histogram_direct(
            data_list=data,
            show_origin=self.settings.origin_show,
            force_exe_launch=self.settings.origin_force_exe_launch,
            try_lognorm_fit=self.settings.origin_try_lognorm_fit,
        )
        if not ok:
            messagebox.showerror("Origin Failed", "Origin automation failed. (pywin32/Origin install check)")
        else:
            messagebox.showinfo("Origin", "Sent to Origin.")

    # -------------------------
    # UI refresh
    # -------------------------
    def refresh_results_ui(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        sizes = []
        for i, r in enumerate(self.records, 1):
            s = float(r.get("eq_d_nm", 0.0))
            sizes.append(s)
            self.tree.insert("", "end", values=(i, f"{s:.2f}" if s > 0 else "-"))

        self._update_stats(sizes)
        self._update_hist(sizes)

    def _update_stats(self, sizes: List[float]):
        arr = np.array([s for s in sizes if s > 0], dtype=float)
        if arr.size == 0:
            self.stat_mean.set("- nm")
            self.stat_std.set("- nm")
            self.stat_min.set("- nm")
            self.stat_max.set("- nm")
            return
        self.stat_mean.set(f"{arr.mean():.2f} nm")
        self.stat_std.set(f"{arr.std(ddof=1) if arr.size > 1 else 0.0:.2f} nm")
        self.stat_min.set(f"{arr.min():.2f} nm")
        self.stat_max.set(f"{arr.max():.2f} nm")

    def _plot_empty(self):
        self.ax.clear()
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.fig_canvas.draw_idle()

    def _update_hist(self, sizes: List[float]):
        arr = np.array([s for s in sizes if s > 0], dtype=float)
        if arr.size == 0:
            self._plot_empty()
            return

        self.ax.clear()
        self.ax.hist(arr, bins=min(30, max(5, int(math.sqrt(arr.size)))))
        self.ax.set_xlabel("Grain Size (nm)")
        self.ax.set_ylabel("Counts")
        self.ax.grid(False)
        self.fig_canvas.draw_idle()


if __name__ == "__main__":
    app = SEMApp()
    app.mainloop()
