// Unit tests for the ModeledCrudCommands currentChanged trigger (issue #1346).
// Conformance tests COMP-019..024 live in tests/conformance/modeledCrud.test.ts.
// See spec/06-composite-vm.md §7 and ADR-0049.

import { Subject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  ConfirmationDecoratorCommand,
  ModeledCrudCommands,
} from "../../src/index.js";

function build(
  getCurrent: () => object | null,
  currentChanged: Subject<void>,
  confirmed = false,
): ModeledCrudCommands<unknown, object> {
  const confirm = () => Promise.resolve(true);
  return new ModeledCrudCommands<unknown, object>({
    current: getCurrent,
    createNew: () => undefined,
    updateCurrent: () => undefined,
    deleteCurrent: () => undefined,
    ...(confirmed ? { confirmUpdate: confirm, confirmDelete: confirm } : {}),
    currentChanged,
  });
}

describe("ModeledCrudCommands currentChanged trigger", () => {
  it("raises Update and Delete canExecuteChanged on a trigger emission", () => {
    let current: object | null = null;
    const currentChanged = new Subject<void>();
    const crud = build(() => current, currentChanged);
    let updateRaised = 0;
    let deleteRaised = 0;
    crud.updateCurrentCommand.canExecuteChanged.subscribe(() => updateRaised++);
    crud.deleteCurrentCommand.canExecuteChanged.subscribe(() => deleteRaised++);

    expect(crud.updateCurrentCommand.canExecute()).toBe(false);
    expect(crud.deleteCurrentCommand.canExecute()).toBe(false);

    current = {};
    currentChanged.next();

    expect(updateRaised).toBe(1);
    expect(deleteRaised).toBe(1);
    expect(crud.updateCurrentCommand.canExecute()).toBe(true);
    expect(crud.deleteCurrentCommand.canExecute()).toBe(true);
    crud.dispose();
  });

  it("reaches confirmation-wrapped commands", () => {
    let current: object | null = null;
    const currentChanged = new Subject<void>();
    const crud = build(() => current, currentChanged, true);
    expect(crud.updateCurrentCommand).toBeInstanceOf(
      ConfirmationDecoratorCommand,
    );
    expect(crud.deleteCurrentCommand).toBeInstanceOf(
      ConfirmationDecoratorCommand,
    );
    let updateRaised = 0;
    let deleteRaised = 0;
    crud.updateCurrentCommand.canExecuteChanged.subscribe(() => updateRaised++);
    crud.deleteCurrentCommand.canExecuteChanged.subscribe(() => deleteRaised++);

    current = {};
    currentChanged.next();

    expect(updateRaised).toBe(1);
    expect(deleteRaised).toBe(1);
    expect(crud.updateCurrentCommand.canExecute()).toBe(true);
    expect(crud.deleteCurrentCommand.canExecute()).toBe(true);
    crud.dispose();
  });

  it.each([
    ["plain", false],
    ["confirmation-wrapped", true],
  ])(
    "releases the trigger subscription on dispose (%s)",
    (_name, confirmed) => {
      let current: object | null = null;
      const currentChanged = new Subject<void>();
      const crud = build(() => current, currentChanged, confirmed);
      let raised = 0;
      for (const command of [
        crud.createNewCommand,
        crud.updateCurrentCommand,
        crud.deleteCurrentCommand,
      ]) {
        command.canExecuteChanged.subscribe(() => raised++);
      }
      expect(currentChanged.observed).toBe(true);

      crud.dispose();
      const afterDispose = raised;
      current = {};
      currentChanged.next();

      expect(currentChanged.observed).toBe(false);
      expect(raised).toBe(afterDispose);
    },
  );
});
