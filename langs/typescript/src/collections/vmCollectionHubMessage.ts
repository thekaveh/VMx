/**
 * Internal: the hub message a VM collection publishes after each local
 * collection-change event (spec ch. 01 §1.4, ADR-0142).
 *
 * CompositeVM and GroupVM emit single-item local events, so each maps to one
 * `CollectionChangedMessage` with the same action, positions, and items, sent
 * by the container itself.
 */
import { CollectionChangedMessage } from "../messages/collectionChanged.js";
import type { CollectionChangedEvent } from "./collectionChangedEvent.js";

export function collectionChangedMessageFor(
  sender: object,
  event: CollectionChangedEvent,
): CollectionChangedMessage<unknown> {
  switch (event.action) {
    case "add":
      return CollectionChangedMessage.forAdd(sender, event.newItems[0], event.newIndex);
    case "remove":
      return CollectionChangedMessage.forRemove(sender, event.oldItems[0], event.oldIndex);
    case "move":
      return CollectionChangedMessage.forMove(
        sender,
        event.newItems[0],
        event.oldIndex,
        event.newIndex,
      );
    case "reset":
      return CollectionChangedMessage.forReset(sender);
  }
}
