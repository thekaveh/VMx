"""Unit tests for tools/check-swift-subscript-chains.py (#1462)."""

from __future__ import annotations

from pathlib import Path

import check_swift_subscript_chains as cssc

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_reports_each_chained_subscript_with_its_location(tmp_path, capsys) -> None:
    _write(tmp_path / "Package.swift", "let ok = 1\n")
    _write(tmp_path / "langs/swift/Sources/A.swift", "let a = 1\nlet x = d[k]?.owner\n")
    _write(tmp_path / "examples/swift/app/Tests/T.swift", "// d[k]?.x in a comment\n")
    _write(tmp_path / "starters/swift-package/Sources/S.swift", "let s = 1\n")

    assert cssc.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "langs/swift/Sources/A.swift:2: let x = d[k]?.owner" in captured.out
    assert "examples/swift/app/Tests/T.swift:1: // d[k]?.x in a comment" in captured.out
    assert "guard let" in captured.err


def test_checks_the_root_manifest_and_skips_build_directories(tmp_path, capsys) -> None:
    _write(tmp_path / "Package.swift", "let v = m[0]?.name\n")
    _write(tmp_path / "langs/swift/.build/checkouts/Dep.swift", "let v = m[0]?.name\n")

    assert cssc.findings(tmp_path) == ["Package.swift:1: let v = m[0]?.name"]


def test_binding_forms_pass(tmp_path, capsys) -> None:
    _write(
        tmp_path / "langs/swift/Sources/A.swift",
        "guard let e = d[k] else { return nil }\nlet y = d[k] ?? z\nlet w = a?.b\n",
    )
    assert cssc.main(["--root", str(tmp_path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_the_repository_has_no_chained_subscript() -> None:
    assert cssc.findings(REPO_ROOT) == []


def test_the_swift_workflow_runs_the_check() -> None:
    workflow = (REPO_ROOT / ".github/workflows/swift.yml").read_text(encoding="utf-8")
    assert "run: python3 tools/check-swift-subscript-chains.py\n" in workflow
    assert '- "tools/check-swift-subscript-chains.py"' in workflow
