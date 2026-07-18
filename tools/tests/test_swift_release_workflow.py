"""Contract tests for Swift package and release GitHub Actions."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_swift_ci_covers_root_nested_and_manifest_parity() -> None:
    workflow = _workflow("swift.yml")

    assert '- "Package.swift"' in workflow
    assert '- "tools/check-swift-package-sync.py"' in workflow
    assert "python3 tools/check-swift-package-sync.py" in workflow
    assert "name: Build root package" in workflow
    assert "name: Test root package" in workflow
    assert "name: Build nested package" in workflow
    assert "name: Test nested package" in workflow


def test_swift_ci_uses_supported_runners_and_compiles_declared_platforms() -> None:
    workflow = _workflow("swift.yml")

    assert "macos-14" not in workflow
    assert "macos-latest" not in workflow
    assert "Xcode_15" not in workflow
    assert "/Applications/Xcode_16.0.app" in workflow
    assert 'destination: "generic/platform=iOS"' in workflow
    assert 'destination: "generic/platform=tvOS"' in workflow
    assert 'destination: "generic/platform=watchOS"' in workflow
    assert "CODE_SIGNING_ALLOWED=NO build" in workflow


def test_swift_ci_enforces_complete_strict_concurrency() -> None:
    workflow = _workflow("swift.yml")

    assert "name: Enforce strict concurrency boundaries" in workflow
    assert "if: matrix.xcode == 'default'" in workflow
    assert "-Xswiftc -strict-concurrency=complete" in workflow
    assert "-Xswiftc -warn-concurrency" in workflow
    assert "-Xswiftc -warnings-as-errors" in workflow


def test_swift_ci_enforces_strict_concurrency_for_flagship() -> None:
    workflow = _workflow("swift.yml")
    examples_job = workflow.split("\n  examples:\n", maxsplit=1)[1]

    assert "name: Enforce NotesShowcase strict concurrency" in examples_job
    assert "-Xswiftc -strict-concurrency=complete" in examples_job
    assert "-Xswiftc -warn-concurrency" in examples_job
    assert "-Xswiftc -warnings-as-errors" in examples_job


def test_swift_release_requires_same_sha_semantic_tag() -> None:
    workflow = _workflow("release.yml")

    assert "refs/tags/v${tag_version}" in workflow
    assert 'git rev-parse "refs/tags/v${tag_version}^{commit}"' in workflow
    assert '"$semantic_sha" != "$GITHUB_SHA"' in workflow
    assert "does not match VMxVersion.current" in workflow


def test_swift_release_gates_both_packages_and_public_consumer() -> None:
    workflow = _workflow("release.yml")

    assert "python3 tools/check-swift-package-sync.py" in workflow
    assert "name: Build & test root package" in workflow
    assert "name: Build & test nested package" in workflow
    assert "python3 tools/smoke-swiftpm-consumer.py" in workflow
    assert "--url https://github.com/thekaveh/VMx.git" in workflow
    assert '"$tag_version"' in workflow


def test_swift_release_separates_read_only_verification_from_write_authority() -> None:
    workflow = _workflow("release.yml")
    verify = workflow.split("\n  swift-verify:\n", maxsplit=1)[1].split(
        "\n  swift-release:\n", maxsplit=1
    )[0]
    release = workflow.split("\n  swift-release:\n", maxsplit=1)[1]

    assert "contents: read" in verify
    assert "contents: write" not in verify
    assert "needs: swift-verify" in release
    assert "contents: write" in release
    assert "gh release create" in release


def test_swift_release_uses_changelog_notes_after_verification() -> None:
    workflow = _workflow("release.yml")

    smoke_index = workflow.index("python3 tools/smoke-swiftpm-consumer.py")
    notes_index = workflow.index("name: Extract Swift release notes")
    release_index = workflow.index("gh release create", notes_index)

    assert smoke_index < notes_index < release_index
    assert "langs/swift/CHANGELOG.md" in workflow
    assert "--notes-file /tmp/swift-release-notes.md" in workflow


def test_swift_release_uses_portable_awk_next_heading_pattern() -> None:
    workflow = _workflow("release.yml")
    swift_job = workflow.split("\n  swift-release:\n", maxsplit=1)[1]

    assert r"capture && /^## \[/ { exit }" in swift_job
    assert r"capture && /^## \\[/ { exit }" not in swift_job


def test_release_contract_suite_triggers_on_swift_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert workflow.count('- ".github/workflows/**"') == 1
