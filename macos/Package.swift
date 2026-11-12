// swift-tools-version: 6.0
// Menu bar companion for mood-engine. Build the app bundle with ./build.sh.
import PackageDescription

let package = Package(
    name: "MoodEngineBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "MoodEngineBar",
            path: "Sources/MoodEngineBar",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
