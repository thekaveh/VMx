#!/usr/bin/env python3
"""Fail when aggregate Cobertura line or branch coverage drops below a floor."""

from __future__ import annotations

import argparse
import re
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
    reports: list[Path],
    minimum_line: float,
    minimum_branch: float,
    package_names: set[str] | None = None,
) -> tuple[float, float]:
    """Aggregate report counters, enforce percentage floors, and return rates."""
    if not reports:
        raise ValueError("no Cobertura coverage reports found")

    totals = {"lines-covered": 0, "lines-valid": 0, "branches-covered": 0, "branches-valid": 0}
    seen_packages: set[str] = set()
    merged_lines: dict[tuple[str, str, str], bool] = {}
    merged_branches: dict[tuple[str, str, str], tuple[int, int]] = {}
    for report in reports:
        root = ET.parse(report).getroot()
        if package_names is None:
            for key in totals:
                totals[key] += int(root.attrib[key])
            continue

        for package in root.findall("./packages/package"):
            package_name = package.attrib.get("name")
            if package_name not in package_names:
                continue
            seen_packages.add(package_name)
            for class_element in package.findall("./classes/class"):
                filename = class_element.attrib.get("filename")
                if not filename:
                    raise ValueError("Cobertura class lacks a source filename")
                filename = filename.replace("\\", "/")
                package_marker = f"{package_name}/"
                marker_index = filename.rfind(package_marker)
                if marker_index >= 0:
                    filename = filename[marker_index:]
                for line in class_element.findall("./lines/line"):
                    key = (package_name, filename, line.attrib["number"])
                    covered = int(line.attrib.get("hits", "0")) > 0
                    merged_lines[key] = merged_lines.get(key, False) or covered
                    if line.attrib.get("branch", "false").lower() != "true":
                        continue
                    match = re.search(r"\((\d+)/(\d+)\)", line.attrib.get("condition-coverage", ""))
                    if match is None:
                        raise ValueError("Cobertura branch line lacks condition counters")
                    branch = (int(match.group(1)), int(match.group(2)))
                    previous = merged_branches.get(key, (0, branch[1]))
                    merged_branches[key] = (
                        max(previous[0], branch[0]),
                        max(previous[1], branch[1]),
                    )

    missing_packages = (package_names or set()) - seen_packages
    if missing_packages:
        missing = ", ".join(sorted(missing_packages))
        raise ValueError(f"Cobertura reports omit required packages: {missing}")

    if package_names is not None:
        totals["lines-valid"] = len(merged_lines)
        totals["lines-covered"] = sum(merged_lines.values())
        totals["branches-covered"] = sum(covered for covered, _valid in merged_branches.values())
        totals["branches-valid"] = sum(valid for _covered, valid in merged_branches.values())

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
    parser.add_argument("--package", action="append", default=[])
    args = parser.parse_args()

    try:
        line_rate, branch_rate = check_coverage(
            find_reports(args.paths),
            args.minimum_line,
            args.minimum_branch,
            set(args.package) or None,
        )
    except (ET.ParseError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(f"coverage floors passed: lines={line_rate:.2f}% branches={branch_rate:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
