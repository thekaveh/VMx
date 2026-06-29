/**
 * VMX-094 regression — RelayCommand aggregates its trigger subscriptions in a
 * single root rxjs Subscription so disposal is exception-safe: a throwing child
 * unsubscribe no longer aborts the loop and strands the remaining subscriptions,
 * and the canExecuteChanged subject is always completed.
 */
import { describe, expect, it } from "vitest";
import { Observable, Subject } from "rxjs";
import { RelayCommand } from "../../src/index.js";

describe("VMX-094: RelayCommand exception-safe disposal", () => {
  it("tears down every trigger and completes even when one unsubscribe throws", () => {
    // First trigger's teardown throws; the second is a plain Subject we can
    // inspect for remaining observers.
    const throwingTrigger = new Observable<void>(() => () => {
      throw new Error("boom");
    });
    const goodTrigger = new Subject<void>();

    const cmd = new RelayCommand(null, null, [throwingTrigger, goodTrigger]);
    expect(goodTrigger.observers.length).toBe(1);

    let completed = false;
    cmd.canExecuteChanged.subscribe({ complete: () => (completed = true) });

    // rxjs aggregates the child-teardown error and rethrows it, but only AFTER
    // tearing down every child — so the good trigger is still unsubscribed.
    expect(() => cmd.dispose()).toThrow();

    expect(completed).toBe(true);
    expect(goodTrigger.observers.length).toBe(0);
  });

  it("dispose is idempotent", () => {
    const cmd = RelayCommand.builder().task(() => {}).build();
    expect(() => {
      cmd.dispose();
      cmd.dispose();
    }).not.toThrow();
  });
});
