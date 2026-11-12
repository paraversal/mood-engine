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
stowed from a dotfiles repo). See HOOKS_TEMPLATE for the format.
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
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import desktop, library, template, terminal, themes

IN_HOOK_ENV = "MOOD_ENGINE_IN_HOOK"
DEFAULT_TIMEOUT = 30
OUTPUT_TAIL = 2000

HOOKS_TEMPLATE = """\
# mood-engine hooks: keep other apps in line with the active theme.
#
# A hook can render a template into an app's theme file, run a command, or both
# (render first, then run). Hooks run in order, when what they depend on changes:
# a different active theme (`mood-engine use`, macOS switching dark/light, another
# app writing current.json), an edited scheme, or an edit to the hook or its
# template. `mood-engine hooks --run [NAME]` runs them now.
#
# Keys:
#   name      shown in the menu and in `mood-engine hooks`; must be unique
#   template  template file, relative to this file's folder (e.g. templates/x.css).
#             Uses the tinted-theming variables ({{base08-hex}}, {{scheme-name}}, …)
#             plus the theme's roles ({{role-bg-hex}}, {{role-accent-rgb-r}}, …).
#             `mood-engine render TEMPLATE` previews it; `--vars` lists variables.
#   output    where the rendered file goes (~ allowed; relative = this folder).
#             Written atomically, and only when its content changes.
#   run       shell command (/bin/sh -c), run after the output is written
#   timeout   seconds, default 30; the command and everything it started is killed
#   enabled   default true
#
# Commands get these variables:
#   MOOD_THEME, MOOD_THEME_NAME, MOOD_VARIANT (dark|light), MOOD_PREVIOUS_THEME,
#   MOOD_APPEARANCE (macOS: dark|light), MOOD_WALLPAPER (path or empty),
#   MOOD_OUTPUT (the rendered file), MOOD_OUTPUT_CHANGED (1 or 0),
#   MOOD_ENGINE (this mood-engine executable), THEMES_DIR, THEMES_STATE_DIR
#
# Don't call `mood-engine use` or `mood-engine sync` from a hook.
#
# Examples (remove the leading # to enable):
#
# [[hook]]
# name = "CSS variables"
# template = "templates/colors.css"
# output = "~/.cache/mood-engine/colors.css"
#
# Ghostty: set `theme = mood-engine` in its config. The template writes the theme
# file; `fade` glides the open terminals from the previous theme to this one and
# makes Ghostty reload its config.
# [[hook]]
# name = "Ghostty"
# template = "templates/ghostty"
# output = "~/.config/ghostty/themes/mood-engine"
# run = '"$MOOD_ENGINE" fade'
# timeout = 10
#
# Übersicht: reload one widget (keeps its DOM, so CSS transitions can glide). Its id is
# the widget's path with / and . turned into -. Avoid the global `refresh`: it
# reloads the whole page, loses widget state and can leave the webview blank.
# [[hook]]
# name = "fs-health widget"
# run = "osascript -e 'tell application id \\"tracesOf.Uebersicht\\" to reload widget id \\"fs-health-widget-index-jsx\\"'"
# timeout = 10
"""

EXAMPLE_TEMPLATE = """\
/* {{scheme-name}} ({{scheme-variant}}), rendered by mood-engine from templates/colors.css */
:root {
  color-scheme: {{scheme-variant}};
  --theme-bg: #{{role-bg-hex}};
  --theme-surface: #{{role-surface-hex}};
  --theme-fg: #{{role-fg-hex}};
  --theme-fg-muted: #{{role-fg-muted-hex}};
  --theme-accent: #{{role-accent-hex}};
  --theme-error: #{{role-error-hex}};
{{#scheme-is-dark-variant}}
  --shadow: rgba(0, 0, 0, 0.5);
{{/scheme-is-dark-variant}}
{{^scheme-is-dark-variant}}
  --shadow: rgba({{base03-rgb-r}}, {{base03-rgb-g}}, {{base03-rgb-b}}, 0.25);
{{/scheme-is-dark-variant}}
}
"""


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


def config_dir() -> Path:
    if d := os.environ.get("MOOD_ENGINE_CONFIG_DIR"):
        return Path(d)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mood-engine"


def hooks_path() -> Path:
    return config_dir() / "hooks.toml"


def sync_path() -> Path:
    return library.state_dir() / "sync.json"


EXAMPLE_TEMPLATES = {"colors.css": EXAMPLE_TEMPLATE, "ghostty": terminal.GHOSTTY_TEMPLATE}


def init_hooks() -> tuple[Path, bool, list[Path]]:
    """Write the commented hooks.toml and the example templates, each only if it doesn't
    exist (or is a dangling symlink, which is left alone). Returns (hooks.toml, whether
    it was written, the templates written)."""
    p = hooks_path()
    created = not p.exists() and not p.is_symlink()
    if created:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HOOKS_TEMPLATE)
    written = []
    for name, text in EXAMPLE_TEMPLATES.items():
        t = p.parent / "templates" / name
        if not t.exists() and not t.is_symlink():
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(text)
            written.append(t)
    return p, created, written


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
        unknown = set(h) - {"name", "run", "template", "output", "timeout", "enabled"}
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
        name = str(h.get("name") or (run.split()[0] if run else Path(tpl).name))
        if name in seen:
            raise HookConfigError(f"{path}: two hooks are named {name!r}")
        seen.add(name)
        hooks.append(Hook(name=name, run=run,
                          template=_config_path(tpl, path.parent) if tpl else None,
                          output=_config_path(out, path.parent) if out else None,
                          timeout=float(timeout), enabled=h.get("enabled", True) is not False))
    return hooks


def watch_dirs() -> list[str]:
    """Directories whose changes can change what the hooks do: the config folder and
    the real folders of hooks.toml and each template (stow symlinks point into the
    dotfiles repo, and file watchers report changes at the real path)."""
    dirs = {config_dir()}
    files = [hooks_path()]
    with contextlib.suppress(HookConfigError):
        files += [h.template for h in load_hooks() if h.template]
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
    spec = {k: v for k, v in asdict(h).items() if k not in ("timeout", "enabled")}
    return _sha(theme_fp, spec, tpl)


def _write_if_changed(path: Path, text: str) -> bool:
    """Atomic write; a symlinked output keeps its link and its target is written."""
    if path.is_symlink():
        path = path.resolve()
    try:
        if path.read_text() == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    library._atomic_write(path, text.encode())
    return True


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


def run_hook(h: Hook, theme: themes.Theme | None, env: dict[str, str]) -> dict:
    """Render the hook's template (if any), then run its command (if any)."""
    t0 = time.monotonic()
    code: int | None = 0
    output = ""
    changed = False
    if h.template and h.output:
        if theme is None:
            code, output = None, "no theme to render"
        else:
            try:
                text = template.render(h.template.read_text(), template.context(theme))
                changed = _write_if_changed(h.output, text)
            except (OSError, UnicodeDecodeError, template.TemplateError) as e:
                code, output = None, f"template {h.template}: {e}"
    if code == 0 and h.run:
        hook_env = {**os.environ, **env, IN_HOOK_ENV: "1",
                    "MOOD_OUTPUT": str(h.output or ""), "MOOD_OUTPUT_CHANGED": "1" if changed else "0"}
        code, output = _run_command(h.run, hook_env, h.timeout)
    return {"name": h.name, "ok": code == 0, "code": code,
            "seconds": round(time.monotonic() - t0, 2), "output": output.strip()[-OUTPUT_TAIL:],
            "output_file": str(h.output) if h.output else None, "output_changed": changed,
            "at": _now()}


def run_hooks(hooks: list[Hook], env: dict[str, str], theme: themes.Theme | None = None) -> list[dict]:
    """Run enabled hooks one after another; a failing hook doesn't stop the rest."""
    return [run_hook(h, theme, env) for h in hooks if h.enabled]


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
         force_hooks: bool | Iterable[str] = False, today: date | None = None) -> dict:
    """Apply what changed since the last sync. `force_hooks` is True (all hooks) or
    hook names to run regardless of their fingerprint. Returns a report (also the
    CLI's JSON):

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
        wallpaper = prev.get("wallpaper") if not changed else None
        if changed or force_wallpaper or prev.get("day") != today_s:
            try:
                wallpaper = desktop.apply(theme.id)["path"]
                report["wallpaper_set"] = True
            except library.LibraryError as e:
                wallpaper, report["note"] = None, str(e)
            except desktop.DesktopError as e:
                report["error"] = f"wallpaper: {e}"
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
        ran = run_hooks(due, env, theme) if due else []
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
