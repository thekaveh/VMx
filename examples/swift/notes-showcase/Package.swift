// swift-tools-version: 5.9
//
// Notes Showcase — Swift flagship example.
//
// A macOS app mirroring the C#/Python/TypeScript Notes Showcase,
// powered by the VMx Swift library. See examples/notes-showcase-parity.md
// for the cross-flavor parity contract.
//
import PackageDescription

let package = Package(
    name: "NotesShowcase",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(path: "../../../langs/swift"),
    ],
    targets: [
        .target(
            name: "NotesShowcaseCore",
            dependencies: [.product(name: "VMx", package: "swift")],
            path: "Sources/NotesShowcaseCore"
        ),
        .executableTarget(
            name: "NotesShowcase",
            dependencies: [
                "NotesShowcaseCore",
                .product(name: "VMx", package: "swift"),
            ],
            path: "Sources/NotesShowcase"
        ),
        .testTarget(
            name: "NotesShowcaseTests",
            dependencies: [
                "NotesShowcase",
                "NotesShowcaseCore",
                .product(name: "VMx", package: "swift"),
            ],
            path: "Tests/NotesShowcaseTests"
        ),
    ]
)
