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

function twoLayerStack() {
  const hub = new MessageHub();
  const inner = ComponentVMOf.builder<string>()
    .name("inner")
    .model("m")
    .services(hub, RxDispatcher.immediate())
    .build();
  const outer = new Layer(new Layer(inner));
  return { hub, inner, outer };
}

describe("FWD-007", () => {
  it("whenPropertyChanged given a two-layer decorator emits the wrapped VM's model write", () => {
    const { hub, inner, outer } = twoLayerStack();
    const messages: PropertyChangedMessage<unknown>[] = [];
    const subscription = whenPropertyChanged(hub, outer, "model").subscribe((m) => messages.push(m));

    outer.model = "updated";

    expect(messages).toHaveLength(1);
    expect(messages[0]!.sender).toBe(inner);
    subscription.unsubscribe();
  });

  it("propertyValueChangedMessagesFor given a two-layer decorator emits the wrapped VM's value", () => {
    const { hub, outer } = twoLayerStack();
    const values: unknown[] = [];
    const subscription = propertyValueChangedMessagesFor(hub, outer, "model").subscribe((v) => values.push(v));

    outer.model = "updated";

    expect(values).toEqual(["updated"]);
    subscription.unsubscribe();
  });

  it("subscribeValue given a two-layer decorator calls back for the wrapped VM's model write", () => {
    const { outer } = twoLayerStack();
    const selected: [string, string][] = [];
    const subscription = subscribeValue(outer, (vm) => vm.model, (current, previous) => selected.push([current, previous]));

    outer.model = "updated";

    expect(selected).toEqual([["updated", "m"]]);
    subscription.unsubscribe();
  });

  it("helpers given a two-layer decorator ignore other VMs on the hub", () => {
    const { hub, outer } = twoLayerStack();
    const other = ComponentVMOf.builder<string>()
      .name("other")
      .model("m")
      .services(hub, RxDispatcher.immediate())
      .build();
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
