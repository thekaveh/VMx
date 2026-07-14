"""Contract tests for Rust package and crates.io release workflows."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_rust_ci_triggers_for_package_verification_tools() -> None:
    workflow = _workflow("rust.yml")

    assert '- "tools/check-rust-package.py"' in workflow
    assert '- "tools/smoke-rust-consumer.py"' in workflow


def test_rust_ci_verifies_packaged_consumers_on_msrv_and_stable() -> None:
    workflow = _workflow("rust.yml")

    assert "name: package (${{ matrix.toolchain }})" in workflow
    assert 'toolchain: ["1.88.0", "stable"]' in workflow
    assert "cargo package --locked --manifest-path langs/rust/Cargo.toml" in workflow
    assert "cargo test --locked --manifest-path langs/rust/Cargo.toml" in workflow
    assert "python3 tools/check-rust-package.py" in workflow
    assert "python3 tools/smoke-rust-consumer.py" in workflow
    assert "--package-dir langs/rust" in workflow


def test_rust_ci_keeps_example_lockfiles_immutable() -> None:
    workflow = _workflow("rust.yml")

    assert (
        "cargo run --locked --manifest-path examples/rust/console/hello-vmx/Cargo.toml" in workflow
    )
    assert (
        "cargo test --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml"
        in workflow
    )
    assert (
        "cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke"
        in workflow
    )


def test_rust_application_example_lockfiles_are_committed_by_policy() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for relative in (
        "examples/rust/console/hello-vmx/Cargo.lock",
        "examples/rust/tui/notes-showcase/Cargo.lock",
    ):
        assert (REPO_ROOT / relative).is_file()
        assert f"!/{relative}" in gitignore


def test_rust_library_lockfile_is_committed_and_ci_uses_it() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    workflow = _workflow("rust.yml")

    assert (REPO_ROOT / "langs/rust/Cargo.lock").is_file()
    assert "!/langs/rust/Cargo.lock" in gitignore
    assert "cargo clippy --locked --manifest-path langs/rust/Cargo.toml" in workflow


def test_rust_examples_do_not_claim_a_lower_msrv_than_vmx() -> None:
    def read_msrv(path: Path) -> tuple[int, ...] | None:
        match = re.search(
            r'^rust-version = "([0-9.]+)"$',
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        return tuple(int(part) for part in match.group(1).split(".")) if match else None

    library_msrv = read_msrv(REPO_ROOT / "langs/rust/Cargo.toml")
    assert library_msrv is not None

    for manifest_path in (
        REPO_ROOT / "examples/rust/console/hello-vmx/Cargo.toml",
        REPO_ROOT / "examples/rust/tui/notes-showcase/Cargo.toml",
    ):
        example_msrv = read_msrv(manifest_path)
        assert example_msrv is not None, f"{manifest_path} must declare rust-version"
        assert example_msrv >= library_msrv


def test_rust_test_only_json_dependency_is_not_published_at_runtime() -> None:
    manifest = (REPO_ROOT / "langs/rust/Cargo.toml").read_text(encoding="utf-8")
    runtime, development = manifest.split("[dev-dependencies]", maxsplit=1)

    assert "serde_json" not in runtime
    assert 'serde_json = "1.0.145"' in development


def test_rust_reactive_facade_has_no_unused_backend_dependency_or_claim() -> None:
    manifest = (REPO_ROOT / "langs/rust/Cargo.toml").read_text(encoding="utf-8")
    assert "rxrust" not in manifest

    for relative in (
        "AGENTS.md",
        "README.md",
        "langs/rust/README.md",
        "docs/content/installation.md",
        "docs/content/flavors/index.md",
        "docs/content/flavors/rust.md",
    ):
        content = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "rxrust" not in content, f"stale backend claim in {relative}"


def test_contract_suite_triggers_on_rust_and_release_workflow_changes() -> None:
    workflow = _workflow("conformance.yml")

    assert workflow.count('- ".github/workflows/rust.yml"') == 2
    assert workflow.count('- ".github/workflows/release.yml"') == 2


def _rust_release_jobs() -> str:
    workflow = _workflow("release.yml")
    return workflow.split("\n  rust-test:\n", maxsplit=1)[1].split("\n  swift:\n", maxsplit=1)[0]


def test_release_runs_msrv_stable_and_five_flavor_gates_before_publish() -> None:
    jobs = _rust_release_jobs()

    assert 'toolchain: ["1.88.0", "stable"]' in jobs
    for command in (
        "cargo fmt --manifest-path langs/rust/Cargo.toml -- --check",
        "cargo clippy --locked --manifest-path langs/rust/Cargo.toml "
        "--all-targets --all-features -- -D warnings",
        "cargo test --locked --manifest-path langs/rust/Cargo.toml --all-features",
        "cargo doc --locked --manifest-path langs/rust/Cargo.toml --all-features --no-deps",
        "python3 tools/check-rust-package.py",
        "python3 tools/smoke-rust-consumer.py",
        "tools/check-conformance-coverage.py --require csharp --require python "
        "--require typescript --require swift --require rust",
    ):
        assert command in jobs
    assert "needs: [rust-test, rust-conformance]" in jobs


def test_release_rejects_non_main_or_mismatched_tag_before_authentication() -> None:
    jobs = _rust_release_jobs()

    ancestry = jobs.index('git merge-base --is-ancestor "$GITHUB_SHA" origin/main')
    version = jobs.index('tag_version="${GITHUB_REF#refs/tags/rust-v}"')
    auth = jobs.index("name: Authenticate with crates.io trusted publishing")

    assert ancestry < auth
    assert version < auth
    assert "startsWith(github.ref, 'refs/tags/rust-v')" in jobs


def test_release_has_protected_mutually_exclusive_bootstrap_and_oidc_paths() -> None:
    jobs = _rust_release_jobs()

    assert "environment:\n      name: crates-rust" in jobs
    assert "id-token: write" in jobs
    assert "CRATES_IO_TOKEN: ${{ secrets.CRATES_IO_TOKEN }}" in jobs
    assert "if: steps.crates-auth-mode.outputs.bootstrap == 'true'" in jobs
    assert "CARGO_REGISTRY_TOKEN: ${{ secrets.CRATES_IO_TOKEN }}" in jobs
    assert "if: steps.crates-auth-mode.outputs.bootstrap != 'true'" in jobs
    assert "rust-lang/crates-io-auth-action@" in jobs
    assert "CARGO_REGISTRY_TOKEN: ${{ steps.auth.outputs.token }}" in jobs
    assert jobs.count("cargo publish --locked --manifest-path langs/rust/Cargo.toml") == 2
    assert "--allow-dirty" not in jobs


def test_release_polls_registry_docs_and_public_consumers_before_notes() -> None:
    jobs = _rust_release_jobs()

    verify = jobs.index("rust-verify-published:")
    notes = jobs.index("rust-release-notes:")
    create = jobs.index("gh release create", notes)

    assert 'toolchain: ["1.88.0", "stable"]' in jobs
    assert "--poll-timeout 1800" in jobs
    assert "needs: rust-publish" in jobs
    assert "needs: rust-verify-published" in jobs
    assert "langs/rust/CHANGELOG.md" in jobs
    assert verify < notes < create
