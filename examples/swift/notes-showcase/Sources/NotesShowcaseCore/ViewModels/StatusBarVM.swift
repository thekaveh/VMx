//
// StatusBarVM — three DerivedProperty<String> slots for the status bar.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/StatusBarVM.cs.
// See task-6-brief.md.
//
// Three slots (all `DerivedProperty<String>`, read-only):
//   noteCountText  — "N note(s)"      from NotesViewVM.filteredItems.count
//   starredText    — "K starred"       from NotesViewVM.filteredItems (starred filter)
//   editingText    — "Editing: TITLE [*]" / "No selection" from NoteFormVM state
//
// Each slot is backed by a `CurrentValueSubject` (= C# BehaviorSubject).
// Hub subscriptions detect property changes from the source VMs and re-send
// the source VM on the subject, triggering a DerivedProperty recompute.
// The re-send is foreground-marshalled to keep recomputes on the UI thread.
//
// Note: BindableDerived sidecars are skipped here — they are wired in Task 8
// (Swift has no INPC, so SwiftUI/AppKit bindings use a different mechanism).
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_raisePropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

/// Read-only VM driving the three status-bar slots.
///
/// Each slot is a `DerivedProperty<String>` recomputed whenever the relevant
/// source VM emits a `PropertyChangedMessage` on the shared hub.
public final class StatusBarVM: ComponentVMBase {

    // ── Private state ──────────────────────────────────────────────────────

    private let _notesView: NotesViewVM
    private let _noteForm: NoteFormVM

    private let _nvSubject: CurrentValueSubject<NotesViewVM, Never>
    private let _nfSubject: CurrentValueSubject<NoteFormVM, Never>

    private var _nvCancellable: AnyCancellable?
    private var _nfCancellable: AnyCancellable?

    // ── Derived properties ─────────────────────────────────────────────────

    /// "N note(s)" — total count of filtered items in the note list.
    public let noteCountText: DerivedProperty<String>

    /// "K starred" — count of starred items in the filtered list.
    public let starredText: DerivedProperty<String>

    /// "Editing: TITLE [*]" when the form is bound and dirty;
    /// "Editing: TITLE" when bound and clean; "No selection" when unbound.
    public let editingText: DerivedProperty<String>

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        notesView: NotesViewVM,
        noteForm: NoteFormVM
    ) {
        _notesView = notesView
        _noteForm  = noteForm

        // Phase 1: create subjects (BehaviorSubject equivalents) before
        // super.init, then create DerivedProperties from them.  We use local
        // vars so that the closures below don't capture `self` before init.
        let nvSubject = CurrentValueSubject<NotesViewVM, Never>(notesView)
        let nfSubject = CurrentValueSubject<NoteFormVM, Never>(noteForm)
        _nvSubject = nvSubject
        _nfSubject = nfSubject

        noteCountText = DerivedProperty<String>.from(nvSubject.eraseToAnyPublisher()) { nv in
            let c = nv.filteredItems.count
            return "\(c) note\(c == 1 ? "" : "s")"
        }
        starredText = DerivedProperty<String>.from(nvSubject.eraseToAnyPublisher()) { nv in
            let k = nv.filteredItems.filter { $0.starred }.count
            return "\(k) starred"
        }
        editingText = DerivedProperty<String>.from(nfSubject.eraseToAnyPublisher()) { nf in
            guard nf.hasBoundNote else { return "No selection" }
            let dirty = nf.isDirty ? " *" : ""
            return "Editing: \(nf.draft.title)\(dirty)"
        }

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        // Phase 2: wire hub subscriptions (safe to capture `self` now).
        //
        // Pattern mirrors C# `.Where(m => ReferenceEquals(m.Sender, notesView))`:
        // filter `PropertyChangedMessage`s whose `sender` is the watched VM,
        // then foreground-marshal the subject re-send.
        _nvCancellable = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak notesView] m in m.sender === notesView }
            .sink { [weak self] _ in
                guard let self else { return }
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    self._nvSubject.send(self._notesView)
                }
            }

        _nfCancellable = hub.messages
            .compactMap { $0 as? PropertyChangedMessage }
            .filter { [weak noteForm] m in m.sender === noteForm }
            .sink { [weak self] _ in
                guard let self else { return }
                self.dispatcher.scheduleForeground { [weak self] in
                    guard let self else { return }
                    self._nfSubject.send(self._noteForm)
                }
            }
    }

    // ── Lifecycle overrides ────────────────────────────────────────────────

    public override func _onDispose() {
        _nvCancellable?.cancel()
        _nvCancellable = nil
        _nfCancellable?.cancel()
        _nfCancellable = nil
        _nvSubject.send(completion: .finished)
        _nfSubject.send(completion: .finished)
        noteCountText.dispose()
        starredText.dispose()
        editingText.dispose()
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder.
    public static func builder() -> StatusBarVMBuilder {
        StatusBarVMBuilder()
    }

    /// Immutable fluent builder for `StatusBarVM`.
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `notesView(_:)`,
    /// `notebooks(_:)` (retained for cross-flavor parity; unused internally),
    /// `noteForm(_:)`.
    public struct StatusBarVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _notesView: NotesViewVM?
        private var _noteForm: NoteFormVM?

        fileprivate init() {}

        public func name(_ value: String) -> StatusBarVMBuilder {
            var c = self; c._name = value; return c
        }
        public func hint(_ value: String) -> StatusBarVMBuilder {
            var c = self; c._hint = value; return c
        }
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> StatusBarVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }
        public func notesView(_ vm: NotesViewVM) -> StatusBarVMBuilder {
            var c = self; c._notesView = vm; return c
        }
        /// Kept for cross-flavor builder parity; `NotebooksRootVM` is not
        /// currently used in the status-bar computation.
        public func notebooks(_ vm: NotebooksRootVM) -> StatusBarVMBuilder { self }
        public func noteForm(_ vm: NoteFormVM) -> StatusBarVMBuilder {
            var c = self; c._noteForm = vm; return c
        }

        /// Validates required fields and constructs a `StatusBarVM`.
        ///
        /// - Throws: `BuilderValidationError` if any required field is missing.
        public func build() throws -> StatusBarVM {
            guard let name = _name else { throw BuilderValidationError(missingField: "name") }
            guard let hub = _hub else { throw BuilderValidationError(missingField: "hub") }
            guard let dispatcher = _dispatcher else { throw BuilderValidationError(missingField: "dispatcher") }
            guard let notesView = _notesView else { throw BuilderValidationError(missingField: "notesView") }
            guard let noteForm = _noteForm else { throw BuilderValidationError(missingField: "noteForm") }
            return StatusBarVM(
                name: name, hint: _hint,
                hub: hub, dispatcher: dispatcher,
                notesView: notesView, noteForm: noteForm
            )
        }
    }
}
