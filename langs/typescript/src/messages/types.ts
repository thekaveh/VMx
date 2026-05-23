/**
 * Core message interfaces for the VMx hub.
 *
 * See spec/03-messages.md §IMessage shape.
 */

/** Base message — every hub message implements this. */
export interface IMessage {
  readonly senderName: string;
  readonly senderObject: object;
}

/** Typed message — carries a strongly-typed sender reference. */
export interface ITypedMessage<TSender> extends IMessage {
  readonly sender: TSender;
}
