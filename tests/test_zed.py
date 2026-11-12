"""Zed: the template, theme blending, and a hook's file `fade`."""

import json

import pytest

from mood_engine import cli, sync, template, terminal, themes, zed

from .test_library import dirs, mac  # noqa: F401  (fixtures)


def render(t: themes.Theme) -> dict:
    return json.loads(template.render(zed.ZED_TEMPLATE, template.context(t)))


def test_template_renders_a_theme_family(firebox, solarized_light):
    fam = render(firebox)
    [theme] = fam["themes"]
    st = theme["style"]
    assert theme["name"] == "mood-engine" and theme["appearance"] == "dark"
    assert st["editor.background"] == "#111111" and st["text.accent"] == "#fe8019"
    assert st["search.match_background"] == "#fe801940" and st["syntax"]["keyword"]["color"] == "#b16286"
    assert render(solarized_light)["themes"][0]["appearance"] == "light"
    ansi = [st[f"terminal.ansi.{n}"] for n in ("black", "red", "green", "yellow", "blue",
                                               "magenta", "cyan", "white")]
    assert ansi == [terminal.colours(firebox)[f"4;{i}"] for i in range(8)]  # same as Ghostty


def test_blend(firebox, solarized_light):
    a, b = firebox, solarized_light
    assert themes.blend(a, b, 1) == b
    start = themes.blend(a, b, 0)
    assert start.palette == a.palette and start.variant == "dark" and start.id == b.id
    mid = themes.blend(a, b, 0.5)
    assert mid.variant == "light" and a.roles["bg"] < mid.roles["bg"] < b.roles["bg"]
    assert render(mid)["themes"][0]["style"]["editor.background"] == mid.roles["bg"]


@pytest.fixture
def zed_hook(dirs, monkeypatch):
    """A fading hook writing `bg=…` to out.txt; every frame is recorded at each sleep."""
    cfg = dirs / "config"
    (cfg / "templates").mkdir(parents=True)
    (cfg / "templates" / "t").write_text("bg={{role-bg-hex}}\n")
    out = dirs / "out.txt"
    sync.hooks_path().write_text(f'[[hook]]\nname = "zed"\ntemplate = "templates/t"\n'
                                 f'output = "{out}"\nfade = 440\n')
    frames: list[str] = []
    monkeypatch.setattr(sync, "_sleep", lambda s: frames.append(out.read_text()))
    return out, frames


def test_hook_fade_steps_the_output_from_the_previous_theme(dirs, mac, zed_hook):
    out, frames = zed_hook
    sync.sync()
    assert frames == [] and out.read_text() == "bg=111111\n"  # first sync: no previous
    mac["appearance"] = "light"
    rep = sync.sync()
    assert rep["hooks"][0]["ok"] and rep["hooks"][0]["output_changed"]
    assert len(frames) == 3                                     # 440 ms / 110 ms = 4 steps
    bgs = [int(f[3:5], 16) for f in frames]
    assert 0x11 < bgs[0] < bgs[1] < bgs[2] < 0xfd               # brightening towards fdf6e3
    assert out.read_text() == "bg=fdf6e3\n"


def test_hook_fade_skipped_without_change_or_previous(dirs, mac, zed_hook, capsys):
    out, frames = zed_hook
    sync.sync()
    assert cli.main(["hooks", "--run", "zed"]) == 0           # forced: no previous theme
    mac["appearance"] = "light"
    out.write_text("bg=fdf6e3\n")                             # already shows the new theme
    sync.sync()
    assert frames == []
    assert cli.main(["hooks"]) == 0 and "(fade 440 ms)" in capsys.readouterr().out


@pytest.mark.parametrize("extra, msg", [
    ('fade = 0\ntemplate = "t"\noutput = "o"', "milliseconds"),
    ('fade = "fast"\ntemplate = "t"\noutput = "o"', "milliseconds"),
    ("fade = true\ntemplate = \"t\"\noutput = \"o\"", "milliseconds"),
    ('fade = 500\nrun = "true"', "needs `template`"),
])
def test_fade_config_validation(tmp_path, extra, msg):
    p = tmp_path / "hooks.toml"
    p.write_text(f'[[hook]]\nname = "x"\n{extra}\n')
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks(p)


def test_fingerprint_of_hooks_without_fade_is_unchanged():
    h = sync.Hook(name="w", run="true")
    assert sync.hook_fingerprint(h, "fp") == sync._sha("fp", {"name": "w", "run": "true",
                                                               "template": None, "output": None}, None)
    assert sync.hook_fingerprint(sync.Hook(name="w", run="true", fade=500.0), "fp") != \
        sync.hook_fingerprint(h, "fp")


def test_init_writes_zed_template_and_example_hook_parses(dirs, mac, monkeypatch, capsys):
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(dirs / "fresh"))
    assert cli.main(["hooks", "--init"]) == 0
    tpl = dirs / "fresh" / "templates" / "zed.json"
    assert cli.main(["render", str(tpl)]) == 0
    capsys.readouterr()
    body = "\n".join(l[2:] for l in sync.HOOKS_TEMPLATE.splitlines()
                     if l.startswith("# ") and ("[[hook]]" in l or " = " in l))
    block = body[body.index('[[hook]]\nname = "Zed"'):].split("[[hook]]")[1]
    p = dirs / "fresh" / "zed-only.toml"
    p.write_text("[[hook]]" + block)
    [h] = sync.load_hooks(p)
    assert h.fade == 800 and h.output.name == "mood-engine.json" and h.run is None
