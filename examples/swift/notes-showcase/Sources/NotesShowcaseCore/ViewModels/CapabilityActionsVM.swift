//
// CapabilityActionsVM — projects a focused VM's capability surface into
// a flat [ActionVM] list for the action bar.
//
// Ports examples/csharp/avalonia/NotesShowcase/ViewModels/CapabilityActionsVM.cs.
// See task-6-brief.md.
//
// Architecture (spec ch. 14 §4 / plan §3.a.10):
//   The focused VM is injected via a delegate (`() -> AnyObject?`) so the host
//   can define "focus" as it likes (last-selected across tree + list + form).
//   `recomputeActions()` pushes the delegate's return value onto a
//   `CurrentValueSubject`, triggering the `DerivedProperty<[ActionVM]>` to
//   recompute via `project(_:)`.
//
//   `ActionVM` is `Equatable` (via command identity) so `DerivedProperty`'s
//   distinct-until-changed suppressor works correctly.
//
// Cross-module subclassing enabled by ADR-0066: `hub`, `dispatcher`, and
// `_raisePropertyChanged` are `public` on `ComponentVMBase`.
//
import Foundation
import Combine
import VMx

/// Projects a focused VM's capability protocols into a flat `[ActionVM]` list.
///
/// Call `recomputeActions()` after any focus change to refresh the list.
public final class CapabilityActionsVM: ComponentVMBase {

    // ── Private state ──────────────────────────────────────────────────────

    private let _focusedGetter: () -> AnyObject?
    private let _focusSubject: CurrentValueSubject<AnyObject?, Never>

    // ── Derived property ───────────────────────────────────────────────────

    /// Projected action list.
    ///
    /// Backed by a `DerivedProperty<[ActionVM]>` that recomputes whenever
    /// `recomputeActions()` is called (or on construction with the initial
    /// focused value from the getter).
    public let actions: DerivedProperty<[ActionVM]>

    // ── Public API ─────────────────────────────────────────────────────────

    /// Inspects the focused VM (via the injected getter) and refreshes
    /// the `actions` list.
    ///
    /// The host calls this after focus changes — e.g. from a hub subscription
    /// on selection messages — to keep the action bar in sync without coupling
    /// `CapabilityActionsVM` to the focus-tracking mechanism.
    public func recomputeActions() {
        _focusSubject.send(_focusedGetter())
    }

    // ── Capability projection ──────────────────────────────────────────────

    /// Maps `focused`'s conformances to capability protocols → `[ActionVM]`.
    ///
    /// Mirrors C# `Project(object? focused)`, preserving the same ordering:
    /// Selection → Expansion → Dialog → CRUD → Lifecycle.
    ///
    /// For `NoteVM` specifically, `Save` and `Delete` reuse `NoteVM.saveCommand`
    /// / `NoteVM.deleteCommand` directly so the confirmation decorator and
    /// "Note deleted" notification fire identically from the action bar and
    /// from the in-list delete button.
    public static func project(_ focused: AnyObject?) -> [ActionVM] {
        guard let focused else { return [] }
        var actions: [ActionVM] = []

        // ── Selection ──────────────────────────────────────────────────────

        if let sel = focused as? Selectable {
            actions.append(ActionVM(
                label: "Select",
                command: RelayCommand.builder()
                    .predicate({ sel.canSelect() })
                    .task({ sel.select() })
                    .build()
            ))
        }
        if let des = focused as? Deselectable {
            actions.append(ActionVM(
                label: "Deselect",
                command: RelayCommand.builder()
                    .predicate({ des.canDeselect() })
                    .task({ des.deselect() })
                    .build()
            ))
        }
        if let sst = focused as? SelectionTogglable {
            actions.append(ActionVM(
                label: "Toggle Selection",
                command: RelayCommand.builder()
                    .predicate({ sst.canToggleSelection() })
                    .task({ sst.toggleSelection() })
                    .build()
            ))
        }

        // ── Expansion ──────────────────────────────────────────────────────

        if let exp = focused as? Expandable {
            actions.append(ActionVM(
                label: "Expand",
                command: RelayCommand.builder()
                    .predicate({ exp.canExpand() })
                    .task({ exp.expand() })
                    .build()
            ))
        }
        if let col = focused as? Collapsible {
            actions.append(ActionVM(
                label: "Collapse",
                command: RelayCommand.builder()
                    .predicate({ col.canCollapse() })
                    .task({ col.collapse() })
                    .build()
            ))
        }
        if let exTog = focused as? ExpansionTogglable {
            actions.append(ActionVM(
                label: "Toggle Expansion",
                command: RelayCommand.builder()
                    .predicate({ exTog.canToggleExpansion() })
                    .task({ exTog.toggleExpansion() })
                    .build()
            ))
        }

        // ── Dialog ─────────────────────────────────────────────────────────

        if let cls = focused as? Closable {
            actions.append(ActionVM(
                label: "Close",
                command: RelayCommand.builder()
                    .predicate({ cls.canClose() })
                    .task({ cls.close() })
                    .build()
            ))
        }
        if let apr = focused as? Approvable {
            actions.append(ActionVM(
                label: "Approve",
                command: RelayCommand.builder()
                    .predicate({ apr.canApprove() })
                    .task({ apr.approve() })
                    .build()
            ))
        }
        if let cnc = focused as? Cancelable {
            actions.append(ActionVM(
                label: "Cancel",
                command: RelayCommand.builder()
                    .predicate({ cnc.canCancel() })
                    .task({ cnc.cancel() })
                    .build()
            ))
        }

        // ── CRUD ───────────────────────────────────────────────────────────

        if let nc = focused as? NewCreatable {
            actions.append(ActionVM(
                label: "New",
                command: RelayCommand.builder()
                    .predicate({ nc.canCreateNew() })
                    .task({ nc.createNew() })
                    .build()
            ))
        }

        // Save / Delete reuse NoteVM's own commands directly (scenario §6.2).
        // This preserves the confirmation decorator and notification post.
        if let noteSelf = focused as? NoteVM {
            // NoteVM conforms to Savable<NoteVM> and Deletable<NoteVM>.
            actions.append(ActionVM(label: "Save",   command: noteSelf.saveCommand))
            actions.append(ActionVM(label: "Delete", command: noteSelf.deleteCommand))
        }

        // ── Lifecycle ──────────────────────────────────────────────────────

        if let rec = focused as? Reconstructable {
            actions.append(ActionVM(
                label: "Reconstruct",
                command: RelayCommand.builder()
                    .predicate({ rec.canReconstruct() })
                    .task({ try? rec.reconstruct() })
                    .build()
            ))
        }

        return actions
    }

    // ── Init ───────────────────────────────────────────────────────────────

    private init(
        name: String,
        hint: String,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        focusedGetter: @escaping () -> AnyObject?
    ) {
        _focusedGetter = focusedGetter
        let subject = CurrentValueSubject<AnyObject?, Never>(focusedGetter())
        _focusSubject = subject

        actions = DerivedProperty<[ActionVM]>.from(
            subject.eraseToAnyPublisher(),
            CapabilityActionsVM.project
        )

        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)
    }

    // ── Lifecycle overrides ────────────────────────────────────────────────

    public override func _onDispose() {
        actions.dispose()
        _focusSubject.send(completion: .finished)
        super._onDispose()
    }

    // ── Builder ────────────────────────────────────────────────────────────

    /// Returns a new empty builder.
    public static func builder() -> CapabilityActionsVMBuilder {
        CapabilityActionsVMBuilder()
    }

    /// Immutable fluent builder for `CapabilityActionsVM`.
    ///
    /// Required: `name(_:)`, `services(hub:dispatcher:)`, `focusedGetter(_:)`.
    /// Optional: `hint(_:)`.
    public struct CapabilityActionsVMBuilder {
        private var _name: String?
        private var _hint: String = ""
        private var _hub: MessageHubProtocol?
        private var _dispatcher: Dispatcher?
        private var _focusedGetter: (() -> AnyObject?)?

        fileprivate init() {}

        public func name(_ value: String) -> CapabilityActionsVMBuilder {
            var c = self; c._name = value; return c
        }
        public func hint(_ value: String) -> CapabilityActionsVMBuilder {
            var c = self; c._hint = value; return c
        }
        public func services(hub: MessageHubProtocol, dispatcher: Dispatcher) -> CapabilityActionsVMBuilder {
            var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
        }
        /// Injects the getter that returns the currently-focused VM (or `nil`).
        public func focusedGetter(_ getter: @escaping () -> AnyObject?) -> CapabilityActionsVMBuilder {
            var c = self; c._focusedGetter = getter; return c
        }

        /// Validates required fields and constructs a `CapabilityActionsVM`.
        ///
        /// - Throws: `BuilderValidationError` if any required field is missing.
        public func build() throws -> CapabilityActionsVM {
            guard let name = _name else { throw BuilderValidationError(missingField: "name") }
            guard let hub = _hub else { throw BuilderValidationError(missingField: "hub") }
            guard let dispatcher = _dispatcher else { throw BuilderValidationError(missingField: "dispatcher") }
            guard let getter = _focusedGetter else { throw BuilderValidationError(missingField: "focusedGetter") }
            return CapabilityActionsVM(
                name: name, hint: _hint,
                hub: hub, dispatcher: dispatcher,
                focusedGetter: getter
            )
        }
    }
}
