"""Unit tests for tools/compare-coverage-runs.py."""

import json
from pathlib import Path

import compare_coverage_runs as compare
import pytest


def _floors(tmp_path: Path) -> Path:
    path = tmp_path / "floors.json"
    path.write_text(
        json.dumps({"demo": {"include": "/src/", "exclude": "/tests/"}}), encoding="utf-8"
    )
    return path


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "race.rs"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "fn race() {\n    if lost {\n        lost_the_race();\n    }\n    finish();\n}\n",
        encoding="utf-8",
    )
    return source


def _report(tmp_path: Path, name: str, source: Path, race_count: int) -> Path:
    # Segments are [line, column, count, has_count, is_region_entry, is_gap].
    segments = [
        [1, 1, 4, True, True, False],
        [2, 13, race_count, True, True, False],
        [4, 6, 4, True, False, False],
        [6, 2, 0, False, False, False],
    ]
    covered = 6 if race_count else 4

    def metric(count: int, hit: int) -> dict[str, float]:
        return {"count": count, "covered": hit, "percent": 100.0 * hit / count}

    files = [
        {
            "filename": str(source),
            "segments": segments,
            "summary": {
                "lines": metric(6, covered),
                "regions": metric(2, 2 if race_count else 1),
                "functions": metric(1, 1),
            },
        },
        {
            "filename": str(source.parent.parent / "tests" / "helper.rs"),
            "segments": [[1, 1, 0, True, True, False], [2, 1, 0, False, False, False]],
            "summary": {
                "lines": metric(1, 0),
                "regions": metric(1, 0),
                "functions": metric(1, 0),
            },
        },
    ]
    path = tmp_path / name
    path.write_text(
        json.dumps({"type": "llvm.coverage.json.export", "data": [{"files": files}]}),
        encoding="utf-8",
    )
    return path


def test_runs_that_execute_the_same_lines_agree(tmp_path: Path, capsys) -> None:
    source = _source(tmp_path)
    reports = [_report(tmp_path, f"run-{i}.json", source, 1) for i in (1, 2)]

    assert compare.compare("demo", reports, _floors(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "run-1.json: lines 6/6  regions 2/2  functions 1/1" in out
    assert "All 2 runs executed the same lines and regions." in out


def test_a_line_executed_in_only_some_runs_is_named_with_its_text(tmp_path: Path, capsys) -> None:
    source = _source(tmp_path)
    reports = [
        _report(tmp_path, "run-1.json", source, 1),
        _report(tmp_path, "run-2.json", source, 0),
        _report(tmp_path, "run-3.json", source, 2),
    ]

    assert compare.compare("demo", reports, _floors(tmp_path)) == 1
    out = capsys.readouterr().out
    assert "2 lines differ across 3 runs:" in out
    assert "race.rs:3 unexecuted in 1 of 3 (run-2.json) | lost_the_race();" in out
    assert "race.rs:4 unexecuted in 1 of 3 (run-2.json) | }" in out
    assert "race.rs: covered regions per run [2, 1, 2]" in out
    assert "helper.rs" not in out


@pytest.mark.parametrize("summary_only", [True, False])
def test_unusable_reports_are_errors(tmp_path: Path, summary_only: bool) -> None:
    source = _source(tmp_path)
    report = _report(tmp_path, "run-1.json", source, 1)
    if summary_only:
        data = json.loads(report.read_text(encoding="utf-8"))
        for file in data["data"][0]["files"]:
            del file["segments"]
        report.write_text(json.dumps(data), encoding="utf-8")
    else:
        report.write_text("{}", encoding="utf-8")

    assert compare.compare("demo", [report], _floors(tmp_path)) == 2
