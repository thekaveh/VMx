"""Conformance tests: LOC-001..003 — localization hooks.

Per spec/17-localization.md and ADR-0019.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from vmx.localization import ILocalizer, NullLocalizer


class _FakeLocalizer:
    def localize(self, key: str, args: Iterable[object] | None = None) -> str:
        if key == "greeting":
            return "hello"
        return key


# ---------------------------------------------------------------------------
# LOC-001
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LOC-001")
def test_LOC_001_localize_returns_string() -> None:
    loc = _FakeLocalizer()
    assert loc.localize("greeting") == "hello"


# ---------------------------------------------------------------------------
# LOC-002
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LOC-002")
def test_LOC_002_nulllocalizer_returns_key_verbatim() -> None:
    loc = NullLocalizer()
    assert loc.localize("some-key") == "some-key"
    assert loc.localize("some-key", ["arg1", "arg2"]) == "some-key"


# ---------------------------------------------------------------------------
# LOC-003
# ---------------------------------------------------------------------------


@pytest.mark.conformance("LOC-003")
def test_LOC_003_custom_localizer_can_substitute() -> None:
    class XLocalizer:
        def localize(self, key: str, args: Iterable[object] | None = None) -> str:
            return f"X:{key}"

    loc: ILocalizer = XLocalizer()
    assert loc.localize("foo") == "X:foo"
