/**
 * NullMessageHub — null-object variant of IMessageHub.
 *
 * See spec/03-messages.md §"Null variant" and ADR-0017.
 */
import { EMPTY, type Observable } from "rxjs";
import type { IMessage } from "../messages/types.js";
import type { ITransactionalMessageHub } from "./messageHub.js";

export class NullMessageHub implements ITransactionalMessageHub {
  /** Shared singleton instance (the hub holds no state). */
  static readonly INSTANCE: NullMessageHub = new NullMessageHub();

  private constructor() {}

  /** Empty observable — completes immediately upon subscribe. */
  readonly messages: Observable<IMessage> = EMPTY;

  /** No-op. */
  send(_message: IMessage): void {
    // intentional no-op per ADR-0017
  }

  /** Execute a transaction body while continuing to publish nothing. */
  batch(transaction: () => void): void {
    transaction();
  }
}
