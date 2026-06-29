//
// Lifecycle capability micro-interfaces — `Constructable`, `Destructable`,
// `Reconstructable`.
//
// Ports langs/typescript/src/capabilities/lifecycleCapabilities.ts. See
// spec/14-capabilities.md §Lifecycle and
// spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// Unlike the other capability micro-interfaces these three are BASELINE: every
// core VM trivially satisfies them, because the five-state lifecycle is part of
// the `ComponentVMBase` contract. `ComponentVMBase` conforms to all three (see
// the conformance extension at the foot of this file) so every concrete VM —
// `ComponentVM`, `CompositeVM`, `GroupVM`, `AggregateVMn`, … — advertises the
// lifecycle triple by inheritance, while non-baseline capabilities remain
// strictly opt-in (CAP-020).
//
// The three verbs are `throws` (ADR-0053: Swift converged on the throwing
// lifecycle contract — an illegal transition surfaces a catchable
// `StatusTransitionError` rather than trapping). Their signatures match
// `ComponentVMBase.construct()` / `destruct()` / `reconstruct()` exactly, so the
// base satisfies the protocols with no additional members.
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//

/// A VM whose construction lifecycle phase can be entered.
public protocol Constructable {
    /// Whether `construct()` may currently be invoked.
    func canConstruct() -> Bool
    /// Enter the constructed state.
    func construct() throws
}

/// A VM whose destruction lifecycle phase can be entered.
public protocol Destructable {
    /// Whether `destruct()` may currently be invoked.
    func canDestruct() -> Bool
    /// Enter the destructed state.
    func destruct() throws
}

/// A VM that can be torn down and rebuilt in a single step.
public protocol Reconstructable {
    /// Whether `reconstruct()` may currently be invoked.
    func canReconstruct() -> Bool
    /// Destruct then re-construct.
    func reconstruct() throws
}

// `ComponentVMBase` already declares `canConstruct()/construct() throws`,
// `canDestruct()/destruct() throws`, and `canReconstruct()/reconstruct() throws`
// at exactly these signatures, so the lifecycle triple is satisfied by a bare
// conformance declaration — making the baseline capability set (CAP-018/020)
// available on every VM by inheritance, with no non-baseline capability implied.
extension ComponentVMBase: Constructable, Destructable, Reconstructable {}
