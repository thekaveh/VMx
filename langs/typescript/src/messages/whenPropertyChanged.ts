/**
 * whenPropertyChanged — typed observable of PropertyChangedMessage events for a
 * specific sender + property (VMX-017).
 *
 * Replaces the hand-wired
 * `hub.messages.pipe(filter(m => m instanceof PropertyChangedMessage && m.sender === x && m.propertyName === "P"))`
 * filter that otherwise gets copy-pasted into every cross-VM binding. Unlike
 * {@link propertyValueChangedMessagesFor} (which maps to the property *value*),
 * this emits the matching message so the subscriber can react and read whatever
 * state it needs — mirroring the C# `IMessageHub.WhenPropertyChanged` helper.
 *
 * Informative-only (ADR-0032); the underlying `messages` stream is the
 * conformance-tested contract.
 *
 * See spec/03-messages.md §"Convenience helpers".
 */
import { filter, type Observable } from "rxjs";
import { PropertyChangedMessage } from "./propertyChanged.js";
import type { IMessage } from "./types.js";

/** Minimal hub shape required by the helper. */
interface IHubLike {
  readonly messages: Observable<IMessage>;
}

/**
 * Returns the stream of {@link PropertyChangedMessage} events published to `hub`
 * by `sender` for the property named `propertyName`. Sender identity is compared
 * by reference.
 *
 * @param hub - The message hub to observe.
 * @param sender - The sender instance to match (identity check).
 * @param propertyName - Name of the property to match.
 */
export function whenPropertyChanged(
  hub: IHubLike,
  sender: object,
  propertyName: string,
): Observable<PropertyChangedMessage<unknown>> {
  return hub.messages.pipe(
    filter(
      (m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage &&
        m.sender === sender &&
        m.propertyName === propertyName,
    ),
  );
}
