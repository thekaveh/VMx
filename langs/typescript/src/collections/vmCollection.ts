import type { Observable } from "rxjs";
import type { ComponentVMBase } from "../components/componentVMBase.js";
import type { BatchUpdateHandle } from "./batchUpdateHandle.js";
import type { CollectionChangedEvent } from "./collectionChangedEvent.js";

/** Shared ordered, observable child-collection capability without selection. */
export interface IVmCollection<VM extends ComponentVMBase> extends Iterable<VM> {
  readonly count: number;
  readonly collectionChanged: Observable<CollectionChangedEvent>;
  at(index: number): VM;
  add(item: VM): void;
  insert(index: number, item: VM): void;
  remove(item: VM): boolean;
  removeAt(index: number): void;
  setAt(index: number, value: VM): void;
  clear(): void;
  move(fromIndex: number, toIndex: number): void;
  batchUpdate(): BatchUpdateHandle;
}

/** VM collection that additionally owns a current-child selection slot. */
export interface ISelectableVmCollection<VM extends ComponentVMBase>
  extends IVmCollection<VM> {
  current: VM | null;
  selectComponent(vm: VM): void;
  deselectComponent(vm: VM): void;
  canSelectComponent(vm: VM): boolean;
}
