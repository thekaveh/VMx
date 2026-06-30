//
// NoteFormVM — strict-mode FormVM<NoteModel> note editor.
//
// Composes (not subclasses) a `FormVM<NoteModel>` in strict mode.
// See spec/20-form-vm.md and the C# reference ViewModels/NoteFormVM.cs.
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_raisePropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

/// Note-editor view-model that composes a strict-mode `FormVM<NoteModel>`.
///
/// A fresh inner `FormVM` is created on each `bindTo(_:)` call and disposed
/// by `unbind()`. All draft mutations flow through `setDraft(_:)` which calls
/// `form.setModel` then fires property-changed signals for every derived
/// property so two-way UI bindings stay in sync.
public final class NoteFormVM: ComponentVMBase {

    // ── Private state ──────────────────────────────────────────────────────

    private let _repo: any NoteRepository
    private let _notificationHub: NotificationHubProtocol?
    private var _form: FormVM<NoteModel>?
    private var _tagDraft: String = ""
    private var _approvedCancellable: AnyCancellable?

    // ── Reactive channels ──────────────────────────────────────────────────

    private let _onSaved = PassthroughSubject<NoteModel, Never>()

    /// Fires on every draft / binding state change so `approveCommand` and
    /// `addTagCommand` re-evaluate their predicates.
    private let _canExecuteTrigger = PassthroughSubject<Void, Never>()

    // ── Commands (phase-1 placeholders; rewired in init phase 2) ──────────

    /// Approve = persist via repo + post "Saved …" notification + emit `onSaved`.
    /// Predicate: `isDirty && isValid`.
    public private(set) var approveCommand: RelayCommand

    /// Deny = revert draft to the current snapshot. No-op when unbound.
    public private(set) var denyCommand: RelayCommand

    /// Append `tagDraft` to the draft tag list (trimmed, case-insensitive
    /// dedup). Predicate: `hasBoundNote && !tagDraft.isBlank`.
    public private(set) var addTagCommand: RelayCommand

    /// Remove the given tag from the draft tag list.
    public private(set) var removeTagCommand: RelayCommandOf<String>

    // ── Empty sentinel ─────────────────────────────────────────────────────

    private static let empty = NoteModel(
        id: "", notebookId: "", title: "", tags: [], body: "", starred: false,
        createdAt: Date.distantPast, updatedAt: Date.distantPast
    )

    // ── Computed properties ────────────────────────────────────────────────

    /// `true` once a note is bound (inner form constructed).
    public var hasBoundNote: Bool { _form != nil }

    /// Live, editable note (the form's mutable model).
    public var draft: NoteModel {
        get { _form?.model ?? Self.empty }
        set {
            guard _form != nil else { return }
            setDraft(newValue)
        }
    }

    /// Snapshot captured at bind time; advances after each successful approve.
    public var snapshot: NoteModel { _form?.snapshot ?? Self.empty }

    /// Two-way title proxy — rebuilds the draft via `with(title:)`.
    public var title: String {
        get { draft.title }
        set {
            guard _form != nil, draft.title != newValue else { return }
            setDraft(draft.with(title: newValue))
        }
    }

    /// Two-way body proxy — rebuilds the draft via `with(body:)`.
    public var body: String {
        get { draft.body }
        set {
            guard _form != nil, draft.body != newValue else { return }
            setDraft(draft.with(body: newValue))
        }
    }

    /// Two-way starred proxy — rebuilds the draft via `with(starred:)`.
    public var starred: Bool {
        get { draft.starred }
        set {
            guard _form != nil, draft.starred != newValue else { return }
            setDraft(draft.with(starred: newValue))
        }
    }

    /// Read-only tag list (mutate via `addTagCommand` / `removeTagCommand`).
    public var tags: [String] { draft.tags }

    /// Comma-joined tag list — bind text labels to this instead of `tags`.
    public var tagsText: String { draft.tags.joined(separator: ", ") }

    /// Tag input buffer; cleared by `addTagCommand` and `unbind()`.
    public var tagDraft: String {
        get { _tagDraft }
        set {
            guard _tagDraft != newValue else { return }
            _tagDraft = newValue
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "tagDraft"))
            _raisePropertyChanged("tagDraft")
            _canExecuteTrigger.send(())
        }
    }

    /// `true` when the draft differs from the snapshot.
    public var isDirty: Bool { _form?.isDirty ?? false }

    /// `true` when the draft has a non-empty (non-whitespace) title.
    public var isValid: Bool {
        !draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Emits the persisted note after each successful approve.
    public var onSaved: AnyPublisher<NoteModel, Never> {
        _onSaved.eraseToAnyPublisher()
    }

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        repo: any NoteRepository,
        notificationHub: NotificationHubProtocol?
    ) {
        _repo = repo
        _notificationHub = notificationHub

        // Phase 1: placeholder commands (required before super.init).
        let placeholder = RelayCommand(task: nil, predicate: nil, triggers: [])
        approveCommand = placeholder
        denyCommand = placeholder
        addTagCommand = placeholder
        removeTagCommand = RelayCommandOf<String>(task: nil, predicate: nil, triggers: [])

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // Phase 2: rewire with real self-capturing closures.
        //
        // Both `approveCommand` and `addTagCommand` subscribe to
        // `_canExecuteTrigger` so that `emitDraftChanges()` / tagDraft setter
        // fire `canExecuteChanged` and UI buttons re-evaluate synchronously
        // (parity with C# Phase 5.a binding-gap fix).

        let trigger = _canExecuteTrigger.eraseToAnyPublisher()

        approveCommand = RelayCommand.builder()
            .predicate({ [weak self] in
                guard let self else { return false }
                return self.isDirty && self.isValid
            })
            .task({ [weak self] in
                guard let self else { return }
                Task { try? await self.approveAsync() }
            })
            .triggers(trigger)
            .build()

        denyCommand = RelayCommand.builder()
            .task({ [weak self] in
                guard let self else { return }
                self._form?.denyCommand.execute()
                self.emitDraftChanges()
            })
            .build()

        addTagCommand = RelayCommand.builder()
            .predicate({ [weak self] in
                guard let self else { return false }
                return self.hasBoundNote
                    && !self._tagDraft.trimmingCharacters(in: .whitespaces).isEmpty
            })
            .task({ [weak self] in self?.addTag() })
            .triggers(trigger)
            .build()

        removeTagCommand = RelayCommandOf<String>.builder()
            .predicate({ [weak self] tag in
                guard let self else { return false }
                return self.hasBoundNote && !tag.isEmpty
            })
            .task({ [weak self] tag in self?.removeTag(tag) })
            .build()
    }

    // ── Binding lifecycle ──────────────────────────────────────────────────

    /// Binds the editor to `note` — builds a fresh strict `FormVM<NoteModel>`
    /// backed by the injected repository and subscribes its `onApproved`
    /// pipeline to forward to `onSaved`.
    public func bindTo(_ note: NoteModel) {
        _form?.dispose()
        _approvedCancellable?.cancel()
        _approvedCancellable = nil

        let form = FormVM<NoteModel>(
            initial: note,
            persister: { [weak self] n in
                guard let self else { return }
                try await self._repo.saveNote(n)
            },
            hub: hub,
            strict: true
        )
        _form = form
        _approvedCancellable = form.onApproved
            .sink { [weak self] model in self?._onSaved.send(model) }
        emitDraftChanges()
    }

    /// Disposes the inner form and clears `tagDraft`. All derived properties
    /// revert to their empty-model values. Mirrors C# `Unbind()`.
    public func unbind() {
        let hadTagDraft = !_tagDraft.isEmpty
        guard _form != nil || hadTagDraft else { return }
        _form?.dispose()
        _form = nil
        _approvedCancellable?.cancel()
        _approvedCancellable = nil
        if hadTagDraft {
            _tagDraft = ""
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "tagDraft"))
            _raisePropertyChanged("tagDraft")
        }
        emitDraftChanges()
    }

    /// Awaitable approve — persists via the repository, emits `onSaved`, and
    /// (when a `NotificationHubProtocol` is wired) posts a foreground
    /// "Saved …" notification. Mirrors C# `ApproveAsync()`.
    public func approveAsync() async throws {
        guard let form = _form else { return }
        try await form.approveAsync()
        emitDraftChanges()
        if let notificationHub = _notificationHub {
            let savedTitle = snapshot.title
            Task {
                _ = await notificationHub.post(VMx.Notification(
                    type: .notification,
                    message: "Saved \u{201C}\(savedTitle)\u{201D}"
                ))
            }
        }
    }

    // ── Private helpers ────────────────────────────────────────────────────

    /// Single mutation site: calls `form.setModel` then broadcasts changes.
    private func setDraft(_ newDraft: NoteModel) {
        guard let form = _form else { return }
        form.setModel(newDraft)
        emitDraftChanges()
    }

    private func addTag() {
        let trimmed = _tagDraft.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, _form != nil else { return }
        let current = draft.tags
        guard !current.contains(where: { $0.lowercased() == trimmed.lowercased() }) else { return }
        setDraft(draft.with(tags: current + [trimmed]))
        tagDraft = ""
    }

    private func removeTag(_ tag: String) {
        guard !tag.isEmpty else { return }
        let filtered = draft.tags.filter { $0.lowercased() != tag.lowercased() }
        setDraft(draft.with(tags: filtered))
    }

    /// Broadcasts property-changed signals for every surface affected by a
    /// draft mutation or binding transition. Mirrors C# `EmitDraftChanges()`.
    private func emitDraftChanges() {
        let props: [String] = [
            "draft", "snapshot", "isDirty", "isValid",
            "title", "body", "starred", "tags", "tagsText",
            "approveCommand", "denyCommand"
        ]
        for prop in props {
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: prop))
            _raisePropertyChanged(prop)
        }
        _canExecuteTrigger.send(())
    }

    // ── Dispose ────────────────────────────────────────────────────────────

    override public func _onDispose() {
        _form?.dispose()
        _form = nil
        _approvedCancellable?.cancel()
        _approvedCancellable = nil
        approveCommand.dispose()
        denyCommand.dispose()
        addTagCommand.dispose()
        removeTagCommand.dispose()
        _canExecuteTrigger.send(completion: .finished)
        _onSaved.send(completion: .finished)
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder for `NoteFormVM`.
    public static func builder() -> NoteFormVMBuilder {
        NoteFormVMBuilder()
    }

    /// Immutable fluent builder for `NoteFormVM` (spec ch. 10).
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `repository(_:)`.
    /// Optional: `hint(_:)`, `notificationHub(_:)`.
    public struct NoteFormVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _repo: (any NoteRepository)?
        private var _notificationHub: NotificationHubProtocol?

        fileprivate init() {}

        /// Sets the required VM name.
        public func name(_ value: String) -> NoteFormVMBuilder {
            var copy = self; copy._name = value; return copy
        }

        /// Sets the optional hint.
        public func hint(_ value: String) -> NoteFormVMBuilder {
            var copy = self; copy._hint = value; return copy
        }

        /// Sets the required services (hub + dispatcher).
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NoteFormVMBuilder {
            var copy = self
            copy._hub = hub
            copy._dispatcher = dispatcher
            return copy
        }

        /// Sets the required note repository.
        public func repository(_ repo: any NoteRepository) -> NoteFormVMBuilder {
            var copy = self; copy._repo = repo; return copy
        }

        /// Sets the optional notification hub (default: silent — no notification posted).
        public func notificationHub(_ hub: NotificationHubProtocol) -> NoteFormVMBuilder {
            var copy = self; copy._notificationHub = hub; return copy
        }

        /// Validates required fields and constructs a `NoteFormVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name`, `services`, or `repository` are missing.
        public func build() throws -> NoteFormVM {
            guard let name = _name else {
                throw BuilderValidationError(missingField: "name")
            }
            guard let hub = _hub else {
                throw BuilderValidationError(missingField: "hub")
            }
            guard let dispatcher = _dispatcher else {
                throw BuilderValidationError(missingField: "dispatcher")
            }
            guard let repo = _repo else {
                throw BuilderValidationError(missingField: "repository")
            }
            return NoteFormVM(
                name: name,
                hint: _hint,
                hub: hub,
                dispatcher: dispatcher,
                repo: repo,
                notificationHub: _notificationHub
            )
        }
    }
}
