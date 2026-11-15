"""Unit tests for tools/check-react-package.py."""

import json
import subprocess
from pathlib import Path

import check_react_package as crp
import pytest

EXPECTED_PAYLOAD = {
    "package/package.json",
    "package/README.md",
    "package/LICENSE",
    "package/NOTICE",
    "package/dist/index.js",
    "package/dist/index.cjs",
    "package/dist/index.d.ts",
    "package/dist/index.d.cts",
}

VALID_MANIFEST = {
    "name": "@thekaveh/vmx-react",
    "peerDependencies": {
        "@thekaveh/vmx": "^3.30.0",
        "react": "^18.3.1 || ^19.0.0",
        "rxjs": "^7.8.0",
        "use-sync-external-store": "^1.6.0",
    },
}


def _stub_npm_pack(monkeypatch: pytest.MonkeyPatch, paths: set[str]) -> None:
    payload = [{"files": [{"path": path.removeprefix("package/")} for path in sorted(paths)]}]
    completed = subprocess.CompletedProcess(
        args=["npm", "pack"], returncode=0, stdout=json.dumps(payload), stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: completed)


def _write_manifest(directory: Path, manifest: dict) -> None:
    (directory / "package.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_validate_paths_accepts_the_exact_payload() -> None:
    assert crp.validate_paths(EXPECTED_PAYLOAD) == []


def test_validate_paths_reports_each_missing_required_file() -> None:
    paths = EXPECTED_PAYLOAD - {"package/NOTICE", "package/dist/index.cjs"}

    assert crp.validate_paths(paths) == [
        "missing required package file: package/NOTICE",
        "missing required package file: package/dist/index.cjs",
    ]


def test_validate_paths_reports_each_unexpected_file_by_name() -> None:
    paths = EXPECTED_PAYLOAD | {
        "package/dist/index.js.map",
        "package/src/index.ts",
        "package/.env",
    }

    assert crp.validate_paths(paths) == [
        "unexpected package file: package/.env",
        "unexpected package file: package/dist/index.js.map",
        "unexpected package file: package/src/index.ts",
    ]


def test_validate_manifest_accepts_all_four_peer_dependencies() -> None:
    assert crp.validate_manifest(VALID_MANIFEST) == []


def test_validate_manifest_requires_the_rxjs_peer() -> None:
    manifest = {
        **VALID_MANIFEST,
        "peerDependencies": {
            name: version
            for name, version in VALID_MANIFEST["peerDependencies"].items()
            if name != "rxjs"
        },
    }

    assert crp.validate_manifest(manifest) == ["missing peer dependency: rxjs"]


def test_validate_manifest_requires_the_canonical_package_name() -> None:
    manifest = {**VALID_MANIFEST, "name": "wrong-name"}

    assert crp.validate_manifest(manifest) == ["unexpected React adapter package name"]


def test_package_contents_packs_without_lifecycle_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps([{"files": [{"path": "package.json"}]}]),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert crp.package_contents() == {"package/package.json"}
    assert "--ignore-scripts" in calls[0]
    assert "--json" in calls[0]


def test_main_passes_on_the_exact_payload_and_valid_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _stub_npm_pack(monkeypatch, EXPECTED_PAYLOAD)

    assert crp.main() == 0
    assert "OK: React adapter package metadata and payload are complete" in capsys.readouterr().out


def test_main_fails_on_extra_payload_file_outside_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _stub_npm_pack(monkeypatch, EXPECTED_PAYLOAD | {"package/dist/index.js.map"})

    assert crp.main() == 1
    assert "unexpected package file: package/dist/index.js.map" in capsys.readouterr().err


def test_main_fails_on_missing_required_file(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _stub_npm_pack(monkeypatch, EXPECTED_PAYLOAD - {"package/NOTICE"})

    assert crp.main() == 1
    assert "missing required package file: package/NOTICE" in capsys.readouterr().err


def test_main_reports_manifest_and_payload_errors_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    manifest = {
        **VALID_MANIFEST,
        "peerDependencies": {
            name: version
            for name, version in VALID_MANIFEST["peerDependencies"].items()
            if name != "rxjs"
        },
    }
    _write_manifest(tmp_path, manifest)
    monkeypatch.setattr(crp, "PACKAGE", tmp_path)
    _stub_npm_pack(monkeypatch, EXPECTED_PAYLOAD | {"package/src/index.ts"})

    assert crp.main() == 1
    err = capsys.readouterr().err
    assert "ERROR: missing peer dependency: rxjs" in err
    assert "ERROR: unexpected package file: package/src/index.ts" in err
