"""Contract tests for Python archive safety and exact inventories."""

import check_python_package as cpp
import pytest


@pytest.mark.parametrize("name", ["../secret", "/absolute", "vmx\\escape.py"])
def test_archive_names_reject_unsafe_paths(name: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        cpp._safe_unique([name])


def test_archive_names_reject_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        cpp._safe_unique(["vmx/__init__.py", "vmx/__init__.py"])


@pytest.mark.parametrize(
    ("actual", "message"),
    [
        ({"vmx/__init__.py"}, "missing"),
        ({"vmx/__init__.py", "vmx/extra.py", "vmx/py.typed"}, "unexpected"),
    ],
)
def test_exact_inventory_rejects_missing_and_unexpected(actual: set[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        cpp._exact(actual, {"vmx/__init__.py", "vmx/py.typed"}, "wheel")
