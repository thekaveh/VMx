//
// Hub convenience helpers over `PropertyChangedMessage` (spec/03 §7, ADR-0050).
// Two small helpers every full-parity flavor ships — the Swift expression of the
// C#/Python/TypeScript `WhenPropertyChanged` / `PropertyValueChangedMessagesFor`
// hub extensions. Both are cold: each subscription attaches a fresh filter to the
// hub's `messages` stream.
//
import Combine

public extension MessageHubProtocol {
    /// The stream of `PropertyChangedMessage`s published by `sender` for
    /// `propertyName` — the canonical typed primitive for a cross-VM subscription
    /// (spec/03 §7.2, ADR-0050).
    func whenPropertyChanged(
        _ sender: AnyObject,
        _ propertyName: String
    ) -> AnyPublisher<PropertyChangedMessage, Never> {
        messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { $0.sender === sender && $0.propertyName == propertyName }
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
