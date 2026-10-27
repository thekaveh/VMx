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
 * Pass an array to watch several properties of one sender (spec/03 §7.2,
 * ADR-0160): `whenPropertyChanged(hub, chart, ["plot", "range"])`. A message
 * matches when its `propertyName` equals any of the names. Each subscription
 * makes one subscription to `hub.messages`, and each matching message is
 * emitted once, in hub order, even when its name appears more than once in the
 * array. The names are copied when the function is called, so a later change
 * to the array has no effect. A single string behaves as before.
 *
 * @param hub - The message hub to observe.
 * @param sender - The sender instance to match (identity check).
 * @param propertyName - Name of the property to match, or a non-empty array of
 *   names to match.
 * @throws RangeError if `propertyName` is an empty array.
 */
export function whenPropertyChanged(
  hub: IHubLike,
  sender: object,
  propertyName: string | readonly string[],
): Observable<PropertyChangedMessage<unknown>> {
  if (typeof propertyName === "string") {
    return hub.messages.pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage &&
          m.sender === sender &&
          m.propertyName === propertyName,
      ),
    );
  }
  if (propertyName.length === 0) {
    throw new RangeError("whenPropertyChanged requires at least one property name.");
  }
  const names: ReadonlySet<string> = new Set(propertyName);
  return hub.messages.pipe(
    filter(
      (m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage &&
        m.sender === sender &&
        names.has(m.propertyName),
    ),
  );
}
