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

  static create(
    sender: object,
    senderName: string,
    status: ConstructionStatus,
  ): ConstructionStatusChangedMessage {
    return new ConstructionStatusChangedMessage(sender, senderName, status);
  }
}
