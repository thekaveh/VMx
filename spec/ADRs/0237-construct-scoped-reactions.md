# ADR 0237 — Construct-scoped reactions: `effect`, `reaction` and `whileConstructed`

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (decision record; chapter 24 and the chapter edits
  land with the implementations)
- **Amends:** [ADR-0041](0041-single-disposable-lifecycle.md) §4;
  [ADR-0090](0090-owned-resource-registration-and-public-hub.md) §2 item 4
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md),
  [ADR-0162](0162-supported-child-transition-helper.md),
  [ADR-0234](0234-registered-reactive-state-with-tracked-dependencies.md),
  [ADR-0236](0236-members-registered-with-an-owner-and-owner-scoped-injection.md),
  [ADR-0238](0238-owner-declared-keyed-resource-driver.md), row D14 and §1.8.3
  of the
  [upstream-candidates plan](../proposals/2026-10-20-upstream-candidates-plan.md),
  the design proposal
  [`2026-11-15-registered-reactive-state.md`](../proposals/2026-11-15-registered-reactive-state.md),
  #668, #1996, #1582.

## 1. Context

### 1.1 Construct-scoped resources today

Chapter 02 §2.2 tells authors to register per-construct subscriptions in
`OnConstruct` and to release them in `OnDestruct`. Chapter 02 §2.3 keeps the
owned-resource helper for the disposal lifetime: "Per-construct resources still
belong in `OnConstruct` / `OnDestruct`." Chapter 05 §2.2 says of that helper:
"The helper is not a mutable public bag and does not replace the `OnConstruct`
/ `OnDestruct` pair for per-construct resources." A `dispose()` from
`Constructed` runs no `OnDestruct`, so a resource that only `OnDestruct`
releases outlives its view-model.

ADR-0041 §4: "Subclasses with per-construct subscriptions register them in
`OnConstruct`, store the `IDisposable` (or equivalent) in a local field, and
dispose it in `OnDestruct`." The same section names the way to revisit: "If a
future consumer pattern repeatedly forgets `OnDestruct` cleanup, revisit as a
`RegisterPerConstruct(IDisposable)` ergonomic helper rather than reintroducing
a second bag."

ADR-0090 §2 item 4: "Keep per-construct resources explicit in
`OnConstruct`/`OnDestruct`. Reconstruct and destruct never drain
disposal-lifetime resources. Do not add two mutable bags."

Plan D14 (construct-scope ownership), disposition "**Adopt in principle** as
`whileConstructed`, after a pilot": "ADR-0041 §4 named this exact helper as the
way to revisit. The catalogue's semantics have gaps." Plan §1.8.3 adds: "The Vue
consumer's 26 fields and 28 `unsubscribe()` calls show repeated code, not
forgotten cleanup. ADR-0090's own bar was a measured pilot diff with green
tests." Its rule 3 reads: "Destruct runs `_onDestruct`, then the teardowns in
LIFO order, then publishes `Destructed`. Hooks therefore always see the
resources of their own scope." Its rule 4 reads: "Dispose from `Constructed`
runs `_onDispose`, then the effect teardowns, then the `own()` registrations,
all LIFO. The inner scope closes before the outer one."

### 1.2 Evidence

The production Vue client of ADR-0234 §1.2 is the Vue consumer of the October
plan. The owner accepts the tier B rewrite, together with two subscription
leaks that the study found in the client's current code, as the pilot that
plan D14 asked for. The rewrite type-checks and passed a smoke test of 105
expectations; the client's own tests did not run against it (the design
proposal §8.4). Two of the client's pages released their per-visit hub
subscriptions only in `_onDestruct`. The client disposes those pages from
`Constructed`, so
`_onDestruct` never ran, and each visit leaked 5 and 10 hub subscriptions. That
is the "silent leak class" of ADR-0090 §1, in the mirror form of the trigger of
ADR-0041 §4: the cleanup exists, but in a hook that the dispose path skips.
Elsewhere, the client keeps 15 construct-scope fields, and some of its pages
stop them a second time at dispose to work around the same gap. In the tier B
rewrite, 57 reactions replace these fields and their hooks. With the members of
ADR-0236, the overrides of lifecycle hooks fall from 83 to 5, and `.subscribe(`
calls fall from 74 to 16. The prototype's tests pin the rules of plan §1.8.3 and
the order of §2.3 below (ADR-0234 §1.2).

## 2. Decision

### 2.1 The reactions

1. `effect(fn)` runs `fn` in a tracking frame. `fn` may return a cleanup. When
   a value that it read changes, the effect runs the cleanup and then `fn`
   again, and its stop runs the cleanup. `fn` may write, and its writes settle
   at once (ADR-0234 §2.3). `fn` runs synchronously. In TypeScript, a function
   that returns a promise is tracked only up to its first `await`, its promise
   is no cleanup, a rejection goes to the stream-fed route, and development
   builds report the effect. Python raises the usage error when an effect
   function or a reaction handler returns an awaitable, and closes the
   coroutine without running it. C# `Effect` and `Reaction` throw
   `ArgumentException` at registration for an async lambda. The Swift and
   Rust types accept only synchronous functions (the proposal R12.3).
   `asyncRelayCommand` and the keyed driver of ADR-0238 are the tools for
   asynchronous work.
1. `reaction(select, handler, options)` evaluates `select` in a tracking frame.
   It calls `handler(value, previous)` when the selected value changes by
   `options.equals`, which defaults to the flavor's default equality. With
   `immediate`, it also calls the handler at each start. The handler may write.
1. `whileConstructed(setup)` runs `setup` untracked at each start and keeps the
   resource that `setup` returns: a disposable, a cancellable or a cleanup
   function, as the proposal §4 types it per flavor. Its stop releases the
   resource. It is the `RegisterPerConstruct` helper that ADR-0041 §4 named,
   in a declarative form: one registration per resource, not a bag.
1. Every registration returns a handle that removes the reaction. Removal runs
   the cleanup or the teardown once and takes the reaction off its view-model.
   The handle is the flavor's disposal idiom: a function in TypeScript, an
   `IDisposable` in C#, a callable in Python, a cancellable in Swift, and a
   guard in Rust. In C#, Python, TypeScript and Swift, a handle that is
   ignored keeps the reaction for its registration scope (§2.2 rule 4). In
   Rust, as for VMx Rust subscriptions, dropping the guard removes the
   reaction, and a new `detach()` keeps the reaction for its registration
   scope. The Rust implementation records this difference in ADR-0009.
1. Reactions are level-triggered. A run reads the state that is current when it
   runs, so several changes queued before one run produce that one run. Code
   that needs one call per announcement subscribes to the announcements
   (`propertyChanged`, `whenPropertyChanged`), which stay lossless.

### 2.2 The reaction window and registration scopes

1. `effect`, `reaction`, `whileConstructed` and the keyed driver of ADR-0238
   are construct-scoped; the proposal calls them constructed-kind (R12.1).
   They are active while their view-model is constructed: they start in the
   construct sequence, after `_onConstruct` and the member walk and before
   `Constructed` is published, and they stop at the start of the destruct
   sequence.
1. A reaction registered while the window is open starts at once. When its
   first run throws, the error reaches the registration call, and the reaction
   stays registered and active. A reaction registered while the window is
   closed starts at the next construct. A registration after the disposal of
   the view-model has started is ignored and returns a handle that does
   nothing.
1. `reaction(..., { alive: true })` is active from the activation of its
   view-model (ADR-0234 §2.5) until its disposal starts, in every status. It
   has no immediate run, and a destruct neither pauses nor stops it.
1. Every reaction has a registration scope. A reaction registered during a run
   of another reaction of the same view-model belongs to that run: it is
   removed when that reaction runs again, stops or is removed. A reaction
   registered in `_onConstruct`, outside a run, belongs to that construct: it
   is removed when the view-model next publishes `Destructed`. Every other
   reaction lives until the disposal of its view-model or until its handle
   removes it (§2.1 rule 4). The constructor and the field initializers are
   the place to register reactions. A registration scope is not the same as
   being construct-scoped (rule 1): only a reaction registered in
   `_onConstruct`, outside a run, is removed at `Destructed`.
1. A re-run, a select or a handler that throws is reported on the stream-fed
   route (chapter 03 §3.6), and the reaction stays active with the reads that
   it made. A failing teardown or cleanup is isolated and swallowed, as for
   `own()` (`DISP-009`).

### 2.3 The lifecycle sequences

1. Construct: admission, and `Constructing` is published; the view-model
   activates if it has not (ADR-0234 §2.5); `_onConstruct` runs; the members
   construct (ADR-0236); the reactions start in registration order, each as
   one entry of the drain; `Constructed` is published. A setup, a first effect
   run or an immediate handler that throws stops the reactions started so far,
   in reverse order, and fails the construct, which rolls back (`LIFE-014`).
1. Destruct mirrors construct. The reactions pause before `Destructing` is
   published, so that publication runs no effect. Then `Destructing` is
   published; the reactions stop in reverse order, while every member is still
   `Constructed`; the members destruct in reverse registration order;
   `_onDestruct` runs; `Destructed` is published. When a member or
   `_onDestruct` fails, the view-model rolls back to `Constructed`, and the
   stopped reactions start again after the rollback is published.
1. Dispose, from any status, stops the reactions first. From the start of the
   disposal, no reaction runs, starts or registers. The reactions that started,
   construct-scoped and alive, are torn down in reverse order while the
   members and children that they used are still alive. The disposal cascade of
   chapter 02 §7 then continues with the children and members, `Disposed`,
   `_onDispose` and the `own()` resources, in the order that chapter gives. A
   `dispose()` from `Constructed` therefore releases every construct-scoped
   resource, although `_onDestruct` never runs.

### 2.4 Earlier decisions

1. ADR-0041 §4 is amended. A per-construct resource can be declared with
   `whileConstructed`, `effect` or `reaction`, in place of a field that
   `OnConstruct` sets and `OnDestruct` releases. The hooks stay, and no second
   bag is added: each reaction is one declaration next to its own teardown.
1. ADR-0090 §2 item 4 is amended to read: keep per-construct resources
   explicit, in `OnConstruct` and `OnDestruct` or as declared reactions.
   Reconstruct and destruct still never drain disposal-lifetime resources, and
   VMx adds no mutable bag.
1. Plan D14 and #668 are decided: `whileConstructed` is adopted, together with
   `effect` and `reaction`. Rules 1, 2, 5 and 6 of plan §1.8.3 hold. Rules 3
   and 4 are refined by §2.3: the teardowns run before the members destruct and
   before `_onDestruct`, and at disposal before the children, the members,
   `Disposed` and `_onDispose`. The reason that plan rule 3 gives, that hooks
   "always see the resources of their own scope", does not carry over:
   `_onConstruct` runs before the setups and never sees them either, and each
   teardown sits next to its setup. The restart after a rollback answers the
   plan's concern that a failing `_onDestruct` would roll back "with the wiring
   already gone".
1. #1996 asks whether an owned subscription takes the typed message stream of
   #1582. VMx adds no subscription member. A subscription to any stream, typed
   (#1582) or not, is owned with `own()` for the disposal lifetime, or declared
   as `whileConstructed(() => stream.subscribe(...))` for the construct
   lifetime.
1. Chapter 02 (§2.2, §2.3 and the construct, destruct and dispose sequences)
   and chapter 05 §2.2 change when the flavors implement this ADR. The `LIFE`
   and `DISP` IDs keep their meaning, and the new IDs belong to chapter 24.

## 3. Consequences

- The Status of ADR-0041 and its registry cell name this ADR for §4. The
  Status of ADR-0090 and its registry cell name this ADR for §2 item 4.
- A per-construct resource needs no field and no second release at dispose.
  The leak of §1.2 cannot happen to a declared reaction.
- `_onDestruct` runs after the reactions stopped and the members destructed. A
  hook that needs the live state of a member reads it in a teardown instead.
- The lifecycle core changes in every flavor: the reaction start in the
  construct sequence, the pause before `Destructing`, the restart after a
  rollback, and the teardown at the start of a disposal. In every flavor, each
  reaction start is one entry of the drain (ADR-0234 §2.4), so a first run never
  recurses on the call stack.
- Chapter 24 adds the conformance IDs of the reactions (the proposal §5).

## 4. Rejected alternatives

- **Hooks only, as today.** §1.2 shows the failure: a cleanup in
  `_onDestruct` is skipped by a dispose from `Constructed`, and each resource
  needs a field and two release sites.
- **An imperative `ownUntilDestruct(resource)`** (plan §1.12 question 2). It
  registers a resource that already exists, so it must run in `_onConstruct` on
  every construct. It re-runs nothing when an input changes, and it is a
  per-construct bag in all but name.
- **Two public bags.** ADR-0041 rejected them, and that reason stands.
- **The order of plan §1.8.3 rule 3 (`_onDestruct`, then the teardowns).**
  The members destruct before the hook, so a teardown would run after the
  members that it uses were destructed.
- **The order of plan §1.8.3 rule 4 (`_onDispose`, then the teardowns).** The
  members reach `Disposed` before the owner publishes `Disposed` (`LIFE-018`;
  `LIFE-013` for container children), and `_onDispose` runs after that
  publication, so a teardown would run after its members were disposed.
- **Construct-scoped reactions that also run while destructed.** A hidden
  view-model would keep its effects and subscriptions. `alive: true` is the
  explicit choice for that behavior.
