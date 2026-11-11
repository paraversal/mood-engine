"""Local wallpaper library: saved images, their theme pairings, and which one is active.

Files
  $DATA/wallpapers/<source>-<id>.<ext>    the saved image
  $DATA/thumbs/<source>-<id>.jpg          640 px preview for the library page
  $STATE/library.json                     pairings and per-theme selection

DATA  = $MOOD_ENGINE_DATA_DIR  or $XDG_DATA_HOME/mood-engine  or ~/.local/share/mood-engine
STATE = $MOOD_ENGINE_STATE_DIR or $XDG_STATE_HOME/mood-engine or ~/.local/state/mood-engine

library.json is the contract with other programs (e.g. a menu bar app):

  {"version": 1,
   "wallpapers": {"<source>:<id>": {"file": "wallhaven-abc.jpg", "thumb": "wallhaven-abc.jpg",
                                    "source", "id", "page_url", "author", "author_url",
                                    "width", "height", "added": "<ISO time>",
                                    "scores": {"<theme id>": 87.9}}},
   "themes": {"<theme id>": {"wallpapers": ["<key>", ...],
                             "pinned": "<key>" | null,      # null = rotate daily at random
                             "current": "<key>" | null,
                             "changed": "YYYY-MM-DD" | null}}}

Writers hold an exclusive flock on $STATE/library.lock for the whole
read-modify-write and replace library.json atomically (temp file + rename).
Readers may read without the lock. File names are always relative to $DATA.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import random
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from PIL import Image

VERSION = 1
MAX_BYTES = 80 * 1024 * 1024
THUMB_SIDE = 640
_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class LibraryError(Exception):
    pass


def data_dir() -> Path:
    if d := os.environ.get("MOOD_ENGINE_DATA_DIR"):
        return Path(d)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "mood-engine"


def state_dir() -> Path:
    if d := os.environ.get("MOOD_ENGINE_STATE_DIR"):
        return Path(d)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "mood-engine"


def library_path() -> Path:
    return state_dir() / "library.json"


def empty() -> dict:
    return {"version": VERSION, "wallpapers": {}, "themes": {}}


def load() -> dict:
    """Read library.json; a missing or unreadable file is an empty library."""
    try:
        data = json.loads(library_path().read_text())
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    data.setdefault("version", VERSION)
    data.setdefault("wallpapers", {})
    data.setdefault("themes", {})
    return data


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


@contextlib.contextmanager
def edit() -> Iterator[dict]:
    """Locked read-modify-write of library.json."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "library.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lib = load()
        yield lib
        _atomic_write(library_path(), (json.dumps(lib, indent=1) + "\n").encode())


def theme_entry(lib: dict, theme_id: str) -> dict:
    t = lib["themes"].setdefault(theme_id, {})
    t.setdefault("wallpapers", [])
    t.setdefault("pinned", None)
    t.setdefault("current", None)
    t.setdefault("changed", None)
    return t


def file_path(lib: dict, key: str) -> Path:
    return data_dir() / "wallpapers" / lib["wallpapers"][key]["file"]


def thumb_path(lib: dict, key: str) -> Path:
    return data_dir() / "thumbs" / lib["wallpapers"][key]["thumb"]


def _safe_name(source: str, id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"{source}-{id}")


def store_image(source: str, id: str, data: bytes) -> tuple[str, str, int, int]:
    """Validate and write an image plus its thumbnail. Returns (file, thumb, w, h)."""
    if len(data) > MAX_BYTES:
        raise LibraryError(f"image is larger than {MAX_BYTES // 2**20} MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001 - PIL raises many types for bad data
        raise LibraryError(f"not an image ({e})") from e
    ext = _EXT.get(img.format or "")
    if ext is None:
        raise LibraryError(f"unsupported image format {img.format}")
    name = _safe_name(source, id)
    file, thumb = f"{name}.{ext}", f"{name}.jpg"
    _atomic_write(data_dir() / "wallpapers" / file, data)
    small = img.convert("RGB")
    small.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=85)
    _atomic_write(data_dir() / "thumbs" / thumb, buf.getvalue())
    return file, thumb, img.width, img.height


def add(lib: dict, key: str, meta: dict, file: str, thumb: str, theme_id: str,
        score: float | None = None) -> None:
    """Record a stored image and pair it with a theme."""
    w = lib["wallpapers"].setdefault(key, {})
    w.update(meta)
    w.update(file=file, thumb=thumb)
    w.setdefault("added", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    w.setdefault("scores", {})
    if score is not None:
        w["scores"][theme_id] = score
    pair(lib, key, theme_id)


def pair(lib: dict, key: str, theme_id: str, score: float | None = None) -> None:
    if key not in lib["wallpapers"]:
        raise LibraryError(f"{key} is not in the library")
    t = theme_entry(lib, theme_id)
    if key not in t["wallpapers"]:
        t["wallpapers"].append(key)
    if score is not None:
        lib["wallpapers"][key].setdefault("scores", {})[theme_id] = score


def unpair(lib: dict, key: str, theme_id: str) -> bool:
    """Remove a wallpaper from a theme. When no theme uses it any more, its files
    and entry are deleted. Returns True if the files were deleted."""
    t = theme_entry(lib, theme_id)
    if key in t["wallpapers"]:
        t["wallpapers"].remove(key)
    for field in ("pinned", "current"):
        if t[field] == key:
            t[field] = None
    if any(key in other.get("wallpapers", []) for other in lib["themes"].values()):
        return False
    w = lib["wallpapers"].pop(key, None)
    if w:
        for sub, name in (("wallpapers", w.get("file")), ("thumbs", w.get("thumb"))):
            if name:
                with contextlib.suppress(FileNotFoundError):
                    (data_dir() / sub / name).unlink()
    return True


def pin(lib: dict, theme_id: str, key: str | None) -> None:
    """Pin a wallpaper for a theme (fixed), or None to go back to daily rotation."""
    t = theme_entry(lib, theme_id)
    if key is not None and key not in t["wallpapers"]:
        raise LibraryError(f"{key} is not paired with {theme_id}")
    t["pinned"] = key


def choose(lib: dict, theme_id: str, *, today: date | None = None, force_next: bool = False,
           rng: random.Random | None = None) -> str | None:
    """Pick the wallpaper to show for a theme and record it as current.

    Pinned: always the pin. Otherwise the current one is kept for the rest of the
    day; on a new day (or with force_next) another one is drawn at random, never
    the same as the current one when there is a choice.
    """
    t = theme_entry(lib, theme_id)
    keys = [k for k in t["wallpapers"] if k in lib["wallpapers"]]
    if not keys:
        return None
    today_s = (today or date.today()).isoformat()
    if t["pinned"] in keys:
        pick = t["pinned"]
    elif t["current"] in keys and t["changed"] == today_s and not force_next:
        pick = t["current"]
    else:
        pool = [k for k in keys if k != t["current"]] or keys
        pick = (rng or random).choice(pool)
    if pick != t["current"] or t["changed"] != today_s:
        t["current"], t["changed"] = pick, today_s
    return pick


def set_current(lib: dict, theme_id: str, key: str, today: date | None = None) -> None:
    t = theme_entry(lib, theme_id)
    if key not in t["wallpapers"]:
        raise LibraryError(f"{key} is not paired with {theme_id}")
    t["current"], t["changed"] = key, (today or date.today()).isoformat()
