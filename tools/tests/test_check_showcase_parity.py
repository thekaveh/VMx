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
    assert len(csp.EXPECTED) == 10  # 9 VMs + 1 repository
