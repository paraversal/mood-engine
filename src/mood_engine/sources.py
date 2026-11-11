"""Candidate sources: Wallhaven (no key), Unsplash and Pexels (keys from env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlencode

from . import fetch
from .vocab import pexels_color, snap_wallhaven, unsplash_name

APP_NAME = "mood-engine"  # used for Unsplash utm_source attribution links


@dataclass
class Candidate:
    source: str            # "wallhaven" | "unsplash" | "pexels"
    id: str
    page_url: str          # human page on the source site (attribution / link)
    thumb_url: str         # small image used for scoring
    preview_url: str       # medium image shown (hotlinked) in the gallery
    full_url: str          # full-resolution image
    width: int
    height: int
    author: str = ""
    author_url: str = ""
    color_query: str = ""  # which colour filter found it
    download_location: str = ""  # Unsplash: must be pinged when the user downloads
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"


class Source:
    name = ""
    env_key = ""

    def available(self) -> bool:
        return not self.env_key or bool(os.environ.get(self.env_key))

    def token(self, hex_color: str) -> str:
        raise NotImplementedError

    def search(self, query: str, token: str, min_w: int, min_h: int, page: int = 1) -> list[Candidate]:
        raise NotImplementedError


class Wallhaven(Source):
    """https://wallhaven.cc/help/api  - SFW search needs no key; 45 req/min."""

    name = "wallhaven"
    env_key = ""  # WALLHAVEN_API_KEY is optional

    def token(self, hex_color: str) -> str:
        return snap_wallhaven(hex_color)

    def search(self, query, token, min_w, min_h, page=1):
        params = {
            # general only by default; WALLHAVEN_CATEGORIES=111 adds anime + people
            "categories": os.environ.get("WALLHAVEN_CATEGORIES", "100"),
            "purity": "100",  # SFW only
            "colors": token,
            "ratios": "landscape",
            "sorting": "relevance" if query else "toplist",
            "page": page,
        }
        if not query:
            params["topRange"] = "1y"
        if query:
            params["q"] = query
        if min_w and min_h:
            params["atleast"] = f"{min_w}x{min_h}"
        if key := os.environ.get("WALLHAVEN_API_KEY"):
            params["apikey"] = key
        data = fetch.get_json("https://wallhaven.cc/api/v1/search?" + urlencode(params))
        out = []
        for w in data.get("data", []):
            out.append(Candidate(
                source=self.name, id=w["id"], page_url=w["url"],
                thumb_url=w["thumbs"]["original"], preview_url=w["thumbs"]["original"],
                full_url=w["path"], width=int(w["dimension_x"]), height=int(w["dimension_y"]),
                color_query=token, extra={"colors": w.get("colors", [])},
            ))
        return out


class Unsplash(Source):
    """https://unsplash.com/documentation  - needs UNSPLASH_ACCESS_KEY.

    Terms honoured: images are hotlinked from the returned urls, every result
    is attributed ("Photo by X on Unsplash" with utm params) and the
    download_location endpoint is called when the user downloads (server.py).
    """

    name = "unsplash"
    env_key = "UNSPLASH_ACCESS_KEY"

    def headers(self):
        return {"Authorization": f"Client-ID {os.environ[self.env_key]}", "Accept-Version": "v1"}

    def token(self, hex_color: str) -> str:
        return unsplash_name(hex_color)

    @staticmethod
    def utm(url: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}utm_source={APP_NAME}&utm_medium=referral"

    def search(self, query, token, min_w, min_h, page=1):
        params = {
            "query": query or "wallpaper",
            "color": token,
            "orientation": "landscape",
            "per_page": 30,
            "page": page,
            "content_filter": "high",
        }
        data = fetch.get_json("https://api.unsplash.com/search/photos?" + urlencode(params),
                              headers=self.headers())
        out = []
        for p in data.get("results", []):
            w, h = int(p["width"]), int(p["height"])
            if w < min_w or h < min_h:
                continue
            out.append(Candidate(
                source=self.name, id=p["id"], page_url=self.utm(p["links"]["html"]),
                thumb_url=p["urls"]["thumb"], preview_url=p["urls"]["small"],
                full_url=p["urls"]["full"], width=w, height=h,
                author=p["user"]["name"], author_url=self.utm(p["user"]["links"]["html"]),
                color_query=token, download_location=p["links"]["download_location"],
                extra={"avg_color": p.get("color"), "blur_hash": p.get("blur_hash")},
            ))
        return out

    def track_download(self, cand: Candidate) -> str:
        """Ping download_location (required by the API guidelines); returns the image URL."""
        data = fetch.get_json(cand.download_location, headers=self.headers(), use_cache=False)
        return data.get("url") or cand.full_url


class Pexels(Source):
    """https://www.pexels.com/api/documentation  - needs PEXELS_API_KEY; takes hex colours."""

    name = "pexels"
    env_key = "PEXELS_API_KEY"

    def token(self, hex_color: str) -> str:
        return pexels_color(hex_color)

    def search(self, query, token, min_w, min_h, page=1):
        params = {
            "query": query or "wallpaper",
            "color": token,
            "orientation": "landscape",
            "per_page": 40,
            "page": page,
        }
        data = fetch.get_json("https://api.pexels.com/v1/search?" + urlencode(params),
                              headers={"Authorization": os.environ[self.env_key]})
        out = []
        for p in data.get("photos", []):
            w, h = int(p["width"]), int(p["height"])
            if w < min_w or h < min_h:
                continue
            out.append(Candidate(
                source=self.name, id=str(p["id"]), page_url=p["url"],
                thumb_url=p["src"]["small"], preview_url=p["src"]["medium"],
                full_url=p["src"]["original"], width=w, height=h,
                author=p.get("photographer", ""), author_url=p.get("photographer_url", ""),
                color_query=token, extra={"avg_color": p.get("avg_color")},
            ))
        return out


ALL_SOURCES: dict[str, Source] = {s.name: s for s in (Wallhaven(), Unsplash(), Pexels())}
