"""Fetch candidates for a theme, score their thumbnails, rank them."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import fetch
from .palette import Cluster, extract_palette, load_image
from .score import SchemeColors, Score, Weights, score_palette
from .sources import ALL_SOURCES, Candidate
from .themes import Theme
from .vocab import key_colors


@dataclass
class Options:
    query: str = ""
    sources: tuple[str, ...] = ("wallhaven", "unsplash", "pexels")
    min_w: int = 1920
    min_h: int = 1080
    n_colors: int = 4
    pages: int = 1
    bg_page_factor: int = 3  # bg colour query fetches pages * this
    k: int = 8
    limit: int = 40


@dataclass
class Result:
    cand: Candidate
    score: Score
    clusters: list[Cluster]


@dataclass
class Run:
    theme: Theme
    opts: Options
    results: list[Result]
    queries: list[dict] = field(default_factory=list)  # what was asked of each API
    warnings: list[str] = field(default_factory=list)


def parse_res(s: str) -> tuple[int, int]:
    if not s:
        return 0, 0
    w, _, h = s.lower().partition("x")
    return int(w), int(h)


def fetch_candidates(theme: Theme, opts: Options, run: Run) -> list[Candidate]:
    colors = key_colors(theme, opts.n_colors)
    jobs = []
    for name in opts.sources:
        src = ALL_SOURCES.get(name)
        if src is None:
            run.warnings.append(f"unknown source {name!r}")
            continue
        if not src.available():
            run.warnings.append(f"{name}: skipped, set {src.env_key} to enable")
            continue
        tokens = list(dict.fromkeys(src.token(hx) for _, hx in colors))
        run.queries.append({"source": name, "colors": tokens,
                            "from": [f"{label} {hx}" for label, hx in colors]})
        for i, tok in enumerate(tokens):
            # The background colour decides most of the score: give it extra pages.
            pages = opts.pages * (opts.bg_page_factor if i == 0 else 1)
            for page in range(1, pages + 1):
                jobs.append((src, tok, page))

    def do(job):
        src, tok, page = job
        try:
            return src.search(opts.query, tok, opts.min_w, opts.min_h, page)
        except (fetch.HTTPError, fetch.URLError, TimeoutError, KeyError, ValueError) as e:
            run.warnings.append(f"{src.name} color={tok}: {e}")
            return []

    seen: dict[str, Candidate] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for batch in ex.map(do, jobs):
            for c in batch:
                seen.setdefault(c.key, c)
    return list(seen.values())


def score_candidates(cands: list[Candidate], theme: Theme, opts: Options,
                     run: Run, weights: Weights | None = None) -> list[Result]:
    scheme = SchemeColors.from_theme(theme)

    def do(c: Candidate):
        try:
            img = load_image(fetch.get_cached_image(c.thumb_url))
            clusters = extract_palette(img, k=opts.k)
            return Result(c, score_palette(clusters, scheme, weights), clusters)
        except Exception as e:  # noqa: BLE001 - one bad thumbnail must not kill the run
            run.warnings.append(f"{c.key}: thumbnail failed ({e})")
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = [r for r in ex.map(do, cands) if r]
    results.sort(key=lambda r: -r.score.total)
    return results


def run(theme: Theme, opts: Options, weights: Weights | None = None) -> Run:
    r = Run(theme=theme, opts=opts, results=[])
    cands = fetch_candidates(theme, opts, r)
    r.results = score_candidates(cands, theme, opts, r, weights)[: opts.limit]
    return r
