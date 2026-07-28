"""Keep the Avalonia flagship package and test-host contracts aligned."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "csharp" / "avalonia"
APP_PROJECT = EXAMPLE / "NotesShowcase" / "NotesShowcase.csproj"
TEST_PROJECT = EXAMPLE / "NotesShowcase.Tests" / "NotesShowcase.Tests.csproj"
APP_LOCK = EXAMPLE / "NotesShowcase" / "packages.lock.json"
TEST_LOCK = EXAMPLE / "NotesShowcase.Tests" / "packages.lock.json"

APP_PACKAGES = {
    "Avalonia": "12.1.0",
    "Avalonia.Desktop": "12.1.0",
    "Avalonia.Themes.Fluent": "12.1.0",
    "Avalonia.Fonts.Inter": "12.1.0",
}
TEST_PACKAGES = {
    "Microsoft.NET.Test.Sdk": "18.8.1",
    "xunit.v3": "3.2.2",
    "xunit.runner.visualstudio": "3.1.5",
    "Microsoft.Reactive.Testing": "7.0.0",
    "coverlet.msbuild": "10.0.0",
    "Avalonia.Headless.XUnit": "12.1.0",
}


def _properties(project: Path) -> dict[str, str]:
    root = ET.parse(project).getroot()
    return {
        child.tag: (child.text or "").strip()
        for group in root.findall("PropertyGroup")
        for child in group
    }


def _package_versions(project: Path) -> dict[str, str | None]:
    root = ET.parse(project).getroot()
    return {
        package.get("Include", ""): package.get("Version")
        for package in root.findall(".//PackageReference")
    }


def _assert_direct_lock_metadata(
    lockfile: Path,
    target: str,
    expected_versions: dict[str, str],
) -> None:
    dependencies = json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]
    assert set(dependencies) == {target}

    packages = dependencies[target]
    actual = {
        package: {key: packages[package][key] for key in ("type", "requested", "resolved")}
        for package in expected_versions
    }
    expected = {
        package: {
            "type": "Direct",
            "requested": f"[{version}, )",
            "resolved": version,
        }
        for package, version in expected_versions.items()
    }
    assert actual == expected


def test_avalonia_projects_pin_the_reviewed_package_stack() -> None:
    assert _package_versions(APP_PROJECT) == APP_PACKAGES
    assert _package_versions(TEST_PROJECT) == TEST_PACKAGES


def test_avalonia_test_host_uses_the_xunit_v3_executable_contract() -> None:
    properties = _properties(TEST_PROJECT)

    assert properties["TargetFramework"] == "net9.0"
    assert properties["OutputType"] == "Exe"
    assert properties["IsTestProject"] == "true"


def test_avalonia_app_explicitly_preserves_reflection_bindings() -> None:
    properties = _properties(APP_PROJECT)

    assert properties["TargetFramework"] == "net8.0"
    assert properties["AvaloniaUseCompiledBindingsByDefault"] == "false"


def test_avalonia_lockfiles_match_project_targets_and_direct_metadata() -> None:
    _assert_direct_lock_metadata(APP_LOCK, "net8.0", APP_PACKAGES)
    _assert_direct_lock_metadata(TEST_LOCK, "net9.0", TEST_PACKAGES)
