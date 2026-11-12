"""Local library, its server routes and the apply command (no network, no desktop)."""

import http.client
import io
import json
import threading
from datetime import date, timedelta
from random import Random

import pytest
from PIL import Image

from mood_engine import cli, desktop, fetch, library, pipeline, selection, server, themes
from mood_engine.sources import ALL_SOURCES, Candidate

from .conftest import FIREBOX, SOLARIZED_LIGHT

DAY = date(2026, 11, 12)


def png(color="#111111", size=(64, 36)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Isolated library dirs and a two-theme index."""
    monkeypatch.setenv("MOOD_ENGINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOOD_ENGINE_STATE_DIR", str(tmp_path / "state"))
    # Never the user's real hooks.toml: tests must not run their hooks.
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(tmp_path / "config"))
    themes = tmp_path / "themes"
    (themes / "schemes").mkdir(parents=True)
    (themes / "schemes" / "firebox.json").write_text(json.dumps(FIREBOX))
    (themes / "schemes" / "solarized-light.json").write_text(json.dumps(SOLARIZED_LIGHT))
    (themes / "defaults.json").write_text(json.dumps({"dark": "firebox", "light": "solarized-light"}))
    monkeypatch.setenv("THEMES_DIR", str(themes))
    monkeypatch.setenv("THEMES_STATE_DIR", str(tmp_path / "themes-state"))
    return tmp_path


def save(key, theme="firebox", color="#111111"):
    source, id = key.split(":")
    file, thumb, w, h = library.store_image(source, id, png(color))
    with library.edit() as lib:
        library.add(lib, key, {"source": source, "id": id, "width": w, "height": h},
                    file, thumb, theme, 80.0)


# --- store -------------------------------------------------------------------

def test_store_writes_image_thumb_and_rejects_non_images(dirs):
    save("wallhaven:abc")
    lib = library.load()
    assert library.file_path(lib, "wallhaven:abc").read_bytes()[:4] == b"\x89PNG"
    assert Image.open(library.thumb_path(lib, "wallhaven:abc")).format == "JPEG"
    assert lib["themes"]["firebox"]["wallpapers"] == ["wallhaven:abc"]
    assert lib["wallpapers"]["wallhaven:abc"]["scores"] == {"firebox": 80.0}
    with pytest.raises(library.LibraryError, match="not an image"):
        library.store_image("wallhaven", "bad", b"<html>rate limited</html>")
    # atomic writes leave no temp files behind
    assert not list((dirs / "state").glob(".*tmp")) and not list((dirs / "data").rglob(".*tmp"))


def test_ids_cannot_escape_the_data_dir(dirs):
    file, thumb, _, _ = library.store_image("pexels", "../../evil", png())
    assert "/" not in file and (dirs / "data" / "wallpapers" / file).is_file()


# --- choosing ------------------------------------------------------------------

def test_daily_rotation_keeps_a_pick_for_the_day(dirs):
    for k in ("w:a", "w:b", "w:c"):
        save(k)
    lib = library.load()
    rng = Random(1)
    first = library.choose(lib, "firebox", today=DAY, rng=rng)
    assert library.choose(lib, "firebox", today=DAY, rng=rng) == first
    nxt = library.choose(lib, "firebox", today=DAY, rng=rng, force_next=True)
    assert nxt != first
    tomorrow = library.choose(lib, "firebox", today=DAY + timedelta(days=1), rng=rng)
    assert tomorrow != nxt
    assert lib["themes"]["firebox"]["changed"] == (DAY + timedelta(days=1)).isoformat()


def test_pin_wins_and_unpin_returns_to_rotation(dirs):
    for k in ("w:a", "w:b"):
        save(k)
    lib = library.load()
    library.pin(lib, "firebox", "w:b")
    for i in range(5):
        assert library.choose(lib, "firebox", today=DAY + timedelta(days=i), force_next=True) == "w:b"
    library.pin(lib, "firebox", None)
    assert library.choose(lib, "firebox", today=DAY + timedelta(days=9), rng=Random(0)) == "w:a"
    with pytest.raises(library.LibraryError):
        library.pin(lib, "solarized-light", "w:a")  # not paired there


def test_no_wallpapers_means_no_choice(dirs):
    assert library.choose(library.load(), "firebox") is None


def test_unpair_deletes_files_only_when_no_theme_uses_them(dirs):
    save("w:a")
    with library.edit() as lib:
        library.pair(lib, "w:a", "solarized-light")
        path = library.file_path(lib, "w:a")
        library.pin(lib, "firebox", "w:a")
        assert library.unpair(lib, "w:a", "firebox") is False
        assert lib["themes"]["firebox"]["pinned"] is None
    assert path.is_file()
    with library.edit() as lib:
        assert library.unpair(lib, "w:a", "solarized-light") is True
    assert not path.exists() and "w:a" not in library.load()["wallpapers"]


# --- apply / CLI -----------------------------------------------------------------

def test_apply_sets_the_desktop_and_print_mode_does_not(dirs, monkeypatch, capsys):
    save("w:a")
    calls = []
    monkeypatch.setattr(desktop, "set_wallpaper", lambda *p: calls.append(p))
    assert cli.main(["apply", "firebox"]) == 0
    assert calls and calls[0][0].name == "w-a.png"
    calls.clear()
    assert cli.main(["apply", "firebox", "--print"]) == 0
    assert not calls and capsys.readouterr().out.strip().endswith("w-a.png")
    assert cli.main(["apply", "solarized-light"]) == 1  # nothing saved for it
    assert "no wallpapers saved" in capsys.readouterr().err


def test_apply_dry_run_changes_nothing(dirs, capsys):
    save("w:a")
    before = library.library_path().read_text()
    assert cli.main(["apply", "firebox", "--dry-run"]) == 0
    assert "would use" in capsys.readouterr().out
    assert library.library_path().read_text() == before


def test_library_listing(dirs, capsys):
    save("w:a")
    assert cli.main(["library"]) == 0
    out = capsys.readouterr().out
    assert "firebox" in out and "w:a" in out


# --- server ----------------------------------------------------------------------

@pytest.fixture
def srv(dirs, monkeypatch):
    httpd = server.make_server(pipeline.Options(), "firebox", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def request(httpd, method, path, body=None, headers=None):
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = conn.getresponse()
    return r.status, r.read()


def cand(source="wallhaven", id="abc"):
    return Candidate(source=source, id=id, page_url="https://example.invalid/p", thumb_url="",
                     preview_url="", full_url="https://example.invalid/full.png",
                     width=64, height=36, author="Ada", author_url="https://example.invalid/@ada")


def test_server_save_pair_apply_and_remove(srv, monkeypatch):
    srv.state.cands["wallhaven:abc"] = cand()
    fetched = []
    monkeypatch.setattr(fetch, "get_bytes", lambda url, **kw: fetched.append(url) or png())
    applied = []
    monkeypatch.setattr(desktop, "set_wallpaper", lambda *p: applied.append(p))

    code, body = request(srv, "POST", "/api/save", {"key": "wallhaven:abc", "theme": "firebox"})
    assert code == 200 and json.loads(body)["downloaded"] is True
    assert fetched == ["https://example.invalid/full.png"]
    # saving for a second theme pairs without downloading again
    code, body = request(srv, "POST", "/api/save", {"key": "wallhaven:abc", "theme": "solarized-light"})
    assert code == 200 and json.loads(body)["downloaded"] is False and len(fetched) == 1

    code, html = request(srv, "GET", "/library?theme=firebox")
    assert code == 200 and b"wallhaven-abc.png" in html and b'data-act="pin"' in html
    code, img = request(srv, "GET", "/lib/thumbs/wallhaven-abc.jpg")
    assert code == 200 and img[:2] == b"\xff\xd8"
    assert request(srv, "GET", "/lib/wallpapers/..%2F..%2Fstate%2Flibrary.json")[0] == 404

    code, body = request(srv, "POST", "/api/apply", {"key": "wallhaven:abc", "theme": "firebox"})
    assert code == 200 and applied[0][0].name == "wallhaven-abc.png"
    assert library.load()["themes"]["firebox"]["current"] == "wallhaven:abc"

    assert request(srv, "POST", "/api/pin", {"key": "wallhaven:abc", "theme": "firebox"})[0] == 200
    assert library.load()["themes"]["firebox"]["pinned"] == "wallhaven:abc"
    code, body = request(srv, "POST", "/api/unpair", {"key": "wallhaven:abc", "theme": "firebox"})
    assert json.loads(body) == {"deleted": False}
    code, body = request(srv, "POST", "/api/unpair", {"key": "wallhaven:abc", "theme": "solarized-light"})
    assert json.loads(body) == {"deleted": True}


def test_server_save_pings_unsplash_download_endpoint(srv, monkeypatch):
    c = cand("unsplash", "u1")
    srv.state.cands[c.key] = c
    pinged = []
    monkeypatch.setattr(ALL_SOURCES["unsplash"], "track_download",
                        lambda cd: pinged.append(cd.key) or "https://example.invalid/tracked.png")
    fetched = []
    monkeypatch.setattr(fetch, "get_bytes", lambda url, **kw: fetched.append(url) or png())
    assert request(srv, "POST", "/api/save", {"key": c.key, "theme": "firebox"})[0] == 200
    assert pinged == [c.key] and fetched == ["https://example.invalid/tracked.png"]


def test_server_refuses_foreign_requests(srv):
    ok = {"key": "x", "theme": "firebox"}
    assert request(srv, "POST", "/api/pin", ok, {"Origin": "https://evil.example"})[0] == 403
    assert request(srv, "POST", "/api/pin", ok, {"Content-Type": "text/plain"})[0] == 415
    assert request(srv, "GET", "/library", headers={"Host": "evil.example:80"})[0] == 403
    assert request(srv, "POST", "/api/pin", {"key": None, "theme": "nope"})[0] == 400
    code, body = request(srv, "POST", "/api/save", {"key": "wallhaven:gone", "theme": "firebox"})
    assert code == 404 and b"rerun the search" in body
    code, body = request(srv, "POST", "/api/apply", {"theme": "firebox"})
    assert code == 409 and b"no wallpapers saved" in body


# --- use: global theme switch ---------------------------------------------------

@pytest.fixture
def mac(monkeypatch):
    """Fake OS: appearance and wallpaper calls are recorded, nothing real changes."""
    state = {"appearance": "dark", "set_appearance": [], "wallpapers": []}
    monkeypatch.setattr(themes, "system_appearance", lambda: state["appearance"])

    def set_appearance(dark):
        state["set_appearance"].append(dark)
        state["appearance"] = "dark" if dark else "light"
    monkeypatch.setattr(desktop, "set_appearance", set_appearance)
    monkeypatch.setattr(desktop, "set_wallpaper", lambda *p: state["wallpapers"].append(p[0].name))
    return state


def test_use_writes_current_json_and_applies_wallpaper(dirs, mac, capsys):
    current = dirs / "themes-state" / "current.json"
    current.parent.mkdir()
    current.write_text(json.dumps({"light": "solarized-light", "extra": 1}))
    save("w:a")
    assert cli.main(["use", "firebox"]) == 0
    assert json.loads(current.read_text()) == {"light": "solarized-light", "extra": 1, "dark": "firebox"}
    assert mac["wallpapers"] == ["w-a.png"]
    assert themes.choose_theme("system").id == "firebox"
    assert not list(current.parent.glob(".*tmp"))


def test_use_other_variant_waits_for_appearance(dirs, mac, capsys):
    save("w:s", theme="solarized-light")
    assert cli.main(["use", "solarized-light"]) == 0
    assert "becomes active" in capsys.readouterr().out
    assert mac["wallpapers"] == [] and mac["set_appearance"] == []
    assert selection.read() == {"light": "solarized-light"}


def test_use_with_appearance_flips_mode_then_applies(dirs, mac):
    save("w:s", theme="solarized-light")
    assert cli.main(["use", "solarized-light", "--appearance"]) == 0
    assert mac["set_appearance"] == [False] and mac["wallpapers"] == ["w-s.png"]


def test_use_without_saved_wallpapers_still_switches(dirs, mac, capsys):
    assert cli.main(["use", "firebox"]) == 0
    assert selection.read() == {"dark": "firebox"}
    assert "no wallpapers saved" in capsys.readouterr().out


def test_use_rejects_unknown_and_system(dirs, mac):
    assert cli.main(["use", "nope"]) == 2
    assert cli.main(["use", "system"]) == 2
    assert selection.read() == {}


def test_use_keeps_a_symlinked_current_json(dirs, mac):
    real = dirs / "elsewhere" / "current.json"
    real.parent.mkdir()
    real.write_text("{}")
    link = dirs / "themes-state" / "current.json"
    link.parent.mkdir()
    link.symlink_to(real)
    assert cli.main(["use", "firebox"]) == 0
    assert link.is_symlink() and json.loads(real.read_text()) == {"dark": "firebox"}
