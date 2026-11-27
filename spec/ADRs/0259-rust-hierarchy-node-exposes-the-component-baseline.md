# ADR 0259 — Rust hierarchy node exposes the component baseline

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 05 §5 and chapter 18 §3; no spec text change, no conformance ID)
- **Related:** [ADR-0203](0203-rust-lifecycle-errors-hook-methods-and-stored-walks.md) (Rust lifecycle errors and hook methods), [ADR-0206](0206-rust-public-surface-parity.md) (Rust public-surface parity, a precedent only), [ADR-0258](0258-eager-hierarchy-construction-uses-the-child-walk.md) (eager construction uses the child walk), #1853.

## 1. Context

Every VM is also a `ComponentVM` (chapter 01), and chapter 05 §5 puts the five built-in commands on that baseline. A `HierarchicalVM` is a component node (chapter 18), so the C#, Python, TypeScript and Swift nodes inherit the baseline from the component base class.

The Rust `HierarchicalVm` wraps a `ComponentVm` in its `component` field (`langs/rust/src/hierarchical.rs`, `origin/develop` L133) and exposed only part of that baseline:

1. The node had no inherent `is_constructed`, selection member (`select`, `can_select`, `deselect`, `can_deselect`, `is_current`), built-in command, `background_errors`, `destruct` or `reconstruct`. `destruct` and `reconstruct` were reachable only through the `Destructable` and `Reconstructable` capability traits. The blanket `Reconstructable` implementation discards the result of the reconstruct.
1. The `VmNode` implementation (`origin/develop` L1335 to L1383) forwarded `destruct` but not the current flag. `VmNode::is_current` returned the trait default `false`, so a `CompositeVm` selection set the node's current flag but never reported it through `VmNode`.

## 2. Decision

1. **The node has the baseline as inherent members.** `HierarchicalVm` gains `is_constructed`, `can_select`, `select`, `can_deselect`, `deselect`, `is_current`, `background_errors`, `destruct` and `reconstruct`, and the five built-in commands (`select_command`, `deselect_command`, `select_next_command`, `select_previous_command` and `reconstruct_command`). The members forward to the inner component. The sibling commands are inert, and the select pair follows `can_select` and `can_deselect` (chapter 05 §5).
1. **Reconstruct keeps the eager cascade.** The inherent `reconstruct`, and the command that runs it, admit the reconstruct, run the inherent `destruct`, and then construct the node through the core's construct transition. In an eager node that transition constructs each direct child through the child-transition walk, as `construct` does (chapter 18 §3, ADR-0258). The construct phase is stored on the core, so it holds the node weakly (#750). A node that is gone skips it.
1. **Destruct does not cascade.** The inherent `destruct` destructs only the node, as chapter 18 §3 states. A node's `destruct` does not destruct its children.
1. **The node has its own command set.** The node builds a `ComponentCommands` set over its component core when it builds its inner state. Its reconstruct action runs the node's `reconstruct` and holds the node weakly. Its predicate is false once the node is gone (#1483). `dispose` disposes that set after the component is disposed.
1. **The `VmNode` implementation forwards the current flag.** It forwards `set_current_flag`, `commit_current_flag` and `publish_current_flag` to the component core, and `is_current` to the inherent method, as `AsyncResourceVm` does. A composite selection therefore sets the flag and publishes `is_current` from the node.
1. **Trait signatures do not change.** `Destructable::destruct` and `Reconstructable::reconstruct` keep their signatures, which #1840 covers. `VmNode::destruct` calls the inherent `destruct`.
1. **Names and records.** The names are snake_case, as ADR-0006 requires. The change adds no conformance ID, because chapter 05 §5 and chapter 18 §3 already state the behavior, so no other flavor needs a stub. `spec/VERSION` stays 3.30.0. `langs/rust` stays at 0.37.0, which is unreleased, and its CHANGELOG records the members under `Added`.

## 3. Consequences

- The change is a source break for existing call forms. The inherent `destruct` and `reconstruct` shadow the trait methods, so `node.destruct();` and `node.reconstruct();` with a unit result now carry a `must_use` warning, and some unit-valued uses no longer compile (§2 and the CHANGELOG `Changed` entry). The owner accepted the break on 2026-11-27. 0.37.0 absorbs it, since it is the first crates.io release. `cargo semver-checks` and the API baseline check do not model method-call resolution, so they report no break here.
- A caller that has `Destructable` or `Reconstructable` in scope and calls `node.destruct()` or `node.reconstruct()` as a method now calls the inherent method. It returns `VmxResult<()>`, which is `#[must_use]`, where the trait method returned `()`. The fully qualified trait calls, such as `Reconstructable::reconstruct(&node)`, are unchanged.
- A Rust tree row can bind the five commands, read `is_constructed`, and see that it is the current child.
- The node keeps two command sets on one core: the component's own set, which the node does not expose, and the node's set. Both subscribe to the same hub. The node disposes its own set when it is disposed.
- Expansion members stay out of scope (#1852). The other four flavors do not change.

## 4. Rejected alternatives

- **Replace the component's reconstruct action.** That needs a `ComponentVm` constructor that takes a reconstruct action, and the action needs the node's weak handle, which exists only inside `Arc::new_cyclic`. It touches every `ComponentVm`, for one node type.
- **Keep the trait-only reconstruct.** The trait discards the error of a failing destruct hook, and the trait's own documentation sends callers to an inherent method that the node did not have.
- **Add `is_selected` as an alias of `is_current`.** `AsyncResourceVm` has that alias, but the issue does not list it, and it adds surface without a parity requirement.
