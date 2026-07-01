/**
 * MessageHub — hot Subject-backed pub/sub stream for IMessage events.
 *
 * See spec/03-messages.md for the hub contract (HUB-001..HUB-007).
 *
 * HUB-007: a subscriber throwing in its next handler must not break other
 * subscribers or stop the hub. rxjs v7 isolates observer failures and reports
 * them through config.onUnhandledError asynchronously; tests that intentionally
 * throw opt into scoped suppression in tests/setup.ts.
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
    // Per HUB-007: each subscriber is isolated by rxjs observer boundaries.
    return new Observable<IMessage>((subscriber) => {
      const sub = this.#subject.subscribe({
        next: (msg) => subscriber.next(msg),
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
