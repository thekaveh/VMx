# ADR 0235 — Commands created and owned on the view-model, with tracked predicates

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (decision record; chapter 24 and the chapter 04
  edits land with the implementations)
- **Amends:** [ADR-0086](0086-imperative-command-requery.md) §2, the preferred
  representation of observable dependencies;
  [ADR-0012](0012-command-decorators.md) §4, the `CanExecuteChanged`
  propagation of `DecoratorCommand`
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md),
  [ADR-0016](0016-modeled-crud-commands.md),
  [ADR-0090](0090-owned-resource-registration-and-public-hub.md)
  §3, [ADR-0134](0134-disposed-command-wrappers-are-inert.md),
  [ADR-0234](0234-registered-reactive-state-with-tracked-dependencies.md),
  [ADR-0237](0237-construct-scoped-reactions.md), row D13 and §1.8.8 of the
  [upstream-candidates plan](../proposals/2026-10-20-upstream-candidates-plan.md),
  the design proposal
  [`2026-11-15-registered-reactive-state.md`](../proposals/2026-11-15-registered-reactive-state.md),
  #1996, #1580, #372, #371.

## 1. Context

### 1.1 Commands today

A view-model command needs a builder chain, an `own()` call, and triggers that
tell a binding when the predicate may have changed (chapter 04 §4). A predicate
does not announce its own inputs. Chapter 04 §4.2 says: "A predicate alone is
insufficient: it does not publish a notification when its closed-over inputs
change." A forgotten `own()` compiles and leaves a command executable after
its view-model is disposed, and a command with external triggers then keeps
its subscriptions (plan §1.8.8). A forgotten trigger leaves a bound control
stale.

### 1.2 Evidence

The production Vue client of ADR-0234 §1.2 has 117 command builder chains, 39
`.triggers(` calls and 13 `raiseCanExecuteChanged()` calls. Its builders cannot
register ownership, so it patched the builder prototypes with an owner method
of its own and calls that method 160 times. Sixteen of its triggers re-check a
gate on every property change of a whole view-model. Its predicates also read
callback options and the state of other view-models, which a list of trigger
sources must name one by one. In the tier B rewrite, 88 helper commands replace
the builder chains, and no trigger and no imperative raise remain.

### 1.3 The decisions in the way

Plan D13 (an owner method on the builders, an `owner` option and
`registerOwned`), disposition "Decline as proposed": "Does not prevent
omission; public registration path against ADR-0090 §3; parent-first child
disposal against LIFE-013; a second owner invisible to ADR-0107." Plan §1.8.8
keeps three options for #371 (A, docs and a lint rule; B, a narrow owner method
on the three command builders; C, a public lifetime signal) and says: "The
recommendation is A now, then B or C through #371's design gate." #1996 asks
the owner whether new evidence reopens that recommendation for authoring
members on the component base.

ADR-0090 §3: "C#, Python, and TypeScript expose registration only to
subclasses."

ADR-0086 §2: "Triggers remain the preferred representation for observable
dependencies. The imperative method is the escape valve for non-observable host
state or explicit binding invalidation."

ADR-0012 §4: "`CanExecuteChanged` propagation rules differ per decorator
(composite: any child; decorator/confirmation: inner only)." Chapter 04 §8.2
says of `DecoratorCommand`: "`CanExecuteChanged` fires when
`inner.CanExecuteChanged` fires."

Chapter 04 §2: "The predicate MUST NOT raise. If it does, the language flavor
MAY treat the result as `false` (defensive) but MUST NOT propagate the exception
to the caller." Chapter 04 §4: "The command does not evaluate its predicate
itself; consumers re-read `CanExecute` when they receive the event."

The scope of #372 says: "Add no global hub subscription and no inferred closure
dependencies." #1580 asks "Which trigger sources the factory accepts: a
view-model, a container, a stream.", and its sketch lists them by hand:
`watch: [this, this.notes]`.

## 2. Decision

### 2.1 Helpers that create and own a command

1. The component base gets helpers that create a command and own it in one
   call: `relayCommand(task, canExecute?, options?)`,
   `relayCommandOf<T>(task, canExecute?, options?)` and
   `asyncRelayCommand(task, canExecute?, options?)` in TypeScript, and their
   flavor idioms (ADR-0006; the proposal §4 names them). C# names them
   `Command`, `CommandOf<T>` and `AsyncCommand`, because members named
   `RelayCommand` or `AsyncRelayCommand` would hide the command types in every
   subclass; Rust reaches them through `vm.reactive()`. The implementations
   add these rows to the divergence table of ADR-0009. Each helper builds the
   command through its builder, registers it with `own()` in the same call and
   returns the concrete command. The command contract of chapter 04 does not
   change.
1. `options.triggers` passes explicit triggers, and the async helper also
   passes `throwOnCancel`.
1. The helpers are protected in C#, Python and TypeScript, as `own()` is
   (ADR-0090 §3). Swift and Rust use public members, as they do for `own`. No
   public registration path is added: builders get no owner method, view-models
   get no `owner` option, and there is no `registerOwned`. The decline of these
   shapes in plan D13 stands.
1. A helper command is an owned resource of its view-model, released with the
   other `own()` resources (chapter 02 §2.3). A command is no member
   view-model, so the depth-first rule of `LIFE-013` does not apply to it, and
   it has no second owner for ADR-0107 to see.
1. This answers plan D13, the command question of plan §1.8.8, #1996 and
   #1580: creation and ownership are one call, so the registration cannot be
   forgotten. #371 keeps its scope for commands that a fluent composition
   creates around another command.

### 2.2 Tracked predicates

1. Every VMx command tracks its own predicate, however it was built: a
   `RelayCommand`, `RelayCommandOf<T>` or `AsyncRelayCommand` made by a
   helper, by its builder or by its constructor, and the extra predicate of a
   `DecoratorCommand`. Rule 2 names the only exception: the commands that VMx
   library classes build for themselves. Each evaluation of the predicate,
   by `canExecute()` or by the check inside `execute()`, runs in the command's
   own tracking frame (ADR-0234 §2.5).
1. A command that a VMx library class builds for itself, as its chapter
   specifies, tracks no predicate. Examples are the `SelectCommand`,
   `DeselectCommand`, `SelectNextCommand`, `SelectPreviousCommand` and
   `ReconstructCommand` of every view-model, the `ApproveCommand` and
   `DenyCommand` of `FormVM`, the `ExpandableState` commands, the
   `CreateNewCommand`, `UpdateCurrentCommand` and `DeleteCurrentCommand` of
   `ModeledCrudCommands`, the commands of `AsyncResourceVM` and of the paged
   compositions, and the commands of `NotificationVM` and `ConfirmationVM`.
   Such a command keeps the triggers and the raises that its chapter
   specifies, so `EXP-006`, `FORM-032`, `FORM-041`, `FORM-043`, `FORM-044` and
   the `CMD` and `ARES` IDs keep their counts and their order. A predicate of
   `ModeledCrudCommands` that reads a composite's `current` is therefore not
   tracked, and its `current_changed` trigger stays RECOMMENDED (chapter 06
   §7). A frame that calls the `canExecute()` of a library command still
   follows its raises (rule 5).
1. The reads of the predicate form the command's dependency set: the reads of
   its last evaluation, or, for a parameterized command, the union of the reads
   of every evaluation since its last raise.
1. When a settle changes a node in that set, the command raises
   `CanExecuteChanged` exactly once and clears the set. The library never
   evaluates the predicate to decide a raise (chapter 04 §4). Tracked raises,
   trigger raises, execution-state raises and imperative raises share one
   channel and add up. No kind coalesces another (chapter 04 §4.3).
1. The reads of the predicate also count for an enclosing evaluation, so a
   computed property that calls `canExecute()` depends on the same state. A
   `canExecute()` call inside an evaluation also records a dependency on that
   command's `CanExecuteChanged`. A computed property over a command therefore
   follows the command's raises for inputs outside the graph too.
1. A throwing predicate still reads as `false` (chapter 04 §2), and it keeps
   the reads it made before the throw, so a later change raises again. A
   `ReactiveWriteError` or a `ReactiveCycleError` inside a predicate is a
   defect, and development builds report it once per class.
1. `CompositeCommand` and `ConfirmationDecoratorCommand` have no predicate of
   their own. They only forward the raises of their inner commands. A
   `DecoratorCommand` forwards the raises of its inner command, and it also
   raises once when a tracked input of its own extra predicate changes. Its
   frame records the reads of its extra predicate only, not the reads of its
   inner command.
1. Explicit `triggers` and `raiseCanExecuteChanged()` remain, for inputs
   outside the graph only: a stream that is no graph node, or host state that
   has no observable source. The scope line of #372, "no inferred closure
   dependencies", is lifted for predicates, and tracking replaces the `watch`
   lists of #1580. The other constraints in the scope of #372 stay with its
   design of decorator gates, except that its pilot no longer needs explicit
   sources.
1. The task of a command is no change scope. The writes of a task settle as
   they happen (ADR-0234 §2.3). Command wrappers stay non-owning (ADR-0134).

### 2.3 Earlier decisions

1. ADR-0086 §2 is amended. For inputs that are graph nodes, that is registered
   state and library properties, tracking replaces triggers as the
   representation of observable dependencies. Triggers remain for observable
   inputs outside the graph. The imperative method remains the escape valve
   for non-observable host state and for explicit binding invalidation. The
   other rules of ADR-0086 §2 stay.
1. ADR-0012 §4 is amended for `DecoratorCommand`: it propagates the raises of
   its inner command and the raises of its own tracked predicate. A
   `ConfirmationDecoratorCommand` still propagates its inner command only, and a
   `CompositeCommand` still propagates any inner command.
1. Chapter 04 §2, §4, §4.2 and §8.2 change when the flavors implement this
   ADR. Tracked predicates join §4, and the statement of §4.2 that a predicate
   publishes no notification stops holding for inputs that are graph nodes.
   The existing conformance IDs keep their meaning: the `CMD` and `CMDD` IDs,
   and the IDs that count or order the raises of library commands, such as
   `EXP-006`, `FORM-032`, `FORM-041`, `FORM-043` and `FORM-044` (§2.2 rule 2).
   The new IDs belong to chapter 24.

## 3. Consequences

- The Status of ADR-0086 and its registry cell name this ADR for §2. The
  Status of ADR-0012 and its registry cell name this ADR for §4.
- `this.own(builder.build())` stays valid, and a command built that way tracks
  its predicate too. A command whose predicate reads registered state or
  library properties raises more often than today. The raises add up (chapter
  04 §4.3), and a binding re-reads `CanExecute` on each raise. A consumer
  command that keeps a trigger for an input that is a graph node raises twice
  for each change of that input, so a migration removes such a trigger.
- The commands that VMx builds inside its own classes keep their raises, their
  counts and their order (§2.2 rule 2).
- Every command class in every flavor needs its own tracking frame. A
  decorator knows its inner command natively, so it can leave the inner reads
  out of its own frame.
- In the client's tier B rewrite, the builder chains, the triggers and the
  imperative raises go to zero, with 88 helper commands.
- Chapter 24 adds the conformance IDs for the helpers and for tracked
  predicates (the proposal §5).

## 4. Rejected alternatives

- **Docs and a lint rule only (plan §1.8.8, option A).** Every builder chain
  and every trigger stays, and an omission is caught only by extra tooling.
- **A narrow owner method on the builders (option B), an `owner` option, or
  `registerOwned` (plan D13).** A forgotten builder call is as silent as a
  forgotten `own()`, and a public registration path conflicts with ADR-0090
  §3.
- **A public lifetime signal (option C).** It adds public surface in five
  flavors for a problem that one call that creates and owns removes.
- **Named trigger sources (`watch: [this, this.notes]`, #1580).** A whole
  view-model as a source raises on every property change of that view-model. A
  list must name every view-model that a callback reaches, and it drifts when
  the predicate changes.
- **Tracking only in helper commands.** A builder command or a `wrapWith`
  decorator over registered state would need triggers again, and two kinds of
  commands would behave differently.
- **Evaluating predicates in a settle and raising only on a changed result.**
  The library never evaluates a predicate (chapter 04 §4). A predicate can be
  costly or parameterized, and a raise only asks a binding to read again.
