"""Unit tests for vmx.messages concrete message types."""

from __future__ import annotations

import pytest

from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage

# ---------------------------------------------------------------------------
# PropertyChangedMessage
# ---------------------------------------------------------------------------


class TestPropertyChangedMessageCreate:
    def test_create_returns_correct_sender(self) -> None:
        sender = object()
        msg = PropertyChangedMessage.create(sender, "my_vm", "Title")
        assert msg.sender is sender

    def test_create_returns_correct_sender_name(self) -> None:
        sender = object()
        msg = PropertyChangedMessage.create(sender, "my_vm", "Title")
        assert msg.sender_name == "my_vm"

    def test_create_returns_correct_property_name(self) -> None:
        sender = object()
        msg = PropertyChangedMessage.create(sender, "my_vm", "Title")
        assert msg.property_name == "Title"

    def test_sender_object_returns_sender(self) -> None:
        sender = object()
        msg = PropertyChangedMessage.create(sender, "my_vm", "Count")
        assert msg.sender_object is sender

    def test_equal_valued_messages_are_equal(self) -> None:
        sender = object()
        msg_a = PropertyChangedMessage.create(sender, "vm", "Prop")
        msg_b = PropertyChangedMessage.create(sender, "vm", "Prop")
        assert msg_a == msg_b

    def test_different_property_name_not_equal(self) -> None:
        sender = object()
        msg_a = PropertyChangedMessage.create(sender, "vm", "PropA")
        msg_b = PropertyChangedMessage.create(sender, "vm", "PropB")
        assert msg_a != msg_b

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        msg = PropertyChangedMessage.create(object(), "vm", "Prop")
        with pytest.raises((AttributeError, TypeError)):
            msg.property_name = "Other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConstructionStatusChangedMessage
# ---------------------------------------------------------------------------


class TestConstructionStatusChangedMessageCreate:
    def test_create_returns_correct_sender(self) -> None:
        sender = object()
        msg = ConstructionStatusChangedMessage.create(
            sender, "my_vm", ConstructionStatus.CONSTRUCTED
        )
        assert msg.sender is sender

    def test_create_returns_correct_sender_name(self) -> None:
        sender = object()
        msg = ConstructionStatusChangedMessage.create(
            sender, "my_vm", ConstructionStatus.CONSTRUCTING
        )
        assert msg.sender_name == "my_vm"

    def test_create_returns_correct_status(self) -> None:
        sender = object()
        msg = ConstructionStatusChangedMessage.create(sender, "my_vm", ConstructionStatus.DISPOSED)
        assert msg.status is ConstructionStatus.DISPOSED

    def test_sender_object_returns_sender(self) -> None:
        sender = object()
        msg = ConstructionStatusChangedMessage.create(
            sender, "my_vm", ConstructionStatus.DESTRUCTED
        )
        assert msg.sender_object is sender

    def test_equal_valued_messages_are_equal(self) -> None:
        sender = object()
        msg_a = ConstructionStatusChangedMessage.create(
            sender, "vm", ConstructionStatus.CONSTRUCTED
        )
        msg_b = ConstructionStatusChangedMessage.create(
            sender, "vm", ConstructionStatus.CONSTRUCTED
        )
        assert msg_a == msg_b

    def test_different_status_not_equal(self) -> None:
        sender = object()
        msg_a = ConstructionStatusChangedMessage.create(
            sender, "vm", ConstructionStatus.CONSTRUCTING
        )
        msg_b = ConstructionStatusChangedMessage.create(
            sender, "vm", ConstructionStatus.CONSTRUCTED
        )
        assert msg_a != msg_b

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        msg = ConstructionStatusChangedMessage.create(
            object(), "vm", ConstructionStatus.CONSTRUCTED
        )
        with pytest.raises((AttributeError, TypeError)):
            msg.status = ConstructionStatus.DISPOSED  # type: ignore[misc]
