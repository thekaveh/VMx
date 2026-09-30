"""Top-level pytest configuration for the vmx test suite."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Record each conformance marker as a test property so the JUnit report
    # names the catalog IDs a case executed (tools/check-conformance-execution.py).
    for item in items:
        for marker in item.iter_markers("conformance"):
            item.user_properties.append(("conformance", marker.args[0]))
