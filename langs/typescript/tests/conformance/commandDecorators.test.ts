// Conformance tests: CMDD-001..013 — command decorators.
// See spec/04-commands.md §Decorators and ADR-0012.

import { Subject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  CompositeCommand,
  ConfirmationDecoratorCommand,
  DecoratorCommand,
  RelayCommand,
  type ICommand,
} from "../../src/index.js";

function buildRecording(
  log: string[],
  label: string,
  predicate: boolean,
): ICommand {
  return RelayCommand.builder()
    .task(() => log.push(label))
    .predicate(() => predicate)
    .build();
}

describe("CMDD-001", () => {
  it("CompositeCommand.canExecute is OR over inner commands", () => {
    const log: string[] = [];
    const c1 = buildRecording(log, "c1", false);
    const c2 = buildRecording(log, "c2", true);
    const composite = new CompositeCommand(c1, c2);
    expect(composite.canExecute()).toBe(true);

    const c3 = buildRecording(log, "c3", false);
    const c4 = buildRecording(log, "c4", false);
    const compositeFalse = new CompositeCommand(c3, c4);
    expect(compositeFalse.canExecute()).toBe(false);
  });
});

describe("CMDD-002", () => {
  it("CompositeCommand.execute invokes only enabled inner commands", () => {
    const log: string[] = [];
    const c1 = buildRecording(log, "c1", true);
    const c2 = buildRecording(log, "c2", false);
    const c3 = buildRecording(log, "c3", true);
    const composite = new CompositeCommand(c1, c2, c3);
    composite.execute();
    expect(log).toEqual(["c1", "c3"]);
  });
});

describe("CMDD-003", () => {
  it("CompositeCommand propagates inner canExecuteChanged", () => {
    const trigger = new Subject<void>();
    const c1 = RelayCommand.builder()
      .task(() => undefined)
      .triggers(trigger.asObservable())
      .build();
    const composite = new CompositeCommand(c1);
    let fired = 0;
    composite.canExecuteChanged.subscribe(() => fired++);
    trigger.next();
    expect(fired).toBe(1);
  });
});

describe("CMDD-004", () => {
  it("DecoratorCommand.canExecute is inner AND extra-predicate", () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);
    const extraFalse = new DecoratorCommand(inner, { extraPredicate: () => false });
    const extraTrue = new DecoratorCommand(inner, { extraPredicate: () => true });
    const innerFalse = buildRecording(log, "innerF", false);
    const extraTrueInnerFalse = new DecoratorCommand(innerFalse, {
      extraPredicate: () => true,
    });
    expect(extraFalse.canExecute()).toBe(false);
    expect(extraTrue.canExecute()).toBe(true);
    expect(extraTrueInnerFalse.canExecute()).toBe(false);
  });
});

describe("CMDD-005", () => {
  it("DecoratorCommand.execute invokes pre, inner, post in order", () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);
    const dec = new DecoratorCommand(inner, {
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
    });
    dec.execute();
    expect(log).toEqual(["pre", "inner", "post"]);
  });
});

describe("CMDD-006", () => {
  it("DecoratorCommand.execute is no-op when canExecute is false", () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);
    const dec = new DecoratorCommand(inner, {
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
      extraPredicate: () => false,
    });
    dec.execute();
    expect(log).toEqual([]);
  });
});

describe("CMDD-007", () => {
  it("ConfirmationDecoratorCommand invokes inner only when confirmed", async () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);
    const yes = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true));
    await yes.executeAsync();
    expect(log).toEqual(["inner"]);

    log.length = 0;
    const no = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(false));
    await no.executeAsync();
    expect(log).toEqual([]);
  });
});

describe("CMDD-008", () => {
  it("ConfirmationDecoratorCommand.canExecute delegates to inner", () => {
    const log: string[] = [];
    const innerT = buildRecording(log, "x", true);
    const innerF = buildRecording(log, "x", false);
    const confT = new ConfirmationDecoratorCommand(innerT, () => Promise.resolve(true));
    const confF = new ConfirmationDecoratorCommand(innerF, () => Promise.resolve(true));
    expect(confT.canExecute()).toBe(true);
    expect(confF.canExecute()).toBe(false);
  });
});

describe("CMDD-009", () => {
  it("Decorators compose (decorator of confirmation of relay)", async () => {
    const log: string[] = [];
    const relay = buildRecording(log, "relay", true);
    const conf = new ConfirmationDecoratorCommand(relay, () =>
      Promise.resolve(true),
    );
    const dec = new DecoratorCommand(conf);

    expect(dec.canExecute()).toBe(true);
    await conf.executeAsync();
    expect(log).toEqual(["relay"]);
  });
});

describe("CMDD-010", () => {
  // execute() is fire-and-forget across the async confirm gate, so a rejecting
  // confirm delegate or a throwing inner command cannot propagate to the caller
  // the way RelayCommand's task does. They MUST be surfaced on `errors` instead
  // of being swallowed (VMX-009).
  it("surfaces a rejecting confirm delegate and a throwing inner on the errors channel", async () => {
    // (a) the confirm delegate rejects
    const confirmBoom = new Error("confirm rejected");
    const rejectErrors: unknown[] = [];
    const inner = buildRecording([], "inner", true);
    const rejecting = new ConfirmationDecoratorCommand(inner, () =>
      Promise.reject(confirmBoom),
    );
    rejecting.errors.subscribe((e) => rejectErrors.push(e));

    rejecting.execute(); // fire-and-forget
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(rejectErrors).toEqual([confirmBoom]);

    // (b) the inner command throws once confirmed
    const innerBoom = new Error("inner boom");
    const innerErrors: unknown[] = [];
    const throwing = RelayCommand.builder()
      .task(() => {
        throw innerBoom;
      })
      .predicate(() => true)
      .build();
    const confirming = new ConfirmationDecoratorCommand(throwing, () =>
      Promise.resolve(true),
    );
    confirming.errors.subscribe((e) => innerErrors.push(e));

    confirming.execute();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(innerErrors).toEqual([innerBoom]);
  });
});

// Deferred confirmation for CMDD-012: resolves or rejects on demand.
function deferred(): {
  promise: Promise<boolean>;
  resolve: (value: boolean) => void;
  reject: (error: unknown) => void;
} {
  let resolve!: (value: boolean) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<boolean>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("CMDD-011", () => {
  it("disposed composite and decorator commands are inert and leave inner commands usable", () => {
    const log: string[] = [];
    const a = buildRecording(log, "a", true);
    const b = buildRecording(log, "b", true);
    const composite = new CompositeCommand(a, b);
    composite.dispose();
    composite.dispose();

    expect(composite.canExecute()).toBe(false);
    composite.execute();
    expect(log).toEqual([]);

    const inner = buildRecording(log, "inner", true);
    const decorator = new DecoratorCommand(inner, {
      extraPredicate: () => {
        log.push("predicate");
        return true;
      },
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
    });
    decorator.dispose();
    decorator.dispose();

    expect(decorator.canExecute()).toBe(false);
    decorator.execute();
    expect(log).toEqual([]);

    // The inner commands were not disposed.
    a.execute();
    inner.execute();
    expect(log).toEqual(["a", "inner"]);
  });

  it("wrapper disposal leaves the inner canExecuteChanged stream to its owner", () => {
    const inner = RelayCommand.builder().task(() => {}).build();
    let notifications = 0;
    let completed = false;
    inner.canExecuteChanged.subscribe({
      next: () => notifications++,
      complete: () => {
        completed = true;
      },
    });

    for (const wrapper of [
      new CompositeCommand(inner),
      new DecoratorCommand(inner),
      new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true)),
    ]) {
      wrapper.dispose();
    }
    inner.raiseCanExecuteChanged();

    expect(notifications).toBe(1);
    expect(completed).toBe(false);
  });
});

describe("CMDD-012", () => {
  it("a disposed confirmation decorator never consults confirm", async () => {
    const log: string[] = [];
    let confirms = 0;
    const decorator = new ConfirmationDecoratorCommand(buildRecording(log, "inner", true), () => {
      confirms += 1;
      return Promise.resolve(true);
    });
    decorator.dispose();
    decorator.dispose();

    expect(decorator.canExecute()).toBe(false);
    decorator.execute();
    await decorator.executeAsync();
    await settle();

    expect(confirms).toBe(0);
    expect(log).toEqual([]);
  });

  it.each([
    ["true", (d: ReturnType<typeof deferred>) => d.resolve(true)],
    ["false", (d: ReturnType<typeof deferred>) => d.resolve(false)],
    ["faulted", (d: ReturnType<typeof deferred>) => d.reject(new Error("confirm failed"))],
  ])(
    "a confirmation resolving %s after disposal runs nothing and emits nothing",
    async (_, settleWith) => {
      const log: string[] = [];
      const inner = buildRecording(log, "inner", true);
      const pending = deferred();
      const decorator = new ConfirmationDecoratorCommand(inner, () => pending.promise);
      const errors: unknown[] = [];
      let completed = false;
      decorator.errors.subscribe({
        next: (e) => errors.push(e),
        complete: () => (completed = true),
      });

      decorator.execute();
      decorator.dispose();
      settleWith(pending);
      await settle();

      expect(log).toEqual([]);
      expect(errors).toEqual([]);
      expect(completed).toBe(true);
      inner.execute();
      expect(log).toEqual(["inner"]);
    },
  );
});

describe("CMDD-013", () => {
  it("a composite runs no later child after an earlier child disposes it", () => {
    const log: string[] = [];
    let composite: CompositeCommand | null = null;
    const disposer = RelayCommand.builder()
      .task(() => {
        log.push("first");
        composite?.dispose();
      })
      .build();
    composite = new CompositeCommand(disposer, buildRecording(log, "second", true));

    composite.execute();

    expect(log).toEqual(["first"]);
  });

  it("a decorator disposed by its extra predicate runs neither hook nor inner", () => {
    const log: string[] = [];
    let decorator: DecoratorCommand | null = null;
    decorator = new DecoratorCommand(buildRecording(log, "inner", true), {
      extraPredicate: () => {
        decorator?.dispose();
        return true;
      },
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
    });

    decorator.execute();

    expect(log).toEqual([]);
  });

  it("a decorator disposed by its pre-action skips the inner but still runs post once", () => {
    const log: string[] = [];
    let decorator: DecoratorCommand | null = null;
    decorator = new DecoratorCommand(buildRecording(log, "inner", true), {
      preExecute: () => {
        log.push("pre");
        decorator?.dispose();
      },
      postExecute: () => log.push("post"),
    });

    decorator.execute();
    decorator.execute();

    expect(log).toEqual(["pre", "post"]);
  });

  it("an admitted pair whose inner throws still runs post once and rethrows", () => {
    const log: string[] = [];
    const boom = new Error("inner boom");
    const throwing = RelayCommand.builder()
      .task(() => {
        throw boom;
      })
      .build();
    const decorator = new DecoratorCommand(throwing, {
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
    });

    expect(() => decorator.execute()).toThrow(boom);
    expect(log).toEqual(["pre", "post"]);
  });
});

// ---------------------------------------------------------------------------
// DecoratorCommand exception handling (unit; not a conformance ID)
// ---------------------------------------------------------------------------

describe("DecoratorCommand postExecute on throw", () => {
  it("runs postExecute even when inner throws", () => {
    const log: string[] = [];
    const throwing = RelayCommand.builder()
      .task(() => {
        throw new Error("boom");
      })
      .predicate(() => true)
      .build();

    const dec = new DecoratorCommand(throwing, {
      preExecute: () => log.push("pre"),
      postExecute: () => log.push("post"),
    });

    expect(() => dec.execute()).toThrow("boom");
    expect(log).toEqual(["pre", "post"]);
  });
});
