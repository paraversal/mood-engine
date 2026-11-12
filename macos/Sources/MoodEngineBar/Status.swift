import Foundation

/// Output of `mood-engine status` (see cmd_status in cli.py).
struct Status: Decodable {
    struct Theme: Decodable {
        let id: String
        let name: String
        let variant: String
        let colors: [String?]
    }

    struct Wallpaper: Decodable {
        let key: String
        let path: String
        let thumb: String
        let source: String?
        let author: String?
        let pageUrl: String?
        let pinned: Bool
    }

    struct Hooks: Decodable {
        let path: String
        let exists: Bool
        let count: Int
        let error: String?
        /// Real folders of hooks.toml and its templates (stow symlinks resolved).
        let watch: [String]
    }

    struct HookRun: Decodable {
        let name: String
        let ok: Bool
        let code: Int?
        let seconds: Double
        let output: String
    }

    struct LastSync: Decodable {
        let theme: String?
        let at: String?
        let error: String?
        let hooks: [HookRun]?
        let hooksAt: String?
    }

    let appearance: String
    let active: Theme?
    let selection: [String: String?]
    let themes: [Theme]
    let wallpaper: Wallpaper?
    let count: Int
    let pinned: Bool
    let hooks: Hooks
    let lastSync: LastSync
    let paths: [String: String]

    static func decode(_ data: Data) throws -> Status {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(Status.self, from: data)
    }

    func selected(_ variant: String) -> String? { selection[variant] ?? nil }

    var failedHooks: [HookRun] { (lastSync.hooks ?? []).filter { !$0.ok } }

    /// Something the user should look at: shown as a warning in the menu bar.
    var problem: String? {
        if let e = lastSync.error { return e }
        if let e = hooks.error { return e }
        if let h = failedHooks.first { return "hook “\(h.name)” failed" }
        return nil
    }
}
