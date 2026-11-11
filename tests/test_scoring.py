"""Scoring tests on synthetic images."""

import numpy as np
import pytest
from PIL import Image

from mood_engine.color import hex_to_oklab, oklab_to_hex, srgb_to_oklab
from mood_engine.palette import extract_palette, kmeans
from mood_engine.score import score_palette


def blocks(size, parts):
    """Image made of vertical stripes: parts = [(hex, fraction), ...]."""
    w, h = size
    img = Image.new("RGB", size)
    x = 0
    for i, (hx, frac) in enumerate(parts):
        x1 = w if i == len(parts) - 1 else x + round(w * frac)
        img.paste(Image.new("RGB", (x1 - x, h), hx), (x, 0))
        x = x1
    return img


def score(img, theme):
    return score_palette(extract_palette(img), theme)


# --- colour maths ---------------------------------------------------------

def test_oklab_reference_values():
    assert np.allclose(srgb_to_oklab([1, 1, 1]), [1, 0, 0], atol=1e-4)
    assert np.allclose(srgb_to_oklab([0, 0, 0]), [0, 0, 0], atol=1e-6)
    # Björn Ottosson's reference for sRGB red
    assert np.allclose(srgb_to_oklab([1, 0, 0]), [0.62796, 0.22486, 0.12585], atol=1e-3)


def test_oklab_roundtrip():
    for hx in ["#111111", "#fe8019", "#268bd2", "#fdf6e3"]:
        assert oklab_to_hex(hex_to_oklab(hx)) == hx


# --- palette extraction ---------------------------------------------------

def test_palette_area_weights_two_colours():
    img = blocks((100, 60), [("#111111", 0.7), ("#fe8019", 0.3)])
    pal = extract_palette(img, k=8)
    assert len(pal) == 2  # empty / duplicate clusters dropped
    assert pal[0].hex == "#111111" and pal[0].weight == pytest.approx(0.7, abs=0.03)
    assert pal[1].hex == "#fe8019" and pal[1].weight == pytest.approx(0.3, abs=0.03)


def test_kmeans_single_colour_does_not_crash():
    x = np.tile(hex_to_oklab("#336699"), (500, 1))
    c, w = kmeans(x, k=8)
    assert len(c) == 1 and w[0] == pytest.approx(1.0)


# --- scoring --------------------------------------------------------------

def test_theme_coloured_image_scores_near_top(firebox):
    img = blocks((120, 80), [("#111111", 0.6), ("#272524", 0.2), ("#fe8019", 0.1), ("#d79921", 0.1)])
    s = score(img, firebox)
    assert s.total > 90
    assert s.penalty == 0


def test_dark_theme_prefers_dark_image(firebox):
    dark = blocks((120, 80), [("#151413", 0.8), ("#cc6633", 0.2)])
    light = blocks((120, 80), [("#f4f1ea", 0.8), ("#cc6633", 0.2)])
    sd, sl = score(dark, firebox), score(light, firebox)
    assert sd.background > 0.8 > 0.3 > sl.background
    assert sd.total > sl.total + 20


def test_light_theme_prefers_light_image(solarized_light):
    cream = blocks((120, 80), [("#f8f0dc", 0.75), ("#2aa198", 0.25)])
    black = blocks((120, 80), [("#0a0a0a", 0.75), ("#2aa198", 0.25)])
    sc, sb = score(cream, solarized_light), score(black, solarized_light)
    assert sc.background > sb.background
    assert sc.total > sb.total + 20


def test_off_scheme_saturated_hue_is_penalised(firebox):
    # Firebox has warm hues and a muted teal/blue; a vivid blue (h~265°) is foreign.
    blue = blocks((120, 80), [("#111111", 0.5), ("#1e4bff", 0.5)])
    orange = blocks((120, 80), [("#111111", 0.5), ("#fe8019", 0.5)])
    sb, so = score(blue, firebox), score(orange, firebox)
    assert sb.penalty > 0.9
    assert so.penalty == 0
    assert so.total > sb.total


def test_neutral_grey_areas_are_not_penalised(firebox):
    grey = blocks((120, 80), [("#111111", 0.5), ("#777777", 0.5)])
    assert score(grey, firebox).penalty == 0


def test_same_blue_is_fine_for_solarized(solarized_light):
    img = blocks((120, 80), [("#fdf6e3", 0.6), ("#268bd2", 0.4)])
    assert score(img, solarized_light).penalty == 0


def test_closer_palette_scores_higher(firebox):
    near = blocks((120, 80), [("#111111", 0.6), ("#ebdbb2", 0.4)])
    far = blocks((120, 80), [("#111111", 0.6), ("#b0e0ff", 0.4)])
    assert score(near, firebox).palette > score(far, firebox).palette


def test_background_tint_matters(firebox):
    # Same lightness, but a cool navy background is not firebox's warm near-black.
    warm = blocks((120, 80), [("#1c1a19", 0.85), ("#fe8019", 0.15)])
    navy = blocks((120, 80), [("#1c2333", 0.85), ("#fe8019", 0.15)])
    assert score(warm, firebox).background > score(navy, firebox).background + 0.2
