#!/usr/bin/env python3
"""Compare llvm-cov exports of repeated runs and list where their coverage differs.

A coverage floor in `tools/coverage-floors.json` is the lowest figure across
repeated runs of the same sources, so runs that disagree lower the floor. This
tool shows where they disagree: each run's line, region, and function totals
over the flavor's library sources, then every source line that some runs
execute and others do not, with that line's text when the source is readable.
Use it when recording a baseline, or to find tests whose coverage depends on
scheduling.

Exit codes:
    0  Every run executed the same lines.
    1  At least one line was executed in some runs and not in others.
    2  A report or the floor file is missing or malformed, or a report has no
       line segments (exports made with `--summary-only`).

Usage:
    python3 tools/compare-coverage-runs.py --flavor swift run-1.json run-2.json ...
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
FLOORS_PATH = TOOLS_DIR / "coverage-floors.json"


def _floor_tool():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "check_coverage_floor", TOOLS_DIR / "check-coverage-floor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


floor = _floor_tool()


def unexecuted(entry: dict[str, object]) -> set[int]:
    ranges = floor.uncovered_ranges(entry)
    if ranges is None:
        raise floor.ReportError(f"{entry.get('filename')} has no line segments")
    return {line for start, end in ranges for line in range(start, end + 1)}


def source_line(filename: str, number: int) -> str:
    try:
        lines = Path(filename).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    return lines[number - 1].strip() if 0 < number <= len(lines) else ""


def compare(flavor: str, reports: list[Path], floors_path: Path = FLOORS_PATH) -> int:
    try:
        entry = json.loads(floors_path.read_text(encoding="utf-8"))[flavor]
        include, exclude = entry["include"], entry.get("exclude")
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print(f"ERROR: no coverage floor for {flavor!r} in {floors_path}: {error}", file=sys.stderr)
        return 2

    runs: list[tuple[str, dict[str, set[int]], dict[str, str]]] = []
    region_counts: dict[str, list[int]] = {}
    try:
        for report in reports:
            files = floor.select_sources(floor.load_files(report), include, exclude)
            if not files:
                raise floor.ReportError(f"no files in {report} match {include!r}")
            measured = floor.totals(files)
            figures = "  ".join(
                f"{metric} {measured[metric]['covered']:.0f}/{measured[metric]['count']:.0f}"
                for metric in floor.METRICS
            )
            print(f"{report.name}: {figures}")
            missed = {floor.source_key(file, include): unexecuted(file) for file in files}
            names = {floor.source_key(file, include): str(file["filename"]) for file in files}
            for file in files:
                regions = file["summary"]["regions"]  # type: ignore[index]
                region_counts.setdefault(floor.source_key(file, include), []).append(
                    int(regions["covered"])
                )
            runs.append((report.name, missed, names))
    except floor.ReportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    differing = []
    for key in sorted({key for _, missed, _ in runs for key in missed}):
        sets = [missed.get(key, set()) for _, missed, _ in runs]
        filename = next(names[key] for _, _, names in runs if key in names)
        for number in sorted(set().union(*sets) - set.intersection(*sets)):
            unexecuted_in = [
                name for (name, _, _), lines in zip(runs, sets, strict=True) if number in lines
            ]
            differing.append((key, number, unexecuted_in, source_line(filename, number)))

    moved_regions = {key: counts for key, counts in region_counts.items() if len(set(counts)) > 1}
    if not differing and not moved_regions:
        print(f"All {len(runs)} runs executed the same lines and regions.")
        return 0
    if differing:
        print(f"{len(differing)} lines differ across {len(runs)} runs:")
        for key, number, unexecuted_in, text in differing:
            print(
                f"  {key}:{number} unexecuted in {len(unexecuted_in)} of {len(runs)} "
                f"({', '.join(unexecuted_in)}) | {text}"
            )
    for key, counts in sorted(moved_regions.items()):
        print(f"  {key}: covered regions per run {counts}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flavor", required=True)
    parser.add_argument("--floors", type=Path, default=FLOORS_PATH)
    parser.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args(argv)
    return compare(args.flavor, args.reports, args.floors)


if __name__ == "__main__":
    sys.exit(main())
