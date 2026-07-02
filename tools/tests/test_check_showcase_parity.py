"""Unit tests for tools/check-showcase-parity.py."""

from pathlib import Path

import check_showcase_parity as csp


def _build_valid_tree(root: Path) -> None:
    """Materialise a synthetic tree that satisfies parity for all four flavors."""
    cs = root / "examples/csharp/avalonia/NotesShowcase.Tests"
    py = root / "examples/python/textual/notes_showcase/tests"
    ts = root / "examples/typescript/react/notes-showcase/tests"
    sw = root / "examples/swift/notes-showcase/Tests"
    for d in (cs, py, ts, sw):
        d.mkdir(parents=True, exist_ok=True)
    for slug in csp.EXPECTED:
        (cs / f"{csp._pascal(slug)}Tests.cs").write_text("// stub\n")
        (py / f"test_{slug}.py").write_text("# stub\n")
        (ts / f"{csp._camel(slug)}.test.ts").write_text("// stub\n")
        (sw / f"{csp._pascal(slug)}Tests.swift").write_text("// stub\n")
    (cs / "ThemeVMTests.cs").write_text(
        "\n".join(f"[Fact]\npublic void THEME_{i:03d}_Scenario() {{ }}" for i in range(1, 6)),
        encoding="utf-8",
    )
    (py / "test_theme_vm.py").write_text(
        "\n".join(
            f'@pytest.mark.conformance("THEME-{i:03d}")\ndef test_THEME_{i:03d}_scenario(): pass'
            for i in range(1, 6)
        ),
        encoding="utf-8",
    )
    (ts / "themeVm.test.ts").write_text(
        "\n".join(f'describe("THEME-{i:03d} scenario", () => {{}});' for i in range(1, 6)),
        encoding="utf-8",
    )
    (sw / "ThemeVMTests.swift").write_text(
        "\n".join(f"func testTHEME{i:03d}_Scenario() {{ }}" for i in range(1, 6)),
        encoding="utf-8",
    )


def test_expected_keys_pascal_case_for_csharp() -> None:
    keys = csp._expected_keys("csharp", "workspace_vm")
    # Keys are lowercase per the script's case-insensitive matching.
    assert "workspacevmtests" in keys


def test_expected_keys_pascal_case_for_swift() -> None:
    keys = csp._expected_keys("swift", "workspace_vm")
    # Swift uses the same `<Pascal>Tests` stem as C# (`…Tests.swift`).
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


def test_main_returns_one_when_theme_marker_is_missing(tmp_path, monkeypatch, capsys) -> None:
    """The THEME scenario IDs are checked, not just the ThemeVM test filename."""
    _build_valid_tree(tmp_path)
    theme_test = tmp_path / "examples" / "swift" / "notes-showcase" / "Tests" / "ThemeVMTests.swift"
    theme_test.write_text("THEME-001\nTHEME-002\nTHEME-003\nTHEME-004\n", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(tmp_path)])
    assert csp.main() == 1
    assert "THEME-005" in capsys.readouterr().err


def test_main_returns_one_when_theme_id_is_comment_only(tmp_path, monkeypatch, capsys) -> None:
    """THEME IDs in prose/comments must not satisfy executable test coverage."""
    _build_valid_tree(tmp_path)
    theme_test = (
        tmp_path
        / "examples"
        / "typescript"
        / "react"
        / "notes-showcase"
        / "tests"
        / "themeVm.test.ts"
    )
    theme_test.write_text(
        "// THEME-001 THEME-002 THEME-003 THEME-004 THEME-005\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(tmp_path)])
    assert csp.main() == 1
    assert "executable scenario marker" in capsys.readouterr().err
