import { useCallback, useRef } from "react";
import type { IMessageHub } from "@thekaveh/vmx";

import { useVersionedSelector } from "./internal/useVersionedSelector.js";

function sameItems<T>(current: readonly T[], next: readonly T[]): boolean {
  return current.length === next.length &&
    current.every((item, index) => Object.is(item, next[index]));
}

/**
 * Return a cached snapshot of a hierarchical node's children (`HierarchicalVM`
 * or any node with a `hub` and a `children` list). The snapshot refreshes on:
 *
 * - add and reparent into the node: the node publishes `TreeStructureChanged`;
 * - remove: the node publishes `TreeStructureChanged`, and the removed child
 *   publishes its `Parent` change;
 * - reparent away: the new parent publishes `Reparented`, which this node does
 *   not see. The moved child publishes its `Parent` change, and the child
 *   belonged to the last snapshot, so the hook refreshes;
 * - invalidation: `invalidateChildren` publishes a `children` property change
 *   from the node.
 *
 * The reparent-away and remove cases need the children to publish on the same
 * hub as the node, which is the normal setup when nodes share one hub.
 */
export function useVmChildren<TVm extends object>(
  node: { readonly hub: IMessageHub; readonly children: readonly TVm[] },
): readonly TVm[] {
  // The children from the last selector run. A message from one of them can
  // be its `Parent` change after it has left the node's list.
  const lastChildrenRef = useRef<readonly TVm[]>([]);

  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => {
      const subscription = node.hub.messages.subscribe({
        next: (message) => {
          const fromNode = message.sender === node;
          const fromPreviousChild = lastChildrenRef.current.some(
            (child) => child === message.sender,
          );
          if (fromNode || fromPreviousChild) invalidate();
        },
      });
      return () => subscription.unsubscribe();
    },
    [node],
  );

  // `node.children` is the core's cached array, which the core mutates in
  // place. Copy it so each snapshot is a new array, and keep the previous
  // array when the items are unchanged.
  return useVersionedSelector(
    sourceSubscribe,
    () => {
      const items = Array.from(node.children);
      lastChildrenRef.current = items;
      return items;
    },
    sameItems,
  );
}
