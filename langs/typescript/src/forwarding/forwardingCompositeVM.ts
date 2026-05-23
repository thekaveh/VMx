/**
 * ForwardingCompositeVM<VM> — forwarding decorator for CompositeVMBase<VM>.
 *
 * Delegates every member — including collection surface, current, and selection
 * methods — to the wrapped composite by default.
 *
 * See spec/09-forwarding.md §ForwardingCompositeVM.
 */
import type { Observable } from "rxjs";
import type { ConstructionStatus } from "../lifecycle/status.js";
import type { ViewModelType } from "../components/types.js";
import type { ICommand } from "../commands/types.js";
import type { CompositeVMBase } from "../composites/compositeVMBase.js";
import type { ComponentVMBase } from "../components/componentVMBase.js";
import type { CollectionChangedEvent } from "../collections/collectionChangedEvent.js";
import type { BatchUpdateHandle } from "../collections/batchUpdateHandle.js";

export class ForwardingCompositeVM<VM extends ComponentVMBase> {
  protected readonly _wrapped: CompositeVMBase<VM>;

  constructor(wrapped: CompositeVMBase<VM>) {
    this._wrapped = wrapped;
  }

  get name(): string { return this._wrapped.name; }
  get hint(): string { return this._wrapped.hint; }
  get type(): ViewModelType { return this._wrapped.type; }
  get isCurrent(): boolean { return this._wrapped.isCurrent; }
  get isConstructed(): boolean { return this._wrapped.isConstructed; }
  get status(): ConstructionStatus { return this._wrapped.status; }
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

  get current(): VM | null { return this._wrapped.current; }
  set current(value: VM | null) { this._wrapped.current = value; }

  selectComponent(vm: VM): void { this._wrapped.selectComponent(vm); }
  deselectComponent(vm: VM): void { this._wrapped.deselectComponent(vm); }
  canSelectComponent(vm: VM): boolean { return this._wrapped.canSelectComponent(vm); }

  get collectionChanged(): Observable<CollectionChangedEvent> { return this._wrapped.collectionChanged; }
  get count(): number { return this._wrapped.count; }

  [Symbol.iterator](): Iterator<VM> { return this._wrapped[Symbol.iterator](); }

  at(index: number): VM { return this._wrapped.at(index); }

  add(item: VM): void { this._wrapped.add(item); }
  insert(index: number, item: VM): void { this._wrapped.insert(index, item); }
  remove(item: VM): boolean { return this._wrapped.remove(item); }
  removeAt(index: number): void { this._wrapped.removeAt(index); }
  clear(): void { this._wrapped.clear(); }
  batchUpdate(): BatchUpdateHandle { return this._wrapped.batchUpdate(); }
}
