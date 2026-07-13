"""Tests for the Rust crate package-content contract."""

import check_rust_package as checker


def test_expected_package_paths_are_accepted() -> None:
    assert checker.validate_paths(set(checker.REQUIRED_PATHS)) == []


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
