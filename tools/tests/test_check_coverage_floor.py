"""Unit tests for tools/check-coverage-floor.py."""

import json
from pathlib import Path

import check_coverage_floor as floor
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _file(name: str, lines: tuple[int, int], regions: tuple[int, int], functions: tuple[int, int]):
    def metric(count: int, covered: int) -> dict[str, float]:
        return {"count": count, "covered": covered, "percent": 100.0 * covered / count}

    return {
        "filename": name,
        "summary": {
            "lines": metric(*lines),
            "regions": metric(*regions),
            "functions": metric(*functions),
        },
    }


def _report(tmp_path: Path, files: list[dict[str, object]]) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            {"type": "llvm.coverage.json.export", "version": "3.0.1", "data": [{"files": files}]}
        ),
        encoding="utf-8",
    )
    return path


def _floors(tmp_path: Path, **values: object) -> Path:
    path = tmp_path / "floors.json"
    entry = {
        "include": "/src/",
        "exclude": "/tests/",
        "lines": 80.0,
        "regions": 80.0,
        "functions": 80.0,
    }
    entry.update(values)
    path.write_text(json.dumps({"demo": entry}), encoding="utf-8")
    return path


BASELINE = [
    _file("/repo/src/a.rs", (100, 90), (100, 90), (10, 9)),
    _file("/repo/src/b.rs", (100, 80), (100, 80), (10, 8)),
    _file("/repo/tests/helper.rs", (100, 0), (100, 0), (10, 0)),
]


def test_meets_floor_over_library_sources_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = floor.check("demo", _report(tmp_path, BASELINE), _floors(tmp_path, lines=85.0))

    assert rc == 0
    assert "over 2 library source files" in capsys.readouterr().out


def test_a_coverage_decrease_fails_and_names_the_least_covered_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Deleting a covered test drops b.rs from 80 to 50 covered lines.
    decreased = [BASELINE[0], _file("/repo/src/b.rs", (100, 50), (100, 50), (10, 8)), BASELINE[2]]

    rc = floor.check("demo", _report(tmp_path, decreased), _floors(tmp_path, lines=85.0))

    assert rc == 1
    err = capsys.readouterr().err
    assert "lines, regions coverage fell below its floor" in err
    assert err.splitlines()[1] == "Files with the most uncovered lines:"
    assert "b.rs: 50 uncovered lines" in err.splitlines()[2]


def test_a_decrease_names_the_files_that_lost_coverage_since_the_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    decreased = [BASELINE[0], _file("/repo/src/b.rs", (100, 50), (100, 50), (10, 8)), BASELINE[2]]
    floors = _floors(tmp_path, lines=85.0, baseline={"uncovered_lines": {"a.rs": 10, "b.rs": 20}})

    rc = floor.check("demo", _report(tmp_path, decreased), floors)

    assert rc == 1
    err = capsys.readouterr().err.splitlines()
    assert err[1] == "Files that lost coverage since the baseline:"
    assert err[2:] == ["  b.rs: 50 uncovered lines, 30 more than the baseline's 20"]


def test_generated_or_test_only_changes_do_not_move_the_measured_figure(tmp_path: Path) -> None:
    generated = [*BASELINE, _file("/repo/tests/generated_fixture.rs", (500, 0), (500, 0), (5, 0))]

    assert floor.check("demo", _report(tmp_path, generated), _floors(tmp_path, lines=85.0)) == 0


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{",
        json.dumps({"type": "something-else"}),
        json.dumps({"type": "llvm.coverage.json.export", "data": []}),
    ],
    ids=["empty", "truncated", "wrong-type", "no-data"],
)
def test_unusable_reports_are_errors_not_passes(tmp_path: Path, content: str) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(content, encoding="utf-8")

    assert floor.check("demo", report, _floors(tmp_path)) == 2


def test_a_report_with_no_library_sources_is_an_error(tmp_path: Path) -> None:
    report = _report(tmp_path, [_file("/repo/tests/only.rs", (1, 1), (1, 1), (1, 1))])

    assert floor.check("demo", report, _floors(tmp_path)) == 2


def test_an_unknown_flavor_is_an_error(tmp_path: Path) -> None:
    assert floor.check("missing", _report(tmp_path, BASELINE), _floors(tmp_path)) == 2


def test_provenance_records_commit_toolchain_and_figures(tmp_path: Path) -> None:
    provenance = tmp_path / "provenance.json"

    floor.check(
        "demo",
        _report(tmp_path, BASELINE),
        _floors(tmp_path),
        provenance=provenance,
        commit="a" * 40,
        toolchain="rustc 1.94.0",
    )

    recorded = json.loads(provenance.read_text(encoding="utf-8"))
    assert recorded["commit"] == "a" * 40
    assert recorded["toolchain"] == "rustc 1.94.0"
    assert recorded["metrics"]["lines"]["covered"] == 170
    assert recorded["floors"]["lines"] == 80.0


def test_recorded_floors_cover_rust_and_swift_library_sources() -> None:
    floors = json.loads((REPO_ROOT / "tools/coverage-floors.json").read_text(encoding="utf-8"))

    assert set(floors) == {"rust", "swift"}
    for entry in floors.values():
        assert all(0 < float(entry[metric]) <= 100 for metric in floor.METRICS)
        assert entry["include"] and entry["exclude"]
