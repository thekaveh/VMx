# ADR 0185 — Rust resumes a command-path replay panic from `execute()`

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (amends the Rust note in chapter 20 §5.3;
  `FORM-040`)

## 1. Context

Chapter 20 §5.3 rule 6 routes the first replay failure of a queued update
through the approval's own failure route. That route is the awaiter of
`ApproveAsync`, or, on the command path, one emission on `ApproveErrors`.
`FORM-040` tests both paths.

C#, Python and TypeScript follow the rule. On the command path, each emits the
first replay failure once on `ApproveErrors`.

A Rust replay failure is a panic, not an `Err`. The Rust approve command's
action calls `approve()` and sends only a returned `Err` to `approve_errors`.
It does not catch a panic. After the last replay, the first replay panic
therefore resumes out of `approve_command().execute()`, and `approve_errors`
receives nothing. The Rust `FORM-040` test asserts this behavior on both
paths.

The chapter 20 Rust flavor note said only that "the first replay panic
resumes". It did not name the command path or `approve_errors`. The
`FORM-040` catalog entry listed a Swift exception and no Rust exception, so it
required a Rust `approve_errors` emission that the Rust test asserts never
occurs (#1291).

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the Rust behavior stays, and
the spec records it.

- In Rust, the first replay panic resumes from the call that ran the approval:
  `approve()`, or `approve_command().execute()` on the command path.
- `approve_errors` receives no replay panic. It carries only the `Err` that
  `approve()` returns, such as a persister `Err`.
- The chapter 20 §5.3 Rust flavor note and the `FORM-040` catalog entry state
  this.

Rust treats a panic as a failure that unwinds to the caller. The command
action does not catch a persister or settlement observer panic either, so a
replay panic follows the same route. Catching it in the command action would
turn one panic kind into a message and leave the others as panics. The
`execute()` caller still sees the failure, and it sees it once.

## 3. Consequences

- Chapter 20 §5.3 and the `FORM-040` entry gain a Rust sentence. No
  conformance ID changes.
- The Rust code and the Rust `FORM-040` test do not change.
- C#, Python, TypeScript and Swift do not change.
- A Rust host that runs `approve_command().execute()` must catch an unwind to
  observe a replay panic. Subscribing to `approve_errors` is not enough.

## 4. Rejected alternatives

- **Catch the replay panic in the Rust command action and send it to
  `approve_errors`.** This would match the other flavors for replay panics
  only. A persister or observer panic would still resume, so the command path
  would route panics two ways. It would also change Rust behavior that the
  Rust `FORM-040` test asserts.
