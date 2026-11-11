"""Translate scheme colours into each API's colour vocabulary."""

from __future__ import annotations

import numpy as np

from .color import chroma, hex_to_oklab, hue_deg, hue_diff
from .themes import Theme

# Wallhaven's fixed colour filter list (hex without '#').
WALLHAVEN_COLORS = [
    "660000", "990000", "cc0000", "cc3333", "ea4c88", "993399", "663399", "333399",
    "0066cc", "0099cc", "66cccc", "77cc33", "669900", "336600", "666600", "999900",
    "cccc33", "ffff00", "ffcc33", "ff9900", "ff6600", "cc6633", "996633", "663300",
    "000000", "999999", "cccccc", "ffffff", "424153",
]
_WH_LAB = np.array([hex_to_oklab(c) for c in WALLHAVEN_COLORS])

# Unsplash's named colours; chromatic ones anchored at an OKLCH hue angle.
UNSPLASH_HUES = {
    "red": 25.0, "orange": 55.0, "yellow": 95.0, "green": 140.0,
    "teal": 190.0, "blue": 255.0, "purple": 300.0, "magenta": 340.0,
}


def snap_wallhaven(hex_color: str) -> str:
    """Nearest Wallhaven filter colour in OKLab (chroma weighted up so hue wins)."""
    lab = hex_to_oklab(hex_color)
    d = _WH_LAB - lab
    d[:, 1:] *= 1.5
    return WALLHAVEN_COLORS[int(np.argmin((d ** 2).sum(axis=1)))]


def unsplash_name(hex_color: str) -> str:
    lab = hex_to_oklab(hex_color)
    c = float(chroma(lab))
    if c < 0.045:
        L = float(lab[0])
        if L < 0.45:
            return "black"
        if L > 0.8:
            return "white"
        return "black_and_white"
    h = float(hue_deg(lab))
    return min(UNSPLASH_HUES, key=lambda n: float(hue_diff(h, UNSPLASH_HUES[n])))


def pexels_color(hex_color: str) -> str:
    return hex_color.lower()


def key_colors(theme: Theme, n: int = 4) -> list[tuple[str, str]]:
    """The scheme's key colours as (label, hex): bg, accent, then the most
    saturated distinct hue slots (base08-base0F). Distinct = different hue."""
    out: list[tuple[str, str]] = []
    if bg := theme.roles.get("bg", theme.palette.get("base00")):
        out.append(("bg", bg))
    if (acc := theme.roles.get("accent")) and acc != bg:
        out.append(("accent", acc))
    slots = [f"base{i:02X}" for i in range(0x08, 0x10)]
    cand = [(s, theme.palette[s]) for s in slots if s in theme.palette]
    cand.sort(key=lambda sc: -float(chroma(hex_to_oklab(sc[1]))))
    for slot, hx in cand:
        if len(out) >= n:
            break
        lab = hex_to_oklab(hx)
        if float(chroma(lab)) < 0.05:
            continue
        clash = any(
            float(chroma(hex_to_oklab(o))) >= 0.05
            and float(hue_diff(hue_deg(lab), hue_deg(hex_to_oklab(o)))) < 35
            for _, o in out
        )
        if not clash:
            out.append((slot, hx))
    return out[:n]
