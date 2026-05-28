/**
 * propertyValueChangedMessagesFor — value-returning observable over PropertyChangedMessage.
 *
 * Convenience helper over the message hub. Instead of filtering the full message stream and
 * extracting the sender property manually, this function returns an Observable<unknown> that
 * emits the current value of the named property on the sender each time a matching
 * PropertyChangedMessage arrives.
 *
 * This helper is informative-only (ADR-0032); the underlying `messages` stream on the hub
 * is the conformance-tested contract.
 *
 * See spec/03-messages.md §"Convenience helpers".
 */
import { filter, map, Observable } from "rxjs";
import { PropertyChangedMessage } from "./propertyChanged.js";
import type { IMessage } from "./types.js";

/** Minimal hub shape required by the helper. */
interface IHubLike {
  readonly messages: Observable<IMessage>;
}

/**
 * Returns an observable that emits the current value of `propertyName` on `source`
 * each time a matching `PropertyChangedMessage` arrives on the hub.
 *
 * @param hub - The message hub to filter.
 * @param source - The specific sender instance to watch (identity check).
 * @param propertyName - Name of the property to observe.
 * @returns Cold observable of property values (snapshotted at delivery time).
 */
export function propertyValueChangedMessagesFor<TSource extends object>(
  hub: IHubLike,
  source: TSource,
  propertyName: keyof TSource & string,
): Observable<unknown> {
  return hub.messages.pipe(
    filter(
      (msg): msg is PropertyChangedMessage<TSource> =>
        msg instanceof PropertyChangedMessage &&
        msg.sender === source &&
        msg.propertyName === propertyName,
    ),
    map((_msg) => (source as Record<string, unknown>)[propertyName]),
  );
}
