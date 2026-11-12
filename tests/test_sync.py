"""`sync`, hooks, `pin`/`unpin` and `status` (desktop and appearance calls faked)."""

import json
import time
from datetime import date, timedelta

import pytest

from mood_engine import cli, library, selection, sync, themes

from .test_library import DAY, dirs, mac, save  # noqa: F401  (fixtures)


@pytest.fixture
def hooks(dirs, monkeypatch):
    """Write hooks.toml; each hook appends its env to a log file the test reads back."""
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(dirs / "config"))
    log = dirs / "hooks.log"

    def write(*extra: str):
        (dirs / "config").mkdir(exist_ok=True)
        body = ('[[hook]]\nname = "log"\n'
                f'run = "echo \\"$MOOD_THEME $MOOD_PREVIOUS_THEME $MOOD_VARIANT\\" >> {log}"\n')
        sync.hooks_path().write_text(body + "".join(extra))

    def lines() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    write.lines = lines
    return write


def test_first_sync_applies_wallpaper_and_runs_hooks(dirs, mac, hooks):
    hooks()
    save("w:a")
    rep = sync.sync()
    assert rep["theme"] == "firebox" and rep["changed"] and rep["previous"] is None
    assert mac["wallpapers"] == ["w-a.png"] and rep["wallpaper_set"]
    assert hooks.lines() == ["firebox  dark"]
    assert [h["ok"] for h in rep["hooks"]] == [True]


def test_sync_without_change_does_nothing(dirs, mac, hooks):
    hooks()
    save("w:a")
    sync.sync(today=DAY)
    rep = sync.sync(today=DAY)
    assert not rep["changed"] and rep["hooks"] is None and not rep["wallpaper_set"]
    assert mac["wallpapers"] == ["w-a.png"] and hooks.lines() == ["firebox  dark"]


def test_appearance_flip_switches_theme_and_runs_hooks(dirs, mac, hooks):
    hooks()
    save("w:a")
    save("w:s", theme="solarized-light")
    sync.sync(today=DAY)
    mac["appearance"] = "light"
    rep = sync.sync(today=DAY)
    assert rep["theme"] == "solarized-light" and rep["previous"] == "firebox"
    assert mac["wallpapers"] == ["w-a.png", "w-s.png"]
    assert hooks.lines() == ["firebox  dark", "solarized-light firebox light"]


def test_new_day_rotates_wallpaper_without_hooks(dirs, mac, hooks):
    hooks()
    save("w:a")
    save("w:b")
    sync.sync(today=DAY)
    rep = sync.sync(today=DAY + timedelta(days=1))
    assert rep["wallpaper_set"] and rep["hooks"] is None
    assert len(mac["wallpapers"]) == 2 and hooks.lines() == ["firebox  dark"]


def test_current_json_written_elsewhere_is_picked_up(dirs, mac, hooks, monkeypatch):
    hooks()
    sync.sync(today=DAY)
    other = dirs / "themes" / "schemes" / "firebox-2.json"
    other.write_text((dirs / "themes" / "schemes" / "firebox.json").read_text())
    selection.set_global(themes.load_theme("firebox-2"))  # as another app would
    rep = sync.sync(today=DAY)
    assert rep["changed"] and rep["theme"] == "firebox-2"
    assert rep["note"] and "no wallpapers saved" in rep["note"]
    assert hooks.lines()[-1] == "firebox-2 firebox dark"


def test_failing_hook_is_reported_and_others_still_run(dirs, mac, hooks):
    hooks('\n[[hook]]\nname = "boom"\nrun = "echo nope >&2; exit 3"\n',
          '\n[[hook]]\nname = "slow"\nrun = "echo started; sleep 5; echo never"\ntimeout = 0.2\n',
          '\n[[hook]]\nname = "off"\nrun = "exit 1"\nenabled = false\n')
    rep = sync.sync()
    by = {h["name"]: h for h in rep["hooks"]}
    assert set(by) == {"log", "boom", "slow"}
    assert by["boom"]["code"] == 3 and by["boom"]["output"] == "nope"
    assert by["slow"]["code"] is None and by["slow"]["seconds"] < 2
    assert by["slow"]["output"] == "timed out after 0.2 s\nstarted"
    assert sync.read_state()["hooks"] == rep["hooks"]


def test_broken_hooks_file_is_an_error_but_sync_still_applies(dirs, mac, hooks):
    hooks()
    sync.hooks_path().write_text("[[hook]\n")
    save("w:a")
    rep = sync.sync()
    assert rep["error"].startswith("hooks:") and mac["wallpapers"] == ["w-a.png"]
    with pytest.raises(sync.HookConfigError):
        sync.load_hooks()


def test_sync_inside_a_hook_is_skipped(dirs, mac, monkeypatch):
    monkeypatch.setenv(sync.IN_HOOK_ENV, "1")
    assert sync.sync()["note"] == "skipped: called from a hook"
    assert not sync.sync_path().exists()


def test_use_runs_hooks_once_and_the_next_sync_is_a_no_op(dirs, mac, hooks, capsys):
    hooks()
    sync.sync(today=DAY)
    (dirs / "themes" / "schemes" / "ember.json").write_text(
        (dirs / "themes" / "schemes" / "firebox.json").read_text())
    assert cli.main(["use", "ember"]) == 0
    assert "hook: log: ok" in capsys.readouterr().out
    assert sync.sync()["hooks"] is None
    assert hooks.lines() == ["firebox  dark", "ember firebox dark"]


def test_use_same_theme_resets_wallpaper_without_hooks(dirs, mac, hooks):
    hooks()
    save("w:a")
    assert cli.main(["use", "firebox"]) == 0
    assert cli.main(["use", "firebox"]) == 0
    assert mac["wallpapers"] == ["w-a.png", "w-a.png"] and len(hooks.lines()) == 1


def test_hooks_init_list_and_run(dirs, mac, hooks, capsys):
    assert cli.main(["hooks", "--init"]) == 0
    assert sync.load_hooks() == []  # the template's examples are commented out
    hooks()
    assert cli.main(["hooks"]) == 0
    assert "- log" in capsys.readouterr().out
    assert cli.main(["hooks", "--run"]) == 0
    assert cli.main(["hooks", "--run"]) == 0
    assert len(hooks.lines()) == 2


def test_sync_json_cli(dirs, mac, capsys):
    assert cli.main(["sync", "--json", "--appearance", "light"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["theme"] == "solarized-light" and rep["hooks"] == []


def test_pin_and_unpin(dirs, mac, capsys):
    save("w:a")
    save("w:b")
    assert cli.main(["pin"]) == 1  # nothing current yet
    assert cli.main(["pin", "--key", "w:b"]) == 0
    lib = library.load()
    assert lib["themes"]["firebox"]["pinned"] == "w:b" == lib["themes"]["firebox"]["current"]
    assert cli.main(["unpin", "firebox"]) == 0
    assert library.load()["themes"]["firebox"]["pinned"] is None
    assert cli.main(["pin", "--key", "w:zzz"]) == 1


def test_status(dirs, mac, hooks, capsys):
    hooks()
    save("w:a")
    sync.sync()
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["active"]["id"] == "firebox" and st["selection"] == {"dark": "firebox",
                                                                     "light": "solarized-light"}
    assert [t["id"] for t in st["themes"]] == ["firebox", "solarized-light"]
    assert st["wallpaper"]["key"] == "w:a" and st["count"] == 1 and not st["pinned"]
    assert st["hooks"]["count"] == 1 and st["last_sync"]["theme"] == "firebox"
    assert len(st["active"]["colors"]) == 8


# --- templates, fingerprints, config ------------------------------------------------

@pytest.fixture
def cfg(dirs, monkeypatch):
    """Config dir with a template hook that also logs MOOD_OUTPUT_CHANGED."""
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(dirs / "config"))
    (dirs / "config" / "templates").mkdir(parents=True)
    (dirs / "config" / "templates" / "t.css").write_text("bg: #{{role-bg-hex}}; {{scheme-slug}}\n")
    log = dirs / "cfg.log"
    out = dirs / "out" / "t.css"

    def write(extra: str = ""):
        sync.hooks_path().write_text(
            '[[hook]]\nname = "css"\ntemplate = "templates/t.css"\n'
            f'output = "{out}"\n'
            f'run = "echo \\"$MOOD_THEME $MOOD_OUTPUT_CHANGED\\" >> {log}"\n' + extra)

    write.log = lambda: log.read_text().splitlines() if log.exists() else []
    write.out = out
    write()
    return write


def test_template_hook_renders_then_runs(dirs, mac, cfg):
    rep = sync.sync(today=DAY)
    assert cfg.out.read_text() == "bg: #111111; firebox\n"
    assert cfg.log() == ["firebox 1"]
    assert rep["hooks"][0]["output_changed"] and rep["hooks"][0]["output_file"] == str(cfg.out)
    assert sync.sync(today=DAY)["hooks"] is None
    assert sync.sync(today=DAY, force_hooks=True)["hooks"][0]["output_changed"] is False
    assert cfg.log() == ["firebox 1", "firebox 0"]


def test_edited_scheme_reruns_hooks_but_keeps_wallpaper(dirs, mac, cfg):
    save("w:a")
    sync.sync(today=DAY)
    scheme = dirs / "themes" / "schemes" / "firebox.json"
    data = json.loads(scheme.read_text())
    data["palette"]["base00"] = "#000000"
    scheme.write_text(json.dumps(data))
    rep = sync.sync(today=DAY)
    assert rep["edited"] and not rep["changed"] and not rep["wallpaper_set"]
    assert cfg.out.read_text() == "bg: #000000; firebox\n"
    assert mac["wallpapers"] == ["w-a.png"]


def test_only_the_edited_or_new_hook_runs(dirs, mac, cfg):
    other = dirs / "other.log"
    cfg(f'\n[[hook]]\nname = "other"\nrun = "echo x >> {other}"\n')
    sync.sync(today=DAY)
    assert len(cfg.log()) == 1 and other.read_text() == "x\n"
    (dirs / "config" / "templates" / "t.css").write_text("fg: #{{role-fg-hex}}\n")
    rep = sync.sync(today=DAY)
    assert [h["name"] for h in rep["hooks"]] == ["css"] and cfg.out.read_text() == "fg: #ebdbb2\n"
    cfg(f'\n[[hook]]\nname = "other"\nrun = "echo x >> {other}"\n'
        '\n[[hook]]\nname = "new"\nrun = "true"\n')
    assert [h["name"] for h in sync.sync(today=DAY)["hooks"]] == ["new"]
    assert other.read_text() == "x\n"
    # Results of earlier runs stay listed, in config order.
    assert [h["name"] for h in sync.read_state()["hooks"]] == ["css", "other", "new"]


def test_enabling_a_hook_runs_it(dirs, mac, cfg):
    cfg('\n[[hook]]\nname = "later"\nrun = "true"\nenabled = false\n')
    assert [h["name"] for h in sync.sync(today=DAY)["hooks"]] == ["css"]
    cfg('\n[[hook]]\nname = "later"\nrun = "true"\n')
    assert [h["name"] for h in sync.sync(today=DAY)["hooks"]] == ["later"]


def test_template_error_skips_the_command_and_keeps_the_old_output(dirs, mac, cfg):
    sync.sync(today=DAY)
    (dirs / "config" / "templates" / "t.css").write_text("{{nope}}\n")
    rep = sync.sync(today=DAY)
    h = rep["hooks"][0]
    assert not h["ok"] and "unknown variable(s): nope" in h["output"]
    assert cfg.out.read_text() == "bg: #111111; firebox\n" and cfg.log() == ["firebox 1"]


@pytest.mark.parametrize("body, msg", [
    ('[[hook]]\nname = "a"\nrun = "true"\n[[hook]]\nname = "a"\nrun = "true"\n', "two hooks"),
    ('[[hook]]\ntemplate = "x"\n', "go together"),
    ('[[hook]]\nrun = "true"\ncolour = 1\n', "unknown key"),
    ('[[hook]]\nname = "a"\n', "needs `run`"),
    ('[[hook]]\nrun = "true"\ntimeout = true\n', "invalid timeout"),
])
def test_config_errors(dirs, mac, cfg, body, msg):
    sync.hooks_path().write_text(body)
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks()


def test_config_error_keeps_fingerprints(dirs, mac, cfg):
    sync.sync(today=DAY)
    good = sync.hooks_path().read_text()
    sync.hooks_path().write_text("[[hook]\n")
    assert sync.sync(today=DAY)["error"].startswith("hooks:")
    sync.hooks_path().write_text(good)
    assert sync.sync(today=DAY)["hooks"] is None and cfg.log() == ["firebox 1"]


def test_stowed_config_symlinks_work_and_are_watched(dirs, mac, monkeypatch):
    repo = dirs / "dotfiles" / "mood-engine" / ".config" / "mood-engine"
    (repo / "templates").mkdir(parents=True)
    (repo / "templates" / "t.txt").write_text("{{scheme-name}}\n")
    out = dirs / "out.txt"
    (repo / "hooks.toml").write_text(f'[[hook]]\ntemplate = "templates/t.txt"\noutput = "{out}"\n')
    home = dirs / "home-config" / "mood-engine"
    (home / "templates").mkdir(parents=True)  # stow --no-folding: real dirs, linked files
    (home / "hooks.toml").symlink_to(repo / "hooks.toml")
    (home / "templates" / "t.txt").symlink_to(repo / "templates" / "t.txt")
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(home))
    assert sync.sync()["hooks"][0]["name"] == "t.txt"
    assert out.read_text() == "FireBox\n"
    watched = sync.watch_dirs()
    assert str(repo.resolve()) in watched and str((repo / "templates").resolve()) in watched
    assert str(home) in watched


def test_symlinked_output_keeps_its_link(dirs, mac, cfg):
    target = dirs / "real" / "t.css"
    target.parent.mkdir()
    target.write_text("old")
    cfg.out.parent.mkdir()
    cfg.out.symlink_to(target)
    sync.sync()
    assert cfg.out.is_symlink() and target.read_text() == "bg: #111111; firebox\n"


def test_hooks_run_by_name(dirs, mac, cfg, capsys):
    cfg('\n[[hook]]\nname = "b"\nrun = "true"\n')
    sync.sync(today=DAY)
    assert cli.main(["hooks", "--run", "b"]) == 0
    assert "hook: b: ok" in capsys.readouterr().out and len(cfg.log()) == 1
    assert cli.main(["hooks", "--run", "zzz"]) == 2


def test_render_cli(dirs, mac, cfg, capsys, tmp_path):
    tpl = dirs / "config" / "templates" / "t.css"
    assert cli.main(["render", str(tpl), "solarized-light"]) == 0
    assert capsys.readouterr().out == "bg: #fdf6e3; solarized-light\n"
    assert cli.main(["render", "--vars"]) == 0
    assert "role-accent-hex" in capsys.readouterr().out
    assert cli.main(["render", str(tpl), "-o", str(tmp_path / "x.css")]) == 0
    assert (tmp_path / "x.css").read_text().startswith("bg: #111111")


def test_init_writes_example_config_and_builtin_css_renders(dirs, mac, monkeypatch, capsys):
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(dirs / "fresh"))
    assert cli.main(["hooks", "--init"]) == 0
    assert (dirs / "fresh" / "hooks.toml").exists() and not (dirs / "fresh" / "templates").exists()
    assert cli.main(["render", "builtin:colors.css"]) == 0
    out = capsys.readouterr().out
    assert "--theme-bg: #111111;" in out and "rgba(0, 0, 0, 0.5)" in out and "{{" not in out


# --- hooks run at the same time ------------------------------------------------------

def test_hooks_run_at_the_same_time_in_config_order(dirs, mac, hooks):
    hooks(*[f'\n[[hook]]\nname = "slow{i}"\nrun = "sleep 0.4"\n' for i in range(3)])
    t0 = time.monotonic()
    rep = sync.sync()
    assert time.monotonic() - t0 < 1.0                         # not 1.2 s one after another
    assert [h["name"] for h in rep["hooks"]] == ["log", "slow0", "slow1", "slow2"]
    assert all(h["ok"] for h in rep["hooks"])


def test_after_waits_for_the_named_hooks(dirs, mac, hooks):
    done = dirs / "a-done"
    hooks(f'\n[[hook]]\nname = "a"\nrun = "sleep 0.3 && touch {done}"\n'
          f'\n[[hook]]\nname = "b"\nafter = "a"\nrun = "test -f {done}"\n'
          f'\n[[hook]]\nname = "c"\nafter = ["log", "b"]\nrun = "test -f {done}"\n')
    rep = sync.sync()
    assert [h["ok"] for h in rep["hooks"]] == [True, True, True, True]
    assert sync.load_hooks()[3].after == ["log", "b"]


@pytest.mark.parametrize("body, msg", [
    ('[[hook]]\nname = "a"\nrun = "true"\nafter = "b"\n'
     '[[hook]]\nname = "b"\nrun = "true"\n', "not a hook above it"),
    ('[[hook]]\nname = "a"\nrun = "true"\nafter = "a"\n', "not a hook above it"),
    ('[[hook]]\nname = "a"\nrun = "true"\nafter = 3\n', "hook name or a list"),
])
def test_after_validation(tmp_path, body, msg):
    p = tmp_path / "hooks.toml"
    p.write_text(body)
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks(p)


def test_after_is_not_part_of_the_fingerprint():
    a, b = sync.Hook(name="x", run="true"), sync.Hook(name="x", run="true", after=["y"])
    assert sync.hook_fingerprint(a, "fp") == sync.hook_fingerprint(b, "fp")


def test_wallpaper_is_set_while_the_hooks_run(dirs, mac, hooks, monkeypatch):
    from mood_engine import desktop
    log = dirs / "wp.log"
    hooks(f'\n[[hook]]\nname = "wp"\nrun = "sleep 0.4; echo $MOOD_WALLPAPER > {log}"\n')
    monkeypatch.setattr(desktop, "set_wallpaper",
                        lambda p: (time.sleep(0.4), mac["wallpapers"].append(p.name)))
    save("w:a")
    t0 = time.monotonic()
    rep = sync.sync()
    assert time.monotonic() - t0 < 0.7                       # not 0.8 s one after the other
    assert rep["wallpaper_set"] and mac["wallpapers"] == ["w-a.png"]
    assert log.read_text().strip().endswith("w-a.png")       # hooks still get the path


def test_wallpaper_failure_is_reported_and_hooks_still_run(dirs, mac, hooks, monkeypatch):
    from mood_engine import desktop

    def fail(p):
        raise desktop.DesktopError("osascript failed")
    monkeypatch.setattr(desktop, "set_wallpaper", fail)
    hooks()
    save("w:a")
    rep = sync.sync()
    assert rep["error"] == "wallpaper: osascript failed" and not rep["wallpaper_set"]
    assert [h["ok"] for h in rep["hooks"]] == [True] and hooks.lines() == ["firebox  dark"]
    assert sync.read_state()["error"] == "wallpaper: osascript failed"
