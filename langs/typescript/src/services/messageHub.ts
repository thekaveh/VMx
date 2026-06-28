/**
 * MessageHub — hot Subject-backed pub/sub stream for IMessage events.
 *
 * See spec/03-messages.md for the hub contract (HUB-001..HUB-007).
 *
 * HUB-007: a subscriber throwing in its next handler must not break other
 * subscribers or stop the hub. Each subscription is individually wrapped in
 * a try-catch inside send(). rxjs v7 may still route caught errors through
 * reportUnhandledError asynchronously; the test setup (tests/setup.ts) patches
 * config.onUnhandledError to suppress those surfaced exceptions.
 */
import { Subject, Observable } from "rxjs";
import type { IMessage } from "../messages/types.js";

export interface IMessageHub {
  readonly messages: Observable<IMessage>;
  send(message: IMessage): void;
}

export class MessageHub implements IMessageHub {
  readonly #subject = new Subject<IMessage>();
  readonly #onSubscriberError:
    | ((error: unknown, message: IMessage) => void)
    | null;
  #disposed = false;

  /**
   * @param onSubscriberError Optional diagnostic sink invoked when a
   *   subscriber's next-handler throws synchronously (HUB-007). The hub still
   *   isolates the failure from other subscribers; this hook lets a host
   *   observe what was swallowed (logging/metrics) instead of dropping it
   *   silently (VMX-085). Omit it to preserve the prior silent-swallow behavior.
   */
  constructor(
    onSubscriberError?: (error: unknown, message: IMessage) => void,
  ) {
    this.#onSubscriberError = onSubscriberError ?? null;
  }

  get messages(): Observable<IMessage> {
    // Per HUB-007: wrap each subscription so subscriber exceptions are isolated.
    return new Observable<IMessage>((subscriber) => {
      const sub = this.#subject.subscribe({
        next: (msg) => {
          try {
            subscriber.next(msg);
          } catch (error) {
            // HUB-007: isolate the throwing subscriber. Surface to the optional
            // diagnostic sink (VMX-085) rather than dropping it silently.
            this.#onSubscriberError?.(error, msg);
          }
        },
        error: (err: unknown) => subscriber.error(err),
        complete: () => subscriber.complete(),
      });
      return () => sub.unsubscribe();
    });
  }

  send(message: IMessage): void {
    if (!this.#disposed) {
      this.#subject.next(message);
    }
  }

  dispose(): void {
    if (!this.#disposed) {
      this.#disposed = true;
      this.#subject.complete();
    }
  }
}
