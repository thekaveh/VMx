/**
 * NullMessageHub — null-object variant of IMessageHub.
 *
 * See spec/03-messages.md §"Null variant" and ADR-0017.
 */
import { EMPTY, type Observable } from "rxjs";
import type { IMessage } from "../messages/types.js";
import type { IMessageHub } from "./messageHub.js";

export class NullMessageHub implements IMessageHub {
  /** Shared singleton instance (the hub holds no state). */
  static readonly INSTANCE: NullMessageHub = new NullMessageHub();

  private constructor() {}

  /** Empty observable — completes immediately upon subscribe. */
  readonly messages: Observable<IMessage> = EMPTY;

  /** No-op. */
  send(_message: IMessage): void {
    // intentional no-op per ADR-0017
  }
}
