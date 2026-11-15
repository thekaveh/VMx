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

C# grades each target framework separately. The frameworks are the
``<TargetFrameworks>`` of the conformance project, and each case's framework is
the ``bin/<configuration>/<framework>/`` segment of its TRX storage path. The
rule applies per framework, so an ID passes only when it passes on every one. Its
status is the first of ``failed``, ``skipped``, and ``missing`` that any
framework has.

How cases map to IDs:

* Python (JUnit XML from pytest): the ``conformance`` testcase property that
  ``langs/python/tests/conftest.py`` records from each ``conformance`` marker.
* TypeScript (JUnit XML from Vitest): a ``describe`` title that is exactly the ID.
* C# (TRX), Swift (xUnit XML from ``swift test --xunit-output``), and Rust
  (libtest output from ``cargo test``): the test function that the flavor's
  source marker attaches to, found with the same marker rules as the coverage
  checker.

SwiftPM's xUnit report writes an ``XCTSkip`` test as a plain passing case, so
the Swift check also scans the test sources. Every ``XCTSkip`` call outside a
comment fails the gate. A call inside a marked test fails that ID, and a call
anywhere else is reported by file and line.

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
_CSHARP_PROJECT = Path("langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj")
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
    framework: str = ""  # C# target framework, such as net8.0; empty elsewhere


@dataclass
class Evidence:
    status: str = "missing"
    cases: list[dict[str, str]] = field(default_factory=list)
    frameworks: dict[str, str] = field(default_factory=dict)  # C# only: framework -> status


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


# dotnet test stores each test assembly under bin/<configuration>/<framework>/.
_TRX_FRAMEWORK = re.compile(r"[\\/]bin[\\/][^\\/]+[\\/](net[^\\/]*)[\\/]")


def _trx_framework(unit_test: ET.Element, path: Path) -> str:
    found = _TRX_FRAMEWORK.findall(unit_test.get("storage", ""))
    if not found:
        raise ReportError(
            f"{path}: UnitTest {unit_test.get('id')} has no target framework in its storage path"
        )
    return found[-1]


def read_trx(path: Path) -> list[Case]:
    root = _parse_xml(path)
    if root.tag != f"{{{_TRX_NS['t']}}}TestRun":
        raise ReportError(f"{path}: root <{root.tag}> is not a TRX TestRun")
    methods: dict[str, tuple[str, str, str]] = {}
    for unit_test in root.iterfind("t:TestDefinitions/t:UnitTest", _TRX_NS):
        method = unit_test.find("t:TestMethod", _TRX_NS)
        if method is None:
            raise ReportError(f"{path}: UnitTest {unit_test.get('id')} has no TestMethod")
        # Keep the namespace: only the conformance suite's classes may credit an ID.
        class_name = (method.get("className") or "").split(",")[0]
        methods[unit_test.get("id", "")] = (
            class_name,
            method.get("name", ""),
            _trx_framework(unit_test, path),
        )

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
            class_name, method_name, framework = methods[result.get("testId", "")]
        except KeyError as error:
            raise ReportError(
                f"{path}: result {result.get('testName')!r} has no definition"
            ) from error
        method_name = _strip_parameters(method_name).split(".")[-1]
        cases.append(
            Case(
                class_name,
                method_name,
                result.get("testName", ""),
                outcome,
                framework=framework,
            )
        )
    if not cases:
        raise ReportError(f"{path}: the report lists no executed test cases")
    return cases


def read_csharp_frameworks(repo_root: Path) -> tuple[str, ...]:
    """The target frameworks that the conformance project runs."""
    project = repo_root / _CSHARP_PROJECT
    if not project.is_file():
        raise ReportError(f"{project} is not a file (it defines the C# target frameworks)")
    element = _parse_xml(project).find(".//TargetFrameworks")
    names = [] if element is None else (element.text or "").split(";")
    frameworks = tuple(name.strip() for name in names if name.strip())
    if not frameworks:
        raise ReportError(f"{project}: no <TargetFrameworks> element")
    return frameworks


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
# xUnit test classes are public; private helper types nested in a test class
# must not capture its markers.
_CS_TEST_TYPE = re.compile(r"\bpublic\s+(?:(?:sealed|static|partial|abstract)\s+)*class\s+(\w+)")
_CS_NAMESPACE = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
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
        namespace = _CS_NAMESPACE.search(cleaned)
        prefix = f"{namespace.group(1)}." if namespace else ""
        for match in ccc._CS_TRAIT_PATTERN.finditer(cleaned):
            line_start = cleaned.rfind("\n", 0, match.start()) + 1
            if "//" in cleaned[line_start : match.start()]:
                continue
            method = _CS_METHOD.search(cleaned, match.end())
            types = list(_CS_TEST_TYPE.finditer(cleaned, 0, match.start()))
            if method is None or not types:
                raise ReportError(f"{path}: marker {match.group(1)} attaches to no test method")
            key = (prefix + types[-1].group(1), method.group(1))
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


_SWIFT_DECL = re.compile(
    r"^\s*(?:@\w+\s+)*(?:(?:public|internal|private|fileprivate|final|open|override|static)\s+)*"
    r"(func|class|struct|enum|extension|actor)\b\s*(\w+)?"
)


def find_swift_skips(
    directory: Path, mapping: dict[tuple[str, str], set[str]], repo_root: Path
) -> list[tuple[frozenset[str], str]]:
    """Each ``XCTSkip`` call outside a comment, with the IDs of the test it sits in.

    The skip belongs to the last ``func`` or type declaration above it. A skip in
    an unmarked helper therefore never credits a marked test that calls the helper.
    This also matches ``XCTSkipIf`` and ``XCTSkipUnless``.
    """
    hits: list[tuple[frozenset[str], str]] = []
    for path in sorted(directory.rglob("*.swift")):
        text = path.read_text(encoding="utf-8")
        # Keep the newlines of block comments so that line numbers stay true.
        text = ccc._BLOCK_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        owner = func = ""
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.split("//", 1)[0]
            owned = _SWIFT_TEST_TYPE.match(line)
            if owned:
                owner = owned.group(1)
            declared = _SWIFT_DECL.match(line)
            if declared:
                func = (declared.group(2) or "") if declared.group(1) == "func" else ""
            if "XCTSkip" in line:
                ids = frozenset(mapping.get((owner, func), set()))
                hits.append((ids, f"{path.relative_to(repo_root)}:{number}"))
    return hits


def _source_ids(case: Case, mapping: dict[tuple[str, str], set[str]], flavor: str) -> set[str]:
    """IDs for a reported case, matched exactly on (container, function).

    There is deliberately no name-only fallback: a same-named test in another
    class or project must never be credited to an ID. A mismatch shows up as a
    missing ID, which fails loudly.
    """
    if flavor == "rust":
        # Conformance paths are conformance::file_module[::nested]::function, from
        # the `mod conformance { ... }` wrapper in langs/rust/tests/conformance.rs.
        # A src unit test has another root, even when its module shares the stem.
        segments = case.container.split("::")
        if len(segments) < 2 or segments[0] != "conformance":
            return set()
        return mapping.get((segments[1], case.name), set())
    if flavor == "csharp":
        # TRX names a nested test class Namespace.Outer+Inner; markers record
        # the namespace and the innermost public class.
        namespace, _, type_name = case.container.rpartition(".")
        type_name = type_name.split("+")[-1]
        qualified = f"{namespace}.{type_name}" if namespace else type_name
        return mapping.get((qualified, case.name), set())
    container = case.container.split(".")[-1].split("+")[-1]
    return mapping.get((container, case.name), set())


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


def _roll_up(cases: list[dict[str, str]]) -> str:
    outcomes = {case["outcome"] for case in cases}
    if "failed" in outcomes:
        return "failed"
    if "passed" in outcomes:
        return "passed"
    if "skipped" in outcomes:
        return "skipped"
    return "missing"


def aggregate(
    required: set[str],
    cases: Iterable[Case],
    mapping: dict[tuple[str, str], set[str]] | None,
    flavor: str,
    frameworks: tuple[str, ...] = (),
) -> dict[str, Evidence]:
    evidence = {ident: Evidence() for ident in sorted(required)}
    for case in cases:
        ids = set(case.ids) if mapping is None else _source_ids(case, mapping, flavor)
        for ident in ids & required:
            evidence[ident].cases.append(
                {"case": case.display, "outcome": case.outcome, "framework": case.framework}
            )
    for item in evidence.values():
        if not frameworks:
            item.status = _roll_up(item.cases)
            continue
        # Each target framework is graded alone. A pass on one framework never
        # covers an ID that did not execute on another.
        for framework in frameworks:
            item.frameworks[framework] = _roll_up(
                [case for case in item.cases if case["framework"] == framework]
            )
        statuses = set(item.frameworks.values())
        item.status = next((s for s in ("failed", "skipped", "missing") if s in statuses), "passed")
    return evidence


def _apply_swift_skips(
    evidence: dict[str, Evidence], skips: list[tuple[frozenset[str], str]]
) -> list[str]:
    """An XCTSkip fails each required ID whose test holds it. Any other skip is a problem alone."""
    problems: list[str] = []
    for ids, location in skips:
        attributed = [ident for ident in sorted(ids) if ident in evidence]
        if not attributed:
            problems.append(f"  {location}: XCTSkip outside any required conformance test")
        for ident in attributed:
            item = evidence[ident]
            item.status = "failed"
            item.cases.append(
                {"case": f"XCTSkip at {location}", "outcome": "skipped", "framework": ""}
            )
    return problems


def _names(cases: Iterable[dict[str, str]]) -> str:
    return ", ".join(
        f"{case['case']} [{case['outcome']}]" for case in cases if case["outcome"] != "passed"
    )


def _iter_problems(evidence: dict[str, Evidence]) -> Iterator[str]:
    for ident, item in evidence.items():
        if item.status == "passed":
            continue
        if item.frameworks:
            for framework, status in item.frameworks.items():
                if status == "passed":
                    continue
                if status == "missing":
                    yield f"  {ident}: missing on {framework} (no executed case carries this ID)"
                    continue
                cases = [case for case in item.cases if case["framework"] == framework]
                yield f"  {ident}: {status} on {framework} ({_names(cases)})"
            continue
        if item.status == "missing":
            yield f"  {ident}: missing (no executed case carries this ID)"
            continue
        yield f"  {ident}: {item.status} ({_names(item.cases)})"


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
        skips: list[tuple[frozenset[str], str]] = []
        if source:
            directory = repo_root / source
            if not directory.is_dir():
                raise ReportError(f"{directory} is not a directory")
            mapping = {"csharp": map_csharp, "swift": map_swift, "rust": map_rust}[flavor](
                directory
            )
            if flavor == "swift":
                skips = find_swift_skips(directory, mapping, repo_root)
        frameworks = read_csharp_frameworks(repo_root) if flavor == "csharp" else ()
        cases = read_cases(flavor, reports)
    except ReportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    evidence = aggregate(required, cases, mapping, flavor, frameworks)
    source_problems = _apply_swift_skips(evidence, skips)
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
                    "rule": _RULE + (", on each target framework" if frameworks else ""),
                    "required": len(required),
                    "counts": counts,
                    "ids": {
                        ident: {
                            "status": item.status,
                            "frameworks": item.frameworks,
                            "cases": item.cases,
                        }
                        for ident, item in evidence.items()
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    problems = list(_iter_problems(evidence)) + source_problems
    if problems:
        print(f"FAIL: {len(problems)} conformance problem(s):", file=sys.stderr)
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
