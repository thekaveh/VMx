// FORM-031..FORM-034 conformance tests — FormVM single-flight approval admission.
// See spec/20-form-vm.md §5.3 and ADR-0143.
//
// Every persister here blocks on a gate the test releases, so each in-flight
// window is deterministic. No test sleeps or waits on a real timer.

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

const required = (model: Model): string | null =>
  model.value.length === 0 ? "required" : null;

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(reason: Error): void;
}

function deferred<T = void>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A persister whose every call blocks on its own gate until the test settles it. */
function gatedPersister() {
  const calls: Model[] = [];
  const gates: Deferred<void>[] = [];
  return {
    calls,
    persister: (model: Model): Promise<void> => {
      calls.push(model);
      const gate = deferred();
      gates.push(gate);
      return gate.promise;
    },
    succeed(call: number): void {
      gates[call]!.resolve();
    },
    fail(call: number, error: Error): void {
      gates[call]!.reject(error);
    },
  };
}

/** Lets every already-queued promise continuation run; no timers involved. */
async function drainMicrotasks(): Promise<void> {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
}

/** Records every approve-related signal a form emits. */
function record(form: FormVM<Model>) {
  const signals = {
    approved: [] as Model[],
    approveErrors: [] as unknown[],
    errorsChanged: [] as Array<Record<string, string>>,
    canExecuteChanged: 0,
  };
  form.onApproved.subscribe((value) => signals.approved.push(value));
  form.approveErrors.subscribe((error) => signals.approveErrors.push(error));
  form.errorsChanged.subscribe((errors) => signals.errorsChanged.push(errors));
  form.approveCommand.canExecuteChanged.subscribe(() => {
    signals.canExecuteChanged += 1;
  });
  return signals;
}

/** The observable form state a refused approve call must leave untouched. */
function state(form: FormVM<Model>) {
  return {
    model: form.model,
    snapshot: form.snapshot,
    errors: form.errors,
    isDirty: form.isDirty,
    isValid: form.isValid,
  };
}

/** What `approveCommand.canExecute()` reports from the validity and strict gates alone. */
function gatesAlone(form: FormVM<Model>, strict: boolean): boolean {
  return form.isValid && (!strict || form.isDirty);
}

type Entry = "approveAsync" | "command";

// ---------------------------------------------------------------------------
// FORM-031
// ---------------------------------------------------------------------------

describe("FORM-031", () => {
  it.each<Entry>(["approveAsync", "command"])(
    "refuses every other approve call while one admitted through %s is in flight",
    async (entry) => {
      const persist = gatedPersister();
      const refused: Array<Promise<void>> = [];
      const thrown: unknown[] = [];
      let form!: FormVM<Model>;
      const approveEverywhere = (): void => {
        refused.push(form.approveAsync());
        try {
          form.approveCommand.execute();
        } catch (error: unknown) {
          thrown.push(error);
        }
      };

      form = new FormVM<Model>({
        initial: m("initial"),
        persister: (model) => {
          const blocked = persist.persister(model);
          // The persister of the admitted approval approves again.
          if (persist.calls.length === 1) approveEverywhere();
          return blocked;
        },
        validators: { value: required },
      });
      const signals = record(form);
      form.setModel(m("first"));
      const before = state(form);

      // So does a CanExecuteChanged handler, on the admission notification.
      let handlerArmed = true;
      form.approveCommand.canExecuteChanged.subscribe(() => {
        if (!handlerArmed) return;
        handlerArmed = false;
        approveEverywhere();
      });

      const settled = deferred();
      form.onApproved.subscribe(() => settled.resolve());
      let first: Promise<void> | null = null;
      if (entry === "approveAsync") {
        first = form.approveAsync();
      } else {
        form.approveCommand.execute();
      }
      expect(handlerArmed).toBe(false);

      // And so does the caller, while the persister is still blocked.
      approveEverywhere();

      expect(refused).toHaveLength(3);
      await expect(Promise.all(refused)).resolves.toEqual([undefined, undefined, undefined]);
      await drainMicrotasks();
      expect(thrown).toEqual([]);
      expect(persist.calls).toEqual([m("first")]);
      expect(state(form)).toEqual(before);
      expect(signals.approved).toEqual([]);
      expect(signals.approveErrors).toEqual([]);
      expect(signals.errorsChanged).toEqual([]);

      persist.succeed(0);
      await (first ?? settled.promise);

      expect(persist.calls).toEqual([m("first")]);
      expect(form.snapshot).toEqual(m("first"));
      expect(signals.approved).toEqual([m("first")]);

      // After settlement the next approval is admitted and advances the snapshot.
      form.setModel(m("second"));
      const second = form.approveAsync();
      expect(persist.calls).toEqual([m("first"), m("second")]);
      persist.succeed(1);
      await second;

      expect(form.snapshot).toEqual(m("second"));
      expect(form.isDirty).toBe(false);
      expect(signals.approved).toEqual([m("first"), m("second")]);
      expect(signals.approveErrors).toEqual([]);
    },
  );

  it("refuses a later, faster approval so a slow earlier persist cannot overwrite it", async () => {
    const persist = gatedPersister();
    const form = new FormVM<Model>({ initial: m("initial"), persister: persist.persister });
    const signals = record(form);

    form.setModel(m("older"));
    const slow = form.approveAsync();
    form.setModel(m("newer"));
    const fast = form.approveAsync();
    await fast;

    // Only the admitted approval reached the persister.
    expect(persist.calls).toEqual([m("older")]);
    persist.succeed(0);
    await slow;

    expect(form.snapshot).toEqual(m("older"));
    expect(form.model).toEqual(m("newer"));
    expect(form.isDirty).toBe(true);
    expect(signals.approved).toEqual([m("older")]);

    // Snapshots advance in admission order.
    const next = form.approveAsync();
    expect(persist.calls).toEqual([m("older"), m("newer")]);
    persist.succeed(1);
    await next;
    expect(form.snapshot).toEqual(m("newer"));
    expect(signals.approved).toEqual([m("older"), m("newer")]);
  });
});

// ---------------------------------------------------------------------------
// FORM-032
// ---------------------------------------------------------------------------

describe("FORM-032", () => {
  type Outcome = "success" | "failure" | "reset failure";
  const cases: Array<[Outcome, boolean, Entry]> = [];
  for (const outcome of ["success", "failure", "reset failure"] as const) {
    for (const strict of [false, true]) {
      for (const entry of ["approveAsync", "command"] as const) {
        cases.push([outcome, strict, entry]);
      }
    }
  }

  it.each(cases)(
    "notifies once on admission and once on %s settlement (strict: %s, via %s)",
    async (outcome, strict, entry) => {
      const boom = new Error(`approval ${outcome}`);
      const persist = gatedPersister();
      let notifications = 0;
      let notificationsAtPersist = -1;
      let canExecuteAtPersist: boolean | null = null;
      let form!: FormVM<Model>;
      const options: FormVMOptions<Model> = {
        initial: m("initial"),
        strict,
        persister: (model) => {
          notificationsAtPersist = notifications;
          canExecuteAtPersist = form.approveCommand.canExecute();
          return persist.persister(model);
        },
      };
      if (outcome === "reset failure") {
        options.resetOnApproved = () => {
          throw boom;
        };
      }
      form = new FormVM<Model>(options);
      form.setModel(m("edited"));

      const trace: string[] = [];
      form.approveCommand.canExecuteChanged.subscribe(() => {
        notifications += 1;
        trace.push(`canExecuteChanged:${String(form.approveCommand.canExecute())}`);
      });
      const outcomeRouted = deferred<string>();
      form.onApproved.subscribe(() => {
        trace.push("onApproved");
        outcomeRouted.resolve("onApproved");
      });
      form.approveErrors.subscribe((error) => {
        trace.push("approveErrors");
        expect(error).toBe(boom);
        outcomeRouted.resolve("approveErrors");
      });

      let approval: Promise<void> | null = null;
      if (entry === "approveAsync") {
        approval = form.approveAsync();
      } else {
        form.approveCommand.execute();
      }

      // Admission raised exactly one notification before the persister ran.
      expect(notificationsAtPersist).toBe(1);
      expect(canExecuteAtPersist).toBe(false);
      expect(form.approveCommand.canExecute()).toBe(false);
      await drainMicrotasks();
      expect(form.approveCommand.canExecute()).toBe(false);
      expect(notifications).toBe(1);

      if (outcome === "failure") {
        persist.fail(0, boom);
      } else {
        persist.succeed(0);
      }
      if (approval !== null) {
        if (outcome === "success") {
          await approval;
        } else {
          await expect(approval).rejects.toBe(boom);
          trace.push("awaiter");
        }
      } else {
        await outcomeRouted.promise;
      }
      await drainMicrotasks();

      // One settlement notification, published before the outcome is routed.
      expect(notifications).toBe(2);
      const enabled = gatesAlone(form, strict);
      const routed =
        outcome === "success"
          ? "onApproved"
          : entry === "approveAsync" ? "awaiter" : "approveErrors";
      expect(trace).toEqual([
        "canExecuteChanged:false",
        `canExecuteChanged:${String(enabled)}`,
        routed,
      ]);
      expect(form.approveCommand.canExecute()).toBe(enabled);
      // Only a successful strict approval leaves the form pristine and disabled.
      expect(enabled).toBe(!(strict && outcome === "success"));
    },
  );

  it.each([false, true])(
    "merges a commit's validity change into the one settlement notification (strict: %s)",
    async (strict) => {
      const persist = gatedPersister();
      const form = new FormVM<Model>({
        initial: m("initial"),
        persister: persist.persister,
        strict,
        validators: { value: required },
        resetOnApproved: () => m(""),
      });
      form.setModel(m("edited"));
      const signals = record(form);

      const approval = form.approveAsync();
      expect(signals.canExecuteChanged).toBe(1);
      persist.succeed(0);
      await approval;

      expect(signals.errorsChanged).toEqual([{ value: "required" }]);
      expect(signals.canExecuteChanged).toBe(2);
      expect(form.approveCommand.canExecute()).toBe(false);
      expect(form.approveCommand.canExecute()).toBe(gatesAlone(form, strict));
    },
  );
});

// ---------------------------------------------------------------------------
// FORM-033
// ---------------------------------------------------------------------------

describe("FORM-033", () => {
  it.each([false, true])(
    "admits an approval started by an OnApproved subscriber (strict: %s)",
    async (strict) => {
      const persist = gatedPersister();
      const form = new FormVM<Model>({
        initial: m("initial"),
        persister: persist.persister,
        strict,
        resetOnApproved: (model) => m(`settled:${model.value}`),
      });
      form.setModel(m("edited"));

      const observed: Array<[boolean, boolean]> = [];
      const reentrant: Array<Promise<void>> = [];
      form.onApproved.subscribe(() => {
        if (reentrant.length > 0) return;
        observed.push([form.approveCommand.canExecute(), gatesAlone(form, strict)]);
        reentrant.push(form.approveAsync());
      });

      const first = form.approveAsync();
      persist.succeed(0);
      await first;

      // The subscriber saw an idle form: only the validity and strict gates.
      expect(observed).toEqual([[!strict, !strict]]);
      // Its approval was admitted and captured the settled model.
      expect(reentrant).toHaveLength(1);
      expect(persist.calls).toEqual([m("edited"), m("settled:edited")]);
      expect(form.approveCommand.canExecute()).toBe(false);

      persist.succeed(1);
      await reentrant[0]!;
      expect(form.snapshot).toEqual(m("settled:settled:edited"));
      expect(form.approveCommand.canExecute()).toBe(!strict);
    },
  );

  it("routes a command-path failure once to ApproveErrors and admits its subscriber's approval", async () => {
    const commandFailure = new Error("command persist failed");
    const awaitedFailure = new Error("awaited persist failed");
    const persist = gatedPersister();
    const form = new FormVM<Model>({
      initial: m("initial"),
      persister: persist.persister,
      validators: { value: required },
    });
    form.setModel(m("edited"));
    const before = state(form);

    const errors: unknown[] = [];
    const seenBySubscriber: Array<ReturnType<typeof state>> = [];
    const canExecuteSeen: boolean[] = [];
    // Wrapped so awaiting the hand-off does not adopt the gated approval.
    const subscriberApproval = deferred<{ readonly approval: Promise<void> }>();
    form.approveErrors.subscribe((error) => {
      errors.push(error);
      if (errors.length > 1) return;
      seenBySubscriber.push(state(form));
      canExecuteSeen.push(form.approveCommand.canExecute());
      subscriberApproval.resolve({ approval: form.approveAsync() });
    });

    form.approveCommand.execute();
    persist.fail(0, commandFailure);
    const { approval: reentrant } = await subscriberApproval.promise;

    // The failure reached ApproveErrors once; the failed approval changed nothing.
    expect(errors).toEqual([commandFailure]);
    expect(seenBySubscriber).toEqual([before]);
    expect(canExecuteSeen).toEqual([true]);
    expect(state(form)).toEqual(before);

    // The subscriber's approval was admitted. Its own failure goes to its
    // awaiter; the awaitable path emits nothing on ApproveErrors.
    expect(persist.calls).toEqual([m("edited"), m("edited")]);
    persist.fail(1, awaitedFailure);
    await expect(reentrant).rejects.toBe(awaitedFailure);
    await drainMicrotasks();
    expect(errors).toEqual([commandFailure]);
    expect(state(form)).toEqual(before);
  });

  it("admits an approval made by the awaiter that caught the failure", async () => {
    const boom = new Error("persist failed");
    const persist = gatedPersister();
    const form = new FormVM<Model>({ initial: m("initial"), persister: persist.persister });
    const signals = record(form);
    form.setModel(m("edited"));

    const first = form.approveAsync();
    persist.fail(0, boom);
    let caught: unknown = null;
    const retry: Array<Promise<void>> = [];
    try {
      await first;
    } catch (error: unknown) {
      caught = error;
      retry.push(form.approveAsync());
    }

    expect(caught).toBe(boom);
    expect(retry).toHaveLength(1);
    expect(persist.calls).toEqual([m("edited"), m("edited")]);
    persist.succeed(1);
    await retry[0]!;

    // Only the awaiter observed the failure.
    expect(signals.approveErrors).toEqual([]);
    expect(signals.approved).toEqual([m("edited")]);
    expect(form.snapshot).toEqual(m("edited"));
  });

  it("publishes every settlement notification to an idle form, in order", async () => {
    const persist = gatedPersister();
    const form = new FormVM<Model>({
      initial: m("initial"),
      persister: persist.persister,
      validators: { value: required },
      resetOnApproved: (model) => m(`reset:${model.value}`),
    });
    form.setModel(m("edited"));

    const approval = form.approveAsync();
    // A racing invalid edit, which the valid reset will clear.
    form.setModel(m(""));
    const trace: string[] = [];
    const probe = (signal: string): void => {
      trace.push(`${signal}:${String(form.approveCommand.canExecute())}`);
    };
    form.errorsChanged.subscribe(() => probe("errorsChanged"));
    form.approveCommand.canExecuteChanged.subscribe(() => probe("canExecuteChanged"));
    form.onApproved.subscribe(() => probe("onApproved"));

    persist.succeed(0);
    await approval;

    expect(trace).toEqual([
      "errorsChanged:true",
      "canExecuteChanged:true",
      "onApproved:true",
    ]);
  });
});

// ---------------------------------------------------------------------------
// FORM-034
// ---------------------------------------------------------------------------

describe("FORM-034", () => {
  it("lets setModel install a newer model while the captured value still commits", async () => {
    const hub = new MessageHub();
    const modelMessages: unknown[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) modelMessages.push(message);
    });
    const persist = gatedPersister();
    const form = new FormVM<Model>({ initial: m("initial"), persister: persist.persister, hub });
    const signals = record(form);
    form.setModel(m("captured"));
    modelMessages.length = 0;

    const approval = form.approveAsync();
    form.setModel(m("newer"));

    // The edit is not blocked: it settles and publishes during the flight.
    expect(form.model).toEqual(m("newer"));
    expect(modelMessages).toHaveLength(1);
    expect(form.approveCommand.canExecute()).toBe(false);

    persist.succeed(0);
    await approval;

    expect(form.snapshot).toEqual(m("captured"));
    expect(form.model).toEqual(m("newer"));
    expect(form.isDirty).toBe(true);
    expect(signals.approved).toEqual([m("captured")]);
    expect(modelMessages).toHaveLength(1);
  });

  it("lets deny revert to the current snapshot while the captured value still commits", async () => {
    const hub = new MessageHub();
    const denyMessages: unknown[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof FormRevertedMessage) denyMessages.push(message);
    });
    const persist = gatedPersister();
    const form = new FormVM<Model>({ initial: m("initial"), persister: persist.persister, hub });
    const signals = record(form);
    form.setModel(m("captured"));

    const approval = form.approveAsync();
    expect(form.denyCommand.canExecute()).toBe(true);
    form.denyCommand.execute();

    expect(form.model).toEqual(m("initial"));
    expect(denyMessages).toHaveLength(1);

    persist.succeed(0);
    await approval;

    expect(form.snapshot).toEqual(m("captured"));
    expect(form.model).toEqual(m("initial"));
    expect(form.isDirty).toBe(true);
    expect(signals.approved).toEqual([m("captured")]);
  });

  it.each(["setModel", "deny"] as const)(
    "keeps a configured reset authoritative over a %s made during the flight",
    async (edit) => {
      const persist = gatedPersister();
      const form = new FormVM<Model>({
        initial: m("initial"),
        persister: persist.persister,
        resetOnApproved: (model) => m(`reset:${model.value}`),
      });
      const signals = record(form);
      form.setModel(m("captured"));

      const approval = form.approveAsync();
      if (edit === "setModel") {
        form.setModel(m("newer"));
        expect(form.model).toEqual(m("newer"));
      } else {
        form.denyCommand.execute();
        expect(form.model).toEqual(m("initial"));
      }
      persist.succeed(0);
      await approval;

      expect(form.model).toEqual(m("reset:captured"));
      expect(form.snapshot).toEqual(m("reset:captured"));
      expect(form.isDirty).toBe(false);
      expect(signals.approved).toEqual([m("captured")]);
    },
  );

  const disposalCases: Array<[Entry, "succeeds" | "fails"]> = [
    ["approveAsync", "succeeds"],
    ["approveAsync", "fails"],
    ["command", "succeeds"],
    ["command", "fails"],
  ];

  it.each(disposalCases)(
    "suppresses settlement when disposed during a %s approval whose persister then %s",
    async (entry, result) => {
      const boom = new Error("persist failed after disposal");
      const persist = gatedPersister();
      let resets = 0;
      const form = new FormVM<Model>({
        initial: m("initial"),
        persister: persist.persister,
        validators: { value: required },
        // A reset that would change errors, so an unsuppressed settlement
        // would commit state and publish ErrorsChanged.
        resetOnApproved: () => {
          resets += 1;
          return m("");
        },
      });
      form.setModel(m("captured"));
      const signals = record(form);

      let approval: Promise<void> | null = null;
      if (entry === "approveAsync") {
        approval = form.approveAsync();
      } else {
        form.approveCommand.execute();
      }
      expect(persist.calls).toEqual([m("captured")]);
      const before = state(form);

      form.dispose();
      // Dispose completes the channels; nothing may follow it.
      signals.approved.length = 0;
      signals.approveErrors.length = 0;
      signals.errorsChanged.length = 0;
      signals.canExecuteChanged = 0;

      if (result === "succeeds") {
        persist.succeed(0);
      } else {
        persist.fail(0, boom);
      }
      if (approval !== null) {
        // What the awaiter observes is unchanged by admission.
        if (result === "succeeds") {
          await expect(approval).resolves.toBeUndefined();
        } else {
          await expect(approval).rejects.toBe(boom);
        }
      }
      await drainMicrotasks();

      expect(resets).toBe(0);
      expect(state(form)).toEqual(before);
      expect(signals.approved).toEqual([]);
      expect(signals.approveErrors).toEqual([]);
      expect(signals.errorsChanged).toEqual([]);
      expect(signals.canExecuteChanged).toBe(0);

      // The disposed form is inert.
      await expect(form.approveAsync()).resolves.toBeUndefined();
      form.approveCommand.execute();
      expect(persist.calls).toEqual([m("captured")]);
    },
    2_000,
  );
});
