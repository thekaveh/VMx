/**
 * VMX-017 regression — `whenPropertyChanged` typed hub helper that replaces the
 * hand-wired `instanceof PropertyChangedMessage && sender === x && propertyName === "P"`
 * filter repeated across cross-VM bindings.
 */
import { Observable, Subject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  type IMessage,
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

  it("matches any of several names, in hub order (ADR-0160)", () => {
    const hub = new MessageHub();
    const a = { name: "a" };
    const b = { name: "b" };

    const received: string[] = [];
    const sub = whenPropertyChanged(hub, a, ["foo", "bar"]).subscribe((m) =>
      received.push(m.propertyName),
    );

    hub.send(PropertyChangedMessage.create(a, "A", "bar")); // match
    hub.send(PropertyChangedMessage.create(a, "A", "baz")); // name not listed
    hub.send(PropertyChangedMessage.create(b, "B", "foo")); // wrong sender
    hub.send(PropertyChangedMessage.create(a, "A", "foo")); // match
    hub.send(PropertyChangedMessage.create(a, "A", "Foo")); // exact match only
    hub.send(PropertyChangedMessage.create(a, "A", "bar")); // match

    sub.unsubscribe();
    expect(received).toEqual(["bar", "foo", "bar"]);
  });

  it("copies the names when it is called", () => {
    const hub = new MessageHub();
    const sender = {};
    const names = ["foo", "bar"];

    const received: string[] = [];
    const sub = whenPropertyChanged(hub, sender, names).subscribe((m) =>
      received.push(m.propertyName),
    );
    names[1] = "baz";

    hub.send(PropertyChangedMessage.create(sender, "S", "bar"));
    hub.send(PropertyChangedMessage.create(sender, "S", "baz"));

    sub.unsubscribe();
    expect(received).toEqual(["bar"]);
  });

  it("emits a message once when its name is listed twice", () => {
    const hub = new MessageHub();
    const sender = {};

    let hits = 0;
    const sub = whenPropertyChanged(hub, sender, ["foo", "foo", "bar"]).subscribe(() => {
      hits += 1;
    });

    hub.send(PropertyChangedMessage.create(sender, "S", "foo"));

    sub.unsubscribe();
    expect(hits).toBe(1);
  });

  it("makes one hub subscription for several names", () => {
    const subject = new Subject<IMessage>();
    let subscriptions = 0;
    const hub = {
      messages: new Observable<IMessage>((observer) => {
        subscriptions += 1;
        return subject.subscribe(observer);
      }),
    };
    const sender = {};

    const received: string[] = [];
    const sub = whenPropertyChanged(hub, sender, ["foo", "bar"]).subscribe((m) =>
      received.push(m.propertyName),
    );
    expect(subscriptions).toBe(1);

    subject.next(PropertyChangedMessage.create(sender, "S", "foo"));
    sub.unsubscribe();
    subject.next(PropertyChangedMessage.create(sender, "S", "bar"));

    expect(received).toEqual(["foo"]);
    expect(subject.observed).toBe(false);
  });

  it("rejects an empty name array with RangeError", () => {
    const hub = new MessageHub();

    expect(() => whenPropertyChanged(hub, {}, [])).toThrow(RangeError);
  });
});
