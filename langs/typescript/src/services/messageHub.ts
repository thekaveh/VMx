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
  #disposed = false;

  get messages(): Observable<IMessage> {
    // Per HUB-007: wrap each subscription so subscriber exceptions are swallowed.
    return new Observable<IMessage>((subscriber) => {
      const sub = this.#subject.subscribe({
        next: (msg) => {
          try {
            subscriber.next(msg);
          } catch {
            // swallow per HUB-007
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
