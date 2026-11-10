// Conformance tests: FWD-006 — a forwarding decorator's notification helpers
// act on the wrapped VM (#1352): the hub message names the wrapped VM as
// sender, the decorator's propertyChanged emits once, and nothing is published
// after the wrapped VM is disposed. See spec/09-forwarding.md §1 and ADR-0221.
import { describe, it, expect } from "vitest";
import {
  MessageHub,
  RxDispatcher,
  ComponentVMOf,
  CompositeVM,
  ForwardingComponentVM,
  ForwardingCompositeVM,
  PropertyChangedMessage,
  type IComponentVMOf,
} from "../../src/index.js";

function makeHub() { return new MessageHub(); }
function makeDisp() { return RxDispatcher.immediate(); }

class NotifyingComponent extends ForwardingComponentVM<string> {
  notify(name: string): void { this._notifyPropertyChanged(name); }
  raiseLocal(name: string): void { this._raisePropertyChanged(name); }
}

class NotifyingComposite extends ForwardingCompositeVM<ComponentVMOf<string>> {
  notify(name: string): void { this._notifyPropertyChanged(name); }
  raiseLocal(name: string): void { this._raisePropertyChanged(name); }
}

describe("FWD-006", () => {
  const kinds = [
    {
      kind: "component",
      make(hub: MessageHub) {
        const inner = ComponentVMOf.builder<string>()
          .name("inner")
          .model("m")
          .services(hub, makeDisp())
          .build();
        return { inner, decorator: new NotifyingComponent(inner) };
      },
    },
    {
      kind: "composite",
      make(hub: MessageHub) {
        const inner = CompositeVM.builder<ComponentVMOf<string>>()
          .name("inner")
          .services(hub, makeDisp())
          .children(() => [])
          .build();
        return { inner, decorator: new NotifyingComposite(inner) };
      },
    },
  ];

  for (const { kind, make } of kinds) {
    it(`${kind} decorator helpers publish through the wrapped VM`, () => {
      const hub = makeHub();
      const { inner, decorator } = make(hub);
      const messages: PropertyChangedMessage<unknown>[] = [];
      hub.messages.subscribe((m) => {
        if (m instanceof PropertyChangedMessage) messages.push(m);
      });
      const names: string[] = [];
      decorator.propertyChanged.subscribe((name) => names.push(name));

      decorator.notify("custom");

      expect(names).toEqual(["custom"]);
      expect(messages).toHaveLength(1);
      expect(messages[0]!.sender).toBe(inner);
      expect(messages[0]!.propertyName).toBe("custom");

      decorator.raiseLocal("local");

      expect(names).toEqual(["custom", "local"]);
      expect(messages).toHaveLength(1);

      inner.dispose();
      names.length = 0;
      messages.length = 0;
      decorator.notify("after");
      decorator.raiseLocal("after");

      expect(names).toEqual([]);
      expect(messages).toEqual([]);
    });
  }
});

describe("forwarding decorator helpers over a plain IComponentVMOf (#1352)", () => {
  it("throw a TypeError that names the property-change helper", () => {
    const inner = ComponentVMOf.builder<string>()
      .name("inner")
      .model("m")
      .services(makeHub(), makeDisp())
      .build();
    // Delegates every member to `inner` but is not a VMx ComponentVMBase.
    const plain = new Proxy(inner, {
      getPrototypeOf: () => Object.prototype,
      get(target, property) {
        const value: unknown = Reflect.get(target, property, target);
        return typeof value === "function" ? (value as (...args: unknown[]) => unknown).bind(target) : value;
      },
    }) as IComponentVMOf<string>;
    const decorator = new NotifyingComponent(plain);

    expect(() => decorator.notify("custom")).toThrow(
      new TypeError("A forwarding decorator must wrap a VMx ComponentVMBase to report a property change"),
    );
    expect(() => decorator.raiseLocal("custom")).toThrow(
      new TypeError("A forwarding decorator must wrap a VMx ComponentVMBase to report a property change"),
    );
  });
});
