//
// Message — base protocol for every hub envelope.
//
// See spec/03-messages.md §IMessage shape.
//
import Foundation

/// Base message — every hub message conforms to this. Mirrors `IMessage`
/// in the C# / Python / TS flavors.
public protocol Message {
    /// Identifier of the sender (matches `name` on a VM).
    var senderName: String { get }
    /// Reference to the sender object. AnyObject so subscribers can compare
    /// by identity (`===`) across heterogeneous message kinds.
    var senderObject: AnyObject { get }
}
