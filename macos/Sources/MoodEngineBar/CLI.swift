import Foundation

/// Finds and runs the `mood-engine` command line tool. All theme, library and hook
/// logic lives there; the app only decides *when* to call it.
final class CLI {
    struct Result {
        let code: Int32
        let stdout: Data
        let stderr: String
        var ok: Bool { code == 0 }
        var text: String { String(decoding: stdout, as: UTF8.self) }
    }

    static let pathDefaultsKey = "cliPath"

    /// Environment for every child: the login shell's PATH (a GUI app launched by
    /// launchd only gets /usr/bin:/bin:...), so hooks find Homebrew and ~/.local tools.
    let environment: [String: String]
    private(set) var executable: String?

    init() {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = CLI.loginPath(current: env["PATH"])
        env["PYTHONUNBUFFERED"] = "1"
        environment = env
        executable = CLI.locate(path: env["PATH"] ?? "")
    }

    func relocate() { executable = CLI.locate(path: environment["PATH"] ?? "") }

    /// Order: a path chosen in the menu, the one build.sh baked into Info.plist
    /// (the repo's .venv), then `mood-engine` on the login PATH.
    static func locate(path: String) -> String? {
        let fm = FileManager.default
        var candidates: [String] = []
        if let p = UserDefaults.standard.string(forKey: pathDefaultsKey) { candidates.append(p) }
        if let p = Bundle.main.object(forInfoDictionaryKey: "MoodEngineCLI") as? String { candidates.append(p) }
        candidates += path.split(separator: ":").map { "\($0)/mood-engine" }
        return candidates.first { fm.isExecutableFile(atPath: ($0 as NSString).expandingTildeInPath) }
            .map { ($0 as NSString).expandingTildeInPath }
    }

    static func loginPath(current: String?) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let extra = ["/opt/homebrew/bin", "/usr/local/bin", "\(home)/.local/bin"]
        let shell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        var parts: [String] = []
        let p = Process()
        p.executableURL = URL(fileURLWithPath: shell)
        p.arguments = ["-l", "-c", "printf '%s' \"$PATH\""]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        if (try? p.run()) != nil {
            let killer = DispatchWorkItem { if p.isRunning { p.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + 5, execute: killer)
            let data = out.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            killer.cancel()
            if p.terminationStatus == 0 {
                parts = String(decoding: data, as: UTF8.self).split(separator: ":").map(String.init)
            }
        }
        parts += (current ?? "/usr/bin:/bin:/usr/sbin:/sbin").split(separator: ":").map(String.init)
        parts += extra
        var seen = Set<String>()
        return parts.filter { !$0.isEmpty && seen.insert($0).inserted }.joined(separator: ":")
    }

    /// Runs `mood-engine args...` and waits. Call off the main thread.
    func run(_ args: [String], timeout: TimeInterval = 600) -> Result {
        guard let exe = executable else {
            return Result(code: 127, stdout: Data(), stderr: "mood-engine not found")
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = args
        p.environment = environment
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch {
            return Result(code: 126, stdout: Data(), stderr: error.localizedDescription)
        }
        let killer = DispatchWorkItem { if p.isRunning { p.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
        var errData = Data()
        let group = DispatchGroup()
        DispatchQueue.global().async(group: group) { errData = err.fileHandleForReading.readDataToEndOfFile() }
        let outData = out.fileHandleForReading.readDataToEndOfFile()
        group.wait()
        p.waitUntilExit()
        killer.cancel()
        return Result(code: p.terminationStatus, stdout: outData,
                      stderr: String(decoding: errData, as: UTF8.self))
    }
}
