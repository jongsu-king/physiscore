import numpy as np
from scipy.signal import savgol_filter
from pybaselines import Baseline

def smooth_signal(y: np.ndarray, window: int, poly: int) -> np.ndarray:
    if len(y) < 7: return y.copy()
    w = int(window)
    if w < 5: return y.copy()
    if w % 2 == 0: w += 1
    w = min(w, len(y)-1 if (len(y)-1) % 2 == 1 else len(y)-2)
    if w < 5: return y.copy()
    p = min(int(poly), w - 2)
    return savgol_filter(y, window_length=w, polyorder=p)

def baseline_asls(x: np.ndarray, y: np.ndarray, lam: float, p: float, max_iter: int) -> np.ndarray:
    base = Baseline(x_data=x)
    bl, _ = base.asls(y, lam=lam, p=p, max_iter=max_iter)
    return bl
