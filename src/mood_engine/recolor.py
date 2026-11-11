"""Stretch goal: nudge a near-miss wallpaper toward the theme palette.

A small built-in take on what lutgen does: every pixel is pulled toward a
Gaussian-weighted blend of nearby scheme colours in OKLab. Lightness is only
partly moved, so the image keeps its structure.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from .color import hex_to_oklab, oklab_to_srgb, srgb_to_oklab
from .themes import Theme


def recolor(img: Image.Image, theme: Theme, strength: float = 0.75, l_strength: float = 0.35,
            sigma: float = 0.07, max_side: int = 2560) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    w, h = img.size
    rgb = np.asarray(img, dtype=np.float32).reshape(-1, 3) / 255.0
    pal = np.array([hex_to_oklab(c) for c in sorted(set(theme.palette.values()))], dtype=np.float32)
    out = np.empty_like(rgb)
    step = 200_000
    for i in range(0, len(rgb), step):
        lab = srgb_to_oklab(rgb[i:i + step]).astype(np.float32)
        d2 = ((lab[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
        d2 -= d2.min(axis=1, keepdims=True)  # numerically safe softmin
        wts = np.exp(-d2 / (2 * sigma * sigma))
        target = (wts @ pal) / wts.sum(axis=1, keepdims=True)
        new = lab.copy()
        new[:, 0] += l_strength * (target[:, 0] - lab[:, 0])
        new[:, 1:] += strength * (target[:, 1:] - lab[:, 1:])
        out[i:i + step] = oklab_to_srgb(new)
    arr = (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8).reshape(h, w, 3)
    return Image.fromarray(arr)


def recolor_bytes(data: bytes, theme: Theme, **kw) -> bytes:
    out = recolor(Image.open(io.BytesIO(data)), theme, **kw)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92)
    return buf.getvalue()
