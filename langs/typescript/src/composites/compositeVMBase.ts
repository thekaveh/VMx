/**
 * CompositeVMBase — abstract base for all CompositeVM variants.
 *
 * Extends ComponentVMBase with:
 * - Ordered children list
 * - current selection slot
 * - collectionChanged Observable
 * - Coordinated construct / destruct / dispose for child hierarchy
 * - Batch update support (spec v1.1)
 * - AutoConstructOnAdd support (spec v1.1)
 *
 * See spec/06-composite-vm.md.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { IParentVM } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import {
  makeCollectionChangedEvent,
  BatchUpdateHandle,
} from "../collections/index.js";
import type { CollectionChangedEvent, IBatchable } from "../collections/index.js";

export abstract class CompositeVMBase<VM extends ComponentVMBase>
  extends ComponentVMBase
  implements IParentVM, IBatchable
{
  readonly #asyncSelection: boolean;
  readonly #autoConstructOnAdd: boolean;
  protected _children: VM[] = [];
  #current: VM | null = null;
  readonly #collectionChangedSubject = new Subject<CollectionChangedEvent>();
  #populated = false;
  #batchDepth = 0;
  #batchDirty = false;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    asyncSelection?: boolean;
    autoConstructOnAdd?: boolean;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
  }) {
    super(opts);
    this.#asyncSelection = opts.asyncSelection ?? false;
    this.#autoConstructOnAdd = opts.autoConstructOnAdd ?? false;
  }

  get type(): ViewModelType {
    return ViewModelType.Composite;
  }

  // ── IParentVM implementation ──────────────────────────────────────────────

  get currentChild(): ComponentVMBase | null {
    return this.#current;
  }

  selectChild(vm: ComponentVMBase): void {
    for (const child of this._children) {
      if (child === vm) {
        this._setCurrent(child, this.#asyncSelection);
        return;
      }
    }
  }

  deselectChild(vm: ComponentVMBase): void {
    if (this.#current === vm) {
      this._setCurrent(null, this.#asyncSelection);
    }
  }

  // ── collectionChanged ─────────────────────────────────────────────────────

  get collectionChanged(): Observable<CollectionChangedEvent> {
    return this.#collectionChangedSubject.asObservable();
  }

  // ── current property ──────────────────────────────────────────────────────

  get current(): VM | null {
    return this.#current;
  }

  set current(value: VM | null) {
    if (value !== null && !this._children.includes(value)) {
      throw new Error(
        `Cannot set current to '${value.name}': it is not a member of this composite.`,
      );
    }
    this._setCurrent(value, this.#asyncSelection);
  }

  // ── Selection methods ─────────────────────────────────────────────────────

  selectComponent(vm: VM): void {
    if (!this.canSelectComponent(vm)) {
      throw new Error(
        `Cannot select '${vm.name}': canSelectComponent returned false.`,
      );
    }
    this.current = vm;
  }

  deselectComponent(vm: VM): void {
    if (this.#current !== vm) {
      throw new Error(
        `Cannot deselect '${vm.name}': it is not the current selection.`,
      );
    }
    this.current = null;
  }

  canSelectComponent(vm: VM): boolean {
    return (
      this._children.includes(vm) &&
      vm.status === ConstructionStatus.Constructed
    );
  }

  // ── Collection API ────────────────────────────────────────────────────────

  get count(): number {
    return this._children.length;
  }

  [Symbol.iterator](): Iterator<VM> {
    return this._children[Symbol.iterator]();
  }

  at(index: number): VM {
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    return item;
  }

  add(item: VM): void {
    this._children.push(item);
    item._parent = this;
    this._maybeAutoConstruct(item);
    const idx = this._children.length - 1;
    this._emitCollectionChanged(
      makeCollectionChangedEvent("add", {
        newItems: [item],
        newIndex: idx,
      }),
    );
  }

  insert(index: number, item: VM): void {
    this._children.splice(index, 0, item);
    item._parent = this;
    this._maybeAutoConstruct(item);
    this._emitCollectionChanged(
      makeCollectionChangedEvent("add", {
        newItems: [item],
        newIndex: index,
      }),
    );
  }

  remove(item: VM): boolean {
    const idx = this._children.indexOf(item);
    if (idx < 0) return false;
    this.removeAt(idx);
    return true;
  }

  removeAt(index: number): void {
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    this._children.splice(index, 1);
    item._parent = null;
    if (this.#current === item) {
      this._setCurrent(null, false);
    }
    this._emitCollectionChanged(
      makeCollectionChangedEvent("remove", {
        oldItems: [item],
        oldIndex: index,
      }),
    );
  }

  clear(): void {
    for (const child of this._children) {
      child._parent = null;
    }
    this._children = [];
    this.#current = null;
    this._emitCollectionChanged(makeCollectionChangedEvent("reset"));
  }

  // ── Batch updates (spec v1.1) ─────────────────────────────────────────────

  batchUpdate(): BatchUpdateHandle {
    this.#batchDepth++;
    return new BatchUpdateHandle(this);
  }

  _exitBatch(): void {
    this.#batchDepth--;
    if (this.#batchDepth === 0 && this.#batchDirty) {
      this.#batchDirty = false;
      this.#collectionChangedSubject.next(makeCollectionChangedEvent("reset"));
    }
  }

  protected _emitCollectionChanged(event: CollectionChangedEvent): void {
    if (this.#batchDepth > 0) {
      this.#batchDirty = true;
      return;
    }
    this.#collectionChangedSubject.next(event);
  }

  protected _maybeAutoConstruct(child: VM): void {
    if (!this.#autoConstructOnAdd) return;
    if (this.status !== ConstructionStatus.Constructed) return;
    if (child.status === ConstructionStatus.Constructed) return;
    child.construct();
  }

  // ── Lifecycle overrides ───────────────────────────────────────────────────

  protected override _onConstruct(): void {
    super._onConstruct();
    if (!this.#populated) {
      this.#populated = true;
      this._populateChildren();
    }
    for (const child of [...this._children]) {
      child.construct();
    }
  }

  protected override _onDestruct(): void {
    if (this.#current !== null) {
      this._setCurrent(null, false);
    }
    for (const child of [...this._children]) {
      child.destruct();
    }
    super._onDestruct();
  }

  override dispose(): void {
    for (const child of [...this._children]) {
      child.dispose();
    }
    super.dispose();
  }

  protected override _onDispose(): void {
    if (!this.#collectionChangedSubject.closed) {
      this.#collectionChangedSubject.complete();
    }
  }

  // ── Factory hook ──────────────────────────────────────────────────────────

  protected _populateChildren(): void {
    // Default: no-op. Subclasses override to evaluate their factory.
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  protected _setCurrent(value: VM | null, asyncSel: boolean): void {
    if (value !== null && !this._children.includes(value)) {
      throw new Error(
        `Cannot set current to '${value.name}': not a member of this composite.`,
      );
    }
    if (asyncSel) {
      const captured = value;
      this._scheduleForeground(() => this._applyCurrentChange(captured));
    } else {
      this._applyCurrentChange(value);
    }
  }

  private _applyCurrentChange(value: VM | null): void {
    if (this.#current === value) return;

    const previous = this.#current;
    this.#current = value;

    if (previous !== null) previous._setIsCurrent(false);
    if (value !== null) value._setIsCurrent(true);

    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "Current"),
    );
    this._raisePropertyChanged("current");
  }
}
