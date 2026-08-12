import { Subscription } from "rxjs";
import { describe, expect, it } from "vitest";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import {
  ManualDispatcher,
  RecordingMessageHub,
  createTestServices,
} from "../../../src/testing/index.js";

const sender = { name: "subject" };
const changed = (propertyName: string) =>
  PropertyChangedMessage.create(sender, "Subject", propertyName);

describe("RecordingMessageHub", () => {
  it("records delivered messages in reentrant drain order", () => {
    const hub = new RecordingMessageHub();
    const seen: string[] = [];
    const subscription = hub.messages.subscribe((message) => {
      if (!(message instanceof PropertyChangedMessage)) return;
      seen.push(message.propertyName);
      if (message.propertyName === "first") hub.send(changed("second"));
    });

    hub.send(changed("first"));

    expect(seen).toEqual(["first", "second"]);
    expect(hub.records.map((message) => (message as PropertyChangedMessage<object>).propertyName))
      .toEqual(["first", "second"]);
    subscription.unsubscribe();
    hub.dispose();
  });

  it("defers nested batches and exposes immutable copied snapshots", () => {
    const hub = new RecordingMessageHub();
    let duringBatch: readonly unknown[] = [];

    hub.batch(() => {
      hub.send(changed("first"));
      hub.batch(() => hub.send(changed("second")));
      duringBatch = hub.records;
    });

    expect(duringBatch).toEqual([]);
    const snapshot = hub.records;
    expect(snapshot).toHaveLength(2);
    hub.clear();
    expect(hub.records).toEqual([]);
    expect(snapshot).toHaveLength(2);
    hub.dispose();
  });

  it("is inert after idempotent disposal", () => {
    const hub = new RecordingMessageHub();
    let completed = 0;
    hub.messages.subscribe({ complete: () => completed++ });

    hub.dispose();
    hub.dispose();
    hub.send(changed("ignored"));
    hub.batch(() => hub.send(changed("alsoIgnored")));

    expect(completed).toBe(1);
    expect(hub.records).toEqual([]);
  });
});

describe("ManualDispatcher", () => {
  it("keeps foreground and background queues ordered and independent", () => {
    const dispatcher = new ManualDispatcher();
    const seen: string[] = [];
    dispatcher.background.schedule(() => seen.push("background-1"));
    dispatcher.foreground.schedule(() => seen.push("foreground-1"));
    dispatcher.background.schedule(() => seen.push("background-2"));

    expect(seen).toEqual([]);
    dispatcher.flushForeground();
    expect(seen).toEqual(["foreground-1"]);
    dispatcher.flushBackground();
    expect(seen).toEqual(["foreground-1", "background-1", "background-2"]);
    dispatcher.dispose();
  });

  it("flushes both queues and cancels pending or future work on disposal", () => {
    const dispatcher = new ManualDispatcher();
    const seen: string[] = [];
    dispatcher.foreground.schedule(() => seen.push("foreground"));
    dispatcher.background.schedule(() => seen.push("background"));

    dispatcher.flushAll();
    expect(seen).toEqual(["foreground", "background"]);

    dispatcher.foreground.schedule(() => seen.push("cancelled"));
    dispatcher.dispose();
    dispatcher.dispose();
    expect(dispatcher.background.schedule(() => seen.push("ignored")))
      .toBe(Subscription.EMPTY);
    dispatcher.flushAll();
    expect(seen).toEqual(["foreground", "background"]);
  });
});

describe("createTestServices", () => {
  it("returns an owned recording hub and synchronous dispatcher", () => {
    const services = createTestServices();
    const seen: string[] = [];

    services.dispatcher.background.schedule(() => seen.push("ran"));
    services.hub.send(changed("name"));

    expect(seen).toEqual(["ran"]);
    expect(services.hub.records).toHaveLength(1);
    services.dispose();
    services.dispose();
  });
});
