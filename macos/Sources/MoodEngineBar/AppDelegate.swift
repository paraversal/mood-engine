import AppKit
import ServiceManagement

/// The menu bar item. It watches for anything that can change the active theme or
/// what the hooks produce, and runs `mood-engine sync`, which re-applies the
/// wallpaper and runs the hooks whose inputs changed.
///
/// Triggers: macOS switching dark/light (also on its own schedule), writes to
/// current.json, defaults.json, the schemes, hooks.toml or a template (at their
/// real, de-symlinked paths), waking from sleep, and the day changing (daily
/// rotation). Switching Spaces or screens only re-sets the current wallpaper where
/// a Space still shows another one.
final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private let work = DispatchQueue(label: "mood-engine.work")  // serial: one CLI call at a time
    private var cli: CLI?  // only touched on `work`
    private var cliMissing = false

    private var status: Status?
    private var statusError: String?
    private var actionError: String?
    private var iconSymbol: String?

    private var themeWatcher: DirectoryWatcher?
    private var libraryWatcher: DirectoryWatcher?
    private var appearanceObservation: NSKeyValueObservation?
    private var lastDark: Bool?
    private lazy var syncSoon = Debouncer(delay: 0.4) { [weak self] in self?.sync() }
    private lazy var refreshSoon = Debouncer(delay: 0.5) { [weak self] in self?.runCLI(nil as [String]?) }

    private var gallery: Process?
    private var galleryReady = false
    private var galleryURL: URL?
    private let galleryPort = 8765

    private var everySpace: Bool {
        get { UserDefaults.standard.bool(forKey: "everySpace") }
        set { UserDefaults.standard.set(newValue, forKey: "everySpace") }
    }

    // MARK: - Lifecycle

    func applicationDidFinishLaunching(_ note: Notification) {
        UserDefaults.standard.register(defaults: ["everySpace": true])
        menu.delegate = self
        menu.autoenablesItems = false
        statusItem.menu = menu
        updateIcon()

        lastDark = Desktop.isDark
        appearanceObservation = NSApp.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.appearanceMayHaveChanged() }
        }
        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("AppleInterfaceThemeChangedNotification"), object: nil, queue: .main
        ) { [weak self] _ in
            // effectiveAppearance can lag this notification; look now and once more shortly.
            self?.appearanceMayHaveChanged()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self?.appearanceMayHaveChanged() }
        }
        let wsnc = NSWorkspace.shared.notificationCenter
        wsnc.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.syncSoon.poke()
        }
        wsnc.addObserver(forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.enforceWallpaperSoon()
        }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
                                               object: nil, queue: .main) { [weak self] _ in
            self?.enforceWallpaperSoon()
        }
        NotificationCenter.default.addObserver(forName: .NSCalendarDayChanged, object: nil, queue: .main) { [weak self] _ in
            self?.syncSoon.poke()
        }
        sync()
    }

    func applicationWillTerminate(_ note: Notification) {
        gallery?.terminate()
    }

    /// A dark/light flip syncs at once, with no debounce: the rest of macOS has already
    /// switched, so every moment here is a moment the fades start late. The `lastDark`
    /// check already makes the second of macOS's two signals for one flip a no-op.
    /// (File changes and wake still go through `syncSoon`, which merges bursts.)
    /// The wallpaper alone waits: set while macOS is still redrawing for the new
    /// appearance, it can leave the menu bar blank until something clicks it.
    private func appearanceMayHaveChanged() {
        let dark = Desktop.isDark
        guard dark != lastDark else { return }
        lastDark = dark
        sync(wallpaperDelay: Self.flipWallpaperDelay)
    }

    private static let flipWallpaperDelay = 1.0

    // MARK: - Running the CLI

    private var appearance: String { Desktop.isDark ? "dark" : "light" }

    private func sync(wallpaper: Bool = false, hooks: Bool = false, wallpaperDelay: Double = 0) {
        var args = ["sync", "--json", "--appearance", appearance]
        if wallpaper { args.append("--wallpaper") }
        if hooks { args.append("--hooks") }
        if wallpaperDelay > 0 { args += ["--wallpaper-delay", String(wallpaperDelay)] }
        runCLI(args)
    }

    /// Runs `mood-engine args` (if any), then `status`, and keeps the result for the
    /// next time the menu opens. Never touches the menu itself: rebuilding an open
    /// menu makes its items jump.
    private func runCLI(_ args: [String]?, then: ((CLI.Result?) -> Void)? = nil) {
        let appearance = self.appearance
        work.async {
            if self.cli == nil { self.cli = CLI() }
            let cli = self.cli!
            if cli.executable == nil { cli.relocate() }
            let result = args.map { cli.run($0) }
            let st = cli.run(["status", "--appearance", appearance], timeout: 30)
            let missing = cli.executable == nil
            DispatchQueue.main.async {
                self.cliMissing = missing
                if st.ok, let s = try? Status.decode(st.stdout) {
                    self.status = s
                    self.statusError = nil
                    self.rewatch(s)
                } else {
                    self.statusError = missing ? nil : CLI.message(st)
                }
                if let r = result {
                    // Hook failures show up through the status; other failures go to stderr.
                    let err = r.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
                    self.actionError = (r.ok || err.isEmpty) ? nil : err
                }
                then?(result)
                self.updateIcon()
                if args?.first == "sync" || args?.first == "use" { self.enforceWallpaperSoon() }
            }
        }
    }

    private func rewatch(_ s: Status) {
        let fm = FileManager.default
        guard let state = s.paths["state"], let themes = s.paths["themes"], let lib = s.paths["library"] else { return }
        // Create the state and config dirs so a first current.json or hooks.toml is seen.
        // (stow --no-folding links files, not folders, so a real config dir is fine.)
        try? fm.createDirectory(atPath: state, withIntermediateDirectories: true)
        if let config = s.paths["config"] {
            try? fm.createDirectory(atPath: config, withIntermediateDirectories: true)
        }
        // Anything that can change what a sync does: the selection, the theme index
        // (schemes included, recursively) and the hooks with their templates.
        let themeDirs = Array(Set([
            Paths.existingDirectory(state),
            Paths.realDirectory(of: state + "/current.json"),
            Paths.existingDirectory(themes),
            Paths.realDirectory(of: themes + "/defaults.json"),
            s.paths["config"].flatMap(Paths.existingDirectory),
        ].compactMap { $0 } + s.hooks.watch)).sorted()
        if themeWatcher?.directories != themeDirs {
            themeWatcher = DirectoryWatcher(directories: themeDirs) { [weak self] in self?.syncSoon.poke() }
        }
        let libDir = (lib as NSString).deletingLastPathComponent
        try? fm.createDirectory(atPath: libDir, withIntermediateDirectories: true)
        let refreshDirs = [libDir]
        if libraryWatcher?.directories != refreshDirs {
            // The gallery saving, pinning or removing wallpapers, or a sync finishing:
            // refresh the status for the next menu.
            libraryWatcher = DirectoryWatcher(directories: refreshDirs, latency: 0.5) { [weak self] in
                self?.refreshSoon.poke()
            }
        }
    }

    private func enforceWallpaperSoon() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            guard let self, self.everySpace, let p = self.status?.wallpaper?.path else { return }
            Desktop.ensureWallpaper(p)
        }
    }

    // MARK: - Menu

    /// Called right before the menu shows: build it from the last status. The file
    /// watchers keep that status current, so opening the menu runs no CLI call.
    func menuNeedsUpdate(_ menu: NSMenu) {
        if menu === self.menu { rebuildMenu() }
    }

    private func updateIcon() {
        let problem = status?.problem ?? actionError ?? statusError ?? (cliMissing ? "missing" : nil)
        let name = problem != nil ? "exclamationmark.triangle" : "photo.on.rectangle"
        statusItem.button?.toolTip = problem.map { "mood-engine: \($0)" } ?? "mood-engine"
        guard name != iconSymbol else { return }  // re-setting the image makes the button redraw
        iconSymbol = name
        let img = NSImage(systemSymbolName: name, accessibilityDescription: "mood-engine")
        img?.isTemplate = true
        statusItem.button?.image = img
    }

    private func item(_ title: String, _ action: Selector?, key: String = "", enabled: Bool = true,
                      object: Any? = nil, image: NSImage? = nil) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
        i.target = self
        i.isEnabled = enabled && action != nil
        i.representedObject = object
        i.image = image
        return i
    }

    private func symbol(_ name: String) -> NSImage? {
        NSImage(systemSymbolName: name, accessibilityDescription: nil)
    }

    private func rebuildMenu() {
        menu.removeAllItems()
        if cliMissing {
            menu.addItem(item("mood-engine command not found", nil))
            menu.addItem(item("Choose mood-engine…", #selector(chooseCLI)))
            addFooter()
            return
        }
        guard let s = status else {
            menu.addItem(item(statusError.map { "⚠︎ \($0)" } ?? "Loading…",
                              statusError == nil ? nil : #selector(showProblem)))
            addFooter()
            return
        }

        if let t = s.active {
            let header = item(t.name, #selector(openLibrary), image: Swatch.image(t))
            let summary: String
            switch (s.count, s.pinned) {
            case (0, _): summary = "no wallpapers saved"
            case (_, true): summary = "pinned wallpaper"
            case (1, _): summary = "1 wallpaper"
            default: summary = "\(s.count) wallpapers, new one daily"
            }
            header.toolTip = "Open the library for \(t.name)"
            if #available(macOS 14.4, *) {
                header.subtitle = "\(t.variant.capitalized) · \(summary)"
            } else {
                header.title = "\(t.name) — \(summary)"
            }
            menu.addItem(header)
            if let w = s.wallpaper {
                let wi = NSMenuItem()
                let row = WallpaperRowView(wallpaper: w)
                row.onClick = { [weak self] in self?.openWallpaperPage(w) }
                wi.view = row
                wi.toolTip = "Open the wallpaper's page\n\(w.path)"
                menu.addItem(wi)
            }
            menu.addItem(.separator())
            menu.addItem(item("Next Wallpaper", #selector(nextWallpaper), key: "n",
                              enabled: s.count > 1 && !s.pinned))
            if s.pinned {
                menu.addItem(item("Unpin (New One Daily)", #selector(togglePin)))
            } else {
                menu.addItem(item("Pin This Wallpaper", #selector(togglePin), enabled: s.wallpaper != nil))
            }
            menu.addItem(item("Find Wallpapers…", #selector(openGallery), key: "f"))
            menu.addItem(item("Library…", #selector(openLibrary), key: "l"))
        } else {
            menu.addItem(item("No themes in \(s.paths["themes"] ?? "~/.config/themes")", nil))
        }

        menu.addItem(.separator())
        for variant in ["dark", "light"] {
            let sub = NSMenu()
            sub.autoenablesItems = false
            for t in s.themes where t.variant == variant {
                let ti = item(t.name, #selector(chooseTheme), object: t.id, image: Swatch.image(t))
                ti.state = s.selected(variant) == t.id ? .on : .off
                sub.addItem(ti)
            }
            let title = variant == "dark" ? "Dark Theme" : "Light Theme"
            let parent = item(title, nil, image: symbol(variant == "dark" ? "moon" : "sun.max"))
            parent.isEnabled = !sub.items.isEmpty
            if let id = s.selected(variant), let t = s.themes.first(where: { $0.id == id }) {
                if #available(macOS 14.4, *) { parent.subtitle = t.name }
            }
            parent.submenu = sub
            menu.addItem(parent)
        }
        menu.addItem(item(Desktop.isDark ? "Switch to Light Mode" : "Switch to Dark Mode", #selector(toggleAppearance)))

        menu.addItem(.separator())
        menu.addItem(hooksItem(s))
        menu.addItem(item("Re-apply Wallpaper", #selector(reapply)))
        if let p = s.problem ?? actionError {
            menu.addItem(item("⚠︎ \(p)", #selector(showProblem)))
        }
        addFooter()
    }

    private func hooksItem(_ s: Status) -> NSMenuItem {
        let sub = NSMenu()
        sub.autoenablesItems = false
        let summary: String
        switch (s.hooks.count, s.hooks.exists) {
        case (0, false): summary = "No hooks yet"
        case (0, true): summary = "No hooks enabled"
        case (1, _): summary = "1 hook keeps apps in line"
        case (let n, _): summary = "\(n) hooks keep apps in line"
        }
        sub.addItem(item(summary, nil))
        if let e = s.hooks.error {
            sub.addItem(item("⚠︎ hooks.toml has an error", #selector(showText), object: e))
        }
        if let runs = s.lastSync.hooks, !runs.isEmpty {
            sub.addItem(.separator())
            sub.addItem(item("Last run\(Self.time(s.lastSync.hooksAt).map { " at \($0)" } ?? "")", nil))
            for r in runs {
                let status = r.ok ? String(format: "%.1f s", r.seconds)
                    : (r.code.map { "exit \($0)" } ?? "timed out")
                let text = "\(r.name) — \(status)\n\n\(r.output.isEmpty ? "(no output)" : r.output)"
                sub.addItem(item("\(r.name)  (\(status))", #selector(showText), object: text,
                                 image: symbol(r.ok ? "checkmark.circle" : "xmark.octagon")))
            }
        }
        sub.addItem(.separator())
        sub.addItem(item("Run Hooks Now", #selector(runHooks), enabled: s.hooks.count > 0))
        sub.addItem(item("Edit hooks.toml…", #selector(editHooks)))
        let failed = !s.failedHooks.isEmpty || s.hooks.error != nil
        let parent = item(failed ? "Hooks ⚠︎" : "Hooks", nil, image: symbol("bolt"))
        parent.isEnabled = true
        parent.submenu = sub
        return parent
    }

    private func addFooter() {
        menu.addItem(.separator())
        let spaces = item("Keep Wallpaper on Every Space", #selector(toggleEverySpace))
        spaces.state = everySpace ? .on : .off
        spaces.toolTip = "When you switch to a Space that shows another wallpaper, set the theme's wallpaper there too."
        menu.addItem(spaces)
        let login = item("Open at Login", #selector(toggleLogin))
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        menu.addItem(item("Quit mood-engine", #selector(quit), key: "q"))
    }

    private static func time(_ iso: String?) -> String? {
        guard let iso, let d = ISO8601DateFormatter().date(from: iso) else { return nil }
        let f = DateFormatter()
        f.dateStyle = Calendar.current.isDateInToday(d) ? .none : .short
        f.timeStyle = .short
        return f.string(from: d)
    }

    // MARK: - Actions

    @objc private func nextWallpaper() {
        guard let id = status?.active?.id else { return }
        runCLI(["apply", id, "--next"])
    }

    @objc private func togglePin() {
        guard let s = status, let id = s.active?.id else { return }
        runCLI([s.pinned ? "unpin" : "pin", id])
    }

    @objc private func chooseTheme(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        runCLI(["use", id])
    }

    @objc private func toggleAppearance() {
        // KVO on the appearance then triggers the sync.
        if let err = Desktop.toggleDarkMode() { alert("Couldn't switch the appearance", err) }
    }

    @objc private func reapply() { sync(wallpaper: true) }

    @objc private func runHooks() { sync(hooks: true) }

    @objc private func editHooks() {
        runCLI(["hooks", "--init"]) { [weak self] _ in
            guard let path = self?.status?.hooks.path else { return }
            let url = URL(fileURLWithPath: path)
            if !NSWorkspace.shared.open(url) {
                let textEdit = URL(fileURLWithPath: "/System/Applications/TextEdit.app")
                NSWorkspace.shared.open([url], withApplicationAt: textEdit,
                                        configuration: NSWorkspace.OpenConfiguration())
            }
        }
    }

    private func openWallpaperPage(_ w: Status.Wallpaper) {
        if let p = w.pageUrl, let url = URL(string: p) {
            NSWorkspace.shared.open(url)
        } else {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: w.path)])
        }
    }

    @objc private func openGallery() { openServer(path: "/") }

    @objc private func openLibrary() { openServer(path: "/library") }

    /// Starts `mood-engine serve` on first use (stopped when the app quits) and opens
    /// the page in the browser once it listens.
    private func openServer(path: String) {
        var c = URLComponents(string: "http://127.0.0.1:\(galleryPort)\(path)")!
        if let id = status?.active?.id { c.queryItems = [URLQueryItem(name: "theme", value: id)] }
        guard let url = c.url else { return }
        if let g = gallery, g.isRunning {
            if galleryReady { NSWorkspace.shared.open(url) } else { galleryURL = url }
            return
        }
        galleryURL = url
        galleryReady = false
        work.async {
            guard let cli = self.cli, let exe = cli.executable else { return }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: exe)
            p.arguments = ["serve", "--no-open", "--port", String(self.galleryPort)]
            p.environment = cli.environment
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err
            p.standardInput = FileHandle.nullDevice
            var errText = ""
            out.fileHandleForReading.readabilityHandler = { h in
                let s = String(decoding: h.availableData, as: UTF8.self)
                if s.contains("gallery on") {
                    DispatchQueue.main.async { self.galleryDidStart() }
                }
            }
            err.fileHandleForReading.readabilityHandler = { h in
                errText += String(decoding: h.availableData, as: UTF8.self)
            }
            p.terminationHandler = { proc in
                out.fileHandleForReading.readabilityHandler = nil
                err.fileHandleForReading.readabilityHandler = nil
                DispatchQueue.main.async {
                    let wasReady = self.galleryReady
                    self.gallery = nil
                    self.galleryReady = false
                    guard !wasReady, let url = self.galleryURL else { return }
                    self.galleryURL = nil
                    if errText.contains("Address already in use") {
                        NSWorkspace.shared.open(url)  // a gallery from the terminal already runs
                    } else {
                        self.alert("The gallery didn't start", errText.isEmpty ? "exit \(proc.terminationStatus)" : errText)
                    }
                }
            }
            do {
                try p.run()
                DispatchQueue.main.async { self.gallery = p }
            } catch {
                DispatchQueue.main.async { self.alert("The gallery didn't start", error.localizedDescription) }
            }
        }
    }

    private func galleryDidStart() {
        galleryReady = true
        if let url = galleryURL { NSWorkspace.shared.open(url) }
        galleryURL = nil
    }

    @objc private func toggleEverySpace() {
        everySpace.toggle()
        enforceWallpaperSoon()
    }

    @objc private func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
        } catch {
            alert("Couldn't change Open at Login", error.localizedDescription)
        }
    }

    @objc private func chooseCLI() {
        let panel = NSOpenPanel()
        panel.message = "Choose the mood-engine executable (e.g. .venv/bin/mood-engine in the repo)"
        panel.canChooseDirectories = false
        panel.showsHiddenFiles = true
        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let url = panel.url else { return }
        UserDefaults.standard.set(url.path, forKey: CLI.pathDefaultsKey)
        sync()
    }

    @objc private func showProblem() {
        let text = [status?.problem, actionError, statusError].compactMap { $0 }.joined(separator: "\n\n")
        var details = text
        for h in status?.failedHooks ?? [] {
            details += "\n\n\(h.name):\n\(h.output.isEmpty ? "(no output)" : h.output)"
        }
        alert("mood-engine", details)
        actionError = nil
        updateIcon()
    }

    @objc private func showText(_ sender: NSMenuItem) {
        alert("mood-engine", sender.representedObject as? String ?? "")
    }

    @objc private func quit() { NSApp.terminate(nil) }

    private func alert(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = title
        a.informativeText = String(text.prefix(4000))
        a.runModal()
    }
}

extension CLI {
    static func message(_ r: Result) -> String {
        let s = r.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return s.isEmpty ? "mood-engine exited with \(r.code)" : String(s.split(separator: "\n").last ?? "")
    }
}
