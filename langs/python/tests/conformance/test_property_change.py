"""Conformance tests: PROP-001..004.

These tests delegate to the ComponentVM unit suite, mirroring the pattern used
in ``test_lifecycle.py`` for inherited assertions. The implementing module
(``vmx.components.component_vm``) is a core part of the package — earlier
scaffolding wrapped these in ``pytest.importorskip`` while modules were being
phased in, but every dependent module now ships in ``vmx`` and the importorskip
would silently mask a real packaging breakage, so the import is unguarded.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# PROP-001 — PropertyChangedMessage emitted only on real changes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-001")
def test_PROP_001_delegated() -> None:
    """PropertyChangedMessage is emitted when a property value changes."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_001_property_changed_emitted_on_change,
    )

    test_PROP_001_property_changed_emitted_on_change()


# ---------------------------------------------------------------------------
# PROP-002 — No message emitted on same-value set
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-002")
def test_PROP_002_delegated() -> None:
    """No PropertyChangedMessage emitted when setting the same value."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_002_no_message_on_same_value,
    )

    test_PROP_002_no_message_on_same_value()


# ---------------------------------------------------------------------------
# PROP-003 — sender identity is correct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-003")
def test_PROP_003_delegated() -> None:
    """PropertyChangedMessage carries the correct sender instance."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_003_sender_identity,
    )

    test_PROP_003_sender_identity()


# ---------------------------------------------------------------------------
# PROP-004 — property name and sender name correctness
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-004")
def test_PROP_004_delegated() -> None:
    """PropertyChangedMessage carries correct property_name and sender_name."""
    from tests.conformance.test_component_vm import (  # type: ignore[import]
        test_PROP_004_property_name_and_sender_name,
    )

    test_PROP_004_property_name_and_sender_name()
