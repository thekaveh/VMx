import {
  Subscription,
  VirtualTimeScheduler,
  type SchedulerAction,
  type SchedulerLike,
} from "rxjs";
import { RxDispatcher, type IDispatcher } from "../services/dispatcher.js";
import { RecordingMessageHub } from "./recordingMessageHub.js";

class ManualScheduler implements SchedulerLike {
  readonly #scheduler = new VirtualTimeScheduler();
  readonly #scheduled = new Subscription();
  #disposed = false;

  now(): number {
    return this.#scheduler.now();
  }

  schedule<T>(
    work: (this: SchedulerAction<T>, state?: T) => void,
    delay = 0,
    state?: T,
  ): Subscription {
    if (this.#disposed) return Subscription.EMPTY;
    const action = this.#scheduler.schedule(work, delay, state);
    this.#scheduled.add(action);
    return action;
  }

  flush(): void {
    if (!this.#disposed) this.#scheduler.flush();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#scheduled.unsubscribe();
  }
}

/** Dispatcher whose foreground and background queues advance only on demand. */
export class ManualDispatcher implements IDispatcher {
  readonly #foreground = new ManualScheduler();
  readonly #background = new ManualScheduler();

  readonly foreground: SchedulerLike = this.#foreground;
  readonly background: SchedulerLike = this.#background;

  flushForeground(): void {
    this.#foreground.flush();
  }

  flushBackground(): void {
    this.#background.flush();
  }

  flushAll(): void {
    this.flushForeground();
    this.flushBackground();
  }

  dispose(): void {
    this.#foreground.dispose();
    this.#background.dispose();
  }
}

export interface TestServices {
  readonly hub: RecordingMessageHub;
  readonly dispatcher: IDispatcher;
  dispose(): void;
}

/** Create the standard hermetic VMx service pair for a unit test. */
export function createTestServices(): TestServices {
  const hub = new RecordingMessageHub();
  const dispatcher = RxDispatcher.immediate();
  let disposed = false;
  return {
    hub,
    dispatcher,
    dispose: () => {
      if (disposed) return;
      disposed = true;
      hub.dispose();
    },
  };
}
