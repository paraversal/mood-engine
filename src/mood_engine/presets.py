"""Built-in templates and pre-configured hooks.

Templates ship with mood-engine in mood_engine/templates/ and a hook refers to one as
`template = "builtin:<file>"`, so nothing is copied into the user's config and an
upgrade that improves a template re-renders it on the next sync (the template's text is
part of the hook's fingerprint). `mood-engine hooks --eject NAME` copies one into the
config to customise it.

A preset is a whole hook: `[[hook]] preset = "zed"` fills in the keys below, and any
key next to it overrides the preset's. `app_config` is what the app's own config needs
to use the rendered file; it is shown by `mood-engine hooks --presets`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_PREFIX = "builtin:"
TEMPLATES_DIR = Path(__file__).parent / "templates"
EXAMPLE_HOOKS = "hooks.example.toml"  # in TEMPLATES_DIR, written by `hooks --init`


@dataclass(frozen=True)
class Preset:
    name: str           # the hook's default name
    description: str
    keys: dict = field(default_factory=dict)   # hooks.toml keys
    app_config: str = ""


PRESETS: dict[str, Preset] = {
    "ghostty": Preset(
        name="Ghostty",
        description="Ghostty's theme file; fades open terminals into the new theme, "
                    "then reloads Ghostty",
        keys={"template": "builtin:ghostty", "output": "~/.config/ghostty/themes/mood-engine",
              "run": '"$MOOD_ENGINE" fade', "timeout": 10},
        app_config="~/.config/ghostty/config:  theme = mood-engine",
    ),
    "zed": Preset(
        name="Zed",
        description="Zed's theme file, stepped from the previous theme (Zed reloads it "
                    "by itself)",
        keys={"template": "builtin:zed.json", "output": "~/.config/zed/themes/mood-engine.json",
              "fade": 800},
        app_config='~/.config/zed/settings.json:  "theme": "mood-engine"',
    ),
    "css": Preset(
        name="CSS variables",
        description="the theme's roles as --theme-* CSS custom properties",
        keys={"template": "builtin:colors.css", "output": "~/.cache/mood-engine/colors.css"},
        app_config="@import or <link> ~/.cache/mood-engine/colors.css",
    ),
}


def builtin_names() -> list[str]:
    return sorted(p.name for p in TEMPLATES_DIR.iterdir()
                  if p.is_file() and p.name != EXAMPLE_HOOKS and not p.name.startswith("."))


def builtin_path(ref: str) -> Path:
    """`builtin:zed.json` (or `zed.json`) -> its file. Raises KeyError for an unknown one."""
    name = ref[len(BUILTIN_PREFIX):] if ref.startswith(BUILTIN_PREFIX) else ref
    if name not in builtin_names():
        raise KeyError(f"no built-in template {name!r} (there are: {', '.join(builtin_names())})")
    return TEMPLATES_DIR / name


def label(path: Path | None) -> str | None:
    """How to show a template path: `builtin:<file>` for a built-in one."""
    if path is None:
        return None
    return f"{BUILTIN_PREFIX}{path.name}" if path.parent == TEMPLATES_DIR else str(path)


def example_hooks() -> str:
    return (TEMPLATES_DIR / EXAMPLE_HOOKS).read_text()
