//
// ImmediateDispatcher — test-friendly dispatcher that runs every
// scheduled closure synchronously on the calling thread.
//
// Equivalent to `RxDispatcher.immediate()` in TS / Python and
// `RxDispatcher.Immediate()` in C#.
//
import Foundation

public final class ImmediateDispatcher: Dispatcher {
    /// Shared singleton — the dispatcher holds no state.
    public static let INSTANCE = ImmediateDispatcher()

    public init() {}

    public func scheduleForeground(_ work: @escaping () -> Void) {
        work()
    }

    public func scheduleBackground(_ work: @escaping () -> Void) {
        work()
    }
}
