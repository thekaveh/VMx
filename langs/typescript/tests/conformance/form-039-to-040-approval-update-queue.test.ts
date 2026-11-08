// FORM-039..FORM-040 conformance tests — FormVM queues updates made during
// approval publication. See spec/20-form-vm.md §5.1/§5.3/§5.4 and ADR-0174.
//
// TypeScript runs on one thread, and an rxjs subscriber failure does not
// propagate to the notifying call (spec/20 §5.3 flavor note). Only a replayed
// preparation failure therefore reaches the approval's failure route here.

import { describe, expect, it, vi } from "vitest";

import {
  FormRevertedMessage,
  FormVM,
  MessageHub,
  PropertyChangedMessage,
} from "../../src/index.js";
import { allowRxUnhandledErrors } from "../setup.js";

interface Text {
  readonly value: string;
}

interface Num {
  readonly n: number;
}

const text = (value: string): Text => ({ value });
const num = (n: number): Num => ({ n });

/** Lets the command path's rejection handler run. Bounded: one macrotask. */
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

/** Records the form's model and revert hub messages into `trace`. */
function traceHub<TM>(hub: MessageHub, form: () => FormVM<TM>, trace: string[], label: (m: TM) => string) {
  return hub.messages.subscribe((message) => {
    if (message.sender !== form()) return;
    if (message instanceof FormRevertedMessage) trace.push("reverted");
    if (message instanceof PropertyChangedMessage && message.propertyName === "model") {
      trace.push(`model:${label(form().model)}`);
    }
  });
}

describe("FORM-039", () => {
  it("queues a setModel from resetOnApproved and replays it after onApproved", async () => {
    const hub = new MessageHub();
    const trace: string[] = [];
    let atCall: [string, number] | undefined;
    const form: FormVM<Text> = FormVM.builder<Text>()
      .initial(text("initial"))
      .persister(() => Promise.resolve())
      .hub(hub)
      .validator("value", (model) => (model.value === "x" ? "rejected" : null))
      .resetOnApproved(() => {
        form.setModel(text("x"));
        // The queued call changed and published nothing.
        atCall = [form.model.value, trace.length];
        return text("pristine");
      })
      .build();
    form.setModel(text("edited"));

    const errorMaps: Array<Record<string, string>> = [];
    form.errorsChanged.subscribe((errors) => {
      errorMaps.push(errors);
      trace.push(`errors:${JSON.stringify(errors)}`);
    });
    form.approveCommand.canExecuteChanged.subscribe(() => trace.push("can_execute"));
    traceHub(hub, () => form, trace, (model) => model.value);
    const observed: Array<[Text, boolean, boolean]> = [];
    form.onApproved.subscribe(() => {
      trace.push("approved");
      observed.push([form.model, form.isDirty, form.isValid]);
    });

    await form.approveAsync();

    // Admission plus one settlement notification; nothing of the queued call
    // is published before onApproved.
    expect(atCall).toEqual(["edited", 1]);
    expect(observed).toEqual([[text("pristine"), false, true]]);
    expect(trace).toEqual([
      "can_execute",
      "can_execute",
      "approved",
      'errors:{"value":"rejected"}',
      "can_execute",
      "model:x",
    ]);
    expect(form.model).toEqual(text("x"));
    expect(form.errors).toEqual({ value: "rejected" });
    expect(errorMaps.at(-1)).toEqual(form.errors);
  });

  it("queues a deny from a settlement canExecuteChanged observer", async () => {
    const hub = new MessageHub();
    const trace: string[] = [];
    let release!: () => void;
    const form = FormVM.builder<Text>()
      .initial(text("initial"))
      .persister(() => new Promise<void>((resolve) => { release = resolve; }))
      .hub(hub)
      .build();
    form.setModel(text("saved"));

    let armed = false;
    form.approveCommand.canExecuteChanged.subscribe(() => {
      if (!armed) return;
      armed = false;
      form.denyCommand.execute();
      // The queued deny reverted nothing yet.
      expect(form.model).toEqual(text("newer"));
    });
    traceHub(hub, () => form, trace, (model) => model.value);
    const observed: Array<[Text, boolean]> = [];
    form.onApproved.subscribe((approved) => {
      trace.push(`approved:${approved.value}`);
      observed.push([form.model, form.isDirty]);
    });

    const approval = form.approveAsync();
    // A racing edit while the persister runs.
    form.setModel(text("newer"));
    trace.length = 0;
    armed = true;
    release();
    await approval;

    expect(observed).toEqual([[text("newer"), true]]);
    expect(trace).toEqual(["approved:saved", "reverted", "model:saved"]);
    expect(form.model).toEqual(text("saved"));
    expect(form.isDirty).toBe(false);
  });

  it("replays a reset's setModel and deny in call order", async () => {
    const hub = new MessageHub();
    const trace: string[] = [];
    const form: FormVM<Text> = FormVM.builder<Text>()
      .initial(text("initial"))
      .persister(() => Promise.resolve())
      .hub(hub)
      .resetOnApproved(() => {
        form.setModel(text("a"));
        form.denyCommand.execute();
        return text("pristine");
      })
      .build();
    form.setModel(text("edited"));
    traceHub(hub, () => form, trace, (model) => model.value);
    const observed: Text[] = [];
    form.onApproved.subscribe(() => {
      trace.push("approved");
      observed.push(form.model);
    });

    await form.approveAsync();

    expect(observed).toEqual([text("pristine")]);
    expect(trace).toEqual([
      "approved",
      "model:a",
      "reverted",
      "model:pristine",
    ]);
    expect(form.model).toEqual(text("pristine"));
    expect(form.isDirty).toBe(false);
  });
});

describe("FORM-040", () => {
  /**
   * The #1050 shape: initial 1, edited to 2, and a validator that throws for
   * 13 while `failing(13)` is true. `onSettlement` runs in the settlement
   * canExecuteChanged notification (the second one, after admission).
   */
  function settlingForm(onSettlement: (form: FormVM<Num>) => void, failing: () => boolean) {
    const hub = new MessageHub();
    const form = FormVM.builder<Num>()
      .initial(num(1))
      .persister(() => Promise.resolve())
      .hub(hub)
      .validator("n", (model) => {
        if (model.n === 13 && failing()) throw new Error("boom13");
        return null;
      })
      .build();
    form.setModel(num(2));
    const approved: Num[] = [];
    const approveErrors: unknown[] = [];
    const models: number[] = [];
    form.onApproved.subscribe((value) => approved.push(value));
    form.approveErrors.subscribe((error) => approveErrors.push(error));
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.sender === form) {
        models.push(form.model.n);
      }
    });
    let notifications = 0;
    form.approveCommand.canExecuteChanged.subscribe(() => {
      notifications += 1;
      if (notifications === 2) onSettlement(form);
    });
    return { form, approved, approveErrors, models };
  }

  /** The observer of the #1050 repro: SetModel(13) fails, SetModel(42) is queued. */
  function repro(rejected: unknown[]) {
    return (form: FormVM<Num>) => {
      try {
        form.setModel(num(13));
      } catch (error) {
        rejected.push(error);
      }
      expect(form.model).toEqual(num(2));
      form.setModel(num(42));
    };
  }

  it("fails a queued candidate at call time on the awaited path", async () => {
    const rejected: unknown[] = [];
    const { form, approved, approveErrors } = settlingForm(repro(rejected), () => true);

    await expect(form.approveAsync()).resolves.toBeUndefined();

    expect((rejected as Error[]).map((error) => error.message)).toEqual(["boom13"]);
    expect(approved).toEqual([num(2)]);
    expect(approveErrors).toEqual([]);
    expect(form.model).toEqual(num(42));
  });

  it("fails a queued candidate at call time on the command path", async () => {
    const rejected: unknown[] = [];
    const { form, approved, approveErrors } = settlingForm(repro(rejected), () => true);

    form.approveCommand.execute();
    await vi.waitFor(() => expect(approved).toHaveLength(1));
    await settle();

    expect((rejected as Error[]).map((error) => error.message)).toEqual(["boom13"]);
    expect(approved).toEqual([num(2)]);
    expect(approveErrors).toEqual([]);
    expect(form.model).toEqual(num(42));
  });

  it("queues a candidate equal to the live model", async () => {
    const { form, approved, models } = settlingForm((target) => {
      target.setModel(num(5));
      target.setModel(num(2));
    }, () => false);
    models.length = 0;

    await form.approveAsync();

    expect(approved).toEqual([num(2)]);
    // Both calls replayed: 2 -> 5 -> 2.
    expect(models).toEqual([5, 2]);
    expect(form.model).toEqual(num(2));
  });

  /** Queues 13 (passes at call time) then 42; 13 fails when it replays. */
  function failingReplay() {
    let armed = false;
    const context = settlingForm((form) => {
      form.setModel(num(13));
      form.setModel(num(42));
    }, () => armed);
    context.form.onApproved.subscribe(() => { armed = true; });
    return context;
  }

  it("keeps replaying after a failure and routes it to the awaiter once", async () => {
    const { form, approved, approveErrors } = failingReplay();

    await expect(form.approveAsync()).rejects.toThrow("boom13");

    // The later replay still committed, and the approval stays settled.
    expect(form.model).toEqual(num(42));
    expect(form.snapshot).toEqual(num(2));
    expect(approved).toEqual([num(2)]);
    expect(approveErrors).toEqual([]);
    expect(form.approveCommand.canExecute()).toBe(true);
  });

  it("emits a replay failure once on approveErrors on the command path", async () => {
    const { form, approved, approveErrors } = failingReplay();

    form.approveCommand.execute();
    await vi.waitFor(() => expect(approveErrors).toHaveLength(1));
    await settle();

    expect((approveErrors as Error[]).map((error) => error.message)).toEqual(["boom13"]);
    expect(form.model).toEqual(num(42));
    expect(form.snapshot).toEqual(num(2));
    expect(approved).toEqual([num(2)]);
  });

  it("does not let a failing onApproved subscriber stop the replay (rxjs reports it instead)", async () => {
    // An rxjs subscriber failure does not propagate in TypeScript, so the
    // approval carries no failure of its own and the clause in which an
    // onApproved failure wins does not apply. The replay still runs, and its
    // failure is the one routed.
    allowRxUnhandledErrors();
    const { form, approved } = failingReplay();
    form.onApproved.subscribe(() => {
      throw new Error("subscriber");
    });

    await expect(form.approveAsync()).rejects.toThrow("boom13");

    expect(approved).toEqual([num(2)]);
    expect(form.model).toEqual(num(42));
  });
});
