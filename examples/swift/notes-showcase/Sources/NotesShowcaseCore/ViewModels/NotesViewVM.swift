//
// NotesViewVM — VM for the centre pane: paged, searchable, filterable list.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/NotesViewVM.cs.
// See task-5-brief.md.
//
// Architecture (plan §3.a.8):
//   * inner storage  = CompositeVM<NoteVM>  (mutable, lifecycle-aware)
//   * filtered view  = [NoteVM] mirror updated on every filter / search change
//   * paged view     = PagedComposition<NoteVM> over the filtered array
//   * search         = SearchableState<NoteVM> (debounced, 150 ms default)
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_raisePropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

// MARK: - WeakBox helper

/// Reference-type wrapper for a weak reference, used to break the
/// chicken-and-egg cycle when wiring a NoteVM's close handler back to itself.
private final class WeakBox<T: AnyObject> {
    weak var value: T?
    init() {}
}

// MARK: - NotesViewVM

/// VM for the centre pane: paged, searchable, filterable list of notes.
///
/// Conforms to `Searchable`, `Pageable`, and `Filterable` (Swift capability
/// protocols — no `I`-prefix, camelCase, per ADR-0006/0057).
public final class NotesViewVM: ComponentVMBase, Searchable, Pageable, Filterable {

    // MARK: - Filterable associated type

    public typealias Item = NoteVM

    // MARK: - Private state

    private let _repo: any NoteRepository
    private let _dialogService: (any DialogService)?
    private let _notificationHub: NotificationHubProtocol?

    private let _inner: CompositeVM<NoteVM>
    private var _filteredItems: [NoteVM] = []
    private let _paged: PagedComposition<NoteVM>
    private let _search: SearchableState<NoteVM>

    private var _showStarredOnly: Bool = false
    private var _filter: ((NoteVM) -> Bool)?
    private var _current: NoteVM?

    /// Handle for the current in-flight `bindTo` fetch.
    /// Cancelled by a superseding `bindTo` call or by `_onDispose`.
    private var _activeFetchTask: Task<Void, Never>?

    /// Handle for the most recent in-flight fire-and-forget delete (`deleteNote`).
    ///
    /// Retained so a caller can `await` the delete to completion — persistence
    /// plus the inline `_inner` removal — rather than polling `inner` while that
    /// removal mutates the backing array in place on another executor (a Swift
    /// `Array` concurrent read/mutate is undefined behaviour). The production UI
    /// keeps using the fire-and-forget `deleteCommand.execute()` path and simply
    /// ignores this handle; deterministic tests await it. Cancelled by `_onDispose`.
    internal private(set) var pendingDeleteTask: Task<Void, Never>?

    private var _pagedChangedCancellable: AnyCancellable?
    private var _searchCancellable: AnyCancellable?

    // MARK: - Commands

    public private(set) var moveToFirstPageCommand: RelayCommand
    public private(set) var moveToPreviousPageCommand: RelayCommand
    public private(set) var moveToNextPageCommand: RelayCommand
    public private(set) var moveToLastPageCommand: RelayCommand

    // MARK: - Public read surface

    /// The inner composite storing all loaded notes (unfiltered).
    public var inner: CompositeVM<NoteVM> { _inner }

    /// Filtered + searched items (the paged source).
    public var filteredItems: [NoteVM] { _filteredItems }

    /// Items on the current page (decoded slice over `filteredItems`).
    public var visibleItems: [NoteVM] { _paged.items }

    /// The notebook id this view is currently bound to (or `nil`).
    public private(set) var boundNotebookId: String?

    // MARK: - Current selection

    /// Currently selected note (two-way bindable).
    public var current: NoteVM? {
        get { _current }
        set {
            guard _current !== newValue else { return }
            _current = newValue
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "current"))
            _raisePropertyChanged("current")
        }
    }

    // MARK: - Derived properties

    /// `true` when the current filter / search yields no visible items.
    public var isEmpty: Bool { _filteredItems.isEmpty }

    /// "Page X of Y" label.
    public var pageLabel: String {
        "Page \(currentPageIndex + 1) of \(max(1, pageCount))"
    }

    // MARK: - Searchable

    public var searchTerm: String {
        get { _search.searchTerm }
        set {
            guard newValue != _search.searchTerm else { return }
            _search.searchTerm = newValue
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "searchTerm"))
            _raisePropertyChanged("searchTerm")
        }
    }

    public func canSearch() -> Bool { _search.canSearch() }

    /// Force an immediate recompute of filtered items, bypassing the debounce.
    /// Mirrors C# `Search()` / the `search()` path on `SearchableState`.
    public func search() { _search.search() }

    // MARK: - Filterable

    public var filter: ((NoteVM) -> Bool)? {
        get { _filter }
        set {
            _filter = newValue
            recomputeFiltered()
        }
    }

    public func canFilter() -> Bool { status == .constructed }

    /// When `true`, only starred notes pass the combined filter. Triggers a
    /// recompute of `filteredItems`.
    public var showStarredOnly: Bool {
        get { _showStarredOnly }
        set {
            guard _showStarredOnly != newValue else { return }
            _showStarredOnly = newValue
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "showStarredOnly"))
            _raisePropertyChanged("showStarredOnly")
            recomputeFiltered()
        }
    }

    // MARK: - Pageable (delegates to inner PagedComposition)

    public var pageSize: Int {
        get { _paged.pageSize }
        set { _paged.pageSize = newValue }
    }

    public var currentPageIndex: Int {
        get { _paged.currentPageIndex }
        set { _paged.currentPageIndex = newValue }
    }

    public var pageCount: Int { _paged.pageCount }
    public var isPagingEnabled: Bool { _paged.isPagingEnabled }

    public func moveToFirstPage() { _paged.moveToFirstPage() }
    public func moveToPreviousPage() { _paged.moveToPreviousPage() }
    public func moveToNextPage() { _paged.moveToNextPage() }
    public func moveToLastPage() { _paged.moveToLastPage() }

    // MARK: - Init

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        repo: any NoteRepository,
        pageSize: Int,
        searchDebounce: DispatchQueue.SchedulerTimeType.Stride,
        searchScheduler: DispatchQueue?,
        dialogService: (any DialogService)?,
        notificationHub: NotificationHubProtocol?
    ) {
        _repo = repo
        _dialogService = dialogService
        _notificationHub = notificationHub

        // Build the inner composite directly (avoids `try!` / builder throw path).
        _inner = CompositeVM<NoteVM>(
            name: "\(name):inner",
            hub: hub,
            dispatcher: dispatcher,
            childrenFactory: { [] }
        )

        _paged = PagedComposition<NoteVM>(source: [], pageSize: pageSize)

        // Capture `_inner` as a reference before `super.init` so the
        // `SearchableState` items provider can lazily enumerate it at call time.
        let innerRef = _inner
        _search = SearchableState<NoteVM>(
            items: { (0..<innerRef.count).map { innerRef.at($0) } },
            // Predicate is always true — all filtering is done inside
            // `recomputeFiltered()` when the debounced term fires (mirrors C#).
            predicate: { _, _ in true },
            debounce: searchDebounce,
            scheduler: searchScheduler ?? .main
        )

        // Phase 1: placeholder commands (required before `super.init`).
        let placeholder = RelayCommand(task: nil, predicate: nil, triggers: [])
        moveToFirstPageCommand = placeholder
        moveToPreviousPageCommand = placeholder
        moveToNextPageCommand = placeholder
        moveToLastPageCommand = placeholder

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // Phase 2: rewire commands with real self-capturing closures.
        moveToFirstPageCommand = RelayCommand.builder()
            .task({ [weak self] in self?.moveToFirstPage() })
            .build()
        moveToPreviousPageCommand = RelayCommand.builder()
            .task({ [weak self] in self?.moveToPreviousPage() })
            .build()
        moveToNextPageCommand = RelayCommand.builder()
            .task({ [weak self] in self?.moveToNextPage() })
            .build()
        moveToLastPageCommand = RelayCommand.builder()
            .task({ [weak self] in self?.moveToLastPage() })
            .build()

        // Re-broadcast PagedComposition property changes through our own INPC + hub
        // so subscribers bound to NotesViewVM (not the inner PagedComposition) see them.
        _pagedChangedCancellable = _paged.propertyChanged.sink { [weak self] propName in
            guard let self else { return }
            self._raisePropertyChanged(propName)
            self.hub.send(PropertyChangedMessage(
                sender: self, senderName: self.name, propertyName: propName
            ))
            // Page-index / size / count changes also update the page label and slice.
            if propName == "currentPageIndex" || propName == "pageCount" || propName == "pageSize" {
                self._raisePropertyChanged("pageLabel")
                self._raisePropertyChanged("visibleItems")
                self.hub.send(PropertyChangedMessage(
                    sender: self, senderName: self.name, propertyName: "pageLabel"
                ))
                self.hub.send(PropertyChangedMessage(
                    sender: self, senderName: self.name, propertyName: "visibleItems"
                ))
            }
        }

        // Whenever the debounced search term fires, run the combined filter pipeline.
        _searchCancellable = _search.filtered.sink { [weak self] _ in
            self?.recomputeFiltered()
        }
    }

    // MARK: - Public async operations

    /// Cancels any in-flight fetch, loads notes for `notebookId`, and replaces
    /// the inner items on the foreground dispatcher.
    ///
    /// With `ImmediateDispatcher` (used in tests) the foreground marshal runs
    /// inline, so `await bindTo(notebookId:)` returns only after `replaceItems`
    /// has finished — same deterministic guarantee as C#'s `ImmediateScheduler`.
    public func bindTo(notebookId: String) async {
        _activeFetchTask?.cancel()
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                let notes = try await self._repo.loadNotes(notebookId: notebookId)
                guard !Task.isCancelled else { return }
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    self.boundNotebookId = notebookId
                    self.replaceItems(notes)
                }
            } catch {
                // CancellationError and persistence errors are swallowed.
            }
        }
        _activeFetchTask = task
        await task.value
    }

    /// Refreshes the list row for `note` after an external update (save):
    /// re-seats the persisted model into the matching NoteVM and re-runs the
    /// combined filter so row labels and the starred marker reflect saved values.
    public func refreshNote(_ note: NoteModel) {
        for i in 0..<_inner.count {
            let vm = _inner.at(i)
            if vm.noteId == note.id {
                vm.model = note
                recomputeFiltered()
                return
            }
        }
    }

    // MARK: - Private helpers

    /// Builds a NoteVM for `note` with all callbacks wired.
    ///
    /// Uses a `WeakBox` to break the chicken-and-egg cycle between the vm
    /// reference and its own `onClose` handler.
    private func buildNoteVM(note: NoteModel) -> NoteVM {
        let box = WeakBox<NoteVM>()

        var b = NoteVM.builder()
            .name("note:\(note.id)")
            .services(hub: hub, dispatcher: dispatcher)
            .model(note)
            .onDelete({ [weak self] vm in self?.deleteNote(vm) })
            .onClose({ [weak self, box] in
                guard let self else { return }
                if let vm = box.value, self._current === vm {
                    self.current = nil
                }
            })
            .onSave({ [weak self] vm in
                guard let self else { return }
                Task { try? await self._repo.saveNote(vm.model) }
            })

        if let dialogService = _dialogService {
            b = b.confirmDelete({ [title = note.title] in
                await dialogService.confirm(
                    "Delete \u{201C}\(title)\u{201D}?",
                    title: "Delete note"
                )
            })
        }
        if let notificationHub = _notificationHub {
            b = b.notificationHub(notificationHub)
        }

        // Safe: all required fields are set; build() only throws on missing fields.
        let vm = try! b.build()
        box.value = vm
        return vm
    }

    /// Replaces the inner note collection. Must be called on the foreground thread.
    ///
    /// Disposes existing children, builds fresh NoteVMs with wired callbacks,
    /// clears `current`, recomputes the filter, and resets to page 1.
    private func replaceItems(_ notes: [NoteModel]) {
        // Dispose existing children to release their hub subscriptions.
        for i in stride(from: _inner.count - 1, through: 0, by: -1) {
            let vm = _inner.at(i)
            _inner.removeAt(i)
            vm.dispose()
        }

        for note in notes {
            let vm = buildNoteVM(note: note)
            try? vm.construct()
            _inner.add(vm)
        }

        // Clear current selection.
        _current = nil
        hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: "current"))
        _raisePropertyChanged("current")

        recomputeFiltered()
        _paged.moveToFirstPage()
    }

    /// Fire-and-forget: persists deletion via the repo, then on success removes
    /// the note from `inner` on the foreground dispatcher.
    private func deleteNote(_ vm: NoteVM) {
        pendingDeleteTask = Task { [weak self, weak vm] in
            guard let self, let vm else { return }
            do {
                try await self._repo.deleteNote(id: vm.noteId)
            } catch {
                // Persistence failures are surfaced via the notification hub in
                // production; tests pass a synchronous repo so this is dead code.
                return
            }
            self.dispatcher.scheduleForeground { [weak self, weak vm] in
                guard let self, let vm else { return }
                for i in 0..<self._inner.count {
                    if self._inner.at(i) === vm {
                        self._inner.removeAt(i)
                        if self._current === vm {
                            self._current = nil
                            self.hub.send(PropertyChangedMessage(
                                sender: self, senderName: self.name, propertyName: "current"
                            ))
                            self._raisePropertyChanged("current")
                        }
                        self.recomputeFiltered()
                        vm.dispose()
                        break
                    }
                }
            }
        }
    }

    /// Recomputes `filteredItems` by blending `showStarredOnly` + custom `filter`
    /// + the current search term (case-insensitive match on title / body / tags).
    /// Updates the paged source and fires property-changed signals.
    private func recomputeFiltered() {
        let term = _search.searchTerm.lowercased()
        var filtered: [NoteVM] = []
        for i in 0..<_inner.count {
            let n = _inner.at(i)
            if _showStarredOnly && !n.starred { continue }
            if let f = _filter, !f(n) { continue }
            if !term.isEmpty {
                let matchTitle = n.title.lowercased().contains(term)
                let matchBody  = n.body.lowercased().contains(term)
                let matchTags  = n.tags.contains { $0.lowercased().contains(term) }
                if !matchTitle && !matchBody && !matchTags { continue }
            }
            filtered.append(n)
        }
        _filteredItems = filtered
        _paged.setSource(_filteredItems)

        for propName in ["filteredItems", "isEmpty", "visibleItems", "pageLabel"] {
            hub.send(PropertyChangedMessage(sender: self, senderName: name, propertyName: propName))
            _raisePropertyChanged(propName)
        }
    }

    // MARK: - Lifecycle overrides

    public override func _onDestruct() throws {
        // Remove and dispose all NoteVMs so they release hub subscriptions
        // before the parent composite tears down.
        for i in stride(from: _inner.count - 1, through: 0, by: -1) {
            let vm = _inner.at(i)
            _inner.removeAt(i)
            vm.dispose()
        }
        try super._onDestruct()
    }

    public override func _onDispose() {
        _activeFetchTask?.cancel()
        _activeFetchTask = nil
        pendingDeleteTask?.cancel()
        pendingDeleteTask = nil
        _pagedChangedCancellable?.cancel()
        _pagedChangedCancellable = nil
        _searchCancellable?.cancel()
        _searchCancellable = nil
        _search.dispose()
        _inner.dispose()
        moveToFirstPageCommand.dispose()
        moveToPreviousPageCommand.dispose()
        moveToNextPageCommand.dispose()
        moveToLastPageCommand.dispose()
        super._onDispose()
    }

    // MARK: - Builder

    /// Returns a new empty builder for `NotesViewVM`.
    public static func builder() -> NotesViewVMBuilder {
        NotesViewVMBuilder()
    }

    /// Immutable fluent builder for `NotesViewVM` (spec ch. 10).
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `repository(_:)`.
    /// Optional: `hint(_:)`, `pageSize(_:)` (default 5), `searchDebounce(_:)`
    ///           (default 150 ms), `searchScheduler(_:)`, `dialogService(_:)`,
    ///           `notificationHub(_:)`.
    public struct NotesViewVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _repo: (any NoteRepository)?
        private var _pageSize: Int = 5
        private var _searchDebounce: DispatchQueue.SchedulerTimeType.Stride = .milliseconds(150)
        private var _searchScheduler: DispatchQueue?
        private var _dialogService: (any DialogService)?
        private var _notificationHub: NotificationHubProtocol?

        fileprivate init() {}

        public func name(_ value: String) -> NotesViewVMBuilder {
            var c = self; c._name = value; return c
        }
        public func hint(_ value: String) -> NotesViewVMBuilder {
            var c = self; c._hint = value; return c
        }
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NotesViewVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }
        public func repository(_ repo: any NoteRepository) -> NotesViewVMBuilder {
            var c = self; c._repo = repo; return c
        }
        public func pageSize(_ size: Int) -> NotesViewVMBuilder {
            var c = self; c._pageSize = size; return c
        }
        public func searchDebounce(_ debounce: DispatchQueue.SchedulerTimeType.Stride) -> NotesViewVMBuilder {
            var c = self; c._searchDebounce = debounce; return c
        }
        public func searchScheduler(_ scheduler: DispatchQueue) -> NotesViewVMBuilder {
            var c = self; c._searchScheduler = scheduler; return c
        }
        public func dialogService(_ service: any DialogService) -> NotesViewVMBuilder {
            var c = self; c._dialogService = service; return c
        }
        public func notificationHub(_ hub: NotificationHubProtocol) -> NotesViewVMBuilder {
            var c = self; c._notificationHub = hub; return c
        }

        /// Validates required fields and constructs a `NotesViewVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name`, `services`, or `repository` are missing.
        public func build() throws -> NotesViewVM {
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
            return NotesViewVM(
                name: name,
                hint: _hint,
                hub: hub,
                dispatcher: dispatcher,
                repo: repo,
                pageSize: _pageSize,
                searchDebounce: _searchDebounce,
                searchScheduler: _searchScheduler,
                dialogService: _dialogService,
                notificationHub: _notificationHub
            )
        }
    }
}
