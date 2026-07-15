"""Tests for the Rust crate package-content contract."""

import subprocess
from pathlib import Path

import check_rust_package as checker
import pytest


def test_expected_package_paths_are_accepted() -> None:
    assert checker.validate_paths(set(checker.REQUIRED_PATHS)) == []


def test_extracted_runtime_modules_are_allowlisted() -> None:
    assert {
        "src/aggregates.rs",
        "src/async_value.rs",
        "src/capabilities.rs",
        "src/commands.rs",
        "src/components.rs",
        "src/collections.rs",
        "src/derived_property.rs",
        "src/discriminator.rs",
        "src/dialogs.rs",
        "src/forms.rs",
        "src/forwarding.rs",
        "src/groups.rs",
        "src/hierarchical.rs",
        "src/modeled_crud.rs",
        "src/notifications.rs",
        "src/paged_composition.rs",
        "src/searchable_state.rs",
        "src/specialized_vms.rs",
        "src/token_paging.rs",
    } <= checker.REQUIRED_PATHS


def test_license_text_is_allowlisted() -> None:
    assert "LICENSE" in checker.REQUIRED_PATHS


def test_packaged_license_matches_repository_license() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    assert (repository_root / "langs/rust/LICENSE").read_bytes() == (
        repository_root / "LICENSE"
    ).read_bytes()


def test_package_listing_enforces_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout="Cargo.toml\n", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    checker.package_paths(tmp_path)

    assert captured[-2:] == ["--locked", "--list"]


def test_missing_runtime_source_is_reported() -> None:
    paths = set(checker.REQUIRED_PATHS)
    paths.remove("src/lib.rs")

    assert checker.validate_paths(paths) == ["missing required package file: src/lib.rs"]


def test_unexpected_test_or_secret_is_reported() -> None:
    paths = set(checker.REQUIRED_PATHS) | {
        ".env",
        "tests/scratch.rs",
    }

    assert checker.validate_paths(paths) == [
        "unexpected package file: .env",
        "unexpected package file: tests/scratch.rs",
    ]
