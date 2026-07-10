//
// NotebooksRootVM — root of the notebooks tree.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/NotebooksRootVM.cs.
// See task-6-brief.md.
//
// VMx-API adaptation: owns a flat [NotebookVM] instead of a HierarchicalVM
// (same rationale as the C# port — flat mutation + ChildrenGetter closure is
// a cleaner fit for a freely-mutated parent-id collection). Publishes a
// library `TreeStructureChangedMessage` on structural mutations so
// subscribers observe changes identically to HierarchicalVM.
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_notifyPropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

/// Root view-model for the notebooks tree.
///
/// Conforms to `NewCreatable` (create-a-blank-notebook affordance);
/// `Reconstructable` is satisfied automatically via the library extension
/// `extension ComponentVMBase: Constructable, Destructable, Reconstructable {}`.
public final class NotebooksRootVM: ComponentVMBase, NewCreatable {

    // ── Private state ──────────────────────────────────────────────────────

    private let _repo: any NoteRepository
    private let _notificationHub: NotificationHubProtocol?
    private var _all: [NotebookVM] = []
    private var _current: NotebookVM?
    private var _createTasks: [Task<Void, Never>] = []

    // ── Commands ───────────────────────────────────────────────────────────

    /// Convenience command wired to `canCreateNew()` / `createNew()`.
    public private(set) var addNotebookCommand: RelayCommand

    // ── Public tree surface ────────────────────────────────────────────────

    /// Flat ordered list of all notebook VMs (all levels, insertion order).
    public var all: [NotebookVM] { _all }

    /// Root notebooks (no parent).
    public var roots: [NotebookVM] { _all.filter { $0.model.parentId == nil } }

    /// All notebooks in insertion order (parents before children, repo order).
    public func walk() -> [NotebookVM] { _all }

    /// Children of `parent` by `parentId` match.
    public func childrenOf(_ parent: NotebookVM) -> [NotebookVM] {
        _all.filter { $0.model.parentId == parent.model.id }
    }

    // ── Current selection ──────────────────────────────────────────────────

    /// Currently selected notebook (reference-guarded setter).
    ///
    /// Setting the same reference is a no-op. Emits a
    /// `PropertyChangedMessage` on the hub and fires `_notifyPropertyChanged`
    /// on change.
    public var current: NotebookVM? {
        get { _current }
        set {
            guard _current !== newValue else { return }
            _current = newValue
            _notifyPropertyChanged("current")
        }
    }

    // ── NewCreatable ───────────────────────────────────────────────────────

    public func canCreateNew() -> Bool { isConstructed }

    /// Synchronous capability entry point — fire-and-forgets a default
    /// "New Notebook" add.
    public func createNew() {
        let task = Task { [weak self] in
            guard let self else { return }
            await self.addNotebook(parentId: nil, name: "New Notebook")
        }
        _createTasks.append(task)
    }

    // ── Async operations ───────────────────────────────────────────────────

    /// Persists a new notebook via the repository, constructs its VM,
    /// appends it to `all`, and publishes a `TreeStructureChangedMessage`.
    /// Optionally posts a "Notebook added" notification when a
    /// `notificationHub` is wired.
    ///
    /// Async emit of structural changes is foreground-marshalled via the
    /// injected dispatcher (mirrors C# `_dispatcher.Foreground.Schedule`).
    public func addNotebook(parentId: String?, name notebookName: String) async {
        guard status != .disposed, !Task.isCancelled else { return }
        let uuid = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let id = "nb-\(uuid.prefix(5))"
        let model = NotebookModel(id: id, name: notebookName, parentId: parentId)
        try? await _repo.addNotebook(model)
        guard status != .disposed, !Task.isCancelled else { return }

        let vm = try! NotebookVM.builder()
            .name("nb:\(id)")
            .model(model)
            .services(hub: hub, dispatcher: dispatcher)
            .childrenGetter({ [weak self] parent in self?.childrenOf(parent) ?? [] })
            .build()
        try? vm.construct()
        _all.append(vm)

        // Notify the parent or raise "roots" on the foreground dispatcher —
        // this continuation runs off the UI thread after the repo await.
        if let pid = parentId {
            if let parent = _all.first(where: { $0.model.id == pid }) {
                dispatcher.scheduleForeground { [weak self, weak parent] in
                    guard let self, self.status != .disposed else { return }
                    parent?.notifyChildrenChanged()
                }
            }
        } else {
            dispatcher.scheduleForeground { [weak self] in
                guard let self, self.status != .disposed else { return }
                self._notifyPropertyChanged("roots")
            }
        }

        guard status != .disposed, !Task.isCancelled else { return }
        hub.send(TreeStructureChangedMessage(
            sender: self,
            senderName: self.name,
            change: .added,
            affected: vm,
            index: _all.count - 1
        ))

        if let notificationHub = _notificationHub {
            Task { [weak self] in
                guard let self, self.status != .disposed else { return }
                _ = await notificationHub.post(VMx.Notification(
                    type: .notification,
                    message: "Notebook added: \u{201C}\(notebookName)\u{201D}"
                ))
            }
        }
    }

    /// Loads all notebooks from the repository, replaces the flat list, and
    /// constructs each child VM. Intended to be called during workspace
    /// async construction.
    ///
    /// Foreground-marshals the `current` + `roots` raises because this
    /// continuation runs off the UI thread after `loadAll()`.
    public func populate() async throws {
        guard status != .disposed, !Task.isCancelled else { return }
        let (notebooks, _) = try await _repo.loadAll()
        guard status != .disposed, !Task.isCancelled else { return }

        // Dispose existing children before replacing.
        for nb in _all { nb.dispose() }
        _all.removeAll()
        _current = nil

        // Marshal the Current reset to the foreground (continuation is off-thread).
        dispatcher.scheduleForeground { [weak self] in
            guard let self, self.status != .disposed else { return }
            self._notifyPropertyChanged("current")
        }

        for nb in notebooks {
            let vm = try! NotebookVM.builder()
                .name("nb:\(nb.id)")
                .model(nb)
                .services(hub: hub, dispatcher: dispatcher)
                .childrenGetter({ [weak self] parent in self?.childrenOf(parent) ?? [] })
                .build()
            try? vm.construct()
            _all.append(vm)
        }

        guard status != .disposed, !Task.isCancelled else { return }
        // Structural reset notification — subscribers refresh their tree projections.
        hub.send(TreeStructureChangedMessage(
            sender: self,
            senderName: self.name,
            change: .added,
            affected: self,
            index: -1
        ))

        // Roots is a computed snapshot: an already-bound tree view only
        // re-reads it on an explicit raise. Marshal to the foreground.
        dispatcher.scheduleForeground { [weak self] in
            guard let self, self.status != .disposed else { return }
            self._notifyPropertyChanged("roots")
        }
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

        // Phase 1: placeholder command (required before super.init).
        addNotebookCommand = RelayCommand(task: nil, predicate: nil, triggers: [])

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // Phase 2: rewire with real self-capturing closures.
        addNotebookCommand = RelayCommand.builder()
            .predicate({ [weak self] in self?.canCreateNew() ?? false })
            .task({ [weak self] in self?.createNew() })
            .build()
    }

    // ── Lifecycle overrides ────────────────────────────────────────────────

    public override func _onDestruct() throws {
        for nb in _all { try? nb.destruct() }
        try super._onDestruct()
    }

    public override func _onDispose() {
        for task in _createTasks { task.cancel() }
        _createTasks.removeAll()
        for nb in _all { nb.dispose() }
        addNotebookCommand.dispose()
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder.
    public static func builder() -> NotebooksRootVMBuilder {
        NotebooksRootVMBuilder()
    }

    /// Immutable fluent builder for `NotebooksRootVM` (spec ch. 10).
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `repository(_:)`.
    /// Optional: `hint(_:)`, `notificationHub(_:)`.
    public struct NotebooksRootVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _repo: (any NoteRepository)?
        private var _notificationHub: NotificationHubProtocol?

        fileprivate init() {}

        public func name(_ value: String) -> NotebooksRootVMBuilder {
            var c = self; c._name = value; return c
        }
        public func hint(_ value: String) -> NotebooksRootVMBuilder {
            var c = self; c._hint = value; return c
        }
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> NotebooksRootVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }
        public func repository(_ repo: any NoteRepository) -> NotebooksRootVMBuilder {
            var c = self; c._repo = repo; return c
        }
        public func notificationHub(_ hub: NotificationHubProtocol) -> NotebooksRootVMBuilder {
            var c = self; c._notificationHub = hub; return c
        }

        /// Validates required fields and constructs a `NotebooksRootVM`.
        ///
        /// - Throws: `BuilderValidationError` if `name`, `services`, or
        ///   `repository` are missing.
        public func build() throws -> NotebooksRootVM {
            guard let name = _name else { throw BuilderValidationError(missingField: "name") }
            guard let hub = _hub else { throw BuilderValidationError(missingField: "hub") }
            guard let dispatcher = _dispatcher else { throw BuilderValidationError(missingField: "dispatcher") }
            guard let repo = _repo else { throw BuilderValidationError(missingField: "repository") }
            return NotebooksRootVM(
                name: name, hint: _hint,
                hub: hub, dispatcher: dispatcher,
                repo: repo, notificationHub: _notificationHub
            )
        }
    }
}
