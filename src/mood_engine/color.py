"""sRGB <-> OKLab conversions (vectorised with numpy)."""

from __future__ import annotations

import numpy as np

_M1 = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
])
_M2 = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
])
_M2_INV = np.array([
    [1.0, 0.3963377774, 0.2158037573],
    [1.0, -0.1055613458, -0.0638541728],
    [1.0, -0.0894841775, -1.2914855480],
])
_M1_INV = np.array([
    [4.0767416621, -3.3077115913, 0.2309699292],
    [-1.2684380046, 2.6097574011, -0.3413193965],
    [-0.0041960863, -0.7034186147, 1.7076147010],
])


def hex_to_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(round(float(np.clip(c, 0, 1)) * 255)) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def srgb_to_oklab(rgb) -> np.ndarray:
    """rgb: (..., 3) floats in 0..1 -> (..., 3) OKLab (L in 0..1)."""
    lin = srgb_to_linear(rgb)
    lms = lin @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_srgb(lab) -> np.ndarray:
    lms = (np.asarray(lab, dtype=float) @ _M2_INV.T) ** 3
    return linear_to_srgb(lms @ _M1_INV.T)


def hex_to_oklab(h: str) -> np.ndarray:
    return srgb_to_oklab(hex_to_rgb(h))


def oklab_to_hex(lab) -> str:
    return rgb_to_hex(oklab_to_srgb(lab))


def chroma(lab) -> np.ndarray:
    lab = np.asarray(lab, dtype=float)
    return np.hypot(lab[..., 1], lab[..., 2])


def hue_deg(lab) -> np.ndarray:
    lab = np.asarray(lab, dtype=float)
    return np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360


def hue_diff(h1, h2) -> np.ndarray:
    """Smallest absolute angle between hues, in degrees (0..180)."""
    d = np.abs(np.asarray(h1) - np.asarray(h2)) % 360
    return np.minimum(d, 360 - d)
