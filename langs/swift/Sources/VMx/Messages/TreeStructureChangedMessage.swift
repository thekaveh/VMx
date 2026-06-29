//
// TreeStructureChangedMessage — published on the message hub when a
// HierarchicalVM subtree changes structurally (add / remove / reparent).
//
// See spec/18-hierarchical-vm.md §6 and ADR-0028 §3.4.
//
import Foundation

/// Discriminated enum for the structural mutation that occurred.
public enum TreeStructureChange: Sendable, Equatable {
    case added
    case removed
    case reparented
}

/// Message published when a HierarchicalVM's children list mutates.
///
/// `sender` (via `senderObject`) is the node whose children list changed
/// (the parent that called `addChild` / `removeChild` / `reparentChild`).
/// `affected` is the child node that was added, removed, or reparented.
/// `index` is the position in the children list; -1 when not applicable
/// (reparent).
public struct TreeStructureChangedMessage: Message {
    public let senderObject: AnyObject
    public let senderName: String
    public let change: TreeStructureChange
    public let affected: ComponentVMBase
    /// Index in the children list at which the change occurred; -1 for reparent.
    public let index: Int

    public init(
        sender: AnyObject,
        senderName: String,
        change: TreeStructureChange,
        affected: ComponentVMBase,
        index: Int
    ) {
        self.senderObject = sender
        self.senderName = senderName
        self.change = change
        self.affected = affected
        self.index = index
    }

    /// Spec alias of `senderObject`. Matches the `PropertyChangedMessage`
    /// convention.
    public var sender: AnyObject { senderObject }
}
