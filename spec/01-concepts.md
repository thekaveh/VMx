# 01 — Core concepts

This document introduces the VMx mental model. Subsequent sections (`02-lifecycle.md`
onwards) give precise normative definitions; this document is the orientation.

## 1. The viewmodel hierarchy

VMx defines the following viewmodel types (five families, plus a pair of
forwarding decorators that wrap an inner viewmodel). The flat shape — five
independent families rather than a single inheritance chain — is the
canonical decision documented in ADR-0018:

| Family                                            | Role                                  | Children                        | Typical use                            |
| ------------------------------------------------- | ------------------------------------- | ------------------------------- | -------------------------------------- |
| `ComponentVM`                                     | leaf                                  | none                            | a single addressable VM with state     |
| `ReadonlyComponentVM`                             | leaf, immutable model                 | none                            | read-only view of a model              |
| `CompositeVM`                                     | container with selection              | `IList<VM>` + `Current`         | a tab strip, a navigation tree         |
| `GroupVM`                                         | container without selection           | `IList<VM>`                     | peers shown side-by-side               |
| `AggregateVM<VM1..VM6>`                           | fixed tuple of heterogeneous children | 1–6 typed slots                 | a screen composed of distinct sub-VMs  |
| `ForwardingComponentVM` / `ForwardingCompositeVM` | decorator                             | wraps another VM                | proxies, caching, instrumentation      |
| `HierarchicalVM<TModel, TVM>` (v2.1)              | recursive tree VM                     | lazy/eager `IList<TVM>` subtree | file-system tree, org-chart, menu      |
| `FormVM<TM>` (v2.1)                               | snapshot/revert edit VM               | none (embeds model snapshot)    | edit forms with approve/deny lifecycle |

`HierarchicalVM` is specified in chapter 18; `FormVM` in chapter 20.

### 1.0 Cross-language naming

The five active flavors share the same conceptual contracts and complete
conformance catalog; accepted language adaptations and Rust's tracked
source-surface convergence backlog mean that catalog completeness is not a
claim of member-for-member API identity. Identifier casing follows the
per-language idiom defined by ADR-0006. The same logical type appears under the
following names:

| Concept            | C#                        | Python             | TypeScript                | Swift                     | Rust                    |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- | ----------------------- |
| Unmodeled VM       | `ComponentVM`             | `ComponentVM`      | `ComponentVM`             | `ComponentVM`             | `ComponentVm`           |
| Modeled VM         | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        | `ComponentVm<M>`        |
| Status property    | `Status`                  | `status`           | `status`                  | `status`                  | `status()`              |
| Builder entrypoint | `Builder()`               | `builder()`        | `builder()`               | `builder()`               | `builder()`             |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` | `NullMessageHub::hub()` |

C# uses PascalCase, Python and Rust methods use snake_case, TypeScript and Swift use
camelCase. The single substantive divergence is that C# names the modeled
variant with a generic-parameter suffix on the same identifier
(`ComponentVM<M>`), while Python, TypeScript, and Swift expose a separate
`ComponentVMOf` type because their generics syntax cannot overload an
unparameterised name. Throughout this spec, statements about
`ComponentVM<M>` apply equally to `ComponentVMOf[M]` and
`ComponentVMOf<M>` unless explicitly called out. The Swift flavor reached
full library parity in v3.1.0; see
[`langs/swift/README.md` §5](../langs/swift/README.md) for the current
conformance matrix and documented Swift-specific divergences.

**Rendering VMs** (opt-in sub-package, chapter 16): `NotificationVM` and `ConfirmationVM`
are render-side VMs with auto-dismiss lifecycle, suitable for toast/banner UI.

**Collection primitives** (opt-in, chapter 21): `ServicedObservableCollection<T>`,
`ObservableList<T>`, `ObservableDictionary<K1,K2,V>`, and `PagedComposition<TVM>` sit
above the standard language collection types and integrate with the message hub and
paging capability.

Every VM is also a `ComponentVM` (inheritance / protocol composition per language). A
composite's children are themselves VMs and may be composites, components, etc.

### 1.1 Modeled and readonly variants

VMx uses "modeled" to describe two distinct patterns:

- **Modeled component** (`ComponentVM<M>`) — the VM holds a `Model` of type `M` as a
  settable property. Replacing the model (`vm.Model = m'`) fires `PropertyChangedMessage`.
- **Readonly component** (`ReadonlyComponentVM<M>`) — the VM is constructed with a model
  and the model is final. No setter is exposed.
- **Modeled composite** (`CompositeVM<M, VM>`) — `M` parameterizes the *children factory*
  rather than a top-level property; the composite does not expose `M` directly. See
  `06-composite-vm.md` for the full contract.

The shared idea is that `M` is the *domain shape* the VM (or its children) wrap; the
exact surface differs by VM family.

### 1.2 `Current` selection contract

Each `CompositeVM<VM>` has an optional `Current` child. The contract:

- At most one child is `Current` at any time.
- Setting `Current = c` requires `c ∈ children` (otherwise the operation MUST raise).
- Setting `Current = None` is legal at any time.
- The `Current` setter MAY dispatch asynchronously if the builder enabled
  `AsyncSelection(true)`.
- Child VMs observe their selection state via their `IsCurrent` property (raised
  through `PropertyChangedMessage`).

`GroupVM<VM>` has no `Current`. Children are peers.

### 1.3 `IComponentVM` baseline

Every viewmodel exposes:

- `Name : string` — immutable post-construction; an identifier for the VM.
- `Hint : string` — immutable post-construction; a human-readable hint.
- `Type : ViewModelType` — enum (`Component`, `ReadOnlyComponent`, `Aggregate`,
  `Group`, `Composite`); immutable.
- `IsCurrent : bool` — derived from parent's `Current` reference. Raised through
  property-change notification.
- `IsConstructed : bool` — equals `Status == Constructed`. Raised when `Status`
  changes.
- `Status : ConstructionStatus` — the lifecycle state. See `02-lifecycle.md`.
- `Parent` — an internal back-reference to the container (`CompositeVM` or `GroupVM`)
  that currently holds this VM as a child, or `null` when the VM is not a member of
  any container. It is **not** part of the public, consumer-settable surface and is
  **not** observable (a change to `Parent` does NOT publish a `PropertyChangedMessage`);
  it exists solely to back the selection predicates (`can_select` / `can_deselect` /
  `select` / `deselect`) and `IsCurrent`. The container sets it when the VM is added
  (`Add` / `Insert`, or wired as a child at build time) and clears it to `null` when
  the VM is removed (`Remove` / `RemoveAt` / `Clear`) or re-parented — see `05` §6.1
  for the precise contract and `06`/`07` for the container side. Reference
  implementations type it as a minimal internal parent interface
  (`IParentCompositeVM` / `_ParentCompositeVM` / `IParentVM`) exposing only the
  members the child needs for selection delegation, not the full container VM.
- The lifecycle commands: `SelectCommand`, `DeselectCommand`, `SelectNextCommand`,
  `SelectPreviousCommand`, `ReconstructCommand`. Each is an `ICommand`-equivalent
  with appropriate predicates.

### 1.4 Shared VM collection capability

`CompositeVM<VM>` and `GroupVM<VM>` implement one public ordered child-
collection capability (ADR-0085). It contains lifecycle-aware add, insert,
remove, indexed remove, replace, clear, atomic move, count, indexed and iterable
reads, collection-change observation, and batch updates. Its idiomatic names
are `IVmCollection<VM>` (C# / TypeScript), `VmCollectionProto[VM]` (Python),
`VMCollection` (Swift), and `VmCollection<T>` (Rust).

Selection is intentionally layered as a second capability:
`ISelectableVmCollection<VM>` / `SelectableVmCollectionProto` /
`SelectableVMCollection` / `SelectableVmCollection<T>`. `CompositeVM`
implements it; `GroupVM` does not acquire a `Current` placeholder.

`move(fromIndex, toIndex)` changes ordering only. Both indices use the
pre-move `[0, Count)` domain and the child occupies `toIndex` afterward. Equal
indices are silent no-ops. Invalid indices raise before mutation. A successful
move emits one `Move` event containing the same child and both indices, or is
coalesced into the outer batch `Reset`. Identity, parent, lifecycle,
subscriptions, auto-construction count, and a composite's `Current` reference
remain unchanged. Chapters 06 and 07 define the container-specific details;
`COL-032..039` are normative.

## 2. Dependency philosophy

Every VM receives two cross-cutting services:

- `IMessageHub` — the pub/sub hub for `IMessage` events.
- `IDispatcher` — exposes `Foreground` and `Background` Rx schedulers.

These are injected via constructor (and via the builder's `Services(hub, dispatcher)`
call for fluent users). VMx does NOT register a global locator. See ADR-0001 and
ADR-0003 for the rationale.

The `IMessageHub` MAY be shared across many VMs or scoped to a sub-tree; that is
the host application's choice. The conformance tests verify that VMs publish to the
hub they were given (`HUB-001`).

## 3. Concurrency philosophy

VMx is **thread-aware but not thread-bound**:

- It does not own a UI thread.
- It uses Rx schedulers (`IDispatcher.Foreground`, `IDispatcher.Background`) to
  dispatch work.
- Subscribers that need to observe events on a specific thread (e.g., a UI thread)
  MUST inject an `IDispatcher` whose `Foreground` scheduler dispatches there.

The default `IDispatcher` in each language uses the language's standard "main
loop" scheduler for foreground (`SynchronizationContextScheduler` in .NET,
`AsyncIOScheduler(loop)` in Python) and a thread/task pool scheduler for
background.

See `11-threading.md` for the full contract.

## 4. Disposal invariant

Every public VMx-owned type that exposes `Dispose()` / `dispose()` MUST make
that operation safe and idempotent from every state in which the type permits
disposal. The first call claims terminal teardown; later and re-entrant calls
return normally without repeating stream completion, terminal notification,
cancellation, owned-resource cleanup, or other observable side effects.

For types documented as thread-safe, racing dispose callers MUST atomically
claim teardown so terminal work still occurs at most once. This does not make
otherwise single-threaded types thread-safe.

Parent disposal retains each family's specified ordering. A child reachable
through more than one cascade or host teardown path has one observable terminal
transition because its own disposal is idempotent.

The invariant applies only to disposal itself. Each type keeps its documented
post-dispose behavior: calls may be inert, last values may remain readable,
in-flight waiters may resolve with a safe result, or explicitly documented
operations may raise. Disposal also does not change ownership; non-owning
wrappers and serviced collections remain non-owning. The complete public
inventory and per-type behaviors are published in the
[Disposal Contract](../docs/content/primitives/disposal-contract.md). See
ADR-0084 and `DISP-001..006`.

## 5. Conformance

`DISP-001` through `DISP-006` in `12-conformance.md` top up the existing
type-specific coverage for VM cascades, commands, hubs, interaction owners,
reactive helpers, and collection/projection helpers.

## 6. What this spec is not

This spec does not specify:

- The wire format of messages (no serialization).
- The lifetime of `IMessageHub` (the host decides).
- Whether multiple `IMessageHub` instances coexist. Multiple instances MAY be created.
- UI-framework specifics like XAML binding behaviors, accessibility, or rendering.
- The exact Rx version each flavor uses (each flavor's `README.md` documents that).
