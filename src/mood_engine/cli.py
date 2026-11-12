"""mood-engine CLI: `search` (terminal / JSON / static HTML), `serve` (gallery), `apply`, `use`,
`sync`, `hooks`, `render`, `pin`/`unpin`, `library`, `status`, `themes`.

`mood-engine [THEME] [options]` with no subcommand is short for `mood-engine serve`."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from . import desktop, gallery, library, pipeline, selection, themes
from . import sync as syncmod
from . import template as tplmod
from .sources import ALL_SOURCES
from .themes import choose_theme, list_themes, load_theme, themes_dir


def _swatch(hx: str) -> str:
    r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m"


def _opts(a) -> pipeline.Options:
    mw, mh = pipeline.parse_res(a.min_res)
    return pipeline.Options(query=a.query, sources=tuple(a.sources.split(",")), min_w=mw, min_h=mh,
                            n_colors=a.colors, pages=a.pages, k=a.k, limit=a.limit)


def cmd_search(a) -> int:
    theme = choose_theme(a.theme)
    run = pipeline.run(theme, _opts(a))
    for w in dict.fromkeys(run.warnings):
        print(f"warning: {w}", file=sys.stderr)
    if a.json:
        from .server import to_json
        print(json.dumps(to_json(run), indent=1))
        return 0
    if a.html:
        Path(a.html).parent.mkdir(parents=True, exist_ok=True)
        Path(a.html).write_text(gallery.render(run, server=False, saved=a.theme))
        print(f"wrote {a.html}", file=sys.stderr)
    tty = sys.stdout.isatty()
    print(f"{theme.name} ({theme.variant}) · {len(run.results)} results · "
          + "; ".join(f"{q['source']}: {','.join(q['colors'])}"
                      + (f" (+ bg keywords: {', '.join(q['hints'])})" if q.get("hints") else "")
                      for q in run.queries))
    for i, r in enumerate(run.results, 1):
        s, c = r.score, r.cand
        sw = "".join(_swatch(cl.hex) for cl in r.clusters[:6]) if tty else ""
        by = f" by {c.author}" if c.author else ""
        print(f"{i:>3}. {s.total:5.1f}  bg {s.background:.2f} pal {s.palette:.2f} pen {s.penalty:.2f}  "
              f"{sw} {c.source}{by} {c.width}x{c.height}  {c.page_url}")
    return 0


def cmd_serve(a) -> int:
    from .server import serve
    serve(_opts(a), a.theme, port=a.port, open_browser=not a.no_open)
    return 0


def cmd_themes(a) -> int:
    print(f"# {themes_dir()}")
    current = choose_theme("system")
    for i in list_themes():
        try:
            t = load_theme(i)
        except (OSError, ValueError, KeyError):
            continue
        mark = "*" if t.id == current.id else " "
        print(f"{mark} {i:<22} {t.variant:<5} {''.join(_swatch(t.palette[k]) for k in ('base00', 'base01', 'base05', 'base08', 'base09', 'base0A', 'base0B', 'base0D', 'base0E'))}")
    return 0


def _theme_id(saved: str) -> str | None:
    """Resolve THEME (or 'system') to an id that exists in the index."""
    t = choose_theme(saved)
    if t.id not in list_themes():
        print(f"error: unknown theme {saved!r} and no theme index to fall back to "
              f"(themes from {themes_dir()})", file=sys.stderr)
        return None
    return t.id


def cmd_apply(a) -> int:
    tid = _theme_id(a.theme)
    if tid is None:
        return 2
    if a.dry_run:
        lib = copy.deepcopy(library.load())
        pick = library.choose(lib, tid, force_next=a.next)
        if pick is None:
            print(f"error: no wallpapers saved for {tid}", file=sys.stderr)
            return 1
        print(f"{tid}: would use {library.file_path(lib, pick)}")
        return 0
    try:
        res = desktop.apply(tid, force_next=a.next, set_desktop=not a.print)
    except (library.LibraryError, desktop.DesktopError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(res["path"] if a.print else f"{tid}: {res['path']}")
    return 0


def cmd_use(a) -> int:
    """Switch the global theme, then the wallpaper if the theme is now active."""
    if a.theme == "system" or a.theme not in list_themes():
        print(f"error: unknown theme {a.theme!r}; see `mood-engine themes`", file=sys.stderr)
        return 2
    theme = load_theme(a.theme)
    path = selection.set_global(theme)
    print(f"theme: {theme.variant} → {theme.id}  ({path})")
    appearance = themes.system_appearance()
    if theme.variant != appearance:
        if not a.appearance:
            print(f"note: macOS is in {appearance} mode, so {theme.id} becomes active when it "
                  f"switches to {theme.variant} (or pass --appearance). Wallpaper unchanged.")
            return 0
        try:
            desktop.set_appearance(theme.variant == "dark")
        except desktop.DesktopError as e:
            print(f"error: could not switch to {theme.variant} mode: {e}", file=sys.stderr)
            return 1
        print(f"appearance: {appearance} → {theme.variant}")
    rep = syncmod.sync(theme.variant, force_wallpaper=True)
    return _print_sync(rep, show_theme=False)


def _print_sync(rep: dict, show_theme: bool = True) -> int:
    if show_theme and rep["theme"]:
        was = f" (was {rep['previous']})" if rep["changed"] and rep["previous"] else ""
        how = "" if rep["changed"] else (", colours edited" if rep.get("edited") else ", unchanged")
        print(f"theme: {rep['theme']}{was}{how}")
    if rep["wallpaper_set"]:
        print(f"wallpaper: {rep['wallpaper']}")
    if rep["note"]:
        print(f"note: {rep['note']}")
    for h in rep["hooks"] or []:
        status = "ok" if h["ok"] else ("timed out" if h["code"] is None else f"exit {h['code']}")
        out = ""
        if h.get("output_file"):
            out = f", wrote {h['output_file']}" if h.get("output_changed") else ", output unchanged"
        print(f"hook: {h['name']}: {status} ({h['seconds']} s{out})")
        if not h["ok"] and h["output"]:
            print("  " + h["output"].replace("\n", "\n  "))
    if rep["error"]:
        print(f"error: {rep['error']}", file=sys.stderr)
        return 1
    return 0 if all(h["ok"] for h in rep["hooks"] or []) else 1


def cmd_sync(a) -> int:
    rep = syncmod.sync(a.appearance, force_wallpaper=a.wallpaper or a.force,
                       force_hooks=a.hooks or a.force)
    if a.json:
        print(json.dumps(rep, indent=1))
        return 0 if not rep["error"] else 1
    return _print_sync(rep)


def cmd_hooks(a) -> int:
    if a.init:
        path, created = syncmod.init_hooks()
        print(f"{'wrote' if created else 'already exists:'} {path}")
        return 0
    if a.run is not None:
        if a.run:
            try:
                names = {h.name for h in syncmod.load_hooks()}
            except syncmod.HookConfigError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            if unknown := [n for n in a.run if n not in names]:
                print(f"error: no hook named {', '.join(map(repr, unknown))}", file=sys.stderr)
                return 2
        return _print_sync(syncmod.sync(force_hooks=a.run or True))
    path = syncmod.hooks_path()
    try:
        hooks = syncmod.load_hooks()
    except syncmod.HookConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"# {path}" + ("" if path.exists() else "  (missing; `mood-engine hooks --init` writes a template)"))
    for h in hooks:
        off = "" if h.enabled else "  (disabled)"
        print(f"- {h.name}{off}")
        if h.template:
            print(f"    render {h.template} → {h.output}")
        if h.run:
            print(f"    run    {h.run}")
    if path.exists() and not hooks:
        print("no hooks enabled")
    last = syncmod.read_state()
    if last.get("hooks_at"):
        print(f"last run {last['hooks_at']} for {last.get('theme')}:")
        for h in last.get("hooks", []):
            print(f"  {'ok  ' if h['ok'] else 'FAIL'} {h['name']}  ({h.get('at', '')})")
    return 0


def cmd_render(a) -> int:
    """Preview a template with a theme (default: the active one)."""
    tid = _theme_id(a.theme)
    if tid is None:
        return 2
    ctx = tplmod.context(load_theme(tid))
    if a.vars:
        for k, v in ctx.items():
            print(f"{k:<28} {v}")
        return 0
    if not a.template:
        print("error: give a TEMPLATE file (or --vars)", file=sys.stderr)
        return 2
    try:
        text = tplmod.render(Path(a.template).expanduser().read_text(), ctx)
    except (OSError, UnicodeDecodeError, tplmod.TemplateError) as e:
        print(f"error: {a.template}: {e}", file=sys.stderr)
        return 1
    if a.output:
        out = Path(a.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out} ({tid})", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_pin(a) -> int:
    tid = _theme_id(a.theme)
    if tid is None:
        return 2
    try:
        with library.edit() as lib:
            t = library.theme_entry(lib, tid)
            if a.cmd == "unpin":
                library.pin(lib, tid, None)
            else:
                key = a.key or t["current"]
                if key is None:
                    raise library.LibraryError(f"no current wallpaper for {tid}; "
                                               "run `mood-engine apply` first or pass --key")
                library.pin(lib, tid, key)
                library.set_current(lib, tid, key)
    except library.LibraryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{tid}: unpinned (daily rotation)" if a.cmd == "unpin" else f"{tid}: pinned {key}")
    return 0


def _theme_summary(t: themes.Theme) -> dict:
    return {"id": t.id, "name": t.name, "variant": t.variant,
            "colors": [t.roles.get(r) for r in ("bg", "surface", "fg", "accent", "success",
                                                 "warning", "error", "info")]}


def cmd_status(a) -> int:
    """Everything the menu bar app shows, in one call."""
    appearance = a.appearance or themes.system_appearance()
    all_themes = []
    for i in list_themes():
        try:
            all_themes.append(_theme_summary(load_theme(i)))
        except (OSError, ValueError, KeyError):
            continue
    active = syncmod.active_theme(appearance)
    other = "light" if appearance == "dark" else "dark"
    other_t = syncmod.active_theme(other)
    lib = library.load()
    wallpaper, count, pinned = None, 0, False
    if active:
        t = lib["themes"].get(active.id, {})
        keys = [k for k in t.get("wallpapers", []) if k in lib["wallpapers"]]
        count = len(keys)
        cur = t.get("current") if t.get("current") in keys else None
        pinned = t.get("pinned") in keys
        if cur:
            w = lib["wallpapers"][cur]
            wallpaper = {"key": cur, "path": str(library.file_path(lib, cur)),
                         "thumb": str(library.thumb_path(lib, cur)),
                         "source": w.get("source"), "author": w.get("author"),
                         "page_url": w.get("page_url"), "pinned": t.get("pinned") == cur}
    hooks: dict = {"path": str(syncmod.hooks_path()), "exists": syncmod.hooks_path().exists(),
                   "count": 0, "names": [], "error": None, "watch": syncmod.watch_dirs()}
    try:
        enabled = [h.name for h in syncmod.load_hooks() if h.enabled]
        hooks["count"], hooks["names"] = len(enabled), enabled
    except syncmod.HookConfigError as e:
        hooks["error"] = str(e)
    out = {"appearance": appearance,
           "active": _theme_summary(active) if active else None,
           "selection": {appearance: active.id if active else None,
                         other: other_t.id if other_t else None},
           "themes": all_themes, "wallpaper": wallpaper, "count": count, "pinned": pinned,
           "hooks": hooks, "last_sync": syncmod.read_state(),
           "paths": {"themes": str(themes.themes_dir()), "state": str(themes.state_dir()),
                     "config": str(syncmod.config_dir()),
                     "library": str(library.library_path()), "data": str(library.data_dir())}}
    print(json.dumps(out, indent=1))
    return 0


def cmd_library(a) -> int:
    lib = library.load()
    ids = sorted(lib["themes"])
    if a.theme_pos:
        tid = _theme_id(a.theme)
        if tid is None:
            return 2
        ids = [tid]
    print(f"# {library.library_path()}")
    shown = False
    for tid in ids:
        t = lib["themes"].get(tid, {})
        keys = [k for k in t.get("wallpapers", []) if k in lib["wallpapers"]]
        if not keys:
            continue
        shown = True
        mode = "pinned" if t.get("pinned") in keys else "daily rotation"
        print(f"{tid}  ({len(keys)} saved, {mode})")
        for k in keys:
            mark = ("P" if t.get("pinned") == k else " ") + ("*" if t.get("current") == k else " ")
            w = lib["wallpapers"][k]
            score = w.get("scores", {}).get(tid)
            print(f"  {mark} {score if score is not None else '':>5}  {k:<24} {library.file_path(lib, k)}")
    if not shown:
        print("no wallpapers saved yet; run `mood-engine` and press Save in the gallery")
    else:
        print("(P = pinned, * = current)")
    return 0


COMMANDS = ("search", "serve", "themes", "apply", "use", "sync", "hooks", "render", "pin", "unpin",
            "library", "status")


def with_default_command(argv: list[str]) -> list[str]:
    """`mood-engine firebox -q x` -> `mood-engine serve firebox -q x`."""
    if argv and (argv[0] in COMMANDS or argv[0] in ("-h", "--help")):
        return argv
    return ["serve", *argv]


def main(argv: list[str] | None = None) -> int:
    argv = with_default_command(sys.argv[1:] if argv is None else list(argv))
    p = argparse.ArgumentParser(prog="mood-engine", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("theme_pos", nargs="?", metavar="THEME",
                        help="theme id from ~/.config/themes, or 'system' (the default: "
                             "the active theme for the OS appearance)")
        sp.add_argument("-t", "--theme", default="system", help="same as THEME")
        sp.add_argument("-q", "--query", default="", help="optional keywords, e.g. 'mountains'")
        sp.add_argument("--sources", default=",".join(ALL_SOURCES),
                        help="comma list of wallhaven,unsplash,pexels (keyless ones are skipped)")
        sp.add_argument("--min-res", default="1920x1080", help="minimum WxH (default 1920x1080)")
        sp.add_argument("--colors", type=int, default=4, help="key colours to query per source (default 4)")
        sp.add_argument("--pages", type=int, default=1, help="result pages per colour query")
        sp.add_argument("-k", type=int, default=8, help="k-means clusters per thumbnail")
        sp.add_argument("-n", "--limit", type=int, default=40, help="results to keep")

    s = sub.add_parser("search", help="rank wallpapers in the terminal")
    common(s)
    s.add_argument("--json", action="store_true", help="print JSON")
    s.add_argument("--html", metavar="FILE", help="also write a static gallery")
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("serve", help="local web gallery")
    common(g)
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-open", action="store_true", help="don't open a browser")
    g.set_defaults(func=cmd_serve)

    t = sub.add_parser("themes", help="list themes from the index")
    t.set_defaults(func=cmd_themes)

    def theme_arg(sp):
        sp.add_argument("theme_pos", nargs="?", metavar="THEME",
                        help="theme id, or 'system' (the default: the active theme)")
        sp.add_argument("-t", "--theme", default="system", help="same as THEME")

    ap = sub.add_parser("apply", help="set the desktop wallpaper for a theme from your library")
    theme_arg(ap)
    ap.add_argument("--next", action="store_true", help="draw a new random wallpaper even if "
                    "today's was already chosen (ignored when one is pinned)")
    ap.add_argument("--print", action="store_true",
                    help="print the chosen file instead of setting it (for other setters)")
    ap.add_argument("--dry-run", action="store_true", help="show the choice, change nothing")
    ap.set_defaults(func=cmd_apply)

    us = sub.add_parser("use", help="switch the global theme (current.json) and its wallpaper")
    us.add_argument("theme", metavar="THEME", help="theme id from the index")
    us.add_argument("--appearance", action="store_true",
                    help="also switch macOS dark/light mode to the theme's variant "
                         "(asks once for Automation permission)")
    us.set_defaults(func=cmd_use)

    lb = sub.add_parser("library", help="list saved wallpapers per theme")
    theme_arg(lb)
    lb.set_defaults(func=cmd_library)

    appearance_arg = dict(choices=("dark", "light"),
                          help="treat macOS as being in this mode (default: ask macOS)")

    sy = sub.add_parser("sync", help="re-apply the active theme's wallpaper and run hooks "
                        "if the active theme changed since the last sync")
    sy.add_argument("--appearance", **appearance_arg)
    sy.add_argument("--wallpaper", action="store_true", help="set the wallpaper even if nothing changed")
    sy.add_argument("--hooks", action="store_true", help="run the hooks even if nothing changed")
    sy.add_argument("--force", action="store_true", help="both --wallpaper and --hooks")
    sy.add_argument("--json", action="store_true", help="print the report as JSON")
    sy.set_defaults(func=cmd_sync)

    hk = sub.add_parser("hooks", help="list the hooks run after a theme change")
    hk.add_argument("--init", action="store_true",
                    help="write a commented hooks.toml and an example template")
    hk.add_argument("--run", nargs="*", metavar="NAME",
                    help="run them now for the active theme (all, or the named ones)")
    hk.set_defaults(func=cmd_hooks)

    rd = sub.add_parser("render", help="preview a hook template with a theme")
    rd.add_argument("template", nargs="?", metavar="TEMPLATE", help="template file")
    rd.add_argument("theme_pos", nargs="?", metavar="THEME",
                    help="theme id, or 'system' (the default: the active theme)")
    rd.add_argument("-t", "--theme", default="system", help="same as THEME")
    rd.add_argument("-o", "--output", help="write here instead of printing")
    rd.add_argument("--vars", action="store_true", help="list the template variables and values")
    rd.set_defaults(func=cmd_render)

    for name, text in (("pin", "pin the theme's current wallpaper (or --key)"),
                       ("unpin", "go back to daily rotation for the theme")):
        pn = sub.add_parser(name, help=text)
        theme_arg(pn)
        if name == "pin":
            pn.add_argument("--key", help="library key to pin, e.g. wallhaven:abc123")
        pn.set_defaults(func=cmd_pin, key=None)

    st = sub.add_parser("status", help="JSON summary for the menu bar app")
    st.add_argument("--appearance", **appearance_arg)
    st.set_defaults(func=cmd_status)

    a = p.parse_args(argv)
    if getattr(a, "theme_pos", None):
        a.theme = a.theme_pos
    return a.func(a)
