import pytest

from mood_engine.themes import theme_from_dict

# Copies of two schemes so tests never depend on ~/.config/themes.
FIREBOX = {
    "name": "FireBox", "variant": "dark",
    "palette": {
        "base00": "#111111", "base01": "#272524", "base02": "#3c3836", "base03": "#928374",
        "base04": "#a89984", "base05": "#ebdbb2", "base06": "#fbf1c7", "base07": "#f9f5d7",
        "base08": "#cc241d", "base09": "#fe8019", "base0A": "#d79921", "base0B": "#98971a",
        "base0C": "#689d6a", "base0D": "#458588", "base0E": "#b16286", "base0F": "#d48250",
        "base10": "#111111", "base11": "#111111", "base12": "#fb4934", "base13": "#fabd2f",
        "base14": "#b8bb26", "base15": "#8ec07c", "base16": "#83a598", "base17": "#d3869b",
    },
    "roles": {"selection": "#2c2725", "accent": "base09", "on-accent": "#000000",
              "link": "base16", "info": "base16", "success": "base14", "error": "#ff8678"},
}

SOLARIZED_LIGHT = {
    "name": "Solarized Light", "variant": "light",
    "palette": {
        "base00": "#fdf6e3", "base01": "#eee8d5", "base02": "#93a1a1", "base03": "#839496",
        "base04": "#657b83", "base05": "#586e75", "base06": "#073642", "base07": "#002b36",
        "base08": "#dc322f", "base09": "#cb4b16", "base0A": "#b58900", "base0B": "#859900",
        "base0C": "#2aa198", "base0D": "#268bd2", "base0E": "#6c71c4", "base0F": "#d33682",
        "base10": "#fdf6e3", "base11": "#fdf6e3", "base12": "#dc322f", "base13": "#b58900",
        "base14": "#859900", "base15": "#2aa198", "base16": "#268bd2", "base17": "#6c71c4",
    },
    "roles": {"surface-raised": "base01", "selection": "base01"},
}


@pytest.fixture
def firebox():
    return theme_from_dict("firebox", FIREBOX)


@pytest.fixture
def solarized_light():
    return theme_from_dict("solarized-light", SOLARIZED_LIGHT)


@pytest.fixture(autouse=True)
def no_real_terminals(monkeypatch):
    """No test finds (and so signals or writes to) the real Ghostty or its terminals."""
    from mood_engine import terminal
    monkeypatch.setattr(terminal, "processes", lambda: [])
