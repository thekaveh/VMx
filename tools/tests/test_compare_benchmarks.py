"""Tests for tools/compare-benchmarks.py."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_TOOL = Path(__file__).resolve().parents[1] / "compare-benchmarks.py"
_SPEC = importlib.util.spec_from_file_location("compare_benchmarks", _TOOL)
assert _SPEC and _SPEC.loader
compare_benchmarks = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(compare_benchmarks)


def report(**medians: float) -> dict[str, Any]:
    return {
        "schema": "vmx-bench/1",
        "flavor": "typescript",
        "commit": "abc",
        "runtime": {"name": "node", "version": "v22"},
        "hardware": {"cpu_model": "cpu", "logical_cores": 4, "arch": "x64"},
        "workload": {"quick": False},
        "cases": [
            {"id": case_id, "unit": "ns/op", "median": median, "rel_mad": 0.01, "samples": [median]}
            for case_id, median in medians.items()
        ],
        "probes": {"lifecycle.memory": {"bounded": True}},
    }


def write(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_runs_within_the_noise_band_pass(tmp_path: Path) -> None:
    baseline = write(tmp_path, "base.json", report(send=100.0, push=50.0))
    candidate = write(tmp_path, "cand.json", report(send=103.0, push=49.0))

    assert compare_benchmarks.main([str(baseline), str(candidate)]) == 0


def test_a_slowdown_beyond_the_band_is_flagged(tmp_path: Path) -> None:
    rows = compare_benchmarks.compare(report(send=100.0), report(send=130.0))

    assert rows[0]["status"] == "SLOWER"
    baseline = write(tmp_path, "base.json", report(send=100.0))
    candidate = write(tmp_path, "cand.json", report(send=130.0))
    assert compare_benchmarks.main([str(baseline), str(candidate)]) == 1


def test_threshold_follows_observed_variance() -> None:
    noisy = report(send=100.0)
    noisy["cases"][0]["rel_mad"] = 0.10

    rows = compare_benchmarks.compare(noisy, report(send=130.0), k=4.0, floor=0.05)

    assert rows[0]["threshold"] == pytest.approx(0.40)
    assert rows[0]["status"] == "ok"


def test_faster_new_and_missing_cases_are_reported() -> None:
    rows = compare_benchmarks.compare(report(send=100.0, gone=10.0), report(send=50.0, added=5.0))

    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses == {"send": "FASTER", "added": "NEW", "gone": "MISSING"}


def test_an_unbounded_probe_fails_the_review(tmp_path: Path) -> None:
    candidate_data = report(send=100.0)
    candidate_data["probes"]["lifecycle.memory"]["bounded"] = False
    baseline = write(tmp_path, "base.json", report(send=100.0))
    candidate = write(tmp_path, "cand.json", candidate_data)

    assert compare_benchmarks.main([str(baseline), str(candidate)]) == 1


def test_incomparable_runs_warn_and_strict_mode_refuses(tmp_path: Path) -> None:
    other = copy.deepcopy(report(send=100.0))
    other["hardware"]["cpu_model"] = "other cpu"
    baseline = write(tmp_path, "base.json", report(send=100.0))
    candidate = write(tmp_path, "cand.json", other)

    assert compare_benchmarks.comparability(report(send=1.0), other)
    assert compare_benchmarks.main([str(baseline), str(candidate)]) == 0
    assert compare_benchmarks.main([str(baseline), str(candidate), "--strict"]) == 2


def test_reports_without_the_required_fields_are_rejected(tmp_path: Path) -> None:
    broken = report(send=100.0)
    del broken["hardware"]
    baseline = write(tmp_path, "base.json", report(send=100.0))
    candidate = write(tmp_path, "cand.json", broken)

    assert compare_benchmarks.main([str(baseline), str(candidate)]) == 2
    with pytest.raises(compare_benchmarks.ReportError):
        compare_benchmarks.validate({**report(send=1.0), "schema": "other"}, "x")


@pytest.mark.parametrize(
    "baseline_file",
    sorted((Path(__file__).resolve().parents[2] / "benchmarks/baselines").glob("*.json")),
)
def test_committed_baselines_follow_the_report_format(baseline_file: Path) -> None:
    data = compare_benchmarks.load(baseline_file)

    assert data["dirty"] is False
    assert data["workload"]["quick"] is False
    assert data["workload"]["slowdown"] == {}
    assert compare_benchmarks.unbounded_probes(data) == []
