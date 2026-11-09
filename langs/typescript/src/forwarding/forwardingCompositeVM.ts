/**
 * ForwardingCompositeVM<VM> — forwarding decorator for CompositeVMBase<VM>.
 *
 * Delegates every member — including collection surface, current, and selection
 * methods — to the wrapped composite by default.
 *
 * The decorator is a `ComponentVMBase`, so it can join a `CompositeVM` or a
 * `GroupVM`. It shares one ownership identity with the wrapped composite, and
 * `own()` registers resources on the wrapped composite (ADR-0213).
 *
 * See spec/09-forwarding.md §ForwardingCompositeVM.
 */
import type { Observable, Subscription } from "rxjs";
import type { ConstructionStatus } from "../lifecycle/status.js";
import type { ViewModelType } from "../components/types.js";
import type { RelayCommand } from "../commands/relayCommand.js";
import type { CompositeVMBase } from "../composites/compositeVMBase.js";
import { ComponentVMBase, type IOwningParentVM } from "../components/componentVMBase.js";
import type { CollectionChangedEvent } from "../collections/collectionChangedEvent.js";
import type { BatchUpdateHandle } from "../collections/batchUpdateHandle.js";
import type { IMessageHub } from "../services/messageHub.js";
import { NullDispatcher } from "../services/nullDispatcher.js";
import { forwardingParentOf, setForwardingParent } from "./forwardingParents.js";

export class ForwardingCompositeVM<VM extends ComponentVMBase> extends ComponentVMBase {
  protected readonly _wrapped: CompositeVMBase<VM>;

  constructor(wrapped: CompositeVMBase<VM>) {
    super({
      name: wrapped.name,
      hint: wrapped.hint,
      hub: wrapped.hub,
      dispatcher: NullDispatcher.INSTANCE,
    });
    this._wrapped = wrapped;
  }

  /**
   * The wrapped composite. Nested decorators, ownership, and the hub messages
   * of this decorator all belong to it: every message the decorator causes is
   * sent with the wrapped composite as its sender.
   */
  get wrappedBase(): ComponentVMBase { return this._wrapped; }

  override get _ownershipIdentity(): ComponentVMBase {
    return this._wrapped._ownershipIdentity;
  }

  override get _parent(): IOwningParentVM | null {
    return forwardingParentOf(this, this._wrapped);
  }
  override set _parent(parent: IOwningParentVM | null) {
    setForwardingParent(this, this._wrapped, parent);
  }

  override _setIsCurrent(value: boolean): void { this._wrapped._setIsCurrent(value); }
  override _commitIsCurrent(value: boolean): boolean { return this._wrapped._commitIsCurrent(value); }
  override _publishIsCurrent(): void { this._wrapped._publishIsCurrent(); }

  get name(): string { return this._wrapped.name; }
  get hint(): string { return this._wrapped.hint; }
  get type(): ViewModelType { return this._wrapped.type; }
  get isCurrent(): boolean { return this._wrapped.isCurrent; }
  get isConstructed(): boolean { return this._wrapped.isConstructed; }
  get status(): ConstructionStatus { return this._wrapped.status; }
  get hub(): IMessageHub { return this._wrapped.hub; }
  get propertyChanged(): Observable<string> { return this._wrapped.propertyChanged; }
  get selectCommand(): RelayCommand { return this._wrapped.selectCommand; }
  get deselectCommand(): RelayCommand { return this._wrapped.deselectCommand; }
  get selectNextCommand(): RelayCommand { return this._wrapped.selectNextCommand; }
  get selectPreviousCommand(): RelayCommand { return this._wrapped.selectPreviousCommand; }
  get reconstructCommand(): RelayCommand { return this._wrapped.reconstructCommand; }

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

  get supportsChildSelection(): boolean { return this._wrapped.supportsChildSelection; }
  get currentChild(): ComponentVMBase | null { return this._wrapped.currentChild; }
  selectChild(vm: ComponentVMBase): void { this._wrapped.selectChild(vm); }
  deselectChild(vm: ComponentVMBase): void { this._wrapped.deselectChild(vm); }

  get current(): VM | null { return this._wrapped.current; }
  set current(value: VM | null) { this._wrapped.current = value; }

  selectComponent(vm: VM): void { this._wrapped.selectComponent(vm); }
  deselectComponent(vm: VM): void { this._wrapped.deselectComponent(vm); }
  canSelectComponent(vm: VM): boolean { return this._wrapped.canSelectComponent(vm); }

  get collectionChanged(): Observable<CollectionChangedEvent> { return this._wrapped.collectionChanged; }
  get count(): number { return this._wrapped.count; }

  [Symbol.iterator](): Iterator<VM> { return this._wrapped[Symbol.iterator](); }

  snapshot(): readonly VM[] { return this._wrapped.snapshot(); }
  subscribeMembership(callback: () => void): Subscription {
    return this._wrapped.subscribeMembership(callback);
  }

  at(index: number): VM { return this._wrapped.at(index); }

  add(item: VM): void { this._wrapped.add(item); }
  insert(index: number, item: VM): void { this._wrapped.insert(index, item); }
  setAt(index: number, item: VM): void { this._wrapped.setAt(index, item); }
  remove(item: VM): boolean { return this._wrapped.remove(item); }
  removeAt(index: number): void { this._wrapped.removeAt(index); }
  clear(): void { this._wrapped.clear(); }
  move(fromIndex: number, toIndex: number): void { this._wrapped.move(fromIndex, toIndex); }
  batchUpdate(): BatchUpdateHandle { return this._wrapped.batchUpdate(); }
}
