"""Read and set the desktop wallpaper.

macOS: JXA's Objective-C bridge calls NSWorkspace directly
(setDesktopImageURL:forScreen:options:error:), once per screen. This needs no
PyObjC and, unlike System Events scripting, no Automation permission.
macOS only changes the *current* Space of each screen; other Spaces keep their
wallpaper until it is applied again while they are active.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import library


class DesktopError(Exception):
    pass


_GET = """
ObjC.import("AppKit");
function run() {
  const ws = $.NSWorkspace.sharedWorkspace, screens = $.NSScreen.screens, out = [];
  for (let i = 0; i < screens.count; i++) {
    const u = ws.desktopImageURLForScreen(screens.objectAtIndex(i));
    out.push(u.isNil() ? null : ObjC.unwrap(u.path));
  }
  return JSON.stringify(out);
}
"""

_SET = """
ObjC.import("AppKit");
function run(argv) {
  const ws = $.NSWorkspace.sharedWorkspace, screens = $.NSScreen.screens, errs = [];
  for (let i = 0; i < screens.count; i++) {
    const path = argv[Math.min(i, argv.length - 1)];
    const url = $.NSURL.fileURLWithPath(path), err = Ref();
    const opts = ws.desktopImageOptionsForScreen(screens.objectAtIndex(i));
    if (!ws.setDesktopImageURLForScreenOptionsError(url, screens.objectAtIndex(i), opts, err))
      errs.push(ObjC.unwrap(err[0].localizedDescription));
  }
  return JSON.stringify(errs);
}
"""


def _jxa(script: str, *args: str) -> str:
    if sys.platform != "darwin":
        raise DesktopError("setting the wallpaper is only supported on macOS so far "
                           "(use `mood-engine apply --print` with your own setter)")
    try:
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", script, *args],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise DesktopError(f"osascript failed: {e}") from e
    if out.returncode != 0:
        raise DesktopError(out.stderr.strip() or "osascript failed")
    return out.stdout.strip()


def get_wallpapers() -> list[str | None]:
    """Current wallpaper path for each screen."""
    return json.loads(_jxa(_GET))


def set_wallpaper(*paths: Path | str) -> None:
    """Set the wallpaper on every screen. With several paths, screen i gets
    paths[i] (the last one repeats); with one path, every screen gets it."""
    if not paths:
        raise DesktopError("no wallpaper given")
    for p in paths:
        if not Path(p).is_file():
            raise DesktopError(f"no such file: {p}")
    errs = json.loads(_jxa(_SET, *(str(Path(p).resolve()) for p in paths)))
    if errs:
        raise DesktopError("; ".join(errs))


def apply(theme_id: str, key: str | None = None, *, force_next: bool = False,
          set_desktop: bool = True) -> dict:
    """Pick the theme's wallpaper (or use `key`), record it as current, and set it.

    With set_desktop=False only the choice is recorded (for `apply --print`).
    """
    with library.edit() as lib:
        if key:
            library.set_current(lib, theme_id, key)
            pick = key
        else:
            pick = library.choose(lib, theme_id, force_next=force_next)
        if pick is None:
            raise library.LibraryError(
                f"no wallpapers saved for {theme_id}; open the gallery and press Save")
        path = library.file_path(lib, pick)
    if set_desktop:
        set_wallpaper(path)
    return {"key": pick, "file": path.name, "path": str(path)}


def set_appearance(dark: bool) -> None:
    """Switch macOS between dark and light mode. Goes through System Events, so the
    first call asks for Automation permission for the calling app (e.g. the terminal)."""
    if sys.platform != "darwin":
        raise DesktopError("switching the system appearance is only supported on macOS")
    script = ('tell application "System Events" to tell appearance preferences '
              f'to set dark mode to {"true" if dark else "false"}')
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise DesktopError(f"osascript failed: {e}") from e
    if out.returncode != 0:
        msg = out.stderr.strip()
        if "-1743" in msg or "not allowed" in msg.lower():
            msg = ("not allowed to control System Events; allow it in System Settings → "
                   "Privacy & Security → Automation, then try again")
        raise DesktopError(msg or "osascript failed")
