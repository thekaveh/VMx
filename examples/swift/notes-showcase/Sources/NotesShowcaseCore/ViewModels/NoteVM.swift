//
// NoteVM — leaf view-model for a single note.
//
// Capabilities (scenario §6.2):
//   `Selectable`, `Deselectable`, `Closable`, `Deletable`, `Savable`,
//   `Reconstructable`.
//
// `closeCommand` invokes a host-supplied close callback. This avoids
// back-references from the leaf to its container.
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_notifyPropertyChanged` are `public` on the base class.
//
import Foundation
import Combine
import VMx

/// Leaf view-model for a single note.
///
/// Mirrors the C# Avalonia `NoteVM`. Holds a `NoteModel` (equality-guarded
/// setter), proxies `noteId/title/body/starred/tags`, and exposes three
/// commands: `closeCommand`, `saveCommand`, `deleteCommand`. When a
/// `confirmDelete` delegate is wired, `deleteCommand` is wrapped in a
/// `ConfirmationDecoratorCommand`.
public final class NoteVM: ComponentVMBase,
                            Selectable, Deselectable,
                            Closable, Deletable, Savable {
    // `Deletable` and `Savable` have `associatedtype Item`; Swift resolves
    // `Item = NoteVM` from the method signatures below.
    //
    // `Reconstructable` is satisfied automatically via
    // `extension ComponentVMBase: Constructable, Destructable, Reconstructable {}`.

    // ── Private state ──────────────────────────────────────────────────────

    private var _model: NoteModel
    private let _onClose: (() -> Void)?
    private let _onDelete: ((NoteVM) async throws -> Void)?
    private let _onSave: ((NoteVM) async throws -> Void)?
    private let _confirmDelete: (() async throws -> Bool)?
    private let _notificationHub: NotificationHubProtocol?

    // ── Commands (initialization placeholders, rewired after super.init) ──

    /// Inner delete relay — always an `AsyncRelayCommand`, gated on
    /// `canDelete(self)`. Wrapped by `deleteCommand` when a confirm delegate
    /// is wired.
    private var _innerDeleteCommand: AsyncRelayCommand

    /// Convenience command wrapper for `close()`.
    public private(set) var closeCommand: RelayCommand

    /// Convenience command wrapper for `save(self)`.
    public private(set) var saveCommand: AsyncRelayCommand

    /// Convenience command wrapper for `delete(self)`.
    /// Type is `any Command` because it is a plain `RelayCommand` when no
    /// confirm delegate is wired, or a `ConfirmationDecoratorCommand` when one is.
    public private(set) var deleteCommand: any Command

    // ── Public properties ──────────────────────────────────────────────────

    /// Current note model. Equality-guarded; emits `PropertyChangedMessage`s
    /// for changed derived properties (`"title"`, `"starred"`) alongside `"model"`.
    public var model: NoteModel {
        get { _model }
        set {
            guard _model != newValue else { return }
            let oldTitle = _model.title
            let oldStarred = _model.starred
            _model = newValue
            _notifyPropertyChanged("model")
            if oldTitle != newValue.title {
                _notifyPropertyChanged("title")
            }
            if oldStarred != newValue.starred {
                _notifyPropertyChanged("starred")
            }
        }
    }

    /// Note identifier (proxy on `model`).
    public var noteId: String { _model.id }
    /// Note title (proxy on `model`).
    public var title: String { _model.title }
    /// Note body (proxy on `model`).
    public var body: String { _model.body }
    /// Whether the note is starred (proxy on `model`).
    public var starred: Bool { _model.starred }
    /// Tag list (proxy on `model`).
    public var tags: [String] { _model.tags }

    // ── Selectable / Deselectable (delegated to ComponentVMBase) ──────────
    // ComponentVMBase already provides canSelect/select/canDeselect/deselect;
    // the protocol conformance declarations above satisfy the contracts.

    // ── Closable ───────────────────────────────────────────────────────────

    public func canClose() -> Bool { isConstructed }

    public func close() {
        _onClose?()
    }

    // ── Deletable (Item = NoteVM) ──────────────────────────────────────────

    public func canDelete(_ item: NoteVM) -> Bool {
        item === self && isConstructed
    }

    public func delete(_ item: NoteVM) {
        guard canDelete(item) else { return }
        _innerDeleteCommand.execute()
    }

    // ── Savable (Item = NoteVM) ────────────────────────────────────────────

    public func canSave(_ item: NoteVM) -> Bool {
        item === self && isConstructed
    }

    public func save(_ item: NoteVM) {
        guard canSave(item) else { return }
        saveCommand.execute()
    }

    // ── Internal delete implementation ─────────────────────────────────────

    private func _performDelete(_ item: NoteVM) async throws {
        // Defensive re-guard (mirrors the C# reference) so this stays correct if
        // ever invoked from a new call site beyond the already-gated commands.
        let deletedTitle = await runOnForeground { [weak self, weak item] () -> String? in
            guard let self, let item, self.canDelete(item) else { return nil }
            return item.title
        }
        guard let deletedTitle else { return }
        try await _onDelete?(item)
        if let notificationHub = _notificationHub {
            publishNotification(VMx.Notification(
                type: .notification,
                message: "Note deleted: \u{201C}\(deletedTitle)\u{201D}"
            ), to: notificationHub)
        }
    }

    private func _performSave(_ item: NoteVM) async throws {
        let admitted = await runOnForeground { [weak self, weak item] in
            guard let self, let item else { return false }
            return self.canSave(item)
        }
        guard admitted else { return }
        try await _onSave?(item)
    }

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        model: NoteModel,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        onClose: (() -> Void)?,
        onDelete: ((NoteVM) async throws -> Void)?,
        onSave: ((NoteVM) async throws -> Void)?,
        confirmDelete: (() async throws -> Bool)?,
        notificationHub: NotificationHubProtocol?
    ) {
        _model = model
        _onClose = onClose
        _onDelete = onDelete
        _onSave = onSave
        _confirmDelete = confirmDelete
        _notificationHub = notificationHub

        // Placeholder no-op commands are required before super.init.
        let relayPlaceholder = RelayCommand(task: nil, predicate: nil, triggers: [])
        let asyncPlaceholder = AsyncRelayCommand(
            body: nil,
            predicate: nil,
            triggers: [],
            throwOnCancel: false
        )
        _innerDeleteCommand = asyncPlaceholder
        closeCommand = relayPlaceholder
        saveCommand = asyncPlaceholder
        deleteCommand = asyncPlaceholder

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // Rewire with self-capturing closures after `self` becomes valid.

        let innerDelete = AsyncRelayCommand.builder()
            .predicate({ [weak self] in
                guard let self = self else { return false }
                return self.canDelete(self)
            })
            .task({ [weak self] in
                guard let self = self else { return }
                try await self._performDelete(self)
            })
            .build()
        _innerDeleteCommand = innerDelete

        closeCommand = RelayCommand.builder()
            .predicate({ [weak self] in self?.canClose() ?? false })
            .task({ [weak self] in self?.close() })
            .build()

        saveCommand = AsyncRelayCommand.builder()
            .predicate({ [weak self] in
                guard let self = self else { return false }
                return self.canSave(self)
            })
            .task({ [weak self] in
                guard let self = self else { return }
                try await self._performSave(self)
            })
            .build()

        if let confirmDelegate = confirmDelete {
            deleteCommand = ConfirmationDecoratorCommand(innerDelete, confirm: confirmDelegate)
        } else {
            deleteCommand = innerDelete
        }
    }

    // ── Dispose ────────────────────────────────────────────────────────────

    override public func _onDispose() {
        closeCommand.dispose()
        saveCommand.dispose()
        // Dispose the decorator (if any) AND the inner command independently —
        // ConfirmationDecoratorCommand.dispose() does not cascade to its inner
        // command, so both must be disposed when confirm is wired.
        // Idempotent when deleteCommand IS innerDelete (RelayCommand.dispose is guarded).
        (deleteCommand as? ConfirmationDecoratorCommand)?.dispose()
        _innerDeleteCommand.dispose()
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder for `NoteVM`.
    public static func builder() -> NoteVMBuilder {
        NoteVMBuilder()
    }

    /// Immutable fluent builder for `NoteVM` (spec ch. 10).
    ///
    /// Required fields: `name(_:)`, `model(_:)`, `services(hub:dispatcher:)`.
    /// Optional fields: `onClose`, `onDelete`, `onSave`, `confirmDelete`,
    /// `notificationHub`.
    public struct NoteVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _model: NoteModel?
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _onClose: (() -> Void)?
        private var _onDelete: ((NoteVM) async throws -> Void)?
        private var _onSave: ((NoteVM) async throws -> Void)?
        private var _confirmDelete: (() async throws -> Bool)?
        private var _notificationHub: NotificationHubProtocol?

        fileprivate init() {}

        /// Sets the required VM name.
        public func name(_ value: String) -> NoteVMBuilder {
            var copy = self; copy._name = value; return copy
        }

        /// Sets the optional hint.
        public func hint(_ value: String) -> NoteVMBuilder {
            var copy = self; copy._hint = value; return copy
        }

        /// Sets the required note model.
        public func model(_ value: NoteModel) -> NoteVMBuilder {
            var copy = self; copy._model = value; return copy
        }

        /// Sets the required services (hub + dispatcher).
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NoteVMBuilder {
            var copy = self
            copy._hub = hub
            copy._dispatcher = dispatcher
            return copy
        }

        /// Sets the optional close callback (e.g. `NotesViewVM.current = nil`).
        public func onClose(_ handler: @escaping () -> Void) -> NoteVMBuilder {
            var copy = self; copy._onClose = handler; return copy
        }

        /// Sets the optional delete callback (route to repo).
        public func onDelete(_ handler: @escaping (NoteVM) async throws -> Void) -> NoteVMBuilder {
            var copy = self; copy._onDelete = handler; return copy
        }

        /// Sets the optional save callback (route to repo).
        public func onSave(_ handler: @escaping (NoteVM) async throws -> Void) -> NoteVMBuilder {
            var copy = self; copy._onSave = handler; return copy
        }

        /// Sets the optional confirm-delete delegate.
        /// When set, `deleteCommand` is wrapped in a `ConfirmationDecoratorCommand`
        /// that awaits this delegate before invoking the inner delete.
        public func confirmDelete(_ confirm: @escaping () async throws -> Bool) -> NoteVMBuilder {
            var copy = self; copy._confirmDelete = confirm; return copy
        }

        /// Sets the optional notification hub. When set, a successful delete
        /// publishes a "Note deleted: …" notification.
        public func notificationHub(_ hub: NotificationHubProtocol) -> NoteVMBuilder {
            var copy = self; copy._notificationHub = hub; return copy
        }

        /// Validates required fields and constructs a `NoteVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name`, `model`, or `services` are missing.
        public func build() throws -> NoteVM {
            guard let name = _name else {
                throw BuilderValidationError(missingField: "name")
            }
            guard let model = _model else {
                throw BuilderValidationError(missingField: "model")
            }
            guard let hub = _hub else {
                throw BuilderValidationError(missingField: "hub")
            }
            guard let dispatcher = _dispatcher else {
                throw BuilderValidationError(missingField: "dispatcher")
            }
            return NoteVM(
                name: name,
                hint: _hint,
                model: model,
                hub: hub,
                dispatcher: dispatcher,
                onClose: _onClose,
                onDelete: _onDelete,
                onSave: _onSave,
                confirmDelete: _confirmDelete,
                notificationHub: _notificationHub
            )
        }
    }
}
