/**
 * DiscriminatorVM — owns one active key with modal precedence helpers.
 */
import { Observable, Subject } from "rxjs";

export class DiscriminatorVM<TKey> {
  #activeKey: TKey;
  readonly #modalStack: TKey[] = [];
  readonly #activeChanged = new Subject<TKey>();
  #disposed = false;

  constructor(initial: TKey) {
    this.#activeKey = initial;
  }

  get activeKey(): TKey {
    return this.#activeKey;
  }

  get activeChanged(): Observable<TKey> {
    return this.#activeChanged.asObservable();
  }

  get modalDepth(): number {
    return this.#modalStack.length;
  }

  isActive(key: TKey): boolean {
    return Object.is(this.#activeKey, key) || this.#activeKey === key;
  }

  setActiveKey(key: TKey): void {
    if (this.#disposed) return;
    this.#modalStack.length = 0;
    this.#setActiveKeyPreservingModals(key);
  }

  #setActiveKeyPreservingModals(key: TKey): void {
    if (this.isActive(key)) return;
    this.#activeKey = key;
    this.#activeChanged.next(key);
  }

  modalOpen(modalKey: TKey): void {
    if (this.#disposed) return;
    this.#modalStack.push(this.#activeKey);
    this.#setActiveKeyPreservingModals(modalKey);
  }

  modalClose(): void {
    if (this.#disposed || this.#modalStack.length === 0) return;
    const previous = this.#modalStack.pop() as TKey;
    this.#setActiveKeyPreservingModals(previous);
  }

  clearModals(): void {
    if (this.#disposed) return;
    this.#modalStack.length = 0;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#modalStack.length = 0;
    this.#activeChanged.complete();
  }
}
