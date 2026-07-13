"""Unit tests for tools/check-typescript-package.py."""

import check_typescript_package as ctsp


def _valid_paths() -> set[str]:
    paths = {
        "README.md",
        "package.json",
        "src/fixtures/command-truthtable.json",
        "src/fixtures/derived-properties.json",
        "src/fixtures/lifecycle-transitions.json",
        "src/fixtures/message-ordering.json",
        "dist/chunk-AAAA1111.js",
        "dist/chunk-AAAA1111.js.map",
        "dist/chunk-BBBB2222.cjs",
        "dist/chunk-BBBB2222.cjs.map",
        "dist/relayCommand-Ab12Cd34.d.ts",
        "dist/relayCommand-Ab12Cd34.d.cts",
    }
    for entry in ("index", "notifications", "conformance"):
        paths.update(
            {
                f"dist/{entry}.js",
                f"dist/{entry}.js.map",
                f"dist/{entry}.cjs",
                f"dist/{entry}.cjs.map",
                f"dist/{entry}.d.ts",
                f"dist/{entry}.d.cts",
            }
        )
    return paths


def test_validate_paths_accepts_expected_entries_fixtures_and_chunks() -> None:
    assert ctsp.validate_paths(_valid_paths()) == []


def test_validate_paths_reports_missing_entry_declaration() -> None:
    paths = _valid_paths()
    paths.remove("dist/conformance.d.cts")

    errors = ctsp.validate_paths(paths)

    assert errors == ["missing required package file: dist/conformance.d.cts"]


def test_validate_paths_rejects_unexpected_source_or_secret() -> None:
    paths = _valid_paths() | {"src/index.ts", ".env"}

    errors = ctsp.validate_paths(paths)

    assert "unexpected package file: .env" in errors
    assert "unexpected package file: src/index.ts" in errors


def test_validate_paths_requires_runtime_and_declaration_chunks() -> None:
    paths = {
        path
        for path in _valid_paths()
        if not path.startswith("dist/chunk-") and not path.startswith("dist/relayCommand-")
    }

    errors = ctsp.validate_paths(paths)

    assert "missing generated ESM chunk and source map" in errors
    assert "missing generated CommonJS chunk and source map" in errors
    assert "missing generated declaration chunk pair" in errors
