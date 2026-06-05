// swift-tools-version: 5.9
//
// VMx — Swift flavor (skeleton).
//
// First release of the Swift flavor; implements a subset of spec v2.4.0
// (LIFE, CVM, COMP, GRP, AGG, CMD, BLD). See README.md §5 for the in /
// deferred matrix and CHANGELOG.md for what landed in 2.4.0.
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
        .target(name: "VMx", path: "Sources/VMx"),
        .testTarget(name: "VMxTests", dependencies: ["VMx"], path: "Tests/VMxTests"),
    ]
)
