// swift-tools-version: 5.9
//
// VMx — public SwiftPM facade.
//
// SwiftPM resolves remote packages from the tagged repository root. This
// manifest exposes the existing Swift flavor without copying its sources,
// tests, or resources. Keep it structurally synchronized with
// langs/swift/Package.swift; tools/check-swift-package-sync.py enforces parity.
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
        // Resources stay in the library target so Bundle.module resolves to
        // the same VMx bundle for root and nested package consumers.
        .target(
            name: "VMx",
            path: "langs/swift/Sources/VMx",
            resources: [.process("Resources")]
        ),
        .testTarget(
            name: "VMxTests",
            dependencies: ["VMx"],
            path: "langs/swift/Tests/VMxTests"
        ),
    ]
)
