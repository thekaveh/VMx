//
// NotificationsVM — bounded, keyed notification collection.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/NotificationsVM.cs.
// See spec/ADRs/0067-swift-notes-showcase-flagship.md.
//
// Subscribes to `notificationHub.pending` on construct (foreground-marshalled
// via the injected dispatcher). Maintains a bounded `[NotificationVM]` list
// (`visible`, capped at `cap`, default 5). Deduplicates by Notification
// identity and removes resolved notifications when the hub no longer lists them.
//
// A dispatcher that runs foreground work inline (such as `ImmediateDispatcher`)
// can deliver a pending snapshot on another thread while this VM is cleared, so
// the collections change only under a lock and are closed on destruct/dispose.
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_notifyPropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

/// Bounded view-model list for in-flight notifications.
///
/// Subscribes to the notification hub on construct and removes the
/// subscription on destruct / dispose. Each element is a `NotificationVM`
/// whose lifespan timer is driven by the injected `VirtualTimeScheduler`.
public final class NotificationsVM: ComponentVMBase {

    /// Default maximum concurrently rendered notifications.
    public static let defaultCap = 5

    // ── Private state ──────────────────────────────────────────────────────

    private let _notificationHub: NotificationHubProtocol
    private let _scheduler: VirtualTimeScheduler
    private let _lifespan: TimeInterval?
    private let _cap: Int

    /// Guards `_visible`, `_map`, and `_closed`. Never held while a
    /// `NotificationVM` is built or disposed, or while a change is published.
    private let _stateLock = NSLock()
    private var _visible: [NotificationVM] = []
    /// Keyed by `ObjectIdentifier(notification)` for O(1) dedup.
    private var _map: [ObjectIdentifier: NotificationVM] = [:]
    /// Set on destruct/dispose so a delivery that arrives late changes nothing.
    private var _closed = false
    private var _pendingCancellable: AnyCancellable?

    // ── Public surface ─────────────────────────────────────────────────────

    /// Bounded list of currently-rendered notifications.
    ///
    /// Updated synchronously on the foreground thread; observers may re-read
    /// this after receiving a `"visible"` `PropertyChangedMessage` on the hub.
    public var visible: [NotificationVM] { _stateLock.withLock { _visible } }

    /// Maximum number of concurrently rendered notifications.
    public var cap: Int { _cap }

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        notificationHub: NotificationHubProtocol,
        scheduler: VirtualTimeScheduler,
        lifespan: TimeInterval?,
        cap: Int
    ) {
        _notificationHub = notificationHub
        _scheduler = scheduler
        _lifespan = lifespan
        _cap = cap
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    // ── Lifecycle overrides ────────────────────────────────────────────────

    /// Subscribes to `notificationHub.pending` on construct.
    ///
    /// The pending stream (backed by `CurrentValueSubject`) immediately emits
    /// the current snapshot on subscription — `syncFromPending` runs once with
    /// the current state before the first external post.
    ///
    /// Posts arrive from background async continuations and timer callbacks;
    /// `syncFromPending` mutates `_visible` which is observed by the view.
    /// Marshal every sync to the foreground dispatcher to keep collection
    /// mutations on the UI thread.
    public override func _onConstruct() throws {
        _stateLock.withLock { _closed = false }
        _pendingCancellable = _notificationHub.pending
            .sink { [weak self] pending in
                guard let self else { return }
                self.dispatcher.scheduleForeground { [weak self] in
                    self?.syncFromPending(pending)
                }
            }
        try super._onConstruct()
    }

    public override func _onDestruct() throws {
        _pendingCancellable?.cancel()
        _pendingCancellable = nil
        clearVisible()
        try super._onDestruct()
    }

    public override func _onDispose() {
        _pendingCancellable?.cancel()
        _pendingCancellable = nil
        clearVisible()
        super._onDispose()
    }

    // ── Private helpers ────────────────────────────────────────────────────

    /// Mirrors C# `SyncFromPending`: add VMs for new notifications, drop
    /// oldest when over cap, remove VMs whose notifications resolved.
    private func syncFromPending(_ pending: [VMx.Notification]) {
        let fresh = _stateLock.withLock { () -> [VMx.Notification]? in
            guard !_closed else { return nil }
            return pending.filter { _map[ObjectIdentifier($0)] == nil }
        }
        guard let fresh else { return }

        // Build outside the lock. A VM that loses to another delivery or to
        // closing is disposed unused; disposal never resolves its notification.
        let lifespan = _lifespan ?? 60.0
        let built = fresh.map {
            NotificationVM(
                notification: $0,
                hub: _notificationHub,
                scheduler: _scheduler,
                lifespan: lifespan
            )
        }

        var released: [NotificationVM] = []
        let changed = _stateLock.withLock { () -> Bool in
            guard !_closed else {
                released = built
                return false
            }
            // Add VMs for new pending notifications, respecting cap.
            for vm in built {
                let key = ObjectIdentifier(vm.notification)
                if _map[key] != nil {
                    released.append(vm)
                    continue
                }
                _map[key] = vm
                _visible.append(vm)

                // Drop oldest while over cap.
                while _visible.count > _cap {
                    let oldest = _visible.removeFirst()
                    if let oldKey = _map.first(where: { $0.value === oldest })?.key {
                        _map.removeValue(forKey: oldKey)
                    }
                    released.append(oldest)
                }
            }

            // Remove VMs whose notifications are no longer pending.
            let stillPendingKeys = Set(pending.map { ObjectIdentifier($0) })
            let keysToRemove = _map.keys.filter { !stillPendingKeys.contains($0) }
            for key in keysToRemove {
                if let vm = _map.removeValue(forKey: key) {
                    _visible.removeAll { $0 === vm }
                    released.append(vm)
                }
            }
            return true
        }

        for vm in released { vm.dispose() }
        if changed { _notifyPropertyChanged("visible") }
    }

    private func clearVisible() {
        let released = _stateLock.withLock { () -> [NotificationVM] in
            _closed = true
            defer {
                _visible.removeAll()
                _map.removeAll()
            }
            return _visible
        }
        for vm in released { vm.dispose() }
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder.
    public static func builder() -> NotificationsVMBuilder {
        NotificationsVMBuilder()
    }

    /// Immutable fluent builder for `NotificationsVM`.
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `notificationHub(_:)`.
    /// Optional: `hint(_:)`, `scheduler(_:)`, `lifespan(_:)`, `cap(_:)`.
    public struct NotificationsVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _notificationHub: NotificationHubProtocol?
        private var _scheduler: VirtualTimeScheduler?
        private var _lifespan: TimeInterval?
        private var _cap: Int = NotificationsVM.defaultCap

        fileprivate init() {}

        public func name(_ value: String) -> NotificationsVMBuilder {
            var c = self; c._name = value; return c
        }
        public func hint(_ value: String) -> NotificationsVMBuilder {
            var c = self; c._hint = value; return c
        }
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NotificationsVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }
        public func notificationHub(_ hub: NotificationHubProtocol) -> NotificationsVMBuilder {
            var c = self; c._notificationHub = hub; return c
        }
        public func scheduler(_ scheduler: VirtualTimeScheduler) -> NotificationsVMBuilder {
            var c = self; c._scheduler = scheduler; return c
        }
        /// Overrides the per-notification lifespan (default: 60 s from `NotificationVM`).
        public func lifespan(_ value: TimeInterval) -> NotificationsVMBuilder {
            var c = self; c._lifespan = value; return c
        }
        /// Overrides the cap (default `defaultCap` = 5).
        public func cap(_ value: Int) -> NotificationsVMBuilder {
            var c = self; c._cap = value; return c
        }

        /// Validates required fields and constructs a `NotificationsVM`.
        ///
        /// - Throws: `BuilderValidationError` if any required field is missing.
        public func build() throws -> NotificationsVM {
            guard let name = _name else { throw BuilderValidationError(missingField: "name") }
            guard let hub = _hub else { throw BuilderValidationError(missingField: "hub") }
            guard let dispatcher = _dispatcher else { throw BuilderValidationError(missingField: "dispatcher") }
            guard let notifHub = _notificationHub else { throw BuilderValidationError(missingField: "notificationHub") }
            return NotificationsVM(
                name: name, hint: _hint,
                hub: hub, dispatcher: dispatcher,
                notificationHub: notifHub,
                scheduler: _scheduler ?? VirtualTimeScheduler(),
                lifespan: _lifespan,
                cap: _cap
            )
        }
    }
}
