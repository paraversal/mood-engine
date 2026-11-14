---
name: themes
description: How to read the global theme index in ~/.config/themes (Base24 palettes plus a fixed set of semantic color roles) and add theming to any program — CLI, TUI, desktop app, web app or Übersicht widget — including an in-app theme picker whose choice persists. Use whenever a project needs colors, light/dark mode, or a theme setting.
---

# Global theme index

`~/.config/themes` holds the user's favourite color themes as plain JSON. Any program
gets theming by implementing the small reader protocol below. Programs **read** this
directory and never write to it. The directory is curated by hand, often in a dotfiles
repo and symlinked into place (e.g. with GNU stow). To add a theme, add a file there. See
"Adding a theme".

## Layout

This skill ships with mood-engine (`skills/themes/SKILL.md`); link it into
`~/.claude/skills/themes/` to use it. The data it describes:

```
~/.config/themes/
  roles.json        default role → palette-slot mapping (the contract)
  defaults.json     which theme to use when the app has no saved choice
  schemes/
    <id>.json       one theme per file; <id> = file name without .json

~/.local/state/themes/     ($XDG_STATE_HOME/themes; runtime state, apps may write here)
  current.json      the global "apply to all apps" selection (optional)
```

Theme data is read-only for apps. The global selection is runtime state. It lives in a
separate directory, so switching themes never touches a versioned theme directory and
never replaces a symlink.

## File formats

**`schemes/<id>.json`** contains a Base24 palette and optional role overrides:

```json
{
  "name": "Gruvbox dark, hard",
  "author": "…",
  "variant": "dark",
  "palette": { "base00": "#1d2021", "…": "…", "base17": "#d3869b" },
  "roles": { "fg-muted": "#a6adc8", "selection": "base01" }
}
```

- `variant` is `"dark"` or `"light"`.
- `palette` always has all 24 keys, `base00` to `base17`. Keys are written with an
  uppercase hex digit (`base0A`, not `base0a`). Values are lowercase `#rrggbb`.
- `roles` is optional. It overrides entries from `roles.json` for this theme only.
- A role value is either a palette slot name (`"base0D"`) or a literal hex color
  (`"#a6adc8"`). A value that starts with `#` is a literal.

**`roles.json`** maps every role to a palette slot. Its keys are the full list of roles.

**`defaults.json`** is `{ "dark": "<id>", "light": "<id>" }`. It is the baseline for
apps set to "System". It is edited by hand.

**`current.json`** (in the state dir) has the same shape as `defaults.json`, and
either key may be missing. It is the global selection, which overrides `defaults.json`
for apps set to "System". It may not exist. Apps write it only from an explicit "apply
to all apps" action, and always atomically: write a temp file, then rename it over the
target.

## The role contract

Apps style themselves with **roles**, never with raw `baseXX` slots. Base24 slots
mean different things in different schemes. For example, Tokyo Night's `base08` is
not red. Roles are curated per theme so they always mean the same thing.

| Role             | Default | Use for                                                    |
|------------------|---------|------------------------------------------------------------|
| `bg`             | base00  | window / page background                                   |
| `bg-inset`       | base10  | wells, sidebars, code blocks (may equal `bg`)              |
| `surface`        | base01  | cards, panels, status bars, inputs                         |
| `surface-raised` | base02  | popovers, menus, hovered rows                              |
| `border`         | base02  | dividers, outlines                                         |
| `selection`      | base02  | selected text / selected row background                    |
| `fg`             | base05  | body text                                                  |
| `fg-muted`       | base04  | secondary text, labels                                     |
| `fg-subtle`      | base03  | placeholders, disabled text, comments (not for body copy)  |
| `accent`         | base0D  | primary buttons, focus rings, active indicators            |
| `on-accent`      | base00  | text and icons drawn on an `accent` fill                   |
| `link`           | base0D  | hyperlinks                                                 |
| `info`           | base0C  | informational status                                       |
| `success`        | base0B  | success status                                             |
| `warning`        | base0A  | warning status                                             |
| `error`          | base08  | errors, destructive actions                                |

Rules for apps:

- **Derive states; don't store them.** Compute hover, pressed and disabled colors
  and transparency from roles in the app, ideally in OKLCH. For example, hover = the
  role's color with lightness ±0.05; disabled = 40% alpha. Themes stay at 24 colors.
- **Tolerate change.** Ignore unknown keys. If a role is missing, because an older
  app meets a newer index, fall back to the app's built-in value for that role.
  Don't fail.
- **Fade between themes where possible.** When the colours change while the app is
  running (a pick in the app, a live reload after `mood-engine use`, an OS light/dark
  flip), glide from the old colours to the new ones instead of cutting over:
  - Interpolate in OKLab (or OKLCH), with an ease-out curve, over about 400–800 ms.
    mood-engine fades Ghostty in 400 ms and Zed in 800 ms, so this range keeps apps in step.
  - A change during a fade starts the next fade from the colours on screen, not from the
    old theme.
  - Don't fade the first theme applied at startup.
  - Under reduced motion, shorten the fade (to about 150 ms) rather than dropping it. A
    colour change is not movement.
  - Only where the platform makes this practical: a UI that redraws per frame (web,
    SwiftUI/AppKit, a TUI with its own render loop). Where it doesn't (a file read at
    start, a config the program reloads on its own), a hard switch
    is fine. Don't build heavy machinery just to fade.
- **Palette access is for special cases only.** Use it for terminal ANSI colors
  (table below), syntax highlighting, or charts that need many hues
  (`base08`–`base0F`, `base12`–`base17`).
- **Embed a fallback.** Compile one theme into the app, so it still runs when
  `~/.config/themes` is missing (CI, other machines, sandboxed builds).

## Reader algorithm

1. **Locate the directories.** For theme data, use `$THEMES_DIR` if set. Otherwise use
   `$XDG_CONFIG_HOME/themes`. Otherwise use `~/.config/themes`. For state, use
   `$THEMES_STATE_DIR` if set. Otherwise use `$XDG_STATE_HOME/themes`. Otherwise use
   `~/.local/state/themes`. Use these paths on macOS too, not
   `~/Library/Application Support`.
2. **List themes.** Read `schemes/*.json`. The id is the file name without `.json`.
   Sort by id, or by `name` for display. Ignore files that fail to parse; don't abort.
3. **Load a theme.** Merge `roles.json` with the theme's `roles` (theme wins). Resolve
   each value: a `#…` value is the color itself, otherwise look it up in `palette`.
4. **Choose the theme**, in this order:
   1. The app's saved choice, if it is a theme id that exists.
   2. If the saved choice is `"system"`, missing, or unknown, use
      `current.json[appearance]`, where `appearance` is the OS light/dark mode.
      Skip this step if the file or key is missing or the id is unknown.
   3. `defaults.json[appearance]`.
   4. The first listed theme.
   5. The app's embedded fallback.
5. **Persist the user's pick in the app's own settings**, not in either theme
   directory. Store the theme **id** (e.g. `"gruvbox-dark-hard"`) or the string
   `"system"`, never resolved colors. That way, edits to a theme file show up in the
   app. An optional **"Apply to all apps"** action also merges the id into
   `current.json` under the theme's `variant` key and sets this app to `"system"`.
6. **Optional: live reload.** Re-run steps 2–4 whenever something that affects the
   result changes:
   - A theme file, `roles.json` or `defaults.json` is edited.
   - A scheme is added or removed.
   - `current.json` is written by another app.
   - The OS appearance flips while the app is set to `"system"`.

   Apply the reloaded theme with a fade where possible (see "Rules for apps").

   File watching has three traps:
   - **Watch real paths.** The files in `~/.config/themes` may be **symlinks** into
     a dotfiles repo. Directory watchers such as FSEvents report a change at the
     file's real path. Edits made in the repo therefore produce **no event** under
     `~/.config/themes`. Resolve each loaded file with `realpath` and watch the
     directories that contain the real files. Also keep watching `~/.config/themes`
     and `schemes/` themselves, which catches symlinks being added or removed.
   - **Watch directories, not files.** Editors and atomic writers save by renaming a
     temp file over the original. A watch on a single file stops firing after that
     first save.
   - **Debounce and keep the last good theme.** Saves can produce several events and
     half-written files. Wait about 100 ms after the last event before reloading. If
     parsing fails, keep the theme that is currently applied.

   Reloading is cheap, so don't filter events. Any event in a watched directory
   triggers a debounced reload. After a reload, re-create the watchers if the set of
   real directories changed.

The theme picker in an app shows a "System" entry first, then every listed theme
(optionally grouped by `variant`).

## Reference implementation (TypeScript / Node, Bun, Deno)

Port this shape to other languages. It needs only a JSON parser and directory listing.

```ts
import { mkdirSync, readFileSync, readdirSync, realpathSync, renameSync, watch, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type Theme = {
  id: string;
  name: string;
  variant: "dark" | "light";
  palette: Record<string, string>;
  roles: Record<string, string>;
};

type Appearance = "dark" | "light";
type Selection = Partial<Record<Appearance, string>>;

const readJson = (p: string) => JSON.parse(readFileSync(p, "utf8"));
const tryJson = (p: string) => { try { return readJson(p); } catch { return undefined; } };

export function themesDir(): string {
  return process.env.THEMES_DIR
    ?? join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "themes");
}

export function stateDir(): string {
  return process.env.THEMES_STATE_DIR
    ?? join(process.env.XDG_STATE_HOME ?? join(homedir(), ".local", "state"), "themes");
}

export function listThemes(dir = themesDir()): string[] {
  return readdirSync(join(dir, "schemes"))
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.slice(0, -".json".length))
    .sort();
}

export function loadTheme(id: string, dir = themesDir()): Theme {
  const t = readJson(join(dir, "schemes", `${id}.json`));
  const mapping: Record<string, string> = { ...readJson(join(dir, "roles.json")), ...t.roles };
  const roles: Record<string, string> = {};
  for (const [role, ref] of Object.entries(mapping)) {
    const color = ref.startsWith("#") ? ref : t.palette[ref];
    if (color) roles[role] = color; // unresolvable → app falls back for that role
  }
  return { id, name: t.name, variant: t.variant, palette: t.palette, roles };
}

/** saved: the id the app persisted, "system", or null. */
export function resolveThemeId(
  saved: string | null, appearance: Appearance, dir = themesDir(), state = stateDir(),
): string | undefined {
  const ids = listThemes(dir);
  if (saved && saved !== "system" && ids.includes(saved)) return saved;
  for (const sel of [tryJson(join(state, "current.json")), tryJson(join(dir, "defaults.json"))]) {
    if (sel && ids.includes(sel[appearance])) return sel[appearance];
  }
  return ids[0];
}

/** "Apply to all apps": merge into current.json, atomically (temp file + rename). */
export function setGlobalTheme(sel: Selection, state = stateDir()): void {
  mkdirSync(state, { recursive: true });
  const target = join(state, "current.json");
  const tmp = `${target}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify({ ...tryJson(target), ...sel }, null, 2) + "\n");
  renameSync(tmp, target);
}

/**
 * Calls onChange (debounced) after anything that can change the resolved theme:
 * scheme/roles/defaults edits (watched at their real, de-symlinked location),
 * schemes being linked or unlinked, and current.json being written.
 * Returns a stop function. Recreate the watcher if onChange finds new schemes.
 */
export function watchThemes(onChange: () => void, dir = themesDir(), state = stateDir()): () => void {
  mkdirSync(state, { recursive: true }); // so a later first write of current.json is seen
  const dirs = new Set([dir, join(dir, "schemes"), state]);
  const files = ["roles.json", "defaults.json", ...listThemes(dir).map((id) => join("schemes", `${id}.json`))];
  for (const f of files) {
    try { dirs.add(dirname(realpathSync(join(dir, f)))); } catch { /* dangling link: skip */ }
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const fire = () => { clearTimeout(timer); timer = setTimeout(onChange, 100); };
  const watchers = [...dirs].flatMap((d) => { try { return [watch(d, fire)]; } catch { return []; } });
  return () => { clearTimeout(timer); watchers.forEach((w) => w.close()); };
}
```

Typical app wiring:

```ts
let theme = loadTheme(resolveThemeId(settings.theme, appearance())!); // inside try/catch
const reload = () => {
  try { theme = loadTheme(resolveThemeId(settings.theme, appearance())!); apply(theme); }
  catch { /* half-written file or bad JSON: keep the current theme */ }
};
const stop = watchThemes(reload);
// plus: re-run reload() when the OS appearance changes and settings.theme === "system"
```

Wrap the initial load in try/catch too. Any failure there means "use the embedded
fallback theme".

## Platform notes

- **CSS / web UI:** expose roles as custom properties named `--theme-<role>`
  (`--theme-bg`, `--theme-fg-muted`, …) and style only with those. Set
  `color-scheme: dark|light` from `variant`.
  - **Local dev server or Electron/Tauri:** read the directory on the server or main
    side and send the resolved roles to the page. For live reload, run `watchThemes` on
    the server or main side and push the new roles to the page (IPC, SSE or a
    websocket). The page re-sets the custom properties; there's no reload. Follow the
    OS appearance with `matchMedia("(prefers-color-scheme: dark)")` and its `change`
    event.
  - **Fading:** the simplest way is a short `requestAnimationFrame` tween:
    1. Read the colours on screen. Use `getComputedStyle` on a hidden probe element whose
       `color` is `var(--theme-x)`; this also resolves `light-dark()`.
    2. Apply the new theme and read the target colours the same way.
    3. Set inline overrides on `:root` that interpolate between the two in OKLab.
    4. Remove the overrides on the last frame.

    This works in WebKit (Tauri, Übersicht) and Chromium alike. Transitions on
    `@property`-registered `<color>` properties also work, but they misbehave with
    `light-dark()` values in some engines. [Lancelot](https://github.com/paraversal/lancelot)'s
    `app/src/lib/theme.svelte.ts` is a worked example.
  - **Deployed site:** a browser cannot read `~/.config`. At build time, generate a
    CSS file with one block per theme (`[data-theme="<id>"] { --theme-bg: …; }`) and
    switch with `document.documentElement.dataset.theme`. Persist the pick in
    `localStorage` and wrap that access in try/catch.
- **Übersicht widgets:** read files from the widget with
  `run("cat ~/.config/themes/schemes/<id>.json")` from `uebersicht` (and the same for
  `roles.json` / `defaults.json`). Then apply the merge and resolve logic above. Keep
  the chosen id in a top-of-file constant, or in a small JSON file next to the widget.
  Widgets can't watch files, so don't poll for the theme. Read it when the widget
  starts (in `init`, or in a `command` that also runs for other reasons) and let a
  mood-engine hook reload just this widget when the theme changes:
  `osascript -e 'tell application id "tracesOf.Uebersicht" to reload widget id "<id>"'`,
  where the id is the widget's path with `/` and `.` turned into `-`
  (`my.widget/index.jsx` → `my-widget-index-jsx`). Reloading one widget keeps the page
  and `window`, so stash the last theme on `window` and start from it: with the theme
  in its own `<style>` and CSS transitions on the static rules, the new one fades in.
  Avoid Übersicht's global `refresh`, which reloads every widget and loses their state.
- **Swift / macOS:**
  - Read the files with `FileManager` and `JSONDecoder`. Use
    `FileManager.default.homeDirectoryForCurrentUser` and honour the env vars as above.
  - Get light/dark from `NSApp.effectiveAppearance` (AppKit) or `@Environment(\.colorScheme)`
    (SwiftUI). Persist the pick in `UserDefaults`.
  - For live reload, use an **FSEvents** stream (`FSEventStreamCreate` with
    `kFSEventStreamCreateFlagFileEvents`) on the real directories from step 6.
    Don't use `DispatchSource.makeFileSystemObjectSource` on a directory: it only
    fires when entries are added, removed or renamed, not when a file is edited in
    place. Observe appearance changes with KVO on `NSApp.effectiveAppearance`.
  - To fade, apply the new colours inside `withAnimation(.easeOut(duration: 0.5))`
    (SwiftUI). In AppKit, use `NSAnimationContext.runAnimationGroup` for layer-backed
    views, or a short display-link tween.
  - **Sandboxed apps cannot read `~/.config`.** For those, either add
    `com.apple.security.temporary-exception.files.home-relative-path.read-only` for
    `/.config/themes/` (plus the path the symlinks resolve to, if any) and
    `…home-relative-path.read-write` for `/.local/state/themes/`, or copy the themes
    into the bundle at build time.
- **Python:** `json` and `pathlib` from the standard library are enough. For live
  reload, use a `watchdog` `Observer` with one non-recursive schedule per real
  directory from step 6, plus the same debounce. Detect macOS appearance with
  `defaults read -g AppleInterfaceStyle` (prints `Dark` in dark mode, errors in light mode).
- **Terminal / TUI:** emit 24-bit colors (`\x1b[38;2;R;G;Bm`). For a 16-color ANSI
  table, use the Base24 standard mapping:

  | ANSI    | normal | bright |
  |---------|--------|--------|
  | black   | base00 | base03 |
  | red     | base08 | base12 |
  | green   | base0B | base14 |
  | yellow  | base0A | base13 |
  | blue    | base0D | base16 |
  | magenta | base0E | base17 |
  | cyan    | base0C | base15 |
  | white   | base05 | base07 |

## Adding a theme

1. Find the scheme in the tinted-theming catalogue (`github.com/tinted-theming/schemes`,
   folders `base24/` and `base16/`). Use the Base16 version when the Base24 one is a
   poor terminal conversion. A poor conversion shows as `base00`–`base07` not running
   from background to foreground, or as grey body text.
2. Convert the YAML to `schemes/<id>.json` with the fields shown above. For a Base16
   source, fill the missing Base24 slots: `base10`, `base11` ← `base00`; `base12` ←
   `base08`; `base13` ← `base0A`; `base14` ← `base0B`; `base15` ← `base0C`; `base16` ←
   `base0D`; `base17` ← `base0E`.
3. Check each role against its background:
   - `fg` and `fg-muted` on `bg` should be ≥ 4.5:1.
   - `accent` and the status roles on `bg` should be ≥ 3:1.
   - `fg` should stay readable on `surface-raised`.

   Fix problems with `roles` overrides in the theme file. Prefer the theme's own
   official colors as literals over invented ones. Some themes (Solarized, Catppuccin
   Latte) miss a few targets by design, so keep their official colors.
4. To change which themes "System" uses, edit `defaults.json`.

If the directory is a stow package with `--no-folding`, re-run `stow` after adding a
**new** file so it is linked into `~`.
