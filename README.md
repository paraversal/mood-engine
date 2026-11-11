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
mood-engine library [THEME]
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
`~/.local/state/themes` is `current.json`, and only when you run `mood-engine use`.

## Switching the theme

`mood-engine use THEME` is the theme index's "apply to all apps" action:

1. It writes the theme id into `~/.local/state/themes/current.json` under the theme's
   variant (`dark` or `light`) and keeps the other key. The file is replaced atomically.
   If it is a symlink, the link's target is written.
2. If the theme is now active (its variant matches the macOS appearance), it sets the
   theme's wallpaper as `mood-engine apply` would. With nothing saved for the theme, the
   switch still happens and a note says so.

Apps that follow the themes protocol with live reload pick up the change straight away.
Others pick it up the next time they start.

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

Nothing re-applies the wallpaper when macOS flips between dark and light on its own,
or when another app writes `current.json`; that is the menu bar app's job. Until then,
run `mood-engine apply` after such a change, and on a schedule for the daily rotation,
e.g. with a LaunchAgent
(`~/Library/LaunchAgents/<label>.plist`) whose `ProgramArguments` call
`mood-engine apply` with `RunAtLoad` and a `StartCalendarInterval` of `Hour` 6.

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
