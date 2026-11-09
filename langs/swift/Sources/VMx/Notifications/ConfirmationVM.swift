//
// ConfirmationVM — render-side ViewModel for a confirmation Notification.
//
// See spec/16-notifications.md §7 and ADR-0031.
//
// Extends `NotificationVM` with explicit `approveCommand` / `rejectCommand` and
// a longer default lifespan (300 s). Unlike `NotificationVM`, it does NOT
// auto-resolve on lifespan expiry — a timeout means "user did not decide", so
// the notification stays pending until an explicit action.
//
import Foundation
import Combine

public final class ConfirmationVM: NotificationVM {

    /// Resolves the hub with `.approve`.
    public let approveCommand: RelayCommand
    /// Resolves the hub with `.reject`.
    public let rejectCommand: RelayCommand

    /// - Parameter scheduler: Measures the lifespan for `remaining` and
    ///   `opacity`, and drives the decay ticks. Pass a real-time scheduler such
    ///   as `DispatchQueue.main` in an app, and a `VirtualTimeScheduler` in
    ///   tests. The lifespan never resolves the notification.
    public override init<S: NotificationScheduler>(
        notification: Notification,
        hub: NotificationHubProtocol,
        scheduler: S,
        lifespan: TimeInterval = 300,
        tickInterval: TimeInterval = 0
    ) {
        // Build the commands via a weak local so the closures never capture
        // `self` before initialization completes; `weakSelf` is bound after
        // `super.init`. Subclass stored properties must be set before super.init.
        weak var weakSelf: ConfirmationVM?
        self.approveCommand = RelayCommand.builder()
            .task { weakSelf?.resolveWith(.approve) }
            .build()
        self.rejectCommand = RelayCommand.builder()
            .task { weakSelf?.resolveWith(.reject) }
            .build()
        super.init(
            notification: notification,
            hub: hub,
            scheduler: scheduler,
            lifespan: lifespan,
            tickInterval: tickInterval
        )
        weakSelf = self
    }

    /// ConfirmationVM never auto-resolves, so it declines to arm the lifespan
    /// expiry timer — there is no work to do on fire.
    public override func armsExpiryTimer() -> Bool { false }

    /// Defensive no-op: ConfirmationVM requires an explicit user action.
    /// (No timer is armed, so this is never reached unless a subclass re-arms.)
    public override func onExpire() {
        // Intentional no-op. Timeout means "user did not decide".
    }

    /// Delegates to the base, then disposes the approve/reject commands. The
    /// base marks the VM disposed first, so an observer that runs while a
    /// command is disposed cannot resolve the hub (#753).
    public override func dispose() {
        super.dispose()
        approveCommand.dispose()
        rejectCommand.dispose()
    }
}
