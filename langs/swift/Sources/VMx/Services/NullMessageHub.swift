//
// NullMessageHub — null-object variant of `MessageHubProtocol`.
//
// See spec/03-messages.md §"Null variant" and ADR-0017.
//
import Foundation
import Combine

public final class NullMessageHub: TransactionalMessageHubProtocol, @unchecked Sendable {
    /// Shared singleton instance. The hub is stateless.
    public static let INSTANCE = NullMessageHub()

    private init() {}

    /// Empty publisher — completes immediately upon subscribe.
    public let messages: AnyPublisher<any Message, Never> =
        Empty<any Message, Never>(completeImmediately: true)
            .eraseToAnyPublisher()

    /// No-op send per ADR-0017.
    public func send(_ message: any Message) {
        // intentional no-op
    }

    /// Execute the transaction body while continuing to publish nothing.
    public func batch(_ transaction: () throws -> Void) throws {
        try transaction()
    }
}
