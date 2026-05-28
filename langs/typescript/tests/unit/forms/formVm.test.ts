// Unit tests for FormVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/form-001-to-010-form-vm.test.ts.

import { describe, expect, it, vi } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
} from "../../../src/index.js";

interface IModel {
  name: string;
  value: number;
}

function m(name: string, value: number): IModel {
  return { name, value };
}

const noop = (): Promise<void> => Promise.resolve();

function make(initial = m("A", 1)) {
  return new FormVM<IModel>({ initial, persister: noop });
}

// ---------------------------------------------------------------------------
// Construction guards
// ---------------------------------------------------------------------------

describe("FormVM construction guards", () => {
  it("throws when initial is null", () => {
    expect(
      () =>
        new FormVM<IModel>({ initial: null as unknown as IModel, persister: noop }),
    ).toThrow("initial must not be null or undefined");
  });

  it("throws when persister is undefined", () => {
    expect(
      () =>
        new FormVM<IModel>({
          initial: m("A", 1),
          persister: undefined as unknown as () => Promise<void>,
        }),
    ).toThrow("persister must not be null or undefined");
  });
});

// ---------------------------------------------------------------------------
// Snapshot
// ---------------------------------------------------------------------------

describe("FormVM snapshot", () => {
  it("is structurally equal to initial but a different reference", () => {
    const initial = m("Alice", 1);
    const sut = make(initial);
    expect(sut.snapshot).toEqual(initial);
    expect(sut.snapshot).not.toBe(initial); // structuredClone makes a copy
  });

  it("custom snapshotter called at construction", () => {
    const calls: IModel[] = [];
    const snapshotter = (model: IModel): IModel => {
      calls.push(model);
      return { ...model, name: model.name + "-snap" };
    };
    const initial = m("Alice", 1);
    const sut = new FormVM<IModel>({ initial, persister: noop, snapshotter });

    expect(calls).toHaveLength(1);
    expect(sut.snapshot.name).toBe("Alice-snap");
  });

  it("custom snapshotter applied on deny (restores from snapshot copy)", () => {
    const snapCalls: IModel[] = [];
    const snapshotter = (model: IModel): IModel => {
      snapCalls.push(model);
      return { ...model };
    };
    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, snapshotter });
    snapCalls.length = 0; // reset after construction

    sut.setModel(m("B", 2));
    sut.denyCommand.execute();

    expect(snapCalls).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// setModel
// ---------------------------------------------------------------------------

describe("FormVM setModel", () => {
  it("throws when model is null", () => {
    const sut = make();
    expect(() => sut.setModel(null as unknown as IModel)).toThrow(
      "model must not be null or undefined",
    );
  });

  it("tracks latest mutation", () => {
    const sut = make();
    sut.setModel(m("B", 2));
    sut.setModel(m("C", 3));
    expect(sut.model).toEqual(m("C", 3));
    expect(sut.isDirty).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// denyCommand
// ---------------------------------------------------------------------------

describe("FormVM denyCommand", () => {
  it("canExecute is always true", () => {
    const sut = make();
    expect(sut.denyCommand.canExecute()).toBe(true);
  });

  it("publishes hub messages even when model equals snapshot", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    hub.messages.subscribe((m) => messages.push(m));

    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, hub });
    // Not dirty; deny still sends hub messages.
    sut.denyCommand.execute();

    expect(messages).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// approveAsync — multiple rounds
// ---------------------------------------------------------------------------

describe("FormVM approveAsync", () => {
  it("snapshot advances across multiple rounds", async () => {
    const sut = make();

    sut.setModel(m("B", 2));
    await sut.approveAsync();
    expect(sut.snapshot).toEqual(m("B", 2));

    sut.setModel(m("C", 3));
    await sut.approveAsync();
    expect(sut.snapshot).toEqual(m("C", 3));
    expect(sut.isDirty).toBe(false);
  });

  it("non-strict allows re-approve without mutation", async () => {
    const approved: IModel[] = [];
    const sut = make();
    sut.onApproved.subscribe((m) => approved.push(m));

    await sut.approveAsync(); // Not dirty — allowed in non-strict mode.

    expect(approved).toHaveLength(1);
  });

  it("persister receives current model", async () => {
    const received: IModel[] = [];
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: (model) => {
        received.push(model);
        return Promise.resolve();
      },
    });
    sut.setModel(m("B", 2));
    await sut.approveAsync();

    expect(received).toEqual([m("B", 2)]);
  });
});

// ---------------------------------------------------------------------------
// Strict mode
// ---------------------------------------------------------------------------

describe("FormVM strict mode", () => {
  it("canExecuteChanged fires when isDirty transitions on setModel", () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    sut.setModel(m("B", 2));
    expect(fired).toBeGreaterThan(0);
  });

  it("canExecuteChanged fires when isDirty transitions on deny", () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    sut.setModel(m("B", 2)); // make dirty

    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    sut.denyCommand.execute();
    expect(fired).toBeGreaterThan(0);
  });

  it("canExecuteChanged fires after approve advances snapshot", async () => {
    const sut = new FormVM<IModel>({
      initial: m("A", 1),
      persister: noop,
      strict: true,
    });
    sut.setModel(m("B", 2));

    let fired = 0;
    sut.approveCommand.canExecuteChanged.subscribe(() => { fired++; });

    await sut.approveAsync();
    expect(fired).toBeGreaterThan(0);
    expect(sut.approveCommand.canExecute()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Hub message sender identity
// ---------------------------------------------------------------------------

describe("FormVM hub messages", () => {
  it("sender is the FormVM instance", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    hub.messages.subscribe((m) => messages.push(m));

    const sut = new FormVM<IModel>({ initial: m("A", 1), persister: noop, hub });
    sut.setModel(m("B", 2));
    sut.denyCommand.execute();

    const revertMsg = messages.find((m) => m instanceof FormRevertedMessage);
    expect(revertMsg?.sender).toBe(sut);

    const propMsg = messages.find((m) => m instanceof PropertyChangedMessage) as
      | PropertyChangedMessage<object>
      | undefined;
    expect(propMsg?.sender).toBe(sut);
    expect(propMsg?.propertyName).toBe("model");
  });
});

// ---------------------------------------------------------------------------
// onApproved observable
// ---------------------------------------------------------------------------

describe("FormVM onApproved", () => {
  it("completes after dispose", () => {
    const completed = vi.fn();
    const sut = make();
    sut.onApproved.subscribe({ complete: completed });

    sut.dispose();
    expect(completed).toHaveBeenCalledOnce();
  });
});
