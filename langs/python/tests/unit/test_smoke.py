"""Smoke tests — verify the package imports cleanly and exposes expected metadata."""

import vmx


def test_vmx_has_version() -> None:
    assert isinstance(vmx.__version__, str)
    assert len(vmx.__version__) > 0


def test_vmx_has_min_spec_version() -> None:
    assert isinstance(vmx.__min_spec_version__, str)
    assert len(vmx.__min_spec_version__) > 0


def test_message_protocol_importable() -> None:
    from vmx.messages.protocols import Message, TypedMessage

    assert Message is not None
    assert TypedMessage is not None


def test_message_hub_protocol_importable() -> None:
    from vmx.services.message_hub import MessageHub

    assert MessageHub is not None
