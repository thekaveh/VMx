/**
 * FakeScheduler — deterministic virtual-time scheduler for testing.
 *
 * Tracks a virtual `now()` and fires scheduled callbacks synchronously
 * when `advanceTo(ms)` / `advanceBy(ms)` is called.
 *
 * Implements SchedulerLike so it can be injected into NotificationVM / ConfirmationVM.
 */
import { Subscription } from "rxjs";
import type { SchedulerAction, SchedulerLike } from "rxjs";

interface PendingAction {
  readonly dueTime: number;
  readonly work: () => void;
  cancelled: boolean;
}

class FakeSchedulerSubscription extends Subscription {
  constructor(private readonly action: PendingAction) {
    super();
  }
  override unsubscribe(): void {
    this.closed = true;
    this.action.cancelled = true;
  }
}

export class FakeScheduler implements SchedulerLike {
  #currentTime = 0;
  readonly #queue: PendingAction[] = [];

  now(): number {
    return this.#currentTime;
  }

  schedule<T>(
    work: (this: SchedulerAction<T>, state?: T) => void,
    delay = 0,
    state?: T,
  ): Subscription {
    const dueTime = this.#currentTime + delay;
    // Bind work using a no-op SchedulerAction stub. The `as` cast is needed
    // because SchedulerAction extends Subscription (which has private fields),
    // making structural compatibility impossible without a runtime instance.
    const stub = new Subscription() as SchedulerAction<T>;
    const action: PendingAction = {
      dueTime,
      work: () => work.call(stub, state),
      cancelled: false,
    };
    this.#queue.push(action);
    this.#queue.sort((a, b) => a.dueTime - b.dueTime);
    return new FakeSchedulerSubscription(action);
  }

  /** Advance virtual time by `deltaMs` milliseconds, firing all due callbacks. */
  advanceBy(deltaMs: number): void {
    this.advanceTo(this.#currentTime + deltaMs);
  }

  /** Advance virtual time to exactly `targetMs`, firing all due callbacks in order. */
  advanceTo(targetMs: number): void {
    while (this.#queue.length > 0 && (this.#queue[0]?.dueTime ?? Infinity) <= targetMs) {
      const action = this.#queue.shift()!;
      if (!action.cancelled) {
        this.#currentTime = action.dueTime;
        action.work();
      }
    }
    this.#currentTime = targetMs;
  }
}
