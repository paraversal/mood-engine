import json

from mood_engine import themes
from mood_engine.vocab import key_colors, snap_wallhaven, unsplash_name

from .conftest import FIREBOX, SOLARIZED_LIGHT


def test_snap_wallhaven():
    assert snap_wallhaven("#111111") == "000000"
    assert snap_wallhaven("#fdf6e3") == "ffffff"
    assert snap_wallhaven("#fe8019") in {"ff6600", "ff9900"}
    assert snap_wallhaven("#268bd2") in {"0066cc", "0099cc"}


def test_unsplash_names():
    assert unsplash_name("#111111") == "black"
    assert unsplash_name("#fdf6e3") == "white"
    assert unsplash_name("#fe8019") == "orange"
    assert unsplash_name("#268bd2") == "blue"
    assert unsplash_name("#cc241d") == "red"
    assert unsplash_name("#2aa198") == "teal"


def test_key_colors(firebox, solarized_light):
    kc = key_colors(firebox, 4)
    assert kc[0] == ("bg", "#111111")
    assert kc[1] == ("accent", "#fe8019")
    assert len(kc) == 4
    assert key_colors(solarized_light, 3)[:2] == [("bg", "#fdf6e3"), ("accent", "#268bd2")]


def test_reader_protocol(tmp_path, monkeypatch):
    d = tmp_path / "themes"
    (d / "schemes").mkdir(parents=True)
    (d / "schemes" / "firebox.json").write_text(json.dumps(FIREBOX))
    (d / "schemes" / "solarized-light.json").write_text(json.dumps(SOLARIZED_LIGHT))
    (d / "schemes" / "broken.json").write_text("{nope")
    (d / "roles.json").write_text(json.dumps(themes.ROLE_DEFAULTS))
    (d / "defaults.json").write_text(json.dumps({"dark": "firebox", "light": "solarized-light"}))
    state = tmp_path / "state"
    monkeypatch.setenv("THEMES_DIR", str(d))
    monkeypatch.setenv("THEMES_STATE_DIR", str(state))

    assert themes.list_themes() == ["firebox", "solarized-light"]
    assert themes.resolve_theme_id("system", "light") == "solarized-light"
    assert themes.resolve_theme_id("nope", "dark") == "firebox"
    state.mkdir()
    (state / "current.json").write_text(json.dumps({"dark": "solarized-light"}))
    assert themes.resolve_theme_id(None, "dark") == "solarized-light"
    t = themes.load_theme("firebox")
    assert t.roles["accent"] == "#fe8019" and t.roles["error"] == "#ff8678"
    assert t.roles["bg"] == "#111111"


def test_fallback_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("THEMES_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("THEMES_STATE_DIR", str(tmp_path / "missing-state"))
    t = themes.choose_theme("system", "dark")
    assert t.id.startswith("(embedded)")
