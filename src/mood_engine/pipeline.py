"""Fetch candidates for a theme, score their thumbnails, rank them."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from . import fetch
from .palette import Cluster, extract_palette, image_signature, load_image
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
    bg_hints: bool = True    # extra keyword queries for the bg colour (see BG_HINTS)
    dedupe: float = 0.05     # max per-cell signature distance for "same image"; 0 = off


# Wallhaven's colour filter only means "this colour appears somewhere", and its
# toplist is dominated by dark wallpapers: colors=ffffff returned a median OKLab
# lightness of 0.24, with 2 of 24 images light (Nov 2026). Tag searches fix that
# (`white background`: 20/24 light, `minimalism`: 12/24). Dark themes already get a
# dark pool, so they get no hints. Used only when the user gave no keywords.
BG_HINTS: dict[str, tuple[str, ...]] = {"light": ("white background", "minimalism")}


@dataclass
class Result:
    cand: Candidate
    score: Score
    clusters: list[Cluster]
    signature: np.ndarray | None = None


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
        hints = (BG_HINTS.get(theme.variant, ())
                 if src.bg_hints and opts.bg_hints and not opts.query else ())
        run.queries.append({"source": name, "colors": tokens, "hints": list(hints),
                            "from": [f"{label} {hx}" for label, hx in colors]})
        for i, tok in enumerate(tokens):
            # The background colour decides most of the score: give it extra pages.
            pages = opts.pages * (opts.bg_page_factor if i == 0 else 1)
            for page in range(1, pages + 1):
                jobs.append((src, opts.query, tok, page))
            if i == 0:
                for hint in hints:
                    for page in range(1, opts.pages + 1):
                        jobs.append((src, hint, tok, page))

    def do(job):
        src, query, tok, page = job
        try:
            return src.search(query, tok, opts.min_w, opts.min_h, page)
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
            return Result(c, score_palette(clusters, scheme, weights), clusters,
                          image_signature(img))
        except Exception as e:  # noqa: BLE001 - one bad thumbnail must not kill the run
            run.warnings.append(f"{c.key}: thumbnail failed ({e})")
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = [r for r in ex.map(do, cands) if r]
    results.sort(key=lambda r: -r.score.total)
    return dedupe(results, opts.dedupe)


def dedupe(results: list[Result], threshold: float) -> list[Result]:
    """Drop re-uploads: keep the first (best-ranked) of images whose 16x9 OKLab
    signatures match in every cell. Using the max rather than the mean matters: two
    different minimal black wallpapers differ only in a few cells, so their mean
    distance is tiny. In 287 live Wallhaven thumbnails the closest distinct pair had
    a max of 0.086, while a rescaled copy stays far below 0.05. A re-crop of the
    same art shifts every cell and is not caught."""
    if threshold <= 0:
        return results
    kept: list[Result] = []
    for r in results:
        if r.signature is not None and any(
                k.signature is not None
                and float(np.sqrt(((r.signature - k.signature) ** 2).sum(-1)).max()) < threshold
                for k in kept):
            continue
        kept.append(r)
    return kept


def run(theme: Theme, opts: Options, weights: Weights | None = None) -> Run:
    r = Run(theme=theme, opts=opts, results=[])
    cands = fetch_candidates(theme, opts, r)
    r.results = score_candidates(cands, theme, opts, r, weights)[: opts.limit]
    return r
