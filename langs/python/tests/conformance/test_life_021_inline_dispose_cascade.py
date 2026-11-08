"""Conformance test: LIFE-021 — a lifecycle call during the inline dispose cascade.

PLACEHOLDER. spec/02 §7.2 and ADR-0175 define the rule: a ``construct()``,
``destruct()``, or ``reconstruct()`` call that starts during a view-model's
inline dispose cascade raises ``StatusTransitionError`` for ``DISPOSED`` and
publishes nothing, and no status other than ``DISPOSED`` commits once the
cascade has started. The implementation PR replaces this skipped placeholder
with the full ``LIFE-021`` scenarios of spec/12.
"""

from __future__ import annotations

import pytest


@pytest.mark.conformance("LIFE-021")
def test_life_021_placeholder() -> None:
    pytest.skip("LIFE-021 placeholder: replaced by the ADR-0175 implementation")
