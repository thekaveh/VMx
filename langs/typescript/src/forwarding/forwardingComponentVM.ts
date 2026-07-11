/**
 * ForwardingComponentVM<M> — forwarding decorator for IComponentVMOf<M>.
 *
 * Every member delegates to the wrapped VM by default.
 * Subclasses override individual members to customize behavior.
 *
 * See spec/09-forwarding.md §ForwardingComponentVM.
 */
import type { Observable } from "rxjs";
import type { ConstructionStatus } from "../lifecycle/status.js";
import type { IComponentVMOf, ViewModelType } from "../components/types.js";
import type { ICommand } from "../commands/types.js";
import type { IMessageHub } from "../services/messageHub.js";

export class ForwardingComponentVM<M> implements IComponentVMOf<M> {
  protected readonly _wrapped: IComponentVMOf<M>;

  constructor(wrapped: IComponentVMOf<M>) {
    this._wrapped = wrapped;
  }

  get name(): string { return this._wrapped.name; }
  get hint(): string { return this._wrapped.hint; }
  get type(): ViewModelType { return this._wrapped.type; }
  get isCurrent(): boolean { return this._wrapped.isCurrent; }
  get isConstructed(): boolean { return this._wrapped.isConstructed; }
  get status(): ConstructionStatus { return this._wrapped.status; }
  get hub(): IMessageHub { return this._wrapped.hub; }
  get model(): M { return this._wrapped.model; }
  // Delegate the model setter too (spec/09-forwarding.md §1 — the decorator
  // forwards every member; the modeled component's `model` is settable). Matches
  // C#/Python/Swift ForwardingComponentVM and TS ForwardingCompositeVM.set current.
  set model(value: M) { this._wrapped.model = value; }
  get modeledHint(): string { return this._wrapped.modeledHint; }
  get propertyChanged(): Observable<string> { return this._wrapped.propertyChanged; }
  get selectCommand(): ICommand { return this._wrapped.selectCommand; }
  get deselectCommand(): ICommand { return this._wrapped.deselectCommand; }
  get selectNextCommand(): ICommand { return this._wrapped.selectNextCommand; }
  get selectPreviousCommand(): ICommand { return this._wrapped.selectPreviousCommand; }
  get reconstructCommand(): ICommand { return this._wrapped.reconstructCommand; }

  canConstruct(): boolean { return this._wrapped.canConstruct(); }
  construct(): void { this._wrapped.construct(); }
  canDestruct(): boolean { return this._wrapped.canDestruct(); }
  destruct(): void { this._wrapped.destruct(); }
  canReconstruct(): boolean { return this._wrapped.canReconstruct(); }
  reconstruct(): void { this._wrapped.reconstruct(); }
  dispose(): void { this._wrapped.dispose(); }
  canSelect(): boolean { return this._wrapped.canSelect(); }
  select(): void { this._wrapped.select(); }
  canDeselect(): boolean { return this._wrapped.canDeselect(); }
  deselect(): void { this._wrapped.deselect(); }
}
