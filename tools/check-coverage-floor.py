#!/usr/bin/env python3
"""Check an llvm-cov coverage export against a flavor's recorded floor.

Rust (`cargo llvm-cov --json --summary-only`) and Swift
(`swift test --enable-code-coverage`, `swift test --show-codecov-path`) both
write the llvm-cov JSON export format. This tool recomputes line, region, and
function totals over the flavor's library sources only, compares them with the
floors in `tools/coverage-floors.json`, and fails when any metric drops below
its floor. A failure names the files that gained uncovered lines since the
recorded per-file baseline, or, without one, the files with the most uncovered
lines.

Each floor is the lowest figure measured across repeated runs of the baseline
commit, so only run-to-run variation in scheduling-dependent paths is tolerated.
Raise floors as coverage improves; never lower one to make a change pass.

Exit codes:
    0  Every metric meets its floor.
    1  At least one metric is below its floor.
    2  The report or floor file is missing, malformed, truncated, or has no
       matching library sources.

Usage:
    python3 tools/check-coverage-floor.py --flavor rust --report rust-coverage.json \\
        [--provenance coverage-provenance.json --commit SHA --toolchain "rustc 1.94.0"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOORS_PATH = REPO_ROOT / "tools" / "coverage-floors.json"
METRICS = ("lines", "regions", "functions")


class ReportError(Exception):
    """The coverage report cannot be trusted as evidence."""


def load_files(report_path: Path) -> list[dict[str, object]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"cannot read coverage report {report_path}: {error}") from error
    if not isinstance(report, dict) or report.get("type") != "llvm.coverage.json.export":
        raise ReportError(f"{report_path} is not an llvm-cov JSON export")
    data = report.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ReportError(f"{report_path} has no coverage data")
    files = data[0].get("files")
    if not isinstance(files, list):
        raise ReportError(f"{report_path} has no per-file summaries")
    return files


def select_sources(
    files: list[dict[str, object]], include: str, exclude: str | None
) -> list[dict[str, object]]:
    included = re.compile(include)
    excluded = re.compile(exclude) if exclude else None
    selected = []
    for entry in files:
        name = str(entry.get("filename", "")).replace("\\", "/")
        if included.search(name) and not (excluded and excluded.search(name)):
            selected.append(entry)
    return selected


def excluded_counts(
    files: list[dict[str, object]], include: str, exclude: str | None
) -> dict[str, int]:
    """How many reported files the denominator leaves out, by reason.

    Test helpers, generated and build output (matched by ``exclude``) and files
    outside the library (not matched by ``include``) are reported separately, so
    an exclusion is visible instead of silently improving the figure.
    """
    included = re.compile(include)
    excluded = re.compile(exclude) if exclude else None
    counts = {"excluded": 0, "outside": 0}
    for entry in files:
        name = str(entry.get("filename", "")).replace("\\", "/")
        if excluded and excluded.search(name):
            counts["excluded"] += 1
        elif not included.search(name):
            counts["outside"] += 1
    return counts


def totals(files: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for metric in METRICS:
        count = covered = 0
        for entry in files:
            summary = entry.get("summary")
            if not isinstance(summary, dict) or not isinstance(summary.get(metric), dict):
                raise ReportError(f"{entry.get('filename')} has no {metric} summary")
            count += int(summary[metric]["count"])
            covered += int(summary[metric]["covered"])
        percent = 100.0 * covered / count if count else 100.0
        result[metric] = {"count": count, "covered": covered, "percent": percent}
    return result


def source_key(entry: dict[str, object], include: str) -> str:
    """The file's path below the include prefix, e.g. ``token_paging.rs``."""
    name = str(entry.get("filename", "")).replace("\\", "/")
    match = re.search(include, name)
    return name[match.end() :] if match else name


def uncovered_lines(entry: dict[str, object]) -> int:
    lines = entry["summary"]["lines"]  # type: ignore[index]
    return int(lines["count"]) - int(lines["covered"])


def regressions(
    files: list[dict[str, object]], include: str, baseline: dict[str, int]
) -> list[str]:
    """Files with more uncovered lines than the recorded baseline, worst first."""
    rows = []
    for entry in files:
        key = source_key(entry, include)
        missed = uncovered_lines(entry)
        before = baseline.get(key, 0)
        if missed > before:
            rows.append((missed - before, key, missed, before))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [
        f"  {key}: {missed} uncovered lines, {delta} more than the baseline's {before}"
        for delta, key, missed, before in rows
    ]


def least_covered(files: list[dict[str, object]], limit: int = 10) -> list[str]:
    rows = []
    for entry in files:
        lines = entry["summary"]["lines"]  # type: ignore[index]
        missed = uncovered_lines(entry)
        if missed:
            rows.append((missed, float(lines["percent"]), str(entry["filename"])))
    rows.sort(key=lambda row: (-row[0], row[2]))
    return [
        f"  {Path(name).name}: {missed} uncovered lines ({percent:.2f}% covered)"
        for missed, percent, name in rows[:limit]
    ]


def check(
    flavor: str,
    report_path: Path,
    floors_path: Path = FLOORS_PATH,
    provenance: Path | None = None,
    commit: str | None = None,
    toolchain: str | None = None,
) -> int:
    try:
        floors_file = json.loads(floors_path.read_text(encoding="utf-8"))
        floor = floors_file[flavor]
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"ERROR: no coverage floor for {flavor!r} in {floors_path}: {error}", file=sys.stderr)
        return 2
    try:
        reported = load_files(report_path)
        files = select_sources(reported, floor["include"], floor.get("exclude"))
        if not files:
            raise ReportError(f"no files in {report_path} match {floor['include']!r}")
        measured = totals(files)
    except ReportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    left_out = excluded_counts(reported, floor["include"], floor.get("exclude"))

    failures = []
    print(f"{flavor} coverage over {len(files)} library source files:")
    print(
        f"  not counted: {left_out['excluded']} test, generated, or build files "
        f"(exclude {floor.get('exclude')!r}); {left_out['outside']} files outside "
        f"{floor['include']!r}"
    )
    for metric in METRICS:
        value = measured[metric]["percent"]
        minimum = float(floor[metric])
        status = "ok" if value >= minimum else "BELOW FLOOR"
        print(f"  {metric:<9} {value:6.2f}%  floor {minimum:6.2f}%  {status}")
        if value < minimum:
            failures.append(metric)

    if provenance is not None:
        provenance.write_text(
            json.dumps(
                {
                    "flavor": flavor,
                    "commit": commit,
                    "toolchain": toolchain,
                    "source_files": len(files),
                    "not_counted": left_out,
                    "metrics": measured,
                    "floors": {metric: float(floor[metric]) for metric in METRICS},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    baseline = floor.get("baseline", {}).get("uncovered_lines")
    if not baseline and not failures:
        # No per-file baseline yet: show where coverage is thinnest, so the first
        # measurement can be reviewed before its figures become the floor.
        print("Files with the most uncovered lines (no per-file baseline recorded):")
        for row in least_covered(files):
            print(row)

    if failures:
        print(
            f"FAIL: {flavor} {', '.join(failures)} coverage fell below its floor.",
            file=sys.stderr,
        )
        grown = regressions(files, floor["include"], baseline) if baseline else []
        if grown:
            print("Files that lost coverage since the baseline:", file=sys.stderr)
            rows = grown
        else:
            print("Files with the most uncovered lines:", file=sys.stderr)
            rows = least_covered(files)
        for row in rows:
            print(row, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flavor", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--floors", type=Path, default=FLOORS_PATH)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--toolchain")
    args = parser.parse_args(argv)
    return check(
        args.flavor, args.report, args.floors, args.provenance, args.commit, args.toolchain
    )


if __name__ == "__main__":
    raise SystemExit(main())
