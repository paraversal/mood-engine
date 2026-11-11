"""Pipeline query planning, duplicate removal and the CLI shortcut (no network)."""

from PIL import Image, ImageDraw

from mood_engine import pipeline
from mood_engine.cli import with_default_command
from mood_engine.palette import extract_palette, image_signature
from mood_engine.score import Score
from mood_engine.sources import Candidate, Source


class FakeSource(Source):
    name = "fake"
    bg_hints = True

    def __init__(self):
        self.calls = []

    def token(self, hex_color):
        return hex_color

    def search(self, query, token, min_w, min_h, page=1):
        self.calls.append((query, token, page))
        return []


def plan(theme, monkeypatch, **opts):
    src = FakeSource()
    monkeypatch.setitem(pipeline.ALL_SOURCES, "fake", src)
    run = pipeline.Run(theme=theme, opts=None, results=[])
    pipeline.fetch_candidates(theme, pipeline.Options(sources=("fake",), **opts), run)
    return src.calls


def test_light_theme_adds_background_hints(solarized_light, monkeypatch):
    calls = plan(solarized_light, monkeypatch)
    bg = solarized_light.roles["bg"]
    hinted = {q for q, tok, _ in calls if q}
    assert hinted == set(pipeline.BG_HINTS["light"])
    # hints only ride on the background colour query
    assert all(tok == bg for q, tok, _ in calls if q)


def test_dark_theme_and_user_keywords_get_no_hints(firebox, solarized_light, monkeypatch):
    assert all(q == "" for q, _, _ in plan(firebox, monkeypatch))
    assert all(q == "forest" for q, _, _ in plan(solarized_light, monkeypatch, query="forest"))


def _result(img, key):
    cand = Candidate(source="fake", id=key, page_url="", thumb_url="", preview_url="",
                     full_url="", width=1, height=1)
    return pipeline.Result(cand, Score(0, 0, 0, 0), extract_palette(img), image_signature(img))


def _scene(bg, fg):
    img = Image.new("RGB", (320, 180), bg)
    ImageDraw.Draw(img).ellipse((100, 40, 220, 160), fill=fg)
    return img


def test_dedupe_drops_reuploads_but_keeps_distinct_images():
    a = _scene("#111111", "#fe8019")
    reupload = a.resize((640, 360)).resize((300, 169))  # rescaled copy, other size
    shifted = _scene("#111111", "#458588")              # same layout, other colour
    # mostly-black minimal images: tiny mean distance, but not the same picture
    small = Image.new("RGB", (320, 180), "#111111")
    ImageDraw.Draw(small).rectangle((150, 80, 170, 100), fill="#ebdbb2")
    rs = [_result(a, "a"), _result(reupload, "b"), _result(shifted, "c"),
          _result(Image.new("RGB", (320, 180), "#111111"), "d"), _result(small, "e")]
    kept = pipeline.dedupe(rs, pipeline.Options().dedupe)
    assert [r.cand.id for r in kept] == ["a", "c", "d", "e"]
    assert len(pipeline.dedupe([_result(a, "a"), _result(reupload, "b")], 0)) == 2


def test_cli_defaults_to_serve():
    assert with_default_command([]) == ["serve"]
    assert with_default_command(["firebox", "-q", "x"]) == ["serve", "firebox", "-q", "x"]
    assert with_default_command(["-q", "x"]) == ["serve", "-q", "x"]
    assert with_default_command(["search", "firebox"]) == ["search", "firebox"]
    assert with_default_command(["--help"]) == ["--help"]
