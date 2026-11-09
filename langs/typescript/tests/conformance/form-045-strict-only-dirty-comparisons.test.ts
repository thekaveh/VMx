// FORM-045 conformance tests — an update runs the dirty comparisons only in
// strict mode. See spec/20-form-vm.md §5.2/§5.4 and ADR-0216.
//
// A strict setModel compares the candidate with the live model, the live
// model with the snapshot, and the candidate with the snapshot. A strict deny
// runs the last two. A non-strict setModel runs only the first comparison,
// and a non-strict deny runs none. The tests read no isDirty and no
// canExecute() between the calls they count.

import { describe, expect, it } from "vitest";

import { FormVM, MessageHub, PropertyChangedMessage } from "../../src/index.js";

interface Model {
  readonly value: string;
  readonly snapshot?: boolean;
}

const m = (value: string): Model => ({ value });

/** A form with model `x` whose equality counts its calls. */
function makeCountingForm(strict: boolean) {
  let calls = 0;
  const form = new FormVM<Model>({
    initial: m("x"),
    persister: async () => {},
    strict,
    // A separate copy, so the snapshot is never the live model object.
    snapshotter: (model) => ({ ...model }),
    equals: (a, b) => {
      calls += 1;
      return a.value === b.value;
    },
  });
  return {
    form,
    calls: () => calls,
    reset: () => {
      calls = 0;
    },
  };
}

describe("FORM-045", () => {
  it("runs the equality three times for a strict setModel and twice for a strict deny", () => {
    const { form, calls, reset } = makeCountingForm(true);

    form.setModel(m("y"));
    expect(calls()).toBe(3);

    reset();
    form.denyCommand.execute();
    expect(calls()).toBe(2);
  });

  it("runs the equality once for a non-strict setModel and not for a non-strict deny", () => {
    const { form, calls, reset } = makeCountingForm(false);

    form.setModel(m("y"));
    expect(calls()).toBe(1);

    reset();
    form.denyCommand.execute();
    expect(calls()).toBe(0);
  });

  it("never compares with the snapshot in a non-strict setModel", () => {
    const hub = new MessageHub();
    const form = new FormVM<Model>({
      initial: m("x"),
      persister: async () => {},
      hub,
      snapshotter: (model) => ({ ...model, snapshot: true }),
      equals: (a, b) => {
        if (a.snapshot === true || b.snapshot === true) {
          throw new Error("compared with the snapshot");
        }
        return a.value === b.value;
      },
    });
    let modelMessages = 0;
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "model") {
        modelMessages += 1;
      }
    });

    form.setModel(m("z"));

    expect(form.model).toEqual(m("z"));
    expect(modelMessages).toBe(1);
  });
});
