/**
 * Internal: the hub message a VM collection publishes after each local
 * collection-change event (spec ch. 01 §1.4, ADR-0142).
 *
 * CompositeVM and GroupVM emit single-item local events, so each maps to one
 * `CollectionChangedMessage` with the same action, positions, and items, sent
 * by the container itself and carrying the container's name (ADR-0194).
 */
import { CollectionChangedMessage } from "../messages/collectionChanged.js";
import type { CollectionChangedEvent } from "./collectionChangedEvent.js";

export function collectionChangedMessageFor(
  container: { readonly name: string },
  event: CollectionChangedEvent,
): CollectionChangedMessage<unknown> {
  const name = container.name;
  switch (event.action) {
    case "add":
      return CollectionChangedMessage.forAdd(
        container,
        event.newItems[0],
        event.newIndex,
        name,
      );
    case "remove":
      return CollectionChangedMessage.forRemove(
        container,
        event.oldItems[0],
        event.oldIndex,
        name,
      );
    case "move":
      return CollectionChangedMessage.forMove(
        container,
        event.newItems[0],
        event.oldIndex,
        event.newIndex,
        name,
      );
    case "reset":
      return CollectionChangedMessage.forReset(container, name);
  }
}
