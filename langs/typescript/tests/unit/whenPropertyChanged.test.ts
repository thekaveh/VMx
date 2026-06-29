/**
 * VMX-017 regression — `whenPropertyChanged` typed hub helper that replaces the
 * hand-wired `instanceof PropertyChangedMessage && sender === x && propertyName === "P"`
 * filter repeated across cross-VM bindings.
 */
import { describe, expect, it } from "vitest";

import {
  MessageHub,
  PropertyChangedMessage,
  whenPropertyChanged,
} from "../../src/index.js";

describe("VMX-017: whenPropertyChanged", () => {
  it("filters by sender identity and property name", () => {
    const hub = new MessageHub();
    const a = { name: "a" };
    const b = { name: "b" };

    const received: string[] = [];
    const sub = whenPropertyChanged(hub, a, "foo").subscribe((m) =>
      received.push(m.propertyName),
    );

    hub.send(PropertyChangedMessage.create(a, "A", "foo")); // match
    hub.send(PropertyChangedMessage.create(a, "A", "bar")); // wrong property
    hub.send(PropertyChangedMessage.create(b, "B", "foo")); // wrong sender

    sub.unsubscribe();
    expect(received).toEqual(["foo"]);
  });

  it("emits the matching message (not the value)", () => {
    const hub = new MessageHub();
    const sender = {};

    let captured: PropertyChangedMessage<unknown> | null = null;
    const sub = whenPropertyChanged(hub, sender, "p").subscribe((m) => {
      captured = m;
    });

    hub.send(PropertyChangedMessage.create(sender, "S", "p"));
    sub.unsubscribe();

    expect(captured).not.toBeNull();
    expect(captured!.sender).toBe(sender);
    expect(captured!.propertyName).toBe("p");
  });
});
