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
    swift_job = workflow.split("\n  swift:\n", maxsplit=1)[1]

    assert r"capture && /^## \[/ { exit }" in swift_job
    assert r"capture && /^## \\[/ { exit }" not in swift_job


def test_release_contract_suite_triggers_on_swift_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert '- ".github/workflows/swift.yml"' in workflow
    assert '- ".github/workflows/release.yml"' in workflow
