import { describe, expect, it } from "vitest";
import {
  AsyncResourceRetention,
  AsyncResourceStatus,
  AsyncResourceVM,
  MessageHub,
  NullDispatcher,
  PropertyChangedMessage,
  type AsyncResourceState,
} from "../../src/index.js";

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function abortError(): DOMException {
  return new DOMException("cancelled", "AbortError");
}

function hasValue<T>(state: AsyncResourceState<T>): boolean {
  return "value" in state;
}

async function flush(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

describe("AsyncResourceVM conformance", () => {
  describe("ARES-001", () => {
    it("starts idle without invoking the loader and exposes exact command eligibility", () => {
      let calls = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        loader: () => {
          calls += 1;
          return Promise.resolve(1);
        },
      });
      const changes: string[] = [];
      vm.propertyChanged.subscribe((name) => changes.push(name));

      expect(vm.state).toEqual({ status: AsyncResourceStatus.Idle });
      expect(Object.isFrozen(vm.state)).toBe(true);
      expect(calls).toBe(0);
      expect(changes).toEqual([]);
      expect(vm.loadCommand.canExecute()).toBe(true);
      expect(vm.reloadCommand.canExecute()).toBe(false);
      expect(vm.cancelCommand.canExecute()).toBe(false);
    });
  });

  describe("ARES-002", () => {
    it("publishes one ordinary state pair for loading and ready", async () => {
      const hub = new MessageHub();
      const result = deferred<number>();
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub,
        dispatcher: NullDispatcher.INSTANCE,
        loader: () => result.promise,
      });
      const local: string[] = [];
      const shared: string[] = [];
      vm.propertyChanged.subscribe((name) => local.push(name));
      hub.messages.subscribe((message) => {
        if (message instanceof PropertyChangedMessage && message.sender === vm) {
          shared.push(message.propertyName);
        }
      });

      const load = vm.load();
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Loading });
      result.resolve(42);
      await load;

      expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 42 });
      expect(local).toEqual(["state", "state"]);
      expect(shared).toEqual(local);
      expect(vm.loadCommand.canExecute()).toBe(false);
      expect(vm.reloadCommand.canExecute()).toBe(true);
      expect(vm.cancelCommand.canExecute()).toBe(false);
    });
  });

  describe("ARES-003", () => {
    it("routes fire-and-forget loader failure only into error state", async () => {
      const failure = new Error("offline");
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        loader: () => Promise.reject(failure),
      });
      const commandErrors: unknown[] = [];
      vm.loadCommand.errors.subscribe((error) => commandErrors.push(error));

      vm.loadCommand.execute();
      await flush();

      expect(vm.state.status).toBe(AsyncResourceStatus.Error);
      if (vm.state.status !== AsyncResourceStatus.Error) throw new Error("expected error");
      expect(vm.state.error).toBe(failure);
      expect(hasValue(vm.state)).toBe(false);
      expect(commandErrors).toEqual([]);
      expect(vm.reloadCommand.canExecute()).toBe(true);
    });
  });

  describe("ARES-004", () => {
    it("retries from error and replaces it with ready", async () => {
      const failure = new Error("first");
      let attempt = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        loader: () => {
          attempt += 1;
          if (attempt === 1) return Promise.reject(failure);
          return Promise.resolve(7);
        },
      });

      await vm.load();
      expect(vm.state.status).toBe(AsyncResourceStatus.Error);
      const reload = vm.reload();
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Loading });
      await reload;
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 7 });
      expect("error" in vm.state).toBe(false);
    });
  });

  describe("ARES-005", () => {
    it("cancels an initial load back to idle without an error", async () => {
      let observedAbort = false;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        loader: (signal) => new Promise<number>((_resolve, reject) => {
          signal.addEventListener("abort", () => {
            observedAbort = true;
            reject(abortError());
          }, { once: true });
        }),
      });
      const commandErrors: unknown[] = [];
      vm.loadCommand.errors.subscribe((error) => commandErrors.push(error));

      const load = vm.load();
      expect(vm.cancelCommand.canExecute()).toBe(true);
      vm.cancelCommand.execute();
      await load;

      expect(observedAbort).toBe(true);
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Idle });
      expect(commandErrors).toEqual([]);
      vm.cancel();
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Idle });
    });
  });

  describe("ARES-006", () => {
    it("retains a ready value through reload cancellation and later failure", async () => {
      const second = deferred<number>();
      const failure = new Error("refresh failed");
      let attempt = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        retention: AsyncResourceRetention.RetainPrevious,
        loader: async () => {
          attempt += 1;
          if (attempt === 1) return 3;
          if (attempt === 2) return second.promise;
          throw failure;
        },
      });

      await vm.load();
      const reload = vm.reload();
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Loading, value: 3 });
      vm.cancel();
      await reload;
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 3 });

      await vm.reload();
      expect(vm.state.status).toBe(AsyncResourceStatus.Error);
      if (vm.state.status !== AsyncResourceStatus.Error) throw new Error("expected error");
      expect(vm.state.value).toBe(3);
      expect(vm.state.error).toBe(failure);
    });
  });

  describe("ARES-007", () => {
    it("discards and cleans the previous value before loading is observed", async () => {
      const second = deferred<number>();
      const failure = new Error("still offline");
      let attempt = 0;
      const cleaned: number[] = [];
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        cleanupValue: (value) => cleaned.push(value),
        loader: async () => {
          attempt += 1;
          if (attempt === 1) return 5;
          if (attempt === 2) return second.promise;
          throw failure;
        },
      });

      await vm.load();
      const reload = vm.reload();
      expect(cleaned).toEqual([5]);
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Loading });
      vm.cancel();
      await reload;
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Idle });

      await vm.load();
      expect(vm.state.status).toBe(AsyncResourceStatus.Error);
      expect(hasValue(vm.state)).toBe(false);
    });
  });

  describe("ARES-008", () => {
    it("admits only the latest overlapping completion", async () => {
      const first = deferred<number>();
      const second = deferred<number>();
      const signals: AbortSignal[] = [];
      let attempt = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        loader: (signal) => {
          signals.push(signal);
          attempt += 1;
          return attempt === 1 ? first.promise : second.promise;
        },
      });

      const older = vm.load();
      const newer = vm.reload();
      expect(signals[0]?.aborted).toBe(true);
      first.resolve(1);
      await older;
      expect(vm.state.status).toBe(AsyncResourceStatus.Loading);
      second.resolve(2);
      await newer;
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 2 });
    });
  });

  describe("ARES-009", () => {
    it("cleans a stale success once without notifying state", async () => {
      const first = deferred<number>();
      const second = deferred<number>();
      const cleaned: number[] = [];
      const changes: string[] = [];
      let attempt = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        cleanupValue: (value) => cleaned.push(value),
        loader: () => {
          attempt += 1;
          return attempt === 1 ? first.promise : second.promise;
        },
      });
      vm.propertyChanged.subscribe((name) => changes.push(name));

      const older = vm.load();
      const newer = vm.reload();
      second.resolve(2);
      await newer;
      const countAfterCurrent = changes.length;
      first.resolve(1);
      await older;

      expect(cleaned).toEqual([1]);
      expect(changes).toHaveLength(countAfterCurrent);
      expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 2 });
    });
  });

  describe("ARES-010", () => {
    it("cleans replaced and terminal accepted ownership exactly once", async () => {
      const cleaned: number[] = [];
      let value = 1;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        retention: AsyncResourceRetention.RetainPrevious,
        cleanupValue: (owned) => cleaned.push(owned),
        loader: () => Promise.resolve(value++),
      });

      await vm.load();
      await vm.reload();
      expect(cleaned).toEqual([1]);
      vm.dispose();
      vm.dispose();
      expect(cleaned).toEqual([1, 2]);
    });
  });

  it("suppresses a replaced-value completion when cleanup starts a newer reload", async () => {
    let nextValue = 0;
    let reentered = false;
    let reentrantReload = Promise.resolve();
    const changes: string[] = [];
    let vm!: AsyncResourceVM<number>;
    vm = new AsyncResourceVM<number>({
      name: "resource",
      hub: new MessageHub(),
      dispatcher: NullDispatcher.INSTANCE,
      retention: AsyncResourceRetention.RetainPrevious,
      loader: () => Promise.resolve(++nextValue),
      cleanupValue: (value) => {
        if (value === 1 && !reentered) {
          reentered = true;
          reentrantReload = vm.reload();
        }
      },
    });
    vm.propertyChanged.subscribe((name) => changes.push(name));

    await vm.load();
    changes.length = 0;
    await vm.reload();
    await reentrantReload;

    expect(changes).toEqual(["state", "state", "state"]);
    expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 3 });
    expect(nextValue).toBe(3);
  });

  it("abandons a discarded-value reload when cleanup starts a newer reload", async () => {
    let nextValue = 0;
    let reentered = false;
    let reentrantReload = Promise.resolve();
    const changes: string[] = [];
    let vm!: AsyncResourceVM<number>;
    vm = new AsyncResourceVM<number>({
      name: "resource",
      hub: new MessageHub(),
      dispatcher: NullDispatcher.INSTANCE,
      loader: () => Promise.resolve(++nextValue),
      cleanupValue: (value) => {
        if (value === 1 && !reentered) {
          reentered = true;
          reentrantReload = vm.reload();
        }
      },
    });
    vm.propertyChanged.subscribe((name) => changes.push(name));

    await vm.load();
    changes.length = 0;
    await vm.reload();
    await reentrantReload;

    expect(changes).toEqual(["state", "state"]);
    expect(vm.state).toEqual({ status: AsyncResourceStatus.Ready, value: 2 });
    expect(nextValue).toBe(2);
  });

  describe("ARES-011", () => {
    it("disposal cancels and makes late completion and intents inert", async () => {
      const late = deferred<number>();
      const cleaned: number[] = [];
      const changes: string[] = [];
      let signal: AbortSignal | undefined;
      let calls = 0;
      const vm = new AsyncResourceVM<number>({
        name: "resource",
        hub: new MessageHub(),
        dispatcher: NullDispatcher.INSTANCE,
        cleanupValue: (value) => cleaned.push(value),
        loader: (currentSignal) => {
          calls += 1;
          signal = currentSignal;
          return late.promise;
        },
      });
      vm.propertyChanged.subscribe((name) => changes.push(name));

      const load = vm.load();
      vm.dispose();
      vm.dispose();
      const countAtDispose = changes.length;
      expect(signal?.aborted).toBe(true);
      expect(vm.loadCommand.canExecute()).toBe(false);
      expect(vm.reloadCommand.canExecute()).toBe(false);
      expect(vm.cancelCommand.canExecute()).toBe(false);

      late.resolve(9);
      await load;
      await vm.load();
      await vm.reload();
      vm.cancel();

      expect(cleaned).toEqual([9]);
      expect(changes).toHaveLength(countAtDispose);
      expect(calls).toBe(1);
    });
  });
});
