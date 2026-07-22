"""Tests for the disposable local/public Rust crate consumer."""

from pathlib import Path

import pytest
import smoke_rust_consumer as smoke


def test_render_manifest_uses_packaged_path_and_declared_msrv() -> None:
    manifest = smoke.render_manifest(
        'vmx-rs = { path = "/tmp/vmx-rs-0.20.0" }',
        "1.88",
    )

    assert 'rust-version = "1.88"' in manifest
    assert 'vmx-rs = { path = "/tmp/vmx-rs-0.20.0" }' in manifest


def test_render_smoke_checks_version_lifecycle_and_command() -> None:
    source = smoke.render_smoke("0.20.0")

    assert 'VERSION, "0.20.0"' in source
    assert "vm.construct()?" in source
    assert "vm.destruct()?" in source
    assert "vm.dispose()?" in source
    assert "command.execute()" in source
    assert "executions.load" in source


def test_public_add_command_is_exact() -> None:
    assert smoke.public_add_command("cargo", "0.20.0") == [
        "cargo",
        "add",
        "vmx-rs@=0.20.0",
    ]


def test_local_package_generation_uses_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def fake_run(args: list[str], *, cwd: Path) -> None:
        captured.extend(args)
        tarball = cwd / "target/package/vmx-rs-0.20.0.crate"
        tarball.parent.mkdir(parents=True)
        tarball.touch()

    monkeypatch.setattr(smoke, "_run", fake_run)

    smoke._package(tmp_path, "0.20.0", "cargo")

    assert captured[:3] == ["cargo", "package", "--locked"]


def test_invalid_release_version_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"X\.Y\.Z"):
        smoke.render_smoke("main")


def test_wait_for_public_requires_registry_and_docs() -> None:
    crate_results = iter([False, True, True])
    docs_results = iter([False, False, True])
    sleeps: list[float] = []

    smoke.wait_for_public(
        "0.20.0",
        10,
        interval_seconds=1,
        crate_lookup=lambda _version: next(crate_results),
        docs_lookup=lambda _version: next(docs_results),
        sleeper=sleeps.append,
        clock=iter([0.0, 0.5, 1.0, 1.5]).__next__,
    )

    assert sleeps == [1, 1]


def test_find_extracted_crate_requires_exact_directory(tmp_path: Path) -> None:
    expected = tmp_path / "vmx-rs-0.20.0"
    expected.mkdir()

    assert smoke.find_extracted_crate(tmp_path, "0.20.0") == expected


def test_extracted_crate_runs_its_shipped_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(smoke, "_run", lambda args, *, cwd: calls.append((args, cwd)))

    smoke.test_extracted_crate(tmp_path, "cargo-msrv")

    assert calls == [(["cargo-msrv", "test", "--locked", "--all-features"], tmp_path)]
