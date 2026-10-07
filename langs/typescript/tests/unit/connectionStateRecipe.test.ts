/**
 * Executable form of the connection-state recipe (#575) in
 * docs/content/primitives/state-reactive-helpers.md. The docs-snippet regions
 * are shown there verbatim, dedented, and `make docs-check` keeps them equal.
 * No conformance ID: this is a recipe over ComponentVMOf, not a primitive.
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVMOf,
  type IMessage,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "../../src/index.js";

// docs-snippet:start connection-state
type FeedState =
  | { readonly status: "connected" }
  | { readonly status: "reconnecting"; readonly reason: string }
  | { readonly status: "disconnected"; readonly reason?: string };

const reasonOf = (state: FeedState) => ("reason" in state ? state.reason : undefined);

function advance(current: FeedState, reported: FeedState): FeedState {
  // Disconnected is terminal: no later report moves the feed out of it.
  if (current.status === "disconnected") return current;
  // ComponentVMOf compares models with ===, so a fresh but equal object would
  // publish again. Keep the current instance when nothing changed.
  const unchanged = reported.status === current.status && reasonOf(reported) === reasonOf(current);
  return unchanged ? current : reported;
}
// docs-snippet:end connection-state

function feedWithChanges() {
  const hub = new MessageHub();
  const feed = ComponentVMOf.builder<FeedState>()
    .name("feed")
    .model({ status: "connected" })
    .services(hub, RxDispatcher.immediate())
    .build();
  feed.construct();
  const changes: IMessage[] = [];
  hub.messages.subscribe(message => {
    if (
      message instanceof PropertyChangedMessage &&
      message.sender === feed &&
      message.propertyName === "model"
    ) {
      changes.push(message);
    }
  });
  return { feed, changes };
}

describe("connection-state recipe", () => {
  it("publishes one change for repeated retries with the same reason", () => {
    const { feed, changes } = feedWithChanges();

    const report = (state: FeedState) => {
      feed.model = advance(feed.model, state);
    };

    for (let attempt = 0; attempt < 5; attempt += 1) {
      report({ status: "reconnecting", reason: "server restarting" });
    }
    // Each retry builds a new object; advance keeps the first, so one publishes.

    expect(changes).toHaveLength(1);
    expect(feed.model).toEqual({ status: "reconnecting", reason: "server restarting" });
  });

  it("publishes again when the reason changes", () => {
    const { feed, changes } = feedWithChanges();

    feed.model = advance(feed.model, { status: "reconnecting", reason: "server restarting" });
    feed.model = advance(feed.model, { status: "reconnecting", reason: "server restarting" });
    feed.model = advance(feed.model, { status: "reconnecting", reason: "rate limited" });

    expect(changes).toHaveLength(2);
    expect(reasonOf(feed.model)).toBe("rate limited");
  });

  it("treats disconnected as terminal", () => {
    const { feed, changes } = feedWithChanges();
    const reports: FeedState[] = [
      { status: "reconnecting", reason: "server restarting" },
      { status: "connected" },
      { status: "disconnected", reason: "closed by server" },
    ];
    for (const reported of reports) feed.model = advance(feed.model, reported);
    expect(changes).toHaveLength(3);

    feed.model = advance(feed.model, { status: "reconnecting", reason: "retrying" });
    feed.model = advance(feed.model, { status: "connected" });

    expect(changes).toHaveLength(3);
    expect(feed.model).toEqual({ status: "disconnected", reason: "closed by server" });
  });
});
