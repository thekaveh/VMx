//
// Hub convenience helpers over `PropertyChangedMessage` (spec/03 §7, ADR-0050).
// Two small helpers every full-parity flavor ships — the Swift expression of the
// C#/Python/TypeScript `WhenPropertyChanged` / `PropertyValueChangedMessagesFor`
// hub extensions. Both are cold: each subscription attaches a fresh filter to the
// hub's `messages` stream.
//
import Combine

/// The canonical sender identity that the chapter 03 §7 helpers match
/// (spec/03 §7, ADR-0233). A forwarding decorator sends no message of its own:
/// the wrapped VM is the sender of each message it causes (ADR-0221), and nested
/// decorators resolve to the same innermost VM (ADR-0124). An object that is not
/// a VM is its own identity.
func canonicalSenderIdentity(_ sender: AnyObject) -> AnyObject {
    if let component = sender as? ComponentVMBase {
        return component._ownershipIdentity
    }
    return sender
}

public extension MessageHubProtocol {
    /// The stream of `PropertyChangedMessage`s published by `sender` for
    /// `propertyName` — the canonical typed primitive for a cross-VM subscription
    /// (spec/03 §7.2, ADR-0050). A decorator matches the messages of its wrapped
    /// VM (ADR-0233).
    func whenPropertyChanged(
        _ sender: AnyObject,
        _ propertyName: String
    ) -> AnyPublisher<PropertyChangedMessage, Never> {
        let identity = canonicalSenderIdentity(sender)
        return messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === identity && $0.propertyName == propertyName }
            .eraseToAnyPublisher()
    }

    /// The stream of `PropertyChangedMessage`s published by `sender` for any of
    /// the given property names (spec/03 §7.2, ADR-0160):
    /// `hub.whenPropertyChanged(chart, "plot", "range")`.
    ///
    /// Each subscription makes one subscription to `messages`. Each matching
    /// message is emitted once, in hub order, even when its name is passed more
    /// than once. The overload takes at least two names, so a one-name call
    /// always binds to `whenPropertyChanged(_:_:)` and a call without names does
    /// not compile.
    func whenPropertyChanged(
        _ sender: AnyObject,
        _ firstPropertyName: String,
        _ secondPropertyName: String,
        _ otherPropertyNames: String...
    ) -> AnyPublisher<PropertyChangedMessage, Never> {
        let names = Set([firstPropertyName, secondPropertyName] + otherPropertyNames)
        let identity = canonicalSenderIdentity(sender)
        return messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === identity && names.contains($0.propertyName) }
            .eraseToAnyPublisher()
    }

    /// The stream of `source`'s current `propertyName` value, read via `getter`
    /// each time that property changes on the hub (spec/03 §7.1, ADR-0050). The
    /// getter mirrors the C# `Func<TSource, TProperty>` / TS keyed read.
    func propertyValueChangedMessagesFor<Property>(
        _ source: AnyObject,
        _ propertyName: String,
        getter: @escaping () -> Property
    ) -> AnyPublisher<Property, Never> {
        whenPropertyChanged(source, propertyName)
            .map { _ in getter() }
            .eraseToAnyPublisher()
    }
}
