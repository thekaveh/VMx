"""Unit tests for tools/smoke-swiftpm-consumer.py."""

from pathlib import Path

import pytest
import smoke_swiftpm_consumer as smoke


def test_render_manifest_uses_public_from_dependency() -> None:
    manifest = smoke.render_manifest(
        "https://github.com/thekaveh/VMx.git",
        "3.20.0",
    )

    assert '.package(url: "https://github.com/thekaveh/VMx.git", from: "3.20.0")' in manifest
    assert '.product(name: "VMx", package: "vmx")' in manifest
    assert ".macOS(.v13)" in manifest


def test_render_main_checks_version_and_lifecycle_round_trip() -> None:
    source = smoke.render_main("3.20.0")

    assert 'VMxVersion.current == "3.20.0"' in source
    assert "try vm.construct()" in source
    assert "try vm.destruct()" in source
    assert "vm.dispose()" in source
    assert "vm.status == .disposed" in source


def test_render_manifest_rejects_non_semver_version() -> None:
    with pytest.raises(ValueError, match="semantic version"):
        smoke.render_manifest("https://github.com/thekaveh/VMx.git", "main")


def test_validate_resources_accepts_all_fixture_names(tmp_path: Path) -> None:
    bundle = tmp_path / "debug" / "VMx_VMx.bundle"
    bundle.mkdir(parents=True)
    for name in smoke.EXPECTED_RESOURCES:
        (bundle / name).write_text("{}\n", encoding="utf-8")

    smoke.validate_resources(tmp_path)


def test_validate_resources_reports_every_missing_fixture(tmp_path: Path) -> None:
    bundle = tmp_path / "debug" / "VMx_VMx.bundle"
    bundle.mkdir(parents=True)
    (bundle / "lifecycle-transitions.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError) as caught:
        smoke.validate_resources(tmp_path)

    message = str(caught.value)
    assert "command-truthtable.json" in message
    assert "derived-properties.json" in message
    assert "message-ordering.json" in message
