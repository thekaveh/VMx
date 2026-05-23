/**
 * BatchUpdateHandle — ref-counted disposable for batch collection mutations.
 *
 * See spec/06-composite-vm.md §Batch updates (spec v1.1).
 */

/** Internal interface implemented by containers that support batching. */
export interface IBatchable {
  _exitBatch(): void;
}

export class BatchUpdateHandle {
  #owner: IBatchable;
  #disposed = false;

  constructor(owner: IBatchable) {
    this.#owner = owner;
  }

  dispose(): void {
    if (!this.#disposed) {
      this.#disposed = true;
      this.#owner._exitBatch();
    }
  }

  /** Support `using` resource management (TC39 stage 3 / TypeScript 5.2). */
  [Symbol.dispose](): void {
    this.dispose();
  }
}
