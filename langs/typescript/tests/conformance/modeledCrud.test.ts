// Conformance tests: COMP-019..024 — modeled CRUD commands.
// See spec/06-composite-vm.md §Modeled CRUD and ADR-0016.

import { describe, expect, it } from "vitest";

import {
  ConfirmationDecoratorCommand,
  ModeledCrudCommands,
} from "../../src/index.js";

describe("COMP-019", () => {
  it("CreateNewCommand invokes create-new action", () => {
    const log: string[] = [];
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => null,
      createNew: () => log.push("create"),
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
    });
    crud.createNewCommand.execute();
    expect(log).toEqual(["create"]);
  });
});

describe("COMP-020", () => {
  it("UpdateCurrentCommand invokes update with current VM", () => {
    const log: object[] = [];
    const vm1 = {};
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: (vm) => log.push(vm),
      deleteCurrent: () => undefined,
    });
    crud.updateCurrentCommand.execute();
    expect(log).toEqual([vm1]);
  });
});

describe("COMP-021", () => {
  it("UpdateCurrentCommand.canExecute false when current is null", () => {
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => null,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
    });
    expect(crud.updateCurrentCommand.canExecute()).toBe(false);
  });
});

describe("COMP-022", () => {
  it("DeleteCurrentCommand invokes delete with current VM", () => {
    const log: object[] = [];
    const vm1 = {};
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: (vm) => log.push(vm),
    });
    crud.deleteCurrentCommand.execute();
    expect(log).toEqual([vm1]);
  });
});

describe("COMP-023", () => {
  it("DeleteCurrentCommand.canExecute false when current is null", () => {
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => null,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
    });
    expect(crud.deleteCurrentCommand.canExecute()).toBe(false);
  });
});

describe("COMP-024", () => {
  it("DeleteCurrentCommand confirm gate", async () => {
    const log: object[] = [];
    const vm1 = {};

    const crudNo = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: (vm) => log.push(vm),
      confirmDelete: () => Promise.resolve(false),
    });
    expect(crudNo.deleteCurrentCommand).toBeInstanceOf(ConfirmationDecoratorCommand);
    await (crudNo.deleteCurrentCommand as ConfirmationDecoratorCommand).executeAsync();
    expect(log).toEqual([]);

    const crudYes = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: (vm) => log.push(vm),
      confirmDelete: () => Promise.resolve(true),
    });
    await (crudYes.deleteCurrentCommand as ConfirmationDecoratorCommand).executeAsync();
    expect(log).toEqual([vm1]);
  });
});

// Unit-style assertions for the dispose path (not a conformance ID — kept
// adjacent to the COMP-024 confirm tests for proximity to the helper).
describe("ModeledCrudCommands.dispose", () => {
  it("disposes inner RelayCommands and is idempotent", () => {
    const vm1 = {};
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
    });

    expect(crud.createNewCommand.canExecute()).toBe(true);
    expect(crud.updateCurrentCommand.canExecute()).toBe(true);
    expect(crud.deleteCurrentCommand.canExecute()).toBe(true);

    expect(() => crud.dispose()).not.toThrow();
    expect(() => crud.dispose()).not.toThrow();
  });

  it("completes inner canExecuteChanged after dispose", () => {
    const vm1 = {};
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
    });

    let completions = 0;
    const sub = (cmd: { canExecuteChanged: { subscribe: (o: { complete: () => void }) => unknown } }) =>
      cmd.canExecuteChanged.subscribe({
        complete: () => {
          completions++;
        },
      });

    sub(crud.createNewCommand);
    sub(crud.updateCurrentCommand);
    sub(crud.deleteCurrentCommand);

    crud.dispose();
    expect(completions).toBe(3);
  });

  it("is idempotent with confirmation wrappers present", () => {
    const vm1 = {};
    const crud = new ModeledCrudCommands<unknown, object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: () => undefined,
      confirmUpdate: () => Promise.resolve(true),
      confirmDelete: () => Promise.resolve(true),
    });

    expect(crud.updateCurrentCommand).toBeInstanceOf(ConfirmationDecoratorCommand);
    expect(crud.deleteCurrentCommand).toBeInstanceOf(ConfirmationDecoratorCommand);
    // createNew has no confirm hook by spec.
    expect(crud.createNewCommand).not.toBeInstanceOf(ConfirmationDecoratorCommand);

    expect(() => crud.dispose()).not.toThrow();
    expect(() => crud.dispose()).not.toThrow();
  });
});
