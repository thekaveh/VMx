#!/usr/bin/env python3
"""Check that every library conformance ID has a passing executed test case.

`tools/check-conformance-coverage.py` proves that a marker for each catalog ID
exists in a flavor's test sources. It cannot see whether a runner discovered,
executed, and passed that test. This tool reads a runner's own result report,
maps each executed case back to the catalog IDs it carries, and fails unless
every required ID has a qualifying passing execution.

Aggregation rule, per required ID:

* ``failed``: at least one executed case for the ID failed or errored.
* ``passed``: no case failed and at least one passed.
* ``skipped``: every case for the ID was skipped.
* ``missing``: no executed case carries the ID.

Only ``passed`` qualifies. Parameterized cases and duplicate reports of one case
each count as separate executions, so any failing variant fails the ID. A report
that cannot be parsed, is truncated, disagrees with its own totals, or records a
collection or build failure is rejected outright rather than read as success.

How cases map to IDs:

* Python (JUnit XML from pytest): the ``conformance`` testcase property that
  ``langs/python/tests/conftest.py`` records from each ``conformance`` marker.
* TypeScript (JUnit XML from Vitest): a ``describe`` title that is exactly the ID.
* C# (TRX), Swift (xUnit XML from ``swift test --xunit-output``), and Rust
  (libtest output from ``cargo test``): the test function that the flavor's
  source marker attaches to, found with the same marker rules as the coverage
  checker.

Exit codes:
    0  Every required ID has a passing execution.
    1  At least one required ID is failed, skipped, or missing.
    2  A report is unreadable, truncated, inconsistent, or records a collection
       failure; or the catalog or test directory cannot be read.

Usage:
    python3 tools/check-conformance-execution.py --flavor python \\
        --report conformance-results.xml --evidence conformance-evidence.json \\
        --commit SHA --toolchain "Python 3.12.7" --configuration "ubuntu-latest"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_REL = Path("spec/12-conformance.md")
_ID = re.compile(r"^[A-Z]{3,5}-\d{3}$")
_STATUSES = ("passed", "failed", "skipped", "missing")
_RULE = "an ID passes when no executed case for it failed and at least one passed"


def _load_coverage_module():  # type: ignore[no-untyped-def]
    name = "check_conformance_coverage"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / "check-conformance-coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ccc = _load_coverage_module()


class ReportError(Exception):
    """The report cannot be trusted as execution evidence."""


@dataclass(frozen=True)
class Case:
    """One executed test case as the runner reported it."""

    container: str  # class, module, or file as reported
    name: str  # test function name without parameters
    display: str  # the runner's full case name, kept for actionable output
    outcome: str  # passed | failed | skipped
    ids: frozenset[str] = frozenset()  # IDs the report itself carries


@dataclass
class Evidence:
    status: str = "missing"
    cases: list[dict[str, str]] = field(default_factory=list)


# ─── Report adapters ─────────────────────────────────────────────────────────


def _parse_xml(path: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ReportError(f"{path}: unreadable or truncated XML ({error})") from error


def _int(element: ET.Element, attribute: str, path: Path) -> int | None:
    value = element.get(attribute)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ReportError(f"{path}: {attribute}={value!r} is not an integer") from error


def _junit_suites(root: ET.Element, path: Path) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag == "testsuites":
        suites = root.findall("testsuite")
        if not suites:
            raise ReportError(f"{path}: <testsuites> holds no <testsuite>")
        return suites
    raise ReportError(f"{path}: root <{root.tag}> is not a JUnit or xUnit report")


def _junit_outcome(testcase: ET.Element) -> str:
    if testcase.find("failure") is not None or testcase.find("error") is not None:
        return "failed"
    if testcase.find("skipped") is not None:
        return "skipped"
    return "passed"


def _strip_parameters(name: str) -> str:
    return re.split(r"[\[(]", name, maxsplit=1)[0].strip()


def read_junit(path: Path, *, id_source: str) -> list[Case]:
    """Read pytest, Vitest, or SwiftPM xUnit XML.

    ``id_source`` is ``property`` (pytest), ``describe`` (Vitest), or ``source``
    (SwiftPM, whose cases are mapped through source markers).
    """
    root = _parse_xml(path)
    cases: list[Case] = []
    for suite in _junit_suites(root, path):
        testcases = suite.iter("testcase")
        suite_cases = list(testcases)
        declared = _int(suite, "tests", path)
        if declared is not None and declared != len(suite_cases):
            raise ReportError(
                f"{path}: suite {suite.get('name')!r} declares {declared} tests "
                f"but lists {len(suite_cases)}"
            )
        for testcase in suite_cases:
            container = testcase.get("classname", "")
            display = testcase.get("name", "")
            outcome = _junit_outcome(testcase)
            if _is_collection_failure(testcase, container, display, outcome, id_source):
                raise ReportError(f"{path}: collection failure in {container or display!r}")
            ids: set[str] = set()
            if id_source == "property":
                for prop in testcase.iter("property"):
                    if prop.get("name") == "conformance":
                        ids.add(prop.get("value", ""))
            elif id_source == "describe":
                ids.update(part for part in display.split(" > ") if _ID.match(part))
            name = display.split(" > ")[-1] if id_source == "describe" else display
            cases.append(Case(container, _strip_parameters(name), display, outcome, frozenset(ids)))
    if not cases:
        raise ReportError(f"{path}: the report lists no executed test cases")
    return cases


def _is_collection_failure(
    testcase: ET.Element, container: str, display: str, outcome: str, id_source: str
) -> bool:
    if outcome != "failed":
        return False
    for tag in ("error", "failure"):
        detail = testcase.find(tag)
        if detail is None:
            continue
        message = (detail.get("message") or "").lower()
        if "collection failure" in message or "failed to load" in message:
            return True
    # pytest reports a module that fails to import as a case named after the
    # module path with an empty class name.
    return id_source == "property" and not container


_TRX_NS = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
_TRX_OUTCOMES = {
    "Passed": "passed",
    "NotExecuted": "skipped",
    "Inconclusive": "skipped",
    "Failed": "failed",
    "Error": "failed",
    "Timeout": "failed",
    "Aborted": "failed",
}


def read_trx(path: Path) -> list[Case]:
    root = _parse_xml(path)
    if root.tag != f"{{{_TRX_NS['t']}}}TestRun":
        raise ReportError(f"{path}: root <{root.tag}> is not a TRX TestRun")
    methods: dict[str, tuple[str, str]] = {}
    for unit_test in root.iterfind("t:TestDefinitions/t:UnitTest", _TRX_NS):
        method = unit_test.find("t:TestMethod", _TRX_NS)
        if method is None:
            raise ReportError(f"{path}: UnitTest {unit_test.get('id')} has no TestMethod")
        class_name = (method.get("className") or "").split(",")[0].split(".")[-1]
        methods[unit_test.get("id", "")] = (class_name, method.get("name", ""))

    results = root.findall("t:Results/t:UnitTestResult", _TRX_NS)
    counters = root.find("t:ResultSummary/t:Counters", _TRX_NS)
    if counters is None:
        raise ReportError(f"{path}: TRX has no ResultSummary counters (truncated run?)")
    total = _int(counters, "total", path)
    if total is not None and total != len(results):
        raise ReportError(f"{path}: counters report {total} tests but {len(results)} results")
    errors = _int(counters, "error", path) or 0
    if errors:
        raise ReportError(f"{path}: the test host reported {errors} run error(s)")

    cases: list[Case] = []
    for result in results:
        outcome = _TRX_OUTCOMES.get(result.get("outcome", ""))
        if outcome is None:
            raise ReportError(f"{path}: unknown TRX outcome {result.get('outcome')!r}")
        try:
            class_name, method_name = methods[result.get("testId", "")]
        except KeyError as error:
            raise ReportError(
                f"{path}: result {result.get('testName')!r} has no definition"
            ) from error
        method_name = _strip_parameters(method_name).split(".")[-1]
        cases.append(Case(class_name, method_name, result.get("testName", ""), outcome))
    if not cases:
        raise ReportError(f"{path}: the report lists no executed test cases")
    return cases


_LIBTEST_RUNNING = re.compile(r"^running (\d+) tests?$")
# Doctest names contain spaces, so the name runs up to the last " ... ".
_LIBTEST_CASE = re.compile(r"^test (.+) \.\.\. (ok|FAILED|ignored(?:, .*)?)$")
_LIBTEST_SUMMARY = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;"
)


def read_libtest(path: Path) -> list[Case]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ReportError(f"{path}: unreadable libtest output ({error})") from error
    cases: list[Case] = []
    expected: int | None = None
    block: list[Case] = []
    blocks = 0
    for line in lines:
        running = _LIBTEST_RUNNING.match(line)
        if running:
            if expected is not None:
                raise ReportError(f"{path}: a test binary stopped before its summary")
            expected, block = int(running.group(1)), []
            continue
        case = _LIBTEST_CASE.match(line)
        if case and expected is not None:
            outcome = {"ok": "passed", "FAILED": "failed"}.get(case.group(2), "skipped")
            module, _, name = case.group(1).rpartition("::")
            block.append(Case(module, name, case.group(1), outcome))
            continue
        summary = _LIBTEST_SUMMARY.match(line)
        if summary and expected is not None:
            passed, failed, ignored = (int(summary.group(n)) for n in (2, 3, 4))
            counts = [sum(c.outcome == o for c in block) for o in ("passed", "failed", "skipped")]
            if len(block) != expected or counts != [passed, failed, ignored]:
                raise ReportError(
                    f"{path}: a test binary lists {len(block)} results but declares "
                    f"{expected} tests ({passed} passed, {failed} failed, {ignored} ignored)"
                )
            cases.extend(block)
            expected, blocks = None, blocks + 1
    if expected is not None:
        raise ReportError(f"{path}: the output ends before the last test summary (truncated)")
    if not blocks or not cases:
        raise ReportError(f"{path}: no test binary ran (build or collection failure?)")
    return cases


# ─── Source maps: marker ID -> test function ────────────────────────────────

_CS_METHOD = re.compile(
    r"(?:public|internal|private|protected)\s+(?:static\s+)?(?:async\s+)?"
    r"(?:void|Task|ValueTask)\s+(\w+)\s*\("
)
_CS_TYPE = re.compile(r"\b(?:class|record|struct)\s+(\w+)")
_SWIFT_FUNC = re.compile(
    r"^\s*(?:@\w+\s+)*(?:(?:public|internal|private|override|final)\s+)*func\s+(test\w*)"
)
# Only XCTestCase subclasses own test methods; helper types nested in a test
# class must not capture its markers.
_SWIFT_TEST_TYPE = re.compile(
    r"^\s*(?:(?:public|internal|private|final|open|@\w+)\s+)*class\s+(\w+)\s*:\s*XCTestCase\b"
)


def map_csharp(directory: Path) -> dict[tuple[str, str], set[str]]:
    mapping: dict[tuple[str, str], set[str]] = {}
    for path in sorted(directory.rglob("*.cs")):
        cleaned = ccc._BLOCK_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
        for match in ccc._CS_TRAIT_PATTERN.finditer(cleaned):
            line_start = cleaned.rfind("\n", 0, match.start()) + 1
            if "//" in cleaned[line_start : match.start()]:
                continue
            method = _CS_METHOD.search(cleaned, match.end())
            types = list(_CS_TYPE.finditer(cleaned, 0, match.start()))
            if method is None or not types:
                raise ReportError(f"{path}: marker {match.group(1)} attaches to no test method")
            key = (types[-1].group(1), method.group(1))
            mapping.setdefault(key, set()).add(match.group(1))
    return mapping


def map_swift(directory: Path) -> dict[tuple[str, str], set[str]]:
    mapping: dict[tuple[str, str], set[str]] = {}
    for path in sorted(directory.rglob("*.swift")):
        lines = path.read_text(encoding="utf-8").splitlines()
        owner = ""
        for index, line in enumerate(lines):
            declared = _SWIFT_TEST_TYPE.match(line)
            if declared:
                owner = declared.group(1)
            match = ccc._SWIFT_COMMENT_MARKER_PATTERN.match(line)
            if match is None or not ccc._swift_marker_attaches_to_test(lines, index):
                continue
            if match.group(1).split("-", 1)[0] in ccc._NON_CONFORMANCE_PREFIXES:
                continue
            func = next((m.group(1) for m in map(_SWIFT_FUNC.match, lines[index + 1 :]) if m), None)
            if func is None:
                raise ReportError(f"{path}: marker {match.group(1)} attaches to no test")
            mapping.setdefault((owner, func), set()).add(match.group(1))
    return mapping


def map_rust(directory: Path) -> dict[tuple[str, str], set[str]]:
    mapping: dict[tuple[str, str], set[str]] = {}
    for path in sorted(directory.rglob("*.rs")):
        lines = ccc._mask_rust_non_code(path.read_text(encoding="utf-8")).splitlines()
        module = path.stem
        for index, line in enumerate(lines):
            match = ccc._RUST_COMMENT_MARKER_PATTERN.match(line)
            if match is None or not ccc._rust_marker_attaches_to_test(lines, index):
                continue
            if match.group(1).split("-", 1)[0] in ccc._NON_CONFORMANCE_PREFIXES:
                continue
            name = next(
                (
                    m.group(1)
                    for m in (
                        ccc._RUST_TEST_FN_PATTERN.match(raw.strip()) for raw in lines[index + 1 :]
                    )
                    if m and m.group(1)
                ),
                None,
            )
            if name is None:
                raise ReportError(f"{path}: marker {match.group(1)} attaches to no test")
            mapping.setdefault((module, name), set()).add(match.group(1))
    return mapping


def _source_ids(case: Case, mapping: dict[tuple[str, str], set[str]], flavor: str) -> set[str]:
    """IDs for a reported case: exact (container, function) first, then a
    function name that only one container defines."""
    container = case.container
    if flavor in ("swift", "csharp"):
        container = container.split(".")[-1].split("+")[-1]
    elif flavor == "rust":
        container = container.split("::")[-1]
    exact = mapping.get((container, case.name))
    if exact is not None:
        return exact
    matches = [ids for (_, name), ids in mapping.items() if name == case.name]
    return matches[0] if len(matches) == 1 else set()


# ─── Aggregation ─────────────────────────────────────────────────────────────

_FLAVORS: dict[str, tuple[str, str]] = {
    # flavor: (report format, source directory for marker mapping or "")
    "python": ("junit-property", ""),
    "typescript": ("junit-describe", ""),
    "csharp": ("trx", "langs/csharp/tests/VMx.Conformance.Tests"),
    "swift": ("xunit", "langs/swift/Tests/VMxTests"),
    "rust": ("libtest", "langs/rust/tests/conformance"),
}


def read_cases(flavor: str, reports: Iterable[Path]) -> list[Case]:
    report_format, _ = _FLAVORS[flavor]
    cases: list[Case] = []
    for report in reports:
        if report_format == "junit-property":
            cases.extend(read_junit(report, id_source="property"))
        elif report_format == "junit-describe":
            cases.extend(read_junit(report, id_source="describe"))
        elif report_format == "xunit":
            cases.extend(read_junit(report, id_source="source"))
        elif report_format == "trx":
            cases.extend(read_trx(report))
        else:
            cases.extend(read_libtest(report))
    return cases


def aggregate(
    required: set[str],
    cases: Iterable[Case],
    mapping: dict[tuple[str, str], set[str]] | None,
    flavor: str,
) -> dict[str, Evidence]:
    evidence = {ident: Evidence() for ident in sorted(required)}
    for case in cases:
        ids = set(case.ids) if mapping is None else _source_ids(case, mapping, flavor)
        for ident in ids & required:
            evidence[ident].cases.append({"case": case.display, "outcome": case.outcome})
    for item in evidence.values():
        outcomes = {case["outcome"] for case in item.cases}
        if "failed" in outcomes:
            item.status = "failed"
        elif "passed" in outcomes:
            item.status = "passed"
        elif "skipped" in outcomes:
            item.status = "skipped"
    return evidence


def _iter_problems(evidence: dict[str, Evidence]) -> Iterator[str]:
    for ident, item in evidence.items():
        if item.status == "passed":
            continue
        if item.status == "missing":
            yield f"  {ident}: missing (no executed case carries this ID)"
            continue
        names = ", ".join(
            f"{case['case']} [{case['outcome']}]"
            for case in item.cases
            if case["outcome"] != "passed"
        )
        yield f"  {ident}: {item.status} ({names})"


def check(
    flavor: str,
    reports: list[Path],
    *,
    repo_root: Path = REPO_ROOT,
    evidence_path: Path | None = None,
    commit: str | None = None,
    toolchain: str | None = None,
    configuration: str | None = None,
) -> int:
    try:
        required = ccc.parse_catalog_ids(repo_root / CATALOG_REL)
    except OSError as error:
        print(f"ERROR: cannot read the catalog: {error}", file=sys.stderr)
        return 2
    _, source = _FLAVORS[flavor]
    try:
        mapping = None
        if source:
            directory = repo_root / source
            if not directory.is_dir():
                raise ReportError(f"{directory} is not a directory")
            mapping = {"csharp": map_csharp, "swift": map_swift, "rust": map_rust}[flavor](
                directory
            )
        cases = read_cases(flavor, reports)
    except ReportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    evidence = aggregate(required, cases, mapping, flavor)
    counts = {
        status: sum(item.status == status for item in evidence.values()) for status in _STATUSES
    }
    print(
        f"{flavor} executed conformance: {counts['passed']}/{len(required)} passed, "
        f"{counts['failed']} failed, {counts['skipped']} skipped, {counts['missing']} missing "
        f"({len(cases)} executed cases)"
    )
    if evidence_path is not None:
        evidence_path.write_text(
            json.dumps(
                {
                    "flavor": flavor,
                    "commit": commit,
                    "toolchain": toolchain,
                    "configuration": configuration,
                    "rule": _RULE,
                    "required": len(required),
                    "counts": counts,
                    "ids": {
                        ident: {"status": item.status, "cases": item.cases}
                        for ident, item in evidence.items()
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    problems = list(_iter_problems(evidence))
    if problems:
        print(f"FAIL: {len(problems)} required ID(s) lack a passing execution:", file=sys.stderr)
        for line in problems:
            print(line, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flavor", required=True, choices=sorted(_FLAVORS))
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--toolchain")
    parser.add_argument("--configuration")
    args = parser.parse_args(argv)
    return check(
        args.flavor,
        args.report,
        repo_root=args.repo_root,
        evidence_path=args.evidence,
        commit=args.commit,
        toolchain=args.toolchain,
        configuration=args.configuration,
    )


if __name__ == "__main__":
    raise SystemExit(main())
