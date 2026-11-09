# ADR 0198 — `SearchableState` construction starts no term debounce

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 06 §8 and §10; `SRCH-008`)
- **Amends:** [ADR-0014](0014-search-and-filter.md)

## 1. Context

Chapter 06 §8 says that setting `SearchTerm` to a new value starts the term
debounce. It does not mention construction (#1307).

C#, Python, TypeScript and Swift seed the term subject with `""` and send that
seed through the debounce. When the first window ends, the helper re-reads
`Items` and emits one filtered snapshot that nobody requested. A supplier
change in that window therefore reaches subscribers with no source signal, no
term change and no `search()` call. `SRCH-007` forbids that result.

- With a zero debounce, C#, Python and TypeScript pass the seed through inside
  the constructor. No subscriber can exist yet, so nobody sees it.
- Swift schedules even a zero debounce on its `DispatchQueue`, so its snapshot
  arrives after construction. #550 traced a notes-showcase test race to this
  late snapshot.
- Rust has no debounce. It notifies only on a changed term, a `search()` call
  or a source signal.

Every `SRCH-007` test uses a zero debounce and checks at once, so no test saw
the extra snapshot. Ledger item §2.2 of
`docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` recorded the gap.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the rule that matches
Rust and the chapter 06 wording.

- Construction starts no term debounce. The initial empty term is not a new
  value.
- After construction, the helper emits a filtered snapshot only for a term
  change after its debounce window, a `search()` call, or a source signal.
- A replaying filtered output still gives a new subscriber its current value.
  That replay is not a new notification.
- The rule holds for every debounce, zero included. With a zero debounce in C#,
  Python and TypeScript, the constructor no longer re-reads `Items` for the
  seed.
- The source-signal rules of §8.1 and §8.2 do not change. With a source
  signal, construction still reconciles from `Items` once before it returns.
- Decided under the owner's 2026-11-07 delegation: the new conformance ID is
  `SRCH-008`. It uses a non-zero debounce and waits, or advances virtual time,
  past the first window.

## 3. Flavor impact

- **C#.** The debounced term stream skips the seed value of `_termSubject`
  before `Throttle`, and also on the zero-debounce path.
- **Python.** The debounced term stream skips the seed value of
  `_term_subject` before `debounce`, and also on the zero-debounce path.
- **TypeScript.** The debounced term stream skips the seed value of
  `#termSubject` before `debounceTime`, and also on the zero-debounce path.
- **Swift.** The debounced term publisher drops the first value of
  `termSubject` before `debounce`.
- **Rust.** No change. The suite gains a `SRCH-008` test.

No flavor differs, so ADR-0009 gains no entry.

## 4. Conformance

`SRCH-008` covers a helper with a non-zero debounce and no source signal. A
supplier change after construction produces no filtered notification until
`search()` or a term change. A term set after construction still produces one
notification after its window.

## 5. Consequences

- A consumer that relied on the first-window snapshot to pick up items loaded
  after construction now calls `search()` or wires a source signal.
- The notes-showcase example test jobs in C#, Python, TypeScript and Swift
  must stay green. A showcase view model that needs a refresh in the first
  window calls `search()`.
- Ledger item §2.2 of the open cross-flavor decisions is removed.

## 6. Rejected alternatives

- **Specify the seed snapshot for every flavor.** Rust would need a timer, and
  the snapshot would still break `SRCH-007` for a supplier change in the first
  window.
- **Leave the timing flavor-defined.** Swift would keep a late snapshot that can
  overwrite a forced search, as in #550.
