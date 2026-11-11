"""Local gallery server (127.0.0.1 only).

Pages
  GET  /                  ranked search gallery; query: theme, q, minres, src (repeatable)
  GET  /library           saved wallpapers for a theme; query: theme
  GET  /api               the search ranking as JSON
  GET  /lib/<kind>/<name> a saved wallpaper or thumbnail (only files in the library)
  GET  /recolor           built-in OKLab recolor of the full image toward the theme

Actions (POST, JSON body, same-origin only)
  /api/save    {key, theme}         download the full image, store it, pair it with theme
  /api/apply   {theme, key?}        set the desktop wallpaper (key, or the theme's pick)
  /api/pin     {theme, key|null}    pin a wallpaper for the theme, or back to daily rotation
  /api/unpair  {theme, key}         remove from theme; deletes the file when no theme uses it
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import desktop, fetch, gallery, library, pipeline, recolor
from .sources import ALL_SOURCES, Candidate
from .themes import choose_theme, list_themes, load_theme, themes_dir


class HTTPFail(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


class State:
    def __init__(self, base: pipeline.Options, saved_theme: str):
        self.base = base
        self.saved_theme = saved_theme
        self.lock = threading.Lock()
        self.cands: dict[str, Candidate] = {}
        self.scores: dict[tuple[str, str], float] = {}  # (theme id, key) -> score
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
                    self.scores[(theme.id, r.cand.key)] = r.score.total
        return run, saved

    # --- library actions ---------------------------------------------------

    def save(self, key: str, theme_id: str) -> dict:
        score = self.scores.get((theme_id, key))
        if key in library.load()["wallpapers"]:
            with library.edit() as lib:
                if key in lib["wallpapers"]:
                    library.pair(lib, key, theme_id, score)
                    return {"key": key, "file": lib["wallpapers"][key]["file"], "downloaded": False}
        cand = self.cands.get(key)
        if cand is None:
            raise HTTPFail(404, "unknown image (rerun the search)")
        url = cand.full_url
        if cand.source == "unsplash":
            url = ALL_SOURCES["unsplash"].track_download(cand)
        data = fetch.get_bytes(url, timeout=120)
        try:
            file, thumb, w, h = library.store_image(cand.source, cand.id, data)
        except library.LibraryError as e:
            raise HTTPFail(502, f"download from {cand.source} failed: {e}") from e
        meta = {"source": cand.source, "id": cand.id, "page_url": cand.page_url,
                "author": cand.author, "author_url": cand.author_url,
                "origin_url": cand.full_url, "width": w, "height": h}
        with library.edit() as lib:
            library.add(lib, key, meta, file, thumb, theme_id, score)
        return {"key": key, "file": file, "downloaded": True}


def to_json(run: pipeline.Run) -> dict:
    return {
        "theme": {"id": run.theme.id, "name": run.theme.name, "variant": run.theme.variant},
        "queries": run.queries,
        "warnings": run.warnings,
        "results": [{
            "rank": i + 1, "key": r.cand.key, "score": r.score.total,
            "background": r.score.background, "palette": r.score.palette,
            "penalty": r.score.penalty, "details": r.score.details,
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

        def send_json(self, code: int, obj):
            self.send(code, json.dumps(obj).encode(), "application/json")

        # Only this page may drive the server: a localhost Host header blocks DNS
        # rebinding, and POSTs must be same-origin JSON (a cross-site form can't
        # send that without a CORS preflight, which is never answered).
        def local_origins(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def check_host(self):
            if self.headers.get("Host") not in self.local_origins():
                raise HTTPFail(403, "bad Host header")

        def check_post(self):
            self.check_host()
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{h}" for h in self.local_origins()}:
                raise HTTPFail(403, "cross-origin request refused")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                raise HTTPFail(415, "expected application/json")

        def do_GET(self):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            try:
                self.check_host()
                if u.path == "/":
                    run, saved = state.run_for(qs)
                    html = gallery.render(run, server=True, theme_ids=state.theme_ids(),
                                          saved=saved, library=library.load())
                    self.send(200, html.encode(), "text/html; charset=utf-8")
                elif u.path == "/library":
                    saved = (qs.get("theme") or [state.saved_theme])[0]
                    html = gallery.render_library(choose_theme(saved), library.load(),
                                                  theme_ids=state.theme_ids(), saved=saved)
                    self.send(200, html.encode(), "text/html; charset=utf-8")
                elif u.path == "/api":
                    run, _ = state.run_for(qs)
                    self.send_json(200, to_json(run))
                elif u.path.startswith("/lib/"):
                    self.serve_file(u.path)
                elif u.path == "/recolor":
                    cand = state.cands.get((qs.get("key") or [""])[0])
                    if cand is None:
                        raise HTTPFail(404, "unknown image (rerun the search)")
                    url = cand.full_url
                    if cand.source == "unsplash":
                        url = ALL_SOURCES["unsplash"].track_download(cand)
                    theme = choose_theme((qs.get("theme") or [state.saved_theme])[0])
                    out = recolor.recolor_bytes(fetch.get_bytes(url, timeout=60), theme)
                    self.send(200, out, "image/jpeg", {
                        "Content-Disposition": f'inline; filename="{cand.source}-{cand.id}-recolored.jpg"'})
                elif u.path == "/favicon.ico":
                    self.send(204, b"", "image/x-icon")
                else:
                    raise HTTPFail(404, "not found")
            except HTTPFail as e:
                self.send(e.code, str(e).encode(), "text/plain; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self.send(500, f"error: {e}".encode(), "text/plain; charset=utf-8")

        def serve_file(self, path: str):
            _, _, kind, name = path.split("/", 3) if path.count("/") >= 3 else ("", "", "", "")
            name = unquote(name)
            field = {"wallpapers": "file", "thumbs": "thumb"}.get(kind)
            lib = library.load()
            if not field or name not in {w.get(field) for w in lib["wallpapers"].values()}:
                raise HTTPFail(404, "not in library")
            p = library.data_dir() / kind / name
            if not p.is_file():
                raise HTTPFail(404, "file missing")
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send(200, p.read_bytes(), ctype, {"Cache-Control": "max-age=3600"})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                self.check_post()
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                if not isinstance(body, dict):
                    raise HTTPFail(400, "expected a JSON object")
                theme_id = body.get("theme")
                if theme_id not in list_themes():
                    raise HTTPFail(400, f"unknown theme {theme_id!r}")
                key = body.get("key") or None
                if u.path == "/api/save":
                    if not key:
                        raise HTTPFail(400, "missing key")
                    self.send_json(200, state.save(key, theme_id))
                elif u.path == "/api/apply":
                    self.send_json(200, desktop.apply(theme_id, key))
                elif u.path == "/api/pin":
                    with library.edit() as lib:
                        library.pin(lib, theme_id, key)
                    self.send_json(200, {"pinned": key})
                elif u.path == "/api/unpair":
                    with library.edit() as lib:
                        deleted = library.unpair(lib, key, theme_id)
                    self.send_json(200, {"deleted": deleted})
                else:
                    raise HTTPFail(404, "not found")
            except HTTPFail as e:
                self.send_json(e.code, {"error": str(e)})
            except (library.LibraryError, desktop.DesktopError) as e:
                self.send_json(409, {"error": str(e)})
            except (fetch.HTTPError, fetch.URLError, TimeoutError) as e:
                self.send_json(502, {"error": f"download failed: {e}"})
            except ValueError as e:
                self.send_json(400, {"error": f"bad request: {e}"})
            except Exception as e:  # noqa: BLE001
                self.send_json(500, {"error": str(e)})

    return Handler


def make_server(base: pipeline.Options, saved_theme: str, port: int = 8765) -> ThreadingHTTPServer:
    state = State(base, saved_theme)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    httpd.state = state  # type: ignore[attr-defined]  # for tests
    return httpd


def serve(base: pipeline.Options, saved_theme: str, port: int = 8765, open_browser: bool = True):
    httpd = make_server(base, saved_theme, port)
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
