/**
 * FilteredCompositeVM — visible projection over a CompositeVM source.
 */
import { Subject, Subscription } from "rxjs";
import type { Observable } from "rxjs";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { CompositeVMBase } from "./compositeVMBase.js";

export enum FilteredCursorPolicy {
  SnapToFirst = "snapToFirst",
  Clear = "clear",
  PreserveIfVisible = "preserveIfVisible",
}

export interface FilteredCompositeOptions<VM extends ComponentVMBase> {
  readonly predicate?: (vm: VM) => boolean;
  readonly cursorPolicy?: FilteredCursorPolicy;
  readonly deferInitialRecompute?: boolean;
}

export class FilteredCompositeVM<VM extends ComponentVMBase> {
  protected readonly source: CompositeVMBase<VM>;
  protected predicate: (vm: VM) => boolean;
  readonly #cursorPolicy: FilteredCursorPolicy;
  readonly #changed = new Subject<void>();
  readonly #subscription: Subscription;
  #visible: VM[] = [];
  #current: VM | null = null;
  #disposed = false;

  constructor(
    source: CompositeVMBase<VM>,
    options: FilteredCompositeOptions<VM> = {},
  ) {
    this.source = source;
    this.predicate = options.predicate ?? (() => true);
    this.#cursorPolicy = options.cursorPolicy ?? FilteredCursorPolicy.SnapToFirst;
    this.#subscription = source.collectionChanged.subscribe(() => this._recompute());
    if (options.deferInitialRecompute !== true) this._recompute();
  }

  get visible(): VM[] {
    return [...this.#visible];
  }

  get visibleCount(): number {
    return this.#visible.length;
  }

  get current(): VM | null {
    return this.#current;
  }

  set current(value: VM | null) {
    this.setCurrent(value);
  }

  get changed(): Observable<void> {
    return this.#changed.asObservable();
  }

  setPredicate(predicate: (vm: VM) => boolean): void {
    this.predicate = predicate;
    this._recompute();
  }

  setCurrent(item: VM | null): void {
    if (item !== null && !this.#visible.includes(item)) {
      throw new Error("current must be null or a visible item");
    }
    if (this.#current === item) return;
    this.#current = item;
    this.#changed.next();
  }

  moveToNextVisible(): void {
    if (this.#visible.length === 0) {
      this.setCurrent(null);
      return;
    }
    if (this.#current === null || !this.#visible.includes(this.#current)) {
      this.setCurrent(this.#visible[0] ?? null);
      return;
    }
    const index = this.#visible.indexOf(this.#current);
    this.setCurrent(this.#visible[Math.min(index + 1, this.#visible.length - 1)] ?? null);
  }

  moveToPreviousVisible(): void {
    if (this.#visible.length === 0) {
      this.setCurrent(null);
      return;
    }
    if (this.#current === null || !this.#visible.includes(this.#current)) {
      this.setCurrent(this.#visible[0] ?? null);
      return;
    }
    const index = this.#visible.indexOf(this.#current);
    this.setCurrent(this.#visible[Math.max(index - 1, 0)] ?? null);
  }

  protected orderedVisible(): VM[] {
    return [...this.source].filter((vm) => this.predicate(vm));
  }

  protected _recompute(): void {
    this.#visible = this.orderedVisible();
    if (this.#current !== null && !this.#visible.includes(this.#current)) {
      this.#current =
        this.#cursorPolicy === FilteredCursorPolicy.SnapToFirst
          ? (this.#visible[0] ?? null)
          : null;
    } else if (this.#current === null && this.#cursorPolicy === FilteredCursorPolicy.SnapToFirst) {
      this.#current = this.#visible[0] ?? null;
    }
    this.#changed.next();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#subscription.unsubscribe();
    this.#changed.complete();
  }
}
