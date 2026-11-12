import AppKit
import CoreServices

/// FSEvents on a set of directories. Directories, not files: atomic writers rename a
/// temp file over the target, which a per-file watch would miss after the first save.
final class DirectoryWatcher {
    private var stream: FSEventStreamRef?
    private let onChange: () -> Void
    let directories: [String]

    init?(directories: [String], latency: TimeInterval = 0.2, onChange: @escaping () -> Void) {
        self.directories = directories
        self.onChange = onChange
        guard !directories.isEmpty else { return nil }
        var ctx = FSEventStreamContext(version: 0, info: nil, retain: nil, release: nil, copyDescription: nil)
        ctx.info = Unmanaged.passUnretained(self).toOpaque()
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            Unmanaged<DirectoryWatcher>.fromOpaque(info).takeUnretainedValue().onChange()
        }
        let flags = UInt32(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer)
        guard let s = FSEventStreamCreate(nil, callback, &ctx, directories as CFArray,
                                          FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
                                          latency, flags) else { return nil }
        stream = s
        FSEventStreamSetDispatchQueue(s, .main)
        FSEventStreamStart(s)
    }

    deinit {
        if let s = stream {
            FSEventStreamStop(s)
            FSEventStreamInvalidate(s)
            FSEventStreamRelease(s)
        }
    }
}

/// Calls `action` once, `delay` after the last `poke()`.
final class Debouncer {
    private let delay: TimeInterval
    private let action: () -> Void
    private var item: DispatchWorkItem?

    init(delay: TimeInterval, action: @escaping () -> Void) {
        self.delay = delay
        self.action = action
    }

    func poke() {
        item?.cancel()
        let i = DispatchWorkItem(block: action)
        item = i
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: i)
    }
}

enum Paths {
    /// The directory a file really lives in (stow symlinks point into the dotfiles
    /// repo, and FSEvents reports changes at the real path), or nil if it doesn't exist.
    static func realDirectory(of file: String) -> String? {
        let url = URL(fileURLWithPath: file)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url.resolvingSymlinksInPath().deletingLastPathComponent().path
    }

    static func existingDirectory(_ path: String) -> String? {
        var isDir: ObjCBool = false
        return FileManager.default.fileExists(atPath: path, isDirectory: &isDir) && isDir.boolValue ? path : nil
    }
}

enum Desktop {
    static var isDark: Bool {
        NSApp.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
    }

    /// Sets `path` on every screen whose current Space shows something else.
    /// Returns how many screens changed.
    @discardableResult
    static func ensureWallpaper(_ path: String) -> Int {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: path) else { return 0 }
        let ws = NSWorkspace.shared
        var changed = 0
        for screen in NSScreen.screens where ws.desktopImageURL(for: screen)?.standardizedFileURL != url.standardizedFileURL {
            let opts = ws.desktopImageOptions(for: screen) ?? [:]
            if (try? ws.setDesktopImageURL(url, for: screen, options: opts)) != nil { changed += 1 }
        }
        return changed
    }

    /// Flips macOS dark mode through System Events (asks for Automation permission once).
    static func toggleDarkMode() -> String? {
        let src = "tell application \"System Events\" to tell appearance preferences to set dark mode to not dark mode"
        var err: NSDictionary?
        NSAppleScript(source: src)?.executeAndReturnError(&err)
        guard let err else { return nil }
        let n = err[NSAppleScript.errorNumber] as? Int
        if n == -1743 {
            return "mood-engine isn't allowed to control System Events. Allow it in System Settings → Privacy & Security → Automation."
        }
        return err[NSAppleScript.errorMessage] as? String ?? "could not switch the appearance"
    }
}
