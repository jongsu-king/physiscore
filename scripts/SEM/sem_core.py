
# sem_core.py - SEM Analysis Core Logic (No UI)
import os
import math
import time
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import cv2
import numpy as np


# =========================
# Settings (editable)
# =========================
@dataclass
class Settings:
    # -------------------------
    # Segmentation (your existing core)
    # -------------------------
    roi_half: int = 150
    fg_thresh_ratio: float = 0.25
    close_ksize: int = 7
    close_iter: int = 2

    ff_lo: int = 10
    ff_hi: int = 10

    enable_merge: bool = True
    merge_grad_thresh: float = 10.0

    min_area_px: int = 80
    max_area_frac: float = 0.30
    whole_image_frac_guard: float = 0.90

    brush_radius: int = 12
    undo_depth: int = 40

    out_dir: str = ""
    out_prefix: str = ""

    origin_show: bool = True
    origin_try_lognorm_fit: bool = True
    origin_force_exe_launch: bool = True

    # -------------------------
    # NEW: segmenteverygrain-like seed generation
    # (boundary -> distance transform -> peak local max -> watershed -> centroids)
    # -------------------------
    seed_enable: bool = True
    seed_max_points: int = 300           # limit for runtime
    seed_min_distance_px: int = 12       # peak separation in distance map
    seed_canny1: int = 40
    seed_canny2: int = 120
    seed_boundary_dilate: int = 3        # odd number recommended
    seed_interior_open_iter: int = 1

    # clustering/dedup
    seed_use_dbscan_if_available: bool = True
    seed_dbscan_eps: float = 20.0
    seed_dbscan_min_samples: int = 2
    seed_dedup_thresh_px: int = 15       # fallback dedup radius

    # batch auto-measure
    batch_skip_if_inside_existing: bool = True
    batch_skip_if_overlap_existing: bool = True

    # ignore black footer (scale bar/label area)
    black_footer_enable: bool = True
    black_footer_thresh: int = 25       # mean intensity threshold (0-255)
    black_footer_max_frac: float = 0.25 # max portion of image height to ignore
    footer_std_thresh: float = 12.0     # grayscale std-dev threshold per row
    footer_edge_density_thresh: float = 0.02  # edge density threshold per row
    footer_gap_tolerance: int = 4       # allow a few noisy rows (text) in footer
    footer_min_height_px: int = 12      # require at least this many rows to treat as footer
    footer_force_cutoff_frac: float = 0.12  # force-ignore bottom fraction (0 to disable)


# =========================
# Image I/O
# =========================
def read_image_bgr(path: str) -> np.ndarray:
    """
    Read image supporting unicode paths.
    Handles grayscale and BGRA safely.
    """
    with open(path.encode("utf-8"), "rb") as f:
        bytes_data = bytearray(f.read())
    numpyarray = np.asarray(bytes_data, dtype=np.uint8)
    img = cv2.imdecode(numpyarray, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"OpenCV failed to read: {path}")

    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif len(img.shape) == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def preprocess(gray: np.ndarray) -> np.ndarray:
    """Preprocess grayscale image with blur and CLAHE."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(blur)


def detect_black_footer_cutoff(gray: np.ndarray, thresh: int, max_frac: float) -> Optional[int]:
    """
    Detect a dark footer band near the bottom (legacy, mean-intensity based).
    Returns cutoff y (rows [cutoff:] are ignored) or None.
    """
    h, _ = gray.shape[:2]
    max_h = int(h * max_frac)
    if max_h <= 0:
        return None
    row_means = gray.mean(axis=1)
    y = h - 1
    count = 0
    while y >= 0 and count < max_h and row_means[y] <= thresh:
        count += 1
        y -= 1
    if count <= 0:
        return None
    return max(0, h - count)


def detect_footer_cutoff(gray: np.ndarray, settings: Settings) -> Optional[int]:
    """
    Detect a low-texture footer band near the bottom (e.g., SEM status bar).
    Uses row-wise std-dev + edge density with gap tolerance.
    Returns cutoff y (rows [cutoff:] are ignored) or None.
    """
    h, _ = gray.shape[:2]
    if settings.footer_force_cutoff_frac and settings.footer_force_cutoff_frac > 0:
        frac = min(0.9, max(0.01, float(settings.footer_force_cutoff_frac)))
        return int(h * (1.0 - frac))
    max_h = int(h * settings.black_footer_max_frac)
    if max_h <= 0:
        return None

    # edge density
    edges = cv2.Canny(gray, 40, 120)
    edge_density = (edges > 0).mean(axis=1)
    row_std = gray.std(axis=1)

    y = h - 1
    count = 0
    gaps = 0
    while y >= 0 and count < max_h:
        is_footer = (row_std[y] <= settings.footer_std_thresh) and (edge_density[y] <= settings.footer_edge_density_thresh)
        if is_footer:
            count += 1
            gaps = 0
        else:
            gaps += 1
            count += 1
            if gaps > settings.footer_gap_tolerance:
                break
        y -= 1

    if count < settings.footer_min_height_px:
        return None
    return max(0, h - count)


def get_tiles(img: np.ndarray, grid: Tuple[int, int], overlap: int) -> List[Tuple[np.ndarray, int, int]]:
    """
    Split image into grid tiles with overlap.
    Returns list of (tile_img, x_offset, y_offset).
    """
    h, w = img.shape[:2]
    rows, cols = grid
    tiles = []

    step_h = h // rows
    step_w = w // cols

    for r in range(rows):
        for c in range(cols):
            x_start = c * step_w
            y_start = r * step_h
            x_end = w if c == cols - 1 else (c + 1) * step_w
            y_end = h if r == rows - 1 else (r + 1) * step_h

            x0 = max(0, x_start - overlap)
            y0 = max(0, y_start - overlap)
            x1 = min(w, x_end + overlap)
            y1 = min(h, y_end + overlap)

            crop = img[y0:y1, x0:x1]
            tiles.append((crop, x0, y0))
    return tiles


# =========================
# Calibration
# =========================
def nm_per_px_from_two_points(p0: Tuple[int, int], p1: Tuple[int, int], known_nm: float) -> float:
    dx = float(p1[0] - p0[0])
    dy = float(p1[1] - p0[1])
    px_len = math.hypot(dx, dy)
    if px_len <= 0:
        raise ValueError("Invalid calibration points (zero distance).")
    return float(known_nm) / px_len


# =========================
# Measurements
# =========================
def area_and_eq_diameter(mask: np.ndarray, nm_per_px: float) -> Tuple[int, float, float]:
    area_px2 = int(cv2.countNonZero(mask))
    area_nm2 = area_px2 * (nm_per_px ** 2)
    area_um2 = area_nm2 / 1e6
    eq_d_nm = 2.0 * math.sqrt(area_nm2 / math.pi) if area_nm2 > 0 else 0.0
    return area_px2, area_um2, eq_d_nm


# =========================
# Watershed & Floodfill (your existing)
# =========================
def watershed_labels(gray_enh: np.ndarray, seed_xy: Tuple[int, int], roi_half: int, fg_ratio: float):
    h, w = gray_enh.shape
    x, y = seed_xy
    x0, x1 = max(0, x - roi_half), min(w, x + roi_half)
    y0, y1 = max(0, y - roi_half), min(h, y + roi_half)
    roi = gray_enh[y0:y1, x0:x1]
    if roi.size == 0:
        return None, None, (x0, y0, x1, y1)

    _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.medianBlur(bw, 5)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    sure_bg = cv2.dilate(bw, np.ones((3, 3), np.uint8), iterations=2)

    dist = cv2.distanceTransform(bw, cv2.DIST_L2, 5)
    _, sure_fg = cv2.threshold(dist, fg_ratio * dist.max(), 255, 0)
    sure_fg = sure_fg.astype(np.uint8)

    unknown = cv2.subtract(sure_bg, sure_fg)

    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0

    roi_bgr = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    ws = cv2.watershed(roi_bgr, markers)
    return roi, ws, (x0, y0, x1, y1)


def merge_by_boundary_gradient(roi: np.ndarray, ws: np.ndarray, seed_rc: Tuple[int, int], grad_thresh: float):
    sy, sx = seed_rc
    seed_label = int(ws[sy, sx])
    if seed_label <= 1:
        return None

    gx = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)

    seed_mask = (ws == seed_label)
    seed_mask_u8 = (seed_mask.astype(np.uint8) * 255)
    seed_dil = cv2.dilate(seed_mask_u8, np.ones((3, 3), np.uint8), iterations=1).astype(bool)

    border = seed_dil & (~seed_mask)
    neighbor_labels = set(np.unique(ws[border]))
    neighbor_labels.discard(-1)
    neighbor_labels.discard(0)
    neighbor_labels.discard(1)
    neighbor_labels.discard(seed_label)

    merged = ws.copy()
    for lb in neighbor_labels:
        nb_mask = (ws == lb)
        nb_dil = cv2.dilate((nb_mask.astype(np.uint8) * 255), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
        bnd = seed_mask & nb_dil
        if not np.any(bnd):
            continue
        mean_grad = float(np.mean(grad[bnd]))
        if mean_grad < float(grad_thresh):
            merged[nb_mask] = seed_label

    return merged


def mask_from_ws(roi: np.ndarray, ws: np.ndarray, seed_rc: Tuple[int, int], close_ksize: int, close_iter: int):
    sy, sx = seed_rc
    seed_label = int(ws[sy, sx])
    if seed_label <= 1:
        return None

    mask = np.zeros_like(roi, dtype=np.uint8)
    mask[ws == seed_label] = 255

    k = max(3, int(close_ksize) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=int(close_iter))
    return mask


def floodfill_mask(gray_enh: np.ndarray, seed_xy: Tuple[int, int], lo: int, hi: int, close_ksize: int, close_iter: int):
    h, w = gray_enh.shape
    x, y = seed_xy
    mask = np.zeros((h + 2, w + 2), np.uint8)
    tmp = gray_enh.copy()
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(tmp, mask, (int(x), int(y)), 0, (int(lo),) * 3, (int(hi),) * 3, flags)
    m = (mask[1:-1, 1:-1] > 0).astype(np.uint8) * 255

    k = max(3, int(close_ksize) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=int(close_iter))
    return m


def perform_auto_segment(cv_enh: np.ndarray, x: int, y: int, settings: Settings) -> Optional[np.ndarray]:
    roi, ws, box = watershed_labels(cv_enh, (int(x), int(y)), settings.roi_half, settings.fg_thresh_ratio)
    if roi is None or ws is None:
        return None

    x0, y0, x1, y1 = box
    sy, sx = int(y) - y0, int(x) - x0

    ws2 = ws
    if settings.enable_merge:
        merged = merge_by_boundary_gradient(roi, ws, (sy, sx), settings.merge_grad_thresh)
        if merged is not None:
            ws2 = merged

    mask_roi = mask_from_ws(roi, ws2, (sy, sx), settings.close_ksize, settings.close_iter)

    H, W = cv_enh.shape
    full = np.zeros((H, W), dtype=np.uint8)

    if mask_roi is not None and cv2.countNonZero(mask_roi) > settings.min_area_px:
        full[y0:y1, x0:x1] = mask_roi
    else:
        full = floodfill_mask(cv_enh, (int(x), int(y)), settings.ff_lo, settings.ff_hi, settings.close_ksize, settings.close_iter)

    if cv2.countNonZero(full) > settings.whole_image_frac_guard * (H * W):
        return None

    return full


# =========================
# Overlap/inside checks
# =========================
def is_point_in_existing(records: List[Dict], x: int, y: int) -> bool:
    for r in records:
        m = r.get("mask")
        if m is None:
            continue
        if 0 <= y < m.shape[0] and 0 <= x < m.shape[1]:
            if m[y, x] > 0:
                return True
    return False


def check_mask_overlap(records: List[Dict], new_mask: np.ndarray) -> bool:
    for r in records:
        m = r.get("mask")
        if m is None:
            continue
        inter = cv2.bitwise_and(new_mask, m)
        if cv2.countNonZero(inter) > 0:
            return True
    return False


# =========================
# NEW: segmenteverygrain-like seed generator
# =========================
def _dedup_points_greedy(points: List[Tuple[int, int]], thresh: int) -> List[Tuple[int, int]]:
    if not points:
        return []
    pts = np.array(points, dtype=np.float32)
    keep = np.ones(len(pts), dtype=bool)
    for i in range(len(pts)):
        if not keep[i]:
            continue
        d = np.linalg.norm(pts[i + 1:] - pts[i], axis=1)
        close = np.where(d < float(thresh))[0] + (i + 1)
        keep[close] = False
    out = pts[keep].astype(int).tolist()
    return [(int(x), int(y)) for x, y in out]


def remove_duplicate_points(points: List[Tuple[int, int]], threshold: float) -> List[Tuple[int, int]]:
    """Wrapper for greedy deduplication used by external scripts."""
    return _dedup_points_greedy(points, int(threshold))


def _cluster_points_dbscan_if_available(points: List[Tuple[int, int]], eps: float, min_samples: int) -> List[Tuple[int, int]]:
    """
    If sklearn is available, cluster nearby seeds and replace cluster with mean point.
    Otherwise fallback to greedy dedup.
    """
    if not points:
        return []
    try:
        from sklearn.cluster import DBSCAN  # optional
    except Exception:
        return points

    pts = np.array(points, dtype=np.float32)
    db = DBSCAN(eps=float(eps), min_samples=int(min_samples)).fit(pts)
    labels = db.labels_
    out = []

    # noise
    noise = pts[labels == -1]
    for p in noise:
        out.append((int(p[0]), int(p[1])))

    # clusters
    for lb in sorted(set(labels)):
        if lb == -1:
            continue
        cluster = pts[labels == lb]
        xy = np.mean(cluster, axis=0)
        out.append((int(xy[0]), int(xy[1])))

    return out


def generate_seed_points_segmenteverygrain_like(gray_enh: np.ndarray, settings: Settings) -> List[Tuple[int, int]]:
    """
    CPU seed generator inspired by segmenteverygrain's boundary-distance-watershed prompt logic.
    Output: list of (x, y) seed points.
    """
    # 1) boundary map from edges
    edges = cv2.Canny(gray_enh, int(settings.seed_canny1), int(settings.seed_canny2))
    k = max(1, int(settings.seed_boundary_dilate) | 1)
    edges = cv2.dilate(edges, np.ones((k, k), np.uint8), iterations=1)

    # 2) interior = NOT boundary, then clean
    interior = (edges == 0).astype(np.uint8) * 255
    interior = cv2.morphologyEx(interior, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=int(settings.seed_interior_open_iter))

    # Optionally ignore black footer area
    if settings.black_footer_enable:
        try:
            cutoff = detect_footer_cutoff(gray_enh, settings)
            if cutoff is None:
                cutoff = detect_black_footer_cutoff(gray_enh, settings.black_footer_thresh, settings.black_footer_max_frac)
            if cutoff is not None and 0 < cutoff < gray_enh.shape[0]:
                interior[cutoff:, :] = 0
        except Exception:
            pass

    # remove huge background connected component by keeping only "thick" interior regions
    # (works better than nothing for SEM; you can tune later)
    # 3) distance transform and local maxima
    dist = cv2.distanceTransform((interior > 0).astype(np.uint8), cv2.DIST_L2, 5)
    if dist.max() <= 0:
        return []

    # local maxima (approx peak_local_max)
    dist_u8 = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    # non-maximum suppression via dilation
    dil = cv2.dilate(dist_u8, np.ones((3, 3), np.uint8), iterations=1)
    peaks = ((dist_u8 == dil) & (dist_u8 > 0)).astype(np.uint8) * 255

    # enforce min distance using connected components on dilated peaks
    md = max(1, int(settings.seed_min_distance_px))
    peaks = cv2.dilate(peaks, np.ones((md, md), np.uint8), iterations=1)
    num, labels, stats, centroids = cv2.connectedComponentsWithStats((peaks > 0).astype(np.uint8), connectivity=8)
    seeds = []
    H, W = gray_enh.shape
    for i in range(1, num):
        x, y = centroids[i]
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < W and 0 <= yi < H:
            seeds.append((xi, yi))

    # 4) cluster/dedup like segmenteverygrain (DBSCAN on centroids)
    if settings.seed_use_dbscan_if_available:
        clustered = _cluster_points_dbscan_if_available(seeds, settings.seed_dbscan_eps, settings.seed_dbscan_min_samples)
        seeds = clustered

    seeds = _dedup_points_greedy(seeds, settings.seed_dedup_thresh_px)

    # 5) cap
    if len(seeds) > int(settings.seed_max_points):
        seeds = seeds[: int(settings.seed_max_points)]
    return seeds


# =========================
# NEW: Batch auto measure from seeds
# =========================
def batch_auto_measure_from_seeds(
    image_bgr: np.ndarray,
    nm_per_px: float,
    settings: Settings,
    existing_records: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    1) preprocess -> generate seeds (segmenteverygrain-like)
    2) for each seed: perform_auto_segment -> compute size -> create record
    Returns: new_records
    """
    if existing_records is None:
        existing_records = []

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray_enh = preprocess(gray)

    cutoff = None
    if settings.black_footer_enable:
        cutoff = detect_footer_cutoff(gray, settings)
        if cutoff is None:
            cutoff = detect_black_footer_cutoff(gray, settings.black_footer_thresh, settings.black_footer_max_frac)

    seeds = generate_seed_points_segmenteverygrain_like(gray_enh, settings) if settings.seed_enable else []
    new_records: List[Dict] = []

    for (x, y) in seeds:
        if cutoff is not None and y >= cutoff:
            continue
        if settings.batch_skip_if_inside_existing and is_point_in_existing(existing_records + new_records, x, y):
            continue

        mask = perform_auto_segment(gray_enh, x, y, settings)
        if mask is None:
            continue
        if cutoff is not None and 0 < cutoff < mask.shape[0]:
            mask[cutoff:, :] = 0
            if cv2.countNonZero(mask) < int(settings.min_area_px):
                continue
        if cv2.countNonZero(mask) < int(settings.min_area_px):
            continue

        if settings.batch_skip_if_overlap_existing and check_mask_overlap(existing_records + new_records, mask):
            continue

        area_px2, area_um2, eq_d_nm = area_and_eq_diameter(mask, nm_per_px)

        new_records.append(
            dict(
                x=int(x), y=int(y),
                mask=mask,
                area_px2=int(area_px2),
                area_um2=float(area_um2),
                eq_d_nm=float(eq_d_nm),
                method="seed_batch",
            )
        )

    return new_records


# =========================
# Origin Automation (Robust)
# =========================
def find_origin_exe_from_registry() -> str:
    try:
        import winreg
    except ImportError:
        return ""

    candidates = []
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OriginLab\Origin"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\OriginLab\Origin"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\OriginLab\Origin"),
    ]

    for root, path in reg_paths:
        try:
            with winreg.OpenKey(root, path) as k:
                for vn in ["Path", "OriginPath", "ExePath", "InstallDir", "InstallPath"]:
                    try:
                        v, _ = winreg.QueryValueEx(k, vn)
                        if isinstance(v, str) and v:
                            candidates.append(v)
                    except Exception:
                        pass
        except Exception:
            pass

    for c in candidates:
        c = c.strip().strip('"')
        if c.lower().endswith("origin.exe") and os.path.exists(c):
            return c
        exe1 = os.path.join(c, "Origin.exe")
        if os.path.exists(exe1):
            return exe1
    return ""


def try_origin_histogram_direct(
    data_list: List[float],
    show_origin: bool = True,
    force_exe_launch: bool = True,
    exe_hint: str = "",
    try_lognorm_fit: bool = True,
) -> bool:
    try:
        import win32com.client
    except Exception:
        return False

    origin = None
    try:
        origin = win32com.client.Dispatch("Origin.ApplicationSI")
    except Exception:
        origin = None

    if origin is None and force_exe_launch:
        exe_path = exe_hint.strip() or find_origin_exe_from_registry()
        if exe_path and os.path.exists(exe_path):
            try:
                subprocess.Popen([exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                return False

            for _ in range(20):
                time.sleep(1.0)
                try:
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    if origin is not None:
                        break
                except Exception:
                    pass

    if origin is None:
        return False

    if show_origin:
        try:
            origin.Visible = 1
            origin.WindowState = 2
        except Exception:
            pass

    try:
        wb_name = origin.CreatePage(2, "GrainData", "Origin")
        origin.Execute(f"page.active$ = {wb_name};")
        origin.Execute("wks.ncols = 1;")
        origin.Execute('wks.col1.lname$ = "Grain Size";')
        origin.Execute('wks.col1.unit$ = "nm";')
        origin.Execute("wks.col1.type = 1;")
        origin.PutWorksheet(f"[{wb_name}]Sheet1", list(map(float, data_list)), 0, 0)
    except Exception:
        return False

    lt = r"""
    plotxy iy:=col(1) plot:=219 ogl:=<new>;
    label -xb "Grain Size (nm)";
    label -yl "Counts";
    xb.fsize = 30;
    yl.fsize = 30;
    layer.x.showAxes = 3;
    layer.x2.ticks = 0;
    layer.x.showLabels = 1;
    layer.x2.label.show = 0;
    layer.y.showAxes = 3;
    layer.y2.ticks = 0;
    layer.y.showLabels = 1;
    layer.y2.label.show = 0;
    legend.show=0;
    layer -a;
    """

    if try_lognorm_fit:
        lt += r"""
        fitdist iy:=1 dist:=Lognormal plot:=1;
        """

    try:
        origin.Execute(lt)
    except Exception:
        return False

    return True
