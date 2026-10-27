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
///
/// `expandCommand`, `collapseCommand` and `toggleExpansionCommand` wrap the
/// three verbs (ADR-0159). Each is built on its first read, so a helper whose
/// commands are never read holds no trigger subscriptions and disposal creates
/// none.
public final class ExpandableState: Expandable, Collapsible, ExpansionTogglable {
    private let expandedSubject: CurrentValueSubject<Bool, Never>
    private var disposed = false
    private var builtExpandCommand: RelayCommand?
    private var builtCollapseCommand: RelayCommand?
    private var builtToggleExpansionCommand: RelayCommand?

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

    /// Runs `expand()` when `canExpand()` is true. This helper owns the
    /// command: `dispose()` disposes it, and callers must not.
    public var expandCommand: RelayCommand {
        if let command = builtExpandCommand { return command }
        let command = buildCommand(
            predicate: { [weak self] in self?.canExpand() ?? false },
            task: { [weak self] in self?.expand() }
        )
        builtExpandCommand = command
        return command
    }

    /// Runs `collapse()` when `canCollapse()` is true. This helper owns the
    /// command: `dispose()` disposes it, and callers must not.
    public var collapseCommand: RelayCommand {
        if let command = builtCollapseCommand { return command }
        let command = buildCommand(
            predicate: { [weak self] in self?.canCollapse() ?? false },
            task: { [weak self] in self?.collapse() }
        )
        builtCollapseCommand = command
        return command
    }

    /// Runs `toggleExpansion()` when `canToggleExpansion()` is true. This
    /// helper owns the command: `dispose()` disposes it, and callers must not.
    public var toggleExpansionCommand: RelayCommand {
        if let command = builtToggleExpansionCommand { return command }
        let command = buildCommand(
            predicate: { [weak self] in self?.canToggleExpansion() ?? false },
            task: { [weak self] in self?.toggleExpansion() }
        )
        builtToggleExpansionCommand = command
        return command
    }

    public func canExpand() -> Bool { !expandedSubject.value }

    public func expand() {
        guard !disposed, !expandedSubject.value else { return }
        expandedSubject.send(true)
    }

    public func canCollapse() -> Bool { expandedSubject.value }

    public func collapse() {
        guard !disposed, expandedSubject.value else { return }
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

    /// Dispose the commands that were read, complete `isExpandedChanged`, and
    /// make later mutations inert. `isExpanded` retains its last reading.
    /// Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        builtExpandCommand?.dispose()
        builtCollapseCommand?.dispose()
        builtToggleExpansionCommand?.dispose()
        expandedSubject.send(completion: .finished)
    }

    // The closures hold the helper weakly, so the cached commands do not keep
    // it alive. A command read after disposal is built without the completed
    // trigger and disposed at once, so it is inert like the others (ADR-0068).
    private func buildCommand(
        predicate: @escaping () -> Bool,
        task: @escaping () -> Void
    ) -> RelayCommand {
        var builder = RelayCommand.builder().predicate(predicate).task(task)
        if !disposed {
            builder = builder.triggers(
                isExpandedChanged.map { _ in () }.eraseToAnyPublisher()
            )
        }
        let command = builder.build()
        if disposed { command.dispose() }
        return command
    }
}
