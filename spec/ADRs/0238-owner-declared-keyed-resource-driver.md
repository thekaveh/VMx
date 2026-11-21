# ADR 0238 — An owner-declared keyed driver for `AsyncResourceVM`

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (decision record; chapter 24 and the chapter 23
  edit land with the implementations)
- **Extends:** [ADR-0100](0100-async-resource-vm.md), with a keyed driver that
  the owner declares; its §2.7 and §4.6 stay
- **Related:** [ADR-0056](0056-v3-async-command-cancellation.md),
  [ADR-0195](0195-command-continuation-timing-order-and-thread.md),
  [ADR-0199](0199-async-resource-loader-cancellation-restores-the-stable-state.md),
  [ADR-0228](0228-discard-retry-cancel-restores-the-stable-state.md),
  [ADR-0234](0234-registered-reactive-state-with-tracked-dependencies.md),
  [ADR-0236](0236-members-registered-with-an-owner-and-owner-scoped-injection.md),
  [ADR-0237](0237-construct-scoped-reactions.md), rows D7 and D27 of the
  [upstream-candidates plan](../proposals/2026-10-20-upstream-candidates-plan.md),
  the design proposal
  [`2026-11-15-registered-reactive-state.md`](../proposals/2026-11-15-registered-reactive-state.md),
  #366, #376, #1622.

## 1. Context

### 1.1 Keyed loading today

`AsyncResourceVM` loads one value on demand. A view-model whose data depends on
a key, such as an id, a filter or a page number, and on whether its view is
visible, writes the loading policy by hand. It compares the requested key with
the loaded key, starts or supersedes a load, cancels a load when the view
hides, marks the data outdated, and loads again when the view shows.

ADR-0100 §2.7: "The state machine does not auto-load on construct or cancel on
destruct. Disposal alone is terminal: it invalidates identity, cancels
work/commands, releases the accepted value, and makes later intents and
notifications inert." ADR-0100 §4.6 rejects coupling loading to construct and
destruct: "Rejected. View attachment and route activation are separate product
policies; only terminal disposal has portable teardown meaning." Chapter 23 §1:
"It does not start automatically during component construction or stop during
destruction; terminal `Dispose` controls its lifetime."

ADR-0100 §2.4 keeps the error surface small: "no new token, signal, exception,
or error observable becomes public." Chapter 23 §7: "expected loader failure is
represented once by resource state and MUST NOT also appear on
`AsyncRelayCommand.Errors`."

Plan D27 (`cancelOnDestruct`), disposition "Decline as an option", gives the
reason "Contradicts ADR-0100 §2.7" and points to plan D14 or a hook in the
owner instead. Plan D7 (polling), disposition "Recipe now; use case for #388 and
D30": "ADR-0100 §2.1, §2.7, §4.6. `AsyncResourceVM` is sealed in C# and final in
Swift."

### 1.2 Evidence

The view-models of the production Vue client of ADR-0234 §1.2 compare a
requested key with the current one, cancel stale loads, mark data outdated
while a section is collapsed, and load again when it opens. Some of them
subclass `AsyncResourceVM` to gate `load()`. C# and Swift forbid that subclass,
and Rust has no subclassing. The tier B rewrite uses 8 keyed resources or
drivers. Two sites kept their hand logic, because their rules differ from the
driver's rules: one does not retry an error when its section opens again, and
one starts its first load when its parent asks for it, so a first load that a
collapse cancelled must not start again by itself. In the rewrite, a load that
the driver started and that rejected reached the platform's unhandled-error
route, where the hand-written code had logged it.

## 2. Decision

### 2.1 The driver is the owner's policy

1. `keyedResource(options)` builds an `AsyncResourceVM<T>`. The resource gets
   the owner's hub and dispatcher, the name `options.name` (by default the
   owner's name followed by `:resource`), the retention and the value cleanup
   of the options, and a loader that passes `options.load` the key that the
   load captured when it started. `keyedResource` registers the resource as a
   member of its owner (ADR-0236), installs a keyed driver for it and returns
   it.
1. `followKey(resource, options)` installs a keyed driver for a resource that
   exists already: a member, or the view-model itself when it subclasses
   `AsyncResourceVM` in a flavor that allows that subclass. It returns the
   reaction handle of ADR-0237.
1. A keyed driver is a construct-scoped reaction (ADR-0237). It is active from
   the construct of its owner until the owner's destruct, and its stop applies
   the disable rule (§2.2 rule 4). It evaluates `key()` and `enabled()` in its
   tracking frame, so it follows what they read (ADR-0234). `enabled` defaults
   to always true.
1. The resource keeps chapter 23 unchanged: it never loads at its own construct
   and never cancels at its own destruct (ADR-0100 §2.7). The coupling is a
   policy that the owner declares and that VMx executes. ADR-0100 §4.6 stands:
   view attachment and activation stay product policies, which the owner
   expresses through `key()` and `enabled()`.

### 2.2 The rules of the driver

1. The driver keeps two values. `startedKey` is the key of the last load that
   entered `Loading`, whoever started that load. `outdated` is false at first.
   The driver's effective enable is true when the driver is active, `enabled()`
   returns true, and `key()` has returned a key at least once. An `enabled()`
   that throws reads as false.
1. When the effective enable turns true, also at the start of the driver: a
   resource that never started a load starts one only with `autoLoad`.
   `autoLoad` defaults to false, so the first load stays on demand (chapter 23
   §1). Otherwise the driver starts a load when `outdated` is set, when `key()`
   differs from `startedKey` by the key equality, or when the state is `Error`.
1. While the effective enable stays true, a `key()` that differs from
   `startedKey` starts a load, when the resource has started a load before.
   The latest start wins (chapter 23 §6).
1. When the effective enable turns false, also at the stop of the driver, a
   load in flight is cancelled and `outdated` is set, unless
   `cancelWhenDisabled` is false.
1. While the driver is disabled, it does not remember a key change, because
   rule 2 compares with `startedKey`. Enabling it again never reloads data that
   is current for its key. A consumer that wants a reload at every enable
   writes that reload as a reaction.
1. The driver starts a load with `load()` from `Idle` and with `reload()`
   otherwise. Any entry into `Loading` clears `outdated`, also an entry that
   something else started. A `key()` that throws keeps the previous key, and
   the error is reported once per change into error.
1. Two policy options serve the sites whose rules differ. The first one turns
   off the retry of an `Error` when the driver is enabled again (rule 2). The
   second one keeps on demand a first load that a disable cancelled: the next
   enable then treats the resource as one that never started a load. The
   defaults keep rules 2 to 5. The proposal (§4) names the options in each
   flavor.
1. A load that the driver starts has no caller that awaits it, like a
   fire-and-forget command execution (chapter 04 §10.4). When such a load
   rejects, the driver reports the fault on the resource's own error channel:
   the `errors` channel of the resource's load command for a start from
   `Idle`, and of its reload command otherwise. The fault never goes to the
   platform's unhandled-error route. As on the fire-and-forget path of
   chapter 04 §10.4 (ADR-0195), the fault reaches `errors` only after the
   load has settled. An expected loader failure stays the
   `Error` state and never reaches that channel (chapter 23 §7), and a
   cancellation is never an error. The resource gains no new public error
   observable (ADR-0100 §2.4).
1. The key equality is `options.equals`, by default the flavor's default
   equality. In development builds, a load that only a key difference caused,
   while the new key is structurally equal to `startedKey`, is reported once
   per class, because the equality probably compares identities.

### 2.3 Earlier decisions

1. ADR-0100 is extended, and its §2.7 and §4.6 stand: the resource stays free
   of lifecycle coupling.
1. Plan D27 stays declined: the resource gets no `cancelOnDestruct` option.
   The stop of the driver at destruct cancels a load in flight only because
   the owner declared the driver.
1. Plan D7 is unchanged. The driver needs no subclass, so `AsyncResourceVM`
   stays sealed in C# and final in Swift.
1. Chapter 23 describes the driver when the flavors implement it. The `ARES`
   IDs keep their meaning, and the IDs of the driver belong to chapter 24.

## 3. Consequences

- The Status of ADR-0100 and its registry cell name this ADR as an extension.
- The keyed-loading logic of each view-model becomes one declaration with
  tested rules: the latest start wins, a hidden view cancels its load, and
  outdated data loads again when the view shows.
- A view-model that subclassed `AsyncResourceVM` to gate its loads composes a
  resource and a driver instead. `followKey(this, ...)` remains for the
  subclasses that exist.
- The resource needs an internal way to report a fault on the `errors` channel
  of its own commands when its driver started the load. No public member is
  added for that.
- An owner's construct starts a load only when the driver is enabled, has a
  key, and either has `autoLoad` or has a reason from §2.2 rule 2.
- Chapter 24 adds the conformance IDs of the driver (the proposal §5).

## 4. Rejected alternatives

- **Options that couple the resource to its own lifecycle**, such as a load at
  construct or `cancelOnDestruct`. ADR-0100 §4.6 and plan D27 stand: such an
  option couples every resource to its lifecycle, while the policy belongs to
  the owner.
- **`autoLoad` on by default.** Every keyed resource would load at construct,
  against the on-demand first load of chapter 23 §1.
- **A reload at every enable.** It reloads data that is current for its key.
  The evidence shows sites that mark data stale only when an input changed
  while the view was hidden.
- **Marking the data outdated for a key change while disabled.** A key that
  changed and changed back while the view was hidden then reloaded data that
  was current for its key. The comparison with `startedKey` detects every real
  change.
- **The platform's unhandled-error route for the rejections of driver loads.**
  The owner cannot handle a fault there for one resource, and the hand-written
  code that the driver replaces handled its faults itself.
- **A new public error observable on the resource.** ADR-0100 §2.4 rules it
  out, and the `errors` channel of the resource's commands exists already.
- **Gating loads by subclassing `AsyncResourceVM`.** C# seals the class and
  Swift makes it final (plan D7), while a composed driver works in every
  flavor.
