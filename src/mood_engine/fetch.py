"""Tiny HTTP layer with an on-disk cache (keeps us well inside API rate limits)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "mood-engine/0.1 (+local prototype)"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "mood-engine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url: str, headers: dict[str, str] | None = None, ttl: float = 3600,
             use_cache: bool = True):
    """GET JSON. Cached by URL (auth headers are not part of the key) for `ttl` seconds."""
    path = cache_dir() / "api" / f"{_key(url)}.json"
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < ttl:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    data = json.loads(get_bytes(url, headers))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    return data


def get_cached_image(url: str) -> bytes:
    """Thumbnails are immutable, so cache them forever."""
    path = cache_dir() / "thumbs" / _key(url)
    if path.exists():
        return path.read_bytes()
    data = get_bytes(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


def warn(msg: str) -> None:
    print(f"mood-engine: {msg}", file=sys.stderr)


HTTPError = urllib.error.HTTPError
URLError = urllib.error.URLError
