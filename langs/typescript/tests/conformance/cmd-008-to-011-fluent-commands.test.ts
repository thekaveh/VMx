// Conformance tests: CMD-008..CMD-011 — fluent command extension methods.
// See spec/04-commands.md §9 and ADR-0027.

import { describe, expect, it } from "vitest";
import {
  CompositeCommand,
  ConfirmationDecoratorCommand,
  DecoratorCommand,
} from "../../src/commands/index.js";
import {
  confirm,
  precedeWith,
  succeedWith,
  wrapWith,
} from "../../src/commands/fluent.js";
import type { ICommand } from "../../src/commands/types.js";
import { NEVER } from "rxjs";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildRecording(
  log: string[],
  label: string,
  enabled: boolean,
): ICommand {
  return {
    canExecute: () => enabled,
    execute: () => {
      log.push(label);
    },
    canExecuteChanged: NEVER,
  };
}

// CMD-008 — confirm(delegate) equivalent to explicit ConfirmationDecoratorCommand
describe("CMD-008", () => {
  it("confirm(delegate) produces an equivalent ConfirmationDecoratorCommand", async () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);

    const confirmYes = () => Promise.resolve(true);
    const confirmNo = () => Promise.resolve(false);

    // fluent form — accepted
    const result = confirm(inner, confirmYes);
    expect(result).toBeInstanceOf(ConfirmationDecoratorCommand);
    expect(result.canExecute()).toBe(true);
    await result.executeAsync();
    expect(log).toEqual(["inner"]);

    // fluent form — rejected
    log.length = 0;
    const resultNo = confirm(inner, confirmNo);
    await resultNo.executeAsync();
    expect(log).toEqual([]);

    // equivalent canExecute to explicit constructor
    const explicit = new ConfirmationDecoratorCommand(inner, confirmYes);
    expect(result.canExecute()).toBe(explicit.canExecute());
  });
});

// CMD-009 — precedeWith(other) equivalent to CompositeCommand(other, receiver)
describe("CMD-009", () => {
  it("precedeWith(other) produces CompositeCommand(other, receiver): other runs first", () => {
    const log: string[] = [];
    const receiver = buildRecording(log, "receiver", true);
    const other = buildRecording(log, "other", true);

    const result = precedeWith(receiver, other);
    expect(result).toBeInstanceOf(CompositeCommand);

    result.execute();
    expect(log).toEqual(["other", "receiver"]);
  });
});

// CMD-010 — succeedWith(other) equivalent to CompositeCommand(receiver, other)
describe("CMD-010", () => {
  it("succeedWith(other) produces CompositeCommand(receiver, other): receiver runs first", () => {
    const log: string[] = [];
    const receiver = buildRecording(log, "receiver", true);
    const other = buildRecording(log, "other", true);

    const result = succeedWith(receiver, other);
    expect(result).toBeInstanceOf(CompositeCommand);

    result.execute();
    expect(log).toEqual(["receiver", "other"]);
  });
});

// CMD-011 — wrapWith(predicate?, pre?, post?) equivalent to explicit DecoratorCommand
describe("CMD-011", () => {
  it("wrapWith() produces a DecoratorCommand with optional predicate/pre/post", () => {
    const log: string[] = [];
    const inner = buildRecording(log, "inner", true);

    // all-undefined → transparent decorator
    const allUndefined = wrapWith(inner);
    expect(allUndefined).toBeInstanceOf(DecoratorCommand);
    expect(allUndefined.canExecute()).toBe(true);
    allUndefined.execute();
    expect(log).toEqual(["inner"]);

    // with pre/post/predicate
    log.length = 0;
    const decorated = wrapWith(
      inner,
      () => true,
      () => log.push("pre"),
      () => log.push("post"),
    );
    expect(decorated).toBeInstanceOf(DecoratorCommand);
    decorated.execute();
    expect(log).toEqual(["pre", "inner", "post"]);

    // predicate returning false blocks execution
    log.length = 0;
    const blocked = wrapWith(inner, () => false);
    expect(blocked.canExecute()).toBe(false);
    blocked.execute();
    expect(log).toEqual([]);
  });
});
