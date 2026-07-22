import VMx

/// Bridges VM state work onto the injected foreground dispatcher and resumes
/// only after the work has completed. The example keeps UI executor policy in
/// the host dispatcher instead of imposing `MainActor` on VMx protocols.
func performOnForeground<Value: Sendable>(
    using dispatcher: Dispatcher,
    _ work: @escaping () -> Value
) async -> Value {
    await withCheckedContinuation { continuation in
        dispatcher.scheduleForeground {
            continuation.resume(returning: work())
        }
    }
}

func performThrowingOnForeground<Value: Sendable>(
    using dispatcher: Dispatcher,
    _ work: @escaping () throws -> Value
) async throws -> Value {
    let result: Result<Value, any Error> = await performOnForeground(using: dispatcher) {
        Result(catching: work)
    }
    return try result.get()
}

extension ComponentVMBase {
    func runOnForeground<Value: Sendable>(
        _ work: @escaping () -> Value
    ) async -> Value {
        await performOnForeground(using: dispatcher, work)
    }
}

/// Narrow transfer boundary for the flagship's internally-created tasks.
/// State access still returns through `runOnForeground`; this box does not
/// declare the wrapped public VM generally Sendable.
final class FlagshipTransferBox<Value>: @unchecked Sendable {
    let value: Value

    init(_ value: Value) {
        self.value = value
    }
}

/// Publishes a transient notification without making the originating command
/// wait for the user's eventual resolution. `NotificationHub.post` deliberately
/// suspends until resolve/dispose, so awaiting it from save/delete/add would
/// deadlock command completion while the toast is still visible.
func publishNotification(
    _ notification: VMx.Notification,
    to hub: any NotificationHubProtocol
) {
    let transferableHub = FlagshipTransferBox(hub)
    let transferableNotification = FlagshipTransferBox(notification)
    Task { [transferableHub, transferableNotification] in
        _ = await transferableHub.value.post(transferableNotification.value)
    }
}
