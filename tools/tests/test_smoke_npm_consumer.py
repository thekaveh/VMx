"""Unit tests for tools/smoke-npm-consumer.py."""

import json

import pytest
import smoke_npm_consumer as smoke


def test_render_package_json_uses_exact_package_and_consumer_dependencies() -> None:
    payload = json.loads(smoke.render_package_json("3.21.0"))

    assert payload["dependencies"]["@thekaveh/vmx"] == "3.21.0"
    assert payload["dependencies"]["rxjs"] == "^7.8.0"
    assert payload["devDependencies"]["typescript"] == "^5.4.0"
    assert payload["type"] == "module"


def test_render_esm_checks_all_entries_and_exact_version() -> None:
    source = smoke.render_esm("3.21.0")

    assert 'from "@thekaveh/vmx"' in source
    assert 'from "@thekaveh/vmx/notifications"' in source
    assert 'from "@thekaveh/vmx/conformance"' in source
    assert '__version__ !== "3.21.0"' in source


def test_render_commonjs_checks_all_entries_and_exact_version() -> None:
    source = smoke.render_commonjs("3.21.0")

    assert 'require("@thekaveh/vmx")' in source
    assert 'require("@thekaveh/vmx/notifications")' in source
    assert 'require("@thekaveh/vmx/conformance")' in source
    assert 'vmx.__version__ !== "3.21.0"' in source


def test_render_types_imports_declarations_from_all_entries() -> None:
    source = smoke.render_types()

    assert "type IMessageHub" in source
    assert "type INotificationHub" in source
    assert "type ConsumerConformanceSuite" in source


def test_typescript_command_uses_package_public_library_floor() -> None:
    command = smoke.typescript_command()

    assert command[-2:] == [
        "--lib",
        "ES2020,ES2022.Error,ESNext.Disposable,DOM",
    ]
    target_index = command.index("--target")
    assert command[target_index : target_index + 2] == ["--target", "ES2020"]


def test_json_array_ignores_ansi_and_lifecycle_output_before_npm_json() -> None:
    payload = [{"filename": "thekaveh-vmx-3.21.0.tgz"}]
    output = f"\x1b[36mCLI build [start]\x1b[0m\n{json.dumps(payload)}"

    assert smoke.json_array(output) == payload


def test_wait_for_version_polls_until_exact_version() -> None:
    responses = iter([None, "3.21.0"])
    sleeps: list[float] = []

    smoke.wait_for_version(
        "@thekaveh/vmx",
        "3.21.0",
        1,
        interval_seconds=0.01,
        lookup=lambda _package, _version: next(responses),
        sleeper=sleeps.append,
    )

    assert sleeps == [0.01]


def test_wait_for_version_times_out_when_exact_version_is_absent() -> None:
    with pytest.raises(TimeoutError, match=r"@thekaveh/vmx@3\.21\.0"):
        smoke.wait_for_version(
            "@thekaveh/vmx",
            "3.21.0",
            0,
            lookup=lambda _package, _version: None,
            sleeper=lambda _seconds: None,
        )


@pytest.mark.parametrize("version", ["main", "3.21", "v3.21.0", "3.21.0-beta.1"])
def test_renderers_reject_non_release_semver(version: str) -> None:
    with pytest.raises(ValueError, match=r"X\.Y\.Z"):
        smoke.render_esm(version)
