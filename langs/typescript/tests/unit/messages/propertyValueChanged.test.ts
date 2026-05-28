// Unit tests for propertyValueChangedMessagesFor helper.

import { describe, expect, it } from "vitest";
import { MessageHub } from "../../../src/services/messageHub.js";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import { propertyValueChangedMessagesFor } from "../../../src/messages/propertyValueChanged.js";

/** Minimal test source: manually sends messages through the hub on change. */
class TestSource {
  #hub: MessageHub;
  #count = 0;
  #label = "";

  constructor(hub: MessageHub) {
    this.#hub = hub;
  }

  get count(): number {
    return this.#count;
  }
  set count(value: number) {
    if (value !== this.#count) {
      this.#count = value;
      this.#hub.send(
        PropertyChangedMessage.create(this, "test-source", "count"),
      );
    }
  }

  get label(): string {
    return this.#label;
  }
  set label(value: string) {
    if (value !== this.#label) {
      this.#label = value;
      this.#hub.send(
        PropertyChangedMessage.create(this, "test-source", "label"),
      );
    }
  }
}

describe("propertyValueChangedMessagesFor", () => {
  it("returns observable of property values", () => {
    const hub = new MessageHub();
    const source = new TestSource(hub);
    const values: number[] = [];

    const sub = propertyValueChangedMessagesFor(hub, source, "count").subscribe(
      (v) => values.push(v as number),
    );

    source.count = 1;
    source.count = 2;
    source.count = 3;

    expect(values).toEqual([1, 2, 3]);
    sub.unsubscribe();
  });

  it("filters by sender instance", () => {
    const hub = new MessageHub();
    const source1 = new TestSource(hub);
    const source2 = new TestSource(hub);
    const values1: number[] = [];
    const values2: number[] = [];

    const sub1 = propertyValueChangedMessagesFor(
      hub,
      source1,
      "count",
    ).subscribe((v) => values1.push(v as number));
    const sub2 = propertyValueChangedMessagesFor(
      hub,
      source2,
      "count",
    ).subscribe((v) => values2.push(v as number));

    source1.count = 10;
    source2.count = 20;

    expect(values1).toEqual([10]);
    expect(values2).toEqual([20]);
    sub1.unsubscribe();
    sub2.unsubscribe();
  });

  it("filters by property name", () => {
    const hub = new MessageHub();
    const source = new TestSource(hub);
    const counts: number[] = [];
    const labels: string[] = [];

    const subCount = propertyValueChangedMessagesFor(
      hub,
      source,
      "count",
    ).subscribe((v) => counts.push(v as number));
    const subLabel = propertyValueChangedMessagesFor(
      hub,
      source,
      "label",
    ).subscribe((v) => labels.push(v as string));

    source.count = 42;
    source.label = "hello";

    expect(counts).toEqual([42]);
    expect(labels).toEqual(["hello"]);
    subCount.unsubscribe();
    subLabel.unsubscribe();
  });

  it("snapshots property value at message time", () => {
    const hub = new MessageHub();
    const source = new TestSource(hub);
    const snapshots: number[] = [];

    const sub = propertyValueChangedMessagesFor(hub, source, "count").subscribe(
      (v) => snapshots.push(v as number),
    );

    source.count = 5;
    source.count = 10;

    expect(snapshots).toEqual([5, 10]);
    sub.unsubscribe();
  });
});
