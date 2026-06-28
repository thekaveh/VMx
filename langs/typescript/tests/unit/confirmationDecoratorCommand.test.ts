// Unit tests for ConfirmationDecoratorCommand — fire-and-forget safety.
// Conformance-level tests live in tests/conformance/commandDecorators.test.ts.

import { describe, expect, it } from "vitest";
import { ConfirmationDecoratorCommand, RelayCommand } from "../../src/index.js";

describe("ConfirmationDecoratorCommand – execute()", () => {
  it("does not surface an unhandled rejection when the confirm delegate rejects", async () => {
    let innerRan = false;
    const inner = RelayCommand.builder()
      .task(() => {
        innerRan = true;
      })
      .build();
    const cmd = new ConfirmationDecoratorCommand(inner, () =>
      Promise.reject(new Error("nope")),
    );

    cmd.execute(); // a bare `void` here used to crash Node >= 15

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(innerRan).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Error channel (VMX-009)
//
// execute() is fire-and-forget across an async confirm gate, so it cannot
// propagate the way the base RelayCommand's task does. Previously BOTH a
// rejecting confirm delegate AND a throwing inner command were swallowed
// (`.catch(() => undefined)`). They must now be OBSERVABLE on the errors
// channel. Await executeAsync() to observe them inline.
// ---------------------------------------------------------------------------

describe("ConfirmationDecoratorCommand – error channel (VMX-009)", () => {
  it("surfaces a rejecting confirm delegate on errors instead of swallowing it", async () => {
    const boom = new Error("nope");
    const errors: unknown[] = [];
    const inner = RelayCommand.builder()
      .task(() => undefined)
      .build();
    const cmd = new ConfirmationDecoratorCommand(inner, () => Promise.reject(boom));
    cmd.errors.subscribe((e) => errors.push(e));

    cmd.execute();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(errors).toEqual([boom]);
  });

  it("surfaces a throwing inner command on errors", async () => {
    const boom = new Error("inner boom");
    const errors: unknown[] = [];
    const inner = RelayCommand.builder()
      .task(() => {
        throw boom;
      })
      .build();
    const cmd = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true));
    cmd.errors.subscribe((e) => errors.push(e));

    cmd.execute();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(errors).toEqual([boom]);
  });
});

describe("Command decorators – dispose parity", () => {
  it("dispose is idempotent on all three decorators", async () => {
    const { CompositeCommand, DecoratorCommand } = await import("../../src/index.js");
    const inner = RelayCommand.builder().task(() => undefined).build();

    const deco = new DecoratorCommand(inner);
    deco.dispose();
    deco.dispose();

    const composite = new CompositeCommand(inner);
    composite.dispose();
    composite.dispose();

    const confirm = new ConfirmationDecoratorCommand(inner, () => Promise.resolve(true));
    confirm.dispose();
    confirm.dispose();
  });
});
