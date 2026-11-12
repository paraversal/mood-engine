"""Ghostty theming: the template, finding terminals, and the OSC fade (on a real pty; no
real process is ever signalled)."""

import os
import re
import select
import signal
import threading
import time

import pytest

from mood_engine import cli, presets, sync, template, terminal

from .test_library import dirs, mac  # noqa: F401  (fixtures)

OSC = re.compile(rb"\x1b\](\d+(?:;\d+)?);(rgb:[0-9a-f/]+|)\x1b\\")


@pytest.fixture
def pty():
    """A pseudo-terminal: fade writes to the tty path; a thread drains it as a terminal
    app would (a pty's buffer is small), and read() returns what arrived so far."""
    master, slave = os.openpty()
    path = os.ttyname(slave)
    buf, stop = bytearray(), threading.Event()

    def drain():
        while not stop.is_set():
            if select.select([master], [], [], 0.01)[0]:
                try:
                    buf.extend(os.read(master, 65536))
                except OSError:
                    return
    t = threading.Thread(target=drain, daemon=True)
    t.start()

    def read() -> bytes:
        time.sleep(0.05)  # let the drain catch up
        return bytes(buf)
    yield path, read
    stop.set()
    t.join()
    os.close(slave)
    os.close(master)


def sequences(data: bytes) -> list[tuple[str, str]]:
    return [(k.decode(), v.decode()) for k, v in OSC.findall(data)]


def test_template_renders_the_same_colours_the_fade_uses(firebox, solarized_light):
    for t in (firebox, solarized_light):
        text = template.render(presets.builtin_path("ghostty").read_text(), template.context(t))
        conf = dict(l.split(" = ", 1) for l in text.splitlines() if l and not l.startswith("#")
                    and not l.startswith("palette"))
        pal = dict(l.split(" = ", 1)[1].split("=") for l in text.splitlines() if l.startswith("palette"))
        cols = terminal.colours(t)
        assert {f"4;{i}": v for i, v in pal.items()} == {k: v for k, v in cols.items() if k.startswith("4;")}
        assert (conf["foreground"], conf["background"], conf["cursor-color"]) == (cols["10"], cols["11"], cols["12"])
    assert terminal.colours(firebox)["4;0"] == "#272524" and terminal.colours(firebox)["11"] == "#111111"


def test_osc_set_and_steps(firebox, solarized_light):
    a, b = terminal.colours(firebox), terminal.colours(solarized_light)
    assert terminal.osc_set({"11": "#11AA22"}) == b"\x1b]11;rgb:11/aa/22\x1b\\"
    frames = terminal.steps(a, b, 10)
    assert len(frames) == 10 and frames[-1] == b and set(frames[0]) == set(b)
    lightness = [int(f["11"][1:3], 16) for f in frames]
    assert lightness == sorted(lightness) and lightness[0] > 0x11  # dark bg brightens steadily
    assert terminal.steps(a, b, 1) == [b]


def test_app_ttys_walks_through_root_login(firebox):
    me, P = os.getuid(), terminal.Proc
    procs = [P(10, 1, me, "??", "/Applications/Ghostty.app/Contents/MacOS/ghostty"),
             P(11, 10, 0, "ttys001", "/usr/bin/login"),          # login runs as root
             P(12, 11, me, "ttys001", "-zsh"),
             P(13, 12, me, "ttys001", "nvim"),
             P(14, 10, 0, "ttys004", "/usr/bin/login"),
             P(20, 1, 0, "??", "/Applications/Ghostty.app/Contents/MacOS/ghostty"),  # someone else's
             P(21, 20, 0, "ttys009", "/usr/bin/login"),
             P(30, 1, me, "ttys002", "/bin/zsh")]                 # not under Ghostty
    assert terminal.app_pids("ghostty", procs) == [10]
    assert terminal.app_ttys("ghostty", procs) == ["/dev/ttys001", "/dev/ttys004"]
    assert terminal.app_ttys("kitty", procs) == []


def test_fade_pins_reloads_glides_then_unpins(firebox, solarized_light, pty):
    path, read = pty
    events = []
    res = terminal.fade(firebox, solarized_light, ms=100, fps=50, ttys=[path], pids=[4242],
                        kill=lambda pid, sig: events.append(("kill", pid, sig, len(read()))))
    data = read()
    assert res.faded and res.reloaded == [4242] and res.errors == []
    assert events[0][:3] == ("kill", 4242, signal.SIGUSR2)
    assert events[0][3] > 0  # the old colours were pinned before the reload
    seqs = sequences(data)
    old, new = terminal.colours(firebox), terminal.colours(solarized_light)
    spec = lambda hx: f"rgb:{hx[1:3]}/{hx[3:5]}/{hx[5:7]}"  # noqa: E731
    assert seqs[:len(old)] == [(k, spec(v)) for k, v in old.items()]   # pinned old colours first
    assert dict(seqs) == {k: spec(v) for k, v in new.items()}          # glided all the way
    assert data.endswith(terminal.OSC_RESET)                           # pins dropped last
    bgs = [v for k, v in seqs if k == "11"]
    assert len(bgs) == 1 + 5                                           # pin + 100 ms × 50 fps


def test_fade_without_previous_theme_only_reloads(solarized_light, pty):
    path, read = pty
    killed = []
    res = terminal.fade(None, solarized_light, ttys=[path], pids=[1, 2],
                        kill=lambda pid, sig: killed.append(pid))
    assert killed == [1, 2] and not res.faded and read() == b""


def test_fade_without_reload_leaves_new_colours_pinned(firebox, solarized_light, pty):
    path, read = pty
    res = terminal.fade(firebox, solarized_light, app="kitty", reload=False, ms=40, ttys=[path],
                        kill=lambda *a: pytest.fail("no reload expected"))
    data = read()
    assert res.faded and b"]104" not in data and data.endswith(
        terminal.osc_set(terminal.colours(solarized_light)))
    with pytest.raises(ValueError):
        terminal.fade(firebox, solarized_light, app="kitty", ttys=[path], pids=[])


def test_fade_skips_ttys_it_cannot_open(firebox, solarized_light):
    res = terminal.fade(firebox, solarized_light, ms=20, ttys=["/dev/does-not-exist"], pids=[],
                        kill=lambda *a: None)
    assert res.errors and "does-not-exist" in res.errors[0]


# --- CLI and hooks ----------------------------------------------------------------

@pytest.fixture
def fake_fade(monkeypatch):
    calls = []

    def fade(src, dst, **kw):
        calls.append((src.id if src else None, dst.id, kw))
        return terminal.FadeResult(ttys=["/dev/ttys001"], reloaded=[1], faded=src is not None,
                                   seconds=0.4, errors=[])
    monkeypatch.setattr(terminal, "fade", fade)
    monkeypatch.setattr(terminal, "processes", lambda: [])
    return calls


def test_fade_cli_uses_hook_environment(dirs, mac, fake_fade, monkeypatch, capsys):
    monkeypatch.setenv("MOOD_THEME", "solarized-light")
    monkeypatch.setenv("MOOD_PREVIOUS_THEME", "firebox")
    assert cli.main(["fade"]) == 0
    assert fake_fade[-1][:2] == ("firebox", "solarized-light")
    assert "faded 1 terminal(s) firebox → solarized-light" in capsys.readouterr().out
    monkeypatch.setenv("MOOD_PREVIOUS_THEME", "")
    assert cli.main(["fade", "--ms", "10"]) == 0
    assert fake_fade[-1][0] is None and fake_fade[-1][2]["ms"] == 10
    assert cli.main(["fade", "firebox", "--from", "solarized-light"]) == 0
    assert fake_fade[-1][:2] == ("solarized-light", "firebox")
    assert cli.main(["fade", "--from", "nope"]) == 0 and fake_fade[-1][0] is None
    assert cli.main(["fade", "--app", "kitty"]) == 2
    assert cli.main(["fade", "--app", "kitty", "--no-reload"]) == 0
    assert cli.main(["fade", "--dry-run"]) == 0
    assert "would" in capsys.readouterr().out


def test_hook_gets_mood_engine_and_previous_theme(dirs, mac, monkeypatch):
    monkeypatch.setenv("MOOD_ENGINE_CONFIG_DIR", str(dirs / "config"))
    (dirs / "config").mkdir()
    log = dirs / "env.log"
    sync.hooks_path().write_text(
        f'[[hook]]\nname = "env"\nrun = \'echo "$MOOD_ENGINE|$MOOD_PREVIOUS_THEME" >> {log}\'\n')
    sync.sync()
    mac["appearance"] = "light"
    sync.sync()
    first, second = log.read_text().splitlines()
    engine = first.split("|")[0]
    assert engine.endswith("mood-engine") and second == f"{engine}|firebox"



# --- the `terminal` hook key (the Ghostty preset) -----------------------------------

def test_terminal_hook_glides_in_process(dirs, mac, monkeypatch):
    calls = []

    def fake_fade(src, dst, **kw):
        calls.append((src.id if src else None, dst.id, kw))
        return terminal.FadeResult(ttys=["/dev/ttys001"], reloaded=[1], faded=src is not None,
                                   seconds=0.4, errors=["/dev/ttys009: could not write"])
    monkeypatch.setattr(terminal, "fade", fake_fade)
    monkeypatch.setattr(sync, "_sleep", lambda s: pytest.fail("no file frames with `terminal`"))
    (dirs / "config").mkdir()
    out = dirs / "ghostty-theme"
    sync.hooks_path().write_text(f'[[hook]]\npreset = "ghostty"\noutput = "{out}"\n')
    sync.sync()
    mac["appearance"] = "light"
    rep = sync.sync()
    assert [c[:2] for c in calls] == [(None, "firebox"), ("firebox", "solarized-light")]
    assert calls[-1][2] == {"app": "ghostty", "ms": 400}
    [h] = rep["hooks"]
    assert h["ok"] and "faded 1 terminal(s) firebox → solarized-light" in h["output"]
    assert "ttys009" in h["output"] and "background = #fdf6e3" in out.read_text()


def test_terminal_hook_failure_is_reported(dirs, mac, monkeypatch):
    def broken(*a, **kw):
        raise OSError("ps failed")
    monkeypatch.setattr(terminal, "fade", broken)
    (dirs / "config").mkdir()
    sync.hooks_path().write_text(f'[[hook]]\npreset = "ghostty"\noutput = "{dirs / "g"}"\n')
    [h] = sync.sync()["hooks"]
    assert not h["ok"] and h["output"] == "ghostty: ps failed"


@pytest.mark.parametrize("body, msg", [
    ('terminal = "kitty"\ntemplate = "t"\noutput = "o"', "must be one of ghostty"),
    ('terminal = "ghostty"\nrun = "true"', "needs `template`"),
])
def test_terminal_validation(tmp_path, body, msg):
    p = tmp_path / "hooks.toml"
    p.write_text(f'[[hook]]\nname = "x"\n{body}\n')
    with pytest.raises(sync.HookConfigError, match=msg):
        sync.load_hooks(p)
