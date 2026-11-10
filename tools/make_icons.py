"""Draw the launcher icons of the tools added in 3.5 (logo/<name>.png).

The older icons are bitmaps of unknown origin; these six are drawn here so
they can be regenerated: a framed miniature of the tool's main graph with
the tool's name under it, in the same size and colours.

    python tools/make_icons.py [output folder]
"""
from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 6                                   # supersampling
W, H = 98, 112
TOP, BOTTOM = (21, 119, 177), (3, 52, 95)
FILL_TOP, FILL_BOTTOM = (255, 255, 255), (214, 237, 249)
INK = (2, 41, 75)
CURVE = (16, 104, 164)
ACCENT = (226, 120, 30)
GRID = (150, 185, 205)
FRAME = (6, 3, 91, 88)                  # x0, y0, x1, y1 of the frame, in icon pixels
PLOT = (20, 14, 80, 72)                 # plot area inside the frame


def _font(size: float) -> ImageFont.FreeTypeFont:
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, int(round(size * S)))
    import matplotlib
    return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans-Bold.ttf"),
                              int(round(size * S)))


def _vgradient(size, top, bottom) -> Image.Image:
    w, h = size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(int(round(a + (b - a) * t)) for a, b in zip(top, bottom)))
    return col.resize((w, h))


def _xy(u: float, v: float):
    """Plot coordinates (0-1, v upwards) to supersampled pixels."""
    x0, y0, x1, y1 = PLOT
    return ((x0 + u * (x1 - x0)) * S, (y1 - v * (y1 - y0)) * S)


def _line(d: ImageDraw.ImageDraw, pts, color=CURVE, width=2.4):
    d.line([_xy(u, v) for u, v in pts], fill=color, width=int(round(width * S)), joint="curve")


def _dots(d: ImageDraw.ImageDraw, pts, color=CURVE, r=2.3):
    for u, v in pts:
        x, y = _xy(u, v)
        d.ellipse([x - r * S, y - r * S, x + r * S, y + r * S], fill=color)


def _dashed(d: ImageDraw.ImageDraw, a, b, color=ACCENT, width=1.4, n=7):
    for i in range(n):
        t0, t1 = i / n, (i + 0.55) / n
        _line(d, [(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                  (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], color, width)


def draw_sclc(d):
    _line(d, [(0.04, 0.10), (0.36, 0.27)])                       # ohmic, slope 1
    _line(d, [(0.36, 0.27), (0.56, 0.70)], ACCENT)               # trap filling
    _line(d, [(0.56, 0.70), (0.98, 0.94)])                       # Child, slope 2
    _dashed(d, (0.36, 0.0), (0.36, 0.27), GRID, 1.2, 4)


def draw_intensity(d):
    pts = [(0.06 + 0.15 * i, 0.16 + 0.125 * i) for i in range(7)]
    _line(d, [(0.0, 0.11), (1.0, 0.944)], ACCENT, 1.6)
    _dots(d, pts)


def draw_trpl(d):
    pts = []
    for i in range(60):
        u = 0.10 + 0.88 * i / 59
        t = (u - 0.10) / 0.88
        y = 0.72 * math.exp(-t / 0.07) + 0.28 * math.exp(-t / 0.55)
        pts.append((u, 0.06 + 0.88 * (math.log10(max(y, 1e-3)) + 1.5) / 1.5))
    _line(d, [(0.02, 0.06), (0.08, 0.06), (0.10, 0.94)] + pts)


def draw_eis(d):
    def arc(c, r, col):
        _line(d, [(c + r * math.cos(math.pi * (1 - k / 40)), 0.08 + 1.55 * r * math.sin(math.pi * k / 40))
                  for k in range(41)], col)
    arc(0.27, 0.19, CURVE)
    arc(0.69, 0.27, ACCENT)


def draw_cv(d):
    pts = [(0.08 + 0.105 * i, 0.90 - 0.095 * i) for i in range(6)]
    _line(d, [(0.02, 0.955), (0.98, 0.085)], ACCENT, 1.6)
    _dots(d, pts)
    _dots(d, [(0.78, 0.36), (0.90, 0.33)], GRID, 2.0)


def draw_stability(d):
    pts = []
    for i in range(50):
        t = i / 49
        pts.append((0.03 + 0.95 * t, 0.10 + 0.84 * (0.80 + 0.14 * math.exp(-t / 0.10) - 0.30 * t) / 0.94))
    _dashed(d, (0.0, 0.52), (1.0, 0.52), ACCENT, 1.3, 8)
    _line(d, pts)


ICONS = [
    ("SCLC", "SCLC", draw_sclc),
    ("Light intensity", "Suns-Voc", draw_intensity),
    ("TRPL", "TRPL", draw_trpl),
    ("Impedance", "Impedance", draw_eis),
    ("C-V", "C-V", draw_cv),
    ("Stability", "Stability", draw_stability),
]


def make(label: str, draw) -> Image.Image:
    big = Image.new("RGB", (W * S, H * S), (255, 255, 255))
    x0, y0, x1, y1 = [v * S for v in FRAME]
    shadow = Image.new("L", big.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle([x0 + S, y0 + 2 * S, x1 + S, y1 + 2 * S], radius=13 * S, fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(2.2 * S))
    big.paste(Image.new("RGB", big.size, (120, 150, 170)), mask=shadow)
    outer = Image.new("L", big.size, 0)
    ImageDraw.Draw(outer).rounded_rectangle([x0, y0, x1, y1], radius=13 * S, fill=255)
    big.paste(_vgradient(big.size, TOP, BOTTOM), mask=outer)
    b = 4 * S
    inner = Image.new("L", big.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle([x0 + b, y0 + b, x1 - b, y1 - b], radius=9 * S, fill=255)
    big.paste(_vgradient(big.size, FILL_TOP, FILL_BOTTOM), mask=inner)
    d = ImageDraw.Draw(big)
    px0, py0, px1, py1 = [v * S for v in PLOT]
    d.line([(px0, py0 - 2 * S), (px0, py1), (px1 + 2 * S, py1)], fill=INK, width=int(1.6 * S))   # axes
    draw(d)
    font = _font(12.5)
    size = 12.5
    while d.textlength(label, font=font) > (W - 6) * S and size > 8:
        size -= 0.5
        font = _font(size)
    tw = d.textlength(label, font=font)
    d.text(((W * S - tw) / 2, 93.5 * S), label, font=font, fill=INK)
    return big.resize((W, H), Image.LANCZOS).convert("RGBA")


def main(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name, label, draw in ICONS:
        path = os.path.join(out_dir, f"{name}.png")
        make(label, draw).save(path)
        print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logo"))
