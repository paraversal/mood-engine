"""The theme JSON template and a hook's `notify` (a Darwin notification after each write)."""

import json
import sys

import pytest

from mood_engine import presets, sync, template, themes

from .test_library import dirs, mac  # noqa: F401  (fixtures)


def render(t: themes.Theme) -> dict:
    return json.loads(template.render(presets.builtin_path("theme.json").read_text(),
                                      template.context(t)))


def test_template_is_valid_json_with_every_role_and_colour(firebox, solarized_light):
    for t in (firebox, solarized_light):
        data = render(t)
        assert (data["id"], data["variant"]) == (t.id, t.variant)
        assert set(data["roles"]) == set(themes.ROLE_DEFAULTS)
        assert list(data["palette"]) == themes.PALETTE_KEYS
        assert data["roles"]["bg"] == "#" + t.roles["bg"].lstrip("#").lower()
        assert all(len(v) == 7 and v[0] == "#" for v in [*data["roles"].values(),
                                                         *data["palette"].values()])


@pytest.fixture
def posts(monkeypatch):
    """Replaces notify_post: records (name, the output file's content at that moment)."""
    seen: list[tuple[str, str]] = []
    state = {"out": None, "fail": None}

    def post(name):
        seen.append((name, state["out"].read_text() if state["out"] else ""))
        return state["fail"]

    monkeypatch.setattr(sync, "_post", post)
    return seen, state


@pytest.fixture
def json_hook(dirs, posts, monkeypatch):
    out = dirs / "theme.json"
    (dirs / "config").mkdir(exist_ok=True)
    sync.hooks_path().write_text(f'[[hook]]\npreset = "json"\noutput = "{out}"\nfade = 440\n')
    posts[1]["out"] = out
    monkeypatch.setattr(sync, "_sleep", lambda s: None)
    return out


def test_posts_after_each_fade_frame_and_the_final_write(dirs, mac, posts, json_hook):
    seen, _ = posts
    sync.sync()
    assert [n for n, _ in seen] == [presets.NOTIFY_NAME]        # first sync: no fade
    seen.clear()
    mac["appearance"] = "light"
    rep = sync.sync()
    assert rep["hooks"][0]["ok"]
    assert len(seen) == 4                                         # 3 frames + the final write
    bgs = [int(json.loads(text)["roles"]["bg"][1:3], 16) for _, text in seen]
    assert bgs == sorted(bgs) and bgs[-1] == 0xfd                 # each post sees its own frame
    assert json.loads(json_hook.read_text())["variant"] == "light"


def test_hooks_run_posts_once_even_when_unchanged(dirs, mac, posts, json_hook):
    seen, _ = posts
    sync.sync()
    seen.clear()
    [res] = sync.run_hooks(sync.load_hooks(), {}, sync.active_theme("dark"))
    assert res["ok"] and not res["output_changed"] and len(seen) == 1


def test_failed_post_fails_the_hook(dirs, mac, posts, json_hook):
    posts[1]["fail"] = "notify local.mood-engine.theme: notify_post returned 1000000"
    [res] = sync.sync()["hooks"]
    assert not res["ok"] and "notify_post returned" in res["output"]
    assert json.loads(json_hook.read_text())["id"]                # the file is written anyway


def test_no_notify_no_post(dirs, mac, posts):
    (dirs / "config").mkdir(exist_ok=True)
    sync.hooks_path().write_text(f'[[hook]]\npreset = "css"\noutput = "{dirs / "c.css"}"\n')
    sync.sync()
    assert posts[0] == []


def test_notify_is_not_in_the_fingerprint_when_unset(dirs, mac):
    (dirs / "config").mkdir(exist_ok=True)
    sync.hooks_path().write_text(f'[[hook]]\nname = "x"\npreset = "css"\n')
    [h] = sync.load_hooks()
    spec = {"name": "x", "run": None, "template": "builtin:colors.css", "output": h.output}
    assert sync.hook_fingerprint(h, "fp") == sync._sha("fp", spec, h.template.read_bytes().hex())


@pytest.mark.parametrize("extra, msg", [
    ('notify = ""\ntemplate = "t"\noutput = "o"', "non-empty string"),
    ('notify = 3\ntemplate = "t"\noutput = "o"', "non-empty string"),
    ('notify = "a.b"\nrun = "true"', "needs `template`"),
])
def test_notify_config_validation(tmp_path, extra, msg):
    p = tmp_path / "hooks.toml"
    p.write_text(f'[[hook]]\nname = "x"\n{extra}\n')
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks(p)


@pytest.mark.skipif(sys.platform != "darwin", reason="notify(3) is macOS")
def test_real_notify_post_succeeds():
    assert sync._notify_post("local.mood-engine.test") is None
