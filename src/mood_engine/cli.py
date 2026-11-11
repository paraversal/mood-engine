"""mood-engine CLI: `search` (terminal / JSON / static HTML), `serve` (gallery), `themes`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import gallery, pipeline
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
          + "; ".join(f"{q['source']}: {','.join(q['colors'])}" for q in run.queries))
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mood-engine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-t", "--theme", default="system",
                        help="theme id from ~/.config/themes, or 'system' (default: OS appearance)")
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

    a = p.parse_args(argv)
    return a.func(a)
