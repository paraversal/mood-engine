"""Source parsing with mocked API payloads (no network, no keys) and recolor."""

from urllib.parse import parse_qs, urlparse

from PIL import Image

from mood_engine import sources
from mood_engine.palette import extract_palette
from mood_engine.recolor import recolor
from mood_engine.score import score_palette

UNSPLASH = {"results": [
    {"id": "abc", "width": 6000, "height": 4000, "color": "#0c0c0c", "blur_hash": "x",
     "urls": {"thumb": "T", "small": "S", "full": "F", "regular": "R", "raw": "W"},
     "links": {"html": "https://unsplash.com/photos/abc", "download_location": "https://api.unsplash.com/photos/abc/download"},
     "user": {"name": "Ada", "links": {"html": "https://unsplash.com/@ada"}}},
    {"id": "small", "width": 800, "height": 600, "urls": {"thumb": "", "small": "", "full": ""},
     "links": {"html": "", "download_location": ""}, "user": {"name": "", "links": {"html": ""}}},
]}

PEXELS = {"photos": [
    {"id": 42, "width": 5000, "height": 3000, "url": "https://www.pexels.com/photo/42/",
     "photographer": "Bo", "photographer_url": "https://www.pexels.com/@bo", "avg_color": "#111111",
     "src": {"original": "O", "medium": "M", "small": "S", "tiny": "T"}},
]}


def test_unsplash_parse_and_attribution(monkeypatch):
    seen = {}

    def fake(url, headers=None, **kw):
        seen["url"], seen["headers"] = url, headers
        return UNSPLASH

    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "k123")
    monkeypatch.setattr(sources.fetch, "get_json", fake)
    out = sources.Unsplash().search("", "black", 1920, 1080)
    assert [c.id for c in out] == ["abc"]  # below min resolution dropped
    c = out[0]
    assert c.page_url.endswith("utm_source=mood-engine&utm_medium=referral")
    assert c.author == "Ada" and "utm_source" in c.author_url
    assert c.download_location.endswith("/download")
    assert seen["headers"]["Authorization"] == "Client-ID k123"
    q = parse_qs(urlparse(seen["url"]).query)
    assert q["color"] == ["black"] and q["query"] == ["wallpaper"]
    assert "k123" not in seen["url"]  # key never in the URL / cache key


def test_pexels_parse_and_hex_colour(monkeypatch):
    seen = {}

    def fake(url, headers=None, **kw):
        seen["url"] = url
        return PEXELS

    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setattr(sources.fetch, "get_json", fake)
    out = sources.Pexels().search("forest", "#111111", 1920, 1080)
    assert out[0].id == "42" and out[0].author == "Bo"
    q = parse_qs(urlparse(seen["url"]).query)
    assert q["color"] == ["#111111"] and q["query"] == ["forest"]


def test_sources_without_keys_are_unavailable(monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert sources.Wallhaven().available()
    assert not sources.Unsplash().available()
    assert not sources.Pexels().available()


def test_recolor_improves_score(firebox):
    img = Image.new("RGB", (80, 50), "#10203a")       # cool navy, foreign to firebox
    img.paste(Image.new("RGB", (30, 50), "#2f6fff"), (50, 0))
    before = score_palette(extract_palette(img), firebox).total
    after = score_palette(extract_palette(recolor(img, firebox)), firebox).total
    assert after > before
