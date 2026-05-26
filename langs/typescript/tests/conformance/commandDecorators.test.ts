// Conformance tests: CMDD-001..009 — command decorators.
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
