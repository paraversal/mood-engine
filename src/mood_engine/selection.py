"""Write the global theme selection (the theme index's "apply to all apps" action).

$THEMES_STATE_DIR/current.json (default ~/.local/state/themes/current.json) holds
{"dark": "<id>", "light": "<id>"}, either key optional. Setting a theme merges its id
under its own variant and keeps the other key. The file is replaced atomically. If
current.json is a symlink, its target is written so the link survives.
This never touches ~/.config/themes or the dotfiles repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .themes import Theme, state_dir


def current_path() -> Path:
    return state_dir() / "current.json"


def read() -> dict:
    try:
        data = json.loads(current_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_global(theme: Theme) -> Path:
    """Make `theme` the global choice for its variant. Returns the file written."""
    sel = read()
    sel[theme.variant] = theme.id
    target = current_path()
    if target.is_symlink():
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(sel, indent=2) + "\n")
    tmp.replace(target)
    return target
