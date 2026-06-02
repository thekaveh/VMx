//
// Dispatcher — paired foreground / background work scheduler.
//
// See spec/11-threading.md for the threading contract. Swift uses
// `DispatchQueue` as the foreground/background primitive, mirroring the
// Rx Scheduler used by the C# / Python / TS flavors.
//
import Foundation

/// Pair of execution targets for VMx work. Mirrors `IDispatcher` in the
/// other flavors. A dispatcher is intentionally just a "schedule this
/// closure" surface — the receiving side decides whether the closure
/// runs synchronously or hops to a queue.
public protocol Dispatcher: AnyObject {
    /// Schedule `work` on the foreground execution target. Implementations
    /// MAY run `work` synchronously on the calling thread (see
    /// `ImmediateDispatcher`) or asynchronously on a dedicated queue.
    func scheduleForeground(_ work: @escaping () -> Void)

    /// Schedule `work` on the background execution target. Same
    /// synchronous-vs-async rules apply.
    func scheduleBackground(_ work: @escaping () -> Void)
}

/// Default dispatcher: foreground hops to the main queue (asynchronously
/// when called off-main), background hops to a user-initiated global
/// queue. Suitable for production apps. Tests should prefer
/// `ImmediateDispatcher` for determinism.
public final class DefaultDispatcher: Dispatcher {
    public init() {}

    public func scheduleForeground(_ work: @escaping () -> Void) {
        if Thread.isMainThread {
            work()
        } else {
            DispatchQueue.main.async(execute: work)
        }
    }

    public func scheduleBackground(_ work: @escaping () -> Void) {
        DispatchQueue.global(qos: .userInitiated).async(execute: work)
    }
}
