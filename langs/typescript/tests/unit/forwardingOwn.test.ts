/**
 * Owned resources registered through a forwarding decorator (spec/09 §1,
 * ADR-0151). FWD-005 covers the catalog scenario; these tests cover the
 * TypeScript edges.
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVMOf,
  ForwardingComponentVM,
  MessageHub,
  RxDispatcher,
  type IComponentVMOf,
} from "../../src/index.js";

class OwningDecorator<M> extends ForwardingComponentVM<M> {
  register(resource: () => void): void {
    this.own(resource);
  }
}

class Inner extends ComponentVMOf<string> {
  register(resource: () => void): void {
    this.own(resource);
  }
}

function makeInner(): IComponentVMOf<string> {
  return ComponentVMOf.builder<string>()
    .name("inner")
    .model("m")
    .services(new MessageHub(), RxDispatcher.immediate())
    .build();
}

describe("forwarding decorator own()", () => {
  it("releases a registration made after the decorator is disposed exactly once", () => {
    const decorator = new OwningDecorator(makeInner());
    let released = 0;
    decorator.dispose();

    decorator.register(() => (released += 1));
    expect(released).toBe(1);

    decorator.dispose();
    expect(released).toBe(1);
  });

  it("shares one LIFO order with the wrapped component's own registrations", () => {
    const inner = new Inner({
      name: "inner",
      initialModel: "m",
      hub: new MessageHub(),
      dispatcher: RxDispatcher.immediate(),
    });
    const decorator = new OwningDecorator(inner);
    const released: string[] = [];
    inner.register(() => released.push("inner-1"));
    decorator.register(() => released.push("decorator"));
    inner.register(() => released.push("inner-2"));

    decorator.dispose();

    expect(released).toEqual(["inner-2", "decorator", "inner-1"]);
  });

  it("rejects registration when the wrapped component is not a ComponentVMBase", () => {
    const real = makeInner();
    // Reads go to the real component; `instanceof ComponentVMBase` is false.
    const foreign = new Proxy(real, {
      get: (target, key) => {
        const value: unknown = Reflect.get(target, key, target);
        return typeof value === "function"
          ? (value as (...args: unknown[]) => unknown).bind(target)
          : value;
      },
      getPrototypeOf: () => Object.prototype,
    });
    const decorator = new OwningDecorator(foreign);

    expect(() => {
      decorator.register(() => undefined);
    }).toThrow(TypeError);
  });
});
