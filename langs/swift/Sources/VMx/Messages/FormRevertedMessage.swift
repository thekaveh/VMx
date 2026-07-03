//
// FormRevertedMessage — emitted when a FormVM reverts its model to snapshot.
//
// See spec/20-form-vm.md §8 — Hub messages.
//
import Foundation

/// Hub envelope broadcast by ``FormVM`` when `denyCommand` is executed and
/// the live model is reverted to the current snapshot.
///
/// Mirrors `FormRevertedMessage` in the C# / Python / TS flavors.
public struct FormRevertedMessage: Message {
    public let senderObject: AnyObject
    public let senderName: String

    public init(senderObject: AnyObject, senderName: String) {
        self.senderObject = senderObject
        self.senderName = senderName
    }

    /// Spec alias of `senderObject`. Provided to match the C# / Python
    /// `Sender` / `sender` field name.
    public var sender: AnyObject { senderObject }
}
