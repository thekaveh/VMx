//
// NullDispatcher — null-object variant of `Dispatcher`.
//
// See spec/11-threading.md §"Null variant" and ADR-0017. Both targets
// run synchronously on the calling thread, matching `NullDispatcher`
// behavior in the other flavors.
//
import Foundation

public final class NullDispatcher: Dispatcher {
    /// Shared singleton instance.
    public static let INSTANCE = NullDispatcher()

    private init() {}

    public func scheduleForeground(_ work: @escaping () -> Void) {
        work()
    }

    public func scheduleBackground(_ work: @escaping () -> Void) {
        work()
    }
}
