# ADR 0169 — A token-paged load that finds a terminal token at its start fetches nothing

- **Status:** Accepted
- **Date:** 2026-11-07
- **Spec version:** 3.30.0 (clarification of chapter 21 §6.2)

## 1. Context

Chapter 21 §6.2 requires that `Items` and `CurrentToken` describe one
contiguous prefix loaded from the initial token. It also requires that a
terminal token sets `HasMore` to false and disables `LoadMoreCommand`.

`TokenPagedComposition` checked `HasMore` only in the `LoadMoreCommand`
predicate, at admission. In C#, Python, Swift and Rust the load body starts
later than admission. A refresh or another load can commit a terminal token in
that window. The body then read the terminal token, which is `null` like the
initial token, and fetched page 1 again. It appended page 1 to the accumulator
and left `HasMore` true. A probe loaded pages `[1]` and `[101]`, then committed
the terminal page `[1, 101, 555]` in the window. All four flavors ended with
`Items == [1, 101, 555, 1]` (#1161).

TypeScript is not affected. Its `executeAsync` runs the predicate, the start
notification and the load body up to its first `await` in one turn, and every
commit follows an `await`.

§6.2 also said that each load or refresh supersedes every operation started
before it. It did not say whether a run that fetches nothing counts as an
operation start.

## 2. Decision

- A `LoadMoreCommand` run checks `HasMore` again when its load starts. The
  check and the operation start are atomic with respect to commits.
- When `HasMore` is false at that point, the run is not an operation start. It
  does not call `fetch_next`, mutate state, publish notifications or supersede
  any operation. An in-flight refresh that started after the terminal commit
  still commits.
- §6.2 states this rule in one sentence after the supersession paragraph.
- Every flavor implements the check:
  - C# re-checks under its state gate.
  - Python re-checks before its first `await`.
  - Swift re-checks in the state queue.
  - Rust re-checks in the command load tasks under the operation gate, then
    reads `has_more`. This is the same order that a commit uses. The ad hoc
    `load_more(loader)` call keeps its unconditional start, because the caller
    supplies the loader and asks for the page explicitly.
  - TypeScript adds the same check for symmetry. Its behavior does not change.

Decided under the owner's 2026-11-07 delegation: a gated-out load supersedes
nothing. This is the simplest reading, because a run that fetches nothing
changes nothing, and it keeps the in-flight refresh that a user started.

No conformance ID is added. The regression cases run under `COL-026`.

## 3. Consequences

- `Items` and `CurrentToken` keep describing one prefix when a terminal token
  lands between admission and the load body.
- A load that loses this race completes without a fetch and without
  notifications.
- No public API changes.
