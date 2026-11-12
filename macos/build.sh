#!/bin/sh
# Build "mood-engine.app" (menu bar companion) into macos/build/.
#   ./build.sh            build only
#   ./build.sh --install  also copy it to ~/Applications and (re)start it
set -eu
cd "$(dirname "$0")"
repo=$(cd .. && pwd)
app=build/mood-engine.app

swift build -c release
bin=$(swift build -c release --show-bin-path)/MoodEngineBar

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin" "$app/Contents/MacOS/mood-engine-bar"

# The CLI the app runs: the repo's virtualenv (editable install, so it always runs
# the current code). Falls back to `mood-engine` on the login PATH if it is missing.
cli="$repo/.venv/bin/mood-engine"
[ -x "$cli" ] || echo "note: $cli not found; run \`uv sync\` in $repo (the app will look on PATH)" >&2

cat > "$app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>local.mood-engine.menubar</string>
  <key>CFBundleName</key><string>mood-engine</string>
  <key>CFBundleDisplayName</key><string>mood-engine</string>
  <key>CFBundleExecutable</key><string>mood-engine-bar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSAppleEventsUsageDescription</key>
  <string>mood-engine switches macOS between dark and light mode through System Events.</string>
  <key>MoodEngineCLI</key><string>$cli</string>
</dict>
</plist>
EOF

codesign --force --sign - "$app" >/dev/null
echo "built $(pwd)/$app"

if [ "${1:-}" = "--install" ]; then
  dest="$HOME/Applications/mood-engine.app"
  pkill -x mood-engine-bar 2>/dev/null && sleep 0.5 || true
  mkdir -p "$HOME/Applications"
  rm -rf "$dest"
  cp -R "$app" "$dest"
  open "$dest"
  echo "installed and started $dest"
fi
