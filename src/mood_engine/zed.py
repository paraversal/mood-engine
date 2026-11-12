"""The Zed theme template.

Zed reads theme families (JSON, https://zed.dev/schema/themes/v0.2.0.json) from
~/.config/zed/themes and re-reads a file there when it changes, so a hook only renders
this template to ~/.config/zed/themes/mood-engine.json and Zed's settings say
`"theme": "mood-engine"`. The family holds one theme, named "mood-engine", whose
appearance follows the mood-engine theme's variant.

The template is built from the mapping below, so it is valid JSON by construction.
UI colours come from the theme's roles; syntax follows the base16 styling guide; the
terminal's ANSI colours match the Ghostty template.
"""

from __future__ import annotations

import json

from .terminal import ANSI_SLOTS

CLEAR = "#00000000"


def _var(name: str, alpha: str = "") -> str:
    return "#{{" + name + "-hex}}" + alpha


def _role(role: str, alpha: str = "") -> str:
    return _var(f"role-{role}", alpha)


def _slot(slot: str, alpha: str = "") -> str:
    return _var(slot, alpha)


def _syntax(colour: str, font_style: str | None = None, font_weight: int | None = None) -> dict:
    return {"color": _slot(colour) if colour.startswith("base") else _role(colour),
            "font_style": font_style, "font_weight": font_weight}


def _style() -> dict:
    r = _role
    style: dict = {
        "background.appearance": "opaque",
        "background": r("surface"),
        "surface.background": r("surface"),
        "elevated_surface.background": r("surface-raised"),
        "panel.background": r("surface"),
        "title_bar.background": r("surface"),
        "title_bar.inactive_background": r("bg-inset"),
        "status_bar.background": r("surface"),
        "tab_bar.background": r("surface"),
        "tab.inactive_background": r("surface"),
        "tab.active_background": r("bg"),
        "toolbar.background": r("bg"),
        "editor.background": r("bg"),
        "editor.gutter.background": r("bg"),
        "editor.subheader.background": r("surface"),
        "editor.foreground": r("fg"),
        "editor.line_number": r("fg-subtle"),
        "editor.active_line_number": r("fg"),
        "editor.active_line.background": r("surface", "bf"),
        "editor.highlighted_line.background": r("surface"),
        "editor.indent_guide": r("surface-raised"),
        "editor.indent_guide_active": r("fg-subtle"),
        "editor.invisible": r("fg-subtle"),
        "editor.wrap_guide": r("surface-raised", "80"),
        "editor.active_wrap_guide": r("fg-subtle", "80"),
        "editor.document_highlight.read_background": r("accent", "1a"),
        "editor.document_highlight.write_background": r("accent", "33"),
        "editor.document_highlight.bracket_background": r("accent", "26"),
        "search.match_background": r("accent", "40"),
        "drop_target.background": r("accent", "26"),
        "border": r("border"),
        "border.variant": r("surface-raised"),
        "border.focused": r("accent"),
        "border.selected": r("accent"),
        "border.transparent": CLEAR,
        "border.disabled": r("fg-subtle", "80"),
        "pane.focused_border": r("accent"),
        "pane_group.border": r("border"),
        "panel.focused_border": r("accent"),
        "panel.indent_guide": r("surface-raised"),
        "panel.indent_guide_active": r("fg-subtle"),
        "panel.indent_guide_hover": r("fg-muted"),
        "element.background": r("surface"),
        "element.hover": r("surface-raised"),
        "element.active": r("selection"),
        "element.selected": r("selection"),
        "element.disabled": r("surface"),
        "ghost_element.background": CLEAR,
        "ghost_element.hover": r("surface-raised"),
        "ghost_element.active": r("selection"),
        "ghost_element.selected": r("selection"),
        "ghost_element.disabled": CLEAR,
        "text": r("fg"),
        "text.muted": r("fg-muted"),
        "text.placeholder": r("fg-subtle"),
        "text.disabled": r("fg-subtle"),
        "text.accent": r("accent"),
        "icon": r("fg"),
        "icon.muted": r("fg-muted"),
        "icon.placeholder": r("fg-subtle"),
        "icon.disabled": r("fg-subtle"),
        "icon.accent": r("accent"),
        "link_text.hover": r("link"),
        "scrollbar.thumb.background": r("fg-subtle", "4c"),
        "scrollbar.thumb.hover_background": r("fg-subtle", "80"),
        "scrollbar.thumb.border": CLEAR,
        "scrollbar.track.background": CLEAR,
        "scrollbar.track.border": CLEAR,
    }
    for status, role in (("error", "error"), ("warning", "warning"), ("success", "success"),
                         ("info", "info"), ("hint", "fg-subtle"), ("created", "success"),
                         ("deleted", "error"), ("modified", "warning"), ("renamed", "info"),
                         ("conflict", "warning"), ("hidden", "fg-subtle"),
                         ("ignored", "fg-subtle"), ("predictive", "fg-subtle"),
                         ("unreachable", "fg-muted")):
        style[status] = r(role)
        style[f"{status}.background"] = r(role, "1a")
        style[f"{status}.border"] = r(role, "66")

    style |= {"terminal.background": r("bg"), "terminal.ansi.background": r("bg"),
              "terminal.foreground": r("fg"), "terminal.bright_foreground": _slot("base07"),
              "terminal.dim_foreground": r("fg-muted")}
    names = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
    for i, name in enumerate(names):
        style[f"terminal.ansi.{name}"] = _slot(ANSI_SLOTS[i])
        style[f"terminal.ansi.bright_{name}"] = _slot(ANSI_SLOTS[i + 8])
        style[f"terminal.ansi.dim_{name}"] = _slot(ANSI_SLOTS[i], "b3")

    style["accents"] = [_slot(b) for b in ("base0D", "base0E", "base0C", "base0B", "base0A",
                                           "base09", "base08")]
    style["players"] = [{"cursor": r("accent"), "background": r("accent"),
                         "selection": r("selection")}]
    style["players"] += [{"cursor": _slot(b), "background": _slot(b), "selection": _slot(b, "3d")}
                         for b in ("base08", "base0B", "base0E", "base0A", "base0C", "base09",
                                   "base0F")]
    s = _syntax
    style["syntax"] = {
        "comment": s("base03", "italic"), "comment.doc": s("base04", "italic"),
        "keyword": s("base0E"), "operator": s("base0C"), "preproc": s("base0A"),
        "function": s("base0D"), "constructor": s("base0D"), "title": s("base0D", None, 700),
        "string": s("base0B"), "string.escape": s("base0C"), "string.regex": s("base0C"),
        "string.special": s("base0F"), "string.special.symbol": s("base0F"),
        "number": s("base09"), "boolean": s("base09"), "constant": s("base09"),
        "type": s("base0A"), "enum": s("base0A"), "variant": s("base0A"),
        "attribute": s("base0A"),
        "variable": s("fg"), "variable.special": s("base08"), "property": s("base08"),
        "tag": s("base08"), "label": s("base0D"),
        "punctuation": s("fg-muted"), "punctuation.bracket": s("fg-muted"),
        "punctuation.delimiter": s("fg-muted"), "punctuation.list_marker": s("base08"),
        "punctuation.special": s("base0F"),
        "embedded": s("base0F"), "text.literal": s("base0B"),
        "link_text": s("base0D", "italic"), "link_uri": s("base0C"),
        "emphasis": s("fg", "italic"), "emphasis.strong": s("base09", None, 700),
        "predictive": s("fg-subtle", "italic"), "hint": s("fg-subtle"),
    }
    return style


ZED_TEMPLATE = json.dumps({
    "$schema": "https://zed.dev/schema/themes/v0.2.0.json",
    "name": "mood-engine",
    "author": "mood-engine ({{scheme-name}})",
    "themes": [{"name": "mood-engine", "appearance": "{{scheme-variant}}", "style": _style()}],
}, indent=2) + "\n"
