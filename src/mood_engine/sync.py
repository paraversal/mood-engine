"""Bring the desktop in line with the active theme, and run hooks when their inputs change.

`sync()` resolves the active theme (current.json, then defaults.json, for the given
macOS appearance) and compares it with the last sync:

- active theme changed (or first sync): set its wallpaper
- same theme, new day: set the wallpaper again (daily rotation)
- each hook runs when its fingerprint changed: the active theme's colours, the
  hook's own definition and its template file. So a theme switch or an edited
  scheme runs every hook, an edited template runs only its hook, and a hook
  added to hooks.toml runs once on its own.

The menu bar app calls this whenever macOS switches between dark and light,
current.json, defaults.json, a scheme, hooks.toml or a template changes, the Mac
wakes or the day changes; `mood-engine use` calls it after writing current.json.
A lock on $STATE/sync.lock serialises concurrent syncs, so the same change never
runs a hook twice.

State: $STATE/sync.json (STATE as in library.py)

  {"theme": "<id>", "theme_fp": "<sha256>", "appearance": "dark", "day": "YYYY-MM-DD",
   "wallpaper": "<path>" | null, "at": "<ISO time>", "error": "<message>" | null,
   "hook_fps": {"<hook name>": "<sha256>"},             # what each hook last ran for
   "hooks": [{"name", "ok", "code", "seconds", "output", "at",
              "output_file", "output_changed"}],         # latest result per hook
   "hooks_at": "<ISO time>" | null}

Config: $CONFIG/hooks.toml and templates next to it, CONFIG = $MOOD_ENGINE_CONFIG_DIR
or $XDG_CONFIG_HOME/mood-engine or ~/.config/mood-engine. Both may be symlinks (e.g.
stowed from a dotfiles repo). templates/hooks.example.toml documents the format;
presets.py has the built-in templates and pre-configured hooks.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import desktop, library, presets, template, terminal, themes

IN_HOOK_ENV = "MOOD_ENGINE_IN_HOOK"
DEFAULT_TIMEOUT = 30
OUTPUT_TAIL = 2000
# Time between the in-between frames of a hook's `fade`. Zed re-reads a changed theme
# file at most about every 100 ms and merges faster changes.
FADE_STEP = 0.11
TERMINAL_FADE_MS = 400  # a `terminal` hook's fade without `fade`
_sleep = time.sleep  # tests replace it

_libsystem = None


def _notify_post(name: str) -> str | None:
    """Post a Darwin notification (notify(3)) that any process can subscribe to with
    notify_register_dispatch or `notifyutil -w NAME`. None on success, else an error.
    A no-op off macOS."""
    global _libsystem
    if sys.platform != "darwin":
        return None
    try:
        if _libsystem is None:
            import ctypes
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            lib.notify_post.argtypes = [ctypes.c_char_p]
            lib.notify_post.restype = ctypes.c_uint32
            _libsystem = lib
        status = _libsystem.notify_post(name.encode())
    except (OSError, AttributeError) as e:
        return f"notify {name}: {e}"
    return None if status == 0 else f"notify {name}: notify_post returned {status}"


_post = _notify_post  # tests replace it

class HookConfigError(Exception):
    pass


@dataclass
class Hook:
    name: str
    run: str | None = None
    template: Path | None = None
    output: Path | None = None
    timeout: float = DEFAULT_TIMEOUT
    enabled: bool = True
    fade: float | None = None  # ms
    terminal: str | None = None  # an app whose terminals glide via OSC (terminal.fade)
    after: list[str] = field(default_factory=list)  # hooks above this one to wait for
    notify: str | None = None  # Darwin notification posted after each write of `output`


def config_dir() -> Path:
    if d := os.environ.get("MOOD_ENGINE_CONFIG_DIR"):
        return Path(d)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mood-engine"


def hooks_path() -> Path:
    return config_dir() / "hooks.toml"


def sync_path() -> Path:
    return library.state_dir() / "sync.json"


def init_hooks() -> tuple[Path, bool]:
    """Write the commented example hooks.toml if there is none (a dangling symlink is
    left alone). Returns (path, whether it was written). Templates aren't copied: the
    presets use the built-in ones."""
    p = hooks_path()
    if p.exists() or p.is_symlink():
        return p, False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(presets.example_hooks())
    return p, True


def eject_template(name: str) -> tuple[Path, Path, bool]:
    """Copy a built-in template (by preset or file name) into the config's templates/
    folder, for customising. Returns (source, destination, whether it was written);
    an existing file is never overwritten. Raises KeyError for an unknown name."""
    ref = presets.PRESETS[name].keys.get("template") if name in presets.PRESETS else name
    if not ref:
        raise KeyError(f"preset {name!r} has no template")
    src = presets.builtin_path(ref)
    dest = config_dir() / "templates" / src.name
    if dest.exists() or dest.is_symlink():
        return src, dest, False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text())
    return src, dest, True


def engine_command() -> str:
    """This mood-engine, for hooks (the menu bar app's PATH may not have it): the
    `mood-engine` script next to the running interpreter, else the one on PATH."""
    exe = Path(sys.executable).parent / "mood-engine"
    if exe.is_file() and os.access(exe, os.X_OK):
        return str(exe)
    return shutil.which("mood-engine") or "mood-engine"


def _config_path(value: str, base: Path) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else base / p


def _template_path(value: str, base: Path) -> Path:
    if value.startswith(presets.BUILTIN_PREFIX):
        return presets.builtin_path(value)
    return _config_path(value, base)


def load_hooks(path: Path | None = None) -> list[Hook]:
    """Parse hooks.toml. A missing file means no hooks; a broken one raises HookConfigError."""
    path = path or hooks_path()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise HookConfigError(f"{path}: {e}") from e
    raw = data.get("hook", [])
    if not isinstance(raw, list):
        raise HookConfigError(f"{path}: use [[hook]] tables")
    hooks: list[Hook] = []
    seen: set[str] = set()
    for i, h in enumerate(raw, 1):
        if not isinstance(h, dict):
            raise HookConfigError(f"{path}: hook {i} is not a table")
        if "preset" in h:
            pname = h["preset"]
            if not isinstance(pname, str) or pname not in presets.PRESETS:
                raise HookConfigError(f"{path}: hook {i}: unknown preset {pname!r} "
                                      f"(presets: {', '.join(presets.PRESETS)})")
            pre = presets.PRESETS[pname]
            h = {"name": pre.name, **pre.keys, **{k: v for k, v in h.items() if k != "preset"}}
        unknown = set(h) - {"name", "run", "template", "output", "timeout", "enabled", "fade",
                            "terminal", "after", "notify"}
        if unknown:
            raise HookConfigError(f"{path}: hook {i} has unknown key(s) {', '.join(sorted(unknown))}")
        run, tpl, out = h.get("run"), h.get("template"), h.get("output")
        for key, val in (("run", run), ("template", tpl), ("output", out)):
            if val is not None and (not isinstance(val, str) or not val.strip()):
                raise HookConfigError(f"{path}: hook {i}: `{key}` must be a non-empty string")
        if run is None and tpl is None:
            raise HookConfigError(f"{path}: hook {i} needs `run`, `template`, or both")
        if (tpl is None) != (out is None):
            raise HookConfigError(f"{path}: hook {i}: `template` and `output` go together")
        timeout = h.get("timeout", DEFAULT_TIMEOUT)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise HookConfigError(f"{path}: hook {i} has an invalid timeout")
        fade = h.get("fade")
        if fade is not None:
            if isinstance(fade, bool) or not isinstance(fade, (int, float)) or not 0 < fade <= 10000:
                raise HookConfigError(f"{path}: hook {i}: `fade` is milliseconds, 1 to 10000")
            if tpl is None:
                raise HookConfigError(f"{path}: hook {i}: `fade` needs `template` and `output`")
        term = h.get("terminal")
        if term is not None:
            if not isinstance(term, str) or term.lower() not in terminal.RELOAD_SIGNALS:
                raise HookConfigError(f"{path}: hook {i}: `terminal` must be one of "
                                      f"{', '.join(terminal.RELOAD_SIGNALS)}")
            if tpl is None:
                raise HookConfigError(f"{path}: hook {i}: `terminal` needs `template` and `output`")
        notify = h.get("notify")
        if notify is not None:
            if not isinstance(notify, str) or not notify.strip():
                raise HookConfigError(f"{path}: hook {i}: `notify` must be a non-empty string "
                                      f"(a notification name such as local.mood-engine.theme)")
            if tpl is None:
                raise HookConfigError(f"{path}: hook {i}: `notify` needs `template` and `output`")
        after = h.get("after", [])
        if isinstance(after, str):
            after = [after]
        if not isinstance(after, list) or not all(isinstance(a, str) for a in after):
            raise HookConfigError(f"{path}: hook {i}: `after` is a hook name or a list of them")
        name = str(h.get("name") or (run.split()[0] if run else Path(tpl).name))
        if name in seen:
            raise HookConfigError(f"{path}: two hooks are named {name!r}")
        if missing := [a for a in after if a not in seen]:
            raise HookConfigError(f"{path}: hook {name!r}: `after` names "
                                  f"{', '.join(map(repr, missing))}, not a hook above it")
        seen.add(name)
        try:
            template_path = _template_path(tpl, path.parent) if tpl else None
        except KeyError as e:
            raise HookConfigError(f"{path}: hook {i}: {e.args[0]}") from None
        hooks.append(Hook(name=name, run=run,
                          template=template_path,
                          output=_config_path(out, path.parent) if out else None,
                          timeout=float(timeout), enabled=h.get("enabled", True) is not False,
                          fade=float(fade) if fade is not None else None,
                          terminal=term.lower() if term else None, after=after,
                          notify=notify.strip() if notify else None))
    return hooks


def watch_dirs() -> list[str]:
    """Directories whose changes can change what the hooks do: the config folder and
    the real folders of hooks.toml and each template (stow symlinks point into the
    dotfiles repo, and file watchers report changes at the real path)."""
    dirs = {config_dir()}
    files = [hooks_path()]
    with contextlib.suppress(HookConfigError):
        files += [h.template for h in load_hooks()
                  if h.template and h.template.parent != presets.TEMPLATES_DIR]
    for f in files:
        dirs.add(f.parent)
        with contextlib.suppress(OSError):
            dirs.add(f.resolve(strict=True).parent)
    return sorted(str(d) for d in dirs if d.is_dir())


def _sha(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def theme_fingerprint(t: themes.Theme) -> str:
    return _sha(t.id, t.name, t.author, t.variant, t.palette, t.roles)


def hook_fingerprint(h: Hook, theme_fp: str) -> str:
    try:
        tpl = h.template.read_bytes().hex() if h.template else None
    except OSError:
        tpl = "missing"
    # Keys added later count only when set, so upgrading doesn't rerun every hook.
    # `after` only changes when a hook runs, not what it does.
    spec = {k: v for k, v in asdict(h).items()
            if k not in ("timeout", "enabled", "after")
            and not (k in ("fade", "terminal", "notify") and v is None)}
    if h.template and h.template.parent == presets.TEMPLATES_DIR:
        spec["template"] = presets.label(h.template)  # not where mood-engine is installed
    return _sha(theme_fp, spec, tpl)


def _real(path: Path) -> Path:
    """A symlinked output keeps its link; its target is written."""
    return path.resolve() if path.is_symlink() else path


def _read(path: Path) -> str | None:
    try:
        return _real(path).read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _write_if_changed(path: Path, text: str) -> bool:
    """Atomic write, skipped when the file already holds `text`."""
    if _read(path) == text:
        return False
    library._atomic_write(_real(path), text.encode())
    return True


def _fade_frames(h: Hook, source: str, previous: themes.Theme, theme: themes.Theme) -> None:
    """Write the in-between frames of the hook's fade (not the final one) to its output,
    posting the hook's `notify` after each. A frame's failed post is ignored; the final
    post reports it."""
    n = max(1, round(h.fade / 1000 / FADE_STEP))
    path = _real(h.output)
    for i in range(1, n):
        mid = themes.blend(previous, theme, terminal.ease_in_out(i / n))
        library._atomic_write(path, template.render(source, template.context(mid)).encode())
        if h.notify:
            _post(h.notify)
        _sleep(FADE_STEP)


def _run_command(cmd: str, env: dict[str, str], timeout: float) -> tuple[int | None, str]:
    try:
        # Own process group, so a timeout also stops whatever the shell started.
        proc = subprocess.Popen(["/bin/sh", "-c", cmd], env=env, text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        return None, str(e)
    try:
        output, _ = proc.communicate(timeout=timeout)
        return proc.returncode, output
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        rest, _ = proc.communicate()
        return None, f"timed out after {timeout:g} s\n{rest or ''}"


def run_hook(h: Hook, theme: themes.Theme | None, env: dict[str, str],
             previous: themes.Theme | None = None) -> dict:
    """Render the hook's template (if any), glide the `terminal` app into it (if set),
    then run the command (if any). With `fade` and a `previous` theme, the output steps
    through blended themes first, or, with `terminal`, the app's terminals glide."""
    t0 = time.monotonic()
    code: int | None = 0
    output = ""
    changed = False
    if h.template and h.output:
        if theme is None:
            code, output = None, "no theme to render"
        else:
            try:
                source = h.template.read_text()
                text = template.render(source, template.context(theme))
                if (h.fade and not h.terminal and previous is not None
                        and previous.id != theme.id and _read(h.output) != text):
                    _fade_frames(h, source, previous, theme)
                changed = _write_if_changed(h.output, text)
            except (OSError, UnicodeDecodeError, template.TemplateError) as e:
                code, output = None, f"template {h.template}: {e}"
            # Posted even when the file didn't change, so `hooks --run` can nudge a
            # listener that started late.
            if code == 0 and h.notify and (err := _post(h.notify)):
                code, output = None, err
    if code == 0 and h.terminal and theme is not None:
        src = previous if previous is not None and previous.id != theme.id else None
        try:
            res = terminal.fade(src, theme, app=h.terminal,
                                ms=int(h.fade if h.fade is not None else TERMINAL_FADE_MS))
            output = "\n".join([terminal.describe(res, h.terminal, src, theme), *res.errors])
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            code, output = None, f"{h.terminal}: {e}"
    if code == 0 and h.run:
        hook_env = {**os.environ, **env, IN_HOOK_ENV: "1",
                    "MOOD_OUTPUT": str(h.output or ""), "MOOD_OUTPUT_CHANGED": "1" if changed else "0"}
        code, output = _run_command(h.run, hook_env, h.timeout)
    return {"name": h.name, "ok": code == 0, "code": code,
            "seconds": round(time.monotonic() - t0, 2), "output": output.strip()[-OUTPUT_TAIL:],
            "output_file": str(h.output) if h.output else None, "output_changed": changed,
            "at": _now()}


def run_hooks(hooks: list[Hook], env: dict[str, str], theme: themes.Theme | None = None,
              previous: themes.Theme | None = None) -> list[dict]:
    """Run the enabled hooks at the same time, so their fades glide together. A hook
    with `after` starts once those hooks (when they run too) have finished. A failing
    hook doesn't stop the rest. Results come back in config order."""
    hooks = [h for h in hooks if h.enabled]
    if not hooks:
        return []

    def run(h: Hook, deps: list[Future]) -> dict:
        wait(deps)
        return run_hook(h, theme, env, previous)

    futures: dict[str, Future] = {}
    with ThreadPoolExecutor(max_workers=len(hooks), thread_name_prefix="hook") as pool:
        for h in hooks:  # `after` only names hooks above, so their futures exist already
            futures[h.name] = pool.submit(run, h, [futures[a] for a in h.after if a in futures])
        return [futures[h.name].result() for h in hooks]


def read_state() -> dict:
    try:
        data = json.loads(sync_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    d = library.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class _Background(threading.Thread):
    """Runs fn(*args) in the background, after `delay` seconds; join() waits, `error`
    is what it raised."""

    def __init__(self, fn, *args, delay: float = 0.0) -> None:
        super().__init__(daemon=True, name="wallpaper")
        self.fn, self.args, self.delay, self.error = fn, args, delay, None
        self.start()

    def run(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay)
        try:
            self.fn(*self.args)
        except Exception as e:  # noqa: BLE001 - reported in the sync's report
            self.error = e


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active_theme(appearance: themes.Appearance) -> themes.Theme | None:
    """The theme apps set to "System" show for this appearance, or None without an index."""
    try:
        tid = themes.resolve_theme_id("system", appearance)
        return themes.load_theme(tid) if tid else None
    except (OSError, ValueError, KeyError):
        return None


def sync(appearance: themes.Appearance | None = None, *, force_wallpaper: bool = False,
         force_hooks: bool | Iterable[str] = False, today: date | None = None,
         wallpaper_delay: float = 0.0) -> dict:
    """Apply what changed since the last sync. `force_hooks` is True (all hooks) or
    hook names to run regardless of their fingerprint. `wallpaper_delay` holds the
    wallpaper back (hooks still start at once): right after a dark/light flip, setting
    it while macOS is still redrawing for the new appearance can leave the menu bar
    blank until it is clicked. Returns a report (also the CLI's JSON):

    {"theme", "name", "variant", "previous", "appearance", "changed": bool (theme id),
     "edited": bool (same theme, different colours), "wallpaper": path | None,
     "wallpaper_set": bool, "note": str | None, "error": str | None,
     "hooks": [results of hooks that ran] | None (None = none ran)}
    """
    report: dict = {"theme": None, "name": None, "variant": None, "previous": None,
                    "appearance": None, "changed": False, "edited": False, "wallpaper": None,
                    "wallpaper_set": False, "note": None, "error": None, "hooks": None}
    if os.environ.get(IN_HOOK_ENV):
        report["note"] = "skipped: called from a hook"
        return report
    appearance = appearance or themes.system_appearance()
    report["appearance"] = appearance
    theme = active_theme(appearance)
    if theme is None:
        report["error"] = f"no themes in {themes.themes_dir()}"
        return report
    report.update(theme=theme.id, name=theme.name, variant=theme.variant)
    today_s = (today or date.today()).isoformat()
    theme_fp = theme_fingerprint(theme)

    with _locked():
        prev = read_state()
        report["previous"] = prev.get("theme")
        changed = prev.get("theme") != theme.id
        report["changed"] = changed
        report["edited"] = not changed and prev.get("theme_fp") != theme_fp
        # Pick the wallpaper first (hooks get its path), but set it while the hooks run:
        # setting it takes 0.2-0.3 s and would hold up every fade.
        wallpaper = prev.get("wallpaper") if not changed else None
        setter: _Background | None = None
        if changed or force_wallpaper or prev.get("day") != today_s:
            try:
                wallpaper = desktop.apply(theme.id, set_desktop=False)["path"]
                setter = _Background(desktop.set_wallpaper, Path(wallpaper), delay=wallpaper_delay)
            except library.LibraryError as e:
                wallpaper, report["note"] = None, str(e)
        report["wallpaper"] = wallpaper

        try:
            hooks = [h for h in load_hooks() if h.enabled]
        except HookConfigError as e:
            hooks, report["error"] = [], f"hooks: {e}"
        forced = (set(h.name for h in hooks) if force_hooks is True
                  else set(force_hooks or ()))
        old_fps = prev.get("hook_fps") or {}
        fps = {h.name: hook_fingerprint(h, theme_fp) for h in hooks}
        due = [h for h in hooks if h.name in forced or old_fps.get(h.name) != fps[h.name]]
        env = {"MOOD_THEME": theme.id, "MOOD_THEME_NAME": theme.name,
               "MOOD_VARIANT": theme.variant,
               "MOOD_PREVIOUS_THEME": (prev.get("theme") or "") if changed else "",
               "MOOD_APPEARANCE": appearance, "MOOD_WALLPAPER": wallpaper or "",
               "MOOD_ENGINE": engine_command(),
               "THEMES_DIR": str(themes.themes_dir()), "THEMES_STATE_DIR": str(themes.state_dir())}
        previous = None
        if changed and prev.get("theme"):
            with contextlib.suppress(OSError, ValueError, KeyError):
                previous = themes.load_theme(prev["theme"])
        ran = run_hooks(due, env, theme, previous) if due else []
        if setter is not None:
            setter.join()
            if setter.error is None:
                report["wallpaper_set"] = True
            else:
                msg = f"wallpaper: {setter.error}"
                report["error"] = f"{report['error']}; {msg}" if report["error"] else msg
        if ran:
            report["hooks"] = ran
        elif changed or force_hooks:
            report["hooks"] = []

        # Latest result per configured hook, in config order; a hook config error
        # keeps the old fingerprints so nothing reruns spuriously once it is fixed.
        latest = {r["name"]: r for r in prev.get("hooks", []) if isinstance(r, dict)}
        latest.update({r["name"]: r for r in ran})
        if report["error"] and report["error"].startswith("hooks:"):
            hook_fps, results = old_fps, list(latest.values())
        else:
            hook_fps = {n: fp for n, fp in fps.items()}
            results = [latest[h.name] for h in hooks if h.name in latest]
        state = {"theme": theme.id, "theme_fp": theme_fp, "appearance": appearance,
                 "day": today_s, "wallpaper": wallpaper, "at": _now(), "error": report["error"],
                 "hook_fps": hook_fps, "hooks": results,
                 "hooks_at": _now() if ran else prev.get("hooks_at")}
        library._atomic_write(sync_path(), (json.dumps(state, indent=1) + "\n").encode())
    return report
