//
// WorkspaceVM — composition root for the Notes Showcase.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/WorkspaceVM.cs.
// See task-7-brief.md.
//
// Architecture notes (plan §3.a.11):
//   AggregateVM6 is sealed (the generic instantiation cannot be subclassed),
//   so WorkspaceVM wraps it rather than inheriting from it.  Lifecycle
//   (construct / destruct / dispose) is delegated to the inner aggregate;
//   the cascade rules of ADR-0034 still apply, just via composition.
//
//   WorkspaceVM is NOT a ComponentVMBase.  It composes one, plus a 7th
//   workspace-owned ThemeVM sibling that shares the same hub/dispatcher.
//
//   Cross-module subclassing is enabled by ADR-0066 for the child VMs;
//   WorkspaceVM itself is a plain final class.
//
//   Swift two-phase init note: all `let` stored properties are assigned
//   in phase 1 (before `self` is usable).  Commands and wiring subscriptions
//   that require self-capturing closures are (re-)wired in phase 2, after
//   every stored property has a value.  The FocusCell below breaks the
//   specific chicken-and-egg problem between CapabilityActionsVM's
//   `focusedGetter` and `self._focusCell`, which would otherwise form a
//   forward-reference cycle inside the init body.
//
import Foundation
import Combine
import VMx

// MARK: - FocusCell

/// Reference-type cell that indirects between `WorkspaceVM.trackFocus`
/// and `CapabilityActionsVM.focusedGetter`.
///
/// `CapabilityActionsVM` is constructed before `self` is fully initialised
/// (phase 1), so the getter cannot capture `self` directly.  Instead, it
/// captures this cell (a local variable), and `WorkspaceVM` stores the cell
/// as `_focusCell`.  After init, `trackFocus` updates `_focusCell.focused`
/// and calls `recomputeActions()`.
private final class FocusCell {
    var focused: AnyObject?
}

// MARK: - WorkspaceVM

/// Composition root for the Notes Showcase.
///
/// Owns six aggregate children via
/// `AggregateVM6<NotebooksRootVM, NotesViewVM, NoteFormVM, StatusBarVM,
/// NotificationsVM, CapabilityActionsVM>`, plus a 7th workspace-owned
/// `ThemeVM` sibling.
///
/// Lifecycle (construct / destruct / dispose) delegates to the inner
/// aggregate, which cascades to all six children per ADR-0034.
public final class WorkspaceVM {

    // MARK: - Private state

    private let _repo: any NoteRepository
    private let _dialogService: any DialogService
    private let _notificationHub: NotificationHubProtocol
    private let _hub: MessageHubProtocol
    private let _dispatcher: Dispatcher

    // Pre-built children — stored separately so they are accessible before
    // and after the aggregate's construct call (avoids a force-unwrap on
    // component1..6 which are nil until _onConstruct runs).
    private let _notebooks: NotebooksRootVM
    private let _notesView: NotesViewVM
    private let _noteForm: NoteFormVM
    private let _statusBar: StatusBarVM
    private let _notificationsVM: NotificationsVM
    private let _capabilities: CapabilityActionsVM

    private let _agg: AggregateVM6<
        NotebooksRootVM, NotesViewVM, NoteFormVM,
        StatusBarVM, NotificationsVM, CapabilityActionsVM
    >
    private let _theme: ThemeVM
    private let _globalSearch: GlobalSearchVM

    /// Indirect focus cell — allows CapabilityActionsVM's getter to be wired
    /// before `self` is fully initialised.
    private let _focusCell: FocusCell

    private let _commandTrigger: PassthroughSubject<Void, Never>

    /// Most recent notebook-bind request (set synchronously) — deduplicates
    /// the construct-time bind and rapid A→B→A notebook switches.
    private var _requestedNotebookId: String?
    private var _disposed = false

    // Wiring subscriptions
    private var _currentNoteSubscription: AnyCancellable?
    private var _notebookSubscription: AnyCancellable?
    private var _savedNoteSubscription: AnyCancellable?

    // MARK: - Commands

    /// Adds a new notebook at the root level.
    ///
    /// Predicate: `isConstructed`. Trigger: `_commandTrigger`.
    public private(set) var newNotebookCommand: AsyncRelayCommand

    /// Adds an untitled note to the currently selected notebook.
    ///
    /// Predicate: `isConstructed && notebooksRoot.current != nil`.
    /// Trigger: `_commandTrigger`.
    public private(set) var newNoteCommand: AsyncRelayCommand

    /// Exports the full workspace to a user-chosen file via the dialog service.
    ///
    /// Predicate: `isConstructed`. Trigger: `_commandTrigger`.
    public private(set) var exportCommand: AsyncRelayCommand

    // MARK: - Child accessors

    /// Notebooks tree (Component1).
    public var notebooksRoot: NotebooksRootVM { _notebooks }

    /// Notes view / centre pane (Component2).
    public var notesView: NotesViewVM { _notesView }

    /// Note form / right-pane editor (Component3).
    public var noteForm: NoteFormVM { _noteForm }

    /// Status bar (Component4).
    public var statusBar: StatusBarVM { _statusBar }

    /// Notification list (Component5).
    public var notifications: NotificationsVM { _notificationsVM }

    /// Capability-action projection (Component6).
    public var capabilityActions: CapabilityActionsVM { _capabilities }

    /// Token-paged all-notes search.
    public var globalSearch: GlobalSearchVM { _globalSearch }

    /// Theme seam — workspace-owned, not an aggregate child (VMX-129).
    public var theme: ThemeVM { _theme }

    // MARK: - Workspace surface

    /// Shared message hub; also the hub for all child VMs.
    public var hub: MessageHubProtocol { _hub }

    /// Workspace name (proxied through the inner aggregate).
    public var name: String { _agg.name }

    /// Aggregate lifecycle status.
    public var status: ConstructionStatus { _agg.status }

    /// `true` once `construct()` / `constructAsync()` has finished.
    public var isConstructed: Bool { _agg.isConstructed }

    // MARK: - Private helpers

    /// Updates the focused VM, refreshes the capability-action list, and
    /// pushes the command trigger so command predicates re-evaluate.
    ///
    /// Reference-equality guarded: setting the same object is a no-op.
    private func trackFocus(_ focused: AnyObject?) {
        guard _focusCell.focused !== focused else { return }
        _focusCell.focused = focused
        _capabilities.recomputeActions()
        _commandTrigger.send(())
    }

    // MARK: - Init

    private init(
        repo: any NoteRepository,
        dialogService: any DialogService,
        notificationHub: NotificationHubProtocol,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        name: String
    ) {
        // ── Phase 1: assign all let stored properties ──────────────────────
        // (`self` cannot be used until every let property has a value.)

        _repo = repo
        _dialogService = dialogService
        _notificationHub = notificationHub
        _hub = hub
        _dispatcher = dispatcher

        // Pre-build all six children so siblings can wire to live references.
        // Each builder requires the shared hub + dispatcher so all messages
        // ride the same bus.

        let notebooks = try! NotebooksRootVM.builder()
            .name("notebooks")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .notificationHub(notificationHub)
            .build()

        let notesView = try! NotesViewVM.builder()
            .name("notes")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .pageSize(5)
            .dialogService(dialogService)
            .notificationHub(notificationHub)
            .build()

        let noteForm = try! NoteFormVM.builder()
            .name("form")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .notificationHub(notificationHub)
            .build()

        let statusBar = try! StatusBarVM.builder()
            .name("status")
            .services(hub: hub, dispatcher: dispatcher)
            .notesView(notesView)
            .notebooks(notebooks)
            .noteForm(noteForm)
            .build()

        let notificationsVM = try! NotificationsVM.builder()
            .name("notifications")
            .services(hub: hub, dispatcher: dispatcher)
            .notificationHub(notificationHub)
            .build()

        // FocusCell: created as a local variable so it can be captured by the
        // CapabilityActionsVM getter closure without requiring `self`.  After
        // init, the cell is stored in `_focusCell`; `trackFocus` updates it.
        let focusCell = FocusCell()

        let capabilities = try! CapabilityActionsVM.builder()
            .name("capabilities")
            .services(hub: hub, dispatcher: dispatcher)
            .focusedGetter({ [weak focusCell] in focusCell?.focused })
            .canAddNote({ [weak notesView, weak notebooks] in
                guard let notesView, let notebooks else { return false }
                return notebooks.current != nil && !notesView.currentNotebookIsReadonly
            })
            .addNoteAction({ [weak notesView, weak notebooks, repo] in
                guard let nb = notebooks?.current else { return }
                let uuid = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                let note = NoteModel(
                    id: "note-\(uuid.prefix(5))",
                    notebookId: nb.model.id,
                    title: "Untitled",
                    tags: [],
                    body: "",
                    starred: false,
                    createdAt: Date(),
                    updatedAt: Date()
                )
                try await repo.saveNote(note)
                await notesView?.bindTo(notebookId: nb.model.id)
            })
            .build()

        // Assign children to stored properties.
        _notebooks = notebooks
        _notesView = notesView
        _noteForm = noteForm
        _statusBar = statusBar
        _notificationsVM = notificationsVM
        _capabilities = capabilities
        _focusCell = focusCell

        // Build the aggregate with lazy factories that return the pre-built
        // instances — avoids double-construction and keeps siblings on live refs.
        _agg = try! AggregateVM6<
            NotebooksRootVM, NotesViewVM, NoteFormVM,
            StatusBarVM, NotificationsVM, CapabilityActionsVM
        >.builder()
            .name(name)
            .services(hub: hub, dispatcher: dispatcher)
            .component1({ notebooks })
            .component2({ notesView })
            .component3({ noteForm })
            .component4({ statusBar })
            .component5({ notificationsVM })
            .component6({ capabilities })
            .build()

        // Workspace-owned theme seam: shares the hub + dispatcher so
        // ThemeChangedMessages ride the same bus as the six children.
        _theme = try! ThemeVM.builder()
            .name("theme")
            .services(hub: hub, dispatcher: dispatcher)
            .build()
        _globalSearch = try! GlobalSearchVM.builder()
            .name("global-search")
            .services(hub: hub, dispatcher: dispatcher)
            .repository(repo)
            .pageSize(5)
            .searchDebounce(.milliseconds(150))
            .build()

        // Command trigger (used below in phase 2 and later in trackFocus /
        // constructAsync to notify commands that predicates may have changed).
        let commandTrigger = PassthroughSubject<Void, Never>()
        _commandTrigger = commandTrigger

        // Phase-1 placeholder commands — `var` properties must be assigned
        // before phase 2; real closures are wired immediately after (phase 2).
        // The placeholder has no subscriptions to dispose.
        let placeholder = AsyncRelayCommand(
            body: nil,
            predicate: nil,
            triggers: [],
            throwOnCancel: false
        )
        newNotebookCommand = placeholder
        newNoteCommand = placeholder
        exportCommand = placeholder

        // ── Phase 2: all let stored properties are now assigned ────────────
        // `self` is usable; safe to create [weak self] closures and set up
        // subscriptions.

        let trigger = commandTrigger.eraseToAnyPublisher()

        newNotebookCommand = AsyncRelayCommand.builder()
            .predicate({ [weak self] in self?.isConstructed ?? false })
            .task({ [weak self] in
                guard let self else { return }
                try await self._notebooks.addNotebook(parentId: nil, name: "New Notebook")
            })
            .triggers(trigger)
            .build()

        newNoteCommand = AsyncRelayCommand.builder()
            .predicate({ [weak self] in
                guard let self else { return false }
                return self.isConstructed && self._notebooks.current != nil
            })
            .task({ [weak self] in
                guard let self else { return }
                try await self.addNewNoteToCurrent()
            })
            .triggers(trigger)
            .build()

        exportCommand = AsyncRelayCommand.builder()
            .predicate({ [weak self] in self?.isConstructed ?? false })
            .task({ [weak self] in
                guard let self else { return }
                try await self.exportInternal()
            })
            .triggers(trigger)
            .build()

        // ── Wiring subscriptions ───────────────────────────────────────────

        // Current note → form binding: when the user selects a note in the
        // centre pane, bind the right-pane editor.  When selection clears
        // (e.g. the selected note is deleted), unbind so no ghost data lingers.
        // Foreground-marshalled per THR-001.
        _currentNoteSubscription = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak notesView] m in
                m.sender === notesView && m.propertyName == "current"
            }
            .sink { [weak self] _ in
                guard let self else { return }
                self._dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    if let current = self._notesView.current {
                        self._noteForm.bindTo(current.model)
                        self.trackFocus(current)
                    } else {
                        self._noteForm.unbind()
                        self.trackFocus(self._notebooks.current)
                    }
                }
            }

        // Notebook selection → notes rebind: tracks focus + deduplicates so
        // a construct-time bind and a user click on the same notebook don't
        // trigger two concurrent loads.  Fire-and-forgets a Task for the async
        // bind so the foreground handler returns immediately.
        _notebookSubscription = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak notebooks] m in
                m.sender === notebooks && m.propertyName == "current"
            }
            .sink { [weak self] _ in
                guard let self else { return }
                self._dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    guard let nb = self._notebooks.current else { return }
                    self._notesView.currentNotebookIsReadonly = nb.model.isReadonly
                    self.trackFocus(nb)
                    self._commandTrigger.send(())
                    guard self._requestedNotebookId != nb.model.id else { return }
                    let notebookId = nb.model.id
                    self._requestedNotebookId = notebookId
                    let workspace = FlagshipTransferBox(self)
                    Task { [workspace, notebookId] in
                        await workspace.value.bindNotesObserved(notebookId: notebookId)
                    }
                }
            }

        // Saved note → list row refresh: reseat the persisted model into the
        // matching NoteVM so row labels and the starred marker reflect saved
        // values.  Foreground-marshalled per THR-001.
        _savedNoteSubscription = noteForm.onSaved
            .sink { [weak self] note in
                guard let self else { return }
                self._dispatcher.scheduleForeground { [weak self] in
                    self?._notesView.refreshNote(note)
                }
            }
    }

    // MARK: - Private async helpers

    /// Awaits `notesView.bindTo(notebookId:)` and clears `_requestedNotebookId`
    /// if the bind did not take effect (e.g. internal cancellation), so the
    /// notebook remains selectable rather than permanently deduped.
    private func bindNotesObserved(notebookId: String) async {
        await _notesView.bindTo(notebookId: notebookId)
        // If the bind was swallowed (repo error / cancellation), the
        // boundNotebookId will not match; clear the dedup key so a
        // subsequent selection of the same notebook can retry.
        await performOnForeground(using: _dispatcher) { [weak self] in
            guard let self else { return }
            if self._notesView.boundNotebookId != notebookId,
               self._requestedNotebookId == notebookId {
                self._requestedNotebookId = nil
            }
        }
    }

    /// Saves a new "Untitled" note in the current notebook and rebinds
    /// the notes view so the new row appears.
    private func addNewNoteToCurrent() async throws {
        let notebookId = await performOnForeground(using: _dispatcher) { [weak self] in
            self?._notebooks.current?.model.id
        }
        guard let notebookId else { return }
        let uuid = UUID().uuidString
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
        let id = "note-\(uuid.prefix(5))"
        let note = NoteModel(
            id: id,
            notebookId: notebookId,
            title: "Untitled",
            tags: [],
            body: "",
            starred: false,
            createdAt: Date(),
            updatedAt: Date()
        )
        try await _repo.saveNote(note)
        await _notesView.bindTo(notebookId: notebookId)
    }

    /// Presents a file-save dialog and, if the user picks a path, loads the
    /// full workspace from the repository and exports it to that path.
    private func exportInternal() async throws {
        guard let path = await _dialogService.pickFileToSave(
            filter: nil,
            title: "Export workspace",
            suggestedName: "notes-export.json"
        ), !path.isEmpty else { return }
        let (notebooks, notes) = try await _repo.loadAll()
        try await _repo.export(notebooks: notebooks, notes: notes, path: path)
    }

    // MARK: - Lifecycle

    /// Synchronous construct — cascades to the aggregate (all six children)
    /// and the theme seam.
    public func construct() throws {
        try _agg.construct()
        try _theme.construct()
        try _globalSearch.construct()
    }

    /// Async construct: builds the aggregate + theme, populates notebooks,
    /// selects the first root, and binds the notes view to it.
    ///
    /// The Current / focus assignments are foreground-marshalled because this
    /// continuation runs off the UI thread after the repository awaits.
    public func constructAsync() async throws {
        try await performThrowingOnForeground(using: _dispatcher) { [weak self] in
            guard let self else { return }
            try self._agg.construct()
            try self._theme.construct()
            try self._globalSearch.construct()
        }
        try await _notebooks.populate()
        let first = await performOnForeground(using: _dispatcher) { [weak self] in
            FlagshipTransferBox(self?._notebooks.roots.first)
        }
        if let first = first.value {
            // Set dedup key BEFORE the bind so the notebook subscription
            // (which fires on Current assignment below) sees it and skips.
            await performOnForeground(using: _dispatcher) { [weak self] in
                self?._requestedNotebookId = first.model.id
            }
            await _notesView.bindTo(notebookId: first.model.id)
            await _noteForm.refreshTagSuggestions()
            await performOnForeground(using: _dispatcher) { [weak self, first] in
                guard let self, !self._disposed else { return }
                self._notebooks.current = first
                self._notesView.currentNotebookIsReadonly = first.model.isReadonly
                self.trackFocus(first)
                self._commandTrigger.send(())
            }
        } else {
            // No notebooks: still push the trigger so toolbar commands
            // re-evaluate CanExecute after construction.
            await performOnForeground(using: _dispatcher) { [weak self] in
                guard let self, !self._disposed else { return }
                self._commandTrigger.send(())
            }
        }
    }

    /// Sets the currently-focused VM for capability-action projection.
    public func setFocus(_ focused: AnyObject) {
        trackFocus(focused)
    }

    /// Destructs the theme seam and the aggregate (cascades to all six children).
    public func destruct() throws {
        try _theme.destruct()
        try _globalSearch.destruct()
        try _agg.destruct()
    }

    /// Disposes wiring subscriptions, the command trigger, all commands, the
    /// theme seam, and the aggregate (cascade per ADR-0034).
    public func dispose() {
        _disposed = true
        _currentNoteSubscription?.cancel()
        _currentNoteSubscription = nil
        _notebookSubscription?.cancel()
        _notebookSubscription = nil
        _savedNoteSubscription?.cancel()
        _savedNoteSubscription = nil
        _commandTrigger.send(completion: .finished)
        newNotebookCommand.dispose()
        newNoteCommand.dispose()
        exportCommand.dispose()
        _theme.dispose()
        _globalSearch.dispose()
        _agg.dispose()
    }

    // MARK: - Builder

    /// Returns a new empty builder.
    public static func builder() -> WorkspaceVMBuilder {
        WorkspaceVMBuilder()
    }

    /// Immutable fluent builder for `WorkspaceVM`.
    ///
    /// Required: `repository(_:)`.
    /// Optional: `name(_:)` (default `"workspace"`), `dialogService(_:)`
    /// (default `NullDialogService.INSTANCE`), `notificationHub(_:)` (default
    /// a fresh `NotificationHub`), `messageHub(_:)` (default a fresh
    /// `MessageHub`), `dispatcher(_:)` (default `ImmediateDispatcher.INSTANCE`).
    public struct WorkspaceVMBuilder {
        private var _name: String = "workspace"
        private var _repo: (any NoteRepository)?
        private var _dialogService: (any DialogService)?
        private var _notificationHub: NotificationHubProtocol?
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?

        fileprivate init() {}

        public func name(_ value: String) -> WorkspaceVMBuilder {
            var c = self; c._name = value; return c
        }
        public func repository(_ repo: any NoteRepository) -> WorkspaceVMBuilder {
            var c = self; c._repo = repo; return c
        }
        public func dialogService(_ service: any DialogService) -> WorkspaceVMBuilder {
            var c = self; c._dialogService = service; return c
        }
        public func notificationHub(_ hub: NotificationHubProtocol) -> WorkspaceVMBuilder {
            var c = self; c._notificationHub = hub; return c
        }
        public func messageHub(_ hub: MessageHubProtocol) -> WorkspaceVMBuilder {
            var c = self; c._hub = hub; return c
        }
        public func dispatcher(_ d: Dispatcher) -> WorkspaceVMBuilder {
            var c = self; c._dispatcher = d; return c
        }

        /// Validates required fields and builds the `WorkspaceVM`.
        ///
        /// - Throws: `BuilderValidationError` if `repository` is not set.
        public func build() throws -> WorkspaceVM {
            guard let repo = _repo else {
                throw BuilderValidationError(missingField: "repository")
            }
            return WorkspaceVM(
                repo: repo,
                dialogService: _dialogService ?? NullDialogService.INSTANCE,
                notificationHub: _notificationHub ?? NotificationHub(),
                hub: _hub ?? MessageHub(),
                dispatcher: _dispatcher ?? ImmediateDispatcher.INSTANCE,
                name: _name
            )
        }
    }
}
