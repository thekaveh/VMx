// FORM-041..FORM-042 conformance tests — nested FormVM updates notify at the
// outermost update. See spec/20-form-vm.md §5.3/§5.4/§10 and ADR-0180.
//
// A setModel, deny, or approve call made from a preparation callback, or from
// an errorsChanged observer that the outermost update delivers, returns before
// its notifications. The outermost update sends them before it returns: error
// maps first, then the rest in commit order, then a nested approval's
// persister call. Once the form is disposed, the queued notifications are
// dropped and a persister that has not started is never called.

import { describe, expect, it } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
  type FormVMOptions,
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

/** A valid, non-strict form on its own hub, whose notifications go to `log`. */
function makeForm(log: string[], options: Partial<FormVMOptions<Model>> = {}) {
  const hub = new MessageHub();
  const form = new FormVM<Model>({
    initial: m("initial"),
    persister: async () => {},
    hub,
    snapshotter: (value) => value,
    ...options,
  });
  form.errorsChanged.subscribe((errors) => log.push(`errors ${JSON.stringify(errors)}`));
  form.approveCommand.canExecuteChanged.subscribe(() => log.push("can_execute"));
  hub.messages.subscribe((message) => {
    if (message.sender !== form) return;
    if (message instanceof FormRevertedMessage) log.push("reverted");
    if (message instanceof PropertyChangedMessage && message.propertyName === "model") {
      log.push(`model ${form.model.value}`);
    }
  });
  return { form, hub };
}

describe("FORM-041", () => {
  it("sends a nested assignment's notifications after it returns", () => {
    const log: string[] = [];
    let reentered = false;
    let form!: FormVM<Model>;
    ({ form } = makeForm(log, {
      validators: {
        value: (model) => {
          if (model.value === "a" && !reentered) {
            reentered = true;
            form.setModel(m("b"));
            log.push("nested returned");
          }
          return model.value === "b" ? "taken" : null;
        },
      },
    }));

    form.setModel(m("a"));
    log.push("outer returned");

    expect(log).toEqual([
      "nested returned",
      'errors {"value":"taken"}',
      "can_execute",
      "model b",
      "outer returned",
    ]);
    expect(form.model).toEqual(m("b"));
    expect(form.errors).toEqual({ value: "taken" });
  });

  it("sends a nested deny's notifications after it returns", () => {
    const log: string[] = [];
    let armed = false;
    let reentered = false;
    let form!: FormVM<Model>;
    ({ form } = makeForm(log, {
      validators: {
        value: (model) => {
          if (armed && model.value === "a" && !reentered) {
            reentered = true;
            form.denyCommand.execute();
            log.push("nested returned");
          }
          return model.value === "x" ? "rejected" : null;
        },
      },
    }));
    form.setModel(m("x"));
    log.length = 0;
    armed = true;

    form.setModel(m("a"));
    log.push("outer returned");

    expect(log).toEqual([
      "nested returned",
      "errors {}",
      "reverted",
      "model initial",
      "can_execute",
      "outer returned",
    ]);
    expect(form.model).toBe(form.snapshot);
    expect(form.isValid).toBe(true);
  });

  it("queues an assignment made from an errorsChanged observer behind the outer update", () => {
    const log: string[] = [];
    let reentered = false;
    const { form } = makeForm(log, {
      validators: { value: (model) => (model.value === "a" ? "rejected" : null) },
    });
    const maps: Array<Record<string, string>> = [];
    form.errorsChanged.subscribe((errors) => {
      maps.push(errors);
      if (!reentered) {
        reentered = true;
        form.setModel(m("c"));
        log.push("nested returned");
      }
    });

    form.setModel(m("a"));
    log.push("outer returned");

    expect(log).toEqual([
      'errors {"value":"rejected"}',
      "nested returned",
      "errors {}",
      "can_execute",
      "model c",
      "can_execute",
      "model c",
      "outer returned",
    ]);
    expect(maps).toEqual([{ value: "rejected" }, {}]);
    expect(form.model).toEqual(m("c"));
  });

  it("sends the notifications of a call nested in an errorsChanged observer's update", () => {
    const log: string[] = [];
    let reentered = false;
    let nestedInC = false;
    let form!: FormVM<Model>;
    ({ form } = makeForm(log, {
      validators: {
        value: (model) => {
          // The update from the errorsChanged observer makes a nested call
          // of its own; that call's notifications must still go out.
          if (model.value === "c" && !nestedInC) {
            nestedInC = true;
            form.setModel(m("d"));
          }
          return model.value === "a" ? "rejected" : null;
        },
      },
    }));
    form.errorsChanged.subscribe(() => {
      if (!reentered) {
        reentered = true;
        form.setModel(m("c"));
      }
    });

    form.setModel(m("a"));
    log.push("outer returned");

    expect(log).toEqual([
      'errors {"value":"rejected"}',
      "errors {}",
      "can_execute",
      "model d",
      "can_execute",
      "model d",
      "outer returned",
    ]);
    expect(form.model).toEqual(m("d"));
  });

  it("calls a nested approval's persister after the outer update's notifications", async () => {
    const log: string[] = [];
    const persisted: string[] = [];
    let reentered = false;
    let approval: Promise<void> | undefined;
    let form!: FormVM<Model>;
    ({ form } = makeForm(log, {
      persister: (model) => {
        log.push("persist");
        persisted.push(model.value);
        return Promise.resolve();
      },
      validators: {
        value: (model) => {
          if (model.value === "a" && !reentered) {
            reentered = true;
            approval = form.approveAsync();
            log.push("nested returned");
          }
          return null;
        },
      },
    }));

    form.setModel(m("a"));
    log.push("outer returned");

    expect(log).toEqual([
      "nested returned",
      "can_execute",
      "model a",
      "persist",
      "outer returned",
    ]);
    await approval;
    expect(persisted).toEqual(["initial"]);
    expect(form.model).toEqual(m("a"));
    expect(form.snapshot).toEqual(m("initial"));
    expect(form.isDirty).toBe(true);
  });
});

describe("FORM-042", () => {
  /** Counts every channel the scenarios watch. */
  function counted(form: FormVM<Model>, hub: MessageHub) {
    const counts = { errors: 0, canExecute: 0, model: 0, approved: 0, approveErrors: 0 };
    form.errorsChanged.subscribe(() => (counts.errors += 1));
    form.approveCommand.canExecuteChanged.subscribe(() => (counts.canExecute += 1));
    form.onApproved.subscribe(() => (counts.approved += 1));
    form.approveErrors.subscribe(() => (counts.approveErrors += 1));
    hub.messages.subscribe((message) => {
      if (message.sender === form && message instanceof PropertyChangedMessage) counts.model += 1;
    });
    return counts;
  }

  /**
   * What a bare `dispose()` changes: the disposed approve command raises one
   * final re-evaluation (FORM-014). A scenario that publishes nothing of its
   * own matches this.
   */
  function bareDisposeCounts() {
    const { form, counts } = makeCountedForm();
    form.dispose();
    return counts;
  }

  function makeCountedForm(validator?: (form: FormVM<Model>, model: Model) => string | null) {
    const hub = new MessageHub();
    let persisterCalls = 0;
    let form!: FormVM<Model>;
    const options: FormVMOptions<Model> = {
      initial: m("initial"),
      persister: () => {
        persisterCalls += 1;
        return Promise.resolve();
      },
      hub,
      snapshotter: (value) => value,
    };
    if (validator !== undefined) options.validators = { value: (model) => validator(form, model) };
    form = new FormVM<Model>(options);
    const counts = counted(form, hub);
    return { form, counts, persisterCalls: () => persisterCalls };
  }

  it("never calls the persister of a nested command approval followed by dispose()", async () => {
    let reentered = false;
    const { form, counts, persisterCalls } = makeCountedForm((self, model) => {
      if (model.value === "trigger" && !reentered) {
        reentered = true;
        self.approveCommand.execute();
        self.dispose();
      }
      return null;
    });

    form.setModel(m("trigger"));
    await settle();

    expect(persisterCalls()).toBe(0);
    expect(counts).toEqual(bareDisposeCounts());
  });

  it("completes a nested approveAsync awaiter normally when dispose() follows it", async () => {
    let reentered = false;
    let approval: Promise<void> | undefined;
    const { form, counts, persisterCalls } = makeCountedForm((self, model) => {
      if (model.value === "trigger" && !reentered) {
        reentered = true;
        approval = self.approveAsync();
        self.dispose();
      }
      return null;
    });

    form.setModel(m("trigger"));

    await expect(approval).resolves.toBeUndefined();
    await settle();
    expect(persisterCalls()).toBe(0);
    expect(counts).toEqual(bareDisposeCounts());
  });

  it("drops the queued notifications of a nested assignment followed by dispose()", async () => {
    let reentered = false;
    const { form, counts } = makeCountedForm((self, model) => {
      if (model.value === "a" && !reentered) {
        reentered = true;
        self.setModel(m("b"));
        self.dispose();
      }
      return model.value === "b" ? "taken" : null;
    });

    form.setModel(m("a"));
    await settle();

    expect(counts).toEqual(bareDisposeCounts());
  });

  it("keeps the persister call count after a dispose() that follows execute()", async () => {
    const { form, persisterCalls } = makeCountedForm();

    form.approveCommand.execute();
    const n = persisterCalls();
    form.dispose();
    await settle();

    // The command path calls the persister before execute() returns.
    expect(n).toBe(1);
    expect(persisterCalls()).toBe(n);
  });
});
