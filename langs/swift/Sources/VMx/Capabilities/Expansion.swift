//
// Expansion capability micro-interfaces — `Expandable`, `Collapsible`,
// `ExpansionTogglable` — plus the `ExpandableState` composition helper.
//
// Ports langs/typescript/src/capabilities/expansion.ts and
// langs/typescript/src/capabilities/expandableState.ts. See
// spec/14-capabilities.md §2.2, spec/ADRs/0057-v3-capability-micro-interface-granularity.md,
// and ADR-0015.
//
// As with the selection triple (§2.1), `ExpansionTogglable` is a distinct opt-in
// contract, NOT an implied `Expandable + Collapsible`. When all three are present
// `toggleExpansion()` delegates to `expand()` / `collapse()`, while
// `canToggleExpansion()` is reported independently (ADR-0057 §2.1).
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//
import Combine

/// A VM that can be expanded. `isExpanded` is read-only on this contract; a
/// setter (if any) belongs to the concrete VM (spec/14 §2.2).
public protocol Expandable {
    /// Whether this VM is currently expanded.
    var isExpanded: Bool { get }
    /// Whether `expand()` may currently be invoked.
    func canExpand() -> Bool
    /// Expand this VM.
    func expand()
}

/// A VM that can be collapsed.
public protocol Collapsible {
    /// Whether `collapse()` may currently be invoked.
    func canCollapse() -> Bool
    /// Collapse this VM.
    func collapse()
}

/// A VM that exposes a single disclosure "toggle" affordance. Independent of
/// `Expandable` / `Collapsible` (ADR-0057 §2.1).
public protocol ExpansionTogglable {
    /// Whether `toggleExpansion()` may currently be invoked.
    func canToggleExpansion() -> Bool
    /// Flip this VM's expansion state.
    func toggleExpansion()
}

/// Composition-friendly helper implementing the full expansion triple over a
/// single boolean. Mirrors `expandableState.ts`.
///
/// State is held in a `CurrentValueSubject<Bool, Never>` so `isExpanded` is a
/// synchronous read of the latest value. `expand()` / `collapse()` are guarded:
/// a no-op transition publishes nothing. `toggleExpansion()` flips the state, so
/// a double-toggle returns to the initial value (CAP-003/006 idempotence).
public final class ExpandableState: Expandable, Collapsible, ExpansionTogglable {
    private let expandedSubject: CurrentValueSubject<Bool, Never>
    private var disposed = false

    /// - Parameter initiallyExpanded: the starting expansion state (default
    ///   collapsed).
    public init(initiallyExpanded: Bool = false) {
        self.expandedSubject = CurrentValueSubject(initiallyExpanded)
    }

    /// Latest expansion state.
    public var isExpanded: Bool { expandedSubject.value }

    /// Emits each post-construction expansion transition (never replays the
    /// initial value — `dropFirst()` skips the behavior-subject's replay).
    /// Completes on `dispose()`.
    public var isExpandedChanged: AnyPublisher<Bool, Never> {
        expandedSubject.dropFirst().eraseToAnyPublisher()
    }

    public func canExpand() -> Bool { !expandedSubject.value }

    public func expand() {
        guard !expandedSubject.value else { return }
        expandedSubject.send(true)
    }

    public func canCollapse() -> Bool { expandedSubject.value }

    public func collapse() {
        guard expandedSubject.value else { return }
        expandedSubject.send(false)
    }

    public func canToggleExpansion() -> Bool { true }

    public func toggleExpansion() {
        if expandedSubject.value {
            collapse()
        } else {
            expand()
        }
    }

    /// Complete `isExpandedChanged` and halt further notifications. `isExpanded`
    /// retains its last reading. Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        expandedSubject.send(completion: .finished)
    }
}
