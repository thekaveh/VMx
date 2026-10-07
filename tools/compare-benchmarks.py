#!/usr/bin/env python3
"""Compare two VMx benchmark reports and flag cases outside the noise band.

Usage:
    python3 tools/compare-benchmarks.py BASELINE.json CANDIDATE.json [--k 4] [--floor 0.05]

Both reports come from a `benchmarks/<flavor>` harness (schema `vmx-bench/1`).
For each case present in both, the review threshold is derived from the
observed variance of the two runs:

    threshold = max(floor, k * max(baseline.rel_mad, candidate.rel_mad))

where `rel_mad` is the median absolute deviation divided by the median. A case
is SLOWER when candidate.median > baseline.median * (1 + threshold) and FASTER
when candidate.median < baseline.median / (1 + threshold). The exit status is 1
when any case is slower, or when a lifecycle probe in the candidate is not
bounded. It is a review signal for a person, not a hard CI gate; see
docs/content/performance-methodology.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "vmx-bench/1"
REQUIRED = ("schema", "flavor", "commit", "runtime", "hardware", "workload", "cases")
CASE_FIELDS = ("id", "unit", "median", "rel_mad", "samples")


class ReportError(ValueError):
    """The report does not follow the vmx-bench/1 format."""


def load(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    validate(report, str(path))
    return report


def validate(report: dict[str, Any], label: str) -> None:
    missing = [key for key in REQUIRED if key not in report]
    if missing:
        raise ReportError(f"{label}: missing {', '.join(missing)}")
    if report["schema"] != SCHEMA:
        raise ReportError(f"{label}: schema {report['schema']!r} is not {SCHEMA!r}")
    for case in report["cases"]:
        absent = [key for key in CASE_FIELDS if key not in case]
        if absent:
            raise ReportError(f"{label}: case {case.get('id')!r} lacks {', '.join(absent)}")


def comparability(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Reasons the two runs are not like for like; empty when comparable."""
    reasons = []
    if baseline["flavor"] != candidate["flavor"]:
        reasons.append(f"flavor {baseline['flavor']} vs {candidate['flavor']}")
    for key in ("cpu_model", "logical_cores", "arch"):
        before, after = baseline["hardware"].get(key), candidate["hardware"].get(key)
        if before != after:
            reasons.append(f"hardware.{key} {before!r} vs {after!r}")
    before, after = baseline["runtime"].get("version"), candidate["runtime"].get("version")
    if before != after:
        reasons.append(f"runtime {before!r} vs {after!r}")
    if baseline["workload"].get("quick") != candidate["workload"].get("quick"):
        reasons.append("one report used --quick")
    return reasons


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], k: float = 4.0, floor: float = 0.05
) -> list[dict[str, Any]]:
    base_cases = {case["id"]: case for case in baseline["cases"]}
    rows = []
    for case in candidate["cases"]:
        base = base_cases.get(case["id"])
        if base is None:
            rows.append({"id": case["id"], "status": "NEW"})
            continue
        threshold = max(floor, k * max(base["rel_mad"], case["rel_mad"]))
        ratio = case["median"] / base["median"] if base["median"] else float("inf")
        if ratio > 1 + threshold:
            status = "SLOWER"
        elif ratio < 1 / (1 + threshold):
            status = "FASTER"
        else:
            status = "ok"
        rows.append(
            {
                "id": case["id"],
                "status": status,
                "baseline": base["median"],
                "candidate": case["median"],
                "ratio": ratio,
                "threshold": threshold,
            }
        )
    candidate_ids = {case["id"] for case in candidate["cases"]}
    rows.extend(
        {"id": case_id, "status": "MISSING"}
        for case_id in base_cases
        if case_id not in candidate_ids
    )
    return rows


def unbounded_probes(report: dict[str, Any]) -> list[str]:
    return [
        name
        for name, probe in report.get("probes", {}).items()
        if isinstance(probe, dict) and probe.get("bounded") is False
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--k", type=float, default=4.0, help="noise multiplier (default 4)")
    parser.add_argument(
        "--floor", type=float, default=0.05, help="minimum threshold (default 0.05)"
    )
    parser.add_argument(
        "--strict", action="store_true", help="fail when the runs are not comparable"
    )
    options = parser.parse_args(argv)
    try:
        baseline, candidate = load(options.baseline), load(options.candidate)
    except (OSError, json.JSONDecodeError, ReportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    reasons = comparability(baseline, candidate)
    for reason in reasons:
        print(f"warning: not like for like: {reason}", file=sys.stderr)
    if reasons and options.strict:
        return 2

    rows = compare(baseline, candidate, options.k, options.floor)
    print(f"{'case':<36} {'baseline':>11} {'candidate':>11} {'ratio':>7} {'band':>7}  status")
    for row in rows:
        if "ratio" in row:
            print(
                f"{row['id']:<36} {row['baseline']:>11.1f} {row['candidate']:>11.1f} "
                f"{row['ratio']:>7.3f} {row['threshold'] * 100:>6.1f}%  {row['status']}"
            )
        else:
            print(f"{row['id']:<36} {'':>11} {'':>11} {'':>7} {'':>7}  {row['status']}")
    unbounded = unbounded_probes(candidate)
    for name in unbounded:
        print(f"probe {name} is not bounded in the candidate")
    slower = [row["id"] for row in rows if row["status"] == "SLOWER"]
    if slower or unbounded:
        print(f"review: {len(slower)} slower case(s), {len(unbounded)} unbounded probe(s)")
        return 1
    print("no case outside its noise band")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
