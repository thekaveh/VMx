//
// NotificationVM — render-side ViewModel for a Notification.
//
// See spec/16-notifications.md §6 and ADR-0031.
//
// Consumes a `Notification` and exposes UI-bindable state with a timed
// auto-dismiss lifecycle, driven by an injected `VirtualTimeScheduler`:
//
//   - `opacity` decays linearly 1.0 → 0.0 over `lifespan` as the scheduler's
//     virtual `now` advances (NOTIF-011).
//   - at expiry (`now` reaches `start + lifespan`) the VM auto-resolves the hub
//     notification with `.approve` (NOTIF-012); `ConfirmationVM` opts out.
//   - `dismissCommand` resolves `.approve` and cancels the timer (NOTIF-014).
//   - an external `hub.resolve(...)` is observed via `hub.pending` and flips
//     `isResolved` + cancels the timer (NOTIF-015).
//
// Time unit: SECONDS (`TimeInterval`) throughout — `lifespan`, `remaining`, and
// the scheduler all measure seconds, so a `lifespan` of 10 advanced to 5 yields
// `opacity` 0.5. `propertyChanged` emits Swift-idiomatic property names
// (`"isResolved"`, `"remaining"`, `"opacity"`).
//
// `open` (not `final`): `ConfirmationVM` subclasses it and overrides
// `armsExpiryTimer()` / `onExpire()` / `dispose()`.
//
import Foundation
import Combine

open class NotificationVM {

    // MARK: - Stored state

    private let notificationRef: Notification
    private let hub: NotificationHubProtocol
    private let scheduler: VirtualTimeScheduler
    private let tickInterval: TimeInterval
    private let emitsDecayTicks: Bool
    /// Virtual instant (seconds) captured at construction; opacity decay and
    /// the expiry timer are measured relative to it.
    private let startTime: TimeInterval

    private let propertyChangedSubject = PassthroughSubject<String, Never>()

    private var resolved = false
    private var disposed = false
    private var timerCancellable: AnyCancellable?
    private var tickCancellable: AnyCancellable?
    private var pendingCancellable: AnyCancellable?

    // MARK: - Public surface

    /// Configured lifespan in seconds (default 60). Read-only.
    public let lifespan: TimeInterval

    /// Resolves with `.approve` and cancels the timer. Idempotent.
    public let dismissCommand: RelayCommand

    public init(
        notification: Notification,
        hub: NotificationHubProtocol,
        scheduler: VirtualTimeScheduler,
        lifespan: TimeInterval = 60,
        tickInterval: TimeInterval = 0
    ) {
        self.notificationRef = notification
        self.hub = hub
        self.scheduler = scheduler
        self.lifespan = lifespan
        self.tickInterval = tickInterval
        self.emitsDecayTicks = tickInterval > 0 && lifespan > 0
        self.startTime = scheduler.now.seconds

        // Build the dismiss command via a weak local so we never reference
        // `self` before initialization completes. `weakSelf` is assigned after
        // every stored property is set (below).
        weak var weakSelf: NotificationVM?
        self.dismissCommand = RelayCommand.builder()
            .task { weakSelf?.dismiss() }
            .build()
        weakSelf = self  // self fully initialized — safe to use below

        // Arm the lifespan expiry timer unless a subclass opts out (e.g.
        // ConfirmationVM never auto-resolves). `armsExpiryTimer()` is an open
        // hook resolved via dynamic dispatch, so the subclass override runs.
        if armsExpiryTimer() {
            let expireAt = scheduler.now.advanced(by: .seconds(lifespan))
            self.timerCancellable = scheduler.schedule(at: expireAt) { [weak self] in
                self?.onExpire()
            }
        }

        // Detect EXTERNAL resolution via the hub's pending stream (NOTIF-015):
        //   drop(while:)  — ignore snapshots until the notification first appears
        //   dropFirst()   — drop that first "present" snapshot
        //   filter        — keep only "gone" snapshots
        //   prefix(1)     — fire on the first "gone" snapshot, then complete
        let target = notification
        self.pendingCancellable = hub.pending
            .drop(while: { !$0.contains { $0 === target } })
            .dropFirst()
            .filter { !$0.contains { $0 === target } }
            .prefix(1)
            .sink { [weak self] _ in self?.notifyExternalResolve() }

        if emitsDecayTicks { scheduleDecayTick() }
    }

    // ── Public properties ───────────────────────────────────────────────────

    /// The notification datum consumed by this VM.
    public var notification: Notification { notificationRef }

    /// INPC-style change-notification stream: emits the name of each property
    /// whose value changed (`"isResolved"`, and — when a tick interval is
    /// configured — `"remaining"` / `"opacity"` as the notification fades).
    public var propertyChanged: AnyPublisher<String, Never> {
        propertyChangedSubject.eraseToAnyPublisher()
    }

    /// Remaining time in seconds, decaying toward 0 via the injected scheduler.
    public var remaining: TimeInterval {
        let elapsed = scheduler.now.seconds - startTime
        let r = lifespan - elapsed
        return r > 0 ? r : 0
    }

    /// Opacity derived as `remaining / lifespan`, clamped to `[0.0, 1.0]`.
    /// Linear decay from 1.0 to 0.0 over `lifespan`.
    public var opacity: Double {
        guard lifespan > 0 else { return 0.0 }
        return Swift.max(0.0, Swift.min(1.0, remaining / lifespan))
    }

    /// `true` once the notification has been resolved (manually, by the timer,
    /// or externally via the hub).
    public var isResolved: Bool { resolved }

    // ── Public methods ──────────────────────────────────────────────────────

    /// Disposes resources: cancels the timer, the pending subscription, the
    /// decay tick, and the dismiss command, then completes `propertyChanged`.
    public func dispose() {
        if disposed { return }
        disposed = true
        timerCancellable?.cancel(); timerCancellable = nil
        tickCancellable?.cancel(); tickCancellable = nil
        pendingCancellable?.cancel(); pendingCancellable = nil
        dismissCommand.dispose()
        propertyChangedSubject.send(completion: .finished)
    }

    // ── Open hooks (subclass override points) ────────────────────────────────

    /// Whether this VM arms the lifespan expiry timer at construction.
    /// Default `true` (auto-dismiss). `ConfirmationVM` overrides to `false`.
    /// Called from `init`; overrides must not read subclass-initialized state.
    open func armsExpiryTimer() -> Bool { true }

    /// Called when the lifespan timer fires. Default: auto-dismiss with
    /// `.approve`. `ConfirmationVM` overrides to a no-op.
    open func onExpire() { dismiss() }

    // ── Internal resolution helpers (callable by subclasses) ─────────────────

    /// Resolves the hub with `.approve` and cancels the timer. Idempotent.
    func dismiss() { markResolved(reaction: .approve, notifyHub: true) }

    /// Resolves the hub with `reaction` and cancels the timer. Idempotent.
    /// Used by `ConfirmationVM`'s approve/reject commands.
    func resolveWith(_ reaction: NotificationReaction) {
        markResolved(reaction: reaction, notifyHub: true)
    }

    // ── Private ──────────────────────────────────────────────────────────────

    /// Observed external resolution: flip `isResolved` and cancel the timer
    /// WITHOUT re-notifying the hub (it already resolved). Idempotent.
    private func notifyExternalResolve() {
        markResolved(reaction: nil, notifyHub: false)
    }

    /// Single resolution path. The `resolved` guard makes every entry point
    /// (dismiss / command / timer / external) resolve exactly once — so a timer
    /// firing after a manual dismiss, or the pending-stream echo of the VM's own
    /// `hub.resolve`, is a no-op.
    private func markResolved(reaction: NotificationReaction?, notifyHub: Bool) {
        if resolved { return }
        resolved = true
        timerCancellable?.cancel(); timerCancellable = nil
        tickCancellable?.cancel(); tickCancellable = nil
        if notifyHub, let reaction {
            hub.resolve(notificationRef, reaction)
        }
        raiseResolvedChanges()
    }

    private func scheduleDecayTick() {
        let due = scheduler.now.advanced(by: .seconds(tickInterval))
        tickCancellable = scheduler.schedule(at: due) { [weak self] in
            guard let self, !self.disposed, !self.resolved else { return }
            self.raisePropertyChanged("remaining")
            self.raisePropertyChanged("opacity")
            if self.remaining > 0 { self.scheduleDecayTick() }
        }
    }

    private func raisePropertyChanged(_ name: String) {
        guard !disposed else { return }
        propertyChangedSubject.send(name)
    }

    private func raiseResolvedChanges() {
        raisePropertyChanged("isResolved")
        raisePropertyChanged("remaining")
        raisePropertyChanged("opacity")
    }
}
