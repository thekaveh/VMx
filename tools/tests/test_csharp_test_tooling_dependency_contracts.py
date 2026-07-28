"""Keep C# test-tooling pins, lockfiles, and maintenance evidence aligned."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C_SHARP = ROOT / "langs" / "csharp"
TEST_LOCKFILES = (
    C_SHARP / "tests" / "VMx.Tests" / "packages.lock.json",
    C_SHARP / "tests" / "VMx.Conformance.Tests" / "packages.lock.json",
)
EXPECTED_TEST_VERSIONS = {
    "Microsoft.NET.Test.Sdk": "18.8.1",
    "xunit": "2.9.3",
    "xunit.runner.visualstudio": "3.1.5",
    "FluentAssertions": "6.12.2",
    "coverlet.collector": "10.0.0",
}
EXPECTED_TARGETS = {"net8.0", "net9.0", "net10.0"}
EXPECTED_TEST_SDK_TRANSITIVES = {
    "Microsoft.CodeCoverage": "18.8.1",
    "Microsoft.TestPlatform.ObjectModel": "18.8.1",
    "Microsoft.TestPlatform.TestHost": "18.8.1",
}
LEDGER_CONTRACT = (
    "`Microsoft.NET.Test.Sdk` is `18.8.1`, "
    "`xunit.runner.visualstudio` is `3.1.5`, and "
    "`coverlet.collector` is `10.0.0`; "
    "`xunit` remains `2.9.3` and `FluentAssertions` remains `6.12.2`"
)
DEFERRED_COLLECTOR_CONTRACT = (
    "`coverlet.collector` `10.0.1` is deferred because its active net10 "
    "instrumentation produces invalid IL in `MessageHub.DrainQueue`; 10.0.0 is the "
    "highest stable version verified against that focused coverage reproduction"
)


def test_csharp_test_tooling_central_versions_match_the_reviewed_stack() -> None:
    versions = {
        package.get("Include"): package.get("Version")
        for package in ET.parse(C_SHARP / "Directory.Packages.props").findall(".//PackageVersion")
    }

    assert {package: versions[package] for package in EXPECTED_TEST_VERSIONS} == (
        EXPECTED_TEST_VERSIONS
    )


def test_csharp_test_lockfiles_resolve_the_reviewed_stack_for_every_target() -> None:
    for lockfile in TEST_LOCKFILES:
        dependencies = json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]
        assert set(dependencies) == EXPECTED_TARGETS, lockfile

        for target, packages in dependencies.items():
            direct_metadata = {
                package: {key: packages[package][key] for key in ("type", "requested", "resolved")}
                for package in EXPECTED_TEST_VERSIONS
            }
            expected_direct_metadata = {
                package: {
                    "type": "Direct",
                    "requested": f"[{version}, )",
                    "resolved": version,
                }
                for package, version in EXPECTED_TEST_VERSIONS.items()
            }
            assert direct_metadata == expected_direct_metadata, (lockfile, target)

            test_sdk = packages["Microsoft.NET.Test.Sdk"]
            assert test_sdk["dependencies"] == {
                "Microsoft.CodeCoverage": "18.8.1",
                "Microsoft.TestPlatform.TestHost": "18.8.1",
            }, (lockfile, target)

            transitive_metadata = {
                package: {
                    "type": packages[package]["type"],
                    "resolved": packages[package]["resolved"],
                }
                for package in EXPECTED_TEST_SDK_TRANSITIVES
            }
            assert transitive_metadata == {
                package: {"type": "Transitive", "resolved": version}
                for package, version in EXPECTED_TEST_SDK_TRANSITIVES.items()
            }, (lockfile, target)
            assert packages["Microsoft.TestPlatform.TestHost"]["dependencies"] == {
                "Microsoft.TestPlatform.ObjectModel": "18.8.1"
            }, (lockfile, target)
            assert "Newtonsoft.Json" not in packages, (lockfile, target)


def test_contract_ledger_records_the_csharp_test_tooling_decision() -> None:
    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    normalized_ledger = " ".join(ledger.split())

    assert LEDGER_CONTRACT in normalized_ledger
    assert DEFERRED_COLLECTOR_CONTRACT in normalized_ledger
