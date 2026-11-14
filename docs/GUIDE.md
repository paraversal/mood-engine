# mood-engine guide

Setup, daily use, theming hooks, and the app integrations that have been tested. For the
short version, start with the [README](../README.md).

## Contents

- [Requirements and install](#requirements-and-install)
- [What mood-engine is](#what-mood-engine-is)
- [Theme index](#theme-index)
- [Commands](#commands)
- [Switching the theme](#switching-the-theme)
- [Menu bar app](#menu-bar-app)
- [Hooks](#hooks)
- [App support](#app-support)
- [Tested apps](#tested-apps)
- [Adding another app](#adding-another-app)
- [The themes Claude skill](#the-themes-claude-skill)
- [Wallpaper sources and environment](#wallpaper-sources-and-environment)
- [Wallpapers: gallery and library](#wallpapers-gallery-and-library)
- [How wallpapers are ranked](#how-wallpapers-are-ranked)
- [API terms and recolouring](#api-terms-and-recolouring)
- [Development](#development)
- [Known limits](#known-limits)

## Requirements and install

- **macOS** for setting wallpapers and for the menu bar app. Search, rendering and the
  local gallery also work on other platforms.
- [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11. uv fetches Python if needed.
- Xcode or the Command Line Tools to build the menu bar app.
- macOS 14+ for the menu bar app.

```bash
git clone https://github.com/paraversal/mood-engine.git
cd mood-engine
uv sync
uv run mood-engine themes                 # list themes; * = what "system" resolves to
uv run mood-engine use firebox            # theme the apps and the desktop
uv run mood-engine                        # gallery: find a wallpaper for the theme
uv run mood-engine firebox                # gallery for a given theme
./macos/build.sh --install                # optional menu bar app
```

`uv tool install -e .` puts `mood-engine` on your `PATH`. The menu bar app runs the
repository's `.venv/bin/mood-engine` (path baked in at build time), or else `mood-engine`
on your login shell's `PATH`, or one you pick from its menu. Run `uv sync` before
building it.

## What mood-engine is

mood-engine is a theming app for macOS, not a wallpaper finder that added theming. The
theme index is the input and the source of truth; applying it to apps and the desktop is
the job. The wallpaper is one of the things the theme controls.

That distinction shapes the design:

- `~/.config/themes` is read-only. Apps that can implement the reader follow the same
  choice; apps that can't are kept in line by hooks.
- `mood-engine use` changes the global selection, renders/fades/notifies the apps, and
  picks the theme's wallpaper from the library. The wallpaper is chosen first so hooks
  receive its path, but it is set while the hooks run so no fade waits on the desktop.
- Wallpaper discovery is supporting infrastructure. Instead of extracting a palette from
  an image (pywal, wallust, matugen) or recolouring an image to a palette (lutgen,
  gowall), mood-engine starts from curated theme data and finds an existing image that
  fits. The gallery and library exist so the desktop can keep up with the theme.

The rest of this guide follows the same order: theme index, commands, switching, hooks
and app support first; wallpaper sources, gallery, library and scoring after that.

## Theme index

mood-engine reads themes from a plain-JSON directory, `~/.config/themes` by default
(override with `THEMES_DIR`). It only ever reads it:

```
~/.config/themes/
  schemes/<id>.json   {"name", "variant": "dark"|"light",
                       "palette": {"base00": "#rrggbb", … "base17": …},
                       "roles": {optional overrides, e.g. "accent": "base09"}}
  roles.json          role -> palette slot, e.g. {"bg": "base00", "accent": "base0D", …}
  defaults.json       {"dark": "<id>", "light": "<id>"}   used for -t system
~/.local/state/themes/current.json   optional, same shape, overrides defaults.json
```

Palettes use the [Base24](https://github.com/tinted-theming/base24) slots, so any scheme
from the tinted-theming catalogue can be converted. The id is the file name without
`.json`. Roles are the semantic colours that scoring, templates and the gallery use:

| Role             | Default | Use for                                                    |
|------------------|---------|------------------------------------------------------------|
| `bg`             | base00  | window / page background                                   |
| `bg-inset`       | base10  | wells, sidebars, code blocks                               |
| `surface`        | base01  | cards, panels, status bars, inputs                         |
| `surface-raised` | base02  | popovers, menus, hovered rows                              |
| `border`         | base02  | dividers, outlines                                         |
| `selection`      | base02  | selected text / selected row background                    |
| `fg`             | base05  | body text                                                  |
| `fg-muted`       | base04  | secondary text, labels                                     |
| `fg-subtle`      | base03  | placeholders, disabled text, comments                      |
| `accent`         | base0D  | primary buttons, focus rings, active indicators            |
| `on-accent`      | base00  | text and icons drawn on an `accent` fill                   |
| `link`           | base0D  | hyperlinks                                                 |
| `info`           | base0C  | informational status                                       |
| `success`        | base0B  | success status                                             |
| `warning`        | base0A  | warning status                                             |
| `error`          | base08  | errors, destructive actions                                |

A role value is either a palette slot name (`"base0D"`) or a literal hex colour
(`"#a6adc8"`). A value that starts with `#` is a literal.

**Choosing the theme.** `system` resolves through `current.json` and then
`defaults.json` for the current macOS appearance, then the first theme. Without the
directory, mood-engine falls back to an embedded Gruvbox dark theme. Apps that implement
the same reader protocol follow the same choice.

`mood-engine use` writes `current.json` atomically, keeping the other variant's key. If
`current.json` is a symlink, the link's target is written.

## Commands

```
mood-engine use     THEME [--appearance]
mood-engine sync    [--appearance dark|light] [--wallpaper] [--hooks] [--force]
                    [--wallpaper-delay SECONDS] [--json]
mood-engine hooks   [--init] [--presets] [--eject NAME] [--run [NAME ...]]
mood-engine render  [TEMPLATE | builtin:NAME] [THEME] [-o OUT] [--vars]
mood-engine fade    [THEME] [--from THEME] [--app ghostty] [--ms 400] [--no-reload] [--dry-run]
mood-engine status  [--appearance dark|light]
mood-engine themes
mood-engine apply   [THEME] [--next] [--print] [--dry-run]
mood-engine pin     [THEME] [--key SOURCE:ID]
mood-engine unpin   [THEME]
mood-engine library [THEME]
mood-engine [THEME] [options]           same as `mood-engine serve [THEME] [options]`
mood-engine search|serve [THEME] [-q KEYWORDS] [--sources wallhaven,unsplash,pexels]
                       [--min-res 1920x1080] [--colors 4] [--pages 1] [-k 8] [-n 40]
mood-engine search ... [--json] [--html out/gallery.html]
mood-engine serve  ... [--port 8765] [--no-open]
```

- `THEME` (or `-t/--theme`) is a theme id, or `system` (the default). `system` resolves
  through `current.json` and then `defaults.json` for the current macOS appearance, then
  falls back to the first theme. If the index is missing, an embedded Gruvbox theme is
  used.
- `--json` on `search` and `status` is machine-readable; `--html` writes a static gallery.
- `-q` adds keywords such as `mountains`, `abstract` or `minimal`. Keywords help a lot,
  especially for light themes.
- In the gallery you can switch theme, keywords, minimum resolution and sources. The
  `JSON` link returns the same ranking as data.

## Switching the theme

`mood-engine use THEME` is the theme index's "apply to all apps" action:

1. It writes the theme id into `~/.local/state/themes/current.json` under the theme's
   variant (`dark` or `light`) and keeps the other key. The file is replaced atomically.
2. If the active theme changed and the theme is now active (its variant matches the
   macOS appearance), it runs your [hooks](#hooks): apps render the new theme, fade into
   it, or receive a notification.
3. It picks the theme's wallpaper from the library — the pin, or today's pick — and
   starts setting it while the hooks run, so no fade waits on the desktop. With nothing
   saved for the theme, the switch still happens and a note says so.

Apps that follow the themes protocol with live reload pick up the change straight away.
Others need a hook, or pick it up the next time they start.

Switching to a theme of the other variant, e.g. `use solarized-light` while macOS is
dark, sets your light theme but changes nothing visible until macOS goes light. Pass
`--appearance` to also switch macOS to the theme's variant. That goes through System
Events, so the first time macOS asks to let your terminal control it (System Settings →
Privacy & Security → Automation).

To change only the wallpaper without touching the global theme, use
`mood-engine apply THEME`.

### What `sync` applies

`mood-engine sync` brings the desktop in line with the active theme and compares it with
the last sync, kept in `~/.local/state/mood-engine/sync.json`:

| Since the last sync                     | Hooks            | Wallpaper            |
|-----------------------------------------|------------------|----------------------|
| active theme changed                    | all run          | set                  |
| same theme, colours edited in a scheme  | all run          | –                    |
| a hook or its template edited, or added | that hook runs   | –                    |
| same theme, new day                     | –                | set (daily rotation) |
| nothing                                 | –                | –                    |

Each hook remembers a fingerprint of what it last ran for: the theme's colours, its own
definition and its template. `--wallpaper` and `--hooks` force either one, `--force`
both. A lock serialises concurrent syncs, so one change never runs the hooks twice, even
when `mood-engine use` and the menu bar app both notice it. `--json` prints a report;
`status` prints everything the menu bar app shows.

`--wallpaper-delay` holds the wallpaper back while hooks start at once. The menu bar app
uses it after a dark/light flip: setting the wallpaper while macOS is still redrawing for
the new appearance can leave the menu bar blank until it is clicked.

## Menu bar app

`macos/` holds a small native menu bar app (Swift, AppKit, macOS 14+). It keeps no logic
of its own: it watches for changes and calls the CLI.

```bash
./macos/build.sh             # builds macos/build/mood-engine.app
./macos/build.sh --install   # copies it to ~/Applications and starts it
```

**When it syncs:** on launch; when macOS switches between dark and light, including on
its own schedule; when `current.json`, `defaults.json`, a scheme, `hooks.toml` or a
template changes (watched at their real paths, so stow symlinks and edits in the
dotfiles repo count); after waking from sleep; and when the day changes (daily rotation).
When you switch Spaces or plug in a screen, a Space that still shows another wallpaper
gets the current one (turn off **Keep Wallpaper on Every Space** to leave other Spaces
alone).

**The menu** shows the active theme and its wallpaper, and offers:

- Next Wallpaper, Pin / Unpin, Find Wallpapers… (the gallery) and Library…. The app
  starts `mood-engine serve` on first use and stops it when it quits.
- Dark Theme / Light Theme submenus that set the global theme for that variant (as
  `mood-engine use` does) and Switch to Light/Dark Mode. Switching the appearance goes
  through System Events, so macOS asks once for Automation permission. Because the app
  is ad-hoc signed, it may ask again after a rebuild.
- Hooks: the last run with ✓/✗ per hook (click one for its output), Run Hooks Now and
  Edit hooks.toml….
- Re-apply Wallpaper, Open at Login, Quit.

The menu bar icon turns into a warning triangle when a hook failed or a sync hit an
error; the menu has the details. The app runs hooks with your login shell's `PATH`, so
Homebrew and `~/.local/bin` tools are found.

## Hooks

Hooks keep apps that don't read the theme index, or don't reload it on their own, in
line. A hook renders a template into the app's theme file, runs a command (a reload
signal, a widget refresh, a restart), or both: render first, then run. Hooks run when
what they depend on changes: a different active theme, an edited scheme, or an edit to
the hook or its template.

**Where they live:** `~/.config/mood-engine/` (`$MOOD_ENGINE_CONFIG_DIR`, or
`$XDG_CONFIG_HOME/mood-engine`):

```
~/.config/mood-engine/
  hooks.toml          the hooks
  templates/          your own templates (paths are relative to hooks.toml)
```

Both can come from a dotfiles repo with GNU stow (e.g. a `mood-engine` package holding
`.config/mood-engine/hooks.toml` and `.config/mood-engine/templates/…`). The menu bar app
watches the real files the symlinks point to, so editing them in the repo counts.
`mood-engine hooks --init` writes a commented example `hooks.toml` if there is none:
[`templates/hooks.example.toml`](../src/mood_engine/templates/hooks.example.toml), which
documents every key.

### Hook keys

| Key        | Meaning |
|------------|---------|
| `name`     | Shown in the menu and `mood-engine hooks`; must be unique. |
| `preset`   | Start from a ready-made hook. Any other key overrides the preset's. |
| `template` | Template file relative to `hooks.toml`, or `builtin:NAME`. |
| `output`   | Where the rendered file goes (`~` allowed; relative = the config folder). Written atomically, and only when its content changes. |
| `fade`     | Milliseconds. Step the output through in-between themes before the final file, for apps that reload the file by themselves. Needs `template`. |
| `terminal` | `"ghostty"`: after writing `output`, glide its open terminals from the previous theme, then make it reload. Uses `fade` (default 400). |
| `notify`   | Darwin notification name to post after every write, fade steps included, and once at the end even when nothing changed. Needs `template`. |
| `after`    | A hook name, or a list of them, defined above this one: wait for those to finish first. |
| `run`      | Shell command (`/bin/sh -c`), run after the output is written. |
| `timeout`  | Seconds, default 30; the command and everything it started is killed. |
| `enabled`  | Default true. |

All hooks start at the same time, so fades glide together and a slow hook doesn't hold up
the rest. When a hook needs another one's result, `after = "Name"` (or a list) makes it
wait; the named hooks must be defined above it. A failing hook doesn't stop the others;
its exit code and the end of its output are kept in `sync.json` and shown in the menu bar
app. A hook runs once per change, even if it failed, so a broken one isn't retried in a
loop; fix it and it runs again. Hooks must not call `mood-engine use` or `mood-engine sync`
(such calls are skipped).

### Templates

Templates use the [tinted-theming](https://github.com/tinted-theming/home) builder
variables, so existing base16/base24 templates for many apps work unchanged:
`{{scheme-name}}`, `{{scheme-slug}}`, `{{scheme-variant}}`, `{{base08-hex}}`,
`{{base08-rgb-r}}`, `{{base08-dec-r}}`, `{{base08-hex-bgr}}`, … for `base00`–`base17`.
The theme's roles come with the same suffixes: `{{role-bg-hex}}`, `{{role-accent-rgb-r}}`,
and so on. Sections work on `scheme-is-dark-variant` / `scheme-is-light-variant`
(`{{#…}}…{{/…}}`, inverted `{{^…}}`). Unknown variables are an error, so a typo never
writes a broken theme file; the hook fails and the old output stays.

```bash
mood-engine render templates/alacritty.toml        # preview with the active theme
mood-engine render builtin:zed.json solarized-light -o /tmp/x.json
mood-engine render --vars                           # every variable and its value
```

Built-in templates live in [`src/mood_engine/templates/`](../src/mood_engine/templates)
and are used where they are, not copied: when mood-engine improves one, the next sync
re-renders it (the template's text is part of the hook's fingerprint). Any hook can use
one with `template = "builtin:NAME"`. To customise one, `mood-engine hooks --eject zed`
(or `--eject builtin:zed.json`) copies it into `templates/` and prints the `template = …`
line to put in the hook instead; it never overwrites a file.

### Presets

Presets are ready-made hooks. Each names a built-in template, where its output goes and
what to run; any key next to `preset` overrides the preset's:

```toml
[[hook]]
preset = "ghostty"   # then `theme = mood-engine` in Ghostty's config

[[hook]]
preset = "zed"       # then "theme": "mood-engine" in Zed's settings
fade = 1200          # slower than the preset's 800 ms
```

| Preset    | Template              | Output                                   | Then |
|-----------|-----------------------|------------------------------------------|------|
| `ghostty` | `builtin:ghostty`     | `~/.config/ghostty/themes/mood-engine`   | `theme = mood-engine`; `terminal = "ghostty"`, `fade = 400` |
| `zed`     | `builtin:zed.json`    | `~/.config/zed/themes/mood-engine.json`  | `"theme": "mood-engine"`; `fade = 800` |
| `css`     | `builtin:colors.css`  | `~/.cache/mood-engine/colors.css`        | import or link the file |
| `json`    | `builtin:theme.json`  | `~/.cache/mood-engine/theme.json`        | listen for `local.mood-engine.theme`; `fade = 800` |

`mood-engine hooks --presets` prints each preset's keys and the line the app's own config
needs.

### Commands and their environment

Commands run with `/bin/sh -c` and get:

`MOOD_THEME`, `MOOD_THEME_NAME`, `MOOD_VARIANT` (`dark`|`light`), `MOOD_PREVIOUS_THEME`,
`MOOD_APPEARANCE` (macOS: `dark`|`light`), `MOOD_WALLPAPER` (path or empty),
`MOOD_OUTPUT` (the rendered file), `MOOD_OUTPUT_CHANGED` (`1`/`0`), `MOOD_ENGINE` (the
path of this mood-engine, since the menu bar app's `PATH` may not have it), `THEMES_DIR`
and `THEMES_STATE_DIR`. `MOOD_PREVIOUS_THEME` is empty unless the active theme changed.

### Fades

**File fade (`fade = 800`).** When the active theme changes, the hook first writes
in-between themes to the output, about every 110 ms, then the final file. The in-between
themes mix every palette slot and role of the previous and the new theme in OKLab, eased
in and out, so any template works unchanged. The variant flips halfway, so an app's
dark/light window chrome switches once. Without a previous theme (the first sync, an
edited scheme or template, `hooks --run`) or when the file already shows the new theme,
it writes the final file straight away.

Zed re-reads a changed theme file at most about 10 times a second; faster changes are
merged (measured with Zed 1.28: 40 writes 16 ms apart gave 7 reloads, 10 writes 100 ms
apart gave 9). So a Zed fade is a glide in about 8 steps rather than Ghostty's 60 frames
a second. A longer `fade` gives more steps; each step redraws every Zed window.

**Terminal fade (`terminal = "ghostty"`).** The hook writes the theme file, then glides
every open Ghostty terminal from the previous theme to the new one, in `fade` ms (400 by
default), and leaves Ghostty on the reloaded file. It runs inside mood-engine, which
saves the 0.2 s it takes to start another one. `mood-engine fade` does the same from the
command line, or from your own hook's `run = '"$MOOD_ENGINE" fade'`:

1. It writes the old theme's colours to each terminal's tty as OSC colour sequences
   (ANSI 0–15, foreground, background, cursor), as a program in the terminal could.
2. It steps those colours to the new theme's in OKLab, eased in and out, about 60 times
   a second.
3. It sends Ghostty `SIGUSR2`. Ghostty reloads the config, which now names the new
   theme, but colours set by OSC win over the config, so nothing changes on screen.
   Ghostty's light/dark report (mode 2031) is sent now, after the glide, so an app that
   re-queries the terminal background on that report already sees the new colours.
4. It drops the OSC colours again (OSC 104/110/111/112). What's left is the reloaded
   config, which by then shows the same colours.

With no previous theme (the first sync, an edited scheme, `hooks --run`), it only
reloads. It finds the terminals as the ttys of the processes Ghostty started, so it needs
no permissions. It only *sets* colours and never asks the terminal for any, because the
answer would arrive in the shell as typed input. `--dry-run` lists the terminals it would
touch. `--from`/`THEME` override the two themes, so `mood-engine fade solarized-light
--from firebox` previews a switch without changing anything else (Ghostty reloads, but
its theme file is unchanged).

Ghostty caveats:

- The in-between colours come from the mapping built into mood-engine (black is
  `base01`, bright colours are base24's `base12`–`base17`). If you change the template's
  mapping, the fade ends with a small step to your template's colours.
- Programs that set the terminal's colours themselves lose those at step 4. Programs
  that draw in true colour, like Neovim with `termguicolors`, keep their own colours and
  don't fade.
- On a dark/light flip, the fade starts once the menu bar app has noticed the flip and
  run the hooks, a moment after the rest of macOS has switched.
- For another terminal that understands OSC 4/10/11/12 (kitty, WezTerm, iTerm2),
  `fade --app NAME --no-reload` glides its terminals and leaves the new colours set, but
  it can't make that app reload its own config.

**Notification fade (`notify = "NAME"`).** Any hook with a `template` can post a Darwin
notification after each write, fade steps included. The `json` preset does this with
`local.mood-engine.theme`, so a listener that just applies the colours it reads glides
along with Ghostty and Zed. The final write always posts, even when the file didn't
change, so `mood-engine hooks --run "Theme JSON"` nudges a listener that started late.

## App support

The apps on this machine fall into five practical integration shapes. Pick by how the
app notices a theme change, not by what kind of app it is.

| # | The app's behaviour | What mood-engine does | Tested with |
|---|---------------------|-----------------------|-------------|
| 1 | Watches a theme file and reloads it | Render the file; optional `fade` steps it through in-between themes | Zed |
| 2 | Reloads on a signal, and the terminal understands OSC colours | Render the file, glide the ttys, then send the reload signal | Ghostty |
| 3 | Reads the theme index itself (and polls) | Nothing, or a command that triggers an immediate refresh | SketchyBar, Übersicht Dailies |
| 4 | Needs a command to re-read its theme | Render the file, then run an AppleScript/CLI reload command | Übersicht fs-health, job-overview |
| 5 | Can't read the theme index (native app, sandbox, browser) | Render JSON or CSS, post a Darwin notification, or stream it through a bridge | Firefox + Sidebery |

The first four are hooks. The fifth is the push channel: a file plus a notification, or a
small native host. A native app can read `~/.cache/mood-engine/theme.json` at start and
on every post; a browser needs an extension because web pages can't read files. The
`css` preset is the same idea for web UI: roles exposed as `--theme-*` custom properties.

### Tested apps

These are the integrations configured and tested here: `hooks.toml`, the Übersicht
widgets, and the Firefox companion.

| App | Shape | How it is wired |
|-----|-------|-----------------|
| **Ghostty** | 2 | `preset = "ghostty"`; `theme = mood-engine` in Ghostty's config. Open terminals glide with OSC colours, then reload. |
| **Zed** | 1 | `preset = "zed"`; `"theme": "mood-engine"` in Zed's settings. Zed re-reads `~/.config/zed/themes/mood-engine.json` by itself. |
| **SketchyBar** | 3 | Reads `~/.config/themes` with the reader protocol; the hook runs `sketchybar --trigger theme_changed`, and the bar glides its colours over 0.5 s. It also polls, so the trigger only makes the switch instant. |
| **Übersicht: fs-health** | 4 | Reads the theme index in its `command`; the hook runs `osascript … reload widget id "fs-health-widget-index-jsx"`. Reloading one widget keeps its DOM and state, so CSS transitions glide. |
| **Übersicht: job-overview** | 4 | Same shape: reads the theme index; the hook reloads `job-overview-widget-index-jsx`. Its job-server socket is torn down and reopened on reload, which is harmless. |
| **Übersicht: Dailies** | 3 | Reads the theme index every 5 s (`refreshFrequency = 5000`), so it needs no hook. |
| **Firefox + Sidebery** | 5 | `preset = "json"` writes `theme.json`; the `mood-engine-firefox` native host streams it to a WebExtension, which calls `browser.theme.update()`. Sidebery's "Firefox theme" colour scheme follows `browser.theme.onUpdated`. |
| **mood-engine menu bar app** | — | The companion app in this repository; watches the files and runs `sync`. |

### Ghostty

```toml
[[hook]]
preset = "ghostty"
# stands for: template = "builtin:ghostty", output = "~/.config/ghostty/themes/mood-engine",
#             terminal = "ghostty", fade = 400
```

```
# ~/.config/ghostty/config
theme = mood-engine
```

Use a single `theme = mood-engine`, not Ghostty's `light:…,dark:…` form: mood-engine
already follows the macOS appearance, and with one file every switch, including a
dark/light flip, goes through the fade.

### Zed

```toml
[[hook]]
preset = "zed"
# stands for: template = "builtin:zed.json",
#             output = "~/.config/zed/themes/mood-engine.json", fade = 800
```

```jsonc
// ~/.config/zed/settings.json
"theme": "mood-engine",
```

The template fills all 142 colours of Zed's theme schema (v0.2.0) from the theme's
roles; syntax colours follow the base16 styling guide, and Zed's terminal gets the same
ANSI colours as Ghostty. As with Ghostty, use the single theme rather than Zed's
`{"mode": "system", …}` form, so a dark/light flip goes through mood-engine and fades.

### SketchyBar

SketchyBar reads the theme index itself, following the reader protocol. The bar's
`lib/theme.sh` resolves the active theme to shell variables, and its theme follower
replays every painted colour in one animated call. The hook is only a nudge:

```toml
[[hook]]
name = "sketchybar"
run = "/opt/homebrew/bin/sketchybar --trigger theme_changed"
timeout = 5
```

Without the trigger, the bar picks up a theme on its next poll. With it, the switch is
instant and glides over about 0.5 s.

### Übersicht

Übersicht widgets are web views. They can read the theme index in their `command` and
put the colours into their own CSS variables. Two patterns work:

- **Poll every few seconds.** Dailies re-reads the theme every 5 s and needs no hook.
- **Reload one widget.** fs-health and job-overview read the theme on every refresh, but
  the hook makes them reload at once:

```toml
[[hook]]
name = "fs-health widget"
run = "osascript -e 'tell application id \"tracesOf.Uebersicht\" to reload widget id \"fs-health-widget-index-jsx\"'"
timeout = 10
```

The widget id is the widget's path with `/` and `.` turned into `-`. Avoid the global
`refresh`: it reloads the whole page, loses widget state and can leave the webview blank.
Keep the theme in its own `<style>` and the static CSS transitions in another, so a new
theme fades in instead of jumping. A half-written scheme keeps the last good theme.

### Firefox and Sidebery

Firefox has no external API for chrome colours, but a WebExtension with the `theme`
permission can call `browser.theme.update()`. The companion `mood-engine-firefox`
repository provides:

- a native messaging host that watches `~/.cache/mood-engine/theme.json` (the `json`
  preset) with `kqueue()` on macOS, falling back to a 40 ms poll elsewhere;
- an extension that maps mood-engine's roles to Firefox theme keys and calls
  `browser.theme.update()` on every frame;
- a `sign.sh` for an unlisted AMO signature, so the add-on survives a Firefox restart.

Sidebery needs no extra channel: set **Settings → Appearance → Color scheme → Firefox
theme** (its default). It reads the applied theme through `browser.theme.onUpdated`, so
the browser chrome and the sidebar move together. The role mapping and signing details
live in that repository's README.

The `json` preset is required:

```toml
[[hook]]
preset = "json"
```

### Native apps and tweaks

The `json` preset hands the active theme to anything that can read a file: a native
tweak, a Swift app, Hammerspoon, a shell script with `jq`. The file holds the theme's id,
its variant, every role and `base00`–`base17` as `#rrggbb`:

```json
{"id": "gruvbox-dark-hard", "variant": "dark",
 "roles": {"bg": "#1d2021", "accent": "#83a598", …}, "palette": {"base00": "#1d2021", …}}
```

After every write, the hook posts the Darwin notification `local.mood-engine.theme`
(`notify_post(3)`). Any process can listen, sandboxed ones too, and a post nobody listens
to costs nothing. With `fade`, the file steps through in-between themes like Zed's, with
a post after each step, so a listener that applies the colours it reads glides along.
Watch it from a shell:

```bash
while notifyutil -1 local.mood-engine.theme; do jq -c .roles.bg ~/.cache/mood-engine/theme.json; done
```

In Objective-C (a menu bar app or other native process), read the file once at start and
again on every post:

```objc
#import <notify.h>

static void MoodApply(void) {
    NSString *path = [@"~/.cache/mood-engine/theme.json" stringByExpandingTildeInPath];
    NSData *data = [NSData dataWithContentsOfFile:path];
    NSDictionary *theme = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    NSString *bg = theme[@"roles"][@"bg"];   // "#1d2021"
    if (bg) { /* turn it into an NSColor and apply it */ }
}

int token;
MoodApply();
notify_register_dispatch("local.mood-engine.theme", &token, dispatch_get_main_queue(),
                         ^(int t) { MoodApply(); });
```

A sandboxed process can receive the notification but not read `~/.cache`. Point `output`
somewhere it can read, or have it read through a helper. The theme's name is left out of
the JSON because templates don't escape quotes.

### CSS variables

The `css` preset renders the theme's roles as custom properties for a web page, an
Electron/Tauri app or an Übersicht widget:

```css
:root {
  color-scheme: dark;
  --theme-bg: #1d2021;
  --theme-surface: #3c3836;
  --theme-fg: #d5c4a1;
  --theme-accent: #83a598;
  /* … */
}
```

Point `output` at a file the page can import or link. Set `color-scheme` from the
variant, and style only with the variables, so switching the theme is one changed
stylesheet. CSS transitions on those properties give a fade where the engine supports it.

## Adding another app

1. **Classify it.** Does it watch a file, need a signal, read the theme index itself, or
   need a command? Use the table in [App support](#app-support).
2. **Build the template.** Start from a built-in one or a tinted-theming template. Use
   roles for semantic UI, palette slots only for ANSI colours, syntax or charts. Preview
   it with `mood-engine render`, including a light theme.
3. **Add the hook.** A file-watching app needs `template` + `output` and possibly `fade`.
   A signal app needs the same plus `run` (or `terminal`). A theme-index reader needs no
   output, only an optional `run` trigger.
4. **Test both directions.** Run `mood-engine hooks --run NAME`, switch to another theme
   and back, then flip the macOS appearance. Check `mood-engine status` and the menu bar
   app for failures. For a fade, use `mood-engine fade --dry-run` first.
5. **Document the app's own config.** The preset's `app_config` line is what users must
   put in the app (a theme name, a settings key, a widget id). Add it to the tested table
   when it is verified on a real machine.

Good candidates that fit an existing shape: Alacritty reloads a config file on change
(shape 1), and kitty/WezTerm/iTerm2 understand the OSC colour sequences but need
`fade --app NAME --no-reload` (shape 2, without the reload). They are not wired in this
repository today.

## The themes Claude skill

The app-side protocol is documented in the `themes` Claude skill
(`~/.claude/skills/themes/SKILL.md`), kept with the theme index in the dotfiles `themes`
package (`dotfiles/themes/.claude/skills/themes/SKILL.md`). It covers the reader
algorithm, the role contract, live reload, fades, and platform notes for Swift/AppKit,
web/CSS, Übersicht and TUIs.

That skill has been used to implement mood-engine support in apps. It is the starting
point for a new integration: follow it for the app-side reader, then add a hook here for
the push side.

## Wallpaper sources and environment

These keys are only for wallpaper discovery; theming reads the theme index and needs no
network.

| Source    | Key                    | Needed? | Notes |
|-----------|------------------------|---------|-------|
| Wallhaven | `WALLHAVEN_API_KEY`    | no      | SFW search works without a key. 45 requests/min. |
| Unsplash  | `UNSPLASH_ACCESS_KEY`  | yes     | Create an app at <https://unsplash.com/oauth/applications>. Use the *Access Key* (not the secret). Demo apps get 50 requests/hour. |
| Pexels    | `PEXELS_API_KEY`       | yes     | <https://www.pexels.com/api/new/>. 200 requests/hour. |

Keys are read only from the environment and are never written to disk or put in URLs.
API responses are cached by URL, without auth headers, for an hour. Sources without a
key are skipped with a warning. For example, in `~/.zshenv` or a direnv `.envrc`:

```bash
export UNSPLASH_ACCESS_KEY=...
export PEXELS_API_KEY=...
```

Other environment variables:

- `WALLHAVEN_CATEGORIES`: Wallhaven category bitmask, general/anime/people.
  The default is `100` (general only). Use `111` for all three.
- `THEMES_DIR`, `XDG_CONFIG_HOME`, `THEMES_STATE_DIR` and `XDG_STATE_HOME` work as in
  the theme-index reader protocol.
- `XDG_CACHE_HOME`: the API cache and the `css`/`json` preset outputs live in
  `$XDG_CACHE_HOME/mood-engine`, or `~/.cache/mood-engine` when it is unset.
- `MOOD_ENGINE_CONFIG_DIR`: hooks and templates. Otherwise
  `$XDG_CONFIG_HOME/mood-engine` or `~/.config/mood-engine`.
- `MOOD_ENGINE_DATA_DIR`, `MOOD_ENGINE_STATE_DIR`: the wallpaper library and its state.
  Otherwise `$XDG_DATA_HOME/mood-engine` / `$XDG_STATE_HOME/mood-engine`.

## Wallpapers: gallery and library

**Save** on a gallery card downloads the full image into your library and pairs it with
the theme you are browsing. Save the same image while browsing another theme to pair it
there too; it isn't downloaded again. After saving, **Set as wallpaper** sets it right
away. The **Library** tab shows what is saved for a theme:

- **Set as wallpaper** sets it now and marks it as today's wallpaper for the theme.
- **Pin** fixes this wallpaper for the theme. Without a pin, the theme rotates: each day
  a random saved wallpaper is drawn, never the same one twice in a row.
- **Remove** unpairs it from the theme. The file is deleted once no theme uses it.

`mood-engine apply [THEME]` sets the wallpaper for a theme (by default the active one)
from the library: the pin if there is one, otherwise today's pick, drawing a new one when
the day has changed.

- `--next` draws a new random wallpaper now (ignored while one is pinned).
- `--print` prints the file's path instead of setting it, for other wallpaper setters.
- `--dry-run` shows the choice and changes nothing.
- `mood-engine library` lists what is saved, pinned and current per theme.
- `mood-engine pin [THEME]` pins the theme's current wallpaper (`--key` picks another
  saved one); `mood-engine unpin [THEME]` goes back to daily rotation.

The [menu bar app](#menu-bar-app) re-applies the wallpaper when macOS flips between dark
and light on its own, when another app writes `current.json`, and when the day changes.
Without it, run `mood-engine sync` after such a change.

**Setting the wallpaper (macOS).** mood-engine calls `NSWorkspace.setDesktopImageURL` for
every screen through `osascript`'s JavaScript ObjC bridge, so it needs no extra Python
packages and no Automation permission. macOS only changes the *current* Space of each
screen. Other Spaces keep their wallpaper until you apply again while they are active.
Other platforms aren't supported yet; use `mood-engine apply --print` with your own
setter.

**Where things live.** Nothing is written to the theme index.

```
~/.local/share/mood-engine/wallpapers/<source>-<id>.<ext>   saved images
~/.local/share/mood-engine/thumbs/<source>-<id>.jpg          previews for the Library tab
~/.local/state/mood-engine/library.json                     pairings, pins, current pick
~/.local/state/mood-engine/sync.json                        last sync and hook results
```

`MOOD_ENGINE_DATA_DIR` and `MOOD_ENGINE_STATE_DIR` override the two directories;
otherwise `XDG_DATA_HOME` and `XDG_STATE_HOME` are honoured. `library.json` is meant to
be read by other programs too. Its format and locking rules (an exclusive `flock` on
`library.lock` for every write, then an atomic rename) are documented at the top of
`src/mood_engine/library.py`.

**The local server** listens on 127.0.0.1 only. It refuses requests whose `Host` header
isn't local, and only accepts actions as same-origin JSON `POST`s, so other websites
can't save or delete files through it. It serves only files that are in the library.

## How wallpapers are ranked

1. **Key colours.** mood-engine takes the theme's `bg` role and its `accent` role, then
   adds the most saturated `base08`–`base0F` slots whose hues are distinct, up to
   `--colors`.
2. **Colour vocabularies.** Each key colour is translated per API:
   - Wallhaven: snapped to its fixed list of 29 hex colours by nearest OKLab distance,
     with chroma weighted up so the hue wins.
   - Unsplash: mapped to a named colour (`black`, `white`, `black_and_white`, or the
     nearest OKLCH hue among red, orange, yellow, green, teal, blue, purple and
     magenta).
   - Pexels: the hex value is passed through unchanged.

   The background query fetches 3× as many pages, because it decides most of the score.
   Wallhaven's colour filter only means "this colour appears somewhere", and its toplist
   is mostly dark: `colors=ffffff` returned 2 light images out of 24. So for **light
   themes**, when you give no keywords, the Wallhaven background query also runs with
   the keywords `white background` and `minimalism` (20/24 and 12/24 light in the same
   test). The gallery and terminal output list these keywords next to the colour
   filters. The list is `pipeline.BG_HINTS`.
3. **Palette extraction.** Each thumbnail is downsampled to 96 px and converted to
   OKLab, then clustered with k-means (k = 8, k-means++ seeding, deterministic). Each
   cluster's weight is its share of the image area.
4. **Score** (0–100) = 40 % background + 40 % palette + 20 % (1 − penalty):
   - **Background fit** has two halves. The area-weighted median lightness must fall in
     the lightness band of the theme's background roles (`bg`, `bg-inset`, `surface`,
     `surface-raised`, so `base00`–`base02` plus overrides); outside the band, the score
     falls off as a Gaussian. Enough of the image's area must also sit close to one of
     those colours; the distance for this check counts tint (a/b) double, so a navy
     background doesn't pass as a warm near-black.
   - **Palette fit** = exp(−d / 0.06), where d is the area-weighted mean OKLab distance
     from each cluster to the nearest colour in the scheme (all 24 slots plus resolved
     roles).
   - **Off-hue penalty**: the share of area in saturated clusters (chroma > 0.05, counted
     fully from 0.15) whose hue is more than 20° away from every chromatic scheme
     colour. Reaching full penalty takes 40° beyond that tolerance, and the penalty is
     maxed out at 30 % of the area. A bright blue sky against a warm dark theme is the
     typical case.

   All the constants are in `score.Weights`.

   Re-uploads of the same image at another resolution are dropped, keeping the
   better-ranked copy. Two images count as the same when every cell of their 16×9 OKLab
   grids is within 0.05.
5. **Gallery.** The gallery is styled with the theme's roles as `--theme-*` CSS
   variables. Each card shows the score, a breakdown, the extracted palette strip, the
   resolution, the colour filter that found the image, attribution and links.

## API terms and recolouring

- **Unsplash:** images are hotlinked from the returned `urls`. Every card says
  "Photo by *name* on Unsplash", with links that carry
  `utm_source=mood-engine&utm_medium=referral`. **Save** and **Recolor** call the
  photo's `download_location` endpoint before fetching the file, as the API guidelines
  require. The static `--html` output can't do that, so there Download links to the photo
  page on Unsplash instead. Saved Unsplash images keep their photographer credit in the
  Library tab.
- **Pexels:** each card credits the photographer and links to Pexels.
- **Wallhaven:** only SFW results are requested, and each card links to the wallpaper's
  page. Wallhaven images come from many uploaders with mixed licences, so check the
  source before redistributing one.
- Results are cached so the hourly limits on demo keys last. One `serve` page costs at
  most about 6 requests per source with the defaults.

**Recolor** on a card (server mode) downloads the full image and nudges it toward the
theme. Every pixel is pulled toward a Gaussian-weighted blend of nearby scheme colours
in OKLab: chroma at 75 %, lightness at 35 %. The output is capped at 2560 px. It is a
small built-in take on what [lutgen](https://github.com/ozwaldorf/lutgen-rs) does. On an
Unsplash image it counts as a download and triggers `download_location`. In one test it
raised a green forest photo from 77 to 85 for Firebox. lutgen and gowall aren't wired in.

## Development

```bash
uv run pytest -q
```

The tests use synthetic striped images and embedded copies of the Firebox and Solarized
Light schemes, so they don't need `~/.config/themes` or network access. They cover:

- OKLab reference values and round-trips, area weights from k-means, dark/light
  background preference, tint sensitivity, the off-hue penalty, vocabulary snapping
- query planning (light-theme background keywords; none for dark themes or when you give
  keywords), duplicate removal, and the `mood-engine THEME` shortcut
- the reader protocol, including `current.json` precedence and the embedded fallback
- Unsplash and Pexels parsing with mocked responses, attribution, recolouring
- the library: storage, rejecting non-images, daily rotation, pins, unpairing and file
  deletion, and `apply` / `library` (desktop calls mocked)
- `use`: merging into `current.json`, other-variant themes, `--appearance`, symlinked
  `current.json`
- the server's save, pair, apply, pin and remove routes against a real local server,
  including the Unsplash download ping and refusing foreign hosts and origins
- `sync`: first sync, no-op, appearance flips, daily rotation without hooks,
  `current.json` written by another app, `use` running hooks exactly once, and the
  wallpaper delay
- hooks: environment, failures and timeouts (process group killed), disabled hooks, a
  broken `hooks.toml`, nested calls from a hook; `pin`/`unpin` and `status`
- templates: tinted-theming variables and roles, sections, errors for unknown variables;
  rendering before the command, writing only on change, symlinked outputs; per-hook
  fingerprints; `render` and `hooks --run NAME`
- hooks at the same time, `after` ordering, Ghostty terminal discovery and the fade on a
  pseudo-terminal, Zed's theme template and stepped fade, and every preset's template

The menu bar app has no automated tests; build it with `./macos/build.sh`.

## Known limits

- Results depend on what the APIs return for a colour filter. Wallhaven's filter only
  requires the colour to appear somewhere in the image, so the ranking does the real
  work. Use `--pages` to widen the pool.
- Duplicate detection only catches rescaled copies. A re-crop of the same art shifts
  every cell and shows up twice.
- Thumbnails are about 200–300 px wide, which is fine for palettes but not for fine
  detail.
- An earth mover's distance between the image and scheme palettes would reward coverage
  of the accent colours. The current nearest-colour distance doesn't.
- The Unsplash `color`/`blur_hash` and Pexels `avg_color` fields could pre-filter results
  before any thumbnail is downloaded.
- Wallpaper setting is macOS-only and changes the current Space; other Spaces keep their
  wallpaper until you apply again while they are active.
- Firefox needs the companion bridge and a signed (or temporary) add-on. Without signing,
  the extension disappears when Firefox exits.
- The menu bar app is ad-hoc signed, so macOS may ask for Automation permission again
  after a rebuild.
