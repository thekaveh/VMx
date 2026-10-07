"""Executable form of the connection-state recipe (#575).

The blocks between the docs-snippet markers are shown verbatim, dedented, in
docs/content/primitives/state-reactive-helpers.md; `make docs-check` keeps them
equal. No conformance ID: this is a recipe over ComponentVMOf, not a primitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vmx import NULL_DISPATCHER, ComponentVMOf, Message, MessageHub, PropertyChangedMessage


# docs-snippet:start connection-state
class Feed(Enum):
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class FeedState:
    status: Feed
    reason: str | None = None


def advance(current: FeedState, reported: FeedState) -> FeedState:
    """Disconnected is terminal: no later report moves the feed out of it."""
    return current if current.status is Feed.DISCONNECTED else reported
    # docs-snippet:end connection-state


def _feed(hub: MessageHub[Message]) -> ComponentVMOf[FeedState]:
    feed: ComponentVMOf[FeedState] = (
        ComponentVMOf.builder()
        .name("feed")
        .model(FeedState(Feed.CONNECTED))
        .services(hub, NULL_DISPATCHER)
        .build()
    )
    feed.construct()
    return feed


def _model_changes(hub: MessageHub[Message], feed: object) -> list[object]:
    changes: list[object] = []

    def record(message: Message) -> None:
        if (
            isinstance(message, PropertyChangedMessage)
            and message.sender is feed
            and message.property_name == "model"
        ):
            changes.append(message)

    hub.messages.subscribe(record)
    return changes


def test_repeated_retries_with_the_same_reason_publish_one_change() -> None:
    hub: MessageHub[Message] = MessageHub()
    feed = _feed(hub)
    changes = _model_changes(hub, feed)

    # docs-snippet:start connection-state-retries
    def report(state: FeedState) -> None:
        feed.model = advance(feed.model, state)

    for _attempt in range(5):
        report(FeedState(Feed.RECONNECTING, "server restarting"))
    # Equal frozen dataclasses compare equal, so only the first retry publishes.
    # docs-snippet:end connection-state-retries

    assert len(changes) == 1
    assert feed.model == FeedState(Feed.RECONNECTING, "server restarting")


def test_a_changed_reason_publishes_again() -> None:
    hub: MessageHub[Message] = MessageHub()
    feed = _feed(hub)
    changes = _model_changes(hub, feed)

    feed.model = advance(feed.model, FeedState(Feed.RECONNECTING, "server restarting"))
    feed.model = advance(feed.model, FeedState(Feed.RECONNECTING, "server restarting"))
    feed.model = advance(feed.model, FeedState(Feed.RECONNECTING, "rate limited"))

    assert len(changes) == 2
    assert feed.model.reason == "rate limited"


def test_disconnected_is_terminal() -> None:
    hub: MessageHub[Message] = MessageHub()
    feed = _feed(hub)
    changes = _model_changes(hub, feed)

    for reported in (
        FeedState(Feed.RECONNECTING, "server restarting"),
        FeedState(Feed.CONNECTED),
        FeedState(Feed.DISCONNECTED, "closed by server"),
    ):
        feed.model = advance(feed.model, reported)
    assert len(changes) == 3

    feed.model = advance(feed.model, FeedState(Feed.RECONNECTING, "retrying"))
    feed.model = advance(feed.model, FeedState(Feed.CONNECTED))

    assert len(changes) == 3
    assert feed.model == FeedState(Feed.DISCONNECTED, "closed by server")
