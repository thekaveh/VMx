# ADR 0202 — Rust hierarchy node data and lock-free token reads

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 18 §2, §10 and `HIER-001`; chapter 21 §6.1)

## 1. Context

Two Rust public types differed from the other four flavors. Each difference
needed a decision before a fix. Rust is not on crates.io, and the Rust 0.36.0
source version is unreleased, so a public-API change is a pre-publication
change.

### 1.1. The hierarchy node type (#1263)

Chapter 18 §2 defines `HierarchicalVM<TModel, TVM>`. `TVM` is the concrete
node type, and `Parent`, `Children` and `Path` return it. C# and TypeScript
bind `TVM` recursively. Python uses a weaker bound (ADR-0009 §2.5), and Swift
binds only `TVM: AnyObject`. In each of the four flavors a consumer subclass
adds fields and methods to every node.

Rust `HierarchicalVm<M>` has one type parameter. Its children factory takes
and returns `HierarchicalVm<M>`, and `parent()`, `children()` and `path()`
return the same type. Rust has no subclassing. Per-node state therefore had to
live in the model `M` or in a table outside the node. The model is a value
that `model()` clones and compares, so it cannot hold state with identity.
Chapter 18 §2 recorded the gap as open. ADR-0149 listed it as an open Rust
follow-up, and ADR-0164 named it as a constraint on `TreeSelection`.

### 1.2. The token clone lock (#1278)

Rust `TokenPagedComposition` stored the cursor as
`Mutex<Option<Arc<Mutex<Token>>>>` (#1162). A reader copied the `Arc` under
the slot lock, then ran `Token::clone` under the token's own lock. That lock
had two effects:

- Clones of one stored token took turns. A `Token::clone` that waited for
  another thread's `current_token()` waited for its own lock.
- A `Token::clone` that read the cursor again on its own thread blocked
  forever, because the lock is not re-entrant.

The `current_token()` rustdoc stated both limits. C#, Python, TypeScript and
Swift run no user code when they read the token. They copy or return the
stored value. The public Rust bound was `Token: Clone + Send + 'static`, so
two threads could not share a `&Token` without a lock.

## 2. Decision

### 2.1. Owner decision

Decided under the owner's 2026-11-07 delegation: in both cases Rust takes the
option that gives the behavior of the other four flavors. Neither difference
becomes a recorded Rust divergence.

### 2.2. A node-data type in place of `TVM`

Rust `HierarchicalVm<M>` becomes `HierarchicalVm<M, N = ()>`. `N` is the
consumer's node data, the Rust form of the fields that a `TVM` subclass adds.

- The concrete node type is `HierarchicalVm<M, N>`. `parent()`, `children()`,
  `try_children()`, `path()`, the children factory, `attach_many` and
  `BatchAttachResult` use it.
- `node_data(&self) -> &N` returns the node's own `N`. Clones of a node share
  it, as they share the model and the children.
- `N` is `Send + Sync + 'static`. It needs no `Clone` or `PartialEq`, because
  the node owns it and never copies or compares it. State that changes uses
  interior mutability, as other shared Rust VMx state does.
- `N` must not hold a strong handle to its own node or an ancestor. Such a
  handle forms a reference cycle, and the tree is never freed.
- Node methods come from an extension trait that the consumer implements for
  `HierarchicalVm<M, N>`.
- `N` defaults to `()`. `HierarchicalVm::new`, `with_children_factory`,
  `builder` and `HierarchicalVmBuilder::new` create `()` nodes, so code that
  names `HierarchicalVm<M>` keeps its meaning.
- Decided under the owner's 2026-11-07 delegation:
  `HierarchicalVm::with_node_data(name, model, node_data, children_factory, eager_children, hub)`
  creates a node with data. `HierarchicalVmBuilder::with_node_data(node_data)`
  starts a builder for such a root. The builder needs no new required field,
  so `HIER-015` to `HIER-017` keep their meaning.
- `TreeSelection<M>` becomes `TreeSelection<M, N = ()>`. Its `current()` and
  `current_changed()` return `HierarchicalVm<M, N>`.

### 2.3. Token reads hold no token lock

- The Rust bound becomes `Token: Clone + Send + Sync + 'static`.
- The cursor stores `Mutex<Option<Arc<Token>>>`. A reader copies the `Arc`
  under the slot lock, releases the lock, then runs `Token::clone` on the
  shared token with no pager lock held.
- Clones of one stored token can run at once on several threads. A
  `Token::clone` can call `current_token()`, `load_more(loader)` or
  `load_next()` on its own thread. `load_next()` from a clone keeps the
  existing command re-entry rules.
- A commit still swaps only the `Arc` under the slot lock, and no user code
  runs under any pager lock. A reader that holds the last `Arc` runs
  `Token::drop` after it releases every lock.
- The `current_token()` rustdoc states no clone limit.

## 3. Flavor impact

- **Rust.** `hierarchical.rs` adds the `N` parameter, `with_node_data`,
  `node_data` and the builder start. `tree_selection.rs` adds `N`.
  `token_paging.rs` changes the bound and the cursor type.
- **C#, Python, TypeScript and Swift.** No change. Their subclasses already
  carry per-node state, and their token reads run no user code.

## 4. Conformance

No conformance ID is added. `HIER-001` now states the Rust form: a three-level
tree of a consumer node-data type returns that type from `children()`,
`parent()` and `path()`, and each node exposes its data with no downcast and
no side table. The other flavors already meet `HIER-001` through their
subclasses.

The token change is Rust-only, because no other flavor runs user code when it
reads the token. Rust regression tests cover both former limits:

- A clone that waits for another thread's `current_token()` sees that call
  return.
- A clone that calls `current_token()` on its own thread returns the token.

## 5. Consequences

- Rust code that names `HierarchicalVm<M>` or `TreeSelection<M>` still
  compiles and means the `()` node type.
- A consumer can now give tree nodes their own state and methods. Chapter 18
  §2 no longer lists a Rust gap. ADR-0009 §2.5 records the Rust form, and the
  Rust parity ledger records it as an accepted idiom.
- A token type that is `Send` but not `Sync`, for example one that holds a
  `Cell`, no longer compiles as a `TokenPagedComposition` token. Such a token
  can wrap its state in a `Mutex` or an atomic. Every other token type in the
  repository is already `Sync`.
- `TokenPagedComposition` no longer allocates a second lock for each stored
  token.

## 6. Rejected alternatives

- **Record the node type as a Rust divergence.** Rust consumers would keep
  per-node state in side tables keyed by node identity. The tables must be
  cleaned up by hand, and every tree feature would differ from the spec shape.
- **A `TVM` trait that the consumer's wrapper struct implements.** A child
  must return its parent as the wrapper type. The node would have to store a
  strong wrapper handle, which forms a cycle, or rebuild the wrapper, which
  loses the consumer's fields. The node-data parameter keeps the state inside
  the shared node.
- **Keep the `Send` bound and record both token limits.** Rust would stay the
  only flavor whose token read can block on user code.
- **Make the token lock re-entrant.** That removes only the same-thread
  deadlock. Clones of one token would still take turns.
