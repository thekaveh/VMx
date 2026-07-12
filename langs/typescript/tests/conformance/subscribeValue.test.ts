import type { Subscription } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  ComponentVMOf,
  MessageHub,
  RxDispatcher,
  subscribeValue,
} from "../../src/index.js";
import { allowRxUnhandledErrors } from "../setup.js";

interface TestModel {
  value: number;
}

function makeVm(
  hub: MessageHub,
  name: string,
  value: number,
): ComponentVMOf<TestModel> {
  return ComponentVMOf.builder<TestModel>()
    .name(name)
    .model({ value })
    .services(hub, RxDispatcher.immediate())
    .build();
}

describe("SUBV-001", () => {
  it("filters to one sender and uses Object.is with optional immediate delivery", () => {
    const hub = new MessageHub();
    const vm = makeVm(hub, "source", 0);
    const other = makeVm(hub, "other", 0);
    const seen: Array<[number, number]> = [];
    let selectorCalls = 0;

    const sub = subscribeValue(
      vm,
      (source: ComponentVMOf<TestModel>): number => {
        selectorCalls += 1;
        return source.model.value;
      },
      (current: number, previous: number): void => {
        seen.push([current, previous]);
      },
      { fireImmediately: true },
    );

    expect(seen).toEqual([[0, 0]]);
    expect(selectorCalls).toBe(1);

    other.republishModel();
    hub.send({ sender: vm, senderName: vm.name });
    expect(selectorCalls).toBe(1);

    vm.republishModel();
    expect(selectorCalls).toBe(2);
    expect(seen).toEqual([[0, 0]]);

    vm.model = { value: 1 };
    vm.model = { value: Number.NaN };
    vm.model = { value: Number.NaN };

    expect(selectorCalls).toBe(5);
    expect(seen).toEqual([
      [0, 0],
      [1, 0],
      [Number.NaN, 1],
    ]);

    sub.unsubscribe();
  });
});

describe("SUBV-002", () => {
  it("evaluates the selector and custom equality once per matching message", () => {
    const hub = new MessageHub();
    const vm = makeVm(hub, "source", 1.1);
    const seen: Array<[number, number]> = [];
    const comparisons: Array<[number, number]> = [];
    let selectorCalls = 0;

    const sub = subscribeValue(
      vm,
      (source: ComponentVMOf<TestModel>): number => {
        selectorCalls += 1;
        return source.model.value;
      },
      (current: number, previous: number): void => {
        seen.push([current, previous]);
      },
      {
        equality: (current: number, next: number): boolean => {
          comparisons.push([current, next]);
          return Math.floor(current) === Math.floor(next);
        },
      },
    );

    vm.model = { value: 1.9 };
    vm.republishModel();
    vm.model = { value: 2.1 };

    expect(selectorCalls).toBe(4);
    expect(comparisons).toEqual([
      [1.1, 1.9],
      [1.1, 1.9],
      [1.1, 2.1],
    ]);
    expect(seen).toEqual([[2.1, 1.1]]);

    sub.unsubscribe();
  });
});

describe("SUBV-003", () => {
  it("preserves re-entrant order, suppresses final batch snapshots, and unsubscribes deterministically", () => {
    const hub = new MessageHub();
    const vm = makeVm(hub, "source", 0);
    const seen: Array<[number, number]> = [];

    const sub = subscribeValue(
      vm,
      (source: ComponentVMOf<TestModel>): number => source.model.value,
      (current: number, previous: number): void => {
        seen.push([current, previous]);
        if (current === 1) vm.model = { value: 2 };
      },
    );

    vm.model = { value: 1 };
    expect(seen).toEqual([
      [1, 0],
      [2, 1],
    ]);

    hub.batch(() => {
      vm.model = { value: 3 };
      vm.model = { value: 4 };
    });
    expect(seen).toEqual([
      [1, 0],
      [2, 1],
      [4, 2],
    ]);

    sub.unsubscribe();
    vm.model = { value: 5 };
    expect(seen).toHaveLength(3);

    const callbackVm = makeVm(hub, "callback-source", 0);
    const callbackSeen: Array<[number, number]> = [];
    let selectorCalls = 0;
    let callbackSub: Subscription | undefined;
    callbackSub = subscribeValue(
      callbackVm,
      (source: ComponentVMOf<TestModel>): number => {
        selectorCalls += 1;
        return source.model.value;
      },
      (current: number, previous: number): void => {
        callbackSeen.push([current, previous]);
        callbackSub?.unsubscribe();
        callbackVm.model = { value: 2 };
      },
    );

    callbackVm.model = { value: 1 };
    callbackVm.model = { value: 3 };

    expect(callbackSeen).toEqual([[1, 0]]);
    expect(selectorCalls).toBe(2);
  });
});

describe("SUBV-004", () => {
  it("propagates setup failures and isolates delivery failures without rolling back the baseline", () => {
    const hub = new MessageHub();
    const selectorVm = makeVm(hub, "selector-source", 0);
    const initialSelectorError = new Error("initial selector failed");
    let failedSelectorCalls = 0;

    expect(() =>
      subscribeValue(
        selectorVm,
        (_source: ComponentVMOf<TestModel>): number => {
          failedSelectorCalls += 1;
          throw initialSelectorError;
        },
        (_current: number, _previous: number): void => {},
      ),
    ).toThrow(initialSelectorError);
    selectorVm.republishModel();
    expect(failedSelectorCalls).toBe(1);

    const immediateVm = makeVm(hub, "immediate-source", 0);
    const immediateError = new Error("immediate callback failed");
    let immediateSelectorCalls = 0;
    expect(() =>
      subscribeValue(
        immediateVm,
        (source: ComponentVMOf<TestModel>): number => {
          immediateSelectorCalls += 1;
          return source.model.value;
        },
        (_current: number, _previous: number): void => {
          throw immediateError;
        },
        { fireImmediately: true },
      ),
    ).toThrow(immediateError);
    immediateVm.republishModel();
    expect(immediateSelectorCalls).toBe(1);

    allowRxUnhandledErrors();
    const deliveryVm = makeVm(hub, "delivery-source", 0);
    const deliveryError = new Error("delivery callback failed");
    const seen: Array<[number, number]> = [];
    let healthyDeliveries = 0;
    hub.messages.subscribe(() => {
      healthyDeliveries += 1;
    });

    const sub = subscribeValue(
      deliveryVm,
      (source: ComponentVMOf<TestModel>): number => source.model.value,
      (current: number, previous: number): void => {
        seen.push([current, previous]);
        if (current === 1) throw deliveryError;
      },
    );

    expect(() => {
      deliveryVm.model = { value: 1 };
      deliveryVm.model = { value: 2 };
    }).not.toThrow();
    expect(seen).toEqual([
      [1, 0],
      [2, 1],
    ]);
    expect(healthyDeliveries).toBe(2);

    sub.unsubscribe();
  });
});
