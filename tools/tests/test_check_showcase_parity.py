"""Unit tests for tools/check-showcase-parity.py."""

import check_showcase_parity as csp


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
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr("sys.argv", ["check-showcase-parity.py", "--root", str(repo_root)])
    assert csp.main() == 0
    assert "[OK]" in capsys.readouterr().out
