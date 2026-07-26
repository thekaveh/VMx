# Task 3 report — VMx-owned reactive and async parity

Status: complete

Implementation commit: `5fbe1a959ec7da3c77eda57b4eba23d0f16b854a`

## Implemented

- Added `ValueStream<T>`, a VMx-owned typed stream with replaying and hot
  construction, completion-aware subscriptions, retained current values,
  idempotent disposal, and subscriber-panic isolation.
- Added completion-aware `MessageHub::subscribe_with_completion`, including
  immediate completion for disposed and null hubs.
- Added `NotificationHub::pending_stream` with initial/late replay, committed
  snapshot updates, terminal empty publication, and completion. Added the null
  pending stream's empty-then-complete behavior.
- Reworked `DerivedProperty` source factories around owned `ValueStream`
  subscriptions, automatic distinct recomputation, typed value changes,
  one-through-five typed factories, arbitrary same-typed sources, source-based
  write-back, and disposal of source subscriptions and change streams. The
  existing manual constructors, recompute method, and message hub remain for
  source compatibility.
- Added executor-neutral `AsyncValue::map` and `AsyncValue::and_then`
  continuations with first-wins completion, continuation-panic isolation, and a
  deterministic retained-continuation count.
- Removed native worker threads from `make_confirm` and both confirmation
  decorator paths. `ConfirmationExecution` remains awaitable and keeps the
  existing `.join()` call shape without retaining a worker thread.
- Preserved notification publish-before-waiter-completion order, command panic
  routing by execution mode, post-dispose no-op behavior, and the existing
  dependency set.

## TDD evidence

Focused RED commands and expected failures:

- `cargo test --locked --all-features --test conformance value_stream_replays_current_value_and_completes_late_subscribers`
  failed to compile with missing `ValueStream`, source factories,
  `subscribe_with_completion`, and notification pending-stream APIs.
- `cargo test --locked --all-features --test conformance async_value_maps_and_composes_without_an_executor`
  failed to compile with missing `AsyncValue::map`, `and_then`, and
  `pending_continuation_count`.
- `cargo test --locked --all-features --test conformance validator_and_write_back_enable_set_value`
  failed to compile with missing `from_sources_with_write_back`.
- `cargo test --locked --all-features --test conformance hot_value_stream_skips_replay_but_still_completes`
  failed to compile with missing `ValueStream::hot` and typed
  `DerivedProperty::value_changes`.

Focused GREEN commands:

- `cargo test --locked --all-features --test conformance conformance::async_value::`
  — 2 passed.
- `cargo test --locked --all-features --test conformance conformance::value_stream::`
  — 3 passed.
- `cargo test --locked --all-features --test conformance conformance::derived_properties::`
  — 13 passed.
- `cargo test --locked --all-features --test conformance conformance::message_hub::`
  — 20 passed.
- `cargo test --locked --all-features --test conformance conformance::notifications::`
  — 21 passed.
- `cargo test --locked --all-features --test conformance conformance::command_decorators::`
  — 21 passed.

The resource-bound confirmation tests create 128 unresolved decisions and assert
one retained continuation per operation. Resolver-thread identity assertions
prove that notification and command continuations run on the resolving thread.
No timing sleeps were added.

## Full verification

- `cargo fmt --check` — passed.
- `cargo clippy --locked --all-targets --all-features -- -D warnings` — passed.
- `cargo test --locked --all-features` — 6 unit, 540 conformance, and 6 doc
  tests passed.
- `RUSTDOCFLAGS="-D warnings" cargo doc --locked --all-features --no-deps` —
  passed.
- `cargo package --locked` — packaged and verified 77 files after the
  implementation commit.
- `git diff --check` — passed.
- Commit-time pre-commit hooks — passed.

## Risks and follow-up

- `ConfirmationDecoratorCommand::execute_async` now returns
  `ConfirmationExecution` rather than `std::thread::JoinHandle<()>`. Existing
  inferred `.join()` callers retain their call shape, and async callers gain a
  real `Future`; callers that explicitly name the old concrete return type must
  adapt. This concrete-type change is required to remove per-pending native
  threads.
- The available compiler was Rust 1.94.1, not a locally installed 1.88
  toolchain. `Cargo.toml` remains at `rust-version = "1.88"`, no dependency was
  added or changed, and the implementation avoids APIs newer than 1.88, but the
  exact MSRV toolchain was not executable in this worktree.
- Ledger disposition and changelog closure remain Task 4 work by plan.
