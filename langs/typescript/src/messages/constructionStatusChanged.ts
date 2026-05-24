/**
 * ConstructionStatusChangedMessage — emitted on every legal lifecycle transition.
 *
 * See spec/03-messages.md §ConstructionStatusChangedMessage.
 */
import type { IMessage } from "./types.js";
import { ConstructionStatus } from "../lifecycle/status.js";

export class ConstructionStatusChangedMessage implements IMessage {
  readonly senderObject: object;
  readonly senderName: string;
  readonly status: ConstructionStatus;

  private constructor(
    sender: object,
    senderName: string,
    status: ConstructionStatus,
  ) {
    this.senderObject = sender;
    this.senderName = senderName;
    this.status = status;
  }

  /**
   * Alias of {@link senderObject}. Matches the `sender` field on the C# and
   * Python flavors — kept as a getter to avoid duplicating storage and to
   * preserve the existing `senderObject` shape (spec/03-messages.md §Required
   * fields treats them as the same value).
   */
  get sender(): object {
    return this.senderObject;
  }

  static create(
    sender: object,
    senderName: string,
    status: ConstructionStatus,
  ): ConstructionStatusChangedMessage {
    return new ConstructionStatusChangedMessage(sender, senderName, status);
  }
}
