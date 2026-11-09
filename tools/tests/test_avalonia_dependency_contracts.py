"""Keep the Avalonia flagship package and test-host contracts aligned.

The project files are the source of the versions; the lock files must match
them, so a Dependabot update passes without an edit here (#1363). The package
set, the shared Avalonia version, and the Coverlet and xunit.v3 holds stay
checked.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "csharp" / "avalonia"
APP_PROJECT = EXAMPLE / "NotesShowcase" / "NotesShowcase.csproj"
TEST_PROJECT = EXAMPLE / "NotesShowcase.Tests" / "NotesShowcase.Tests.csproj"
APP_LOCK = EXAMPLE / "NotesShowcase" / "packages.lock.json"
TEST_LOCK = EXAMPLE / "NotesShowcase.Tests" / "packages.lock.json"

APP_PACKAGES = {"Avalonia", "Avalonia.Desktop", "Avalonia.Themes.Fluent", "Avalonia.Fonts.Inter"}
TEST_PACKAGES = {
    "Microsoft.NET.Test.Sdk",
    "xunit.v3",
    "xunit.runner.visualstudio",
    "Microsoft.Reactive.Testing",
    "coverlet.msbuild",
    "Avalonia.Headless.XUnit",
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
    app = _package_versions(APP_PROJECT)
    tests = _package_versions(TEST_PROJECT)
    assert set(app) == APP_PACKAGES
    assert set(tests) == TEST_PACKAGES
    for versions in (app, tests):
        assert all(
            version and re.fullmatch(r"\d+\.\d+\.\d+", version) for version in versions.values()
        )
    avalonia = {
        name: version for name, version in {**app, **tests}.items() if name.startswith("Avalonia")
    }
    assert len(set(avalonia.values())) == 1, f"Avalonia packages must share one version: {avalonia}"


def test_avalonia_test_host_keeps_its_holds() -> None:
    tests = _package_versions(TEST_PROJECT)
    config = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    assert tests["coverlet.msbuild"] not in ("10.0.1", "10.1.0"), (
        "hold: coverlet.msbuild 10.0.1 and 10.1.0 produce invalid IL (contract ledger section 2)"
    )
    assert re.search(
        r'dependency-name: coverlet\.msbuild\n\s+versions: \["10\.0\.1", "10\.1\.0"\]', config
    )
    assert (tests["xunit.v3"] or "").split(".")[0] == "3", (
        "hold: xunit.v3 4+ waits for the Microsoft.Testing.Platform migration (#523)"
    )
    assert re.search(r'dependency-name: xunit\.v3\n\s+versions: \[">=4\.0\.0"\]', config)


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
    _assert_direct_lock_metadata(APP_LOCK, "net8.0", _package_versions(APP_PROJECT))
    _assert_direct_lock_metadata(TEST_LOCK, "net9.0", _package_versions(TEST_PROJECT))
