/**
 * ICommand interfaces for the VMx command contract.
 *
 * See spec/04-commands.md.
 */
import type { Observable } from "rxjs";

export interface ICommand {
  canExecute(): boolean;
  execute(): void;
  readonly canExecuteChanged: Observable<void>;
}

export interface ICommandOf<T> {
  canExecute(parameter: T): boolean;
  execute(parameter: T): void;
  readonly canExecuteChanged: Observable<void>;
}
