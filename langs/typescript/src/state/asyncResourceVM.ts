/**
 * AsyncResourceVM — one cancellable asynchronously acquired presentation value.
 *
 * Spec: spec/23-async-resource-vm.md; ADR-0100.
 */
import type { IDispatcher } from "../services/dispatcher.js";
import type { IMessageHub } from "../services/messageHub.js";
import { AsyncRelayCommand } from "../commands/asyncRelayCommand.js";
import { RelayCommand } from "../commands/relayCommand.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";

export enum AsyncResourceStatus {
  Idle = "Idle",
  Loading = "Loading",
  Ready = "Ready",
  Error = "Error",
}

export enum AsyncResourceRetention {
  DiscardPrevious = "DiscardPrevious",
  RetainPrevious = "RetainPrevious",
}

export type AsyncResourceState<T> =
  | Readonly<{ status: AsyncResourceStatus.Idle }>
  | Readonly<{ status: AsyncResourceStatus.Loading; value?: T }>
  | Readonly<{ status: AsyncResourceStatus.Ready; value: T }>
  | Readonly<{ status: AsyncResourceStatus.Error; error: unknown; value?: T }>;

type StableAsyncResourceState<T> = Exclude<
  AsyncResourceState<T>,
  Readonly<{ status: AsyncResourceStatus.Loading; value?: T }>
>;

export interface AsyncResourceVMOptions<T> {
  readonly name: string;
  readonly loader: (signal: AbortSignal) => Promise<T>;
  readonly hub: IMessageHub;
  readonly dispatcher: IDispatcher;
  readonly hint?: string;
  readonly retention?: AsyncResourceRetention;
  readonly cleanupValue?: (value: T) => void;
}

interface PresentValue<T> {
  readonly present: true;
  readonly value: T;
}

interface AbsentValue {
  readonly present: false;
}

type OptionalValue<T> = PresentValue<T> | AbsentValue;

const ABSENT_VALUE: AbsentValue = Object.freeze({ present: false });

function idleState<T>(): StableAsyncResourceState<T> {
  return Object.freeze({ status: AsyncResourceStatus.Idle });
}

function valueOf<T>(state: StableAsyncResourceState<T>): OptionalValue<T> {
  if (state.status === AsyncResourceStatus.Ready) {
    return { present: true, value: state.value };
  }
  if (state.status === AsyncResourceStatus.Error && "value" in state) {
    return { present: true, value: state.value };
  }
  return ABSENT_VALUE;
}

export class AsyncResourceVM<T> extends ComponentVMBase {
  readonly #loader: (signal: AbortSignal) => Promise<T>;
  readonly #retention: AsyncResourceRetention;
  readonly #cleanupValue: ((value: T) => void) | null;

  #state: AsyncResourceState<T> = idleState<T>();
  #stableState: StableAsyncResourceState<T> = idleState<T>();
  #operationId = 0;
  #controller: AbortController | null = null;
  #disposed = false;

  readonly loadCommand: AsyncRelayCommand;
  readonly reloadCommand: AsyncRelayCommand;
  readonly cancelCommand: RelayCommand;

  constructor(options: AsyncResourceVMOptions<T>) {
    super({
      name: options.name,
      hint: options.hint ?? "",
      hub: options.hub,
      dispatcher: options.dispatcher,
    });
    this.#loader = options.loader;
    this.#retention = options.retention ?? AsyncResourceRetention.DiscardPrevious;
    this.#cleanupValue = options.cleanupValue ?? null;

    this.loadCommand = AsyncRelayCommand.builder()
      .task((signal) => this.load(signal))
      .predicate(() => this.#canLoad())
      .build();
    this.reloadCommand = AsyncRelayCommand.builder()
      .task((signal) => this.reload(signal))
      .predicate(() => this.#canReload())
      .build();
    this.cancelCommand = RelayCommand.builder()
      .task(() => this.cancel())
      .predicate(() => this.#canCancel())
      .build();
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get state(): AsyncResourceState<T> {
    return this.#state;
  }

  async load(signal?: AbortSignal): Promise<void> {
    if (!this.#canLoad()) return;
    await this.#start(signal);
  }

  async reload(signal?: AbortSignal): Promise<void> {
    if (!this.#canReload()) return;
    await this.#start(signal);
  }

  cancel(): void {
    if (!this.#canCancel()) return;
    const controller = this.#controller;
    this.loadCommand.cancel();
    this.reloadCommand.cancel();
    controller?.abort();
  }

  protected override _onDispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#operationId += 1;
    const controller = this.#controller;
    this.#controller = null;
    controller?.abort();
    this.loadCommand.cancel();
    this.reloadCommand.cancel();
    this.loadCommand.dispose();
    this.reloadCommand.dispose();
    this.cancelCommand.dispose();

    const accepted = valueOf(this.#stableState);
    this.#stableState = idleState<T>();
    if (accepted.present) this.#cleanup(accepted.value);
  }

  #canLoad(): boolean {
    return !this.#disposed && this.#state.status === AsyncResourceStatus.Idle;
  }

  #canReload(): boolean {
    return !this.#disposed && this.#state.status !== AsyncResourceStatus.Idle;
  }

  #canCancel(): boolean {
    return !this.#disposed && this.#state.status === AsyncResourceStatus.Loading;
  }

  async #start(externalSignal?: AbortSignal): Promise<void> {
    const previousController = this.#controller;
    const operationId = this.#operationId + 1;
    this.#operationId = operationId;

    const controller = new AbortController();
    this.#controller = controller;
    previousController?.abort();

    if (this.#retention === AsyncResourceRetention.DiscardPrevious) {
      const previous = valueOf(this.#stableState);
      if (previous.present) {
        this.#stableState = idleState<T>();
        this.#cleanup(previous.value);
      }
    }

    const baseline = this.#stableState;
    const retained = this.#retention === AsyncResourceRetention.RetainPrevious
      ? valueOf(baseline)
      : ABSENT_VALUE;
    const loading: AsyncResourceState<T> = retained.present
      ? Object.freeze({ status: AsyncResourceStatus.Loading, value: retained.value })
      : Object.freeze({ status: AsyncResourceStatus.Loading });

    let unlinkExternal = (): void => {};
    let resolveCancellation!: () => void;
    const cancellation = new Promise<"cancelled">((resolve) => {
      resolveCancellation = () => resolve("cancelled");
    });
    const finishCancellation = (): void => {
      unlinkExternal();
      resolveCancellation();
      if (!this.#isCurrent(operationId, controller)) return;
      this.#operationId += 1;
      this.#controller = null;
      this.#setState(baseline);
    };
    controller.signal.addEventListener("abort", finishCancellation, { once: true });

    if (externalSignal !== undefined) {
      const abortFromExternal = (): void => controller.abort(externalSignal.reason);
      if (externalSignal.aborted) {
        controller.abort(externalSignal.reason);
      } else {
        externalSignal.addEventListener("abort", abortFromExternal, { once: true });
        unlinkExternal = () => externalSignal.removeEventListener("abort", abortFromExternal);
      }
    }

    if (this.#isCurrent(operationId, controller)) this.#setState(loading);
    if (controller.signal.aborted) return;

    let loaderPromise: Promise<T>;
    try {
      loaderPromise = this.#loader(controller.signal);
    } catch (error: unknown) {
      loaderPromise = Promise.resolve().then(() => {
        throw error;
      });
    }
    const outcome = await Promise.race([
      loaderPromise.then(
        (value) => ({ kind: "success" as const, value }),
        (error: unknown) => ({ kind: "failure" as const, error }),
      ),
      cancellation,
    ]);

    if (outcome === "cancelled") {
      void loaderPromise.then(
        (value) => this.#cleanup(value),
        () => {},
      );
      return;
    }

    if (outcome.kind === "success") {
      if (!this.#isCurrent(operationId, controller)) {
        this.#cleanup(outcome.value);
        return;
      }

      unlinkExternal();
      const previous = valueOf(this.#stableState);
      this.#controller = null;
      const ready: StableAsyncResourceState<T> = Object.freeze({
        status: AsyncResourceStatus.Ready,
        value: outcome.value,
      });
      this.#stableState = ready;
      if (previous.present) this.#cleanup(previous.value);
      if (!this.#disposed && this.#operationId === operationId && this.#stableState === ready) {
        this.#setState(ready);
      }
      return;
    }

    if (!this.#isCurrent(operationId, controller)) return;
    unlinkExternal();
    this.#controller = null;

    const previous = this.#retention === AsyncResourceRetention.RetainPrevious
      ? valueOf(this.#stableState)
      : ABSENT_VALUE;
    const failed: StableAsyncResourceState<T> = previous.present
      ? Object.freeze({
        status: AsyncResourceStatus.Error,
        value: previous.value,
        error: outcome.error,
      })
      : Object.freeze({ status: AsyncResourceStatus.Error, error: outcome.error });
    this.#stableState = failed;
    this.#setState(failed);
  }

  #isCurrent(operationId: number, controller: AbortController): boolean {
    return !this.#disposed
      && this.#operationId === operationId
      && this.#controller === controller;
  }

  #setState(state: AsyncResourceState<T>): void {
    if (this.#disposed || this.#state === state) return;
    this.#state = state;
    this._notifyPropertyChanged("state");
    this.loadCommand.raiseCanExecuteChanged();
    this.reloadCommand.raiseCanExecuteChanged();
    this.cancelCommand.raiseCanExecuteChanged();
  }

  #cleanup(value: T): void {
    try {
      this.#cleanupValue?.(value);
    } catch {
      // Best-effort ownership cleanup, matching ComponentVMBase.own().
    }
  }
}
