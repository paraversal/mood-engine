"""Local gallery server (127.0.0.1 only).

Routes
  /            ranked gallery; query: theme, q, minres, src (repeatable)
  /api         same, as JSON
  /download    Unsplash: ping download_location (API terms), then redirect
  /recolor     built-in OKLab recolor of the full image toward the theme
"""

from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import fetch, gallery, pipeline, recolor
from .sources import ALL_SOURCES, Candidate
from .themes import choose_theme, list_themes, load_theme, themes_dir


class State:
    def __init__(self, base: pipeline.Options, saved_theme: str):
        self.base = base
        self.saved_theme = saved_theme
        self.lock = threading.Lock()
        self.cands: dict[str, Candidate] = {}
        self.runs: dict[tuple, pipeline.Run] = {}

    def theme_ids(self) -> list[tuple[str, str]]:
        out = []
        for i in list_themes():
            try:
                out.append((i, load_theme(i).variant))
            except (OSError, ValueError, KeyError):
                pass
        return out

    def run_for(self, qs: dict) -> tuple[pipeline.Run, str]:
        saved = (qs.get("theme") or [self.saved_theme])[0]
        theme = choose_theme(saved)
        opts = self.base
        if "q" in qs or "minres" in qs or "src" in qs:
            mw, mh = pipeline.parse_res((qs.get("minres") or [""])[0])
            opts = replace(opts, query=(qs.get("q") or [""])[0].strip(),
                           min_w=mw, min_h=mh,
                           sources=tuple(qs.get("src") or ()) or opts.sources)
        key = (theme.id, opts.query, opts.min_w, opts.min_h, opts.sources)
        with self.lock:
            run = self.runs.get(key)
        if run is None:
            run = pipeline.run(theme, opts)
            with self.lock:
                self.runs[key] = run
                for r in run.results:
                    self.cands[r.cand.key] = r.cand
        return run, saved


def to_json(run: pipeline.Run) -> dict:
    return {
        "theme": {"id": run.theme.id, "name": run.theme.name, "variant": run.theme.variant},
        "queries": run.queries,
        "warnings": run.warnings,
        "results": [{
            "rank": i + 1, "score": r.score.total, "background": r.score.background,
            "palette": r.score.palette, "penalty": r.score.penalty, "details": r.score.details,
            "source": r.cand.source, "id": r.cand.id, "page_url": r.cand.page_url,
            "preview_url": r.cand.preview_url, "full_url": r.cand.full_url,
            "width": r.cand.width, "height": r.cand.height,
            "author": r.cand.author, "author_url": r.cand.author_url,
            "colors": [{"hex": c.hex, "weight": round(c.weight, 3)} for c in r.clusters],
        } for i, r in enumerate(run.results)],
    }


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quieter
            pass

        def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            try:
                if u.path == "/":
                    run, saved = state.run_for(qs)
                    html = gallery.render(run, server=True, theme_ids=state.theme_ids(), saved=saved)
                    self.send(200, html.encode(), "text/html; charset=utf-8")
                elif u.path == "/api":
                    run, _ = state.run_for(qs)
                    self.send(200, json.dumps(to_json(run), indent=1).encode(), "application/json")
                elif u.path in ("/download", "/recolor"):
                    cand = state.cands.get((qs.get("key") or [""])[0])
                    if cand is None:
                        return self.send(404, b"unknown image (rerun the search)", "text/plain")
                    url = cand.full_url
                    if cand.source == "unsplash":
                        url = ALL_SOURCES["unsplash"].track_download(cand)
                    if u.path == "/download":
                        return self.send(302, b"", "text/plain", {"Location": url})
                    theme = choose_theme((qs.get("theme") or [state.saved_theme])[0])
                    out = recolor.recolor_bytes(fetch.get_bytes(url, timeout=60), theme)
                    self.send(200, out, "image/jpeg", {
                        "Content-Disposition": f'inline; filename="{cand.source}-{cand.id}-recolored.jpg"'})
                elif u.path == "/favicon.ico":
                    self.send(204, b"", "image/x-icon")
                else:
                    self.send(404, b"not found", "text/plain")
            except Exception as e:  # noqa: BLE001
                self.send(500, f"error: {e}".encode(), "text/plain")

    return Handler


def serve(base: pipeline.Options, saved_theme: str, port: int = 8765, open_browser: bool = True):
    state = State(base, saved_theme)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"mood-engine gallery on {url}  (themes from {themes_dir()})  Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
