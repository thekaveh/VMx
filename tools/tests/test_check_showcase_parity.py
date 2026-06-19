"""Unit tests for tools/check-showcase-parity.py."""

from pathlib import Path

import check_showcase_parity as csp


def _build_valid_tree(root: Path) -> None:
    """Materialise a synthetic tree that satisfies parity for all three flavors."""
    cs = root / "examples/csharp/avalonia/NotesShowcase.Tests"
    py = root / "examples/python/textual/notes_showcase/tests"
    ts = root / "examples/typescript/react/notes-showcase/tests"
    for d in (cs, py, ts):
        d.mkdir(parents=True, exist_ok=True)
    for slug in csp.EXPECTED:
        (cs / f"{csp._pascal(slug)}Tests.cs").write_text("// stub\n")
        (py / f"test_{slug}.py").write_text("# stub\n")
        (ts / f"{csp._camel(slug)}.test.ts").write_text("// stub\n")


def test_expected_keys_pascal_case_for_csharp() -> None:
    keys = csp._expected_keys("csharp", "workspace_vm")
    # Keys are lowercase per the script's case-insensitive matching.
    assert "workspacevmtests" in keys


def test_expected_keys_underscore_for_python() -> None:
    keys = csp._expected_keys("python", "workspace_vm")
    assert "test_workspace_vm" in keys


def test_expected_keys_camel_case_for_typescript() -> None:
    keys = csp._expected_keys("typescript", "workspace_vm")
    assert "workspacevm.test" in keys


def test_expected_slug_list_matches_documented_set() -> None:
    """Pin the EXPECTED list so accidental removals are caught."""
    assert "workspace_vm" in csp.EXPECTED
    assert "in_memory_repository" in csp.EXPECTED
    assert "theme_vm" in csp.EXPECTED
    assert len(csp.EXPECTED) == 11  # 10 VMs + 1 repository


def test_main_exits_zero_on_real_repo(monkeypatch, capsys) -> None:
    """main() against the actual repo should pass (sanity smoke)."""
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(repo_root)])
    assert csp.main() == 0
    assert "[OK]" in capsys.readouterr().out


def test_main_returns_one_when_a_slug_file_is_missing(tmp_path, monkeypatch, capsys) -> None:
    """A complete tree passes; deleting one slug's file makes parity fail (rc=1)."""
    _build_valid_tree(tmp_path)
    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(tmp_path)])
    assert csp.main() == 0  # sanity: synthetic tree is complete

    missing = tmp_path / "examples/python/textual/notes_showcase/tests/test_theme_vm.py"
    missing.unlink()
    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(tmp_path)])
    assert csp.main() == 1
    assert "missing test for 'theme_vm'" in capsys.readouterr().err


def test_main_returns_one_when_test_roots_absent(tmp_path, monkeypatch, capsys) -> None:
    """An empty repo root (no flavor test trees) reports each missing root and fails."""
    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(tmp_path)])
    assert csp.main() == 1
    assert "test root not found" in capsys.readouterr().err
