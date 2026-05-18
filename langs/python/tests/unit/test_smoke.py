"""Smoke tests — verify the package imports cleanly and exposes expected metadata."""

import vmx


def test_vmx_has_version() -> None:
    assert isinstance(vmx.__version__, str)
    assert len(vmx.__version__) > 0


def test_vmx_has_min_spec_version() -> None:
    assert isinstance(vmx.__min_spec_version__, str)
    assert len(vmx.__min_spec_version__) > 0


def test_message_protocol_importable_via_subpackage() -> None:
    """Verifies the vmx.messages re-export chain (not just the implementation module)."""
    from vmx.messages import Message, TypedMessage

    assert Message is not None
    assert TypedMessage is not None


def test_message_hub_protocol_importable_via_subpackage() -> None:
    """Verifies the vmx.services re-export chain."""
    from vmx.services import MessageHub

    assert MessageHub is not None
