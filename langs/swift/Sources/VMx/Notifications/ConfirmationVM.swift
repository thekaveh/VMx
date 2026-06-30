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

    public override init(
        notification: Notification,
        hub: NotificationHubProtocol,
        scheduler: VirtualTimeScheduler,
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

    /// Disposes the approve/reject commands, then delegates to the base.
    public override func dispose() {
        approveCommand.dispose()
        rejectCommand.dispose()
        super.dispose()
    }
}
