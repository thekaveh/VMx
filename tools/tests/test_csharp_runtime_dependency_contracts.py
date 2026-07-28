"""Keep C# runtime/build package pins and committed lock targets aligned."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C_SHARP = ROOT / "langs" / "csharp"
EXPECTED_CENTRAL_VERSIONS = {
    "Microsoft.SourceLink.GitHub": "10.0.301",
    "Microsoft.Bcl.AsyncInterfaces": "10.0.10",
    "Microsoft.Extensions.DependencyInjection.Abstractions": "10.0.10",
    "Microsoft.Extensions.DependencyInjection": "8.0.1",
}
LOCK_TARGETS = {
    "src/VMx/packages.lock.json": {".NETStandard,Version=v2.0", "net8.0"},
    "src/VMx.Notifications/packages.lock.json": {".NETStandard,Version=v2.0", "net8.0"},
    "src/VMx.Extensions.DependencyInjection/packages.lock.json": {
        ".NETStandard,Version=v2.0",
        "net8.0",
    },
    "tests/VMx.Tests/packages.lock.json": {"net8.0", "net9.0", "net10.0"},
    "tests/VMx.Conformance.Tests/packages.lock.json": {"net8.0", "net9.0", "net10.0"},
}
LEDGER_CONTRACT = (
    "`Microsoft.SourceLink.GitHub` is `10.0.301`; "
    "`Microsoft.Extensions.DependencyInjection.Abstractions` and "
    "`Microsoft.Bcl.AsyncInterfaces` are `10.0.10`; "
    "`Microsoft.Extensions.DependencyInjection` remains `8.0.1`"
)


def test_csharp_runtime_pins_and_lockfiles_cover_every_project_target() -> None:
    versions = {
        package.get("Include"): package.get("Version")
        for package in ET.parse(C_SHARP / "Directory.Packages.props").findall(".//PackageVersion")
    }
    assert {package: versions[package] for package in EXPECTED_CENTRAL_VERSIONS} == (
        EXPECTED_CENTRAL_VERSIONS
    )

    for relative_path, expected_targets in LOCK_TARGETS.items():
        lockfile = C_SHARP / relative_path
        dependencies = json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]
        assert set(dependencies) == expected_targets, lockfile
        for target, packages in dependencies.items():
            assert packages["Microsoft.SourceLink.GitHub"]["resolved"] == "10.0.301", (
                lockfile,
                target,
            )

    di_lock = json.loads(
        (C_SHARP / "src/VMx.Extensions.DependencyInjection/packages.lock.json").read_text(
            encoding="utf-8"
        )
    )["dependencies"]
    for target, packages in di_lock.items():
        abstraction = packages["Microsoft.Extensions.DependencyInjection.Abstractions"]
        assert abstraction["resolved"] == "10.0.10", (target,)
    assert (
        di_lock[".NETStandard,Version=v2.0"]["Microsoft.Bcl.AsyncInterfaces"]["resolved"]
        == "10.0.10"
    )

    for relative_path in (
        "tests/VMx.Tests/packages.lock.json",
        "tests/VMx.Conformance.Tests/packages.lock.json",
    ):
        lockfile = C_SHARP / relative_path
        dependencies = json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]
        for target, packages in dependencies.items():
            assert packages["Microsoft.Extensions.DependencyInjection"]["resolved"] == "8.0.1", (
                relative_path,
                target,
            )

    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    assert LEDGER_CONTRACT in ledger
