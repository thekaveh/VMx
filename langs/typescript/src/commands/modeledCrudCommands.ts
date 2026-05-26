/**
 * ModeledCrudCommands — Create / UpdateCurrent / DeleteCurrent helper.
 *
 * See spec/06-composite-vm.md §Modeled CRUD commands and ADR-0016.
 */
import {
  ConfirmationDecoratorCommand,
  type ConfirmDelegate,
} from "./confirmationDecoratorCommand.js";
import { RelayCommand } from "./relayCommand.js";
import type { ICommand } from "./types.js";

export interface ModeledCrudCommandsOptions<VM> {
  current: () => VM | null | undefined;
  createNew: () => void;
  updateCurrent: (vm: VM) => void;
  deleteCurrent: (vm: VM) => void;
  confirmUpdate?: ConfirmDelegate;
  confirmDelete?: ConfirmDelegate;
}

export class ModeledCrudCommands<VM> {
  readonly createNewCommand: ICommand;
  readonly updateCurrentCommand: ICommand;
  readonly deleteCurrentCommand: ICommand;

  constructor(opts: ModeledCrudCommandsOptions<VM>) {
    const create = RelayCommand.builder().task(opts.createNew).build();
    const update = RelayCommand.builder()
      .task(() => {
        const c = opts.current();
        if (c) opts.updateCurrent(c);
      })
      .predicate(() => opts.current() != null)
      .build();
    const remove = RelayCommand.builder()
      .task(() => {
        const c = opts.current();
        if (c) opts.deleteCurrent(c);
      })
      .predicate(() => opts.current() != null)
      .build();

    this.createNewCommand = create;
    this.updateCurrentCommand = opts.confirmUpdate
      ? new ConfirmationDecoratorCommand(update, opts.confirmUpdate)
      : update;
    this.deleteCurrentCommand = opts.confirmDelete
      ? new ConfirmationDecoratorCommand(remove, opts.confirmDelete)
      : remove;
  }
}
