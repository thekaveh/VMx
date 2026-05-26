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
    const crud = new ModeledCrudCommands<object>({
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
    const crud = new ModeledCrudCommands<object>({
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
    const crud = new ModeledCrudCommands<object>({
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
    const crud = new ModeledCrudCommands<object>({
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
    const crud = new ModeledCrudCommands<object>({
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

    const crudNo = new ModeledCrudCommands<object>({
      current: () => vm1,
      createNew: () => undefined,
      updateCurrent: () => undefined,
      deleteCurrent: (vm) => log.push(vm),
      confirmDelete: () => Promise.resolve(false),
    });
    expect(crudNo.deleteCurrentCommand).toBeInstanceOf(ConfirmationDecoratorCommand);
    await (crudNo.deleteCurrentCommand as ConfirmationDecoratorCommand).executeAsync();
    expect(log).toEqual([]);

    const crudYes = new ModeledCrudCommands<object>({
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
