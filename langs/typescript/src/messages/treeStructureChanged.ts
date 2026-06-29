/**
 * TreeStructureChangedMessage — published on the message hub when a
 * HierarchicalVM subtree changes structurally (add / remove / reparent).
 *
 * See spec/18-hierarchical-vm.md §6 and ADR-0028 §3.4.
 */
import type { IMessage } from "./types.js";

/** Discriminated union for the structural mutation that occurred. */
export type TreeStructureChange = "added" | "removed" | "reparented";

/**
 * Message published when a HierarchicalVM's children list mutates.
 *
 * @param TSource - Type of the node whose subtree changed.
 * @param TAffected - Type of the node added, removed, or reparented.
 */
export class TreeStructureChangedMessage<TSource, TAffected>
  implements IMessage
{
  readonly sender: TSource;
  readonly senderName: string;
  readonly change: TreeStructureChange;
  readonly affected: TAffected;
  /** Index in the children list at which the change occurred; -1 when not applicable. */
  readonly index: number;

  constructor(
    sender: TSource,
    senderName: string,
    change: TreeStructureChange,
    affected: TAffected,
    index: number,
  ) {
    this.sender = sender;
    this.senderName = senderName;
    this.change = change;
    this.affected = affected;
    this.index = index;
  }
}
