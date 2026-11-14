# Development notes

State as of 2026-11-14, and what's next.

## Where things stand

- `main` is in sync with `origin/main`.
- Recently landed: the README and `docs/GUIDE.md` were rewritten around the theming-first
  scope, with the tested app integrations; the Ghostty fade now reloads *after* the
  glide; the menu bar app holds the wallpaper back for a second after a dark/light flip
  (`sync --wallpaper-delay`), so macOS can finish redrawing first.
- 132 tests pass (`uv run pytest -q`).
- The fade order is deliberate: Ghostty emits its mode-2031 light/dark report on reload,
  and apps such as omp re-query the terminal background when they see it. Reloading
  before the glide made them cache the pinned old colours (white-on-white in omp);
  reload after the glide, then drop the pins, so the report sees the new colours.
- The dotfiles repo still has the new `mood-engine/` and `themes/` stow packages
  uncommitted.
- Hand-test pending: how a real dark/light flip feels with the ~250 ms hold at the end
  of the fade (0.4 s glide + 0.25 s hold).

## Next: moods over the day (slow theme changes)

The chosen next feature: a schedule such as morning → day → golden hour → night, tied
to clock times or sunrise and sunset, with the desktop *drifting* between themes over
20–40 minutes instead of switching.

What exists already:

- `themes.blend(a, b, x)` mixes two themes in OKLab: palette and roles, with the
  variant flipping at x ≥ 0.5.
- Hooks with `fade` already step apps through in-between themes: Zed writes file
  frames, and Ghostty uses `terminal.fade()` with OSC sequences. The Ghostty fade now
  reloads after the glide, then drops the pins, so a mode-2031-aware app sees the new
  terminal colours when it handles the reload's light/dark report.
- The menu bar app has a timer and day-change handling to hang this on.

Open design questions:

- **Schedule format.** Probably a `[[mood]]` list in a config file: a theme id plus a
  start time, `sunrise±N`/`sunset±N`, and a transition length. Sun times need a location
  (manual lat/lon, or CoreLocation in the Swift app).
- **How it fits with dark/light.** Does the schedule replace defaults.json and the
  system appearance, or only pick among themes of the current variant? Should a
  transition flip macOS appearance halfway?
- **What "the active theme" is mid-transition.** A blended theme needs an id/name that
  hooks, `status`, the gallery and current.json can carry, e.g. `blend:a:b:0.37`, or a
  generated scheme written to the state dir.
- **Pace.** Push a new blended theme every few seconds (or on each 1–2 % step), not at
  60 fps. Zed: a file write per step is fine at that rate. Ghostty already uses the
  right shape: set the OSC colours per step, then reload once at the end. Hooks without
  `fade` (e.g. Übersicht reloads) probably run only at the end points, or need an
  opt-in.
- **The wallpaper.** Switch it once, at the midpoint or at the end. macOS can't
  crossfade it slowly.
- **Interruptions.** `mood-engine use X` or a manual menu pick during a transition
  should cancel it. Sleep and wake should jump to the correct point.

## Other ideas, roughly in order

1. **A library that fills itself.** A background job searches each theme, keeps the top
   few above a score threshold, and feeds them into the daily rotation, so a new theme
   gets wallpapers without curating. Watch the API rate limits; remember rejected
   images.
2. **Making themes, not just using them.**
   - Generate a Base24 scheme from a wallpaper you love (the reverse direction).
   - Tweak a scheme in the gallery.
   - A contrast check on the roles (fg/bg, accent/surface) that warns about hard-to-read
     schemes.
3. **Better ranking.**
   - An earth mover's distance to reward covering the accent colours.
   - Pre-filter on the Unsplash `color`/`blur_hash` and Pexels `avg_color` fields before
     downloading thumbnails.
   - Catch re-cropped duplicates.
4. **More apps, as needed.**
   - Neovim and Helix. A theme built on ANSI colours follows Ghostty's fade for free;
     a full-colour theme needs a hook per editor (Neovim `--remote-send`, Helix
     SIGUSR1).
   - Alacritty: it reloads on file change, so it could reuse the Zed file-frame fade.
   - Obsidian: a CSS snippet, with a CSS transition for the fade.
   - VS Code: `workbench.colorCustomizations`, with no fade possible.
