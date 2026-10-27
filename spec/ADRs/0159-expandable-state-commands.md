# ADR 0159 — `ExpandableState` owns expand, collapse and toggle commands

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0

## 1. Context

`ExpandableState` (ADR-0015, chapter 05 §8) exposes `Expand()`, `Collapse()`,
`ToggleExpansion()`, their `can*` checks and `IsExpandedChanged`. It exposes no
commands. So every tree node, menu and popover that binds expansion builds the
same three relay commands by hand. Each copy sets the matching `can*` check as
the predicate, the verb as the task, and the change stream as the trigger.
Each copy must also dispose the commands with the helper (#660).

Expansion stays an opt-in capability (ADR-0015, ADR-0028 §3 item 6, chapter 14
rule 2). The owning VM publishes `IsExpanded` changes (chapter 14 rule 6). Rust
reports expansion changes through a `MessageHub`, and its
`RelayCommandBuilder::trigger` takes a `MessageHub`.

## 2. Decision

1. `ExpandableState` exposes `ExpandCommand`, `CollapseCommand` and
   `ToggleExpansionCommand` in every flavor. The names follow ADR-0006: C#
   `ExpandCommand`, Python `expand_command`, TypeScript and Swift
   `expandCommand`, and Rust `expand_command()`.
1. Each command is a relay command built with the flavor's relay command
   builder. Its predicate is the matching `can*` check, and its task calls the
   matching verb.
1. The trigger of each command is the helper's change stream:
   `IsExpandedChanged`, or `expanded_changed()` in Rust. So `CanExecuteChanged`
   fires once for every effective expansion change.
1. Each command is built on its first read and cached. Later reads return the
   same command. A Rust read returns a clone of it, and clones of the helper
   share it. A helper whose commands are never read holds no trigger
   subscriptions, which matters for large trees of nodes.
1. The helper owns the commands. `dispose()` disposes each command that was
   read, then completes the change stream. It runs every step and rethrows the
   first failure (#768). Rust resumes the first panic. Swift steps cannot
   throw. After that, each command is inert (ADR-0068). A command first read
   after disposal is built without the trigger and disposed at once, so it is
   inert too. Disposal never builds an unread command.
1. Rust guards the cache with a mutex, because its helper is shared across
   threads. The command closures capture only the shared expansion state, not
   the cache, so the helper and its commands form no reference cycle. The other
   flavors' helpers are not thread-safe, and their caches are plain fields.
   Swift closures hold the helper weakly.
1. The commands publish nothing to a hub. The owning VM forwards
   `IsExpandedChanged` to its own property-change notification. The state and
   reactive helpers guide shows that forwarder as a checked snippet.

## 3. Consequences

- Owners re-export a helper command instead of building one. The command
  predicate, trigger and disposal are the same in every owner.
- `EXP-006`, `EXP-007` and `EXP-008` cover the predicates and
  `CanExecuteChanged`, command execution, and inertness after helper disposal
  in all five flavors.
- The disposal inventory lists the commands under the `ExpandableState` row.
- The change is additive. Existing helper members and IDs are unchanged.

## 4. Rejected alternatives

- **Eager commands.** Every helper would hold three commands and three trigger
  subscriptions, even when no view binds them. Tree nodes are the main
  consumer, so the cost grows with the tree.
- **Commands on `HierarchicalVM`.** Expansion is opt-in, and `HierarchicalVM`
  does not implement it (ADR-0028 §3 item 6).
- **Hub publication from the helper.** The helper has no identity or hub of its
  own, and chapter 14 rule 6 gives publication to the owning VM.
