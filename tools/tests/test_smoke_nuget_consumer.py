"""Unit tests for tools/smoke-nuget-consumer.py."""

from pathlib import Path

import pytest
import smoke_nuget_consumer as smoke


def test_parse_packages_accepts_known_exact_versions_and_adds_core_floor() -> None:
    packages = smoke.parse_packages(["VMx.Notifications=1.2.0"])

    assert packages == {"VMx": "3.23.0", "VMx.Notifications": "1.2.0"}


@pytest.mark.parametrize("specification", ["Unknown=1.0.0", "VMx=main", "VMx=3.20", "VMx"])
def test_parse_packages_rejects_unknown_or_non_exact_input(specification: str) -> None:
    with pytest.raises(ValueError):
        smoke.parse_packages([specification])


def test_render_project_pins_packages_and_framework() -> None:
    project = smoke.render_project(
        {"VMx": "3.20.0", "VMx.Extensions.DependencyInjection": "2.1.1"},
        "netstandard2.0",
    )

    assert "<TargetFramework>netstandard2.0</TargetFramework>" in project
    assert "<LangVersion>latest</LangVersion>" in project
    assert 'Include="VMx" Version="[3.20.0]"' in project
    assert 'Include="VMx.Extensions.DependencyInjection" Version="[2.1.1]"' in project


def test_render_source_probes_all_requested_assemblies_and_apis() -> None:
    source = smoke.render_source(
        {
            "VMx": "3.20.0",
            "VMx.Notifications": "1.2.0",
            "VMx.Extensions.DependencyInjection": "2.1.1",
        }
    )

    assert "new MessageHub()" in source
    assert "new NotificationHub()" in source
    assert "services => services.AddVMx()" in source
    assert 'Check(typeof(NotificationHub), "1.2.0")' in source
    assert 'Check(typeof(ServiceCollectionExtensions), "2.1.1")' in source


def test_render_source_uses_library_probe_for_netstandard() -> None:
    source = smoke.render_source({"VMx": "3.20.0"}, "netstandard2.0")

    assert "public static class Probe" in source
    assert "public static string Run()" in source
    assert "Console.WriteLine" not in source


def test_wait_for_packages_polls_until_every_exact_version_is_visible() -> None:
    responses = iter([False, True, False, True, True])
    sleeps: list[float] = []

    smoke.wait_for_packages(
        {"VMx": "3.20.0", "VMx.Notifications": "1.2.0"},
        1,
        interval_seconds=0.01,
        lookup=lambda _package, _version, _timeout: next(responses),
        sleeper=sleeps.append,
        clock=iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]).__next__,
    )

    assert sleeps == [0.01, 0.01]


def test_wait_for_packages_caps_lookup_and_sleep_to_end_to_end_deadline() -> None:
    timeouts: list[float] = []
    sleeps: list[float] = []

    with pytest.raises(TimeoutError, match="timed out waiting"):
        smoke.wait_for_packages(
            {"VMx": "3.20.0"},
            1,
            interval_seconds=5,
            lookup=lambda _package, _version, timeout: timeouts.append(timeout) or False,
            sleeper=sleeps.append,
            clock=iter([0.0, 0.2, 0.8, 1.0, 1.0]).__next__,
        )

    assert timeouts == pytest.approx([0.8])
    assert sleeps == pytest.approx([0.2])


def test_flat_container_url_normalizes_package_id() -> None:
    assert smoke.flat_container_url("VMx.Extensions.DependencyInjection") == (
        "https://api.nuget.org/v3-flatcontainer/vmx.extensions.dependencyinjection/index.json"
    )


def test_discover_packages_reads_current_project_versions(tmp_path: Path) -> None:
    project = tmp_path / "VMx" / "VMx.csproj"
    project.parent.mkdir()
    project.write_text(
        "<Project><PropertyGroup><PackageId>VMx</PackageId>"
        "<Version>3.20.0</Version></PropertyGroup></Project>",
        encoding="utf-8",
    )

    assert smoke.discover_packages(tmp_path) == {"VMx": "3.20.0"}


def test_main_handles_command_timeout_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise smoke.subprocess.TimeoutExpired(["dotnet"], 1)

    monkeypatch.setattr(smoke, "run_smoke", fail)

    assert smoke.main(["--package", "VMx=3.20.0", "--framework", "net8.0"]) == 1
    assert "ERROR: NuGet consumer smoke failed:" in capsys.readouterr().err
