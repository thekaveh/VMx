"""Keep C# central package pins, committed lock files, and holds aligned.

The expected versions come from `langs/csharp/Directory.Packages.props`, so a
Dependabot update of a central version passes with only that file and the
regenerated lock files (#1363). Deliberate holds stay literal, and a test fails
and names the hold when one changes. Each lock file must hold a section for
every target framework of its project, and the .NET servicing family must move
together (#1361).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from check_nuget_package import central_package_versions

ROOT = Path(__file__).resolve().parents[2]
C_SHARP = ROOT / "langs" / "csharp"
PINS = central_package_versions(C_SHARP / "Directory.Packages.props")
LOCKFILES = sorted(
    path
    for root in (C_SHARP, ROOT / "examples" / "csharp")
    for path in root.rglob("packages.lock.json")
    if "bin" not in path.parts and "obj" not in path.parts
)
LEDGER = ROOT / "docs/maintenance/2026-07-01-contract-ledger.md"
DEPENDABOT = ROOT / ".github/dependabot.yml"
# dotnet/runtime ships these packages in one servicing release. Dependabot opens
# one pull request per package, so a check names the members left behind (#1361).
SERVICING_FAMILY = (
    "Microsoft.Bcl.AsyncInterfaces",
    "Microsoft.Extensions.DependencyInjection.Abstractions",
    "System.Collections.Immutable",
    "System.Text.Json",
)
# Deliberate holds: the held version and the Dependabot ignore range that keeps it.
HOLDS = {"Microsoft.Extensions.DependencyInjection": ("8.0.1", ">=9.0.0")}
LEDGER_HOLD = "`Microsoft.Extensions.DependencyInjection` remains `8.0.1`"


def regeneration_command(lockfile: Path) -> str:
    """Return the command that regenerates a lock file with every target section."""
    if lockfile.is_relative_to(C_SHARP):
        return "dotnet restore langs/csharp/VMx.sln --force-evaluate"
    project = next(lockfile.parent.glob("*.csproj"))
    return f"dotnet restore {project.relative_to(ROOT).as_posix()} --force-evaluate"


def lock_section(framework: str) -> str:
    match = re.fullmatch(r"netstandard(\d+\.\d+)", framework)
    return f".NETStandard,Version=v{match.group(1)}" if match else framework


def project_frameworks(lockfile: Path) -> set[str]:
    project = next(lockfile.parent.glob("*.csproj"))
    root = ET.parse(project).getroot()
    value = root.findtext("PropertyGroup/TargetFrameworks") or root.findtext(
        "PropertyGroup/TargetFramework"
    )
    assert value, f"{project} declares no target framework"
    return {lock_section(item.strip()) for item in value.split(";") if item.strip()}


def lock_dependencies(lockfile: Path) -> dict[str, dict[str, dict[str, object]]]:
    return json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]


def test_lock_files_are_found() -> None:
    assert len(LOCKFILES) >= 8


@pytest.mark.parametrize("lockfile", LOCKFILES, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_lock_file_has_a_section_for_each_project_target(lockfile: Path) -> None:
    sections = set(lock_dependencies(lockfile))
    expected = project_frameworks(lockfile)

    assert sections == expected, (
        f"{lockfile.relative_to(ROOT)} has sections {sorted(sections)} but the project "
        f"targets {sorted(expected)}; regenerate it with: {regeneration_command(lockfile)}"
    )


def test_lock_files_resolve_the_central_versions() -> None:
    mismatches = []
    for lockfile in LOCKFILES:
        if not lockfile.is_relative_to(C_SHARP):
            continue
        for section, packages in lock_dependencies(lockfile).items():
            for name, entry in packages.items():
                if name not in PINS or entry["type"] not in ("Direct", "CentralTransitive"):
                    continue
                version = PINS[name]
                if entry["resolved"] != version or entry.get("requested") != f"[{version}, )":
                    mismatches.append(
                        f"{lockfile.relative_to(ROOT)} [{section}] {name}: "
                        f"{entry.get('requested')} -> {entry['resolved']}, central pin {version}"
                    )

    assert not mismatches, (
        "lock files differ from Directory.Packages.props; regenerate them with: "
        "dotnet restore langs/csharp/VMx.sln --force-evaluate\n" + "\n".join(mismatches)
    )


def test_servicing_family_moves_together() -> None:
    versions = {name: PINS[name] for name in SERVICING_FAMILY}
    newest = max(versions.values(), key=lambda value: tuple(int(part) for part in value.split(".")))
    behind = {name: version for name, version in versions.items() if version != newest}

    assert not behind, (
        f"the .NET servicing family must share one version; move these to {newest} in "
        f"langs/csharp/Directory.Packages.props: "
        + ", ".join(f"{name} {version}" for name, version in sorted(behind.items()))
    )


@pytest.mark.parametrize(("name", "hold"), sorted(HOLDS.items()))
def test_holds_keep_their_version_and_dependabot_ignore_rule(
    name: str, hold: tuple[str, str]
) -> None:
    version, ignored = hold
    config = DEPENDABOT.read_text(encoding="utf-8")

    assert PINS[name] == version, (
        f"hold: {name} stays at {version} (contract ledger section 2); "
        f"Directory.Packages.props has {PINS[name]}"
    )
    assert re.search(
        rf'dependency-name: {re.escape(name)}\n\s+versions: \["{re.escape(ignored)}"\]', config
    ), f"hold: .github/dependabot.yml must ignore {name} {ignored}"


def test_test_projects_run_the_held_dependency_injection_runtime() -> None:
    held = HOLDS["Microsoft.Extensions.DependencyInjection"][0]
    for relative_path in (
        "tests/VMx.Tests/packages.lock.json",
        "tests/VMx.Conformance.Tests/packages.lock.json",
    ):
        for section, packages in lock_dependencies(C_SHARP / relative_path).items():
            resolved = packages["Microsoft.Extensions.DependencyInjection"]["resolved"]
            assert resolved == held, (relative_path, section)


def test_netstandard_locks_hold_the_system_text_json_closure() -> None:
    expected_types = {
        "src/VMx/packages.lock.json": "Direct",
        "src/VMx.Notifications/packages.lock.json": "CentralTransitive",
        "src/VMx.Extensions.DependencyInjection/packages.lock.json": "CentralTransitive",
    }
    for relative_path, expected_type in expected_types.items():
        netstandard = lock_dependencies(C_SHARP / relative_path)[".NETStandard,Version=v2.0"]
        system_text_json = netstandard["System.Text.Json"]
        assert system_text_json["type"] == expected_type, relative_path
        dependencies = system_text_json["dependencies"]
        assert "Microsoft.Bcl.AsyncInterfaces" in dependencies, relative_path
        for dependency in dependencies:
            assert dependency in netstandard, (relative_path, dependency)


def test_ledger_names_the_version_source_and_the_hold() -> None:
    ledger = " ".join(LEDGER.read_text(encoding="utf-8").split())

    assert "versions are the pins in `langs/csharp/Directory.Packages.props`" in ledger
    assert LEDGER_HOLD in ledger
