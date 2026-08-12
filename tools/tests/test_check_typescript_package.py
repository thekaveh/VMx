"""Unit tests for tools/check-typescript-package.py."""

import json
import subprocess

import check_typescript_package as ctsp
import pytest


def test_main_reports_package_timeout(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        ctsp,
        "package_contents",
        lambda _path: (_ for _ in ()).throw(subprocess.TimeoutExpired("npm", 1)),
    )

    assert ctsp.main([]) == 2
    assert "unable to inspect npm package" in capsys.readouterr().err


def _valid_paths() -> set[str]:
    paths = {
        "LICENSE",
        "NOTICE",
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
        "dist/formVm-Ab12Cd34.d.ts",
        "dist/formVm-Ef56Gh78.d.cts",
        "dist/messageHub-Ab12Cd34.d.ts",
        "dist/messageHub-Ab12Cd34.d.cts",
    }
    for entry in ("index", "notifications", "conformance", "testing", "devtools"):
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


def test_testing_entry_is_a_required_package_contract() -> None:
    assert "testing" in ctsp.ENTRIES

    paths = _valid_paths()
    paths.remove("dist/testing.d.cts")

    assert ctsp.validate_paths(paths) == ["missing required package file: dist/testing.d.cts"]


def test_devtools_entry_is_a_required_package_contract() -> None:
    assert "devtools" in ctsp.ENTRIES

    paths = _valid_paths()
    paths.remove("dist/devtools.d.cts")

    assert ctsp.validate_paths(paths) == ["missing required package file: dist/devtools.d.cts"]


def test_validate_name_requires_the_canonical_publish_target() -> None:
    assert ctsp.validate_name("@thekaveh/vmx") == []
    assert ctsp.validate_name("wrong-name") == [
        "package name 'wrong-name' != expected '@thekaveh/vmx'"
    ]


def test_main_rejects_wrong_packed_package_name(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(ctsp, "package_contents", lambda _path: ("wrong-name", _valid_paths()))

    assert ctsp.main([]) == 1
    assert "package name 'wrong-name' != expected '@thekaveh/vmx'" in capsys.readouterr().err


def test_legal_files_are_required() -> None:
    assert {"LICENSE", "NOTICE"} <= ctsp.REQUIRED_PATHS


def test_validate_paths_reports_missing_entry_declaration() -> None:
    paths = _valid_paths()
    paths.remove("dist/conformance.d.cts")

    errors = ctsp.validate_paths(paths)

    assert errors == ["missing required package file: dist/conformance.d.cts"]


def test_validate_paths_requires_form_harness_declaration_chunks() -> None:
    paths = {path for path in _valid_paths() if not path.startswith("dist/formVm-")}

    assert ctsp.validate_paths(paths) == ["missing generated declaration chunk pair"]


def test_validate_paths_requires_devtools_message_hub_declaration_chunks() -> None:
    paths = {path for path in _valid_paths() if not path.startswith("dist/messageHub-")}

    assert ctsp.validate_paths(paths) == ["missing generated declaration chunk pair"]


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


def test_json_array_ignores_ansi_and_lifecycle_output_before_npm_json() -> None:
    payload = [{"files": [{"path": "package.json"}]}]
    output = f"\x1b[36mCLI build [start]\x1b[0m\n{json.dumps(payload)}"

    assert ctsp.json_array(output) == payload
