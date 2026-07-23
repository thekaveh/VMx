#!/usr/bin/env python3
"""Fail when aggregate Cobertura line or branch coverage drops below a floor."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def find_reports(paths: list[Path]) -> list[Path]:
    """Return unique Cobertura XML reports beneath files or directories."""
    reports: set[Path] = set()
    for path in paths:
        if path.is_dir():
            reports.update(path.rglob("coverage.cobertura.xml"))
        elif path.is_file():
            reports.add(path)
    return sorted(reports)


def check_coverage(
    reports: list[Path], minimum_line: float, minimum_branch: float
) -> tuple[float, float]:
    """Aggregate report counters, enforce percentage floors, and return rates."""
    if not reports:
        raise ValueError("no Cobertura coverage reports found")

    totals = {"lines-covered": 0, "lines-valid": 0, "branches-covered": 0, "branches-valid": 0}
    for report in reports:
        root = ET.parse(report).getroot()
        for key in totals:
            totals[key] += int(root.attrib[key])

    if totals["lines-valid"] == 0 or totals["branches-valid"] == 0:
        raise ValueError("Cobertura reports contain no valid line or branch counters")

    line_rate = 100 * totals["lines-covered"] / totals["lines-valid"]
    branch_rate = 100 * totals["branches-covered"] / totals["branches-valid"]
    if line_rate < minimum_line:
        raise ValueError(f"line coverage {line_rate:.2f}% is below {minimum_line:.2f}%")
    if branch_rate < minimum_branch:
        raise ValueError(f"branch coverage {branch_rate:.2f}% is below {minimum_branch:.2f}%")
    return line_rate, branch_rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--minimum-line", type=float, required=True)
    parser.add_argument("--minimum-branch", type=float, required=True)
    args = parser.parse_args()

    try:
        line_rate, branch_rate = check_coverage(
            find_reports(args.paths), args.minimum_line, args.minimum_branch
        )
    except (ET.ParseError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(f"coverage floors passed: lines={line_rate:.2f}% branches={branch_rate:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
