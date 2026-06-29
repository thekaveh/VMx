//
// Dialog / form capability micro-interfaces — `Closable`, `Approvable`,
// `Cancelable`.
//
// Ports langs/typescript/src/capabilities/dialog.ts. See
// spec/14-capabilities.md §2.4 and spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// Three independent, opt-in contracts (ADR-0010): a VM advertises exactly the
// dialog verbs it supports. Swift idiom: bare protocol names (no `I`-prefix),
// camelCase members.
//

/// A VM that can be closed (e.g. a dialog or pane).
public protocol Closable {
    /// Whether `close()` may currently be invoked.
    func canClose() -> Bool
    /// Close this VM.
    func close()
}

/// A VM that can be approved (e.g. an OK / confirm affordance).
public protocol Approvable {
    /// Whether `approve()` may currently be invoked.
    func canApprove() -> Bool
    /// Approve this VM.
    func approve()
}

/// A VM that can be cancelled.
public protocol Cancelable {
    /// Whether `cancel()` may currently be invoked.
    func canCancel() -> Bool
    /// Cancel this VM.
    func cancel()
}
