import { Subscription } from "rxjs";
import { FormVM, type FormVMOptions } from "../forms/formVm.js";
import { PropertyChangeRecorder } from "./recorders.js";
import { RecordingMessageHub } from "./recordingMessageHub.js";

export type FormHarnessOptions<T> = Omit<FormVMOptions<T>, "persister" | "hub">;

/**
 * Test harness around the real FormVM lifecycle with a controllable persister.
 */
export class FormHarness<T> {
  readonly hub = new RecordingMessageHub();
  readonly form: FormVM<T>;
  readonly propertyChanges: PropertyChangeRecorder<FormVM<T>>;

  readonly #subscriptions = new Subscription();
  readonly #persistAttempts: T[] = [];
  readonly #approved: T[] = [];
  readonly #approveErrors: unknown[] = [];
  #nextFailure: Error | null = null;
  #disposed = false;

  constructor(options: FormHarnessOptions<T>) {
    this.form = new FormVM<T>({
      ...options,
      hub: this.hub,
      persister: (value) => {
        this.#persistAttempts.push(value);
        const failure = this.#nextFailure;
        this.#nextFailure = null;
        if (failure !== null) return Promise.reject(failure);
        return Promise.resolve();
      },
    });
    this.propertyChanges = new PropertyChangeRecorder(this.hub, {
      sender: this.form,
    });
    this.#subscriptions.add(this.form.onApproved.subscribe((value) => {
      this.#approved.push(value);
    }));
    this.#subscriptions.add(this.form.approveErrors.subscribe((error) => {
      this.#approveErrors.push(error);
    }));
  }

  get persistAttempts(): readonly T[] {
    return [...this.#persistAttempts];
  }

  get approved(): readonly T[] {
    return [...this.#approved];
  }

  get approveErrors(): readonly unknown[] {
    return [...this.#approveErrors];
  }

  set(value: T): void {
    this.form.setModel(value);
  }

  approve(): Promise<void> {
    return this.form.approveAsync();
  }

  deny(): void {
    this.form.denyCommand.execute();
  }

  failNext(error: Error): void {
    this.#nextFailure = error;
  }

  clear(): void {
    this.#persistAttempts.length = 0;
    this.#approved.length = 0;
    this.#approveErrors.length = 0;
    this.#nextFailure = null;
    this.propertyChanges.clear();
    this.hub.clear();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#subscriptions.unsubscribe();
    this.propertyChanges.dispose();
    this.form.dispose();
    this.hub.dispose();
  }
}

export function createFormHarness<T>(options: FormHarnessOptions<T>): FormHarness<T> {
  return new FormHarness(options);
}
