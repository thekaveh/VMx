/**
 * PropertyChangedMessage — emitted when a VM property changes value.
 *
 * See spec/03-messages.md §PropertyChangedMessage.
 */
import type { ITypedMessage } from "./types.js";

export class PropertyChangedMessage<TSender>
  implements ITypedMessage<TSender>
{
  readonly sender: TSender;
  readonly senderName: string;
  readonly propertyName: string;

  private constructor(
    sender: TSender,
    senderName: string,
    propertyName: string,
  ) {
    this.sender = sender;
    this.senderName = senderName;
    this.propertyName = propertyName;
  }

  static create<TSender>(
    sender: TSender,
    senderName: string,
    propertyName: string,
  ): PropertyChangedMessage<TSender> {
    return new PropertyChangedMessage(sender, senderName, propertyName);
  }
}
