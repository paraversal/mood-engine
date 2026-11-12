"""Theme running terminals: the Ghostty theme template and a smooth fade between themes.

`fade()` glides every terminal of an app (Ghostty by default) from one theme to another
with OSC colour sequences written to the terminals' ttys, the same way a program inside
the terminal could change its colours:

  1. pin the old theme's colours (OSC 4 palette 0-15, OSC 10/11/12 fg/bg/cursor),
  2. ask the app to reload its config (Ghostty: SIGUSR2), which now names the new theme;
     the pinned colours stay on screen, so the reload itself shows nothing,
  3. step the pinned colours to the new theme's, eased, interpolated in OKLab,
  4. drop the pins (OSC 104/110/111/112), which leaves the reloaded config's colours.

The in-between colours come from `colours()`; where the app's theme file (rendered from
GHOSTTY_TEMPLATE, or the user's own template) differs, step 4 snaps to the file's colours.

Only colour *set* sequences are written. A query's reply would arrive as input to
whatever runs in the terminal, e.g. the shell.

Caveats: programs that set terminal colours themselves (OSC 4/10/11/12) lose those in
step 4, and a sequence could land inside another program's half-written escape
sequence on the same tty, which at worst garbles that one sequence.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np

from .color import hex_to_oklab, oklab_to_hex
from .themes import Theme

# Base24 slots for ANSI colours 0-15. Black is base01 rather than the background, so
# "black" cells stay visible on dark themes; the bright row uses base24's bright slots.
ANSI_SLOTS = ("base01", "base08", "base0B", "base0A", "base0D", "base0E", "base0C", "base05",
              "base03", "base12", "base14", "base13", "base16", "base17", "base15", "base07")

# Kept in step with ANSI_SLOTS and colours(); the tests check that it renders the same.
GHOSTTY_TEMPLATE = """\
# {{scheme-name}} ({{scheme-variant}}), rendered by mood-engine.
# Ghostty: theme = mood-engine (this file is ~/.config/ghostty/themes/mood-engine)
palette = 0=#{{base01-hex}}
palette = 1=#{{base08-hex}}
palette = 2=#{{base0B-hex}}
palette = 3=#{{base0A-hex}}
palette = 4=#{{base0D-hex}}
palette = 5=#{{base0E-hex}}
palette = 6=#{{base0C-hex}}
palette = 7=#{{base05-hex}}
palette = 8=#{{base03-hex}}
palette = 9=#{{base12-hex}}
palette = 10=#{{base14-hex}}
palette = 11=#{{base13-hex}}
palette = 12=#{{base16-hex}}
palette = 13=#{{base17-hex}}
palette = 14=#{{base15-hex}}
palette = 15=#{{base07-hex}}
background = #{{role-bg-hex}}
foreground = #{{role-fg-hex}}
cursor-color = #{{role-accent-hex}}
cursor-text = #{{role-on-accent-hex}}
selection-background = #{{role-selection-hex}}
selection-foreground = #{{role-fg-hex}}
"""

# How to make an app re-read its config. Ghostty reloads on SIGUSR2 (macOS and Linux).
RELOAD_SIGNALS = {"ghostty": signal.SIGUSR2}

OSC_RESET = b"\x1b]104\x1b\\\x1b]110\x1b\\\x1b]111\x1b\\\x1b]112\x1b\\"
# Ghostty applies a reload on its main thread, a moment after the signal; the pins are
# never dropped sooner than this after it.
MIN_RELOAD_WAIT = 0.25


def colours(theme: Theme) -> dict[str, str]:
    """OSC target -> '#rrggbb': '4;0'…'4;15' (palette), '10' fg, '11' bg, '12' cursor."""
    out = {f"4;{i}": theme.palette[slot] for i, slot in enumerate(ANSI_SLOTS)}
    out |= {"10": theme.roles["fg"], "11": theme.roles["bg"], "12": theme.roles["accent"]}
    return out


def osc_set(cols: dict[str, str]) -> bytes:
    def spec(hx: str) -> str:
        h = hx.lstrip("#").lower()
        return f"rgb:{h[0:2]}/{h[2:4]}/{h[4:6]}"
    return "".join(f"\x1b]{k};{spec(v)}\x1b\\" for k, v in cols.items()).encode()


def ease_in_out(x: float) -> float:
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def steps(src: dict[str, str], dst: dict[str, str], n: int) -> list[dict[str, str]]:
    """n colour sets after `src`, eased, ending exactly at `dst`."""
    keys = list(dst)
    a = np.array([hex_to_oklab(src[k]) for k in keys])
    b = np.array([hex_to_oklab(dst[k]) for k in keys])
    out = []
    for i in range(1, n + 1):
        if i == n:
            out.append(dict(dst))
            continue
        lab = a + (b - a) * ease_in_out(i / n)
        out.append({k: oklab_to_hex(lab[j]) for j, k in enumerate(keys)})
    return out


# --- finding the terminals -------------------------------------------------------

@dataclass
class Proc:
    pid: int
    ppid: int
    uid: int
    tty: str
    comm: str


def processes() -> list[Proc]:
    """All processes. The tree runs Ghostty -> login (root) -> shell, so it can't be
    limited to the user's own processes."""
    ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,uid=,tty=,comm="],
                        capture_output=True, text=True, check=True).stdout
    procs = []
    for line in ps.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit():
            procs.append(Proc(int(parts[0]), int(parts[1]), int(parts[2]), parts[3], parts[4]))
    return procs


def app_pids(app: str, procs: Iterable[Proc], uid: int | None = None) -> list[int]:
    """The user's processes whose executable is named `app`."""
    uid = os.getuid() if uid is None else uid
    return sorted(p.pid for p in procs
                  if p.uid == uid and os.path.basename(p.comm).lower() == app.lower())


def app_ttys(app: str, procs: list[Proc], uid: int | None = None) -> list[str]:
    """tty devices of every process started (directly or not) by the user's `app`."""
    children: dict[int, list[Proc]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)
    ttys: set[str] = set()
    stack = app_pids(app, procs, uid)
    seen = set(stack)
    while stack:
        for c in children.get(stack.pop(), []):
            if c.tty not in ("??", "-", "?", ""):
                ttys.add(c.tty if c.tty.startswith("/dev/") else f"/dev/{c.tty}")
            if c.pid not in seen:
                seen.add(c.pid)
                stack.append(c.pid)
    return sorted(ttys)


# --- writing ---------------------------------------------------------------------

def _open(paths: Iterable[str]) -> tuple[dict[str, int], list[str]]:
    fds, errors = {}, []
    for p in paths:
        try:
            fds[p] = os.open(p, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as e:
            errors.append(f"{p}: {e.strerror or e}")
    return fds, errors


def _write(fd: int, data: bytes, *, must: bool = False, tries: int = 25) -> bool | None:
    """Write without blocking on a busy terminal. True: written. False: dropped (a frame
    that didn't fit; a later one replaces it). None: the terminal is gone or unwritable.

    `must` retries briefly, for the sequences that have to arrive. A partly written
    sequence is always finished, so the terminal is never left inside an escape."""
    view = memoryview(data)
    for _ in range(tries):
        try:
            while view:
                view = view[os.write(fd, view):]
            return True
        except BlockingIOError:
            if not must and len(view) == len(data):
                return False
            time.sleep(0.02)
        except OSError:
            return None
    return None


@dataclass
class FadeResult:
    ttys: list[str]
    reloaded: list[int]
    faded: bool
    seconds: float
    errors: list[str]


def fade(src: Theme | None, dst: Theme, *, app: str = "ghostty", ms: int = 400, fps: int = 60,
         reload: bool = True, ttys: list[str] | None = None, pids: list[int] | None = None,
         kill: Callable[[int, int], None] = os.kill,
         sleep: Callable[[float], None] = time.sleep) -> FadeResult:
    """Glide `app`'s terminals from `src` to `dst` (see the module docstring).

    Without `src` (or with identical colours) nothing is faded and only the reload
    happens. Without `reload` the last colours stay pinned, because nothing else would
    show the new theme. `ttys`/`pids` override the process lookup (tests)."""
    t0 = time.monotonic()
    if reload and app.lower() not in RELOAD_SIGNALS:
        raise ValueError(f"don't know how to make {app} reload its config; pass reload=False")
    if ttys is None or (reload and pids is None):
        procs = processes()
        ttys = app_ttys(app, procs) if ttys is None else ttys
        pids = app_pids(app, procs) if pids is None else pids
    a, b = (colours(src) if src else None), colours(dst)
    animate = a is not None and a != b and ms > 0
    fds, errors = _open(ttys) if animate or not reload else ({}, [])

    def broadcast(data: bytes, must: bool = False) -> None:
        for path, fd in list(fds.items()):
            if _write(fd, data, must=must) is None:
                errors.append(f"{path}: could not write")
                os.close(fd)
                del fds[path]

    try:
        if animate:
            broadcast(osc_set(a), must=True)            # 1. pin the old colours
        reloaded: list[int] = []
        t_reload = time.monotonic()
        if reload:                                       # 2. reload under the pins
            for pid in pids or []:
                try:
                    kill(pid, RELOAD_SIGNALS[app.lower()])
                    reloaded.append(pid)
                except ProcessLookupError:
                    pass
                except PermissionError as e:
                    errors.append(f"pid {pid}: {e.strerror}")
        if animate:                                      # 3. glide
            frames = steps(a, b, max(1, round(ms / 1000 * fps)))
            start, dt = time.monotonic(), ms / 1000 / len(frames)
            for i, f in enumerate(frames, 1):
                broadcast(osc_set(f), must=i == len(frames))
                sleep(max(0.0, start + i * dt - time.monotonic()))
        elif not reload:
            broadcast(osc_set(b), must=True)
        if reload and fds:                               # 4. unpin
            sleep(max(0.0, t_reload + MIN_RELOAD_WAIT - time.monotonic()))
            broadcast(OSC_RESET, must=True)
    finally:
        for fd in fds.values():
            os.close(fd)
    return FadeResult(ttys=list(ttys), reloaded=reloaded, faded=animate,
                      seconds=round(time.monotonic() - t0, 2), errors=errors)
