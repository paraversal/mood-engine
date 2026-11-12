"""Render app theme files from the active theme.

Templates use the tinted-theming (base16/base24) builder variables, so existing
templates for many apps work unchanged:

  scheme-name  scheme-author  scheme-slug  scheme-system (base24)  scheme-variant
  scheme-is-dark-variant  scheme-is-light-variant          (booleans, for sections)
  base00 … base17, each as
    -hex (1d2021)  -hex-r/-hex-g/-hex-b (1d)  -hex-bgr (21201d)
    -rgb-r/-rgb-g/-rgb-b (29)  -dec-r/-dec-g/-dec-b (0.11372549)

plus the theme index's roles, with the same suffixes: role-bg-hex, role-accent-rgb-r, …
and theme-id (the theme's id; same as scheme-slug).

Syntax is a Mustache subset: {{var}} ({{{var}}} and {{& var}} are the same, nothing is
HTML-escaped), sections {{#var}}…{{/var}} and inverted sections {{^var}}…{{/var}} for
booleans, and comments {{! …}}. A line holding only a section or comment tag is
dropped entirely, as in Mustache. Unknown variables are an error, so a typo never
writes a half-broken theme file.
"""

from __future__ import annotations

import re

from .themes import PALETTE_KEYS, Theme


class TemplateError(Exception):
    pass


def _color_vars(prefix: str, hx: str) -> dict[str, str]:
    h = hx.lstrip("#").lower()
    r, g, b = h[0:2], h[2:4], h[4:6]
    out = {f"{prefix}-hex": h, f"{prefix}-hex-bgr": b + g + r}
    for name, part in (("r", r), ("g", g), ("b", b)):
        v = int(part, 16)
        out[f"{prefix}-hex-{name}"] = part
        out[f"{prefix}-rgb-{name}"] = str(v)
        out[f"{prefix}-dec-{name}"] = f"{v / 255:.8f}"
    return out


def context(theme: Theme) -> dict[str, str | bool]:
    """All variables a template can use for `theme`."""
    ctx: dict[str, str | bool] = {
        "scheme-name": theme.name,
        "scheme-author": theme.author,
        "scheme-slug": theme.id,
        "scheme-system": "base24",
        "scheme-variant": theme.variant,
        "scheme-is-dark-variant": theme.variant == "dark",
        "scheme-is-light-variant": theme.variant == "light",
        "theme-id": theme.id,
    }
    for key in PALETTE_KEYS:
        if key in theme.palette:
            ctx.update(_color_vars(key, theme.palette[key]))
    for role, hx in theme.roles.items():
        ctx.update(_color_vars(f"role-{role}", hx))
    return ctx


_STANDALONE = re.compile(r"^[ \t]*(\{\{[#^/!][^}]*\}\})[ \t]*\r?\n", re.MULTILINE)
_TAG = re.compile(r"\{\{(\{)?\s*([#^/!&]?)\s*(.*?)\s*\}?\}\}", re.DOTALL)


def render(source: str, ctx: dict[str, str | bool]) -> str:
    source = _STANDALONE.sub(r"\1", source)
    out: list[str] = []
    stack: list[tuple[str, bool]] = []  # (section name, whether the enclosing output is shown)
    showing = True
    missing: list[str] = []
    pos = 0
    for m in _TAG.finditer(source):
        if showing:
            out.append(source[pos:m.start()])
        pos = m.end()
        kind, name = m.group(2), m.group(3)
        if kind == "!":
            continue
        if kind in ("#", "^"):
            if name not in ctx:
                missing.append(name)
            value = ctx.get(name)
            truthy = bool(value) and value != "false"
            stack.append((name, showing))
            showing = showing and (truthy if kind == "#" else not truthy)
            continue
        if kind == "/":
            if not stack or stack[-1][0] != name:
                raise TemplateError(f"unexpected {{{{/{name}}}}}")
            showing = stack.pop()[1]
            continue
        if name not in ctx:
            missing.append(name)
            continue
        if showing:
            v = ctx[name]
            out.append(("true" if v else "false") if isinstance(v, bool) else v)
    if stack:
        raise TemplateError(f"unclosed {{{{#{stack[-1][0]}}}}}")
    if showing:
        out.append(source[pos:])
    if missing:
        raise TemplateError("unknown variable(s): " + ", ".join(dict.fromkeys(missing)))
    return "".join(out)
