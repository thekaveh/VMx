"""Unit tests for property_value_changed_messages_for helper."""

from __future__ import annotations

from vmx.messages import property_value_changed_messages_for
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHub


class _TestSource:
    """Minimal source that emits PropertyChangedMessage via a hub."""

    def __init__(self, hub: MessageHub) -> None:  # type: ignore[type-arg]
        self._hub = hub
        self._count: int = 0
        self._label: str = ""

    @property
    def count(self) -> int:
        return self._count

    @count.setter
    def count(self, value: int) -> None:
        if value != self._count:
            self._count = value
            self._hub.send(PropertyChangedMessage.create(self, "test-source", "count"))

    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, value: str) -> None:
        if value != self._label:
            self._label = value
            self._hub.send(PropertyChangedMessage.create(self, "test-source", "label"))


class TestPropertyValueChangedMessagesFor:
    def test_returns_observable_of_property_values(self) -> None:
        hub: MessageHub[PropertyChangedMessage[_TestSource]] = MessageHub()
        source = _TestSource(hub)
        values: list[int] = []

        sub = property_value_changed_messages_for(hub, source, "count").subscribe(values.append)

        source.count = 1
        source.count = 2
        source.count = 3

        assert values == [1, 2, 3]
        sub.dispose()

    def test_filters_by_sender_instance(self) -> None:
        hub: MessageHub[PropertyChangedMessage[_TestSource]] = MessageHub()
        source1 = _TestSource(hub)
        source2 = _TestSource(hub)
        values1: list[int] = []
        values2: list[int] = []

        sub1 = property_value_changed_messages_for(hub, source1, "count").subscribe(values1.append)
        sub2 = property_value_changed_messages_for(hub, source2, "count").subscribe(values2.append)

        source1.count = 10
        source2.count = 20

        assert values1 == [10]
        assert values2 == [20]
        sub1.dispose()
        sub2.dispose()

    def test_filters_by_property_name(self) -> None:
        hub: MessageHub[PropertyChangedMessage[_TestSource]] = MessageHub()
        source = _TestSource(hub)
        counts: list[int] = []
        labels: list[str] = []

        sub_count = property_value_changed_messages_for(hub, source, "count").subscribe(
            counts.append
        )
        sub_label = property_value_changed_messages_for(hub, source, "label").subscribe(
            labels.append
        )

        source.count = 42
        source.label = "hello"

        assert counts == [42]
        assert labels == ["hello"]
        sub_count.dispose()
        sub_label.dispose()

    def test_snapshot_value_at_message_time(self) -> None:
        hub: MessageHub[PropertyChangedMessage[_TestSource]] = MessageHub()
        source = _TestSource(hub)
        snapshots: list[int] = []

        sub = property_value_changed_messages_for(hub, source, "count").subscribe(snapshots.append)

        source.count = 5
        source.count = 10

        assert snapshots == [5, 10]
        sub.dispose()
