//
// PropertyChangedMessage — emitted when a VM property changes value.
//
// See spec/03-messages.md §PropertyChangedMessage.
//
import Foundation

/// Property-changed hub envelope. The sender field is type-erased to
/// `AnyObject`; subscribers may downcast or filter via identity check.
public struct PropertyChangedMessage: Message {
    public let senderObject: AnyObject
    public let senderName: String
    public let propertyName: String

    public init(sender: AnyObject, senderName: String, propertyName: String) {
        self.senderObject = sender
        self.senderName = senderName
        self.propertyName = propertyName
    }

    /// Spec alias of `senderObject`. Provided to match the C# / Python
    /// `Sender` / `sender` field name.
    public var sender: AnyObject { senderObject }
}
