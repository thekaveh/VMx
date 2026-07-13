"""Contract tests for Rust package and crates.io release workflows."""

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
    assert "cargo package --manifest-path langs/rust/Cargo.toml" in workflow
    assert "python3 tools/check-rust-package.py" in workflow
    assert "python3 tools/smoke-rust-consumer.py" in workflow
    assert "--package-dir langs/rust" in workflow


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
        "cargo clippy --manifest-path langs/rust/Cargo.toml "
        "--all-targets --all-features -- -D warnings",
        "cargo test --manifest-path langs/rust/Cargo.toml --all-features",
        "cargo doc --manifest-path langs/rust/Cargo.toml --all-features --no-deps",
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
    assert "if: env.CRATES_IO_TOKEN != ''" in jobs
    assert "CARGO_REGISTRY_TOKEN: ${{ env.CRATES_IO_TOKEN }}" in jobs
    assert "if: env.CRATES_IO_TOKEN == ''" in jobs
    assert "rust-lang/crates-io-auth-action@" in jobs
    assert "CARGO_REGISTRY_TOKEN: ${{ steps.auth.outputs.token }}" in jobs
    assert jobs.count("cargo publish --manifest-path langs/rust/Cargo.toml") == 2
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
