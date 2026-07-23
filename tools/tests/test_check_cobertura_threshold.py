"""Tests for the C# Cobertura coverage floor."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "check-cobertura-threshold.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_cobertura_threshold", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_combines_cobertura_totals_and_accepts_floor(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "one.xml").write_text(
        '<coverage lines-covered="40" lines-valid="100" '
        'branches-covered="30" branches-valid="50"/>',
        encoding="utf-8",
    )
    (tmp_path / "two.xml").write_text(
        '<coverage lines-covered="60" lines-valid="100" '
        'branches-covered="20" branches-valid="50"/>',
        encoding="utf-8",
    )

    result = module.check_coverage(list(tmp_path.glob("*.xml")), 49.0, 49.0)

    assert result == (50.0, 50.0)


def test_rejects_coverage_below_floor(tmp_path: Path) -> None:
    module = _load_module()
    report = tmp_path / "coverage.xml"
    report.write_text(
        '<coverage lines-covered="48" lines-valid="100" '
        'branches-covered="59" branches-valid="100"/>',
        encoding="utf-8",
    )

    try:
        module.check_coverage([report], 49.0, 59.0)
    except ValueError as error:
        assert "line coverage 48.00% is below 49.00%" in str(error)
    else:
        raise AssertionError("coverage below the line floor must fail")
