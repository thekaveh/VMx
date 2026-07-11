/**
 * ViewModelType enum and IComponentVM interface.
 *
 * See spec/01-concepts.md §IComponentVM baseline.
 */
import type { Observable } from "rxjs";
import type { ConstructionStatus } from "../lifecycle/status.js";
import type { ICommand } from "../commands/types.js";
import type { IMessageHub } from "../services/messageHub.js";

export enum ViewModelType {
  Component = "Component",
  ReadOnlyComponent = "ReadOnlyComponent",
  Composite = "Composite",
  Group = "Group",
  Aggregate = "Aggregate",
}

/** Shared baseline every VMx viewmodel exposes. */
export interface IComponentVM {
  readonly name: string;
  readonly hint: string;
  readonly type: ViewModelType;
  readonly isCurrent: boolean;
  readonly isConstructed: boolean;
  readonly status: ConstructionStatus;
  readonly hub: IMessageHub;

  readonly selectCommand: ICommand;
  readonly deselectCommand: ICommand;
  readonly selectNextCommand: ICommand;
  readonly selectPreviousCommand: ICommand;
  readonly reconstructCommand: ICommand;

  canConstruct(): boolean;
  construct(): void;
  canDestruct(): boolean;
  destruct(): void;
  canReconstruct(): boolean;
  reconstruct(): void;
  dispose(): void;

  canSelect(): boolean;
  select(): void;
  canDeselect(): boolean;
  deselect(): void;

  /** INPC-equivalent: emits property names when properties change. */
  readonly propertyChanged: Observable<string>;
}

/**
 * Modeled variant adds a typed Model property. Per spec/09-forwarding.md §1 the
 * modeled component's `model` is settable (read-only only on the readonly
 * component); the forwarding decorator must therefore delegate the setter too.
 */
export interface IComponentVMOf<M> extends IComponentVM {
  model: M;
  readonly modeledHint: string;
}
