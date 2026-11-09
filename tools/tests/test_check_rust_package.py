"""Tests for the Rust crate package-content contract."""

import subprocess
from pathlib import Path

import check_rust_package as checker
import pytest

TRACKED = {
    "src/lib.rs",
    "src/forms.rs",
    "src/fixtures/lifecycle-transitions.json",
    "tests/conformance.rs",
    "tests/conformance/forms.rs",
}


def _package(tracked: set[str] = TRACKED) -> set[str]:
    return set(checker.FIXED_PATHS) | tracked


def test_expected_package_paths_are_accepted() -> None:
    assert checker.validate_paths(_package(), TRACKED) == []


def test_main_reports_package_timeout(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        checker,
        "package_paths",
        lambda _path: (_ for _ in ()).throw(subprocess.TimeoutExpired("cargo", 1)),
    )

    assert checker.main([]) == 2
    assert "unable to inspect Rust crate package" in capsys.readouterr().err


def test_a_new_tracked_conformance_file_needs_no_tool_edit() -> None:
    tracked = TRACKED | {"tests/conformance/brand_new_case.rs"}

    assert checker.validate_paths(_package(tracked), tracked) == []


def test_inventory_comes_from_the_files_git_tracks_in_the_crate() -> None:
    tracked = checker.tracked_source_paths(checker.DEFAULT_PACKAGE_DIR)

    assert {
        "src/lib.rs",
        "src/fixtures/lifecycle-transitions.json",
        "tests/conformance.rs",
    } <= tracked
    assert all(path.split("/", 1)[0] in checker.SOURCE_DIRS for path in tracked)


def test_main_accepts_the_tracked_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(checker, "package_paths", lambda _path: _package())
    monkeypatch.setattr(checker, "tracked_source_paths", lambda _path: set(TRACKED))

    assert checker.main(["--package-dir", str(tmp_path)]) == 0
    assert "OK: Rust crate package contains" in capsys.readouterr().out


def test_main_rejects_an_empty_tracked_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(checker, "package_paths", lambda _path: set(checker.FIXED_PATHS))
    monkeypatch.setattr(checker, "tracked_source_paths", lambda _path: set())

    assert checker.main(["--package-dir", str(tmp_path)]) == 2
    assert "Git tracks no files" in capsys.readouterr().err


def test_legal_texts_and_lockfile_are_fixed_package_files() -> None:
    assert {"LICENSE", "NOTICE", "Cargo.lock"} <= checker.FIXED_PATHS


def test_packaged_legal_texts_match_repository_sources() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    for name in ("LICENSE", "NOTICE"):
        assert (repository_root / f"langs/rust/{name}").read_bytes() == (
            repository_root / name
        ).read_bytes()


def test_package_listing_enforces_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout="Cargo.toml\n", stderr="")

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    checker.package_paths(tmp_path)

    assert captured[-2:] == ["--locked", "--list"]


@pytest.mark.parametrize("missing", ["src/lib.rs", "LICENSE", "Cargo.lock"])
def test_missing_runtime_source_is_reported(missing: str) -> None:
    paths = _package()
    paths.remove(missing)

    assert checker.validate_paths(paths, TRACKED) == [f"missing required package file: {missing}"]


def test_unexpected_test_or_secret_is_reported() -> None:
    paths = _package() | {
        ".env",
        "tests/scratch.rs",
    }

    assert checker.validate_paths(paths, TRACKED) == [
        "unexpected package file: .env (it is not a fixed top-level or generated crate file)",
        "unexpected package file: tests/scratch.rs (Git does not track it)",
    ]
