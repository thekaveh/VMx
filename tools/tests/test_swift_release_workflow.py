"""Contract tests for Swift package and release GitHub Actions."""

import re
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
    assert "needs: [swift-verify, release-metadata]" in release
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


def test_swift_release_uses_the_shared_release_notes_extractor() -> None:
    workflow = _workflow("release.yml")
    swift_job = workflow.split("\n  swift-release:\n", maxsplit=1)[1]

    assert (
        'awk -v v="$tag_version" -f tools/extract-release-notes.awk langs/swift/CHANGELOG.md'
        in swift_job
    )


def test_release_contract_suite_triggers_on_swift_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert workflow.count('- ".github/workflows/**"') == 1


def _job(workflow: str, name: str) -> str:
    """One job of a workflow, up to the next job key."""
    body = workflow.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"(?m)^  [A-Za-z0-9_-]+:\n", body, maxsplit=1)[0]


def test_swift_release_gate_tests_on_an_image_of_the_ci_build_matrix() -> None:
    # #1470: a failure on an image that CI never tested first showed up after
    # the release tags were pushed.
    verify = _job(_workflow("release.yml"), "swift-verify")
    build = _job(_workflow("swift.yml"), "build")
    image = re.search(r"(?m)^    runs-on: (\S+)$", verify)
    assert image is not None
    assert f"- os: {image.group(1)}\n" in build
    steps = verify.split("\n      - ")
    version = next(i for i, step in enumerate(steps) if "run: swift --version" in step)
    first_build = next(i for i, step in enumerate(steps) if "swift build" in step)
    assert version < first_build
    assert '--configuration "${{ matrix.os }} ${{ matrix.label }}"' in build


def test_swift_ci_runs_the_library_tests_under_thread_sanitizer() -> None:
    # #1407: TSan runs on every pull request, and a report fails the job.
    workflow = _workflow("swift.yml")
    job = _job(workflow, "thread-sanitizer")
    command = " ".join(job.split())
    assert "runs-on: macos-15" in job
    assert "TSAN_OPTIONS: halt_on_error=1" in job
    assert (
        "python3 tools/swift-test-watchdog.py --per-test-timeout 240"
        " -- swift test --package-path langs/swift --sanitize=thread"
    ) in command
    assert "needs: [build, platforms, examples, coverage, thread-sanitizer]" in workflow


def test_swift_single_process_runs_name_and_stop_a_hung_case() -> None:
    # #1461: the coverage run is one process, so the watchdog reads XCTest's
    # output, and the test target ends a hung run by itself.
    coverage = " ".join(_job(_workflow("swift.yml"), "coverage").split())
    assert (
        "python3 tools/swift-test-watchdog.py --per-test-timeout 240"
        " -- swift test --package-path langs/swift --enable-code-coverage"
    ) in coverage
    guard = (REPO_ROOT / "langs/swift/Tests/VMxTests/TestCaseHangGuard.swift").read_text(
        encoding="utf-8"
    )
    assert "override class var defaultTestSuite: XCTestSuite" in guard
    assert "_exit(EXIT_FAILURE)" in guard
    tests = (REPO_ROOT / "langs/swift/Tests/VMxTests/CompositeVMTests.swift").read_text(
        encoding="utf-8"
    )
    # The helper's definition and the four COMP-026 deadlock guards.
    assert tests.count("waitForWorkersOrEndTheProcess(") == 1 + 4
