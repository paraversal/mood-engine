# mood-engine

Suggests **existing** wallpapers that match a Base24 theme from your global theme
index (`~/.config/themes`). It asks wallpaper and photo APIs for candidates using each
API's colour filter, scores every thumbnail in OKLab against the theme, and shows a
ranked gallery styled in that theme.

Other tools either recolour an image to a palette (lutgen, gowall) or extract a palette
from an image (pywal, wallust, matugen). mood-engine goes the other way: you give it a
palette and it finds wallpapers.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11 (uv fetches one if needed).

```bash
git clone https://github.com/paraversal/mood-engine.git
cd mood-engine
uv sync
uv run mood-engine themes                 # list themes; * = what "system" resolves to
uv run mood-engine                        # gallery for the active theme, http://127.0.0.1:8765/
uv run mood-engine firebox                # gallery for a given theme
uv run mood-engine search firebox         # ranked list in the terminal
uv run mood-engine apply                  # set a saved wallpaper for the active theme
uv run mood-engine use firebox            # switch the global theme, then its wallpaper
./macos/build.sh --install                # menu bar app (see "Menu bar app")
```

`uv tool install -e .` puts `mood-engine` on your PATH.

### Theme index

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

Palettes use the [Base24](https://github.com/tinted-theming/base24) slots, so any
scheme from the tinted-theming catalogue can be converted. Roles are the semantic
colours (`bg`, `bg-inset`, `surface`, `surface-raised`, `fg`, `accent`, `error`, …)
that the scoring and the gallery styling use. Without the directory, mood-engine
falls back to an embedded Gruvbox dark theme.

### API keys

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
- `XDG_CACHE_HOME`: the cache lives in `$XDG_CACHE_HOME/mood-engine`, or
  `~/.cache/mood-engine` when it is unset. Delete that folder to force fresh results.

## Usage

```
mood-engine [THEME] [options]           same as `mood-engine serve [THEME] [options]`
mood-engine search|serve [THEME] [-q KEYWORDS] [--sources wallhaven,unsplash,pexels]
                       [--min-res 1920x1080] [--colors 4] [--pages 1] [-k 8] [-n 40]
mood-engine search ... [--json] [--html out/gallery.html]
mood-engine serve  ... [--port 8765] [--no-open]
mood-engine apply   [THEME] [--next] [--print] [--dry-run]
mood-engine use     THEME [--appearance]
mood-engine sync    [--appearance dark|light] [--wallpaper] [--hooks] [--force] [--json]
mood-engine hooks   [--init] [--run [NAME ...]]
mood-engine render  [TEMPLATE] [THEME] [-o OUT] [--vars]
mood-engine fade    [THEME] [--from THEME] [--app ghostty] [--ms 400] [--no-reload] [--dry-run]
mood-engine pin     [THEME] [--key SOURCE:ID]
mood-engine unpin   [THEME]
mood-engine library [THEME]
mood-engine status  [--appearance dark|light]
mood-engine themes
```

- `THEME` (or `-t/--theme`) is a theme id, or `system` (the default). `system` resolves through
  `current.json` and then `defaults.json` for the current macOS appearance, then falls
  back to the first theme. If the index is missing, an embedded Gruvbox theme is used.
- `-q` adds keywords such as `mountains`, `abstract` or `minimal`. Keywords help a lot,
  especially for light themes.
- In the gallery you can switch theme, keywords, minimum resolution and sources. The
  `JSON` link returns the same ranking as data.

mood-engine never writes to `~/.config/themes`. The only file it writes in
`~/.local/state/themes` is `current.json`, and only when you run `mood-engine use` (or
pick a theme in the menu bar app).

## Switching the theme

`mood-engine use THEME` is the theme index's "apply to all apps" action:

1. It writes the theme id into `~/.local/state/themes/current.json` under the theme's
   variant (`dark` or `light`) and keeps the other key. The file is replaced atomically.
   If it is a symlink, the link's target is written.
2. If the theme is now active (its variant matches the macOS appearance), it sets the
   theme's wallpaper as `mood-engine apply` would. With nothing saved for the theme, the
   switch still happens and a note says so.
3. If the active theme changed, it runs your [hooks](#hooks-for-apps-without-live-reload).

Apps that follow the themes protocol with live reload pick up the change straight away.
Others need a hook, or pick it up the next time they start.

Switching to a theme of the other variant, e.g. `use solarized-light` while macOS is
dark, sets your light theme but changes nothing visible until macOS goes light. Pass
`--appearance` to also switch macOS to the theme's variant. That goes through System
Events, so the first time macOS asks to let your terminal control it (System Settings →
Privacy & Security → Automation).

To change only the wallpaper without touching the global theme, use
`mood-engine apply THEME`.

## Library: saving wallpapers and switching them with the theme

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

**Setting the wallpaper (macOS).** mood-engine calls
`NSWorkspace.setDesktopImageURL` for every screen through `osascript`'s JavaScript ObjC
bridge, so it needs no extra Python packages and no Automation permission. macOS only
changes the *current* Space of each screen. Other Spaces keep their wallpaper until you
apply again while they are active. Other platforms aren't supported yet; use
`mood-engine apply --print` with your own setter.

**Where things live.** Nothing is written to the theme index.

```
~/.local/share/mood-engine/wallpapers/<source>-<id>.<ext>   saved images
~/.local/share/mood-engine/thumbs/<source>-<id>.jpg          previews for the Library tab
~/.local/state/mood-engine/library.json                     pairings, pins, current pick
```

`MOOD_ENGINE_DATA_DIR` and `MOOD_ENGINE_STATE_DIR` override the two directories;
otherwise `XDG_DATA_HOME` and `XDG_STATE_HOME` are honoured. `library.json` is meant to
be read by other programs too. Its format and locking rules (an exclusive `flock` on
`library.lock` for every write, then an atomic rename) are documented at the top of
`src/mood_engine/library.py`.

**The local server** listens on 127.0.0.1 only. It refuses requests whose `Host` header
isn't local, and only accepts actions as same-origin JSON `POST`s, so other websites
can't save or delete files through it. It serves only files that are in the library.

## Keeping everything in sync

`mood-engine sync` brings the desktop in line with the active theme (what apps set to
"System" show: `current.json`, then `defaults.json`, for the macOS appearance) and
compares it with the last sync, kept in `~/.local/state/mood-engine/sync.json`:

| Since the last sync                     | Wallpaper            | Hooks            |
|-----------------------------------------|----------------------|------------------|
| active theme changed                    | set                  | all run          |
| same theme, colours edited in a scheme  | –                    | all run          |
| a hook or its template edited, or added | –                    | that hook runs   |
| same theme, new day                     | set (daily rotation) | –                |
| nothing                                 | –                    | –                |

Each hook remembers a fingerprint of what it last ran for: the theme's colours, its
own definition and its template. `--wallpaper` and `--hooks` force either one, `--force`
both. A lock serialises
concurrent syncs, so one change never runs the hooks twice, even when `mood-engine use`
and the menu bar app both notice it. `--json` prints a report; `status` prints
everything the menu bar app shows.

### Hooks: keeping other apps in line

Apps that don't read the theme index, or don't reload it on their own, are kept in
line by hooks. A hook renders a template into the app's theme file, runs a command
(a reload signal, a widget refresh, a restart), or both: render first, then run.

**Where they live:** `~/.config/mood-engine/` (`$MOOD_ENGINE_CONFIG_DIR`, or
`$XDG_CONFIG_HOME/mood-engine`):

```
~/.config/mood-engine/
  hooks.toml          the hooks, in order
  templates/          templates the hooks render (paths are relative to hooks.toml)
```

Both can come from a dotfiles repo with GNU stow (e.g. a `mood-engine` package holding
`.config/mood-engine/hooks.toml` and `.config/mood-engine/templates/…`). The menu bar app
watches the real files the symlinks point to, so editing them in the repo counts.
`mood-engine hooks --init` writes a commented `hooks.toml` and the example templates
`templates/colors.css` and `templates/ghostty`, each only if it doesn't exist yet, so
running it again on an existing setup just adds templates that are new.

```toml
[[hook]]
name = "CSS variables"
template = "templates/colors.css"           # relative to hooks.toml
output = "~/.cache/mood-engine/colors.css"  # written atomically, only when it changes

[[hook]]
name = "fs-health widget"
run = "osascript -e 'tell application id \"tracesOf.Uebersicht\" to reload widget id \"fs-health-widget-index-jsx\"'"
timeout = 10         # seconds, default 30; the command and all it started are killed after it
# enabled = false
```

For Übersicht, reload a single widget as above: it keeps the widget's DOM and state,
so CSS transitions can glide to the new colours. The global `refresh` reloads the whole
page, loses widget state, and can leave the webview blank.

**Templates** use the [tinted-theming](https://github.com/tinted-theming/home) builder
variables, so existing base16/base24 templates for many apps work unchanged:
`{{scheme-name}}`, `{{scheme-slug}}`, `{{scheme-variant}}`, `{{base08-hex}}`,
`{{base08-rgb-r}}`, `{{base08-dec-r}}`, `{{base08-hex-bgr}}`, … for `base00`–`base17`. The
theme's roles come with the same suffixes: `{{role-bg-hex}}`, `{{role-accent-rgb-r}}`,
and so on. Sections work on `scheme-is-dark-variant` / `scheme-is-light-variant`
(`{{#…}}…{{/…}}`, inverted `{{^…}}`). Unknown variables are an error, so a typo never
writes a broken theme file; the hook fails and the old output stays.

```bash
mood-engine render templates/colors.css             # preview with the active theme
mood-engine render templates/colors.css solarized-light -o /tmp/x.css
mood-engine render --vars                           # every variable and its value
```

**Commands** run with `/bin/sh -c` and get `MOOD_THEME`, `MOOD_THEME_NAME`,
`MOOD_VARIANT`, `MOOD_PREVIOUS_THEME`, `MOOD_APPEARANCE`, `MOOD_WALLPAPER`, `MOOD_OUTPUT`
(the rendered file), `MOOD_OUTPUT_CHANGED` (`1`/`0`), `MOOD_ENGINE` (the path of this
mood-engine, since the menu bar app's `PATH` may not have it), `THEMES_DIR` and
`THEMES_STATE_DIR`. `MOOD_PREVIOUS_THEME` is empty unless the active theme changed.

**Running them:** see the table above for when a sync runs hooks. `mood-engine hooks`
lists them with their last run; `mood-engine hooks --run [NAME …]` runs all or some now.
A failing hook doesn't stop the others; its exit code and the end of its output are
kept in `sync.json` and shown in the menu bar app. A hook runs once per change, even if
it failed, so a broken one isn't retried in a loop; fix it and it runs again. Hooks must
not call `mood-engine use` or `sync` (such calls are skipped).

### Ghostty, with a fade between themes

Ghostty reads its colours from a theme file and reloads its config on `SIGUSR2`, so one
hook keeps it in line. `mood-engine hooks --init` writes the template
(`templates/ghostty`); then add the hook and point Ghostty at the theme:

```toml
[[hook]]
name = "Ghostty"
template = "templates/ghostty"
output = "~/.config/ghostty/themes/mood-engine"
run = '"$MOOD_ENGINE" fade'
timeout = 10
```

```
# ~/.config/ghostty/config
theme = mood-engine
```

Use a single `theme = mood-engine`, not Ghostty's `light:…,dark:…` form: mood-engine
already follows the macOS appearance, and with one file every switch, including a
dark/light flip, goes through the fade.

`mood-engine fade` glides every open Ghostty terminal from `$MOOD_PREVIOUS_THEME` to the
new theme in 400 ms, then leaves Ghostty on the reloaded theme file:

1. It writes the old theme's colours to each terminal's tty as OSC colour sequences
   (ANSI 0–15, foreground, background, cursor), as a program in the terminal could.
2. It sends Ghostty `SIGUSR2`. Ghostty reloads the config, which now names the new
   theme, but colours set by OSC win over the config, so nothing changes on screen yet.
3. It steps those colours to the new theme's in OKLab, eased in and out, about 60
   times a second.
4. It drops the OSC colours again (OSC 104/110/111/112). What's left is the reloaded
   config, which by then shows the same colours.

With no previous theme (the first sync, an edited scheme, `hooks --run`), `fade` only
reloads. It finds the terminals as the ttys of the processes Ghostty started, so it needs
no permissions. It only *sets* colours and never asks the terminal for any, because the
answer would arrive in the shell as typed input. `--dry-run` lists the terminals it
would touch. `--from`/`THEME` override the two themes, so
`mood-engine fade solarized-light --from firebox` previews a switch without changing
anything else (Ghostty reloads, but its theme file is unchanged).

Caveats:

- The in-between colours come from the mapping built into mood-engine (black is
  `base01`, bright colours are base24's `base12`–`base17`). If you change the template's
  mapping, the fade ends with a small step to your template's colours.
- Programs that set the terminal's colours themselves lose those at step 4. Programs
  that draw in true colour, like Neovim with `termguicolors`, keep their own colours
  and don't fade.
- On a dark/light flip, the fade starts once the menu bar app has noticed the flip and
  run the hooks, a moment after the rest of macOS has switched.
- For another terminal that understands OSC 4/10/11/12 (kitty, WezTerm, iTerm2),
  `fade --app NAME --no-reload` glides its terminals and leaves the new colours set,
  but it can't make that app reload its own config.

## Menu bar app

`macos/` holds a small native menu bar app (Swift, AppKit, macOS 14+). It keeps no logic
of its own: it watches for changes and calls the CLI.

```bash
./macos/build.sh             # builds macos/build/mood-engine.app
./macos/build.sh --install   # copies it to ~/Applications and starts it
```

It needs Xcode or the Command Line Tools. The app runs the repo's
`.venv/bin/mood-engine` (path baked in at build time; run `uv sync` first), or else
`mood-engine` on your login shell's `PATH`, or one you pick from its menu. Hooks get
your login shell's `PATH` too.

**When it syncs:** on launch; when macOS switches between dark and light, including on
its own schedule; when `current.json`, `defaults.json`, a scheme, `hooks.toml` or a
template changes (watched at their real paths, so stow symlinks and edits in the
dotfiles repo count); after waking from sleep;
and when the day changes (daily rotation). When you switch Spaces or plug in a screen,
a Space that still shows another wallpaper gets the current one (turn off
**Keep Wallpaper on Every Space** to leave other Spaces alone).

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
error; the menu has the details.

## How it works

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

   Wallhaven's colour filter only means "this colour appears somewhere", and its
   toplist is mostly dark: `colors=ffffff` returned 2 light images out of 24. So for
   **light themes**, when you give no keywords, the Wallhaven background query also
   runs with the keywords `white background` and `minimalism` (20/24 and 12/24
   light in the same test). Dark themes don't need this. The gallery and terminal
   output list these keywords next to the colour filters. The list is
   `pipeline.BG_HINTS`.
3. **Palette extraction.** Each thumbnail is downsampled to 96 px and converted to
   OKLab, then clustered with k-means (k = 8, k-means++ seeding, deterministic). Each
   cluster's weight is its share of the image area.
4. **Score** (0–100) = 40 % background + 40 % palette + 20 % (1 − penalty):
   - **Background fit** has two halves:
     - The area-weighted median lightness must fall in the lightness band of the
       theme's background roles (`bg`, `bg-inset`, `surface`, `surface-raised`, so
       `base00`–`base02` plus overrides). Outside the band, the score falls off as a
       Gaussian.
     - Enough of the image's area must sit close to one of those colours. The distance
       for this check counts tint (a/b) double, so a navy background doesn't pass as
       Firebox's warm near-black.
   - **Palette fit** = exp(−d / 0.06), where d is the area-weighted mean OKLab distance
     from each cluster to the nearest colour in the scheme (all 24 slots plus resolved
     roles).
   - **Off-hue penalty**: the share of area in saturated clusters (chroma > 0.05,
     counted fully from 0.15) whose hue is more than 20° away from every chromatic
     scheme colour. Reaching full penalty takes 40° beyond that tolerance, and the
     penalty is maxed out at 30 % of the area. A bright blue sky against Firebox is the
     typical case.

   All the constants are in `score.Weights`.

   Re-uploads of the same image at another resolution are dropped, keeping the
   better-ranked copy. Two images count as the same when every cell of their 16×9
   OKLab grids is within 0.05.
5. **Gallery.** The gallery is styled with the theme's roles as `--theme-*` CSS
   variables. Each card shows the score, a breakdown, the extracted palette strip, the
   resolution, the colour filter that found the image, attribution and links.

### Respecting the APIs' terms

- **Unsplash:** images are hotlinked from the returned `urls`. Every card says
  "Photo by *name* on Unsplash", with links that carry
  `utm_source=mood-engine&utm_medium=referral`. **Save** and **Recolor** call the
  photo's `download_location` endpoint before fetching the file, as the API guidelines
  require. The static `--html` output can't do that, so there Download links to the
  photo page on Unsplash instead. Saved Unsplash images keep their photographer credit
  in the Library tab.
- **Pexels:** each card credits the photographer and links to Pexels.
- **Wallhaven:** only SFW results are requested, and each card links to the wallpaper's
  page. Wallhaven images come from many uploaders with mixed licences, so check the
  source before redistributing one.
- Results are cached so the hourly limits on demo keys last. One `serve` page costs at
  most about 6 requests per source with the defaults.

### Recolouring near misses (stretch goal)

**Recolor** on a card (server mode) downloads the full image and nudges it toward the
theme. Every pixel is pulled toward a Gaussian-weighted blend of nearby scheme colours
in OKLab: chroma at 75 %, lightness at 35 %. The output is capped at 2560 px. It is a
small built-in take on what [lutgen](https://github.com/ozwaldorf/lutgen-rs) does. On
an Unsplash image it counts as a download and triggers `download_location`. In one test
it raised a green forest photo from 77 to 85 for Firebox. lutgen and gowall aren't
wired in, because neither was installed when this was built. They would be a better
backend for this.

## Development

```bash
uv run pytest -q
```

The tests use synthetic striped images and embedded copies of the Firebox and
Solarized Light schemes, so they don't need `~/.config/themes` or network access. They
cover:

- OKLab reference values and round-trips
- area weights from k-means
- dark and light themes each preferring a matching background
- tint sensitivity
- off-hue penalty versus in-scheme hues
- vocabulary snapping
- query planning (light-theme background keywords; none for dark themes or when you
  give keywords), duplicate removal, and the `mood-engine THEME` shortcut
- the reader protocol, including `current.json` precedence and the embedded fallback
- Unsplash and Pexels parsing with mocked responses, and attribution
- recolouring raising the score
- the library: storage, rejecting non-images, daily rotation, pins, unpairing and file
  deletion, and `apply` / `library` (desktop calls mocked)
- `use`: merging into `current.json`, other-variant themes, `--appearance`, symlinked
  `current.json` (appearance and desktop calls mocked)
- the server's save, pair, apply, pin and remove routes against a real local server,
  including the Unsplash download ping and refusing foreign hosts and origins
- `sync`: first sync, no-op, appearance flips, daily rotation without hooks,
  `current.json` written by another app, `use` running hooks exactly once
- hooks: environment, failures and timeouts (process group killed), disabled hooks, a
  broken `hooks.toml`, nested calls from a hook; `pin`/`unpin` and `status`
- templates: tinted-theming variables and roles, sections, standalone tag lines, errors
  for unknown variables; rendering before the command, writing only on change,
  symlinked outputs; per-hook fingerprints (edited scheme, edited template, new or
  re-enabled hook); config validation; a stowed (symlinked) config and its watch paths;
  `render` and `hooks --run NAME`
- Ghostty: the template renders the same colours the fade uses (and its example hook
  parses), finding terminals through a root-owned `login`, and the fade on a real
  pseudo-terminal: old colours pinned before the reload, every colour ending on the new
  theme, the pins dropped last; reload only without a previous theme; `--no-reload`;
  unopenable ttys; `fade` reading the hook environment; `MOOD_ENGINE` in hooks;
  `hooks --init` adding a missing template without touching existing files. No test
  signals a real process or runs your real hooks.

The menu bar app has no automated tests; build it with `./macos/build.sh`.

## Known limits / ideas

- Results depend on what the APIs return for a colour filter. Wallhaven's filter only
  requires the colour to appear somewhere in the image, so the ranking does the real
  work. Use `--pages` to widen the pool.
- Duplicate detection only catches rescaled copies. A re-crop of the same art (one
  pair in the Solarized Light pool) shifts every cell and shows up twice.
- Thumbnails are about 200–300 px wide, which is fine for palettes but not for fine
  detail.
- An earth mover's distance between the image and scheme palettes would reward
  coverage of the accent colours. The current nearest-colour distance doesn't.
- The Unsplash `color`/`blur_hash` and Pexels `avg_color` fields could pre-filter
  results before any thumbnail is downloaded.
