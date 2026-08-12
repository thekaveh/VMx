import type { Observable, Subscription } from "rxjs";
import type { IMessage } from "../messages/types.js";
import {
  MessageHub,
  type ITransactionalMessageHub,
  type MessageHubOptions,
} from "../services/messageHub.js";

/** A real MessageHub that also retains messages in their delivered order. */
export class RecordingMessageHub implements ITransactionalMessageHub {
  readonly #hub: MessageHub;
  readonly #recordingSubscription: Subscription;
  readonly #records: IMessage[] = [];
  #disposed = false;

  constructor(options: MessageHubOptions = {}) {
    this.#hub = new MessageHub(options);
    this.#recordingSubscription = this.#hub.messages.subscribe((message) => {
      this.#records.push(message);
    });
  }

  get messages(): Observable<IMessage> {
    return this.#hub.messages;
  }

  /** A copy of the messages delivered so far. */
  get records(): readonly IMessage[] {
    return [...this.#records];
  }

  send(message: IMessage): void {
    if (this.#disposed) return;
    this.#hub.send(message);
  }

  batch(transaction: () => void): void {
    if (this.#disposed) return;
    this.#hub.batch(transaction);
  }

  clear(): void {
    this.#records.length = 0;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#recordingSubscription.unsubscribe();
    this.#hub.dispose();
  }
}
