/**
 * Core message interfaces for the VMx hub.
 *
 * See spec/03-messages.md §IMessage shape.
 */

/**
 * Base message — every hub message implements this.
 *
 * `sender` is the runtime sender instance, exposed uniformly across all
 * flavors as the canonical field (ADR-0006 / ADR-0054). It is typed `unknown`
 * here because the untyped base cannot name a concrete sender type; the typed
 * {@link ITypedMessage} narrows it to `TSender`.
 */
export interface IMessage {
  readonly senderName: string;
  readonly sender: unknown;
}

/** Typed message — narrows {@link IMessage.sender} to a strongly-typed reference. */
export interface ITypedMessage<TSender> extends IMessage {
  readonly sender: TSender;
}
