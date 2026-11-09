// FORM-044 conformance tests — a failed send stops the outermost update's
// queue and releases unstarted nested approvals. See spec/20-form-vm.md §5.4
// rule 7 and ADR-0216.
//
// When a send of the queue fails, no later notification of that queue is
// sent. A nested approval whose persister has not started is released: its
// in-flight mark clears, its persister is never called, and the command is
// re-announced when its admission was announced. The send failure propagates.

import { Subject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  FormVM,
  PropertyChangedMessage,
  type IMessage,
  type IMessageHub,
} from "../../src/index.js";

interface Model {
  readonly value: string;
}

const m = (value: string): Model => ({ value });

/** Waits a bounded time: a few macrotasks, so any scheduled work runs. */
const settle = async (): Promise<void> => {
  for (let i = 0; i < 3; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
};

class HubFailure extends Error {}

/**
 * A hub that records each model `PropertyChangedMessage` it receives and
 * throws on the first one.
 */
class FailingHub implements IMessageHub {
  readonly #subject = new Subject<IMessage>();
  readonly failure = new HubFailure("hub send failed");
  modelMessages = 0;

  get messages() {
    return this.#subject.asObservable();
  }

  send(message: IMessage): void {
    if (!(message instanceof PropertyChangedMessage)) return;
    if (message.propertyName !== "model") return;
    this.modelMessages += 1;
    if (this.modelMessages === 1) throw this.failure;
  }
}

/**
 * A valid, non-strict form whose validator, when it first sees `a`, calls
 * `approve`, then `setModel(b)`, then `setModel(c)`.
 */
function makeScenario(approve: (form: FormVM<Model>) => void) {
  const hub = new FailingHub();
  let persisted = 0;
  let canExecuteChanged = 0;
  let reentered = false;
  let form!: FormVM<Model>;
  form = new FormVM<Model>({
    initial: m("x"),
    persister: () => {
      persisted += 1;
      return Promise.resolve();
    },
    hub,
    validators: {
      value: (model) => {
        if (model.value === "a" && !reentered) {
          reentered = true;
          approve(form);
          form.setModel(m("b"));
          form.setModel(m("c"));
        }
        return null;
      },
    },
  });
  form.approveCommand.canExecuteChanged.subscribe(() => {
    canExecuteChanged += 1;
  });
  return {
    form,
    hub,
    persisted: () => persisted,
    canExecuteChanged: () => canExecuteChanged,
  };
}

describe("FORM-044", () => {
  it("stops the queue and releases a nested command-path approval", async () => {
    const approveErrors: unknown[] = [];
    const scenario = makeScenario((form) => form.approveCommand.execute());
    const { form, hub } = scenario;
    form.approveErrors.subscribe((error) => approveErrors.push(error));

    expect(() => form.setModel(m("a"))).toThrow(hub.failure);

    expect(hub.modelMessages).toBe(1);
    expect(scenario.canExecuteChanged()).toBe(2);
    await settle();
    expect(scenario.persisted()).toBe(0);
    expect(approveErrors).toEqual([]);
    expect(form.approveCommand.canExecute()).toBe(true);
    expect(form.model).toEqual(m("c"));
  });

  it("completes a nested approveAsync awaiter normally after the failure", async () => {
    let nested: Promise<void> | undefined;
    const scenario = makeScenario((form) => {
      nested = form.approveAsync();
    });
    const { form, hub } = scenario;

    expect(() => form.setModel(m("a"))).toThrow(hub.failure);

    expect(nested).toBeDefined();
    await expect(nested).resolves.toBeUndefined();
    expect(hub.modelMessages).toBe(1);
    expect(scenario.canExecuteChanged()).toBe(2);
    await settle();
    expect(scenario.persisted()).toBe(0);
    expect(form.approveCommand.canExecute()).toBe(true);
    expect(form.model).toEqual(m("c"));
  });
});
