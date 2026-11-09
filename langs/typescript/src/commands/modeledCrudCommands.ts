/**
 * ModeledCrudCommands — Create / UpdateCurrent / DeleteCurrent helper.
 *
 * See spec/06-composite-vm.md §Modeled CRUD commands and ADR-0016.
 */
import type { Observable } from "rxjs";

import {
  ConfirmationDecoratorCommand,
  type ConfirmDelegate,
} from "./confirmationDecoratorCommand.js";
import { RelayCommand } from "./relayCommand.js";
import type { ICommand } from "./types.js";

// The `M` (model) type parameter is a phantom: the helper only manipulates
// VMs at runtime, but exposing `M` at the type boundary keeps the public
// signature symmetrical with C# `ModeledCrudCommands<M, VM>` and Python
// `ModeledCrudCommands[M, VM]` per ADR-0006 / ADR-0016.
export interface ModeledCrudCommandsOptions<M, VM> {
  current: () => VM | null | undefined;
  createNew: () => void;
  updateCurrent: (vm: VM) => void;
  deleteCurrent: (vm: VM) => void;
  confirmUpdate?: ConfirmDelegate;
  confirmDelete?: ConfirmDelegate;
  /**
   * Optional trigger that fires when the value of `current` changes, typically
   * the owning composite's current-child stream. When supplied, it is wired as
   * a trigger on the Update and Delete commands, so their `canExecuteChanged`
   * fires on a selection change and a bound control does not keep a stale
   * enabled state (spec/06 §7, ADR-0049). Use it when the commands are bound
   * to UI.
   */
  currentChanged?: Observable<unknown>;
  /**
   * @internal Phantom field to pin the `M` type parameter so it is not erased
   * by the TypeScript compiler. Never read at runtime; always undefined.
   */
  _model?: M;
}

export class ModeledCrudCommands<M, VM> {
  readonly createNewCommand: ICommand;
  readonly updateCurrentCommand: ICommand;
  readonly deleteCurrentCommand: ICommand;

  // Inner RelayCommands hold trigger subscriptions; track them so dispose()
  // can tear them down (parity with C# ModeledCrudCommands.Dispose).
  readonly #innerRelays: readonly RelayCommand[];
  #disposed = false;

  constructor(opts: ModeledCrudCommandsOptions<M, VM>) {
    const create = RelayCommand.builder().task(opts.createNew).build();
    let updateBuilder = RelayCommand.builder()
      .task(() => {
        const c = opts.current();
        if (c) opts.updateCurrent(c);
      })
      .predicate(() => opts.current() != null);
    let removeBuilder = RelayCommand.builder()
      .task(() => {
        const c = opts.current();
        if (c) opts.deleteCurrent(c);
      })
      .predicate(() => opts.current() != null);
    if (opts.currentChanged) {
      updateBuilder = updateBuilder.triggers(opts.currentChanged);
      removeBuilder = removeBuilder.triggers(opts.currentChanged);
    }
    const update = updateBuilder.build();
    const remove = removeBuilder.build();

    this.#innerRelays = [create, update, remove];

    this.createNewCommand = create;
    this.updateCurrentCommand = opts.confirmUpdate
      ? new ConfirmationDecoratorCommand(update, opts.confirmUpdate)
      : update;
    this.deleteCurrentCommand = opts.confirmDelete
      ? new ConfirmationDecoratorCommand(remove, opts.confirmDelete)
      : remove;
  }

  /**
   * Dispose the inner RelayCommands and any confirmation wrappers. Idempotent.
   *
   * The public update/delete commands may be `ConfirmationDecoratorCommand`
   * wrappers (when `confirmUpdate` / `confirmDelete` are supplied). Each wrapper
   * owns an `errors` Subject whose contract is to complete on dispose, so the
   * wrappers are disposed here alongside the inner relays (parity with
   * C#/Python). When no confirm hook is supplied the public command is the inner
   * relay itself, already covered.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    const targets: { dispose(): void }[] = [...this.#innerRelays];
    for (const cmd of [this.updateCurrentCommand, this.deleteCurrentCommand]) {
      if (cmd instanceof ConfirmationDecoratorCommand) targets.push(cmd);
    }
    for (const cmd of targets) cmd.dispose();
  }
}
