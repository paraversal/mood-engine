"""Reader for the global theme index (~/.config/themes).

Implements the theme-index reader protocol:
locate dirs via env vars, list schemes, merge roles.json with per-theme
overrides, and resolve the theme id from saved choice -> current.json ->
defaults.json -> first theme -> embedded fallback. This module only reads.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Appearance = Literal["dark", "light"]

ROLE_DEFAULTS: dict[str, str] = {
    "bg": "base00",
    "bg-inset": "base10",
    "surface": "base01",
    "surface-raised": "base02",
    "border": "base02",
    "selection": "base02",
    "fg": "base05",
    "fg-muted": "base04",
    "fg-subtle": "base03",
    "accent": "base0D",
    "on-accent": "base00",
    "link": "base0D",
    "info": "base0C",
    "success": "base0B",
    "warning": "base0A",
    "error": "base08",
}

# Embedded fallback (gruvbox dark, hard) so the app runs without ~/.config/themes.
_FALLBACK_PALETTE = {
    "base00": "#1d2021", "base01": "#3c3836", "base02": "#504945", "base03": "#665c54",
    "base04": "#bdae93", "base05": "#d5c4a1", "base06": "#ebdbb2", "base07": "#fbf1c7",
    "base08": "#fb4934", "base09": "#fe8019", "base0A": "#fabd2f", "base0B": "#b8bb26",
    "base0C": "#8ec07c", "base0D": "#83a598", "base0E": "#d3869b", "base0F": "#d65d0e",
    "base10": "#1d2021", "base11": "#1d2021", "base12": "#fb4934", "base13": "#fabd2f",
    "base14": "#b8bb26", "base15": "#8ec07c", "base16": "#83a598", "base17": "#d3869b",
}

PALETTE_KEYS = [f"base{i:02X}" for i in range(0x18)]


@dataclass
class Theme:
    id: str
    name: str
    variant: Appearance
    palette: dict[str, str]
    roles: dict[str, str] = field(default_factory=dict)
    author: str = ""


def blend(a: Theme, b: Theme, x: float) -> Theme:
    """`b` with every palette slot and role mixed from `a` by 1 - x, in OKLab, for the
    in-between frames of a fade. x = 0 gives a's colours, x = 1 is b. The variant flips
    halfway, so an app's dark/light chrome switches once."""
    from .color import hex_to_oklab, oklab_to_hex

    def mix(colours_a: dict[str, str], colours_b: dict[str, str]) -> dict[str, str]:
        out = {}
        for k, hb in colours_b.items():
            ha = colours_a.get(k)
            if ha is None or x >= 1:
                out[k] = hb
            else:
                la = hex_to_oklab(ha)
                out[k] = oklab_to_hex(la + (hex_to_oklab(hb) - la) * x)
        return out
    return Theme(id=b.id, name=b.name, author=b.author,
                 variant=b.variant if x >= 0.5 else a.variant,
                 palette=mix(a.palette, b.palette), roles=mix(a.roles, b.roles))


def themes_dir() -> Path:
    if d := os.environ.get("THEMES_DIR"):
        return Path(d)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "themes"


def state_dir() -> Path:
    if d := os.environ.get("THEMES_STATE_DIR"):
        return Path(d)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "themes"


def _try_json(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def list_themes(d: Path | None = None) -> list[str]:
    d = d or themes_dir()
    try:
        files = sorted((d / "schemes").glob("*.json"))
    except OSError:
        return []
    ids = []
    for f in files:
        data = _try_json(f)
        if isinstance(data, dict) and isinstance(data.get("palette"), dict):
            ids.append(f.stem)
    return ids


def resolve_roles(palette: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    roles = {}
    for role, ref in mapping.items():
        if not isinstance(ref, str):
            continue
        color = ref if ref.startswith("#") else palette.get(ref)
        if color:
            roles[role] = color.lower()
    return roles


def fallback_theme() -> Theme:
    return Theme(
        id="(embedded) gruvbox-dark-hard",
        name="Gruvbox dark, hard (embedded)",
        variant="dark",
        palette=dict(_FALLBACK_PALETTE),
        roles=resolve_roles(_FALLBACK_PALETTE, ROLE_DEFAULTS),
    )


def theme_from_dict(id: str, data: dict, role_map: dict[str, str] | None = None) -> Theme:
    """Build a Theme from a parsed scheme file (also used by tests)."""
    palette = {k: v.lower() for k, v in data["palette"].items() if isinstance(v, str)}
    mapping = {**ROLE_DEFAULTS, **(role_map or {}), **(data.get("roles") or {})}
    variant = data.get("variant", "dark")
    return Theme(
        id=id,
        name=data.get("name", id),
        variant="light" if variant == "light" else "dark",
        palette=palette,
        roles=resolve_roles(palette, mapping),
        author=str(data.get("author") or ""),
    )


def load_theme(id: str, d: Path | None = None) -> Theme:
    d = d or themes_dir()
    data = json.loads((d / "schemes" / f"{id}.json").read_text())
    role_map = _try_json(d / "roles.json") or {}
    return theme_from_dict(id, data, role_map)


def system_appearance() -> Appearance:
    """macOS: `defaults read -g AppleInterfaceStyle` prints Dark in dark mode."""
    if sys.platform != "darwin":
        return "dark"
    try:
        out = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2,
        )
        return "dark" if out.stdout.strip().lower() == "dark" else "light"
    except (OSError, subprocess.SubprocessError):
        return "dark"


def resolve_theme_id(saved: str | None, appearance: Appearance,
                     d: Path | None = None, state: Path | None = None) -> str | None:
    d = d or themes_dir()
    state = state or state_dir()
    ids = list_themes(d)
    if saved and saved != "system" and saved in ids:
        return saved
    for sel in (_try_json(state / "current.json"), _try_json(d / "defaults.json")):
        if isinstance(sel, dict) and sel.get(appearance) in ids:
            return sel[appearance]
    return ids[0] if ids else None


def choose_theme(saved: str | None = "system", appearance: Appearance | None = None) -> Theme:
    """Resolve and load a theme; falls back to the embedded theme on any failure."""
    appearance = appearance or system_appearance()
    try:
        tid = resolve_theme_id(saved, appearance)
        if tid:
            return load_theme(tid)
    except (OSError, ValueError, KeyError):
        pass
    return fallback_theme()
