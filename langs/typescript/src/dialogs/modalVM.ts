/**
 * VM-backed modal result primitive.
 */
export class ModalVM<T> {
  readonly #cancellationResult: T;
  #result: T | null = null;
  #isDismissed = false;
  readonly #completion: Promise<T>;
  #resolve!: (result: T) => void;

  constructor(cancellationResult: T) {
    this.#cancellationResult = cancellationResult;
    this.#completion = new Promise<T>((resolve) => {
      this.#resolve = resolve;
    });
  }

  /** Result used when the modal is cancelled or disposed. */
  get cancellationResult(): T {
    return this.#cancellationResult;
  }

  /** Dismissal result, or `null` before dismissal. */
  get result(): T | null {
    return this.#result;
  }

  /** True after dismissal or disposal. */
  get isDismissed(): boolean {
    return this.#isDismissed;
  }

  /** Promise resolved when the modal is dismissed. */
  get completion(): Promise<T> {
    return this.#completion;
  }

  /** Complete the modal with `result`. Idempotent. */
  dismiss(result: T): void {
    if (this.#isDismissed) return;
    this.#result = result;
    this.#isDismissed = true;
    this.#resolve(result);
  }

  /** Cancel the modal with `cancellationResult`. Idempotent. */
  dispose(): void {
    this.dismiss(this.#cancellationResult);
  }
}
