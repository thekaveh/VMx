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
    assert "BatchUpdateHandle" in source
    assert "Symbol.dispose" in source


def test_render_commonjs_checks_all_entries_and_exact_version() -> None:
    source = smoke.render_commonjs("3.21.0")

    assert 'require("@thekaveh/vmx")' in source
    assert 'require("@thekaveh/vmx/notifications")' in source
    assert 'require("@thekaveh/vmx/conformance")' in source
    assert 'vmx.__version__ !== "3.21.0"' in source
    assert "vmx.BatchUpdateHandle" in source
    assert "Symbol.dispose" in source


def test_render_types_imports_declarations_from_all_entries() -> None:
    source = smoke.render_types()

    assert "BatchUpdateHandle" in source
    assert "Disposable" in source
    assert "[Symbol.dispose]" in source
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
        lookup=lambda _package, _version, _timeout: next(responses),
        sleeper=sleeps.append,
    )

    assert sleeps == [0.01]


def test_wait_for_version_times_out_when_exact_version_is_absent() -> None:
    with pytest.raises(TimeoutError, match=r"@thekaveh/vmx@3\.21\.0"):
        smoke.wait_for_version(
            "@thekaveh/vmx",
            "3.21.0",
            0,
            lookup=lambda _package, _version, _timeout: None,
            sleeper=lambda _seconds: None,
        )


def test_registry_lookup_is_bounded_by_remaining_poll_time(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[float] = []

    def fake_run(*_args: object, **kwargs: object) -> object:
        observed.append(float(kwargs["timeout"]))
        return type("Result", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke._registry_version("@thekaveh/vmx", "3.21.0", 2.5) is None
    assert observed == [2.5]


def test_wait_for_provenance_polls_until_attestation_is_visible() -> None:
    responses = iter([False, True])
    sleeps: list[float] = []

    smoke.wait_for_provenance(
        "@thekaveh/vmx",
        "3.21.0",
        1,
        interval_seconds=0.01,
        lookup=lambda _package, _version, _timeout: next(responses),
        sleeper=sleeps.append,
    )

    assert sleeps == [0.01]


def test_main_handles_command_timeout_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise smoke.subprocess.TimeoutExpired(["npm"], 1)

    monkeypatch.setattr(smoke, "run_smoke", fail)

    assert smoke.main(["--version", "3.21.0"]) == 1
    assert "ERROR: npm consumer smoke failed:" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["main", "3.21", "v3.21.0", "3.21.0-beta.1"])
def test_renderers_reject_non_release_semver(version: str) -> None:
    with pytest.raises(ValueError, match=r"X\.Y\.Z"):
        smoke.render_esm(version)
