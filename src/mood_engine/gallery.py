"""Render a ranked, themed HTML gallery for a Run."""

from __future__ import annotations

from html import escape
from urllib.parse import quote, urlencode

from .pipeline import Result, Run
from .themes import PALETTE_KEYS

SOURCE_LABEL = {"wallhaven": "Wallhaven", "unsplash": "Unsplash", "pexels": "Pexels"}


def _attribution(r: Result) -> str:
    c = r.cand
    site = SOURCE_LABEL.get(c.source, c.source)
    if c.author:
        return (f'Photo by <a href="{escape(c.author_url)}" target="_blank" rel="noopener">'
                f'{escape(c.author)}</a> on <a href="{escape(c.page_url)}" target="_blank" '
                f'rel="noopener">{site}</a>')
    return f'<a href="{escape(c.page_url)}" target="_blank" rel="noopener">{site} {escape(c.id)}</a>'


def _bar(label: str, value: float, invert: bool = False) -> str:
    pct = round(value * 100)
    cls = "bar bad" if invert else "bar"
    return (f'<div class="metric"><span>{label}</span><div class="{cls}">'
            f'<i style="width:{pct}%"></i></div><b>{pct}</b></div>')


def _card(rank: int, r: Result, server: bool) -> str:
    c, s = r.cand, r.score
    swatches = "".join(
        f'<i style="flex:{cl.weight:.3f};background:{cl.hex}" title="{cl.hex} {cl.weight:.0%}"></i>'
        for cl in r.clusters)
    if c.source == "unsplash":
        # Unsplash requires pinging download_location; the local server does that.
        dl = f"/download?key={quote(c.key)}" if server else c.page_url
    else:
        dl = c.full_url
    recolor = (f'<a class="btn ghost" href="/recolor?key={quote(c.key)}" target="_blank" '
               f'title="Nudge this image toward the theme palette (built-in OKLab remap)">Recolor</a>'
               if server else "")
    return f"""
<article class="card">
  <a class="thumb" href="{escape(c.page_url)}" target="_blank" rel="noopener">
    <img loading="lazy" src="{escape(c.preview_url)}" alt="Wallpaper {escape(c.key)}">
    <span class="rank">#{rank}</span><span class="score">{s.total:.0f}</span>
  </a>
  <div class="swatches">{swatches}</div>
  <div class="metrics">
    {_bar("Background", s.background)}
    {_bar("Palette", s.palette)}
    {_bar("Off-hue", s.penalty, invert=True)}
  </div>
  <p class="meta">{c.width}×{c.height} · colour filter <code>{escape(c.color_query)}</code></p>
  <p class="attr">{_attribution(r)}</p>
  <div class="actions">
    <a class="btn" href="{escape(dl)}" target="_blank" rel="noopener">Download</a>
    <a class="btn ghost" href="{escape(c.page_url)}" target="_blank" rel="noopener">Open on {SOURCE_LABEL.get(c.source, c.source)}</a>
    {recolor}
  </div>
</article>"""


def _form(run: Run, theme_ids: list[tuple[str, str]], saved: str) -> str:
    o = run.opts
    opts = ['<option value="system"' + (' selected' if saved == "system" else "") + '>System</option>']
    for variant in ("dark", "light"):
        group = [f'<option value="{escape(i)}"{" selected" if saved == i else ""}>{escape(i)}</option>'
                 for i, v in theme_ids if v == variant]
        if group:
            opts.append(f'<optgroup label="{variant.title()}">{"".join(group)}</optgroup>')
    src_boxes = "".join(
        f'<label><input type="checkbox" name="src" value="{n}"{" checked" if n in o.sources else ""}> '
        f'{SOURCE_LABEL[n]}</label>' for n in SOURCE_LABEL)
    return f"""
<form method="get" action="/">
  <label>Theme <select name="theme">{"".join(opts)}</select></label>
  <label>Keywords <input name="q" value="{escape(o.query)}" placeholder="e.g. mountains, abstract"></label>
  <label>Min res <input name="minres" value="{o.min_w}x{o.min_h}" size="9"></label>
  <span class="srcs">{src_boxes}</span>
  <button class="btn">Search</button>
</form>"""


def render(run: Run, *, server: bool = False, theme_ids: list[tuple[str, str]] | None = None,
           saved: str = "system") -> str:
    t = run.theme
    css_vars = "".join(f"--theme-{k}:{v};" for k, v in t.roles.items())
    scheme = "".join(f'<i style="background:{t.palette[k]}" title="{k} {t.palette[k]}"></i>'
                     for k in PALETTE_KEYS if k in t.palette)
    cards = "".join(_card(i + 1, r, server) for i, r in enumerate(run.results)) or \
        '<p class="empty">No candidates. Check the warnings above, or try other keywords.</p>'
    queries = "".join(
        f'<li><b>{SOURCE_LABEL.get(q["source"], q["source"])}</b>: '
        f'{", ".join(f"<code>{escape(x)}</code>" for x in q["colors"])}'
        + (f' (background also searched with keywords '
           f'{", ".join(f"<code>{escape(h)}</code>" for h in q["hints"])})' if q.get("hints") else "")
        + '</li>' for q in run.queries)
    warns = "".join(f"<li>{escape(w)}</li>" for w in dict.fromkeys(run.warnings))
    form = _form(run, theme_ids or [], saved) if server else ""
    json_link = (f'<a href="/api?{escape(urlencode({"theme": saved, "q": run.opts.query}))}">JSON</a>'
                 if server else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mood-engine · {escape(t.name)}</title>
<style>
:root {{ {css_vars} color-scheme: {t.variant}; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Inter", system-ui, sans-serif;
  background: var(--theme-bg); color: var(--theme-fg); }}
a {{ color: var(--theme-link); }}
header {{ padding: 20px 24px 12px; background: var(--theme-bg-inset);
  border-bottom: 1px solid var(--theme-border); }}
h1 {{ margin: 0 0 4px; font-size: 20px; }}
h1 small {{ color: var(--theme-fg-muted); font-weight: 400; }}
.scheme {{ display:flex; height: 14px; border-radius: 4px; overflow:hidden; max-width: 720px; margin: 8px 0; }}
.scheme i {{ flex:1; }}
form {{ display:flex; flex-wrap:wrap; gap: 10px 16px; align-items:center; margin-top: 12px; }}
form label {{ color: var(--theme-fg-muted); }}
input, select {{ background: var(--theme-surface); color: var(--theme-fg);
  border: 1px solid var(--theme-border); border-radius: 6px; padding: 5px 8px; font: inherit; }}
input[type=checkbox] {{ accent-color: var(--theme-accent); }}
.srcs {{ display:flex; gap: 10px; }}
.notes {{ color: var(--theme-fg-subtle); font-size: 12px; margin: 8px 0 0; padding-left: 18px; }}
.notes.warn {{ color: var(--theme-warning); }}
main {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 18px; padding: 20px 24px; }}
.card {{ background: var(--theme-surface); border: 1px solid var(--theme-border); border-radius: 10px; overflow:hidden; }}
.thumb {{ position:relative; display:block; aspect-ratio: 16/10; background: var(--theme-surface-raised); }}
.thumb img {{ width:100%; height:100%; object-fit: cover; display:block; }}
.rank, .score {{ position:absolute; top:8px; padding: 2px 8px; border-radius: 999px; font-weight:600; }}
.rank {{ left:8px; background: var(--theme-bg); color: var(--theme-fg-muted); }}
.score {{ right:8px; background: var(--theme-accent); color: var(--theme-on-accent); }}
.swatches {{ display:flex; height: 10px; }}
.metrics {{ padding: 10px 12px 0; display:grid; gap: 4px; }}
.metric {{ display:grid; grid-template-columns: 78px 1fr 28px; gap: 8px; align-items:center;
  font-size: 12px; color: var(--theme-fg-muted); }}
.metric b {{ text-align:right; color: var(--theme-fg); font-weight: 500; }}
.bar {{ height: 6px; background: var(--theme-surface-raised); border-radius: 3px; overflow:hidden; }}
.bar i {{ display:block; height:100%; background: var(--theme-success); }}
.bar.bad i {{ background: var(--theme-error); }}
.meta, .attr {{ margin: 6px 12px 0; font-size: 12px; color: var(--theme-fg-subtle); }}
.attr {{ color: var(--theme-fg-muted); }}
code {{ font: 11px ui-monospace, Menlo, monospace; }}
.actions {{ display:flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px 12px; }}
.btn {{ display:inline-block; padding: 5px 10px; border-radius: 6px; border: 1px solid var(--theme-accent);
  background: var(--theme-accent); color: var(--theme-on-accent); text-decoration:none; font: inherit; cursor:pointer; }}
.btn.ghost {{ background: transparent; color: var(--theme-fg); border-color: var(--theme-border); }}
.btn:hover {{ filter: brightness(1.08); }}
.empty {{ color: var(--theme-fg-muted); }}
footer {{ padding: 0 24px 24px; color: var(--theme-fg-subtle); font-size: 12px; }}
</style></head>
<body>
<header>
  <h1>mood-engine <small>· {escape(t.name)} ({t.variant}) · {len(run.results)} results {json_link}</small></h1>
  <div class="scheme">{scheme}</div>
  {form}
  <ul class="notes">Colour filters sent: {queries}</ul>
  {f'<ul class="notes warn">{warns}</ul>' if warns else ""}
</header>
<main>{cards}</main>
<footer>Scores are 0–100: 40% background fit, 40% palette fit, 20% absence of off-scheme saturated hues.
Images are hotlinked from and credited to their sources; follow each site's licence.</footer>
</body></html>"""
