/**
 * MessageHub — hot Subject-backed pub/sub stream for IMessage events.
 *
 * See spec/03-messages.md for the hub contract (HUB-001..HUB-013).
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

/** Additive capability for hubs that support lossless message transactions. */
export interface ITransactionalMessageHub extends IMessageHub {
  batch(transaction: () => void): void;
}

export interface MessageHubOptions {
  /**
   * Enable the bounded development cycle diagnostic. Node development/test
   * processes enable it automatically; browser hosts opt in because the web
   * platform has no standard development-mode flag.
   */
  readonly developmentDiagnostics?: boolean;
}

const DEVELOPMENT_DRAIN_LIMIT = 10_000;
const NODE_ENV = typeof process === "undefined" ? undefined : process.env.NODE_ENV;
const NODE_DEVELOPMENT_DIAGNOSTICS = NODE_ENV === "development" || NODE_ENV === "test";

export class MessageHub implements ITransactionalMessageHub {
  readonly #subject = new Subject<IMessage>();
  readonly #pending: IMessage[] = [];
  readonly #developmentDiagnostics: boolean;
  #pendingHead = 0;
  #disposed = false;
  #draining = false;
  #batchDepth = 0;

  constructor(options: MessageHubOptions = {}) {
    this.#developmentDiagnostics =
      options.developmentDiagnostics ?? NODE_DEVELOPMENT_DIAGNOSTICS;
  }

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
    if (this.#disposed) return;
    this.#pending.push(message);
    if (this.#batchDepth === 0 && !this.#draining) this.#drain();
  }

  batch(transaction: () => void): void {
    this.#batchDepth++;
    let callbackFailed = false;
    let callbackError: unknown;
    try {
      transaction();
    } catch (error) {
      callbackFailed = true;
      callbackError = error;
    }

    this.#batchDepth--;
    let drainFailed = false;
    let drainError: unknown;
    if (this.#batchDepth === 0 && !this.#disposed && !this.#draining) {
      try {
        this.#drain();
      } catch (error) {
        drainFailed = true;
        drainError = error;
      }
    }

    if (callbackFailed) throw callbackError;
    if (drainFailed) throw drainError;
  }

  #drain(): void {
    this.#draining = true;
    let delivered = 0;
    const messageTypes = new Set<string>();
    try {
      while (!this.#disposed && this.#pendingHead < this.#pending.length) {
        const message = this.#pending[this.#pendingHead++];
        if (message === undefined) continue;
        if (this.#developmentDiagnostics) {
          messageTypes.add(message.constructor.name || "IMessage");
        }
        this.#subject.next(message);
        if (this.#developmentDiagnostics) {
          delivered++;
          if (delivered >= DEVELOPMENT_DRAIN_LIMIT && this.#pendingHead < this.#pending.length) {
            for (let i = this.#pendingHead; i < this.#pending.length; i++) {
              const pending = this.#pending[i];
              if (pending !== undefined) messageTypes.add(pending.constructor.name || "IMessage");
            }
            this.#pending.length = 0;
            this.#pendingHead = 0;
            throw new Error(
              `MessageHub drain exceeded ${String(DEVELOPMENT_DRAIN_LIMIT)} messages; ` +
              `possible publish cycle involving: ${[...messageTypes].sort().join(", ")}`,
            );
          }
        }
      }
    } finally {
      if (this.#disposed || this.#pendingHead >= this.#pending.length) {
        this.#pending.length = 0;
        this.#pendingHead = 0;
      }
      this.#draining = false;
    }
  }

  dispose(): void {
    if (!this.#disposed) {
      this.#disposed = true;
      this.#pending.length = 0;
      this.#pendingHead = 0;
      this.#subject.complete();
    }
  }
}
