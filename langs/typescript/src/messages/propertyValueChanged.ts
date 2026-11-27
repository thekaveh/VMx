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
import type { IMessageHub } from "../services/messageHub.js";
import { canonicalSender } from "./canonicalSender.js";
import { PropertyChangedMessage } from "./propertyChanged.js";

/**
 * Returns an observable that emits the current value of `propertyName` on `source`
 * each time a matching `PropertyChangedMessage` arrives on the hub.
 *
 * @param hub - The message hub to filter.
 * @param source - The specific sender instance to watch. It is compared by its
 *   canonical identity, so a forwarding decorator matches its wrapped VM (ADR-0233).
 * @param propertyName - Name of the property to observe.
 * @returns Cold observable of property values (snapshotted at delivery time).
 */
export function propertyValueChangedMessagesFor<TSource extends object>(
  hub: Pick<IMessageHub, "messages">,
  source: TSource,
  propertyName: keyof TSource & string,
): Observable<unknown> {
  const identity = canonicalSender(source);
  return hub.messages.pipe(
    filter(
      (msg): msg is PropertyChangedMessage<TSource> =>
        msg instanceof PropertyChangedMessage &&
        msg.sender === identity &&
        msg.propertyName === propertyName,
    ),
    map((_msg) => (source as Record<string, unknown>)[propertyName]),
  );
}
