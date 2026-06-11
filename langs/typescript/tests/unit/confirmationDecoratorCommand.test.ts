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
