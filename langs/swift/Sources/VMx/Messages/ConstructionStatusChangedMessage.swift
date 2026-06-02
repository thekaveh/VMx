//
// ConstructionStatusChangedMessage — emitted on every legal lifecycle
// transition.
//
// See spec/03-messages.md §ConstructionStatusChangedMessage.
//
import Foundation

public struct ConstructionStatusChangedMessage: Message {
    public let senderObject: AnyObject
    public let senderName: String
    public let status: ConstructionStatus

    public init(sender: AnyObject, senderName: String, status: ConstructionStatus) {
        self.senderObject = sender
        self.senderName = senderName
        self.status = status
    }

    /// Spec alias of `senderObject` — matches the `Sender` / `sender`
    /// field on the C# and Python flavors.
    public var sender: AnyObject { senderObject }
}
