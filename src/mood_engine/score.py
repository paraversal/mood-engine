"""Score an image palette against a Base24 theme, in OKLab.

Three parts, each in 0..1:

background  The large-area lightness of the image sits in the theme's
            background band (roles bg / bg-inset / surface / surface-raised,
            i.e. base00-base02 plus overrides), and a good share of the area is
            close to one of those colours (tint differences count double).
palette     Area-weighted mean OKLab distance from each image cluster to the
            nearest scheme colour (all 24 palette slots + resolved roles).
penalty     Area of saturated clusters whose hue is far from every chromatic
            scheme colour (e.g. a big blue sky against a warm theme).

total = 100 * (w_bg*background + w_pal*palette + w_pen*(1 - penalty))
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .color import chroma, hex_to_oklab, hue_deg, hue_diff
from .palette import Cluster
from .themes import Theme

BG_ROLES = ("bg", "bg-inset", "surface", "surface-raised")


@dataclass
class Weights:
    background: float = 0.4
    palette: float = 0.4
    penalty: float = 0.2
    # tuning constants
    light_sigma: float = 0.12     # OKLab L tolerance outside the bg band
    bg_near: float = 0.05         # OKLab distance counted as "background colour"
    bg_tint: float = 2.0          # a/b weight in the bg distance: tints show on big areas
    bg_area_target: float = 0.6   # this much near-bg area gives full marks
    pal_scale: float = 0.06       # palette = exp(-mean_dist / pal_scale)
    sat_min: float = 0.05         # chroma below this is "neutral"
    sat_full: float = 0.15        # chroma at which a cluster counts fully saturated
    hue_tol: float = 20.0         # degrees of hue slack before a miss starts
    hue_span: float = 40.0        # degrees over which a miss ramps to 1
    pen_area_full: float = 0.3    # saturated off-hue area giving full penalty


@dataclass
class SchemeColors:
    variant: str
    bg: np.ndarray      # (m, 3)
    all: np.ndarray     # (n, 3)
    hues: np.ndarray    # (h, 3) chromatic subset
    bg_band: tuple[float, float]

    @classmethod
    def from_theme(cls, theme: Theme, sat_min: float = 0.04) -> "SchemeColors":
        bg_hex = [theme.roles[r] for r in BG_ROLES if r in theme.roles] or [theme.palette["base00"]]
        all_hex = sorted(set(theme.palette.values()) | set(theme.roles.values()))
        bg = np.array([hex_to_oklab(h) for h in dict.fromkeys(bg_hex)])
        allc = np.array([hex_to_oklab(h) for h in all_hex])
        hues = allc[chroma(allc) >= sat_min]
        return cls(theme.variant, bg, allc, hues, (float(bg[:, 0].min()), float(bg[:, 0].max())))


@dataclass
class Score:
    total: float
    background: float
    palette: float
    penalty: float
    details: dict = field(default_factory=dict)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    cw = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cw, cw[-1] / 2)])


def _min_dist(points: np.ndarray, refs: np.ndarray, ab_weight: float = 1.0) -> np.ndarray:
    d = points[:, None, :] - refs[None, :, :]
    d[..., 1:] *= ab_weight
    return np.sqrt((d ** 2).sum(axis=2)).min(axis=1)


def score_palette(clusters: list[Cluster], scheme: SchemeColors | Theme,
                  w: Weights | None = None) -> Score:
    w = w or Weights()
    if isinstance(scheme, Theme):
        scheme = SchemeColors.from_theme(scheme)
    lab = np.array([c.lab for c in clusters])
    wt = np.array([c.weight for c in clusters], dtype=float)
    wt = wt / wt.sum()

    # (a) background fit
    l_med = _weighted_median(lab[:, 0], wt)
    lo, hi = scheme.bg_band
    gap = max(lo - l_med, 0.0, l_med - hi)
    lightness = float(np.exp(-0.5 * (gap / w.light_sigma) ** 2))
    d_bg = _min_dist(lab, scheme.bg, w.bg_tint)
    bg_area = float((wt * np.exp(-((d_bg / w.bg_near) ** 2))).sum())
    background = 0.5 * lightness + 0.5 * min(1.0, bg_area / w.bg_area_target)

    # (b) palette fit
    d_all = _min_dist(lab, scheme.all)
    mean_d = float((wt * d_all).sum())
    palette = float(np.exp(-mean_d / w.pal_scale))

    # (c) saturated off-scheme hues
    c = chroma(lab)
    sat = np.clip((c - w.sat_min) / (w.sat_full - w.sat_min), 0, 1)
    if len(scheme.hues):
        hd = hue_diff(hue_deg(lab)[:, None], hue_deg(scheme.hues)[None, :]).min(axis=1)
    else:
        hd = np.full(len(lab), 180.0)
    miss = np.clip((hd - w.hue_tol) / w.hue_span, 0, 1)
    off_area = float((wt * sat * miss).sum())
    penalty = min(1.0, off_area / w.pen_area_full)

    total = 100.0 * (w.background * background + w.palette * palette + w.penalty * (1 - penalty))
    return Score(
        total=round(total, 1), background=round(background, 3), palette=round(palette, 3),
        penalty=round(penalty, 3),
        details={"lightness_median": round(l_med, 3), "lightness_fit": round(lightness, 3),
                 "bg_area": round(bg_area, 3), "mean_dist": round(mean_d, 4),
                 "off_hue_area": round(off_area, 3)},
    )
