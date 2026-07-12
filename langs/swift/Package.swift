// swift-tools-version: 5.9
//
// VMx — Swift flavor.
//
// Implements spec v3.16.0 at full library parity. See README.md §5 for the
// conformance matrix and CHANGELOG.md for per-release history.
//
import PackageDescription

let package = Package(
    name: "VMx",
    platforms: [
        .iOS(.v16),
        .macOS(.v13),
        .tvOS(.v16),
        .watchOS(.v9),
    ],
    products: [
        .library(name: "VMx", targets: ["VMx"]),
    ],
    targets: [
        // Shared conformance fixtures live in the library bundle. The tests load
        // them via `Bundle.module`, which — with no resources on the test target
        // and `@testable import VMx` — resolves to the library's bundle. Adding
        // resources to the test target would generate a VMxTests `Bundle.module`
        // that shadows the library's and breaks LIFE-011 (it would no longer see
        // lifecycle-transitions.json). Keep test-target resources empty.
        .target(name: "VMx", path: "Sources/VMx", resources: [.process("Resources")]),
        .testTarget(
            name: "VMxTests",
            dependencies: ["VMx"],
            path: "Tests/VMxTests"
        ),
    ]
)
