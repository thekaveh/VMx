"""FORM-039..040 — FormVM queues updates made during approval publication.

Per spec/20-form-vm.md §5.1, §5.3 and §5.4, and ADR-0174.

PLACEHOLDER: the spec change for ADR-0174 adds these IDs before the Python
implementation lands. The implementation PR replaces each skipped test below
with the behavioral test. ``tools/check-conformance-execution.py`` counts a
skipped ID as not passing, so CI stays red until the placeholders are replaced.
"""

from __future__ import annotations

import pytest

_PLACEHOLDER = "ADR-0174 placeholder: replaced by the Python FormVM implementation"


@pytest.mark.conformance("FORM-039")
def test_form_039_updates_during_publication_replay_after_on_approved() -> None:
    pytest.skip(_PLACEHOLDER)


@pytest.mark.conformance("FORM-040")
def test_form_040_queued_update_prepares_at_call_time_and_replays_in_isolation() -> None:
    pytest.skip(_PLACEHOLDER)
