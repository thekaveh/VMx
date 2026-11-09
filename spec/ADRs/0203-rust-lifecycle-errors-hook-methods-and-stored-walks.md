# ADR 0203 — Rust lifecycle errors, hook methods and stored member walks

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (amends the Rust notes in chapter 02 §2.1, §2.2,
  §6.1 and §7.2, and in chapter 11 §4; `LIFE-005`, `LIFE-006`, `LIFE-008`,
  `LIFE-011`, `LIFE-021`)

## 1. Context

Three Rust gaps remained against chapter 02. The other flavors close each of
them.

1. Chapter 02 §2.1 requires the lifecycle transition error for an illegal
   call, and its message must name the current state and the operation. A
   Rust call from `Disposed` returned `VmxError::Disposed`, and a call during
   another transition returned `VmxError::ConcurrentOperation`. Neither variant
   names the state or the operation. ADR-0147 recorded this gap and left it
   open, because a fix changes the public Rust error contract (#1249).
1. Chapter 02 §2.2 gives every view-model three per-phase hooks. In Rust,
   `HierarchicalVm` and `ModeledCompositeVm` had no `on_construct`,
   `on_destruct` or `on_dispose` method, and `ForwardingCompositeVm` reached
   them only through `inner()`. ADR-0149 recorded this gap (#1250).
1. Chapter 02 §6.1 runs the child-transition helper inside the parent's hooks,
   so a background parent walks its members on the background dispatcher and
   `reconstruct()` walks them in both phases. The Rust walk methods took a
   borrowed closure for one call. Thus `construct_with_children` and
   `destruct_with_children` rejected a component built with `background(true)`,
   and `reconstruct()` and the reconstruct command ran no walk. ADR-0162 left
   the `'static` walk API for later (#1288).

Rust 0.36.0 is not released, so a breaking change can ship in it.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the cross-flavor-uniform
and simplest option in each case.

### 2.1. One lifecycle transition error

- Every illegal Rust `construct`, `destruct` or `reconstruct` returns
  `VmxError::InvalidLifecycleTransition { from, operation }`, the variant that
  already carried the state and the operation. This covers a call from
  `Disposed`, a call during the inline dispose cascade (`from` is `Disposed`,
  chapter 02 §7.2), and a call during another transition (`from` is the
  transient status, `LIFE-008`). A sealed construct whose `Constructed`
  publication has not started yet reports `Constructing`, because no observer
  has seen `Constructed`. The message reads
  `invalid lifecycle transition from <state> via <operation>`.
- The other flavors raise one error type for all of these cases, so Rust uses
  one variant too. A caller tells a concurrent call apart by its transient
  `from`, as a caller in the other flavors does.
- `VmxError::ConcurrentOperation` had no other producer, so it is removed.
  `VmxError::Disposed` stays for non-lifecycle operations, such as an add or a
  selection on a container whose disposal is pending.
- A `dispose()` never returned either variant. The aggregate check that treats
  a `VmxError::Disposed` from a replaced slot's disposal as success therefore
  keeps its behavior.

### 2.2. Hook methods on the three types

`HierarchicalVm`, `ModeledCompositeVm` and `ForwardingCompositeVm` gain public
`on_construct`, `on_destruct` and `on_dispose` methods with the `ComponentVm`
closure signature. Each replaces the hook of the wrapped `ComponentVm` or
`CompositeVm`. A failing construct hook rolls the node back as it rolls a
`ComponentVm` back. An eager `HierarchicalVm` runs the hook before it constructs
its children, and a failing hook constructs no child. The modeled composite's
hooks also run in both phases of `reconstruct()`.

### 2.3. Stored member walks and background walks

- `ComponentVm::on_construct_children(walk)` and `on_destruct_children(walk)`
  store a walk closure, as the hook methods store a hook. Every `construct()`,
  `destruct()`, `reconstruct()` and reconstruct command runs the stored walk
  after the hook, as the hooks of the other flavors call the helper. Clones of
  the component share the walks. A walk must capture the members, never the
  component (#750).
- A walk runs where the hook runs. For a component built with
  `background(true)`, the walk of a `construct` or `destruct` runs on the
  background dispatcher inside the same hook admission. A walk that still
  waits for a member hands the terminal publication to that member's settle,
  and a failed walk rolls the component back and reports the failure on
  `background_errors()`. The walk's own terminal or rollback status publishes
  on the foreground dispatcher (chapter 11 §3). This also holds for a member
  failure that arrives while the walk still runs.
- A reconstruct stays one synchronous operation on the calling thread for every
  component (chapter 11 §4). With a stored walk, it runs the destruct walk, then
  the construct walk once the destruct reaches `Destructed`, as
  `reconstruct_with_children` does.
- `construct_with_children` and `destruct_with_children` keep their names and
  run a walk for one call in place of the stored walk. Their walk closure must
  now be `Send + 'static`, so it can move to the background dispatcher. They no
  longer return `VmxError::InvalidArgument` for a background component.
  `reconstruct_with_children` keeps its signature.

## 3. Consequences

- Breaking Rust changes, recorded in the Rust CHANGELOG under 0.36.0: the
  lifecycle error variant for the two cases and the removal of
  `VmxError::ConcurrentOperation`.
- The `Send + 'static` bound on the walk closures of `construct_with_children`
  and `destruct_with_children` is not a break against a release. Those methods
  first ship in the unreleased 0.36.0 (ADR-0162), so the CHANGELOG lists the
  bound under Added. A walk that borrowed its members now captures clones of
  them.
- Chapter 02 §2.1, §2.2, §6.1 and §7.2, chapter 11 §4 and the `LIFE-021` text
  no longer state a Rust gap. The Rust capability-parity record no longer lists
  the forwarding-composite hook gap.
- The Rust lifecycle fixture test checks the state and the operation of every
  illegal row, including the rows from `Disposed`, `Constructing` and
  `Destructing`. No conformance ID is added.
- C#, Python, TypeScript and Swift do not change.
