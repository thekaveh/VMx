// Conformance tests: FWD-007 — the sender-filter helpers (whenPropertyChanged,
// propertyValueChangedMessagesFor, subscribeValue) match a forwarding decorator
// by its canonical identity, through nested decorators. The wrapped VM sends
// each message that a decorator causes (ADR-0221), so a helper given the outer
// decorator sees the wrapped VM's writes and no other VM's. See
// spec/03-messages.md §7.1, §7.2, §7.4, spec/09-forwarding.md §1 and ADR-0233.
import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  ForwardingComponentVM,
  PropertyChangedMessage,
  propertyValueChangedMessagesFor,
  subscribeValue,
  whenPropertyChanged,
} from "../../src/index.js";

class Layer extends ForwardingComponentVM<string> {}

describe("FWD-007", () => {
  it("helpers given a two-layer decorator match the wrapped VM's model write", () => {
    const hub = new MessageHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(hub, RxDispatcher.immediate())
      .build();
    const outer = new Layer(new Layer(inner));
    const messages: PropertyChangedMessage<unknown>[] = [];
    const values: unknown[] = [];
    const selected: [string, string][] = [];
    const subscriptions = [
      whenPropertyChanged(hub, outer, "model").subscribe((m) => messages.push(m)),
      propertyValueChangedMessagesFor(hub, outer, "model").subscribe((v) => values.push(v)),
      subscribeValue(outer, (vm) => vm.model, (current, previous) => selected.push([current, previous])),
    ];

    outer.model = "updated";

    expect(messages).toHaveLength(1);
    expect(messages[0]!.sender).toBe(inner);
    expect(values).toEqual(["updated"]);
    expect(selected).toEqual([["updated", "m"]]);
    for (const subscription of subscriptions) subscription.unsubscribe();
  });

  it("helpers given a two-layer decorator ignore other VMs on the hub", () => {
    const hub = new MessageHub();
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(hub, RxDispatcher.immediate())
      .build();
    const other = ComponentVMOf.builder<string>()
      .name("other")
      .model("m")
      .services(hub, RxDispatcher.immediate())
      .build();
    const outer = new Layer(new Layer(inner));
    const messages: PropertyChangedMessage<unknown>[] = [];
    const values: unknown[] = [];
    const selected: [string, string][] = [];
    const subscriptions = [
      whenPropertyChanged(hub, outer, "model").subscribe((m) => messages.push(m)),
      propertyValueChangedMessagesFor(hub, outer, "model").subscribe((v) => values.push(v)),
      subscribeValue(outer, (vm) => vm.model, (current, previous) => selected.push([current, previous])),
    ];

    other.model = "other-updated";

    expect(messages).toEqual([]);
    expect(values).toEqual([]);
    expect(selected).toEqual([]);
    for (const subscription of subscriptions) subscription.unsubscribe();
  });
});
