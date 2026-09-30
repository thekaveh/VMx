"""Unit tests for tools/check-conformance-execution.py (#345)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import check_conformance_execution as cce
import pytest

CATALOG = """\
# Conformance

### LIFE-001
### LIFE-002
### LIFE-003
### LIFE-004
### THEME-001
"""


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/12-conformance.md").write_text(CATALOG, encoding="utf-8")
    return tmp_path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _pytest_case(name: str, ident: str, body: str = "", classname: str = "tests.t") -> str:
    return (
        f'<testcase classname="{classname}" name="{name}">'
        f'<properties><property name="conformance" value="{ident}"/></properties>'
        f"{body}</testcase>"
    )


def _pytest_report(tmp_path: Path, *cases: str, declared: int | None = None) -> Path:
    count = len(cases) if declared is None else declared
    return _write(
        tmp_path / "junit.xml",
        f'<testsuites><testsuite name="pytest" tests="{count}">{"".join(cases)}'
        "</testsuite></testsuites>",
    )


def _run(tmp_path: Path, flavor: str, *reports: Path) -> tuple[int, dict]:
    evidence = tmp_path / "evidence.json"
    rc = cce.check(
        flavor,
        list(reports),
        repo_root=tmp_path,
        evidence_path=evidence,
        commit="abc123",
        toolchain="tool 1.0",
        configuration="unit",
    )
    data = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else {}
    return rc, data


# ─── Classification and aggregation ──────────────────────────────────────────


def test_every_status_is_classified_and_the_gate_fails(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    report = _pytest_report(
        tmp_path,
        _pytest_case("test_passed", "LIFE-001"),
        _pytest_case("test_failed", "LIFE-002", '<failure message="boom"/>'),
        _pytest_case("test_skipped", "LIFE-003", '<skipped message="later"/>'),
    )

    rc, data = _run(repo, "python", report)

    assert rc == 1
    statuses = {ident: item["status"] for ident, item in data["ids"].items()}
    assert statuses == {
        "LIFE-001": "passed",
        "LIFE-002": "failed",
        "LIFE-003": "skipped",
        "LIFE-004": "missing",
    }
    assert "THEME-001" not in data["ids"]  # scenario IDs stay with the examples
    err = capsys.readouterr().err
    assert "LIFE-002: failed (test_failed [failed])" in err
    assert "LIFE-003: skipped (test_skipped [skipped])" in err
    assert "LIFE-004: missing" in err


def test_provenance_fields_are_recorded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = _pytest_report(tmp_path, *(_pytest_case(f"t{n}", f"LIFE-00{n}") for n in range(1, 5)))

    rc, data = _run(repo, "python", report)

    assert rc == 0
    assert (data["commit"], data["toolchain"], data["configuration"]) == (
        "abc123",
        "tool 1.0",
        "unit",
    )
    assert data["counts"] == {"passed": 4, "failed": 0, "skipped": 0, "missing": 0}
    assert data["rule"].startswith("an ID passes when no executed case")


def test_parameterized_cases_pass_only_when_no_variant_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    others = [_pytest_case(f"t{n}", f"LIFE-00{n}") for n in (3, 4)]
    report = _pytest_report(
        tmp_path,
        _pytest_case("test_param[a]", "LIFE-001"),
        _pytest_case("test_param[b]", "LIFE-001", '<skipped message="n/a"/>'),
        _pytest_case("test_other[a]", "LIFE-002"),
        _pytest_case("test_other[b]", "LIFE-002", '<failure message="variant b"/>'),
        *others,
    )

    rc, data = _run(repo, "python", report)

    assert rc == 1
    assert data["ids"]["LIFE-001"]["status"] == "passed"  # a skipped variant is ignored
    assert data["ids"]["LIFE-002"]["status"] == "failed"
    assert len(data["ids"]["LIFE-002"]["cases"]) == 2


def test_duplicated_reports_of_one_case_all_count(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = [_pytest_case(f"t{n}", f"LIFE-00{n}") for n in range(1, 5)]
    first = _pytest_report(tmp_path, *base)
    second = _write(
        tmp_path / "rerun.xml",
        '<testsuite name="rerun" tests="1">'
        + _pytest_case("t1", "LIFE-001", '<failure message="flaky"/>')
        + "</testsuite>",
    )

    rc, data = _run(repo, "python", first, second)

    assert rc == 1
    assert [case["outcome"] for case in data["ids"]["LIFE-001"]["cases"]] == ["passed", "failed"]


def test_all_skipped_variants_do_not_qualify(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = _pytest_report(
        tmp_path,
        _pytest_case("test_a[x]", "LIFE-001", "<skipped/>"),
        _pytest_case("test_a[y]", "LIFE-001", "<skipped/>"),
        *(_pytest_case(f"t{n}", f"LIFE-00{n}") for n in (2, 3, 4)),
    )

    rc, data = _run(repo, "python", report)

    assert rc == 1
    assert data["ids"]["LIFE-001"]["status"] == "skipped"


# ─── Untrustworthy reports ───────────────────────────────────────────────────


def test_truncated_report_is_rejected(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    report = _write(
        tmp_path / "junit.xml",
        '<testsuites><testsuite name="pytest" tests="4">' + _pytest_case("t1", "LIFE-001"),
    )

    rc, data = _run(repo, "python", report)

    assert rc == 2
    assert data == {}
    assert "unreadable or truncated" in capsys.readouterr().err


def test_report_that_disagrees_with_its_totals_is_rejected(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    report = _pytest_report(tmp_path, _pytest_case("t1", "LIFE-001"), declared=4)

    assert _run(repo, "python", report)[0] == 2
    assert "declares 4 tests but lists 1" in capsys.readouterr().err


def test_pytest_collection_failure_is_rejected(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    report = _pytest_report(
        tmp_path,
        *(_pytest_case(f"t{n}", f"LIFE-00{n}") for n in range(1, 5)),
        '<testcase classname="" name="tests.conformance.test_broken">'
        '<error message="collection failure">ImportError</error></testcase>',
    )

    assert _run(repo, "python", report)[0] == 2
    assert "collection failure" in capsys.readouterr().err


def test_empty_report_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = _write(tmp_path / "junit.xml", '<testsuite name="pytest" tests="0"></testsuite>')

    assert _run(repo, "python", report)[0] == 2


def test_missing_report_file_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert _run(repo, "python", tmp_path / "absent.xml")[0] == 2


# ─── Flavor adapters ─────────────────────────────────────────────────────────


def test_vitest_ids_come_from_exact_describe_titles(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = _write(
        tmp_path / "vitest.xml",
        """\
        <testsuites tests="5">
          <testsuite name="tests/conformance/lifecycle.test.ts" tests="5">
            <testcase classname="lifecycle.test.ts" name="LIFE-001 &gt; constructs"/>
            <testcase classname="lifecycle.test.ts" name="LIFE-002 &gt; nested &gt; destructs"/>
            <testcase classname="lifecycle.test.ts" name="LIFE-003 &gt; waits">
              <skipped/>
            </testcase>
            <testcase classname="lifecycle.test.ts" name="LIFE-004 &gt; fails">
              <failure message="x"/>
            </testcase>
            <testcase classname="lifecycle.test.ts" name="mentions LIFE-004 in prose"/>
          </testsuite>
        </testsuites>
        """,
    )

    rc, data = _run(repo, "typescript", report)

    assert rc == 1
    assert {i: item["status"] for i, item in data["ids"].items()} == {
        "LIFE-001": "passed",
        "LIFE-002": "passed",
        "LIFE-003": "skipped",
        "LIFE-004": "failed",
    }
    assert len(data["ids"]["LIFE-004"]["cases"]) == 1  # prose never maps


def test_vitest_file_load_failure_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    report = _write(
        tmp_path / "vitest.xml",
        '<testsuites><testsuite name="broken.test.ts" tests="1">'
        '<testcase classname="broken.test.ts" name="broken.test.ts">'
        '<failure message="Failed to load url ./missing.js"/></testcase>'
        "</testsuite></testsuites>",
    )

    assert _run(repo, "typescript", report)[0] == 2


CS_SOURCE = """\
namespace VMx.Conformance.Tests;

public sealed class LifecycleConformanceTests
{
    [Fact, Trait("Conformance", "LIFE-001")]
    public void LIFE_001_Constructs() { }

    // [Fact, Trait("Conformance", "LIFE-002")] commented out: never a marker
    [Theory, Trait("Conformance", "LIFE-002")]
    [InlineData(1)]
    [InlineData(2)]
    public async Task LIFE_002_Destructs(int value) { await Task.Yield(); }

    [Fact, Trait("Conformance", "LIFE-003")]
    [Trait("Conformance", "LIFE-004")]
    public void Shared_Test() { }

    private sealed class Probe { }
}
"""

TRX_NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"


def _trx(results: list[tuple[str, str, str]], *, total: int | None = None, error: int = 0) -> str:
    definitions = "".join(
        f'<UnitTest id="id{n}" name="{name}"><TestMethod className="'
        f'VMx.Conformance.Tests.LifecycleConformanceTests, VMx.Conformance.Tests" name="{method}"/>'
        "</UnitTest>"
        for n, (name, method, _) in enumerate(results)
    )
    rows = "".join(
        f'<UnitTestResult testId="id{n}" testName="{name}" outcome="{outcome}"/>'
        for n, (name, _, outcome) in enumerate(results)
    )
    count = len(results) if total is None else total
    return (
        f'<TestRun xmlns="{TRX_NS}"><TestDefinitions>{definitions}</TestDefinitions>'
        f'<Results>{rows}</Results><ResultSummary outcome="Completed">'
        f'<Counters total="{count}" error="{error}"/></ResultSummary></TestRun>'
    )


def test_trx_cases_map_through_csharp_source_markers(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "langs/csharp/tests/VMx.Conformance.Tests/LifecycleTests.cs", CS_SOURCE)
    report = _write(
        tmp_path / "results.trx",
        _trx(
            [
                ("LIFE_001_Constructs", "LIFE_001_Constructs", "Passed"),
                ("LIFE_002_Destructs(value: 1)", "LIFE_002_Destructs(value: 1)", "Passed"),
                ("LIFE_002_Destructs(value: 2)", "LIFE_002_Destructs(value: 2)", "NotExecuted"),
                ("Shared_Test", "Shared_Test", "Failed"),
            ]
        ),
    )

    rc, data = _run(repo, "csharp", report)

    assert rc == 1
    assert {i: item["status"] for i, item in data["ids"].items()} == {
        "LIFE-001": "passed",
        "LIFE-002": "passed",
        "LIFE-003": "failed",
        "LIFE-004": "failed",
    }


def test_trx_host_error_and_count_mismatch_are_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "langs/csharp/tests/VMx.Conformance.Tests/LifecycleTests.cs", CS_SOURCE)
    passed = [("LIFE_001_Constructs", "LIFE_001_Constructs", "Passed")]

    crashed = _write(tmp_path / "crash.trx", _trx(passed, error=1))
    short = _write(tmp_path / "short.trx", _trx(passed, total=3))

    assert _run(repo, "csharp", crashed)[0] == 2
    assert _run(repo, "csharp", short)[0] == 2


SWIFT_SOURCE = """\
import XCTest

final class LifecycleTests: XCTestCase {
    private final class Probe: ComponentVMBase {}

    /// LIFE-001 — construct transitions
    func testConstructs() {}

    /// LIFE-002 — destruct transitions
    @MainActor
    func testDestructs() async {}

    // LIFE-003 prose mention without the em dash is not a marker
    /// LIFE-003 — skipped through XCTSkip
    func testSkips() throws {}
}

final class OtherTests: XCTestCase {
    /// LIFE-004 — same name in another class
    func testConstructs() {}
}
"""


def test_swift_xunit_cases_map_through_source_markers(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "langs/swift/Tests/VMxTests/LifecycleTests.swift", SWIFT_SOURCE)
    report = _write(
        tmp_path / "xunit.xml",
        """\
        <testsuites>
          <testsuite name="TestResults" errors="0" tests="4" failures="1" time="1.0">
            <testcase classname="VMxTests.LifecycleTests" name="testConstructs" time="0.1"/>
            <testcase classname="VMxTests.LifecycleTests" name="testDestructs" time="0.1"/>
            <testcase classname="VMxTests.LifecycleTests" name="testSkips" time="0.1">
              <skipped/>
            </testcase>
            <testcase classname="VMxTests.OtherTests" name="testConstructs" time="0.1">
              <failure message="x"/>
            </testcase>
          </testsuite>
        </testsuites>
        """,
    )

    rc, data = _run(repo, "swift", report)

    assert rc == 1
    assert {i: item["status"] for i, item in data["ids"].items()} == {
        "LIFE-001": "passed",
        "LIFE-002": "passed",
        "LIFE-003": "skipped",
        "LIFE-004": "failed",  # the class disambiguates the shared name
    }


RUST_SOURCE = """\
/// LIFE-001 — construct transitions
#[test]
fn life_001_constructs() {}

/// LIFE-002 — destruct transitions
#[test]
fn life_002_destructs() {}

/* /// LIFE-003 — block-commented, never a marker
#[test]
fn life_003_hidden() {} */

/// LIFE-003 — ignored
#[test]
#[ignore]
fn life_003_ignored() {}
"""


def test_libtest_output_maps_through_rust_source_markers(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "langs/rust/tests/conformance/lifecycle.rs", RUST_SOURCE)
    report = _write(
        tmp_path / "cargo-test.log",
        """\
        running 3 tests
        test conformance::lifecycle::life_001_constructs ... ok
        test conformance::lifecycle::life_002_destructs ... FAILED
        test conformance::lifecycle::life_003_ignored ... ignored, slow

        test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out

        running 1 test
        test src/lib.rs - Thing (line 3) - compile fail ... ok

        test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
        """,
    )

    rc, data = _run(repo, "rust", report)

    assert rc == 1
    assert {i: item["status"] for i, item in data["ids"].items()} == {
        "LIFE-001": "passed",
        "LIFE-002": "failed",
        "LIFE-003": "skipped",
        "LIFE-004": "missing",
    }


@pytest.mark.parametrize(
    "log",
    [
        "running 2 tests\ntest conformance::lifecycle::life_001_constructs ... ok\n",
        "running 2 tests\ntest conformance::lifecycle::life_001_constructs ... ok\n\n"
        "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n",
        "error[E0425]: cannot find value `x` in this scope\nerror: could not compile `vmx`\n",
    ],
    ids=["truncated", "count-mismatch", "build-failure"],
)
def test_untrustworthy_libtest_output_is_rejected(tmp_path: Path, log: str) -> None:
    repo = _repo(tmp_path)
    _write(repo / "langs/rust/tests/conformance/lifecycle.rs", RUST_SOURCE)
    report = _write(tmp_path / "cargo-test.log", log)

    assert _run(repo, "rust", report)[0] == 2


def test_marker_without_a_test_function_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(
        repo / "langs/csharp/tests/VMx.Conformance.Tests/Broken.cs",
        'public sealed class Broken\n{\n    [Fact, Trait("Conformance", "LIFE-001")]\n}\n',
    )
    report = _write(tmp_path / "results.trx", _trx([("A", "A", "Passed")]))

    assert _run(repo, "csharp", report)[0] == 2
