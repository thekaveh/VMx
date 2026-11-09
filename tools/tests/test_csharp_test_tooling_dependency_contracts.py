"""Keep C# test-tooling pins, lock files, holds, and maintenance evidence aligned.

The versions come from `langs/csharp/Directory.Packages.props`, so a Dependabot
update of a test package passes with only that file and the regenerated lock
files (#1363). The FluentAssertions and Coverlet holds stay literal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from check_nuget_package import central_package_versions

ROOT = Path(__file__).resolve().parents[2]
C_SHARP = ROOT / "langs" / "csharp"
PINS = central_package_versions(C_SHARP / "Directory.Packages.props")
TEST_LOCKFILES = (
    C_SHARP / "tests" / "VMx.Tests" / "packages.lock.json",
    C_SHARP / "tests" / "VMx.Conformance.Tests" / "packages.lock.json",
)
TEST_PACKAGES = (
    "Microsoft.NET.Test.Sdk",
    "xunit",
    "xunit.runner.visualstudio",
    "FluentAssertions",
    "coverlet.collector",
)
# Microsoft.NET.Test.Sdk ships these packages in its own release.
TEST_SDK_TRANSITIVES = (
    "Microsoft.CodeCoverage",
    "Microsoft.TestPlatform.ObjectModel",
    "Microsoft.TestPlatform.TestHost",
)
LEDGER_CONTRACT = "`xunit` stays on the 2.x line and `FluentAssertions` remains on the 6.x line"
DEFERRED_COLLECTOR_CONTRACT = (
    "`coverlet.collector` `10.0.1` and `10.1.0` are deferred because their active "
    "instrumentation produces invalid IL in `MessageHub.DrainQueue` (`10.0.1` on net10, "
    "`10.1.0` on net8 as well); 10.0.0 is the highest stable version verified against "
    "that focused coverage reproduction"
)


def test_test_tooling_holds_keep_their_lines() -> None:
    config = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    assert PINS["FluentAssertions"].split(".")[0] == "6", (
        "hold: FluentAssertions stays on 6.x until a migration PR (contract ledger section 2)"
    )
    assert re.search(r'dependency-name: FluentAssertions\n\s+versions: \[">=7\.0\.0"\]', config)
    assert PINS["coverlet.collector"] not in ("10.0.1", "10.1.0"), (
        "hold: coverlet.collector 10.0.1 and 10.1.0 produce invalid IL (contract ledger section 2)"
    )
    assert re.search(
        r'dependency-name: coverlet\.collector\n\s+versions: \["10\.0\.1", "10\.1\.0"\]', config
    )
    assert PINS["xunit"].split(".")[0] == "2"


def test_csharp_test_lockfiles_resolve_the_central_stack_for_every_target() -> None:
    test_sdk_version = PINS["Microsoft.NET.Test.Sdk"]
    for lockfile in TEST_LOCKFILES:
        dependencies = json.loads(lockfile.read_text(encoding="utf-8"))["dependencies"]
        assert set(dependencies) == {"net8.0", "net9.0", "net10.0"}, lockfile

        for target, packages in dependencies.items():
            direct_metadata = {
                package: {key: packages[package][key] for key in ("type", "requested", "resolved")}
                for package in TEST_PACKAGES
            }
            assert direct_metadata == {
                package: {
                    "type": "Direct",
                    "requested": f"[{PINS[package]}, )",
                    "resolved": PINS[package],
                }
                for package in TEST_PACKAGES
            }, (lockfile, target)

            assert packages["Microsoft.NET.Test.Sdk"]["dependencies"] == {
                "Microsoft.CodeCoverage": test_sdk_version,
                "Microsoft.TestPlatform.TestHost": test_sdk_version,
            }, (lockfile, target)
            assert {
                package: (packages[package]["type"], packages[package]["resolved"])
                for package in TEST_SDK_TRANSITIVES
            } == {package: ("Transitive", test_sdk_version) for package in TEST_SDK_TRANSITIVES}, (
                lockfile,
                target,
            )
            assert packages["Microsoft.TestPlatform.TestHost"]["dependencies"] == {
                "Microsoft.TestPlatform.ObjectModel": test_sdk_version
            }, (lockfile, target)
            assert "Newtonsoft.Json" not in packages, (lockfile, target)


def test_contract_ledger_records_the_csharp_test_tooling_decision() -> None:
    ledger = (ROOT / "docs/maintenance/2026-07-01-contract-ledger.md").read_text(encoding="utf-8")
    normalized_ledger = " ".join(ledger.split())

    assert LEDGER_CONTRACT in normalized_ledger
    assert DEFERRED_COLLECTOR_CONTRACT in normalized_ledger
