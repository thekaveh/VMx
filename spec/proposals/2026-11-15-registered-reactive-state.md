# Registered reactive state for view-models: implementers' reference

This document is the reference for the agents and maintainers who implement
registered reactive state in the five VMx flavors. A view-model declares its
observable state once, registers its derived getters as computed properties
whose dependencies VMx tracks through any call chain, creates and owns its
commands with tracked predicates, registers member view-models that follow its
lifecycle, and declares construct-scoped reactions and keyed resources. Views
keep reading plain values.

The document states every rule with a stable number (R3.1 to R19.13), the API of
each flavor, the planned conformance IDs, the planned edits of the normative
chapters, the decided open questions and the implementation phases. Tickets cite
the rule numbers. The text is complete without the private evidence that led to
the design.

## 1. Status

| Field             | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status            | Accepted design. Not normative yet. A new chapter 24, "Registered reactive state", the chapter edits of §5.3 and the `RSTATE` conformance IDs of §5.2 land with the implementations. Chapter 12 admits an ID only with a marker in all five flavors, and CI requires a passing executed test for every library ID in every flavor, so chapter 24 lands after all five flavors pass (§7).                                                                                                                                                                                          |
| Date              | 2026-11-15                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Decision records  | ADR-0234 (registered state and computed properties with tracked dependencies), ADR-0235 (commands created and owned on the view-model, tracked predicates), ADR-0236 (members registered with an owner, owner-scoped injection, walks that visit members), ADR-0237 (construct-scoped reactions), ADR-0238 (the keyed resource driver).                                                                                                                                                                                                                                           |
| Earlier decisions | ADR-0234 supersedes ADR-0040 §2, the INPC-pattern clause of its §4 item 1 and its §4 item 2 for state that a class registers, amends ADR-0083 §4.1, and extends ADR-0172 with the reactive drain's wait; ADR-0083 §4.4 and ADR-0039 stand. ADR-0235 amends ADR-0086 §2 and ADR-0012 §4. ADR-0236 extends ADR-0162 §2.2, ADR-0107 §2 and ADR-0105 §2 (containers and hierarchies refuse a view-model that has an owner), and keeps ADR-0003. ADR-0237 amends ADR-0041 §4 and ADR-0090 §2 item 4. ADR-0238 extends ADR-0100, whose §2.7 and §4.6 stand. The ADRs state each change. |
| Reference code    | `spec/proposals/2026-11-15-registered-reactive-state/prototype/`, a TypeScript prototype on the published VMx 3.30.0. It is reference code: it is not shipped and CI does not build it. Its README says how to build and test it. Paths in this document that start with `prototype/` are relative to `spec/proposals/2026-11-15-registered-reactive-state/`.                                                                                                                                                                                                                     |
| Evidence          | A production Vue client on VMx 3.30.0 was rewritten twice as type-checked prototypes. With this design and the helpers of the unreleased TypeScript 3.31.0 source version (for example the `find` type guard and `DelayedTask`), its view-model layer went from 12,701 to 7,470 code lines (−41.2%), and its hand-written notification calls from 283 to 4. The prototype passes 282 tests, including two adversarial rounds. Details are in §8.                                                                                                                                  |
| Validation step   | A pilot in a second consumer is a recommended validation step, tracked as a follow-up. It is not a gate (ADR-0234).                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Effect            | None on behavior until the implementations land. Spec 05 §2.3 records the adopted direction (ADR-0234); chapter 24 will state the normative rules.                                                                                                                                                                                                                                                                                                                                                                                                                                |

How to use this document:

- §2 defines the terms. §3 states the rules; most groups of rules end with the
  prototype files that implement them.
- §4 gives the API of each flavor. The rules use the TypeScript names; §4 maps
  them.
- §5 gives the conformance IDs with their Given/When/Then text, ready to copy
  into chapter 12 as §5.1 describes, and the planned chapter edits.
- §6 lists the decided open questions. §7 is the implementation plan. §8 is
  the evidence.

## 2. Terms

- **View-model (VM).** An instance of any VMx component base:
  `ComponentVMBase` and its subclasses `ComponentVM`, `ComponentVMOf`,
  `ReadonlyComponentVMOf`, `AsyncResourceVM`, `CompositeVM`, `CompositeVMOf`,
  `GroupVM`, `AggregateVM1` to `AggregateVM6` and `HierarchicalVM`, and the
  forwarding decorators. In Rust, every VM type that has `on_construct`
  (chapter 02 §2.2).
  - `FormVM` and `DiscriminatorVM` are library objects, not VMs, in all five
    flavors: they register nothing and provide native nodes only (R15.1).
  - In C#, the forwarding decorators implement `IComponentVM` without deriving
    from `ComponentVMBase`; they get the helpers of §4.3 by delegation.
  - In C#, `ComponentVM`, `ComponentVM<M>`, `ReadonlyComponentVM<M>`,
    `CompositeVM<VM>`, `GroupVM<VM>` and `AggregateVM1` to `AggregateVM6` are
    sealed, and the helpers are protected. A C# VM that registers is a subclass
    of `ComponentVMBase`, `ComponentVMBaseOfM<M>`, `CompositeVMBase<VM>`,
    `GroupVMBase<VM>` or `HierarchicalVM<TModel, TVM>`, or a forwarding
    decorator.
- **Node.** A reactive value with an equality and a version. The kinds are:
  - **state node**: public state that a VM registers (R3.1);
  - **signal**: private state of a VM (R3.11);
  - **computed node**: a public derived value that a VM registers (R3.2);
  - **memo**: a private derived value, evaluated lazily (R3.11);
  - **native node**: a VMx library property that announces its changes
    (R15.1);
  - **announcement node**: a version counter for a name of a source that is
    not a node (R15.3);
  - **invalidation node**: an internal version counter of each computed and
    each memo, which `invalidate` bumps (R3.10, R6.1).
- **Published node.** A state node or a computed node. It has a name and an
  owning VM, and its changes are announced.
- **Version.** A counter on each node that grows by one whenever its value or
  its error state changes (R6.3).
- **Frame.** A running evaluation that records the nodes it reads: a computed
  or memo evaluation, an activation baseline, a command predicate evaluation,
  an effect run, a reaction select, a keyed-driver selector, or the
  development probe.
- **Evaluation frame.** A frame that must not write. Every frame is one,
  except an effect run. An equality call (R6.10) and an activation (R4.1) are
  evaluation frames that record nothing.
- **Write.** One graph mutation (R6.1). An **accepted** write changes at least
  one node (R6.2).
- **Epoch.** The nodes that one write, or one change scope, writes or
  evaluates. The **settled value** of a node is its value when the epoch
  began.
- **Settle.** The step that brings the affected nodes up to date after one
  write or one change scope, and computes the changed set (R6.4, R6.5).
- **Drain.** The FIFO processing of the queued entries: announcements, command
  raises and reaction runs (R9). The **drainer** is the call, and in a
  threaded flavor the thread, that runs it.
- **Helper.** The dual-channel property notification helper
  `_notifyPropertyChanged` of spec 05 §2.3. The **local-only raise** is the
  primitive `_raisePropertyChanged` of the same section.
- **Library operation.** A call into VMx library code that changes or
  publishes VMx state: lifecycle calls, member registration, container and
  collection mutations, model assignments, command executions, resource
  intents, expansion changes, activation, and the reactive helpers except
  `change()` (R5.7).
- **Library mutation.** A library operation that changes native nodes (R15.2).
- **Library publication.** A library call that delivers its own change
  messages: the helper, the local-only raise, a status transition, a command
  raise, and the change stream of a library class (R15.2).
- **Reaction.** An effect, a reaction, a `whileConstructed` setup or a keyed
  driver (R12). An **alive** reaction is a `reaction` registered with
  `alive: true`. Every other reaction is **constructed-kind**.
- **Reaction scope.** The span of time in which a VM's constructed-kind reactions are
  active: from construct step 5 (R13.1) to the destruct pause (R13.2 step 2).
- **Activation.** The step that turns a VM's registered computeds into
  memoized, announced nodes (R4). A **baseline** is the silent first
  evaluation of a computed at activation.
- **Owner and member.** A VM that registers another VM with `member()` is its
  owner; the registered VM is its member (R11).
- **Stream-fed route.** The route of a failure that has no caller to reach, per
  flavor (spec 03 §3.6 rule 4): C# discards it, Python logs it with
  `logger.exception`, TypeScript reports it through rxjs
  `config.onUnhandledError`, and Rust catches the panic. Swift subscribers on
  these channels cannot fail, so Swift has no such route (§4.7). The
  implementations reuse the existing entry points: TypeScript
  `reportUnhandled` (`langs/typescript/src/services/reportUnhandled.ts`),
  Python the `logger.exception` isolation of `vmx/_subscriber_failures.py`,
  and in C# and Rust the catch sites of the existing hub subscriber
  isolation.
- **Development.** The configuration in which the development diagnostics are
  on for a VM (R19.11, R19.13).
- **Producer flush.** The delivery of a VM's queued announcements before one
  of its direct sends (R9.8).

## 3. Rules

The rules are normative for the implementations. Chapter 24 will restate them.

- **Numbers.** A rule number has the form R*g*.*n*. The group *g* runs from 3 to
  19 in the order of §3.1 to §3.17, so R3 is registration and R19 is
  development diagnostics. The numbers are the ones that the prototype's
  comments and tests cite. A rule keeps its number when its text changes, and a
  new rule takes the next free number of its group.
- **New rules.** A rule, or a part of a rule, that the prototype's design does
  not state is marked *(new in this proposal)*. The prototype does not
  implement it, and §6 records the larger ones as decisions.
- **Names.** The rules use the TypeScript names. §4 maps them to the other
  flavors.
- **Errors.** "The usage error" is the flavor's error for a misuse (§4.7).
  `ReactiveWriteError`, `ReactiveCycleError` and `ReactiveOverflowError` are
  the TypeScript names of the three reactive errors (§4.7).

### 3.1 Registration (R3)

- **R3.1 State.** `observable(initial, equals?)` creates one state node for
  each own enumerable string key of `initial`, in key order.

  - Each node holds the key's initial value. Its equality is `equals[key]`, or
    the flavor's default equality (§4.7).
  - For each key the base installs an accessor on the instance. In TypeScript
    it is an own accessor, configurable and enumerable. The getter is a
    tracked read of the node (R5.1). The setter is one write of that key
    (R6.1). Python installs no setter: an assignment raises `AttributeError`,
    and writes go through the writer (§4.4).
  - Registration announces nothing.
  - The call returns a writer. `writer(patch)` is one write of every key in
    `patch`. A key that is absent from `patch` keeps its value. A key of
    `patch` that this writer did not register raises the usage error before
    anything is written.
  - C#, Swift and Rust register one state node per call or per declaration and
    give the node to the class (§4).

- **R3.2 Computed.** `computed(...names)` and `computed(equalsByName)` create
  one computed node per name, in argument order (key order for the second
  form). The equality is the flavor's default equality or the given function.

  - Each name resolves, on the prototype chain, to an accessor with a getter.
    The base installs an accessor on the instance (TypeScript: own,
    configurable, not enumerable) that reads through the node (R3.9). The node
    evaluates the most-derived getter with the instance as `this`.
  - When the resolved accessor has a setter, the installed accessor forwards an
    assignment to it unchanged.
  - Registration evaluates nothing on a VM that is not activated. On an
    activated VM it takes the baseline at once, with no announcement (R4.3).
  - C#, Swift and Rust cannot wrap an existing getter. There, the computed node
    is created from an evaluation function, and the public property reads the
    node (§4).

- **R3.3 Usage errors.** Each of these raises the usage error.

  - A name that is already registered on this instance, as state or as a
    computed.

  - A state key that names an accessor on the prototype chain.

  - A computed name without a getter on the prototype chain.

  - A name of a member that a VMx library class in the instance's prototype
    chain declares (`name`, `hint`, `type`, `status`, `isConstructed`,
    `isCurrent`, `hub`, `propertyChanged`, `model`, `modeledHint`, `state`,
    `current`, `children`, and every other one). Library properties are native
    nodes already (R15.1). Each flavor finds these names as follows and
    compares them in its announced-name idiom (`IsConstructed`,
    `is_constructed`, `isConstructed`) *(new in this proposal; the prototype
    takes its library classes from the package exports)*:

    - TypeScript: every property name on the prototype chain from the first
      prototype that VMx marks as a library class (with an internal symbol on
      the prototype of each library class) up to `ComponentVMBase.prototype`;
    - Python: the names in `vars()` of each class of the MRO whose
      `__module__` starts with `vmx.`;
    - C#: the public and protected member names that the base types from the
      `VMx` assembly declare, found by reflection and cached per type;
    - Swift: the compiler rejects such a declaration;
    - Rust: a fixed list of library member names for each VM type, in
      `reactive.rs`.

    R19.2 uses the same test to find the first VMx library class.

  - TypeScript and Python: a name that is already an own attribute of the
    instance, such as a class field initialized before the registration.

  - For `invalidate(...names)`: a name that is not a registered computed of
    this VM.

  A registration inside an evaluation frame throws `ReactiveWriteError`
  (R16.7).

  The accessor check (a state key that names an accessor) and the getter
  check (a computed name without a getter) apply to TypeScript and Python
  only. They ignore the accessors and descriptors that VMx itself installed:
  Python unwraps a VMx descriptor to the attribute that it replaced before it
  checks, so a later instance of the same class registers like the first.

- **R3.4 After disposal started.** A registration made after the VM's disposal
  started (R13.3 step 1) installs nothing and starts nothing. `observable()`
  returns a writer that ignores every call. A signal or memo created then is
  released at once: a read returns its initial value (a memo: its function's
  result, not memoized), and a write is ignored. C# and Rust: the state node
  that `ObservableState` or `observable` returns is released at once in the
  same way, like a signal: a read returns its initial value, and a write is
  ignored.

- **R3.5 Index.** One counter per process gives an index, in creation order, to
  each published node (key order within one call, argument order for
  `computed`), each command, and each reaction. The entries that one settle
  queues are ordered by index (R8.1).

- **R3.6 Private nodes.** Signals and memos belong to the VM that created them,
  and they stop with its disposal (R17.1).

- **R3.7 Several registrations.** A VM can make several registration calls, for
  example a base class and a subclass that each register their own names.
  Registrations belong in the constructor or a field initializer; a later
  registration is allowed (R3.13, R4.3).

- **R3.8 Forwarding decorators.** On a forwarding decorator (spec 09),
  registration creates nodes for the decorator's own accessors. Their
  announcements go through the helper, which reports through the wrapped
  component (ADR-0221). The members, reactions, activation and disposal of a
  decorator follow its canonical ownership identity (ADR-0124). A VM keeps a
  weak list of the forwarding decorators that registered nodes on its
  identity, and the activation cascade (R4.1 step 2) reaches them through it
  *(new in this proposal)*.

- **R3.9 Reads of an activated computed.** When the node is clean, a read
  returns its memoized value. When it is dirty or needs a check, the read
  brings it up to date (R6.4), memoizes the result and returns it. A node in
  error state is evaluated again on every read and rethrows while it still
  fails (R16.1). Every read inside a frame is tracked (R5.4).

- **R3.10 Reads of a computed before activation.** On a VM that is not
  activated, a read calls the getter directly. It has no frame of its own and
  memoizes nothing; the reads inside the getter belong to the caller's frame.
  The read also reads the computed's invalidation node, so `invalidate(name)`
  reaches every frame that read the plain getter (R6.1). A plain getter that is
  read during its own evaluation throws `ReactiveCycleError` (R16.8).

- **R3.11 Signals and memos.**

  - Signal: a read of `value` is tracked; an assignment to `value` is one
    write; `peek()` returns the value and records nothing.
  - Memo: it is evaluated lazily, only when a read finds it dirty. A read of
    `value` is tracked and brings the memo up to date; `peek()` brings it up to
    date but records nothing; `invalidate()` is one write that makes the memo
    dirty. The memo function receives the previous value (`undefined` before
    the first evaluation).

- **R3.12 Shadowing check (TypeScript).** At activation (R4.1 step 1), each
  registered name's own property must still be the accessor that the
  registration installed. When a class field replaced it, activation raises the
  usage error "`<name>` is shadowed by a class field; declare it with
  `declare`". The VM stays unactivated, so every later trigger raises the same
  error.

- **R3.13 State registered after activation.** A state registration on an
  activated VM (for example in `_onConstruct`, which runs after activation,
  R13.1) is one write: it bumps the invalidation node of every registered
  computed of the VM, so each one is evaluated again and announced when it
  changed. A frame in another VM that read the name through `read()` before
  the registration follows it from the next announcement (R15.3); any other
  read made before the registration recorded no dependency on it. In
  development the late registration is reported once per class (R19.9).

Reference code: `prototype/src/helpers.ts` (`observable`, `computed`, `signal`,
`memo`, `invalidate`), `prototype/src/vmState.ts` (`readComputed`,
`checkShadowing`, `noteLateState`).

### 3.2 Activation (R4)

- **R4.1 Steps.** Activating a VM V runs these steps, untracked (R5.7) and as
  one evaluation frame:

  1. The shadowing check (R3.12). A failure leaves V unactivated and raises;
     no other step runs.
  1. The cascade: V's registered members in registration order, then V's
     materialized container children in container order, then the forwarding
     decorators that follow V's identity. Each one that is not activated is
     activated, depth-first. A usage error of a member or a child does not stop
     this activation; the first such error is raised when the activation
     completes.
  1. The baseline of each registered computed of V, in index order, each in
     its own evaluation frame. The result becomes both the current value and
     the settled value, and the reads become the node's dependencies. A
     computed that an earlier baseline already brought up to date is not
     evaluated again. A throwing baseline leaves the node in error state, with
     no report and no announcement (R16.3).
  1. The start of V's alive reactions that have not started (R12.5).
  1. In development, the unpublished-getter probe is scheduled on a later task
     (R19.2, R19.12).

  Activation announces nothing, raises no command and calls no handler.

- **R4.2 Triggers.** V is activated at the first of these:

  - (a) the start of V's first `construct()`, after Constructing is published
    and before `_onConstruct` (R13.1 step 2). This holds for every VM, also one
    that has registered nothing yet;
  - (b) the first subscription to V's VM-local property-change surface (spec
    05 §2.1; in C#, the first `PropertyChanged` handler);
  - (c) V's registration as a member of an activated owner, or V's addition as
    a child of an activated container, by add, insert, population or
    transfer;
  - (d) the activation of V's owner or container (R4.1 step 2);
  - (e) a call of `activate(V)`;
  - (f) in C#, Python, TypeScript and Swift, a subscription to a hub helper
    that names V as the sender: `whenPropertyChanged`,
    `propertyValueChangedMessagesFor` and `subscribeValue` (spec 03 §7).

  Rust has no trigger (f). Its hub names a sender only by number (spec 03
  §7.4: `MessageHub::subscribe_value` takes a `sender_id`), so the graph cannot
  reach the VM from the subscription. A Rust host that observes a VM only
  through the hub calls `vmx::reactive::activate` (trigger e).

- **R4.3 Idempotence.** Activation is idempotent. A VM whose disposal started
  is never activated. A computed registered on an activated VM takes its
  baseline at once.

- **R4.4 Evaluation frame.** A write or a registration during an activation
  throws `ReactiveWriteError` (R16.7). In a baseline, the computed then enters
  error state.

- **R4.5 No baselines in constructors.** No baseline is taken while a
  constructor runs. A base-class constructor would evaluate a subclass override
  before the subclass's fields exist. The price: a VM that is never
  constructed, bound, owned, contained or activated does not announce its
  computeds (its state writes are still announced). A host that observes such a
  VM only through the hub calls `activate(vm)`; trigger (f) does this for the
  hub helpers of C#, Python, TypeScript and Swift. In development, R19.7
  reports the case. Phase 3 makes TypeScript's `recordPropertyChanges`
  (`src/testing/recorders.ts`) activate the VM named by `filter.sender` when
  the recorder subscribes; the other flavors ship no sender-filtered recorder.
  A host that binds through raw hub subscriptions calls `activate(vm)`. The
  React adapter is such a host: `useVm` (`packages/react/src/useVm.ts`)
  subscribes to `vm.hub.messages`, which is no trigger. Once `activate` is
  public (phase 10), the adapter's own release makes `useVm` and
  `useVmChildren` call `activate(vm)` when they bind a VM.

- **R4.6 Publication window.** Computed publication works from activation until
  the VM publishes Disposed, in every status in between. A destructed VM that
  something retains keeps computing: a change of a source evaluates its
  activated computeds again and announces each one that changed. There is no
  option to pause it (§6). An owner that wants work to wait for its next
  construct moves the work into a constructed-kind reaction (R12.1).

Reference code: `prototype/src/vmState.ts` (`activateState`,
`activateUntracked`, `installActivationHook`).

### 3.3 Tracking (R5)

- **R5.1 Edges.** A read of a node inside a frame records an edge from the node
  to the frame when the read happens, together with the version that the frame
  read (R9.2).
- **R5.2 Dynamic dependencies.** Each evaluation replaces the frame's
  dependency set with the reads it made. A parameterized command keeps a union
  instead (R10.2).
- **R5.3 Call chains.** Tracking follows the call chain. Plain getters, methods,
  callbacks passed as options (for example `label: () => this.#label.value`)
  and the accessors of other VMs (the owner, a member, a sibling) are
  transparent: the reads that they make belong to the running frame.
- **R5.4 Reads of computeds.** A read of an activated computed inside another
  frame records an edge to that computed node, not to the nodes it depends on.
  The edge is recorded after the computed is brought up to date, so it carries
  the version that the frame actually read.
- **R5.5 Untracked reads.** `untracked(fn)` and `peek()` record nothing. A read
  outside every frame records nothing. A node never depends on itself.
- **R5.6 Reads after disposal.** A read of a node of a VM that published
  Disposed returns the node's last value and records nothing. A computed or
  memo that was never evaluated has no last value: the read calls its getter or
  function directly, without memoizing, as R3.10 does.
- **R5.7 Library operations run untracked.** A library operation runs
  untracked: its internal reads are no dependency of the frame that called it.
  The library operations are the lifecycle calls, member registration and the
  member walk, container and collection mutations, model assignments, command
  executions, resource intents, expansion changes, activation, reaction-handle
  calls, and every reactive helper except `change()`. Inside an evaluation
  frame a library operation throws `ReactiveWriteError` before it changes
  anything (R16.7). Getters and queries (`canExecute`, `canSelect`, `count`,
  item access, snapshots) stay transparent.
- **R5.8 Deliveries run untracked.** A delivery runs untracked: a hub send, a
  VM-local emission, a status publication, a `CanExecuteChanged` raise and
  every drain entry. An observer never records into the frame of the code that
  caused the delivery.

Reference code: `prototype/src/graph.ts` (`track`, `runFrame`, `untracked`),
`prototype/src/library.ts` (a stand-in for R5.7 and R5.8 that a VMx
implementation does not need).

### 3.4 Writes and settles (R6)

- **R6.1 Writes.** Each of these is one write:

  - an assignment to a state accessor (one key);
  - a writer call (every key of its patch);
  - an assignment to a signal's `value`;
  - `invalidate(...names)` (the invalidation nodes of the named computeds of
    this VM);
  - `memo.invalidate()`;
  - the native-node commits of one library mutation (R15.2);
  - one status transition (R15.2);
  - a version bump of an announcement node (R15.3);
  - a state registration on an activated VM (R3.13);
  - the exit of an outermost change scope (R7.2).

- **R6.2 Acceptance.** A write is accepted when all three conditions hold:

  - the owning VM has not published Disposed (R13.3 step 5); otherwise the
    write is ignored without an error;
  - the caller is not inside an evaluation frame; otherwise the write throws
    `ReactiveWriteError` and nothing is applied (R16.7);
  - at least one target value differs from the node's current value by the
    node's equality. `invalidate`, `memo.invalidate()`, version bumps and late
    state registrations are always accepted.

  A write that is not accepted changes nothing, queues nothing and announces
  nothing.

- **R6.3 Commit.** An accepted write stores the new values, adds one to the
  version of each node that it changed, marks the direct dependents of those
  nodes dirty, and marks their transitive dependents "check".

- **R6.4 Settle.** Outside an open change scope, the settle runs right after the
  commit. It brings each dirty or check node that is eager up to date, at most
  once each, with whatever those evaluations pull. A node is eager when it is
  (i) a published computed of an activated VM, (ii) in the dependency set of a
  command, or (iii) in the dependency set of an active reaction.

  - A node is brought up to date only after every node it depends on. A check
    node first brings its derived dependencies up to date, and it is evaluated
    again only when one of them changed.
  - Eager nodes go in ascending height (R6.8), then index.
  - A node that is evaluated again to a value equal to its old value, by its
    equality, does not change: its version stays, and its dependents become
    clean without an evaluation.
  - The settle never evaluates a command predicate or a reaction select. A
    memo that no eager node reads stays dirty until it is read (R3.11).

- **R6.5 Changed set.** A node changed in a settle when its value at the end
  differs from its settled value by its equality. A change from a value to an
  error, from an error to a value, or from an error to a different error
  (R16.2) is a change; the same error again is not. The comparison that the
  write or the evaluation already made is reused, so a write calls an equality
  at most once for one pair of values. The changed published nodes form the set
  C. At the end of the settle, each node that was written or evaluated takes
  its current value as its settled value.

- **R6.6 Schedule.** The settle appends entries to the drain queue in this
  order:

  - (a) one announcement entry for each node in C, by height, then index;
  - (b) one raise entry for each command whose dependency set holds a changed
    node, by index; that set is then cleared (R10.3);
  - (c) one run entry for each active reaction whose dependency set holds a
    changed node, by index; the reaction is marked dirty.

- **R6.7 Delivery.** A write settles before it returns, so the values are
  current when it returns. Its entries are delivered before it returns, unless
  a drain is already active (R9.3) or a library publication is delivering its
  own messages (R15.2). Then they are delivered when that drain, or the
  outermost publication, returns.

- **R6.8 Height.** State, signal, native, announcement and invalidation nodes
  have height 0. A computed or memo has height one more than the largest height
  of its current dependencies, or 1 when it has none.

- **R6.9 Diamond.** For A → B, A → C and B + C → D, one write of A evaluates B,
  C and D at most once each and announces D at most once. Two writes of A are
  two settles; they announce D twice when D changed twice.

- **R6.10 Equalities.** An equality is user code with a defined context:

  - it runs untracked, so its reads are no dependency of the frame that caused
    the comparison;
  - it runs as an evaluation frame, so a write inside it throws
    `ReactiveWriteError` there;
  - a throw counts as "not equal", and the error is reported on the
    stream-fed route once per call. A non-change cannot be hidden, so the
    conservative answer is to accept and announce;
  - the flavor's default equality and the library's shallow equality (§4) run
    directly.

Reference code: `prototype/src/graph.ts` (`writeSources`, `settle`, `evaluate`,
`compareValues`, `isChanged`).

### 3.5 Change scopes (R7)

- **R7.1 Scope.** `change(fn)` runs `fn` synchronously and returns its result.
  While a change scope is open, accepted writes commit (R6.3) but do not
  settle. A read inside `fn` is fresh: a dirty node that `fn` reads is brought
  up to date, which changes its current value but not its settled value.
- **R7.2 Exit.** Nested scopes flatten. When the outermost scope exits,
  normally or by an exception, one settle handles every write of the scope (R6.4
  to R6.6), and the drain then runs if none is active. Each published node is
  announced at most once, when its value at the exit differs from its settled
  value by its own equality.
  - A state that changed and changed back is not announced.
  - Its dependents are still evaluated again. A computed that builds a new
    object each time is announced under identity equality; give it a shallow
    or domain equality.
- **R7.3 Throwing body.** When `fn` throws, the writes made before the throw
  stay, the settle and the drain run, and `fn`'s error is rethrown. An error
  raised while draining (the development bound, R9.6) does not replace it
  (spec 03 §3.3 rule 4).
- **R7.4 Limits.** `change` inside an evaluation frame throws
  `ReactiveWriteError`. A scope includes only the synchronous run of `fn`: code
  after an `await`, or in a continuation, runs outside it. Python's scope is a
  `with` block, which an `await` would keep open: `with self._change():` must
  not contain `await`, and while a scope is open, a write from another asyncio
  task raises the usage error. Frames and scopes are per thread, not
  async-context values (R18.7, §6 question 16).
- **R7.5 Hub transactions.** A change scope is independent of hub transactions:
  it never opens or closes `hub.batch`, and `hub.batch` opens no change scope.
  A direct send inside a scope (a hand-written helper call) is delivered at
  once; the scope's own writes are announced at its exit.
- **R7.6 No merge across causes.** Without a declared scope, every accepted
  write announces each dependent that changed. Nothing is merged across writes,
  and nothing waits for a hub batch, a microtask or a timer. A scope or a
  multi-key patch is the author's declaration that its writes are one change,
  as a hand-written method that assigns several fields and then notifies once
  (spec 05 §2.3). The hub still delivers every message it receives (spec 03
  §3.3).

Reference code: `prototype/src/graph.ts` (`change`).

### 3.6 Ordering (R8)

- **R8.1 One settle.** Within one settle, announcements go by height, then
  index: a value is announced after every changed published value it depends
  on, and the keys of one patch are announced in registration order. The
  command raises follow, by index. The reaction runs come last, by index.
- **R8.2 Across settles.** Entries are processed in the order they were queued
  (FIFO).
- **R8.3 One helper call.** Each announcement is one call of the helper: one
  hub `PropertyChangedMessage`, then one VM-local name (spec 05 §2.3, CVM-007
  to CVM-009). Inside `hub.batch` the local emission happens at once and the
  hub message waits for the batch.
- **R8.4 Sequences.** The order of the construct, destruct and dispose steps is
  in R13.

### 3.7 The drain and re-entrancy (R9)

- **R9.1 Queue.** There is one drain queue per process. TypeScript has one
  thread; the threaded flavors have one drain per process as well (R18.1). An
  entry is one of: announce(V, name), raise(command), run(reaction).
- **R9.2 Processing.** The drain processes the entries in FIFO order, each one
  untracked (R5.8):
  - announce calls the helper, `V._notifyPropertyChanged(name)`. It is
    dropped once V has published Disposed.
  - raise publishes one `CanExecuteChanged` on the command's channel:
    `raiseCanExecuteChanged()` for a relay command, and the decorator's own
    raise for the extra predicate of a `DecoratorCommand` (R10.8), which
    exposes no `raiseCanExecuteChanged()` (spec 04 §4.3). It is dropped once
    the command is disposed, or once the VM that owns the command has
    published Disposed.
  - run runs the reaction. It is dropped when the reaction is no longer active,
    and skipped when the reaction is no longer dirty. A run clears the dirty
    flag before it starts.
  - Skip rule: after a run or a start (R12.9), a reaction that is marked dirty
    stays dirty only when one of the nodes it read now has a newer version than
    the version it read first. Otherwise it is clean again, and its queued run
    is skipped. So an effect that writes a value and then reads the new value
    runs once per cause, and a reaction that read a value before its own write
    changed it runs again.
- **R9.3 Re-entrant writes.** A write made while a drain is active runs R6.3 to
  R6.6 at once, appends its entries and returns. This holds for writes by a hub
  or local observer during an announcement, by a `CanExecuteChanged` handler
  during a raise, by a reaction, and by code that any of them calls. Delivery
  never recurses on the call stack (spec 03 §3.3 rule 5), and the outermost
  write returns with an empty queue.
- **R9.4 Lossless per settle.** A name that an outer settle and a nested
  settle both change is announced by both. Observers read the state that is
  current at delivery.
- **R9.5 Disposal.** Before a VM publishes Disposed, its queued announcement
  entries are delivered through the helper (a producer flush, R9.8), while the
  VM can still announce. After Disposed is published, nothing of the VM is
  queued or delivered, and its remaining entries are dropped. R17.4 states the
  one exception.
- **R9.6 Development bound.** In development (R19.11), one drain throws
  `ReactiveOverflowError` when one entry (the same VM and name, the same
  command, or the same reaction) is processed more than 10,000 times. The rest
  of the queue is abandoned. A write whose fan-out reaches many distinct
  entries is delivered in full. Production has no bound. Swift reports the
  overflow instead of throwing it (§4.5). The message is
  `Reactive drain processed one entry more than 10000 times; cycle involving: <entry> x<count>, …`.
  It names the repeated entries, most repeated first, at most ten. The entry
  names are the prototype's (`describe` in `prototype/src/graph.ts`, `key` in
  `prototype/src/reaction.ts`), where `<Class>` is the VM's class name and
  `<vm name>` its `name`:
  - an announcement: `<Class>(<vm name>).<name>`;
  - a command raise: `<Class>(<vm name>):command#<index>`;
  - a reaction run: `<Class>(<vm name>):<kind>#<index>`, where `<kind>` is
    `effect`, `reaction`, `alive-reaction`, `whileConstructed` or
    `keyedDriver`, and `<index>` is the index of R3.5.
- **R9.7 Hub transactions.** The drain calls the helper unchanged. Inside
  `hub.batch`, the hub holds its messages until the batch exits, while the
  local emissions happen at once (spec 05 §2.3).
- **R9.8 Producer order.** A VM's graph announcements and its direct sends
  reach the hub in the order they were caused (spec 03 §3.2). Before a VM
  sends outside the graph, the queued announcement entries up to and including
  that VM's last one are delivered first, in queue order. A send outside the
  graph is any message that the VM's code or library code sends with the VM as
  sender, other than a graph announcement: a helper call that the graph did
  not make, a call of the local-only raise, a status transition, the messages
  of a model assignment, and the collection, tree-structure, form and resource
  messages of the library classes. Phase 3 names each such send path (§7.1).
  - The end is found again after each delivery: an announcement of the VM that
    an observer queues during the flush also precedes the send.
  - Command raises and reaction runs keep their places in the queue.
  - The rule holds inside library operations too: the library's own sends flush
    like hand-written ones.
  - A flush delivers synchronously, at the send that caused it. Flushes nest at
    most 32 deep. Past that depth the entries keep their queue order, and the
    development bound (R9.6) applies.
  - A send of a VM with nothing queued costs one lookup: the drain keeps a count
    of queued announcements per VM.

Reference code: `prototype/src/graph.ts` (`enqueue`, `drain`,
`flushProducer`, `runAsDrainEntry`), `prototype/src/reaction.ts` (`process`,
`settleDirty`). The prototype flushes only at the helper, the local-only raise
and the status transition; the collection and tree messages of its containers
are not ordered against their queued announcements (its README, §1.5).

### 3.8 Commands (R10)

- **R10.1 Helpers.** `relayCommand(task, canExecute?, options?)`,
  `relayCommandOf<T>(task, canExecute?, options?)` and
  `asyncRelayCommand(task, canExecute?, options?)` build a `RelayCommand`, a
  `RelayCommandOf<T>` and an `AsyncRelayCommand` through their builders. They
  pass the task, the predicate, each entry of `options.triggers` (as
  `.triggers(...)`) and `options.throwOnCancel`. In the same call they register
  the command with `own()` on the canonical ownership identity, and they
  return it. There is no public registration path for commands (plan D13). The
  command contract of spec 04 does not change.
- **R10.2 Tracked predicates.** Every VMx command tracks its own predicate,
  however it was built: a `RelayCommand`, a `RelayCommandOf<T>` and an
  `AsyncRelayCommand` (through the helpers, the builders or the constructors),
  and the extra predicate of a `DecoratorCommand`. The one exception is the
  library commands of R10.10, whose predicates run untracked. Every predicate
  evaluation, in `canExecute()` and in the check inside `execute()`, runs in
  the command's frame. The frame is an evaluation frame, and its reads also
  count for an enclosing frame, so a computed that calls `canExecute()`
  depends on the same nodes.
  - The frame records the reads of the predicate only. A command's own
    in-flight state (`isExecuting`) is not part of its own dependency set; its
    execution-state raises (spec 04 §10.2) already report it.
  - For a command without a parameter, the dependency set is the reads of its
    last evaluation.
  - For a parameterized command, it is the union of the reads of every
    evaluation since its last raise, kept as a set, so it grows linearly.
- **R10.3 One raise.** When a settle changes a node in the dependency set, the
  command raises `CanExecuteChanged` exactly once (R6.6 b) and clears the set.
  The library never evaluates the predicate itself (spec 04 §4). Raises add up
  (spec 04 §4.3).
- **R10.4 Throwing predicates.** A throwing predicate makes `canExecute()` return
  false (spec 04 §2) and keeps the reads it made before the throw, so a later
  change raises again. A predicate cannot hide a cycle (R16.8).
- **R10.5 `isExecuting`.** `AsyncRelayCommand.isExecuting` is a native node
  (R15.1). The command's start and completion notifications (spec 04 §10.2) do
  not change.
- **R10.6 Inputs outside the graph.** A command's task is not a change scope:
  its writes settle as they happen. Explicit triggers and
  `raiseCanExecuteChanged()` keep working for inputs outside the graph.
- **R10.7 Raise dependency.** A `canExecute()` call inside a frame also records
  a dependency on that command's `CanExecuteChanged` channel. A predicate or a
  computed that delegates to any command therefore follows its raises,
  including raises for inputs outside the graph (triggers and imperative
  raises). For a raise that the graph caused, the extra evaluation finds an
  equal value and announces nothing.
- **R10.8 Combinators.** A combinator forwards the raises of its inner
  commands, so the evaluation of an inner command inside a combinator is not
  recorded in the combinator's frame.
  - A `DecoratorCommand`'s frame records the reads of its extra predicate only.
    Its `CanExecuteChanged` is the inner command's raises merged with the
    raises of its own frame. A change of an inner input raises the decorator
    once (forwarded); a change of an extra-predicate input raises it once (its
    own frame).
  - `CompositeCommand` and `ConfirmationDecoratorCommand` have no predicate of
    their own and only forward. R10.7 still applies to a frame that calls their
    `canExecute()`.
  - `wrapWith(resource.reloadCommand, () => this.canRetry)` over registered
    state is raised when `canRetry` changes; it needs no trigger.
- **R10.9 Release.** A helper command is disposed with the VM's `own()`
  resources (R13.3 step 8). A command's dependency set is released when the
  command is disposed and at its owner's graph release. A disposed command
  raises nothing more.
- **R10.10 Library commands** *(new in this proposal; §6 question 17)*. Every
  command that a VMx library class or helper builds keeps the triggers and the
  raises that its chapter specifies, and tracks no predicate (ADR-0235 §2.2
  rule 2). Every construction site in the closed list below builds its command
  with an internal option that turns tracking off: TypeScript, an internal
  symbol option on the three builders; C#, an `internal UntrackedPredicate()`
  builder method; Python, an `_untracked_predicate=True` keyword; Swift, an
  `internal` init parameter; Rust, a `pub(crate) fn untracked_predicate(self)`
  builder method. Their predicates run untracked, and they keep no dependency
  set. Tracking therefore adds no raise for state that the command's trigger
  or imperative raise already reports, and the exact counts of `FORM-043`,
  `EXP-006` and the `CMD` and `ARES` IDs hold. (The TypeScript `FormVM`
  predicate reads the public getters `isValid` and `isDirty`, which R15.1
  makes native nodes, and it also raises through its own trigger; a tracked
  predicate would raise twice for one change.) R10.7 still applies to a frame
  that calls their `canExecute()`, so a computed over such a command follows
  its raises. A `DecoratorCommand` that a VM builds over a library command
  still tracks its own extra predicate (R10.8). A class that the library adds
  later and that builds commands joins the list in chapter 24. The closed list:
  - the built-in commands of spec 05 §5 (`SelectCommand`, `DeselectCommand`,
    `SelectNextCommand`, `SelectPreviousCommand` and `ReconstructCommand`);
  - the `ApproveCommand` and `DenyCommand` of `FormVM`;
  - the commands of `ExpandableState`;
  - the commands of `ModeledCrudCommands` (chapter 06 §7); its update and
    delete commands keep their optional current-changed trigger;
  - the commands of `AsyncResourceVM`;
  - the commands of the paged compositions;
  - the commands of `NotificationVM` and `ConfirmationVM`.

Reference code: `prototype/src/commands.ts`. The prototype finds a decorator's
inner command by the identity of its change stream; a VMx implementation holds
the inner command and needs no such test.

### 3.9 Members and services (R11)

- **R11.1 `member(vm)`.** It registers `vm` as a member of the owner. It records
  the owner link and adds `vm` to the owner's member list. The list takes part
  in the construct, destruct and dispose sequences (R13), the walks (R11.6),
  the activation cascade (R4.1) and the disposal of members (spec 02 §7.1). The
  call returns `vm`. Registering a VM that this owner already registered
  returns it unchanged. The call runs untracked and throws `ReactiveWriteError`
  inside an evaluation frame (R5.7).

  - `ownMember` (spec 02 §7.1) keeps its meaning: disposal only, with no
    construct or destruct. A VM registered with both is a member in the sense
    of this chapter.

- **R11.2 `member(Type, options)`.** It constructs
  `new Type({ ...options, hub: owner.hub, dispatcher: <the owner's dispatcher> })`
  and registers the result as `member(vm)` does. This is explicit constructor
  injection by the owner (ADR-0003). There is no ambient lookup and no
  inherited hub, there is no `parent` option (plan D20), and no public
  dispatcher accessor is needed (plan D19). Flavors that construct with
  positional parameters take a factory that receives the hub and the dispatcher
  (§4).

- **R11.3 Refusals.** Each of these raises the usage error and registers
  nothing:

  - the owner itself, or a VM with the owner's ownership identity (spec 02 §7.1
    rule 6);
  - a VM that already has another owner;
  - a VM that has a container parent;
  - a VM whose registration would close an owner cycle: the VM is the owner,
    or an owner of the owner, by ownership identity.

  Rust returns `VmxError::OwnershipCycle` for the owner itself and for an
  owner cycle, as `own_member` does (spec 02 §7.1 rule 6), and
  `VmxError::InvalidArgument` for the other refusals.

  A container (spec 06, 07, 08 and 18) refuses to add a VM that has an owner.
  It raises its own usage error before it changes anything. §5.3 names the
  operations of each chapter. A member never gets a parent link or a selection
  state.

- **R11.4 Late registration.** What a registration does depends on the owner's
  status:

  - Constructed: `member()` constructs the member at once. A failure propagates
    from `member()`, and the member stays registered.
  - Constructing, before the member walk (in `_onConstruct`, or earlier in the
    construct): the member joins the walk (R13.1 step 4).
  - Constructing, during the walk (a member's `_onConstruct` registers another
    member of the owner): the walk visits it. The walk repeats until no
    unvisited member remains, so a removal during the walk skips nothing.
  - Constructing, after the walk (from a reaction start in R13.1 step 5): the
    member is constructed at once.
  - Destructing or Destructed: the member is constructed at the owner's next
    construct.
  - The owner's disposal started, or the owner is Disposed: the member is
    disposed at once and returned (spec 02 §7.1 rule 4).
  - A VM whose own disposal started, or that is Disposed, registers nothing and
    is returned unchanged.

- **R11.5 Removal at disposal.** A member that reaches Disposed leaves its
  owner's member list, whoever disposed it. The owner keeps no reference to it,
  the walks stop visiting it, and the owner's sequences skip it. A live member
  cannot be removed (§6). A changing set of children belongs in a container.

- **R11.6 Walks.** `walk`, `walkExpanded` and `find` (spec 13) visit a VM's
  registered members after its container children or its aggregate
  `components()`, in registration order and depth-first. They skip a member
  that the children or `components()` already yielded. `walkExpanded` visits
  neither the children nor the members of a collapsed node. A VM registered
  only with `ownMember` is not visited; #1612 handles the other child hooks of
  each flavor. Chapter 13 states this rule, and the next free `UTIL` ID
  (`UTIL-005` when this was written) pins it (ADR-0236 §2.4). C#: an
  aggregate has no members, because `AggregateVM1` to `AggregateVM6` are
  sealed and cannot call the protected helpers (§2).

Reference code: `prototype/src/vmState.ts` (`addMember`, `registerMember`,
`walkMembers`, `memberDisposed`), `prototype/src/walk.ts`. The prototype
exports its walks separately; VMx changes its own.

### 3.10 Reactions (R12)

- **R12.1 Kinds and the reaction scope.** The kinds are `effect(fn)`,
  `reaction(select, handler, options)`, `whileConstructed(setup)` and the keyed
  drivers (R14). Every reaction except an alive one (R12.5) is
  constructed-kind: it is active from its start in R13.1 step 5 until the
  destruct pause (R13.2 step 2), and it stops in R13.2 step 3 or at disposal
  (R13.3 step 2).

  - The first run happens in R13.1 step 5, while the status is still
    Constructing and every member is Constructed, so a failing first run fails
    the construct (LIFE-014).
  - An effect that reads `status` or `isConstructed` sees Constructing and
    false at its first run, and runs again when Constructed is published,
    because both are native nodes. An effect never needs to read
    `isConstructed`.
  - An effect whose first run reads a computed in error state fails the
    construct unless it catches the error.

- **R12.2 Registration timing.** A constructed-kind reaction registered while
  the VM's reaction scope is open starts at once. One registered while the
  scope is closed starts at the next construct, or when a failed destruct rolls
  back (R13.2). An alive reaction starts at the VM's activation, or at once on
  an activated VM. A registration after disposal started is ignored and returns
  an inert handle (R12.10).

- **R12.3 `effect(fn)`.** Its start runs `fn` in a frame and keeps the cleanup
  that `fn` returns. A run entry (R6.6 c) runs the cleanup, then `fn` again. Its
  stop runs the cleanup. An effect run is the one frame that may write.

  - An effect runs synchronously. The flavors treat an asynchronous function
    as follows:
    - TypeScript: a function that returns a promise (a thenable) is tracked
      only up to its first `await`. The promise is no cleanup, its rejection
      goes to the stream-fed route, and in development the effect is reported
      once per class (R19.10).
    - Python *(new in this proposal)*: an effect function or a reaction
      handler that returns an awaitable raises the usage error at that call,
      because a coroutine runs nothing until it is awaited. The base closes a
      returned coroutine without running it. At an effect's first run the
      error fails the start (R16.6); at a later run it is reported (R16.5).
    - C# *(new in this proposal)*: `Effect` and `Reaction` throw
      `ArgumentException` at registration when the effect function or the
      handler is an async lambda, whose method carries
      `AsyncStateMachineAttribute`. Such a lambda converts to `Action` as
      `async void`, and its failure after an `await` would reach no VMx route.
    - Swift and Rust: the effect and handler types take only synchronous
      functions, and the compiler enforces it.
  - A run that stops or removes its own reaction (it disposes its VM, or calls
    its own handle) still has its cleanup run: the cleanup that the run returns
    runs at once, so every cleanup runs exactly once.

- **R12.4 `reaction(select, handler, { equals, immediate })`.** Its start
  evaluates `select` in an evaluation frame, and the result becomes the
  reference value.

  - With `immediate`, the start also calls `handler(value, previous)`.
    `previous` is the last value delivered before the previous stop, or `value`
    itself when nothing was delivered.
  - A run evaluates `select` again. When the new value differs from the
    reference by `equals` (R6.10), the reference is updated first, and then
    `handler(newValue, oldValue)` runs untracked. The handler may write.
  - A stop forgets the dependencies and the reference, and it keeps the last
    delivered value for the `previous` of the next immediate start. Changes
    made while the reaction is stopped are not delivered; a restart takes a new
    reference.
  - When `select` throws at an immediate start, the error is reported, and the
    first successful run makes the start's delivery.

- **R12.5 Alive reactions.** `reaction(..., { alive: true })` is active from the
  VM's activation, or from its registration when that comes later, until the
  VM's disposal starts, in every status. It has no immediate run, and a destruct
  neither pauses nor stops it.

- **R12.6 `whileConstructed(setup)`.** Its start runs `setup` untracked and keeps
  the resource that `setup` returns: an owned-resource shape of spec 02 §2.3, or
  nothing. Its stop releases the resource. A setup records no dependency, so it
  never runs again before its stop. A setup that stops or removes its own
  reaction has its resource released at once.

- **R12.7 Stop order.** Constructed-kind reactions stop in reverse index order:
  last in, first out.

- **R12.8 Teardown failures.** A cleanup, a teardown or a resource release that
  throws is isolated and swallowed (spec 02 §2.3, DISP-009).

- **R12.9 Starts are drain entries.** A reaction's start (an effect's first
  run, a setup, a reaction's reference and its immediate delivery, a keyed
  driver's start) runs as one drain entry. Writes inside it settle at once, so
  its reads stay fresh. The entries that those writes queue, including a re-run
  of the starting reaction, are delivered after the start returns, never inside
  it. A reaction is never re-entered by its own write. A start that throws
  leaves no pending re-run.

  - "Runs as one drain entry" means: the start runs synchronously at its call
    site and is never queued. While it runs, the drain counts as active, so
    its writes settle at once and only append their entries.
  - When no drain and no library publication was active before the start, and
    no change scope is open, the queue is drained right after the start
    returns. Otherwise the outer drain, publication or scope delivers those
    entries.
  - An error of the start propagates to its caller (R12.12, R13.1 step 5)
    after that drain. An error that the drain raises (the development bound,
    R9.6) propagates when the start itself succeeded; a start error takes
    precedence over it.
  - Reference code: `runAsDrainEntry` in `prototype/src/graph.ts`.

- **R12.10 Registration scopes and handles.** Every reaction has a registration
  scope:

  - Run scope. A reaction registered during a run of another reaction of the
    same VM (its start, an effect run, a reaction handler, a setup) belongs to
    that run. It is removed when that reaction runs again, stops or is removed;
    the next run registers it again. An effect that builds an inner effect per
    mode therefore has exactly one inner effect.
  - Construct scope. A reaction registered while its VM is Constructing,
    outside a reaction run (in `_onConstruct`), belongs to that construct. It
    is removed when the VM next publishes Destructed (a completed destruct, the
    destruct phase of a reconstruct, or a construct that rolls back), and it
    survives a destruct that rolls back to Constructed. `_onConstruct`
    registers it again at the next construct, so one copy runs. An alive
    reaction is never construct-scoped.
  - Instance scope. Every other reaction lives until its VM's disposal.

  `effect()`, `reaction()`, `whileConstructed()` and `followKey()` return a
  handle that removes the reaction: the reaction stops (its cleanup or teardown
  runs once), releases its edges and leaves the VM. Removing is idempotent. A
  registration that is ignored returns a handle that does nothing. A handle
  call inside an evaluation frame throws `ReactiveWriteError`, as a
  registration does. In C#, Python, TypeScript and Swift, ignoring the handle
  keeps the reaction for its scope. In Rust the handle is a guard, as VMx Rust
  subscriptions are: dropping it removes the reaction, and `detach()` keeps the
  reaction for its scope (ADR-0237).

- **R12.11 Level-triggered reactions.** A settle schedules one run of each
  affected reaction, and the run evaluates the state that is current when its
  turn comes.

  - Two writes at top level are two settles that each drain before they return,
    so a `reaction()` delivers each change.
  - Two writes made while a drain is active are two settles whose runs come
    later, so the reaction delivers once, or not at all when the value is back
    at the last delivered value.
  - Announcements stay lossless (R9.4). A subscription to `propertyChanged` or
    `whenPropertyChanged` is edge-triggered: one callback per announcement. A
    handler that needs every transition subscribes to the announcements.

- **R12.12 First run after construct.** When the start of a reaction registered
  while the reaction scope is open throws (an effect's first run, a setup, an
  immediate handler), the error propagates to the registration call. The
  reaction stays registered and active, with the reads it made.

Reference code: `prototype/src/reaction.ts`, `prototype/src/reactions.ts`
(`EffectReaction`, `ValueReaction`, `WhileConstructedReaction`),
`prototype/src/vmState.ts` (`addReaction`, `removeConstructScoped`).

### 3.11 Construct, destruct and dispose sequences (R13)

- **R13.1 Construct** (also the construct phase of a reconstruct):

  1. Admission (spec 02 §2.4). V's queued announcements are delivered (R9.8).
     Constructing is published.
  1. V is activated if it is not (R4.2 a).
  1. `_onConstruct()` runs.
  1. The member walk constructs the registered members in registration order,
     with the rules of the child-transition helper (spec 02 §6.1): it skips a
     member that is Constructed or Disposed, joins a member in a transient
     status, and waits for a background member, so V stays Constructing until
     that member settles. A member that does not reach Constructed fails the
     walk, and V rolls back (spec 02 §2.5). Members that reached Constructed
     stay Constructed (spec 02 §6.1; the undo question stays open).
  1. The reaction scope opens. The constructed-kind reactions that have not
     started start in index order, each as a drain entry (R12.9). When a
     setup, an effect's first run or an immediate handler throws, the
     reactions started so far stop in reverse order, and the construct fails
     with that error: V rolls back to Destructed (LIFE-014). An error that the
     drain raises while the starts run (the development bound, R9.6) fails the
     construct in the same way: the started reactions, the overflowing one
     included, stop in reverse order, and V rolls back to Destructed. Swift
     reports the overflow instead (§4.5), so its construct completes.
  1. V's queued announcements are delivered (R9.8). Constructed is published.

- **R13.2 Destruct** (also the destruct phase of a reconstruct). It is the
  mirror of construct:

  1. Admission.
  1. The constructed-kind reactions pause and the reaction scope closes, before
     Destructing is published, so the publication runs no effect and a
     reaction registered during the destruct waits. A change while paused marks
     a reaction dirty, but the reaction does not run. V's queued announcements
     are delivered. Destructing is published.
  1. The constructed-kind reactions stop, last in first out. Their cleanups and
     teardowns run while every member is still Constructed. Keyed drivers apply
     their disable rule (R14.4 rule 3).
  1. The member walk destructs the members in reverse registration order, with
     the rules of spec 02 §6.1. A member still sees the owner's construct-time
     resources.
  1. `_onDestruct()` runs.
  1. Destructed is published. The reactions registered during the construct
     that ends here are removed (R12.10).

  A failure in step 4 or 5 rolls V back to Constructed (LIFE-014). The stopped
  reactions start again, in index order, after the rollback is published. A
  failure of such a restart goes to the stream-fed route and does not change
  the outcome of the destruct. A reaction registered during the failed destruct
  starts then. Members that reached Destructed stay Destructed (spec 02 §6.1).

- **R13.3 Dispose** (from any status):

  1. Disposal starts at the `dispose()` call, before anything is disposed. From
     here no reaction of V runs, starts or registers, registrations are ignored
     (R3.4, R12.2), and activation is refused.
  1. The reactions of V that started, constructed-kind and alive, are torn
     down, last in first out, while the children and members that they used are
     still alive.
  1. V's container children are disposed in the container's dispose order
     (spec 02 §7: last child first when the container was built with the
     `Reverse` destruct order, ADR-0161), then its members in registration
     order, depth-first (spec 02 §7.1). V has not published Disposed, so its
     nodes still accept writes and it still announces.
  1. V's queued announcements are delivered (R9.5).
  1. Disposed is published. From here V's nodes accept no write and evaluate
     nothing, and V's other queued entries are dropped.
  1. `_onDispose()` runs.
  1. The graph release runs (R17.1).
  1. The `own()` resources are released, last in first out (spec 02 §2.3). The
     helper commands are among them.
  1. The terminal streams and the built-in commands are torn down (spec 02
     §2.3).

  Spec 02 §7 requires every member to reach Disposed before the parent
  publishes Disposed (LIFE-013), and `_onDispose` runs after that publication.
  A teardown that needs its members alive therefore runs in step 2.

- **R13.4 Foreign dispose** *(new in this proposal; derived from spec 02 §7
  for the threaded flavors)*. In a threaded flavor, a `dispose()` call while a
  construct or destruct hook of V is admitted on another thread (spec 02 §2.4,
  §7) runs steps 1 and 2 at the call, then steps 4 and 5 (Disposed first, as
  spec 02 §7 says for a foreign dispose), then step 3 after the hook completes,
  then steps 6 to 9.

Reference code: `prototype/src/vmState.ts` (`constructSequence`,
`destructSequence`, `setStatusHook`, `startDisposalOf`, `disposeTail`). The
prototype cannot defer the owner's terminal status for a background member;
the child-transition helper of spec 02 §6.1 can.

### 3.12 Keyed resources (R14)

- **R14.1 `keyedResource(options)`.** It constructs an `AsyncResourceVM<T>`
  with:

  - the name `options.name`, or `<owner name>:resource`, and the hint `""`;
  - the owner's hub and dispatcher;
  - `options.retention` and `options.cleanupValue`;
  - the loader `(signal) => options.load(startKey, signal)`, where `startKey`
    is the value of `key()` read untracked when that load starts. When `key()`
    throws there, that load fails with the error, as any loader failure does,
    and the resource enters Error (spec 23 §7) *(new in this proposal)*.

  It registers the resource as a member (R11.1), installs a keyed driver for
  it, and returns the resource. The resource is disposed as a member.

- **R14.2 `followKey(resource, options)`.** It installs a keyed driver for a
  resource that already exists: a member, or `this` when the VM is itself an
  `AsyncResourceVM` subclass, which only TypeScript and Python allow (C# seals
  the class, Swift makes it final, and Rust has no subclasses). The resource's
  loader reads its own inputs. The call returns a handle (R12.10).

- **R14.3 Driver state.** A keyed driver is a constructed-kind reaction (R12.1)
  with this state:

  - `startedKey`: the key of the last load that entered Loading, whoever
    started it. A `keyedResource` driver takes it from the loader, which knows
    the exact key of the load. A `followKey` driver reads `key()` untracked when
    the resource enters Loading. `startedKey` starts unset, and an unset
    `startedKey` differs from every key. A driver installed on a resource that
    is not Idle therefore starts a reload at its first enable (rule 1).
  - `outdated`: false at first. Every entry of the resource into Loading clears
    it, whoever started the load.
  - "Started before": the resource has entered Loading at least once, or it
    was not Idle when the driver was installed. R14.6 can change this
    meaning.
  - The effective enable E: true when the driver is active, `enabled()`
    returns true (by default it always does), and `key()` has returned a key at
    least once. A throwing `enabled()` reads as false. The driver evaluates
    `key()` and `enabled()` in its own evaluation frame.

- **R14.4 Rules.**

  1. When E turns true, also at the driver's start: when the resource has not
     started before, the driver starts a load only when `autoLoad` is true.
     Otherwise it starts one when `outdated` is set, when `key()` differs from
     `startedKey` by `equals`, or when the state is Error (see `retryOnEnable`,
     R14.6).
  1. While E stays true: when `key()` differs from `startedKey` by `equals` and
     the resource has started before, the driver starts a load. A load in
     flight is superseded; the latest start wins (spec 23 §6).
  1. When E turns false, also at the driver's stop (R13.2 step 3, R13.3 step
     2): when a load is in flight and `cancelWhenDisabled` is true (the
     default), the driver calls `cancel()` and sets `outdated` (see
     `resumeCancelledFirstLoad`, R14.6).
  1. While E is false, a key change is not remembered: rule 1 compares `key()`
     with `startedKey`. Re-enabling never reloads data that is current for its
     key. An owner that wants a refresh on every re-enable writes it:
     `reaction(() => enabled(), (on) => on && void resource.reload())`. An owner
     that marks data stale makes `key()` read a version signal and bumps it.
  1. To start a load, the driver calls `load()` when the state is Idle and
     `reload()` otherwise. Starting a load clears `outdated`. The driver
     observes the intent's outcome (R14.7). The table after this list gives
     the call of each flavor.
  1. A throwing `key()` keeps the previous key. The error is reported on the
     stream-fed route once per transition into error; the same holds for a
     throwing `enabled()`.

How a driver starts an intent (rule 5) and routes an unexpected failure of it
(R14.7). Each flavor does this through the internal entry of `AsyncResourceVM`
that phase 7 adds (§7.1):

| Flavor     | Start                                                                                                                                                                                 | Unexpected failure                                                                                                           |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| TypeScript | call `load()` or `reload()` and attach a rejection handler                                                                                                                            | the rejection goes to `loadCommand.errors` or `reloadCommand.errors`                                                         |
| C#         | start `LoadAsync()` or `ReloadAsync()` without awaiting it                                                                                                                            | a continuation sends a fault, not a cancellation, to `LoadCommand.Errors` or `ReloadCommand.Errors`                          |
| Python     | schedule the `load()` or `reload()` coroutine as `AsyncRelayCommand.execute()` does: on the running loop, or on the VMx background loop of `vmx/_asyncio_runner.py` when no loop runs | a failure, not a cancellation, goes to `load_command.errors` or `reload_command.errors`                                      |
| Swift      | `Task { await resource.load() }`, or `reload()`                                                                                                                                       | none: Swift intents cannot fail                                                                                              |
| Rust       | `load_async()` or `reload_async()`                                                                                                                                                    | a watcher thread joins the handle and sends an `Err` to `load_command().error_stream()` or `reload_command().error_stream()` |

- **R14.5 The resource does not change.** The resource keeps spec 23: it never
  loads at construct or cancels at destruct by itself (ADR-0100 §2.7, §4.6).
  The coupling is a driver that the owner declares. `autoLoad` defaults to
  false, so the first load stays on demand (spec 23 §1).

- **R14.6 Policy options.** Two options cover owners whose rules differ from the
  defaults:

  - `retryOnEnable` (default true). With false, rule 1 does not start a load
    only because the state is Error. An Error then stays until a key change, an
    `outdated` mark or an explicit reload.
  - `resumeCancelledFirstLoad` (default true). With false, a first load that
    rule 3 cancels stays on demand. The cancellation returns the resource to
    Idle (spec 23 §7), rule 3 sets no `outdated` mark, and the driver treats
    the resource again as one that has not started before (rules 1 and 2)
    until a load enters Loading. Re-enabling or a key change then starts no
    load unless `autoLoad` is true.

- **R14.7 Error route.** A loader failure does not reject the intent (spec 23
  §7), so the rejection of an intent that the driver started is an unexpected
  failure, for example a failing state observer. The driver reports it through
  the resource's own error channel: the `errors` channel of the resource's
  `loadCommand` when the driver called `load()`, and of its `reloadCommand` when
  it called `reload()`, as the fire-and-forget path of spec 04 §10.4 does (the
  table after R14.4 names the channel of each flavor). The rejection never
  reaches the stream-fed route. A rejection after the resource's disposal is
  dropped. A Swift intent cannot fail, so Swift has no such case.

Reference code: `prototype/src/reactions.ts` (`KeyedDriver`),
`prototype/src/helpers.ts` (`keyedResource`, `followKey`). The prototype
predates R14.6 and R14.7: it has no policy options, and it reports a rejected
intent on the stream-fed route.

### 3.13 Native nodes and `read` (R15)

- **R15.1 Native nodes.** Every VMx library property that announces its changes
  on a library channel is a native node. A read of it inside a frame is tracked
  like a read of state. Its public surface and its announcements do not change.
  The library commits each native node at its publication point (R15.2). The
  rule decides. The table after this list names every such property known when
  this was written, by its TypeScript name; the other flavors map the names by
  ADR-0006. An implementation that finds another such property makes it a
  native node and adds it to the table of chapter 24.

  - *Storage (new in this proposal).* A native node is created lazily, the
    first time a frame reads that property of that instance. It is kept in a
    per-instance table keyed by the property name.
  - A commit at the publication point looks the node up and does nothing when
    none exists, so a property that no frame read costs one lookup.
  - The table holds no strong reference to dependents (R17.2). A VM drops it
    at its graph release (R17.1). A library object that is not a VM (an
    `ExpandableState`, a command, a collection, a `FormVM`) drops it when it is
    disposed.

| Class                                                                                                                      | Native nodes                                                                                                                                                   | Publication point                                                                     |
| -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| every VM                                                                                                                   | `status`, `isConstructed`                                                                                                                                      | the status transition                                                                 |
| every VM                                                                                                                   | `isCurrent`                                                                                                                                                    | the helper                                                                            |
| `ComponentVMOf`, `ReadonlyComponentVMOf`                                                                                   | `model`, `modeledHint`                                                                                                                                         | the helper, in the model assignment or the explicit republish                         |
| `CompositeVM`, `CompositeVMOf`                                                                                             | `current`                                                                                                                                                      | the helper                                                                            |
| `CompositeVM`, `CompositeVMOf`, `GroupVM`                                                                                  | `count`, iteration, `at()` and `snapshot()`                                                                                                                    | the local collection-change emission, which comes before the hub collection message   |
| `HierarchicalVM`                                                                                                           | `children`, iteration, `parent`, `depth`, `isRoot`, `isLeaf`, `isFirst`, `isLast`, `path`                                                                      | the local structure-change emission                                                   |
| `AggregateVM1` to `AggregateVM6`                                                                                           | `component1` to `component6`                                                                                                                                   | the helper                                                                            |
| `AsyncResourceVM`                                                                                                          | `state`                                                                                                                                                        | the helper                                                                            |
| `ExpandableState`                                                                                                          | `isExpanded`                                                                                                                                                   | `expand()`, `collapse()` and `toggleExpansion()`, before `isExpandedChanged` delivers |
| `DiscriminatorVM`                                                                                                          | `activeKey`, `modalDepth`                                                                                                                                      | before `activeChanged` delivers                                                       |
| `FormVM`                                                                                                                   | `model`, `isDirty`, `errors`, `isValid`                                                                                                                        | before the form's own change messages deliver                                         |
| `DerivedProperty`                                                                                                          | `value`                                                                                                                                                        | before `valueChanged` delivers                                                        |
| `SearchableState`                                                                                                          | `searchTerm` (`filtered` is a stream, not a node)                                                                                                              | the term change, before the recompute delivers                                        |
| `PagedComposition`                                                                                                         | `pageSize`, `currentPageIndex`, `pageCount`, `isPagingEnabled`, `items`, `count`                                                                               | its `propertyChanged` publications                                                    |
| `TokenPagedComposition`                                                                                                    | `items`, `currentToken`, `hasMore`                                                                                                                             | its `collectionChanged` and `propertyChanged` publications                            |
| `ServicedObservableCollection`, `KeyedServicedObservableCollection`, `ObservableList`, `ObservableDictionary` (chapter 21) | `length` (the dictionary: `size`), iteration and item access (`at()`, `get()`, `has()`, `toArray()`, `snapshot()`), the dictionary's `keys1` and `keys2` views | the local change emission                                                             |
| `AsyncRelayCommand`                                                                                                        | `isExecuting`                                                                                                                                                  | the raise, before its listeners run                                                   |
| every command                                                                                                              | the result of `canExecute()`                                                                                                                                   | the raise, before its listeners run (R10.7)                                           |

`name`, `hint`, `type` and `hub` never change and are not nodes. For R19.2,
reads of the model and modeled hint of a `ReadonlyComponentVMOf` and of the
model of a `HierarchicalVM` are exempt: their reference never changes (spec 05
§4). A getter over model state that an explicit republish (spec 05 §3.3)
announces must be registered, because the exemption hides it from the probe.

- **R15.2 State first.** The library commits the state that a delivery announces
  before it delivers (spec 03 §3.6 rule 3), and this extends to derived values:

  - A library publication commits the native nodes that it publishes before it
    delivers anything. Committing marks the dependents, so a hub observer or a
    local observer of the library's own message, in any subscription order,
    reads a computed over the new value fresh: the read brings it up to date
    (R3.9).
  - A status transition commits `status`, and `isConstructed` when it changes,
    before the status is assigned and published; no user code runs in between.
  - A library publication holds the drain. The entries that user code queues
    while the library delivers its own messages (an observer that writes) are
    delivered after the publication returns. Dependents are therefore announced
    after the library's own hub message and local emission.
  - A library mutation (a container or collection change, a selection change, a
    model assignment, a resource intent, an expansion change, a page move, a
    search, a discriminator or form change) is one write of its native nodes:
    their settle runs once, when the mutation returns. A selection move (the
    old child's `isCurrent`, the new child's `isCurrent`, the container's
    `current`) therefore announces a computed over them once, or not at all
    when its value did not change.
  - A write that user code makes during a library mutation is its own write: it
    settles at once, together with the native commits made before it.
  - A lifecycle operation is one write per status transition. A command's
    `execute` is no library write: its task's writes settle as they happen.

- **R15.3 `read(source, name)`.** It returns `source[name]`. Inside a frame it
  also records a dependency:

  - when `source` publishes `name` (a state, computed or native node), on that
    node;
  - otherwise, when `source` is a VM, on the announcement node of (`source`,
    `name`). Every emission of `name` on the VM's VM-local property-change
    surface (spec 05 §2.1) bumps the node as one write. This includes the
    graph's own announcement of a name that `source` registered after the
    dependency was taken (§6, question 1);
  - otherwise, for a plain object, `read` raises the usage error.

  An announcement node is released when its stream completes (a disposed VM),
  so no frame keeps a disposed source reachable through it.

- **R15.4 Migration bridge.** `read()` lets a reactive VM follow a VM that still
  notifies by hand. Once that VM registers the name, the same call tracks the
  node.

- **R15.5 The prototype's stand-in (informative).** The prototype runs on the
  unchanged VMx 3.30.0. It implements the native nodes as announcement nodes
  over the library's change streams, with a `tracked()` helper and wrappers
  installed at import time. A VMx implementation tracks the built-ins natively
  and needs neither.

Reference code: `prototype/src/interop.ts` (`publication`, announcement nodes),
`prototype/src/bridge.ts` (`read`, `activate`, `explain`),
`prototype/src/library.ts` (the import-time stand-ins).

### 3.14 Errors (R16)

- **R16.1 Error state.** A computed or memo whose evaluation throws enters error
  state. The error is never memoized: every read evaluates the node again and
  rethrows while it still fails. The reads made before the throw stay its
  dependencies. For a published node, the change into and out of error state
  is announced (R6.5).
- **R16.2 Error equality.** Two errors are equal when they are the same value,
  or when they have the same type and the same message: in TypeScript the same
  prototype, `name` and `message`; in C# the same exception type and `Message`;
  in Python the same type and `args`; in Swift the same type and
  `String(describing:)`; in Rust the same error variant and `Display` text, or
  for a panic the same payload text. A change from an error to a different
  error is a change: it is announced, it runs the reactions again and raises the
  commands that read the node. A computed that fails with the same error on
  every evaluation keeps one error state and is not announced again.
- **R16.3 Reports.** Each change into error state, and each change to a
  different error, is reported once on the stream-fed route by the settle that
  finds it. A throw on a direct read outside a settle goes to the reader and is
  not reported. A throwing baseline leaves an error node, with no report and no
  announcement.
- **R16.4 Predicates.** A throwing predicate makes `canExecute()` false and
  keeps the reads it made (spec 04 §2, R10.4).
- **R16.5 Reaction failures.** An effect run after the first, a reaction select
  or handler, or a keyed-driver selector that throws is reported on the
  stream-fed route. The reaction stays active with the reads it made. For a
  reaction, the reference value is updated before the handler runs, so a
  failing handler does not loop.
- **R16.6 Start failures.** A setup, an effect's first run or an immediate
  handler that throws during a construct fails the construct (R13.1 step 5).
  While the reaction scope is open, the error propagates to the registration
  call (R12.12).
- **R16.7 Writes in evaluation frames.** A write, a registration, `change()`,
  `invalidate`, `member()`, a reaction-handle call, a lifecycle call or a
  library mutation inside an evaluation frame throws `ReactiveWriteError` at the
  call, also in production. Nothing is applied, and the frame's own rule then
  applies: a computed enters error state, and a predicate reads as false. A
  library publication inside an evaluation frame (a getter that calls the
  helper) still delivers its messages but commits no native node; the
  `ReactiveWriteError` goes to the stream-fed route.
  - Rust *(new in this proposal)*. Several calls return plain values
    (`signal`, `memo`, `effect`, `reaction`, `while_constructed`,
    `relay_command`, `follow_key`), and a closure can ignore an `Err`. So a
    write, a registration or a handle call inside an evaluation frame marks
    the running frame failed with `VmxError::ReactiveWrite`. A fallible call
    also returns that `Err`; an infallible call returns an inert value (a
    released signal or memo, an inert handle, a disposed command).
  - The frame ends in error state whatever the closure returns. `get` then
    panics with that error's text, and `try_get` returns
    `Err(VmxError::ReactiveWrite(..))` (`Err(VmxError::ReactiveCycle(..))`
    for a cycle). A predicate frame that is marked failed reads as false.
  - An equality frame (R6.10) is the exception: it records nothing to fail,
    so the `Err` of the call is the only effect, and the equality's own result
    decides the write (`RSTATE-039`).
- **R16.8 Cycles.** A node read during its own evaluation throws
  `ReactiveCycleError` from the read, and the evaluation of that node fails
  with it.
  - The reader that closes the cycle records its edge before the error is
    thrown, so every node of the cycle recovers, and is announced, when the
    cycle opens.
  - A cycle cannot be hidden: the evaluation of the node that was read again
    fails with the cycle error even when its getter, or a library call inside it
    such as a command predicate, caught the error.
  - A plain getter (a registered computed before activation, or a computed of a
    disposed VM that was never evaluated) that is read during its own
    evaluation also throws `ReactiveCycleError`.
  - Swift *(new in this proposal; §6 question 18)*. Computed functions cannot
    throw, so inside an evaluation a plain read that would throw
    `ReactiveError.cycle` does not trap. The read returns the node's last value
    and marks the running frame failed with the cycle error; a read that closes
    a cycle marks every frame of the cycle failed. A frame that is marked
    failed ends in error state when its function returns, and the value that
    the function returned is discarded. Such a read traps only when the node
    has no last value (a plain getter, or a node that was never evaluated).
    Outside every evaluation, a plain read of a node in error state traps;
    `Reactive.read` (§4.5) throws the error instead.
- **R16.9 Overflow.** A drain over the development bound throws
  `ReactiveOverflowError` (R9.6).
- **R16.10 Observers.** A failing hub observer is swallowed by the hub (spec 03
  §3.4), and the drain continues. For a failing VM-local observer and a failing
  `CanExecuteChanged` handler, the flavors differ:
  - TypeScript, Swift and Rust: the failure goes to the stream-fed route, and
    the drain continues.
  - C# and Python *(the drain's part is new in this proposal)*: today's helper
    (`NotifyPropertyChanged`, `_notify_property_changed`) and
    `RaiseCanExecuteChanged` (a call-fed delivery, spec 03 §3.6 rule 5,
    ADR-0171) rethrow the first failure of a delivery to their caller. The
    drain catches each such failure and keeps delivering. When the queue is empty, it rethrows the first one from the
    call that ran the drain, which is what the caller of a hand-written setter
    sees today. A change scope's body error (R7.3) and a drain overflow (R9.6)
    take precedence over it.
- **R16.11 Equalities.** A throwing equality counts as "not equal" and is
  reported once per call (R6.10).
- **R16.12 Teardown.** A failing cleanup or teardown is isolated and swallowed
  (R12.8).

Reference code: `prototype/src/graph.ts` (`evaluate`, `cycleError`,
`readDerived`, `assertWritable`), `prototype/src/equality.ts` (`errorsEqual`),
`prototype/src/errors.ts`.

### 3.15 Disposal and retention (R17)

- **R17.1 Graph release.** The graph release (R13.3 step 7) removes every edge
  to and from V's nodes and frames: the command dependency sets, the reaction
  frames, and the announcement nodes that follow V. It drops V's references to
  getters, selects, effect functions and setups. V's nodes keep their last
  values for readers, and later reads record no edges (R5.6). Nodes of other
  VMs that depended on V's nodes keep their values and lose those
  dependencies.
- **R17.2 No retention.** A disposed VM is never evaluated, notified or
  scheduled again, and no node of another VM keeps it reachable. A node
  released while a frame runs is not kept by that frame. The conformance tests
  show this with the flavor's weak reference (§4.7) while the disposed VM's
  former sources keep changing.
- **R17.3 Live VMs.** A VM that is not disposed stays reachable from the
  sources it read, as it does through hub subscriptions today. An
  implementation MAY hold dependents weakly.
- **R17.4 Change-scope exception.** A VM disposed inside an open change scope
  has published Disposed by the time the scope settles, so its writes in that
  scope are not announced. Settling part of a scope at a disposal would split
  the change that the author declared.
- **R17.5 Members.** A long-lived owner does not retain the members that it
  disposed (R11.5).

Reference code: `prototype/src/vmState.ts` (`releaseGraph`),
`prototype/src/graph.ts` (`releaseNode`, `forgetFrame`).

### 3.16 Threading (R18)

These rules apply to C#, Python, Swift and Rust. TypeScript has one thread
(R18.6).

- **R18.1 One drain.** Each process has one reactive drain. A thread that writes
  outside a drain acquires the drain. A write by the drainer thread is
  re-entrant (R9.3). An open change scope holds the drain until the scope
  exits, so a write from another thread waits until then (R18.2) *(new in
  this proposal)*.
- **R18.2 Foreign writes.** A write from another thread while the drain is held
  waits for the drain and records the wait in the flavor's wait-for graph (spec
  03 §4.1, ADR-0172): the resource is the reactive drain, and its owner is the
  drainer. When that wait would close a live cycle, it is refused: the write
  commits (R6.3), appends a settle request that the drainer runs in FIFO order,
  and returns. This is a new row of the table in spec 03 §4.1.
- **R18.3 No lock around user code.** No VMx lock is held while consumer code
  runs: getters, predicates, selects, handlers, equalities, setups, cleanups
  and observers (ADR-0117). Node values and edge sets use short leaf locks.
- **R18.4 Foreign reads.** A read on a thread that does not hold the drain
  returns the value of a clean node. A dirty node is evaluated on the reading
  thread without storing the result and without recording edges for the node;
  a frame that encloses the read on that thread still records its reads. This
  is the refused recompute-gate rule of ADR-0209.
- **R18.5 Deliveries on the drainer.** Announcements, raises and reaction runs
  happen on the drainer thread. The helper keeps the foreground rules of spec
  11 §3. VMx stays thread-aware but not thread-bound (spec 11).
- **R18.6 TypeScript.** TypeScript is single-threaded and needs none of R18.1
  to R18.5 and R18.7 to R18.9. A write in a later job (after an `await`, in a
  timer or a promise callback) is an ordinary top-level write: it settles and
  drains before it returns.
- **R18.7 Frames are per thread** *(new in this proposal; §6 question 16)*. The
  stack of running frames, and the open change scope, are per-thread values:
  C# `[ThreadStatic]`, Python `threading.local`, Swift a thread-local value,
  Rust `thread_local!`. They are not async-context values (C# `AsyncLocal`,
  Python `contextvars.ContextVar`, a Swift task-local), because a context value
  flows into the tasks and continuations that a frame starts and would carry a
  closed frame or an open scope past an `await`. Frames are synchronous: a
  frame opens and closes on one thread without suspension, and work that it
  starts asynchronously records nothing into it. A library operation or a
  delivery saves the current frame, clears it and restores it (R5.7, R5.8).
  Code that runs inline on a thread with an open frame, such as a
  continuation that a frame's call-out resumes synchronously (a C#
  `TaskCompletionSource` completed without `RunContinuationsAsynchronously`,
  or a synchronous Swift resumption), runs with the frame cleared: VMx clears
  the frame around every library call-out (R5.7, R5.8), and evaluations must
  not complete awaitables (the declaration rules of §4.2). This departs from
  the prototype's design, which kept the frame in a context value (§6
  question 16).
- **R18.8 Direct sends and publications.** The producer flush (R9.8), the
  native commits and the publication hold (R15.2) run on the drainer. A direct
  send or a library publication on another thread, for a VM with queued
  announcements, waits like a foreign write (R18.2); a refused wait appends the
  send behind the queued announcements.
- **R18.9 Member list.** The removal of a disposed member (R11.5) happens under
  the owner's lifecycle lock (spec 02 §2.4), so a walk in flight sees a
  consistent list.

### 3.17 Development diagnostics (R19)

The diagnostics are off in production. In development they report misuse that
the rules cannot prevent. They never change behavior, except the drain bound of
R9.6.

- **R19.1 Staleness check.** A consumer read (outside every frame, settle and
  probe) of a clean memoized computed schedules one check of that node on a
  later task; a node has at most one pending check. The check evaluates the
  getter untracked in a probe frame (an evaluation frame that records reads but
  installs no edge). It compares the result with the memoized value by the
  node's equality, without reporting a throwing equality again, and then by
  structural equality. A difference is reported once per class and name:
  "`<Class>.<name>` changed without a tracked dependency". The structural
  equality:

  - requires the same type (TypeScript: the same prototype);
  - compares arrays and lists item by item, maps by keys (identity) and values,
    sets by members (identity), dates by time, regular expressions by source and
    flags, and other objects by their own enumerable fields;
  - compares functions by their code (TypeScript: the source text; Python: the
    code object), so a new closure built from tracked state equals the one it
    replaces;
  - is co-inductive: a pair of objects already being compared counts as equal,
    so a graph with back references terminates;
  - counts a pair at depth 32 as equal, so the check reports nothing when it
    cannot decide.

  The structural pass of each flavor *(new in this proposal; the prototype is
  TypeScript)*:

  - TypeScript: as above.
  - Python: the same runtime type; then sequences item by item, mappings by
    key, sets by members, and other objects by `vars()`; functions by their
    code object.
  - C#: the same runtime type; then `IDictionary` by key, other `IEnumerable`
    item by item, then public fields and properties by reflection; delegates
    by `Method` and `Target`.
  - Swift: the same type; `==` for `Equatable` leaves, and `Mirror` children
    otherwise.
  - Rust: no structural pass, because Rust has no reflection. R19.1 compares
    by the node's equality only. R19.8 applies only to a custom `equals`, and
    its structural check is `PartialEq`.

  Under Rust's default equality, `PartialEq`, a key difference is already a
  structural difference, so the default-equality case of R19.8 has no Rust
  case, and `RSTATE-044` skips it in Rust.

- **R19.2 Unpublished getters.** On the task after activation, each public
  getter of the VM's own classes (up to the first VMx library class) that is
  neither registered nor a library member is evaluated once in a probe frame,
  and its errors are ignored. When the probe read a node that is not exempt
  (R15.1), a report is made once per class and name: "`<Class>.<name>` reads
  reactive state but is not published". A getter whose reads are all exempt,
  such as the identity fields of a read-only model, is not reported. The probe
  needs a runtime list of getters: TypeScript, Python and C# run it; Swift and
  Rust do not.

- **R19.3 Hand-written notification.** A hand-written helper call for a
  registered name is reported once per class and name: the graph announces the
  name, and the call should be deleted.

- **R19.4 `explain`.** `explain(vm, name)` lists the nodes read by the last
  evaluation of a registered computed, as pairs of owner object and name,
  without the invalidation node (informative).

- **R19.5 Drain bound.** The bound of R9.6 is also a development diagnostic.

- **R19.6 Reactive errors in predicates.** A `ReactiveWriteError` or a
  `ReactiveCycleError` raised inside a command predicate makes the predicate
  read as false (spec 04 §2) and is reported once per class and error kind.

- **R19.7 Writes to a VM that is not activated.** A registered write on a VM
  that has registered computeds but is not activated, and that is still not
  activated one task later, is reported once per class: its computeds were not
  announced (R4.5).

- **R19.8 Equal keys.** A load that only a key difference started, while the new
  key is structurally equal to `startedKey`, is reported once per class: under
  the default equality with the advice to pass a shallow equality, and under a
  custom equality with the advice to compare the nested values. The equality
  still decides.

- **R19.9 Late state.** A state registration after activation (R3.13) is
  reported once per class.

- **R19.10 Asynchronous effects.** TypeScript: an effect that returns a promise
  is reported once per class (R12.3), with the advice to read every input
  before the first `await`, or to use `keyedResource()` or
  `asyncRelayCommand()`. The other flavors refuse such an effect (R12.3).

- **R19.11 Switch.** Unless the override of R19.13 is set, the diagnostics of a
  VM are on when its hub has development diagnostics on, the switch of the
  hub's own drain bound (spec 03 §3.3):

  - TypeScript: `MessageHubOptions.developmentDiagnostics`, on by default in
    Node development and test processes. A VM whose hub is not a `MessageHub`
    (`RecordingMessageHub`, `NullMessageHub`, a custom hub) takes the Node
    default (`NODE_ENV` is `development` or `test`);
  - C# and Swift: a `DEBUG` build of VMx;
  - Python: when `__debug__` is true;
  - Rust: `debug_assertions`.

  The bound of one drain follows the hub of the VM whose write started the
  drain.

- **R19.12 Reports and later tasks.** Each report is made once per kind, class
  and name in a process, to the flavor's diagnostic sink (§4.7). Tests can
  replace the sink and reset the "once" memory. A failing sink is ignored. A
  diagnostic that evaluates user code (R19.1, R19.2) runs on a later task,
  never inside a read or an activation. *(New in this proposal:)* a later task
  (R4.1 step 5, R19.1, R19.2, R19.7) is a zero-delay action on the process's
  diagnostics scheduler, a scheduler of spec 11 §6.1 (§4.7). It defaults to the
  flavor's real-time scheduler (TypeScript: one macrotask, `setTimeout` with no
  delay). Tests set the flavor's virtual-time scheduler and advance it. In the
  threaded flavors, the scheduled check acquires the reactive drain before it
  evaluates (R18.1), so it never runs during a settle. The diagnostics
  scheduler is a development setting, like the sink; the delayed-work
  consumers of spec 11 §6 still take their scheduler at construction.

- **R19.13 Test override** *(new in this proposal; §6 question 19)*. A
  process-wide override decides the switch for every VM and every drain when
  it is set, and R19.11 decides when it is unset: C#
  `ReactiveGraph.DevelopmentDiagnostics` (`bool?`), Python
  `vmx.reactive.set_development_diagnostics(enabled: bool | None)`, TypeScript
  `setReactiveDevelopmentDiagnostics(enabled: boolean | null)`, Swift
  `Reactive.developmentDiagnostics` (`Bool?`), Rust
  `vmx::reactive::set_development_diagnostics(Option<bool>)`. The override
  works in every build configuration: the drain bound and the reports are
  gated at run time, not compiled out. The C# CI builds and runs the
  conformance tests in the Release configuration, where `DEBUG` is off, and the
  Python, Swift and Rust test processes cannot change their build constant, so
  the conformance tests of both cases set the override. A test that sets it
  resets it afterwards.

Reference code: `prototype/src/diagnostics.ts`, `prototype/src/equality.ts`
(`structurallyEqual`), `prototype/src/vmState.ts` (`runStalenessChecks`,
`probeUnpublishedGetters`, `noteInactiveWrite`). The prototype probes every
getter that read a node; the immutable exemption of R19.2 is new. The prototype
configures its diagnostics with the prototype-only `configureReactiveDiagnostics`
and uses `setTimeout` for later tasks; the report-sink functions, the
diagnostics scheduler (R19.12) and the override (R19.13) replace both.

## 4. API per flavor

### 4.1 Placement and naming

- **Source area.** Each flavor adds a `reactive` area beside its existing
  areas: `langs/typescript/src/reactive/`, `langs/csharp/src/VMx/Reactive/`
  (namespace `VMx.Reactive`), `langs/python/src/vmx/reactive/`,
  `langs/swift/Sources/VMx/Reactive/` and `langs/rust/src/reactive.rs` (module
  `reactive`, re-exported at the crate root). The instance helpers live on the
  component base of each flavor.
- **Visibility.** The instance helpers are protected where the flavor has
  protected members: TypeScript `protected`, C# `protected`, Python a leading
  underscore. Swift and Rust make them public, as they do for `own` (spec 02
  §2.3).
- **Names.** Names follow ADR-0006: PascalCase in C#, snake_case in Python and
  Rust, camelCase in TypeScript and Swift. Announced names follow the property
  idiom of spec 03 §2.1, as every helper call does.
- **Differences beyond casing.** Each one avoids a collision or follows a
  language limit; the implementation of each flavor records its rows in the
  ADR-0009 divergence table:
  - C# names the state helper `ObservableState`, because a base member named
    `Observable` would hide the Rx `Observable` class inside every subclass. It
    names the command helpers `Command`, `CommandOf<T>` and `AsyncCommand`,
    because members named `RelayCommand` or `AsyncRelayCommand` would hide the
    command types inside every subclass.
  - C#, Swift and Rust cannot wrap an existing getter, so a computed is a node
    that the class stores and its public property reads (R3.2). In Swift the
    node is a property wrapper that takes a key path to a private getter.
  - Rust reaches the helpers through one handle, `vm.reactive()`, so their names
    cannot collide with VM methods such as the notification view-model's
    `reaction()` accessor.
  - Swift reports a misuse from a call that cannot throw with a trap
    (precondition failure), as ADR-0053 does for setters (§4.7).

### 4.2 TypeScript API

The instance helpers, `protected` on `ComponentVMBase` (from
`prototype/src/augment.ts`, where a module augmentation makes them public):

```ts
export abstract class ComponentVMBase {
  // ... existing members ...

  // State (R3.1, R3.11)
  protected observable<K extends keyof this>(
    initial: { [P in K]: this[P] },
    equals?: { [P in K]?: Equality<this[P]> },
  ): StateWriter<{ [P in K]: this[P] }>;
  protected signal<T>(initial: T, equals?: Equality<T>): Signal<T>;

  // Computed (R3.2, R3.11, R6.1, R7)
  protected computed<K extends keyof this>(...names: K[]): void;
  protected computed<K extends keyof this>(equals: { [P in K]: Equality<this[P]> }): void;
  protected memo<T>(fn: (previous: T | undefined) => T, equals?: Equality<T>): Memo<T>;
  protected invalidate<K extends keyof this>(...names: K[]): void;
  protected change<R>(fn: () => R): R;

  // Commands (R10)
  protected relayCommand(task: () => void, canExecute?: () => boolean, options?: CommandOptions): RelayCommand;
  protected relayCommandOf<T>(
    task: (parameter: T) => void,
    canExecute?: (parameter: T) => boolean,
    options?: CommandOptions,
  ): RelayCommandOf<T>;
  protected asyncRelayCommand(
    task: (signal: AbortSignal) => Promise<void>,
    canExecute?: () => boolean,
    options?: AsyncCommandOptions,
  ): AsyncRelayCommand;

  // Members and injection (R11)
  protected member<VM extends ComponentVMBase>(vm: VM): VM;
  protected member<O extends { readonly hub: IMessageHub; readonly dispatcher: IDispatcher }, VM extends ComponentVMBase>(
    ctor: new (options: O) => VM,
    options: Omit<O, "hub" | "dispatcher">,
  ): VM;

  // Reactions (R12); each returns the handle that removes the reaction (R12.10)
  protected effect(fn: () => void | (() => void)): () => void;
  protected reaction<T>(select: () => T, handler: (value: T, previous: T) => void, options?: ReactionOptions<T>): () => void;
  protected whileConstructed(setup: () => OwnedResource | void): () => void;

  // Keyed resources (R14)
  protected keyedResource<K, T>(options: KeyedResourceOptions<K, T>): AsyncResourceVM<T>;
  protected followKey<K>(resource: AsyncResourceVM<unknown>, options: FollowKeyOptions<K>): () => void;
}
```

The types and free functions, exported from `@thekaveh/vmx` (from
`prototype/src/types.ts`, with the options of R14.6):

```ts
export type Equality<T> = (a: T, b: T) => boolean;

/** Object.is; or two arrays of equal length whose items are Object.is-equal; or two plain objects
 *  (prototype Object.prototype or null) with the same own enumerable keys whose values are Object.is-equal. */
export function shallowEqual(a: unknown, b: unknown): boolean;
/** Runs fn without recording its reads in the current frame (R5.5). */
export function untracked<T>(fn: () => T): T;
/** Returns source[name] and, inside a frame, records a dependency (R15.3). */
export function read<S extends object, K extends keyof S & string>(source: S, name: K): S[K];
/** Activates vm now (R4.2 e). Idempotent; a no-op once its disposal started. */
export function activate(vm: ComponentVMBase): void;
/** Development inspection (R19.4, informative). */
export function explain(vm: ComponentVMBase, name: string): readonly ExplainEntry[];
/** Replaces the development report sink (R19.12); null restores the default, console.warn. */
export function setReactiveReportSink(sink: ((message: string) => void) | null): void;
/** Forgets which reports were made, so each can be made again (R19.12; for tests). */
export function resetReactiveReports(): void;
/** Sets the diagnostics scheduler of later tasks (R19.12); null restores the default, one macrotask. */
export function setReactiveDiagnosticsScheduler(scheduler: SchedulerLike | null): void;
/** Overrides the development switch for every VM (R19.13); null restores R19.11. */
export function setReactiveDevelopmentDiagnostics(enabled: boolean | null): void;

export class ReactiveWriteError extends Error {}    // R16.7; name "ReactiveWriteError"
export class ReactiveCycleError extends Error {}    // R16.8; name "ReactiveCycleError"
export class ReactiveOverflowError extends Error {} // R9.6; name "ReactiveOverflowError"

export interface Signal<T> {
  value: T;          // tracked read; an assignment is one write
  peek(): T;         // untracked read
}
export interface Memo<T> {
  readonly value: T; // tracked; brings the memo up to date
  peek(): T;         // brings it up to date; records nothing
  invalidate(): void; // one write that makes the memo dirty
}
/** Writes several registered state keys as one write (R3.1). */
export type StateWriter<S> = (patch: Partial<S>) => void;

export interface CommandOptions {
  readonly triggers?: readonly Observable<unknown>[]; // inputs outside the graph (R10.6)
}
export interface AsyncCommandOptions extends CommandOptions {
  readonly throwOnCancel?: boolean;
}
export interface ReactionOptions<T> {
  readonly equals?: Equality<T>; // default Object.is
  readonly immediate?: boolean;  // default false (R12.4)
  readonly alive?: boolean;      // default false (R12.5)
}
export interface FollowKeyOptions<K> {
  readonly key: () => K;                       // tracked
  readonly enabled?: () => boolean;            // tracked; default () => true
  readonly autoLoad?: boolean;                 // default false (R14.5)
  readonly cancelWhenDisabled?: boolean;       // default true (R14.4 rule 3)
  readonly retryOnEnable?: boolean;            // default true (R14.6)
  readonly resumeCancelledFirstLoad?: boolean; // default true (R14.6)
  readonly equals?: Equality<K>;               // default Object.is
}
export interface KeyedResourceOptions<K, T> extends FollowKeyOptions<K> {
  readonly name?: string;                            // default `${owner.name}:resource`
  readonly load: (key: K, signal: AbortSignal) => Promise<T>;
  readonly retention?: AsyncResourceRetention;       // default DiscardPrevious (spec 23 §8)
  readonly cleanupValue?: (value: T) => void;
}
export interface ExplainEntry {
  readonly owner: object;
  readonly name: string;
}
```

New in this proposal, not in the prototype: `setReactiveReportSink`,
`resetReactiveReports`, `setReactiveDiagnosticsScheduler` and
`setReactiveDevelopmentDiagnostics`. They replace the prototype-only
`configureReactiveDiagnostics`. The same holds for the matching members of the
other flavors (§4.3 to §4.6).

Declaration rules:

- Public state is a `declare` field: `declare readonly x: T;` when views only
  read it, or `declare x: T;` when `vm.x = v` and `this.x = v` also write. The
  `declare` keyword is needed under `useDefineForClassFields`; without it a
  class field replaces the accessor, and activation reports it (R3.12). tsc,
  esbuild, swc and oxc emit nothing for a `declare` field; Babel needs
  `allowDeclareFields`.
- `observable({...})` infers its keys and checks each initial value against the
  declared type, including `null` for `T | null`. The writer rejects unknown
  keys and wrong types at compile time. `member(Type, options)` rejects `hub`,
  `dispatcher` and missing options. `read()` checks the name. Views cannot
  assign `declare readonly` state.
- Published computeds are ordinary getters. Registration changes neither their
  code nor their comments.
- Private reactive values are `#private` fields that hold a `Signal` or a
  `Memo`. A plain `#field` that changes after construction must not be read by
  a registered computed; R19.1 reports such a read.
- No decorator and no static block is needed.
- Getters, equalities, predicates and selects must be free of side effects:
  the diagnostics evaluate getters again on a later task (R19.1). They also
  must not complete awaitables (resolve a promise, complete a task source), so
  that no continuation runs inside their frame (R18.7).

### 4.3 C# API

Protected members of `ComponentVMBase` (namespace `VMx.Components`); the types
are in `VMx.Reactive`. `ForwardingComponentVM<M>` and
`ForwardingCompositeVM<VM>` (`VMx.Forwarding`) implement `IComponentVM<M>`
and `ICompositeVM<VM>` directly instead of deriving from `ComponentVMBase`.
They get the same protected members, which delegate to the reactive state of
the canonical ownership identity (ADR-0124), so R3.8 holds in C#:

```csharp
// State (R3.1, R3.11)
protected State<T> ObservableState<T>(string name, T initial, IEqualityComparer<T>? comparer = null);
protected Signal<T> Signal<T>(T initial, IEqualityComparer<T>? comparer = null);

// Computed (R3.2, R3.11, R6.1, R7)
protected Computed<T> Computed<T>(string name, Func<T> evaluate, IEqualityComparer<T>? comparer = null);
protected Memo<T> Memo<T>(Func<T?, T> evaluate, IEqualityComparer<T>? comparer = null);
protected void Invalidate(params string[] names);
protected void Change(Action body);
protected TResult Change<TResult>(Func<TResult> body);

// Commands (R10)
protected RelayCommand Command(Action task, Func<bool>? canExecute = null, CommandOptions? options = null);
protected RelayCommand<T> CommandOf<T>(Action<T> task, Func<T, bool>? canExecute = null, CommandOptions? options = null);
protected AsyncRelayCommand AsyncCommand(
    Func<CancellationToken, Task> task, Func<bool>? canExecute = null, AsyncCommandOptions? options = null);

// Members and injection (R11)
protected TVM Member<TVM>(TVM vm) where TVM : ComponentVMBase;
protected TVM Member<TVM>(Func<IMessageHub, IDispatcher, TVM> create) where TVM : ComponentVMBase;

// Reactions (R12); each returns the handle; Dispose() removes the reaction (R12.10)
protected IDisposable Effect(Action run);
protected IDisposable Effect(Func<Action?> run);                 // the returned action is the cleanup
protected IDisposable Reaction<T>(Func<T> select, Action<T, T> handler, ReactionOptions<T>? options = null);
protected IDisposable WhileConstructed(Func<IDisposable?> setup);

// Keyed resources (R14)
protected AsyncResourceVM<T> KeyedResource<TKey, T>(KeyedResourceOptions<TKey, T> options);
protected IDisposable FollowKey<TKey, T>(AsyncResourceVM<T> resource, FollowKeyOptions<TKey> options);
```

| Type in `VMx.Reactive`                                                          | Members                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `State<T>` (sealed)                                                             | `T Value { get; set; }`: the getter is a tracked read; the setter is one write. `T Peek()`.                                                                                                                                                                                                                                                                                                                                                                                             |
| `Signal<T>` (sealed)                                                            | as `State<T>`, not published.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `Computed<T>` (sealed)                                                          | `T Value { get; }`: tracked, memoized after activation (R3.9). `T Peek()`.                                                                                                                                                                                                                                                                                                                                                                                                              |
| `Memo<T>` (sealed)                                                              | `T Value { get; }`, `T Peek()`, `void Invalidate()`.                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `CommandOptions` (record)                                                       | `IReadOnlyList<IObservable<Unit>> Triggers { get; init; }`, empty by default.                                                                                                                                                                                                                                                                                                                                                                                                           |
| `AsyncCommandOptions` (sealed record, `: CommandOptions`)                       | `bool ThrowOnCancel { get; init; }`.                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `ReactionOptions<T>` (sealed record)                                            | `IEqualityComparer<T>? Comparer`, `bool Immediate`, `bool Alive`, each `{ get; init; }`.                                                                                                                                                                                                                                                                                                                                                                                                |
| `FollowKeyOptions<TKey>` (record)                                               | constructor `(Func<TKey> Key)`; `Func<bool>? Enabled`, `bool AutoLoad`, `bool CancelWhenDisabled = true`, `bool RetryOnEnable = true`, `bool ResumeCancelledFirstLoad = true`, `IEqualityComparer<TKey>? Comparer`.                                                                                                                                                                                                                                                                     |
| `KeyedResourceOptions<TKey, T>` (sealed record, `: FollowKeyOptions<TKey>`)     | constructor `(Func<TKey> Key, Func<TKey, CancellationToken, Task<T>> Load)`; `string? Name`, `AsyncResourceRetention Retention`, `Action<T>? CleanupValue`.                                                                                                                                                                                                                                                                                                                             |
| `ReactiveGraph` (static)                                                        | `T Untracked<T>(Func<T> read)`, `void Untracked(Action read)`, `T Read<T>(object source, string name, Func<T> get)`, `void Activate(IComponentVM vm)`, `IReadOnlyList<ExplainEntry> Explain(IComponentVM vm, string name)`, `event Action<string>? Report` and `void ResetReports()` (R19.12), `IScheduler DiagnosticsScheduler { get; set; }` (R19.12; default `DefaultScheduler.Instance`), `bool? DevelopmentDiagnostics { get; set; }` (R19.13; `null` = the `DEBUG` build switch). |
| `ExplainEntry` (sealed record)                                                  | `ExplainEntry(object Owner, string Name)`.                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `SequenceEqualityComparer<TItem>` (sealed)                                      | `static SequenceEqualityComparer<TItem> Instance`; compares two `IReadOnlyList<TItem>` item by item with `EqualityComparer<TItem>.Default`. The C# shallow equality.                                                                                                                                                                                                                                                                                                                    |
| `ReactiveWriteException`, `ReactiveCycleException`, `ReactiveOverflowException` | derive from `InvalidOperationException`.                                                                                                                                                                                                                                                                                                                                                                                                                                                |

- A class reads its nodes through expression-bodied properties:
  `public bool Collapsed => _collapsed.Value;`. The `name` argument is
  `nameof(Collapsed)`, so announcements use the PascalCase property name.
- `Read` takes the getter because C# cannot read a property by name without
  reflection: `ReactiveGraph.Read(other, nameof(Other.Title), () => other.Title)`.
- The first `PropertyChanged +=` subscription is activation trigger (b).
- `Effect` and `Reaction` refuse an async lambda with `ArgumentException`
  (R12.3): `run.Method` or `handler.Method` carries
  `AsyncStateMachineAttribute`.
- A source generator MAY later emit the node and the property from
  `[Observable] private bool _isEmpty;`. The base form needs none (#399 gates
  generators).

### 4.4 Python API

Protected methods of `_ComponentVMBase` (`vmx.components.base`); the types and
functions are in `vmx.reactive`:

```python
# State (R3.1, R3.11)
def _observable(self, equals: Mapping[str, Callable[[Any, Any], bool]] | None = None, /,
                **initial: Any) -> StateWriter: ...
def _signal(self, initial: T, equals: Callable[[T, T], bool] | None = None) -> Signal[T]: ...

# Computed (R3.2, R3.11, R6.1, R7)
def _computed(self, *names: str, **equals: Callable[[Any, Any], bool]) -> None: ...
def _memo(self, fn: Callable[[T | None], T], equals: Callable[[T, T], bool] | None = None) -> Memo[T]: ...
def _invalidate(self, *names: str) -> None: ...
def _change(self) -> AbstractContextManager[None]: ...          # with self._change(): ...

# Commands (R10)
def _relay_command(self, task: Callable[[], None], can_execute: Callable[[], bool] | None = None, *,
                   triggers: Sequence[rx.Observable[object]] = ()) -> RelayCommand: ...
def _relay_command_of(self, task: Callable[[T | None], None],
                      can_execute: Callable[[T | None], bool] | None = None, *,
                      triggers: Sequence[rx.Observable[object]] = ()) -> RelayCommandOf[T]: ...
def _async_relay_command(self, task: Callable[[], Awaitable[None]],
                         can_execute: Callable[[], bool] | None = None, *,
                         triggers: Sequence[rx.Observable[object]] = (),
                         throw_on_cancel: bool = False) -> AsyncRelayCommand: ...

# Members and injection (R11)
@overload
def _member(self, vm: VMT, /) -> VMT: ...
@overload
def _member(self, cls: type[VMT], /, **options: Any) -> VMT: ...  # cls(**options, hub=..., dispatcher=...)

# Reactions (R12); each returns the handle, a zero-argument callable (R12.10)
def _effect(self, fn: Callable[[], Callable[[], None] | None]) -> Callable[[], None]: ...
def _reaction(self, select: Callable[[], T], handler: Callable[[T, T], None], *,
              equals: Callable[[T, T], bool] | None = None, immediate: bool = False,
              alive: bool = False) -> Callable[[], None]: ...
def _while_constructed(self, setup: Callable[[], OwnedResource | None]) -> Callable[[], None]: ...

# Keyed resources (R14)
def _keyed_resource(self, *, key: Callable[[], K], load: Callable[[K], Awaitable[T]],
                    enabled: Callable[[], bool] | None = None, auto_load: bool = False,
                    cancel_when_disabled: bool = True, retry_on_enable: bool = True,
                    resume_cancelled_first_load: bool = True,
                    equals: Callable[[K, K], bool] | None = None, name: str | None = None,
                    retention: AsyncResourceRetention = AsyncResourceRetention.DISCARD_PREVIOUS,
                    cleanup_value: Callable[[T], None] | None = None) -> AsyncResourceVM[T]: ...
def _follow_key(self, resource: AsyncResourceVM[Any], *, key: Callable[[], K],
                enabled: Callable[[], bool] | None = None, auto_load: bool = False,
                cancel_when_disabled: bool = True, retry_on_enable: bool = True,
                resume_cancelled_first_load: bool = True,
                equals: Callable[[K, K], bool] | None = None) -> Callable[[], None]: ...
```

| Name in `vmx.reactive`                                                     | Shape                                                                               |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `Signal[T]`                                                                | property `value` (get: tracked; set: one write), `peek() -> T`.                     |
| `Memo[T]`                                                                  | property `value` (get), `peek() -> T`, `invalidate() -> None`.                      |
| `StateWriter`                                                              | protocol: `__call__(self, **patch: Any) -> None`.                                   |
| `untracked(fn)`, `read(source, name)`, `activate(vm)`, `explain(vm, name)` | as in TypeScript; `explain` returns `tuple[ExplainEntry, ...]`.                     |
| `ExplainEntry`                                                             | `class ExplainEntry(NamedTuple)` with `owner: object` and `name: str`.              |
| `set_report_sink(sink)`, `reset_reports()`                                 | R19.12; the default sink logs with `logging.getLogger("vmx.reactive").warning`.     |
| `set_diagnostics_scheduler(scheduler: SchedulerBase \| None)`              | R19.12; `None` restores the default, `TimeoutScheduler()`.                          |
| `set_development_diagnostics(enabled: bool \| None)`                       | R19.13; `None` restores R19.11 (`__debug__`).                                       |
| `OwnedResource`                                                            | the shapes of spec 02 §2.3: a zero-argument callable or an object with `dispose()`. |
| `ReactiveWriteError`, `ReactiveCycleError`, `ReactiveOverflowError`        | subclasses of `RuntimeError`.                                                       |

- State: a class-body annotation declares the type for mypy (`is_empty: bool`),
  and `self._observable(is_empty=..., title=...)` registers it. At the first
  registration, the base installs one data descriptor per name on the
  instance's class. The descriptor reads the instance's node; assignment raises
  `AttributeError`, so writes go through the writer. For an instance that did
  not register the name, the descriptor delegates to the attribute that it
  replaced.
- Computed: `self._computed("collapsed", "toggle_text")` wraps `@property`
  getters; `self._computed(items=shallow_equal_items)` passes an equality. The
  default equality is `==`, which already compares lists and dicts item by
  item, so Python ships no shallow equality.
- Python's `AsyncResourceVM` loader takes no cancellation argument (asyncio
  cancels the task), so `load` receives only the key.
- `_effect` and `_reaction` run synchronous functions. An effect function or a
  reaction handler that returns an awaitable raises the usage error at that
  call, and the base closes a returned coroutine without running it (R12.3).

### 4.5 Swift API

Public members of `ComponentVMBase` (in
`langs/swift/Sources/VMx/Lifecycle/ComponentVMBase.swift`), plus two property
wrappers. The wrappers have no `projectedValue`: a projected value takes the
access level of the wrapped property, so `@Observed public private(set) var x`
would publish a public `$x` with a write path, against ADR-0234 §2.2 rule 1.
The throwing forms are static members of `Reactive` that take a key path to the
wrapper's private storage (`\SectionVM._isEmpty`), which only the declaring
class can form.

```swift
// State (R3.1): a property wrapper class; see the notes below
@propertyWrapper public final class Observed<Value> {
    public init(wrappedValue: Value) where Value: Equatable
    public init(wrappedValue: Value, equals: @escaping (Value, Value) -> Bool)
    @available(*, unavailable, message: "accessed through the enclosing view-model")
    public var wrappedValue: Value { get { fatalError() } set { fatalError() } }
    public static subscript<VM: ComponentVMBase>(
        _enclosingInstance vm: VM,
        wrapped wrappedKeyPath: ReferenceWritableKeyPath<VM, Value>,
        storage storageKeyPath: ReferenceWritableKeyPath<VM, Observed<Value>>
    ) -> Value { get set }   // get: tracked read; set: one write
}

// Computed (R3.2): a property wrapper class over a function of the view-model
@propertyWrapper public final class Computed<Value> {
    public init<VM: ComponentVMBase>(_ evaluate: @escaping (VM) -> Value) where Value: Equatable
    public init<VM: ComponentVMBase>(_ evaluate: @escaping (VM) -> Value, equals: @escaping (Value, Value) -> Bool)
    @available(*, unavailable, message: "accessed through the enclosing view-model")
    public var wrappedValue: Value { get { fatalError() } set { fatalError() } }
    public static subscript<VM: ComponentVMBase>(
        _enclosingInstance vm: VM,
        wrapped wrappedKeyPath: ReferenceWritableKeyPath<VM, Value>,
        storage storageKeyPath: ReferenceWritableKeyPath<VM, Computed<Value>>
    ) -> Value { get set }   // get: tracked, memoized after activation; set: traps
}

extension Reactive {
    // The throwing forms (R16.7, R16.8): try Reactive.set(\SectionVM._isEmpty, on: self, to: true)
    public static func set<VM: ComponentVMBase, Value>(
        _ storage: ReferenceWritableKeyPath<VM, Observed<Value>>, on vm: VM, to value: Value) throws
    public static func read<VM: ComponentVMBase, Value>(
        _ storage: KeyPath<VM, Computed<Value>>, on vm: VM) throws -> Value
}

extension ComponentVMBase {
    // Private values and scopes (R3.11, R6.1, R7)
    public func signal<Value: Equatable>(_ initial: Value) -> Signal<Value>
    public func signal<Value>(_ initial: Value, equals: @escaping (Value, Value) -> Bool) -> Signal<Value>
    public func memo<Value: Equatable>(_ evaluate: @escaping (Value?) -> Value) -> Memo<Value>
    public func memo<Value>(_ evaluate: @escaping (Value?) -> Value, equals: @escaping (Value, Value) -> Bool) -> Memo<Value>
    public func invalidate(_ names: String...) throws
    @discardableResult public func change<T>(_ body: () throws -> T) throws -> T

    // Commands (R10)
    public func relayCommand(_ task: @escaping () -> Void, canExecute: (() -> Bool)? = nil,
                             triggers: [AnyPublisher<Void, Never>] = []) -> RelayCommand
    public func relayCommandOf<T>(_ task: @escaping (T) -> Void, canExecute: ((T) -> Bool)? = nil,
                                  triggers: [AnyPublisher<Void, Never>] = []) -> RelayCommandOf<T>
    public func asyncRelayCommand(_ task: @escaping () async throws -> Void, canExecute: (() -> Bool)? = nil,
                                  triggers: [AnyPublisher<Void, Never>] = [],
                                  throwOnCancel: Bool = false) -> AsyncRelayCommand

    // Members and injection (R11)
    @discardableResult public func member<VM: ComponentVMBase>(_ vm: VM) throws -> VM
    @discardableResult public func member<VM: ComponentVMBase>(
        _ create: (MessageHubProtocol, Dispatcher) -> VM) throws -> VM

    // Reactions (R12); each returns the handle (R12.10)
    @discardableResult public func effect(_ run: @escaping () -> Void) -> ReactionHandle
    @discardableResult public func effect(_ run: @escaping () -> (() -> Void)?) -> ReactionHandle
    @discardableResult public func reaction<Value: Equatable>(
        _ select: @escaping () -> Value, _ handler: @escaping (Value, Value) -> Void,
        immediate: Bool = false, alive: Bool = false) -> ReactionHandle
    @discardableResult public func reaction<Value>(
        _ select: @escaping () -> Value, _ handler: @escaping (Value, Value) -> Void,
        equals: @escaping (Value, Value) -> Bool, immediate: Bool = false, alive: Bool = false) -> ReactionHandle
    @discardableResult public func whileConstructed(_ setup: @escaping () -> (any Cancellable)?) -> ReactionHandle
    @discardableResult public func whileConstructed(_ setup: @escaping () -> (() -> Void)?) -> ReactionHandle

    // Keyed resources (R14)
    public func keyedResource<Key: Equatable, Value>(
        name: String? = nil, key: @escaping () -> Key, load: @escaping (Key) async throws -> Value,
        enabled: (() -> Bool)? = nil, autoLoad: Bool = false, cancelWhenDisabled: Bool = true,
        retryOnEnable: Bool = true, resumeCancelledFirstLoad: Bool = true,
        retention: AsyncResourceRetention = .discardPrevious,
        cleanupValue: ((Value) -> Void)? = nil) -> AsyncResourceVM<Value>
    @discardableResult public func followKey<Key: Equatable, Value>(
        _ resource: AsyncResourceVM<Value>, key: @escaping () -> Key, enabled: (() -> Bool)? = nil,
        autoLoad: Bool = false, cancelWhenDisabled: Bool = true, retryOnEnable: Bool = true,
        resumeCancelledFirstLoad: Bool = true) -> ReactionHandle
}
```

| Name                                           | Shape                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Signal<Value>`, `Memo<Value>` (final classes) | `value` (get; a signal also sets), `peek()`, and `invalidate()` on a memo.                                                                                                                                                                                                                                                                                                                             |
| `ReactionHandle` (final class, `Cancellable`)  | `remove()`; `cancel()` calls `remove()`. Releasing the handle does not remove the reaction.                                                                                                                                                                                                                                                                                                            |
| `Reactive` (enum namespace)                    | `untracked(_:)`, `read(_:_:get:)`, `activate(_:)`, `explain(_:_:)`, `static var reportSink: ((String) -> Void)?`, `resetReports()`, the throwing `set(_:on:to:)` and `read(_:on:)` above, `setDiagnosticsScheduler<S: Scheduler>(_:)` and `resetDiagnosticsScheduler()` (R19.12; default `DispatchQueue.main`), `static var developmentDiagnostics: Bool?` (R19.13; `nil` = the `DEBUG` build switch). |
| `ExplainEntry` (struct)                        | `let owner: AnyObject`, `let name: String`.                                                                                                                                                                                                                                                                                                                                                            |
| `ReactiveError` (enum, `Error`)                | `.usage(String)`, `.write(String)`, `.cycle(String)`, `.overflow(String)`; thrown by the calls that can throw.                                                                                                                                                                                                                                                                                         |

- State: `@Observed public private(set) var isEmpty = false`. The initial value
  is set before `super.init` and announces nothing. After `super.init`,
  `isEmpty = true` inside the class is one write. The name is the property name:
  the base reads it from the wrapper's storage label (`_isEmpty`, through
  `Mirror`) when it binds the wrappers. It binds every `Observed` and `Computed`
  wrapper of the instance, superclass first and in declaration order, at the
  first of: any helper call, activation, or the first access through a wrapper.
  Every wrapper is therefore bound before activation, so Swift has no state
  registered after activation (R3.13).

- Computed: the wrapper registers the computed property by a key path to a
  private getter, which Swift passes as a function of the view-model (SE-0249):

  ```swift
  @Computed(\SectionVM.collapsedValue) public private(set) var collapsed: Bool
  private var collapsedValue: Bool { isEmpty || !expansion.isExpanded }
  ```

  A closure such as `{ (vm: SectionVM) in vm.isEmpty }` works too. The
  function takes the view-model, so the declaration captures no `self`. Reads of
  `collapsed` go through the node, so they are memoized (R3.9) and detect
  cycles (R16.8); a key path to the public property itself would do neither.

- Commands, signals, memos and members are created after `super.init`, or in a
  `lazy var` whose first access is in `init`, so that the registration happens
  at construction time.

- Closures that a reaction keeps capture `[unowned self]`.

- `Equatable` values use `==` as their equality; other values need `equals`.
  The keys of `keyedResource` and `followKey` are `Equatable` and compare with
  `==`, so the custom-equality branch of R19.8 has no Swift case.

- Errors. `change`, `invalidate` and `member` throw `ReactiveError`. A misuse
  in a call that cannot throw traps: a write through a wrapper's setter or a
  registration inside an evaluation frame, and a plain read outside every
  evaluation of a computed in error state (R16.8). `Reactive.set` and
  `Reactive.read` give tests and careful callers a throwing form:
  `try Reactive.set(\SectionVM._isEmpty, on: self, to: true)` and
  `try Reactive.read(\SectionVM._collapsed, on: vm)`. The compiler already
  rejects most registration errors of R3.3 (a duplicate or a library name
  cannot be declared).

- Overflow (R9.6). A Swift write through a wrapper's setter cannot throw, so
  the drain reports the overflow and does not throw it:

  - The drain builds `MessageHubOverflowError(limit: 10_000, messageTypes:)`.
    Its `messageTypes` are the entry names of R9.6, most repeated first, at most
    ten, each with its ` x<count>` (for example
    `"Runaway(runaway):effect#2 x10001"`).
  - It passes the error to the diagnostic handler of the hub of the VM whose
    write started the drain, when that hub is a `MessageHub` built with
    `MessageHub(diagnosticHandler:)`. An internal accessor on `MessageHub`
    reads the handler, which is a private stored property today.
  - Otherwise (a hub without a handler, a `NullMessageHub` or a custom hub)
    it passes the description of `ReactiveError.overflow` to
    `Reactive.reportSink`, or to `debugPrint` when the sink is `nil`. It never
    calls `assertionFailure`, unlike the hub's own bound (spec 03 §3.3).
  - The drain then abandons the rest of its queue. The overflowing reaction
    stays registered and active and runs again only at its next input change,
    so a construct whose start overflows completes (R13.1 step 5).

- The wrappers' `wrappedValue` is unavailable: only the enclosing-instance
  subscript is used, which reaches the view-model. A `whileConstructed` setup
  that returns nothing on some path writes `return nil as (() -> Void)?`,
  because `{ nil }` fits both overloads.

- Computed functions, effect runs, selects, handlers and setups are closures
  that cannot throw, as Swift subscribers cannot fail (spec 03 §3.6). R16.1 to
  R16.6 therefore have no Swift case except cycles, which R16.8 states for
  Swift.

- The Observation framework is not used: it needs macOS 14 and iOS 17, above
  the package floor (macOS 13, iOS 16).

### 4.6 Rust API

One handle per VM reaches the helpers: `vm.reactive()` returns `Reactive<D>`
(`D` is the VM's dispatcher type). `ComponentVm` and every VM type that has
`on_construct` (spec 02 §2.2) get the method. The handle is `Clone + Send + Sync` and holds the VM weakly.

```rust
impl<D: Dispatcher> Reactive<D> {
    // State (R3.1, R3.11)
    pub fn observable<T: NodeValue>(&self, name: &str, initial: T) -> VmxResult<State<T>>;
    pub fn observable_with<T: NodeValue>(&self, name: &str, initial: T, equals: impl Fn(&T, &T) -> bool + Send + Sync + 'static) -> VmxResult<State<T>>;
    pub fn signal<T: NodeValue>(&self, initial: T) -> Signal<T>;

    // Computed (R3.2, R3.11, R6.1, R7)
    pub fn computed<T: NodeValue>(&self, name: &str, evaluate: impl Fn() -> T + Send + Sync + 'static) -> VmxResult<Computed<T>>;
    pub fn computed_with<T: NodeValue>(&self, name: &str, evaluate: impl Fn() -> T + Send + Sync + 'static, equals: impl Fn(&T, &T) -> bool + Send + Sync + 'static) -> VmxResult<Computed<T>>;
    pub fn memo<T: NodeValue>(&self, evaluate: impl Fn(Option<&T>) -> T + Send + Sync + 'static) -> Memo<T>;
    pub fn invalidate(&self, names: &[&str]) -> VmxResult<()>;
    pub fn change<R>(&self, body: impl FnOnce() -> R) -> VmxResult<R>;

    // Commands (R10): build from the existing builders and own in one call
    pub fn relay_command(&self, builder: RelayCommandBuilder) -> RelayCommand;
    pub fn relay_command_of<T: Clone + Send + 'static>(&self, action: impl FnMut(T) + Send + 'static, can_execute: Option<Box<dyn Fn(&T) -> bool + Send + Sync>>) -> RelayCommandOf<T>;
    pub fn async_relay_command(&self, builder: AsyncRelayCommandBuilder) -> AsyncRelayCommand;

    // Members and injection (R11)
    pub fn member<N: VmNode>(&self, vm: &N) -> VmxResult<()>;
    pub fn member_with<N: VmNode>(&self, create: impl FnOnce(MessageHub, D) -> N) -> VmxResult<N>;

    // Reactions (R12); each returns the handle (R12.10)
    pub fn effect(&self, run: impl FnMut() -> Option<Cleanup> + Send + 'static) -> ReactionHandle;
    pub fn reaction<T: NodeValue>(&self, select: impl Fn() -> T + Send + Sync + 'static, handler: impl FnMut(&T, &T) + Send + 'static, options: ReactionOptions<T>) -> ReactionHandle;
    pub fn while_constructed(&self, setup: impl FnMut() -> Option<Cleanup> + Send + 'static) -> ReactionHandle;

    // Keyed resources (R14)
    pub fn keyed_resource<K: NodeValue, T: Clone + Send + Sync + 'static>(&self, options: KeyedResourceOptions<K, T>) -> VmxResult<AsyncResourceVm<T, D>>;
    pub fn follow_key<K: NodeValue, T: Clone + Send + Sync + 'static>(&self, resource: &AsyncResourceVm<T, D>, options: FollowKeyOptions<K>) -> ReactionHandle;
}

/// The value bound of every node: `Clone + PartialEq + Send + Sync + 'static`.
pub trait NodeValue: Clone + PartialEq + Send + Sync + 'static {}
impl<T: Clone + PartialEq + Send + Sync + 'static> NodeValue for T {}
pub type Cleanup = Box<dyn FnOnce() + Send>;
```

| Name                               | Shape                                                                                                                                                                                                                                                                                                                          |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `State<T>`, `Signal<T>` (`Clone`)  | `get(&self) -> T` (tracked), `peek(&self) -> T`, `set(&self, value: T) -> VmxResult<()>` (one write; `Err(VmxError::ReactiveWrite)` inside an evaluation frame).                                                                                                                                                               |
| `Computed<T>`, `Memo<T>` (`Clone`) | `get(&self) -> T` (tracked; a node in error state is evaluated again and its panic propagates, and a cycle panics with the cycle message), `try_get(&self) -> VmxResult<T>`, `peek(&self) -> T`; `Memo::invalidate(&self) -> VmxResult<()>`.                                                                                   |
| `ReactionOptions<T>`               | `equals: Option<Arc<dyn Fn(&T, &T) -> bool + Send + Sync>>`, `immediate: bool`, `alive: bool`; `Default`.                                                                                                                                                                                                                      |
| `FollowKeyOptions<K>`              | `key` (mandatory, `Arc<dyn Fn() -> K + Send + Sync>`), `enabled`, `auto_load`, `cancel_when_disabled` (true), `retry_on_enable` (true), `resume_cancelled_first_load` (true), `equals`; built with `FollowKeyOptions::new(key)` and setters.                                                                                   |
| `KeyedResourceOptions<K, T>`       | the fields of `FollowKeyOptions<K>`, plus `load: Arc<dyn Fn(K, CancellationToken) -> VmxResult<T> + Send + Sync>`, `name`, `retention`, `cleanup_value`; `KeyedResourceOptions::new(key, load)`.                                                                                                                               |
| `ReactionHandle` (`#[must_use]`)   | a guard, as the VMx Rust `Subscription` is: dropping it removes the reaction; `dispose(&self)` removes it at once and is idempotent, as `Subscription::dispose` is; `detach(self)` keeps the reaction for its scope (R12.10, ADR-0237 §2.1 rule 4).                                                                            |
| free functions in `vmx::reactive`  | `untracked`, `read(source, name, get)`, `activate`, `explain`, `set_report_sink(Option<Box<dyn Fn(&str) + Send + Sync>>)`, `reset_reports()`, `set_diagnostics_scheduler(Option<Arc<dyn Scheduler>>)` (R19.12; `None` = `SystemScheduler`), `set_development_diagnostics(Option<bool>)` (R19.13; `None` = `debug_assertions`). |
| `ExplainEntry`                     | `pub struct ExplainEntry { pub owner: String, pub name: String }`; `owner` is the owning VM's name.                                                                                                                                                                                                                            |
| `VmxError`                         | new variants `ReactiveWrite(String)`, `ReactiveCycle(String)`, `ReactiveOverflow(String)`. Usage errors are `OwnershipCycle` for a member registration of the owner itself or an owner cycle (R11.3), and `InvalidArgument(String)` otherwise.                                                                                 |

New in this proposal, not in the prototype: the `ReactionHandle` methods
`dispose` and `detach` (ADR-0237 names the guard and `detach()`), and the
diagnostics functions.

- Closures capture node handles (`Arc` clones) and never the VM itself, so no
  cycle keeps a VM alive.
- A computed fails by panicking. The graph catches the panic for each
  evaluation and keeps the error state (R16.1). A read of a node in error state
  evaluates it again (R3.9): `get` lets the new panic propagate to the reader.
  `try_get` returns `Err(VmxError::ReactiveCycle(..))` for a cycle (R16.8),
  `Err(VmxError::ReactiveWrite(..))` when the evaluation's frame failed with a
  write, registration or handle call (R16.7), and
  `Err(VmxError::Other(<panic text>))` for any other panic.
- `relay_command_of` takes an optional predicate and no triggers, because the
  Rust `RelayCommandOf` has no triggers today (`raise_can_execute_changed()`
  is its imperative raise). The implementation records this as an ADR-0009
  row, against R10.1.
- `VmxError` is not `#[non_exhaustive]`, so the three new variants are a
  source-breaking change for exhaustive `match` expressions and need the Rust flavor's
  breaking bump (README §6.1).

### 4.7 Flavor table

| Concern                        | C#                                                                        | Python                                                    | TypeScript                                               | Swift                                                              | Rust                                                                                                                                   |
| ------------------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Default equality               | `EqualityComparer<T>.Default`                                             | `==`                                                      | `Object.is`                                              | `==` (`Equatable`)                                                 | `PartialEq`                                                                                                                            |
| Shallow equality               | `SequenceEqualityComparer<TItem>`                                         | none (`==` is item-wise)                                  | `shallowEqual`                                           | none (`==`)                                                        | none (`PartialEq`)                                                                                                                     |
| Usage error                    | `InvalidOperationException` (`ArgumentException` for bad arguments)       | `RuntimeError`                                            | `Error`                                                  | `ReactiveError.usage` from a call that can throw; otherwise a trap | `VmxError::OwnershipCycle` for the owner itself and for an owner cycle (R11.3, as `own_member`); `VmxError::InvalidArgument` otherwise |
| Reactive errors                | `Reactive*Exception`                                                      | `Reactive*Error` (`RuntimeError`)                         | `Reactive*Error`                                         | `ReactiveError` from a call that can throw; otherwise a trap       | `VmxError::Reactive*`                                                                                                                  |
| Stream-fed route               | discarded                                                                 | `logger.exception`                                        | rxjs `config.onUnhandledError`                           | none (subscribers cannot fail)                                     | the panic is caught                                                                                                                    |
| Report sink (R19.12)           | `ReactiveGraph.Report` event; default `Debug.WriteLine`                   | `set_report_sink`; default logger warning                 | `setReactiveReportSink`; default `console.warn`          | `Reactive.reportSink`; default `debugPrint`                        | `set_report_sink`; default `eprintln!` under `debug_assertions`                                                                        |
| Frame storage (R18.7)          | `[ThreadStatic]`                                                          | `threading.local`                                         | module variable                                          | thread-local                                                       | `thread_local!`                                                                                                                        |
| Reaction handle                | `IDisposable`                                                             | zero-argument callable                                    | `() => void`                                             | `ReactionHandle` (`Cancellable`; releasing it keeps the reaction)  | `ReactionHandle` (a guard; `Drop` and `dispose()` remove, `detach()` keeps)                                                            |
| Weak-reference probe (R17.2)   | `WeakReference` after `GC.Collect()`                                      | `weakref.ref` after `gc.collect()`                        | `WeakRef` with `node --expose-gc`                        | `weak var`                                                         | `Weak` from the VM's handle                                                                                                            |
| Development switch (R19.11)    | `DEBUG` build                                                             | `__debug__`                                               | `developmentDiagnostics`                                 | `DEBUG` build                                                      | `debug_assertions`                                                                                                                     |
| Test override (R19.13)         | `ReactiveGraph.DevelopmentDiagnostics`                                    | `set_development_diagnostics`                             | `setReactiveDevelopmentDiagnostics`                      | `Reactive.developmentDiagnostics`                                  | `set_development_diagnostics`                                                                                                          |
| Diagnostics scheduler (R19.12) | `ReactiveGraph.DiagnosticsScheduler`; default `DefaultScheduler.Instance` | `set_diagnostics_scheduler`; default `TimeoutScheduler()` | `setReactiveDiagnosticsScheduler`; default one macrotask | `Reactive.setDiagnosticsScheduler`; default `DispatchQueue.main`   | `set_diagnostics_scheduler`; default `SystemScheduler`                                                                                 |

### 4.8 Samples

A collapsible section, in TypeScript:

```ts
export class SectionVM extends ComponentVM {
  declare readonly isEmpty: boolean;
  declare readonly title: string;
  readonly #expansion = this.own(new ExpandableState(false));
  readonly toggleCommand = this.relayCommand(() => this.#expansion.toggleExpansion(), () => !this.isEmpty);
  readonly #set;

  constructor(o: SectionVMOptions) {
    super({ name: `section:${o.key}`, hub: o.hub, dispatcher: o.dispatcher });
    this.#set = this.observable({ isEmpty: o.isEmpty, title: o.title });
    this.computed("collapsed", "toggleText");
  }

  get collapsed(): boolean { return this.isEmpty || !this.#expansion.isExpanded; }
  get toggleText(): string { return this.collapsed ? "Show" : "Hide"; }

  update(isEmpty: boolean, title: string): void { this.#set({ isEmpty, title }); } // one write
}
```

The same section in C#:

```csharp
public sealed class SectionVM : ComponentVMBase
{
    private readonly ExpandableState _expansion = new(false);
    private readonly State<bool> _isEmpty;
    private readonly State<string> _title;
    private readonly Computed<bool> _collapsed;
    private readonly Computed<string> _toggleText;

    public SectionVM(SectionVMOptions o) : base($"section:{o.Key}", o.Hub, o.Dispatcher)
    {
        Own(_expansion);
        _isEmpty = ObservableState(nameof(IsEmpty), o.IsEmpty);
        _title = ObservableState(nameof(Title), o.Title);
        _collapsed = Computed(nameof(Collapsed), () => IsEmpty || !_expansion.IsExpanded);
        _toggleText = Computed(nameof(ToggleText), () => Collapsed ? "Show" : "Hide");
        ToggleCommand = Command(_expansion.ToggleExpansion, () => !IsEmpty);
    }

    public override ViewModelType Type => ViewModelType.Component;
    public RelayCommand ToggleCommand { get; }
    public bool IsEmpty => _isEmpty.Value;
    public string Title => _title.Value;
    public bool Collapsed => _collapsed.Value;
    public string ToggleText => _toggleText.Value;

    public void Update(bool isEmpty, string title) => Change(() =>
    {
        _isEmpty.Value = isEmpty;
        _title.Value = title;
    });
}
```

A favorite toggle with a keyed resource and a reaction, in Python:

```python
class FavoriteVM(ComponentVM):
    item_id: str
    is_favorite: bool

    def __init__(self, *, item_id: str, store: FavoriteStore, hub: MessageHubProto[Message],
                 dispatcher: Dispatcher) -> None:
        super().__init__(name=f"favorite:{item_id}", hub=hub, dispatcher=dispatcher)
        self._write = self._observable(item_id=item_id, is_favorite=False)
        self._computed("label")
        self.state_resource = self._keyed_resource(
            key=lambda: self.item_id, load=store.is_favorite, auto_load=True)
        self._reaction(lambda: self.state_resource.state, self._apply_loaded_state)
        self.toggle_command = self._relay_command(self._toggle, self._is_loaded)

    @property
    def label(self) -> str:
        return "Remove favorite" if self.is_favorite else "Add favorite"

    def _apply_loaded_state(self, state: AsyncResourceState[bool], _previous: object) -> None:
        if state.status == AsyncResourceStatus.READY:
            self._write(is_favorite=state.value)

    def _is_loaded(self) -> bool:
        return self.state_resource.state.status == AsyncResourceStatus.READY

    def _toggle(self) -> None:
        self._write(is_favorite=not self.is_favorite)
```

## 5. Conformance plan

### 5.1 The prefix, the section and the tools

- Chapter 12 §1 gains a prefix row, and chapter 12 gains a section for the
  entries of §5.2, as its next section (§34 when this was written). `3.NN`
  stands for the spec release that adds chapter 24, and `NN` for that section
  number:

  ```text
  | `RSTATE-NNN` | Registered reactive state | `24-registered-reactive-state.md` |

  ## NN. Registered reactive state (`RSTATE-NNN`) — spec v3.NN
  ```

- The prefix has six letters. The ID patterns of `tools/check-conformance-*.py`
  (the chapter-structure check, the marker check and the execution check)
  accept three to five letters today (`[A-Z]{3,5}`). Phase 0 of §7 widens them
  to `[A-Z]{3,6}` and adds tests for a six-letter prefix.

- Every flavor implements every ID, with the marker forms of AGENTS.md §2. A
  clause that names flavors applies to those flavors only. These rules map the
  remaining flavor differences:

  - Swift traps where a call cannot throw (§4.5), and its closures cannot
    throw. A clause that needs a Swift closure to throw, or a call that traps,
    is skipped, and the Swift test checks the remaining clauses, as the Swift
    note of `DLY-005` does.
  - "Is reported" means the stream-fed route (§2). Python and TypeScript
    observe the report. In C#, which discards the failure, and in Rust, which
    catches the panic, the test asserts instead that the failure does not
    reach the writer or the caller. Swift has no failing case.
  - "Development diagnostics on" and "off" in a Given set the override of
    R19.13, and the test resets it afterwards. So both cases run in every
    flavor and in every build configuration.
  - "A task passes" means that the diagnostics scheduler runs its pending work
    (R19.12): the test advances its virtual-time scheduler (TypeScript with the
    default scheduler: one macrotask).
  - Rust: "throws `ReactiveWriteError`" for a read of a computed means that
    `try_get` returns `Err(VmxError::ReactiveWrite(..))` and `get` panics
    (R16.7); "throws `ReactiveCycleError`" means
    `Err(VmxError::ReactiveCycle(..))`. "Is in error state" means that
    `try_get` returns an `Err`. A registration inside an evaluation
    (`RSTATE-002`) marks the frame failed, as R16.7 states for Rust.
  - C#: a VM that registers is a subclass of one of the unsealed bases (§2).
    Where an entry names a sealed class (`CompositeVM`, an aggregate), the C#
    test uses a subclass of the matching base, for example
    `CompositeVMBase<VM>`.

- The entries use neutral names: "registers the state `a = 1`" means the
  flavor's state registration (§4). "`a` is assigned `v`" is one single-key
  write in the flavor's idiom: the setter in TypeScript, C#, Swift and Rust,
  and the writer call `write(a=v)` in Python, whose descriptors reject
  assignment (§4.4). Each entry starts with a `Rules:` line for this document;
  in chapter 12 that mapping moves to the Conformance table of chapter 24, and
  the entry keeps only its Given/When/Then lines. To copy an entry into
  chapter 12, change its `####` heading to `###` (`tools/check-conformance-catalog.py` reads
  only `### ` plus one ID), drop its `Rules:` line, and keep the
  Given/When/Then lines unchanged.

- Walks get the next free `UTIL` ID (`UTIL-005` when this was written; open
  issue #1612 also plans a `UTIL` ID, so the one that lands second takes the
  next number), in chapter 12 §14 and in chapter 13 (ADR-0236 §2.4), because
  the walk rule belongs to chapter 13. §5.2 lists it after the `RSTATE`
  entries as `UTIL-005`.

- The prototype's tests carry the same IDs for RSTATE-001 to RSTATE-036
  (`prototype/tests/*.test.ts`), with two exceptions: its `RSTATE-025` test
  checks RSTATE-025 and RSTATE-026 of this plan, and its `RSTATE-026` test
  checks `UTIL-005`. RSTATE-037 has no TypeScript prototype test. The later
  IDs map to these tests:

  - RSTATE-038: `fix-r1.test.ts`, "R9.8 producer order";
  - RSTATE-039: `fix-r2.test.ts`, "R6.10 equalities run in their own
    context";
  - RSTATE-040: `fix-r2.test.ts`, "R12.10 registration scopes and handles"
    and "R13.2 a destruct that rolls back restarts the reactions it stopped";
  - RSTATE-041: `fix-r1.test.ts`, "R11.4, R12.9, R13.2 and R13.3 lifecycle
    windows", and `fix-r1-random.test.ts` for the skip rule;
  - RSTATE-042 and RSTATE-043: no prototype test (R14.6 and R14.7 postdate
    the prototype); phase 7 writes new tests;
  - RSTATE-044: `diagnostics.test.ts`; `fix-r1.test.ts`, "R19.6 reactive
    usage errors inside a predicate" and "R19.8 keyed resources with object
    keys"; `fix-r2.test.ts`, "R3.13 state registered after activation" and
    "R12.3 asynchronous effects";
  - RSTATE-045: `fix-r1.test.ts`, "R5.7 and R5.8 library operations and
    deliveries run untracked";
  - RSTATE-046: `rules.test.ts`, "R3.4 a registration after disposal started
    installs nothing; R3.6 signals and memos stop" and "R3.8 forwarding
    decorators follow the canonical identity".

### 5.2 Entries

#### RSTATE-001 — State registration installs accessors, announces nothing, and writes through the setter (Python: the writer) and the writer

Rules: R3.1, R3.13, R6.1, R8.3.

**Given** a VM V that registers the state `a = 1` and `b = "x"` in one call and
the computed `label`, which returns `b` followed by `a` and counts its
evaluations, with recorders of the hub and of V's local surface
**When** V is activated
**Then** `a` reads 1, `b` reads `"x"`, and nothing was announced
**And** TypeScript: `a` and `b` are own, configurable, enumerable accessors of
V, in key order
**When** `a` is assigned 2
**Then** the recorders see hub `a`, local `a`, hub `label`, local `label`
**When** the writer writes `{ b: "y" }` (C#, Swift and Rust: `b` is assigned
`"y"`)
**Then** `b` reads `"y"` and the recorders see `b`, then `label`
**When** TypeScript and Python: the writer is called with `a = 5` and a key that
it did not register
**Then** the call raises the usage error, `a` still reads 2, and nothing is
announced
**When** V, activated, registers the state `c = 0`
**Then** `label` is evaluated once more and is not announced, because its value
did not change
**And** in development the late registration is reported once for V's class
**And** Swift: every wrapper is bound before activation (§4.5), so Swift has no
state registered after activation, and the test skips this clause

#### RSTATE-002 — Registration errors

Rules: R3.3, R3.12, R16.7.

**Given** a VM class
**When** it registers one name twice, or registers a library member name such
as `status` or `hint`
**Then** each such call raises the usage error
**And** TypeScript and Python: a state key that names an existing getter, a
computed name without a getter, and a name that is already an own attribute of
the instance each raise the usage error
**And** Swift: the compiler rejects these declarations, and the test shows the
runtime case below
**When** `invalidate` names a state or an unknown name
**Then** it raises the usage error (Swift: it throws `ReactiveError.usage`)
**When** a computed's getter registers a signal while it is evaluated
**Then** the read throws `ReactiveWriteError` (Swift: the registration traps and
is not tested)
**When** TypeScript: a subclass declares a class field that replaces a
registered state accessor, and the VM is activated
**Then** activation raises the usage error "`x` is shadowed by a class field;
declare it with `declare`", and a second activation raises it again

#### RSTATE-003 — Accepted writes: equality, custom equality, and the disposal window

Rules: R6.2, R13.3.

**Given** an activated VM V with the state `a = 1` and `b = "x"`, the state
`item` whose custom equality compares only its `id` field, and a hub recorder
**When** `a` is assigned 1, and then `a = 1` and `b = "x"` are written in one
write
**Then** nothing is announced
**When** `item` is written with the same `id` and different other fields
**Then** nothing is announced, and `item` keeps its old value
**When** `item` is written with a different `id`
**Then** `item` is announced once
**When** V has a member whose dispose hook writes V's `a = 5`, and V is disposed
**Then** the write is accepted, and `a` is announced before V's Disposed
message
**When** V's own dispose hook writes `a`, and code writes `a` after the
disposal
**Then** both writes are ignored: `a` keeps its value, nothing is announced,
and no error is raised

#### RSTATE-004 — A multi-key write is one write

Rules: R3.1, R6.1, R6.4, R8.1.

**Given** an activated VM with the state `a` and `b`, registered in that order,
and the computed `label` over both, which counts its evaluations
**When** one write sets `b = "z"` and `a = 9` (TypeScript and Python: one
writer call with the keys in that order; C#, Swift and Rust: one change scope
that assigns `b`, then `a`)
**Then** `label` is evaluated once
**And** the hub sees `a`, `b`, then `label`, each once
**When** `a` is assigned, and then `b` is assigned in a second write
**Then** `label` is evaluated twice, and the hub sees `a`, `label`, `b`, `label`

#### RSTATE-005 — Before activation a registered computed is a plain getter

Rules: R3.10, R4.5, R5.3, R16.8.

**Given** a VM V that registers the state `a` and the computed `label`, which
counts its evaluations, and that is not activated
**When** `label` is read twice
**Then** the getter ran twice and returned the current value each time
**When** `a` is assigned
**Then** the hub sees only `a`
**Given** an activated VM W whose computed `shout` reads V's `label`
**When** V's `a` is assigned
**Then** the hub sees V's `a`, then W's `shout`, and `shout` reads the new value
**When** V calls `invalidate("label")`
**Then** W's `shout` is evaluated again
**Given** a computed of a VM that is not activated, whose getter reads itself
**When** it is read
**Then** the read throws `ReactiveCycleError` (Swift: a plain getter has no
last value, so the read traps (R16.8), and the test skips this clause)

#### RSTATE-006 — Activation triggers and the cascade

Rules: R4.1, R4.2, R4.3, R4.6.

**Given** a VM V whose computed logs each evaluation, and whose construct hook
logs `construct`
**When** V's first `construct()` runs
**Then** the log shows the baseline after Constructing was published and before
`construct`
**Given** a new VM V
**When** a first observer subscribes to V's local property-change surface (C#:
the first `PropertyChanged` handler)
**Then** V's baselines ran
**Given** a `CompositeVM` O (C#: a subclass of `CompositeVMBase<VM>`, §5.1)
that registered the member M and holds the child C, none of them activated,
each with a computed that logs its baseline
**When** O is activated
**Then** M's and C's baselines ran before O's, depth-first
**When** O registers a new member, and a child is added to O
**Then** each is activated at once
**When** `activate(V)` is called twice on a new VM V
**Then** V's baselines ran once
**When** `activate` is called on a VM whose disposal started
**Then** nothing runs
**When** C#, Python, TypeScript and Swift: a subscription to
`whenPropertyChanged` that names a new VM V as the sender is made
**Then** V is activated (Rust has no trigger (f), R4.2)
**Given** a constructed and then destructed VM with the state `a` and a computed
over `a`
**When** `a` is written
**Then** the computed is evaluated again and announced

#### RSTATE-007 — Baselines are silent; a throwing baseline leaves an error node

Rules: R4.1, R16.3.

**Given** a VM with the state `a`, the computed `b` over `a` and the computed `c`
over `b`, each counting its evaluations, and a hub recorder
**When** the VM is activated
**Then** nothing is announced, and `b` and `c` were evaluated once each,
although `c`'s baseline read `b`
**Given** a VM whose computed throws until the state `ready` is true, and a
stream-fed recorder
**When** the VM is activated
**Then** nothing is announced and nothing is reported
**When** `ready` is assigned true
**Then** the computed is announced once, and a read returns its value

#### RSTATE-008 — Memoization

Rules: R3.9, R3.11, R6.4.

**Given** an activated VM with the state `a` and a computed over `a` that counts
its evaluations
**When** the computed is read three times
**Then** it was evaluated once, by the baseline
**When** `a` changes and the computed is read twice
**Then** it was evaluated once more
**Given** a memo over `a` that counts its evaluations and records the previous
value it receives
**When** `a` changes and the memo is not read
**Then** the memo was not evaluated
**When** the memo is read twice
**Then** it was evaluated once, and it received no previous value
**When** `a` changes and the memo is read
**Then** it received the value of its first evaluation as the previous value

#### RSTATE-009 — Each changed published value is announced once per settle, hub first

Rules: R6.4, R6.6, R8.3.

**Given** a VM with the state `a` and the computeds `b = a + 1`, `c = a * 10`
and `d` over `b` and `c`, with recorders of the hub and of the VM-local surface
**When** `a` is assigned
**Then** the recorders see, in order: hub `a`, local `a`, hub `b`, local `b`, hub
`c`, local `c`, hub `d`, local `d`
**Given** an activated VM with the state `n = 1`, the computed `odd` over `n` and
the computed `text` over `odd`
**When** `n` is assigned 3
**Then** the hub sees only `n`
**When** `n` is assigned 4
**Then** the hub sees `n`, `odd` and `text`

#### RSTATE-010 — Glitch freedom

Rules: R6.4, R6.9.

**Given** an activated VM with the state `a`, the computeds `b = a + 1`,
`c = a * 10`, and `d`, which records the values of `b` and `c` that it reads
**When** `a` is assigned 5
**Then** `d` was evaluated once, with `b = 6` and `c = 50`
**And** `d` is announced once

#### RSTATE-011 — Losslessness

Rules: R6.9, R9.3, R9.4.

**Given** the activated VM of RSTATE-010
**When** `a` is assigned twice, at top level, with two different values
**Then** `d` is announced twice
**Given** a hub observer that assigns `a = 3` when it receives `a` while `a` is
2, and records the value of `d` at each announcement of `d`
**When** `a` is assigned 2
**Then** `d` is announced twice, and both announcements read the value of `d`
for `a = 3`

#### RSTATE-012 — Ordering within a settle and across settles

Rules: R6.6, R8.1, R8.2.

**Given** an activated VM with the state `x = 0` and `y = 0`, registered in that
order, the computeds `low = x + y` and `top = low + 1`, a command whose
predicate reads `x` and that was evaluated once, and an alive reaction over
`top`
**When** one write sets `y = 2` and `x = 3` (TypeScript and Python: one writer
call with the keys in that order; C#, Swift and Rust: one change scope that
assigns `y`, then `x`)
**Then** the observed order is: hub `x`, hub `y`, hub `low`, hub `top`, the
command's raise, the reaction's handler with 6

#### RSTATE-013 — Change scopes

Rules: R7.1, R7.2, R7.3, R7.4.

**Given** the activated VM of RSTATE-010 with `a = 1`
**When** a change scope assigns `a = 2`, reads `d`, assigns `a = 3`, and a nested
scope assigns `a = 4`
**Then** the read inside the scope returned the value of `d` for `a = 2`
**And** after the scope, `a`, `b`, `c` and `d` are each announced once, and `d`
reads the value for `a = 4`
**When** a scope assigns `a = 9` and then `a = 4`
**Then** nothing is announced
**When** a scope assigns `a = 7` and then throws
**Then** `a` reads 7, `a` to `d` are announced, and the scope's error reaches the
caller
**When** a computed's getter calls `change`
**Then** its read throws `ReactiveWriteError` (Swift: `change` throws
`ReactiveError.write`)
**When** TypeScript and C#: an asynchronous scope body assigns `a`, awaits, and
assigns `a` again
**Then** the first assignment is announced when the body suspends, and the
second at once
**When** Python: a write from another asyncio task happens while a scope is open
**Then** that write raises the usage error

#### RSTATE-014 — Independence from hub transactions

Rules: R7.5, R8.3, R9.7.

**Given** the VM of RSTATE-010 with a local recorder (which activates it) and a
hub recorder
**When** `a` is assigned inside `hub.batch`
**Then** inside the batch the local recorder saw `a`, `b`, `c` and `d`, and the
hub recorder nothing
**And** after the batch the hub recorder sees `a`, `b`, `c` and `d`
**When** `a` is assigned twice inside one `hub.batch`
**Then** `d` is announced twice
**When** `a` is assigned inside a change scope
**Then** the hub delivers the announcements when the scope exits, with no
batch

#### RSTATE-015 — Re-entrant FIFO without recursion

Rules: R6.7, R9.2, R9.3, R9.4, R16.10.

**Given** an activated VM with the state `n = 0` and the computed `next = n + 1`,
and a local observer that records each name with its current value, counts how
deep it is nested, and assigns `n + 1` when it receives `n` while `n < 5`
**When** `n` is assigned 1
**Then** `n` reads 5
**And** the recorded sequence is `n=1, next=3, n=2, next=4, n=3, next=5, n=4, next=6, n=5, next=6`
**And** the observer was never nested: its depth count never exceeded 1
**Given** C# or Python, an activated VM with the state `m` and a helper command
whose predicate reads `m` and was evaluated once, a local observer that throws
at its first call, and a `CanExecuteChanged` handler that throws at its first
call (R16.10)
**When** `m` is assigned
**Then** the local observer received `m`, and the command raised once
**And** the assignment raises the local observer's error, the first failure,
after the queue is empty

#### RSTATE-016 — `ReactiveWriteError` in evaluation frames

Rules: R4.4, R5.7, R6.2, R16.7.

**Given** an activated VM whose computeds, one each, assign a state, call
`change`, call `invalidate`, call `member()`, call `construct()` on another VM,
and assign the model of another VM
**When** each computed is read
**Then** each read throws `ReactiveWriteError`
**And** nothing was applied: the state keeps its value, and the other VMs keep
their status and model
**And** each computed is in error state
**And** the same holds with development diagnostics off
**Given** a command whose predicate assigns a state
**When** `canExecute()` is called
**Then** it returns false, and the state keeps its value
**And** Swift: an assignment through a wrapper's setter traps and is not tested;
a computed whose function calls `try Reactive.set(...)` on a state gets
`ReactiveError.write`, and the state keeps its value; `change`, `invalidate`
and `member` throw `ReactiveError.write`; a computed that calls
`try other.construct()` gets `ReactiveError.write`, and the other VM keeps its
status; the model-assignment clause is skipped, because the model setter
cannot throw and traps
**And** Rust: each read is `try_get` and returns
`Err(VmxError::ReactiveWrite(..))` (§5.1)

#### RSTATE-017 — Error states and reporting

Rules: R16.1, R16.2, R16.3, R16.5.

**Given** an activated VM with the state `level = 1` and `unit = "m"`, the
computed `reading`, which reads `unit` and `level` and throws an error with the
message `"bad level <level>"` when `level` is negative, a hub recorder and a
stream-fed recorder
**When** `level` is assigned −1
**Then** `reading` is announced, a direct read throws `"bad level -1"`, and the
error is reported once
**When** `level` is assigned −2
**Then** `reading` is announced again, and the new error is reported once
**When** `unit` is assigned `"cm"`, and `reading` throws `"bad level -2"`
again
**Then** `unit` is announced, `reading` is not announced, and nothing is
reported
**When** `level` is assigned 3
**Then** `reading` is announced and reads its value
**Given** a constructed VM with an effect whose re-run throws, and a reaction
whose handler throws
**When** their inputs change twice
**Then** each failure is reported, the effect runs again at the second change,
and the handler is called once per change
**And** C# and Rust: "is reported" follows §5.1; the test shows that the error
does not reach the writer
**And** Swift: computeds, effects, handlers and setups cannot throw; the test
shows that their closure types are non-throwing

#### RSTATE-018 — Cycle detection

Rules: R16.8.

**Given** an activated VM with the state `loop = false` and the computeds `p`
and `q`, where `p` reads `q`, and `q` reads `p` while `loop` is true
**When** `loop` is assigned true
**Then** a read of `p` throws `ReactiveCycleError`
**And** a computed whose getter catches that error from `q` still fails with it
**When** `loop` is assigned false
**Then** `p` and `q` read values again, and both are announced
**Given** a memo whose function reads the memo
**When** the memo is read
**Then** the read throws `ReactiveCycleError`
**And** Swift: the plain reads inside the evaluations return the last values of
the baselines and mark the frames of the cycle failed (R16.8), so
`try Reactive.read(\VM._p, on: vm)` throws `ReactiveError.cycle`, and the
`loop = false` clause holds. The catching computed and the memo clause are
skipped: a Swift function cannot catch the cycle, and the memo has no last
value

#### RSTATE-019 — The development drain bound

Rules: R9.6, R12.9, R13.1, R19.5, R19.13.

**Given** development diagnostics on, and a VM with the state `n = 0` and an
effect that assigns `n + 1` without a limit
**When** the VM is constructed
**Then** the construct throws `ReactiveOverflowError`, and its message contains
`:effect#` with a count above 10,000
**And** the status is Destructed, and the effect is stopped: a later write of
`n` does not run it
**And** Swift, with the VM built on `MessageHub(diagnosticHandler:)`: the
handler receives one `MessageHubOverflowError` whose `messageTypes` name the
effect (`:effect#`), the drain abandons the rest of its queue, and the
construct completes: the VM is Constructed, and the effect stays registered
and runs again only at its next input change (§4.5)
**Given** development diagnostics on, and one write whose fan-out queues 10,500
distinct announcements
**When** the write runs
**Then** all 10,500 announcements are delivered and nothing is thrown
**Given** development diagnostics off, and an effect that assigns `n + 1` until
`n` reaches 12,000
**When** the VM is constructed
**Then** the effect runs to 12,000 and nothing is thrown

#### RSTATE-020 — Tracking through call chains, other view-models, `untracked` and `peek`

Rules: R5.1 to R5.5.

**Given** an activated VM W whose computed reads, through a callback option, a
computed of W's member, then the state of a sibling VM, then a value inside
`untracked`, then a signal with `peek()`
**When** the member's input or the sibling's state changes
**Then** W's computed is evaluated again and announced
**When** the value read inside `untracked`, or the peeked signal, changes
**Then** W's computed is not evaluated again
**Given** a computed that reads `x` only while the state `flag` is true
**When** `flag` becomes false and then `x` changes
**Then** the computed is not evaluated again

#### RSTATE-021 — `invalidate` and `memo.invalidate`

Rules: R3.10, R3.11, R6.1.

**Given** an activated VM with the computed `now`, which reads a plain field
that the graph does not track
**When** the field changes and `invalidate("now")` is called
**Then** `now` is evaluated again and announced
**When** `invalidate("now")` is called while the field did not change
**Then** `now` is evaluated again and not announced
**Given** a memo over an untracked field, and a computed over the memo
**When** the field changes and `memo.invalidate()` is called
**Then** the memo and the computed are evaluated again, and the computed is
announced

#### RSTATE-022 — Tracked predicates

Rules: R10.2, R10.3, R10.4, R10.7, R10.8.

**Given** an activated VM with the state `x` and `y`, and a helper command whose
predicate reads `x`, counts its evaluations, and was evaluated once
**When** `x` changes
**Then** the command raises `CanExecuteChanged` once, and the predicate was not
evaluated by the change
**When** `x` changes again before any new evaluation
**Then** nothing is raised
**When** the predicate is evaluated again and `y` changes
**Then** nothing is raised
**Given** a predicate that reads `x` and then throws
**When** `canExecute()` is called and then `x` changes
**Then** `canExecute()` returned false, and the change raises once
**Given** a parameterized command evaluated with two parameters whose predicate
runs read the state `p` and `q` respectively
**When** `p` changes
**Then** the command raises once
**Given** an activated computed that calls `canExecute()` of a command
**When** a node that the predicate read changes
**Then** the computed is evaluated again and announced when its value changed
**When** the command raises through a trigger or `raiseCanExecuteChanged()`
**Then** the computed is evaluated again
**Given** a command built with the plain builder, whose predicate reads `x`, and
a decorator from `wrapWith`, whose extra predicate reads `y`; both evaluated
**When** `x` changes, and then `y` changes
**Then** the plain command raises once, at the first change
**And** the decorator raises once at each change

#### RSTATE-023 — Helper commands are owned; triggers and `throwOnCancel` pass through

Rules: R10.1, R10.6, R10.9.

**Given** a VM with a helper command and a helper async command
**When** the VM is disposed
**Then** both commands are disposed: `canExecute()` is false, and `execute()`
does nothing
**Given** a helper command built with a trigger
**When** the trigger emits
**Then** the command raises `CanExecuteChanged`
**Given** a helper async command built with `throwOnCancel`, executed through
the awaitable entry point
**When** the command is cancelled
**Then** the awaiter observes the flavor's cancellation error

#### RSTATE-024 — Member injection, refusals, and containers that refuse owned view-models

Rules: R11.1, R11.2, R11.3.

**Given** an owner O built with the hub H and the dispatcher D
**When** O registers a member through its type and options (C# and Swift: a
factory; Rust: `member_with`)
**Then** the member's hub is H, and its dispatcher is D
**When** O registers itself, a VM that another owner registered, a child of a
container, or O's own owner
**Then** each registration raises the usage error and registers nothing
**When** O registers one of its members again
**Then** the call returns that member, and O's member list does not change
**When** a container adds a member of O
**Then** the container raises its usage error, and the container and the member
do not change

#### RSTATE-025 — Member sequences and a failing member

Rules: R11.1, R13.1, R13.2, R13.3.

**Given** an owner O with the members M1 and M2, registered in that order, and an
effect E; each logs its construct, destruct, dispose, start and stop
**When** O is constructed
**Then** the log is `O.construct, M1.construct, M2.construct, E.start`, and M1
and M2 publish Constructed before O
**When** O is destructed
**Then** the log is `E.stop, M2.destruct, M1.destruct, O.destruct`
**When** O is constructed again and then disposed
**Then** the log ends with `E.stop, M1.dispose, M2.dispose, O.dispose`, and M1
and M2 publish Disposed before O
**Given** an owner whose second member fails to construct
**When** the owner is constructed
**Then** the construct fails with that error, the owner is Destructed, the first
member stays Constructed, and E never started

#### RSTATE-026 — Late member registration and removal at disposal

Rules: R11.4, R11.5.

**Given** an owner O
**When** O registers a member while Destructed, one while Constructed, one whose
construct fails while O is Constructed, and one after O was disposed
**Then** the first is constructed at O's next construct; the second at once; the
third raises its error at the registration and stays registered, so O's
disposal disposes it; the fourth is disposed at once
**Given** an owner O with the members M1 and M2
**When** M1 is disposed by other code, and O is then constructed
**Then** O's construct skips M1, O's member list no longer holds M1, and a walk
of O no longer yields it
**When** O registers a VM that is Disposed
**Then** nothing is registered, and the call returns the VM

#### RSTATE-027 — The reaction scope and registration timing

Rules: R12.1, R12.2.

**Given** a VM that registers, in its constructor, an effect that records
`status` and `isConstructed` at each run
**When** the VM is created
**Then** the effect has not run
**When** the VM is constructed
**Then** the effect's first run saw Constructing and false, and a second run saw
Constructed and true
**When** an effect is registered while the VM is Constructed
**Then** it runs at once
**When** an effect is registered while the VM is Destructed
**Then** it runs at the next construct
**When** an effect is registered after the VM's disposal started
**Then** it never runs, and its handle does nothing

#### RSTATE-028 — `effect`

Rules: R9.2, R12.3, R13.2.

**Given** a constructed VM with the state `a` and `seen`, and an effect that
reads `a`, assigns `seen = a`, and returns a cleanup; the runs and cleanups are
logged
**When** `a` changes
**Then** the log shows the cleanup, then the run with the new value
**And** the effect's own write of `seen` did not run it again
**When** the VM is destructed
**Then** the cleanup runs once, and a later change of `a` runs nothing
**Given** an effect run that disposes its own VM and returns a cleanup
**When** that run happens
**Then** the returned cleanup runs once, at once
**And** TypeScript: an effect whose function returns a promise is tracked up to
its first `await`, its promise is no cleanup, and its rejection goes to the
stream-fed route
**And** Python: an effect registered while the VM is Constructed, whose function
returns a coroutine, raises the usage error from the registration call (its
first run), and the coroutine was closed without running
**And** C#: `Effect` with an async lambda throws `ArgumentException` at
registration, and nothing is registered
**And** Swift and Rust: the compiler rejects an asynchronous effect function;
the test registers a synchronous effect and checks the clauses above

#### RSTATE-029 — `reaction`, `immediate`, `previous` and level-triggered runs

Rules: R12.4, R12.11.

**Given** a constructed VM with the state `n = 1` and a reaction over `n` that
logs `(value, previous)`
**When** `n` is assigned 2, then 2, then 3, each at top level
**Then** the log is `(2, 1), (3, 2)`
**When** the VM is destructed, `n` is assigned 4, and the VM is constructed
**Then** nothing is logged for 4, and the next change is delivered with 4 as
`previous`
**Given** an immediate reaction over the state `m = 1`
**When** the VM is constructed, `m` is assigned 5, the VM is destructed, `m` is
assigned 7, and the VM is constructed
**Then** the log is `(1, 1), (5, 1), (7, 5)`
**Given** a reaction with an equality that compares only an `id` field
**When** `n` is assigned a value with the same `id`
**Then** nothing is logged
**Given** a VM with the state `ready = false` and `k = 5`, and an immediate
reaction whose select throws while `ready` is false and otherwise returns `k`
**When** the VM is constructed, `ready` is assigned true, and then `k` is
assigned 6
**Then** the start's error is reported, and the log is `(5, 5), (6, 5)`
(Swift: a select cannot throw; the test skips this clause)
**Given** a hub observer that, during one drain, assigns `n = 2` and then
`n = 3`
**When** the drain runs
**Then** the reaction logs one call, `(3, <the value before>)`
**And** when the two assignments bring `n` back to the last delivered value,
nothing is logged

#### RSTATE-030 — Alive reactions

Rules: R12.5.

**Given** a VM with an alive reaction over the state `n`, never constructed
**When** the VM is activated
**Then** the handler is not called
**When** `n` changes
**Then** the handler is called
**When** the VM is constructed, destructed, and `n` changes while Destructed
**Then** the handler is called for that change too
**When** the VM's disposal starts and `n` changes during the disposal
**Then** the handler is not called

#### RSTATE-031 — Construct and destruct failures with reactions

Rules: R12.7, R12.12, R13.1, R13.2.

**Given** a VM with the setups S1 and S2, which log their start and stop, and
the setup S3, which throws
**When** the VM is constructed
**Then** the log is `S1.start, S2.start, S2.stop, S1.stop`, the construct throws
S3's error, and the status is Destructed
**Given** a constructed VM with an effect and an `_onDestruct` hook that throws
once
**When** the VM is destructed
**Then** the effect stopped, the destruct throws, the status is Constructed, and
the effect started again once, after the rollback was published
**Given** a constructed owner whose member fails to destruct
**When** the owner is destructed
**Then** the owner rolls back to Constructed, and its stopped reactions start
again
**Given** a constructed VM
**When** an effect whose first run throws is registered
**Then** the registration throws that error, and the effect runs again when its
input changes
**And** Swift: setups and effect runs cannot throw; the test checks the destruct
clauses

#### RSTATE-032 — Dispose order and retention

Rules: R5.6, R13.3, R17.1, R17.2.

**Given** a constructed VM with a member, an effect and a `whileConstructed`
setup, which log their cleanup and teardown, an alive reaction, a helper
command, an `own()` resource and a dispose hook, each logging
**When** the VM is disposed
**Then** the log is: the setup's teardown and the effect's cleanup, last
registered first; the member's disposal; the VM's Disposed message; the dispose
hook; the `own()` resources and the command, last registered first
**And** the alive reaction runs no more
**When** a computed of the disposed VM is read
**Then** it returns its last value and records no dependency
**And** a computed of a disposed VM that was never evaluated calls its getter
**Given** a VM with a computed, a memo, a command with a tracked predicate, an
effect and an alive reaction, all reading the state of a long-lived VM S
**When** the VM is disposed and dropped, and S keeps changing
**Then** a weak reference to the disposed VM is cleared after a collection
(§4.7)
**When** an effect disposes its own VM
**Then** the effect keeps no dependency on the nodes it read

#### RSTATE-033 — `keyedResource`

Rules: R11.1, R14.1, R14.4, R14.5.

**Given** an owner O with the state `topic = "t1"` and `hidden = false`, and
`query = keyedResource({ key: () => topic, enabled: () => !hidden, load })`,
whose loads the test records and completes
**When** (setup only)
**Then** `query` is an `AsyncResourceVM` member of O named `<O's name>:resource`
with O's hub, and a walk of O yields it
**When** O is constructed
**Then** no load starts
**When** `query.load()` is called and completes, `topic` is assigned `"t2"` and
then `"t3"`, and the test completes the load of `"t3"` and then the load of
`"t2"`
**Then** loads ran for `"t1"`, `"t2"` and `"t3"`, the completion of `"t2"` is
ignored, and the final state is Ready for `"t3"`
**Given** the same owner with `autoLoad` true and an activated computed over
`query.state`
**When** O is constructed
**Then** one load starts with `"t1"`, and the computed is announced when it
completes
**When** O is disposed
**Then** `query` is disposed

#### RSTATE-034 — `followKey` and the construct and destruct cycle

Rules: R14.2, R14.3, R14.4.

**Given** the owner of RSTATE-033 with `autoLoad` true, constructed, with a load
of `"t1"` in flight
**When** `hidden` is assigned true
**Then** the load is cancelled, and the state returns to Idle
**When** `hidden` is assigned false
**Then** a new load starts with `"t1"`
**Given** a completed load of `"t1"`
**When** `hidden` is assigned true, `topic` is assigned `"t2"`, and `hidden` is
assigned false
**Then** exactly one load starts, with `"t2"`
**When** O is destructed while a load is in flight, and constructed again
**Then** the destruct cancelled the load, and the construct started it again
**When** O is destructed, `topic` changes, and O is constructed
**Then** no load starts while O is Destructed, and the construct loads the new
key
**Given** a load that failed, so the state is Error
**When** the driver is disabled and enabled again
**Then** a reload starts
**Given** `cancelWhenDisabled` false
**When** the driver is disabled during a load
**Then** the load continues
**Given** an owner with the state `page = 1`, a member resource whose loader
reads `page`, and a `followKey` driver over it with `autoLoad` true, whose
`key()` returns `page` and throws when `page` is negative; the owner is
constructed, so the load of page 1 ran
**When** `page` is assigned −1, then −2, then 2
**Then** loads ran for pages 1 and 2 only, and one error was reported (Swift: a
`key()` cannot throw; the test skips this clause)
**And** TypeScript and Python: `followKey(this, ...)` on a subclass of
`AsyncResourceVM` follows the same rules

#### RSTATE-035 — Native nodes: the library's own messages come before their dependents' messages

Rules: R15.1, R15.2.

**Given** an activated VM W with a computed over the `model` of a modeled VM M,
and a recorder of the hub and of M's local surface
**When** M's model is assigned
**Then** M's `model` messages, and its `modeledHint` messages when the hint
changed, come before W's announcement
**And** a hub observer of M's `model` message that subscribed before W reads W's
computed with the new value
**Given** a computed over the `status` of another VM V
**When** V is constructed
**Then** V's status messages come before the computed's announcement, and an
observer of V's Constructed message reads the computed with the new value
**Given** a computed over a composite's `current` and over the `isCurrent` of
its two children, whose value does not change when the selection moves from one
child to the other
**When** the selection moves
**Then** the computed is evaluated once and is not announced
**Given** a hub observer that writes a state of W while M's model is published
**When** M's model is assigned
**Then** W's announcement comes after M's own hub message and local emission
**Given** a computed that reads, without `read()`, the `count` of a container
and the `isExpanded` of an `ExpandableState`
**When** a child is added, and the expansion toggles
**Then** the computed is evaluated again and announced each time
**Given** a listener of a command's `CanExecuteChanged` that subscribed first,
and a computed over that command's `canExecute()`
**When** the command raises
**Then** the listener reads the computed with the new value

#### RSTATE-036 — `read()` interop

Rules: R15.3, R15.4, R19.4.

**Given** a VM L that notifies its `count` by hand, and an activated VM W whose
computed reads `read(L, "count")`
**When** L changes `count` and calls the helper
**Then** the hub sees L's `count`, then W's computed, and W's computed reads the
new value
**Given** a VM M that registers the state `count`, and W's computed reads
`read(M, "count")`
**Then** `explain(W, <computed>)` names M and `count`
**And** a write of M's `count` announces W's computed
**Given** a VM N, and W's computed that read `read(N, "count")` before N
registered `count`
**When** N registers `count` and writes it
**Then** W's computed is evaluated again
**When** `read` is called on a plain object
**Then** it raises the usage error
**And** `read` follows `isExpanded` of an `ExpandableState` and `isExecuting` of
an async command

#### RSTATE-037 — Threading

Rules: R13.4, R18.1 to R18.9.

**Given** C#, Python, Swift or Rust, and an activated VM with the state `a`, the
computed `b = a + 1`, and an observer of `b` that records its thread and checks
that no other observer call is in progress
**When** two threads assign `a` many times
**Then** every write is applied, `b` equals `a + 1` when both threads finish,
and no two observer calls overlap
**Given** an observer of `b` that runs on the drainer and calls `H.send` on a
hub H while another thread T holds `H.batch`, so that the observer's send waits
for T's batch (a wait that the wait-for graph records, spec 03 §4.1)
**When** T, inside that batch and after the observer started waiting, assigns
`a`
**Then** T's wait for the reactive drain is refused, because it closes the cycle
drainer → H's batch → T → reactive drain
**And** T's write commits and returns, T's batch exits, the observer's send
completes, and the drainer delivers T's announcements in FIFO order after the
observer returns
**Given** a change scope open on one thread
**When** another thread assigns `a`
**Then** that write waits until the scope exits, and then settles on its own
(R18.1)
**Given** a dispose of V from one thread while a construct or destruct hook of
V runs on another thread
**Then** V publishes Disposed first, disposes its members after the hook
completes, and runs `_onDispose` after that (R13.4)
**Given** a dirty computed
**When** a thread that does not hold the drain reads it
**Then** it reads the current value, and the node stays dirty: its stored value
and dependencies did not change
**Given** a getter that waits for another thread that reads a node
**When** the getter runs in a settle
**Then** no deadlock occurs: no VMx lock is held while the getter runs
**And** TypeScript: a write in a later job, after an `await` or in a timer,
settles and delivers its announcements before it returns

#### RSTATE-038 — Producer order

Rules: R9.5, R9.8.

**Given** an activated VM P with the state `a` and the computed `b = a + 1`, and
a hub observer that calls P's helper for the unregistered name `note` when it
receives P's `a`
**When** `a` is assigned
**Then** the hub sees `a`, `b`, `note`
**Given** an observer that, during that flush, writes a state of P
**Then** the announcement of that write also comes before `note`
**Given** a hub observer of P's `a` that first assigns a signal of P that a
command predicate and an effect of P read, and then calls P's helper for
`note`
**When** `a` is assigned
**Then** the hub sees `note` before the command raises and before the effect
runs again: both stay queued behind the send
**Given** P with a queued announcement
**When** P's status changes
**Then** the queued announcement comes before the status message
**Given** a hub observer that disposes P while P's announcement is queued
**When** the drain runs
**Then** the queued announcement comes before P's Disposed message, and nothing
of P comes after it

#### RSTATE-039 — Equalities run in their own context

Rules: R6.5, R6.10, R16.11.

**Given** an activated VM with the state `x`, whose custom equality reads the
state `s` of another VM and counts its calls, and a constructed effect that
assigns `x`
**When** `s` changes
**Then** the effect does not run again: the equality's read is no dependency
**When** `x` is assigned a new value
**Then** the equality was called once for that pair of values
**Given** an equality that assigns a state
**When** a write calls it
**Then** the assignment inside it throws `ReactiveWriteError` and is not applied,
the comparison counts as not equal, so the write is accepted, and the error is
reported once
**And** Swift: an equality cannot throw, and the assignment inside it traps;
the test checks the first clause only
**And** Rust: a `PartialEq` or an equality closure cannot fail; the `set()`
inside it returns `Err(VmxError::ReactiveWrite)` and is not applied, the
equality's own result decides the write, and nothing is reported

#### RSTATE-040 — Registration scopes and handles

Rules: R12.10.

**Given** a constructed VM with an effect, a reaction and a `whileConstructed`
setup, each logging its cleanup or teardown
**When** each handle is called twice
**Then** each cleanup or teardown ran once, and later changes run nothing
**Given** an effect whose run registers an inner effect for the current mode
**When** the mode changes three times
**Then** one inner effect is active, and each replaced inner effect was cleaned
up
**Given** an effect registered in `_onConstruct`
**When** a destruct rolls back, then a destruct completes, then a construct runs
**Then** one copy runs after the rollback, none after the completed destruct,
and one after the construct
**Given** an effect run that calls the effect's own handle and returns a cleanup
**Then** the cleanup runs at once, exactly once
**Given** a computed whose getter calls a handle
**When** it is read
**Then** the read throws `ReactiveWriteError` (Swift: the call traps and is not
tested)
**When** a reaction is registered after the VM's disposal started
**Then** its handle does nothing
**And** Rust: dropping a handle removes its reaction, and a handle that was
detached keeps the reaction for its scope

#### RSTATE-041 — Reaction starts are drain entries; the skip rule

Rules: R9.2, R12.9.

**Given** a VM with the state `a = 0` and an effect that counts how deep it is
nested and assigns `a = 1` when it reads `a = 0`
**When** the VM is constructed
**Then** the effect ran twice, first with 0 and then with 1, and was never
nested
**Given** an effect that assigns `b = a * 2` and then reads `b`
**When** `a` changes
**Then** the effect runs once for that change
**Given** an effect that reads `b` and then assigns `b = a * 2`
**When** `a` changes
**Then** the effect runs once more after the run in which its write changed `b`
**Given** an immediate reaction whose handler assigns the state that its select
reads
**When** the reaction starts
**Then** the handler's write is delivered after the start returns, and the
reaction runs once more with the new value
**Given** a construct that fails because an effect's first run throws
**Then** that effect does not run again before the next construct

#### RSTATE-042 — Keyed-driver policy options

Rules: R14.6.

**Given** the owner of RSTATE-033 with `autoLoad` true and `retryOnEnable` false,
whose first load failed, so the state is Error
**When** the driver is disabled and enabled again
**Then** no load starts
**When** the key changes while the driver is enabled
**Then** a load starts
**Given** the owner with `autoLoad` false and `resumeCancelledFirstLoad` false,
and a first load that the test started with `load()`
**When** the driver is disabled during that load and enabled again
**Then** the load was cancelled, the state is Idle, and no load starts at the
enable
**When** the key changes while the driver is enabled
**Then** no load starts
**When** the test calls `load()`
**Then** a load starts, and a later key change starts a reload
**Given** the default options, `autoLoad` false, a first load that the test
started with `load()`, a disable during that load, and an enable
**Then** the enable starts the cancelled first load again

#### RSTATE-043 — The keyed driver's error route

Rules: R14.7.

**Given** an owner with a keyed resource and `autoLoad` true, subscribers to the
`errors` channels of the resource's load and reload commands, and a stream-fed
recorder
**And** C# and Python: a `CanExecuteChanged` handler of the resource's load
command that throws once, so the publication of the Loading state fails and the
intent rejects (spec 03 §3.6, the call-fed route)
**When** the owner is constructed and the driver starts the load
**Then** the rejection is emitted once on the load command's `errors` channel,
and nothing from the driver reaches the stream-fed route
**When** the reload command's handler throws once and the key changes
**Then** the rejection is emitted on the reload command's `errors` channel
**When** the resource is disposed before a rejected intent completes
**Then** nothing is emitted
**And** TypeScript, Swift and Rust: no handler failure rejects an intent (spec 03
§3.6). The test shows that a throwing handler leaves both `errors` channels
silent, and that the stream-fed route receives only the handler's own failure,
once

#### RSTATE-044 — Development diagnostics

Rules: R19.1 to R19.13.

**Given** development diagnostics on and a sink that the test captures
**When** a consumer reads a computed whose getter reads a plain field that
changed without a tracked dependency, and a task passes
**Then** the sink receives one report that names the class and the computed
**And** a second such read adds no report
**And** the getter's evaluation count right after the read did not change: the
check ran on the later task
**When** TypeScript, Python and C#: a VM with a public getter that reads
registered state but is not registered is activated, and a task passes
**Then** one report names the getter
**And** a getter that reads only the model of a `ReadonlyComponentVMOf` is not
reported
**When** a hand-written helper call names a registered name
**Then** one report names it
**When** a predicate raises `ReactiveWriteError`
**Then** `canExecute()` is false, and one report names the class and the error
kind
**When** a state write happens on a VM with computeds that is not activated, and
a task passes without an activation
**Then** one report names the class
**When** a keyed driver reloads for a key that is structurally equal to its
started key
**Then** one report names the class (Rust: only under a custom `equals`, R19.1;
Swift: only under the default equality, §4.5)
**When** state is registered after activation
**Then** one report names the class
**When** TypeScript: an effect returns a promise
**Then** one report names the class
**When** the same misuses happen with development diagnostics off
**Then** the sink receives nothing, and every value and announcement is the same
as with diagnostics on

#### RSTATE-045 — Library operations and deliveries run untracked

Rules: R5.7, R5.8.

**Given** a VM W with the state `z`, an `ExpandableState` E, and a VM H with the
state `go`, whose effect reads `go`, calls `E.toggleExpansion()` (a library
operation that reads `isExpanded`), and then calls H's helper for the
unregistered name `note`
**And** a hub observer of H's `note` that reads W's `z`
**When** H is constructed
**Then** the effect ran once, and E is expanded
**When** other code collapses E, and then W's `z` changes
**Then** the effect does not run again: neither the toggle's read of
`isExpanded` nor the observer's read of `z` is a dependency of the effect
**When** `go` changes
**Then** the effect runs once more

#### RSTATE-046 — Registration after disposal started, and registration on a forwarding decorator

Rules: R3.4, R3.6, R3.8.

**Given** a VM V with a signal `s = 1` and a memo `twice` over `s` that was read
once
**When** V is disposed, then registers the state `x = 1`, and then writes
`x = 2` through that registration
**Then** no error is raised, and nothing is announced
**And** C# and Rust: the returned state node reads 1
**And** TypeScript and Python: V has no accessor `x`, and the writer ignores
the call (TypeScript: `x` reads undefined; Python: a read of `x` raises
`AttributeError`, or, when an earlier instance of the class installed the
descriptor, it delegates to the attribute that the descriptor replaced)
**And** Swift: every wrapper is bound before activation (§4.5), so Swift has no
state registered after activation, and the test skips this clause
**When** `s` is assigned 5
**Then** the write is ignored: `s.peek()` returns 1, and `twice` returns 2
**When** the disposed V creates a signal with 3 and assigns it 4
**Then** a read of that signal returns 3
**Given** a forwarding decorator D over a modeled VM M with the model 1, where D
registers the computed `doubled` (the model times 2) and an effect that logs
`doubled`
**When** D is constructed, and then M's model is assigned 5
**Then** the effect logged 2, then 10, and the hub saw `doubled` once, with M as
the sender (ADR-0221)
**When** D is disposed, and then M's model is assigned 6
**Then** the effect logged nothing more

#### UTIL-005 — Walks visit registered members

Rules: R11.6 (chapter 13 §2, §3, §5; ADR-0236 §2.4).

**Given** a container C (C#: a subclass of `CompositeVMBase<VM>`) with the
child X, where C registered the member M1 and M1 registered the member M2
**When** `walk(C)` runs
**Then** it yields C, X, M1, M2, in that order
**Given** an aggregate A whose slot holds S and that registered the member N
**When** `walk(A)` runs
**Then** it yields A, S, N (C#: aggregates are sealed and have no members,
R11.6; the test skips this clause)
**Given** a VM whose own child hook (spec 13; TypeScript `Symbol.iterator` or
`components()`, Python `__iter__` or `components()`, C#
`IEnumerable<IComponentVM>`, Rust `try_children_nodes`) already yields one of
its members
**When** it is walked
**Then** that member is yielded once (Swift has no such hook)
**When** `walkExpanded` reaches a collapsed node with children and members
**Then** it yields the node and none of its children or members
**When** `find` runs with a predicate that holds for M1
**Then** it returns M1 and does not visit M2

### 5.3 Chapter edits

The edits land with chapter 24, in the pull request that adds the conformance
IDs (§7, phase 10). Each item names the section and the change.

- **Chapter 24 (new), "Registered reactive state".** It states R3 to R19 as
  normative text, in this order: scope; terms (§2 of this document);
  registration; activation; tracking; writes and settles; change scopes;
  ordering; the drain; commands; members and services; reactions; sequences;
  keyed resources; native nodes and `read`; errors; disposal and retention;
  threading; development diagnostics; the API table per flavor (§4.1 to §4.7 in
  short); and a Conformance section that maps every `RSTATE` ID to its rules.
  It keeps the rule numbers of this document as stable anchors.

- **Chapter 02 (lifecycle).**

  - §2.2: the construct and destruct hooks run inside the sequences of R13.1
    and R13.2; `OnConstruct` runs after activation, and the member walk and the
    reaction starts follow it.
  - §2.3: "Per-construct resources still belong in `OnConstruct` /
    `OnDestruct`" becomes "Per-construct resources belong in a
    `whileConstructed` registration (chapter 24 R12.6) or in the `OnConstruct`
    / `OnDestruct` pair" (ADR-0237).
  - §2.5: a failed construct stops the started reactions in reverse order; a
    failed destruct starts the stopped reactions again after the rollback
    (R13.1 step 5, R13.2).
  - §6.1: members registered with `member()` are walked automatically, with the
    rules of the helper (R13.1 step 4, R13.2 step 4); the helper stays the tool
    for `ownMember` members.
  - §7: the dispose order gains the reaction teardown before the children and
    the delivery of queued announcements before Disposed (R13.3 steps 2 and 4).
  - §7.1: a new paragraph: a member registered with `member()` (chapter 24 R11)
    is also constructed and destructed with its owner, and it leaves the
    owner's list when it reaches Disposed (R11.5). The other rules of §7.1
    apply to it unchanged.
  - §9: rows for `RSTATE-025`, `RSTATE-026`, `RSTATE-031`, `RSTATE-032` and
    `RSTATE-040`.

- **Chapter 03 (messages).**

  - §3.2: a VM's graph announcements and its direct sends keep producer order
    (R9.8).
  - §3.3: a paragraph on the reactive drain of chapter 24: one FIFO queue per
    process with the same rules (lossless per settle, FIFO, no recursion, a
    throwing scope body still drains, a development bound that counts
    repetitions of one entry). The graph never opens or closes a hub
    transaction (R7.5, R9.7).
  - §3.6: the graph's failures that have no caller (an equality that throws, a
    computed's error report, a failing reaction, a failing keyed-driver
    selector) take the stream-fed route (R16). In C# and Python, the drain
    rethrows the first call-fed failure of a helper call or a
    `RaiseCanExecuteChanged` from the call that ran it, after the queue is
    empty (R16.10).
  - §4.1: a new row: "A write, a direct send or a library publication on a
    foreign thread waits for the reactive drain | The drainer | The write
    commits and appends a settle request; a send is appended behind the VM's
    queued announcements (chapter 24 R18.2, R18.8)". Rule 2 adds "the reactive
    drain" to the resource instances.
  - §7.1, §7.2 and §7.4: in C#, Python, TypeScript and Swift, a subscription to
    these helpers activates the VM that they name as the sender (R4.2 f). The
    Rust sentence of §7.4 gains: a Rust host calls `vmx::reactive::activate`,
    because `subscribe_value` names the sender only by `sender_id`.
  - §8: rows for `RSTATE-009`, `RSTATE-014`, `RSTATE-015` and `RSTATE-038`.

- **Chapter 04 (commands).**

  - §2: the predicate's reads are tracked (R10.2); a throwing predicate still
    reads as false and keeps its reads (R10.4).
  - §4: triggers stay for inputs outside the graph; a predicate over registered
    state, native nodes or other commands needs no trigger (R10.3, R10.7). The
    library commands keep their triggers and raises (R10.10).
  - §4.2: a consumer command whose predicate reads graph nodes (for example a
    composite's `current`) needs no trigger (R10.2); the trigger stays for
    inputs outside the graph. `ModeledCrudCommands` builds library commands
    (R10.10), so its current-changed trigger stays RECOMMENDED (chapter 06
    §7). The sentence "A predicate alone is insufficient" is limited to inputs
    outside the graph and to library commands.
  - §8.2: the extra predicate of a `DecoratorCommand` is tracked, and its raises
    merge with the forwarded ones (R10.8).
  - §10.2: `IsExecuting` is a native node (R10.5).
  - A new section before §11, "Commands created by a view-model": the helpers
    of R10.1 and their ownership; §11 Conformance moves to §12.
  - Conformance: rows for `RSTATE-022` and `RSTATE-023`.

- **Chapter 05 (component VM).**

  - §2: the member list gains a line that points to the protected helpers of
    chapter 24.
  - §2.2: `member(Type, options)` injects the owner's hub and dispatcher (R11.2);
    the per-construct sentence names `whileConstructed`.
  - §2.3, last paragraph: the paragraph that this decision changed to record the
    adopted direction becomes normative: registered state and computed
    properties are a property-authoring convenience in which the graph decides
    acceptance with each node's equality and calls the helper once per changed
    name; the helper itself still neither stores nor compares (ADR-0083 §4.4).
  - §3: `Model` and `ModeledHint` are native nodes, committed before their
    messages (R15.2).
  - §8.1 rule 6: a registered computed over `IsExpanded` publishes under the
    owner's names; an owner that does not register still forwards
    `IsExpandedChanged` (chapter 14 rule 6 stands).

- **Chapters 06, 07, 08 and 18 (containers).** A container refuses a VM that
  has an owner (chapter 24 R11.3) before it changes anything, with the usage
  error of its other refusals, inside its membership transaction:

  - chapter 06 §2, §4.2 and §5: `CompositeVM` add, insert, replace, population
    and transfer;
  - chapter 07 §1 and §1.1: the same for `GroupVM`;
  - chapter 08 §2: a slot factory that returns a VM that has an owner fails
    the population, as any factory failure does;
  - chapter 18 §7: `AddChild` and `ReparentChild` refuse such a child as they
    refuse an invalid structural mutation, and `AttachMany` (§6) returns it as
    an `AttachmentFailed` rejection.

  Each chapter's Conformance section gains a row for `RSTATE-024`.

- **Chapter 11 (threading).**

  - §3: graph announcements are helper calls and follow §3; reaction runs happen
    on the drainer (R18.5).
  - §6.1: "There is no global scheduler" gains one exception, the development
    diagnostics scheduler of chapter 24 R19.12, a development setting that no
    delayed-work consumer uses.
  - A new section before §7, "The reactive drain", with R18.1 to R18.9; §7
    Conformance moves to §8 and gains `RSTATE-037`.

- **Chapter 13 (tree utilities).**

  - §2 and §5: the pseudocode adds
    `for member in root.members (registration order): if not yielded: walk(member)`
    after the children and slots; "A leaf `ComponentVM` yields exactly itself"
    becomes "A leaf `ComponentVM` yields itself, then its registered members".
    A VM registered only with `ownMember` stays outside the walk; #1612 decides
    the other child hooks of each flavor.
  - §3: `find` follows the new walk order.
  - §7: a row for the walk's `UTIL` ID (`UTIL-005` when this was written);
    chapter 12 §14 gains its entry.

- **Chapter 23 (async resource).**

  - §1: an owner can declare a keyed driver (chapter 24 R14) that starts and
    cancels the resource's intents by the owner's policy; the resource itself
    stays free of lifecycle coupling, and `autoLoad` defaults to false.
  - §4: a keyed driver uses `Load`, `Reload` and `Cancel` like any caller,
    through the per-flavor calls of the table after R14.4.
  - §7: a rejection of an intent that a keyed driver started goes to the
    `Errors` channel of the matching command (R14.7).
  - §11: rows for `RSTATE-033`, `RSTATE-034`, `RSTATE-042` and `RSTATE-043`.

- **Other files.** Chapter 01 §2 notes that the dependency tracker is VMx-owned
  in every flavor and adds no reactive library (ADR-0101). Chapter 15 notes the
  distinction of ADR-0011: `DerivedProperty` stays the stream-composition
  primitive, and a registered computed derives from view-model state and
  publishes on the hub. `spec/README.md` lists chapter 24. The chapter range
  and count of AGENTS.md §1, the spec tree of `README.md`,
  `docs/content/specification-conformance.md` and
  `docs/content/architecture/system-architecture.md` gain chapter 24. The
  Disposal Contract inventory (`docs/content/primitives/disposal-contract.md`,
  which chapter 01 §4 requires) lists the reaction handles of each flavor,
  whose removal is idempotent (R12.10). When the fixture of §5.4 is added,
  every "four JSON fixtures" statement (AGENTS.md §1,
  `docs/content/architecture/system-architecture.md`) changes too. The
  public-API baselines, the flavor CHANGELOGs, `compatibility-matrix.md` and
  the documentation guides follow AGENTS.md §4.

### 5.4 Optional fixture

`spec/fixtures/reactive-ordering.json` MAY encode the scenarios of R6.9, R7.2,
R8.1 and R9.4 for all flavors, in the style of `message-ordering.json`:

```json
{
  "$schema-version": "1.0.0",
  "computeds": {
    "b": "a + 1",
    "c": "a * 10",
    "d": "b and c joined with ':'"
  },
  "scenarios": [
    {
      "id": "diamond-one-write",
      "description": "One write of a evaluates d once and announces each value once (R6.9).",
      "state": { "a": 1 },
      "writes": [[{ "a": 2 }]],
      "expected_announcements": ["a", "b", "c", "d"],
      "expected_evaluations": { "d": 1 }
    },
    {
      "id": "changed-back-in-one-scope",
      "description": "A value that changes and changes back in one change scope is not announced (R7.2).",
      "state": { "a": 1 },
      "writes": [[{ "a": 9 }, { "a": 1 }]],
      "expected_announcements": []
    }
  ]
}
```

Each inner array of `writes` is one change scope. The test of each flavor
implements the named computeds. When the fixture is added, TypeScript's
`sync-fixtures` copies it, C# copies it into the conformance output, Swift adds
it to `Sources/VMx/Resources`, and the Python and Rust conformance tests read it
as they read `message-ordering.json` (AGENTS.md §1).

## 6. Decided open questions

The prototype's design left thirteen questions open. Each one is decided with
the recommended option. Two lessons of the client rewrite add rows 14 and 15.
Rows 16 to 19 were decided while this document was reviewed, where the
prototype's design was silent or did not fit every flavor.

| #   | Question                                                                                                                                                                                                              | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Rules          |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| 1   | A dependency taken through `read()` before the source registered the name stays on the announcement node, which the graph's own announcements did not bump. Bump it?                                                  | Bump. Every emission of the name, the graph's own announcement included, bumps an announcement node that exists. The cost is one extra evaluation per such frame: after it, the frame reads through the node.                                                                                                                                                                                                                                                                                                                                                                                                           | R15.3          |
| 2   | Members dispose in registration order but destruct in reverse order. Dispose last in, first out too, with an order option?                                                                                            | Keep registration order for dispose, as spec 02 §7.1 and `LIFE-018` already require, and reverse order for destruct, the mirror of construct. No order option for members: an owner that wants another order registers in that order.                                                                                                                                                                                                                                                                                                                                                                                   | R13.2, R13.3   |
| 3   | A destructed VM that something retains keeps computing. Pause it?                                                                                                                                                     | Keep computing, and document it. No pause option now. Work that must wait for the next construct belongs in a constructed-kind reaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | R4.6           |
| 4   | The producer flush delivers announcements ahead of earlier command raises and reaction runs. Deliver the whole queue prefix instead?                                                                                  | Keep the flush to announcements. Delivering the prefix would run reactions nested inside a direct send, the recursion that R12.9 removes.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | R9.8           |
| 5   | Container membership is announced on the collection channels. Make `count` and the children native nodes, so a direct read is tracked?                                                                                | Yes. VMx tracks them natively and commits them at the local collection-change emission.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | R15.1          |
| 6   | The staleness check costs one evaluation per node per task in development. Make it opt-in?                                                                                                                            | Keep it on in development, under the switch of the hub's development bound. Production never runs it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | R19.1, R19.11  |
| 7   | A live member cannot be moved to another owner. Add a release operation?                                                                                                                                              | No. No consumer asked for it. A changing set of children belongs in a container.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | R11.5          |
| 8   | `_onDestruct` runs after the members were destructed. Add a hook that runs before them?                                                                                                                               | No. The teardown of a `whileConstructed` registration runs before the members destruct and serves that need.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | R13.2          |
| 9   | Recommend `_onConstruct` for per-construct reactions, or keep the constructor as the one place?                                                                                                                       | Keep the constructor and field initializers as the documented place. A registration in `_onConstruct` stays legal and is construct-scoped.                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | R3.7, R12.10   |
| 10  | Offer an edge-triggered `reaction()` that calls its handler once per announcement?                                                                                                                                    | No. Reactions stay level-triggered. A handler that needs every transition subscribes to the announcements.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | R12.11         |
| 11  | R10.7 evaluates a computed over a command once more after each raise that the graph caused. Exclude commands without explicit triggers?                                                                               | No. Every command keeps R10.7, so an imperative raise always reaches the dependents. The extra evaluation finds an equal value and announces nothing.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | R10.7          |
| 12  | Members that a failed destruct of the owner already destructed stay Destructed while the owner is Constructed.                                                                                                        | No change. Spec 02 §6.1 holds, and the question of undoing siblings stays open in the cross-flavor decisions ledger.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | R13.1, R13.2   |
| 13  | The owner's gates: the decision on plan D21 (#1997) and a pilot in a second consumer.                                                                                                                                 | Plan D21 is decided: adopt (ADR-0234). The pilot is a recommended validation step, tracked as a follow-up, not a gate.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | §1             |
| 14  | The client's rewrite: the unpublished-getter check reported getters that read only immutable state, such as the identity fields of a read-only model.                                                                 | Exempt them. Reads of immutable library values do not count.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | R15.1, R19.2   |
| 15  | The client's rewrite: some owners' rules for hidden content did not fit the driver (no retry on re-enable; a cancelled first load stays on demand), and a rejected load went to the platform's unhandled-error route. | Two policy options, and an error route through the `errors` channels of the resource's own commands.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | R14.6, R14.7   |
| 16  | Frame storage. The prototype's design put the current frame in a context value (C# `AsyncLocal`, Python `contextvars.ContextVar`, a Swift task-local). Keep that, or store frames per thread?                         | Per thread (`[ThreadStatic]`, `threading.local`, a Swift thread-local, `thread_local!`), which departs from the prototype's design. A per-thread frame adds one hazard, a continuation that runs inline on the frame's thread; R18.7 handles it by clearing the frame around every library call-out. A context value flows into the tasks and continuations that a frame starts, so code after an `await` would run in a closed frame or an open change scope, against R7.4 and R12.3. Python's `with` scope therefore must not contain `await`, and another task's write while a scope is open raises the usage error. | R7.4, R18.7    |
| 17  | Library commands whose predicates read native nodes and that also raise through their own triggers (for example the TypeScript `FormVM` approve command): track them too?                                             | No. Library commands keep today's raises and run their predicates untracked, so the exact counts of the existing IDs hold. R10.7 still reaches a frame that calls their `canExecute()`. The closed list of R10.10 is the list of ADR-0235 §2.2 rule 2, `ModeledCrudCommands` included, whose current-changed trigger therefore stays.                                                                                                                                                                                                                                                                                   | R10.10         |
| 18  | Swift computed functions cannot throw. Trap on every cycle, or recover as the other flavors do?                                                                                                                       | Recover. Inside an evaluation, a plain read that closes a cycle returns the last value and fails the frames of the cycle, which recover when the cycle opens. A read traps only when no last value exists.                                                                                                                                                                                                                                                                                                                                                                                                              | R16.8          |
| 19  | The development switch is a build constant in C#, Python, Swift and Rust, and the C# CI runs the tests in Release. How do the "diagnostics on" and "off" cases run?                                                   | A process-wide override, gated at run time, which the tests set (R19.13), and a process-wide diagnostics scheduler for later tasks, which the tests replace with a virtual-time scheduler (R19.12).                                                                                                                                                                                                                                                                                                                                                                                                                     | R19.12, R19.13 |

## 7. Implementation plan

### 7.1 Phases and dependencies

Each flavor implements the phases in this order. A phase depends only on the
phases named in its row, so phases 4 and 5 can run in parallel. TypeScript goes
first, because the prototype is TypeScript; the other flavors can start phase 1
once TypeScript's phase 1 is reviewed, and then proceed in parallel.

| Phase | Content                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Rules                                             | Depends on                    | Prototype tests to port                                                                                                                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | Tooling: widen the ID pattern of `tools/check-conformance-*.py` from three to five letters to three to six, with tests. No flavor change.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | §5.1                                              | none                          | none                                                                                                                                                                                     |
| 1     | Graph core, internal: nodes and versions; per-thread frames; `track`, `untracked`, `peek`; the settle (coloring, height order, equality cut-off); epochs, snapshots and the changed set; change scopes; the drain with its three entry kinds and the skip rule; the producer-flush primitive with per-VM counts; the development switch and its test override (R19.11, R19.13) and the development bound that they gate; error state, error equality and cycles; `ReactiveWriteError`; the equality context.                                                                                                                                                                                                                                   | R5.1 to R5.6, R6, R7, R8, R9, R16, R19.11, R19.13 | none                          | `settle`, `errors`, `tracking` (through a minimal test VM); `attack-r1-cycles`, `attack-r2-cycles`, `attack-r1-memo`, `attack-r2-memo`                                                   |
| 2     | Registration and activation on the component base: state, signals, computeds, memos, `invalidate`, `change`; the accessors of each flavor; announcements through the helper; activation triggers (a), (b) and (e), and the container parts of (c) and (d); the cascade over container children and forwarding decorators, and the baselines; reads after disposal.                                                                                                                                                                                                                                                                                                                                                                             | R3, R4.1 to R4.6 (not R4.2 f), R5.6               | 1                             | `state`, `activation`, `rules` (registration and drain parts)                                                                                                                            |
| 3     | Native nodes and library operations: the inventory of R15.1 in every library class; state first and the publication hold; library operations untracked and refused in frames; producer order at every send path of R9.8 (the helper, the local-only raise, the status transition, the model assignment, the collection-change sends of the containers and serviced collections, the tree-structure sends of `HierarchicalVM`, and the change messages of `FormVM` and `AsyncResourceVM`) and at disposal; `read()` and announcement nodes; trigger (f) in the hub helpers of C#, Python, TypeScript and Swift; TypeScript's `recordPropertyChanges` activates its `filter.sender` (R4.5). Native tracking is behind the internal switch below. | R4.2 f, R5.7, R5.8, R9.5, R9.8, R15               | 2                             | `interop`; `fix-r1` (R9.8, R5.7, R5.8, R15.1); `fix-r2` (R15.2); `attack-r1-ordering`, `attack-r2-ordering`                                                                              |
| 4     | Commands: a frame in every command class and every construction path; the parameterized union; one raise and clear; the raise dependency; combinators; the create-and-own helpers; the untracked library commands (R10.10). Tracked predicates are behind the internal switch below.                                                                                                                                                                                                                                                                                                                                                                                                                                                           | R10                                               | 1, 3                          | `commands`; `fix-r1` (R10.7); `fix-r2` (R10.2); `attack-r1-commands`, `attack-r2-commands`                                                                                               |
| 5     | Members: `member()` and injection; refusals, including the container refusal inside each container's membership transaction (spec 06, 07, 08, 18; the operations of §5.3); late registration; removal at Disposed; the member walks inside construct and destruct (with the helper of spec 02 §6.1); the member parts of activation triggers (c) and (d) and of the cascade; walks that visit members (spec 13).                                                                                                                                                                                                                                                                                                                               | R11, R13.1 step 4, R13.2 step 4                   | 2                             | `members`; `fix-r2` (R11.5)                                                                                                                                                              |
| 6     | Reactions and sequences: effect, reaction, `whileConstructed`, alive reactions; the reaction scope; starts as drain entries; registration scopes and handles; the construct, destruct and dispose sequences; the restart after a destruct rollback.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | R12, R13, R17                                     | 1, 2, 3, 5                    | `reactions`, `dispose`; `fix-r2` (R12.10, R13.2); `attack-r1-reentrancy`, `attack-r2-reentrancy`, `attack-r1-lifecycle`, `attack-r2-lifecycle`, `attack-r1-dispose`, `attack-r2-dispose` |
| 7     | Keyed resources: `keyedResource`, `followKey`, the driver rules, the policy options, and the error route (an internal entry of `AsyncResourceVM` that starts an intent for a driver and sends an unexpected rejection to the matching command's `errors` channel, per the table after R14.4).                                                                                                                                                                                                                                                                                                                                                                                                                                                  | R14                                               | 3, 5, 6                       | `keyed`; `attack-r1-keyed`, `attack-r2-keyed`; new tests for R14.6 and R14.7                                                                                                             |
| 8     | Development diagnostics: the reports, the report sink and the diagnostics scheduler (R19.12), gated at run time by the switch and the override of phase 1.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | R19 (R19.11 and R19.13 in phase 1)                | 2 to 7                        | `diagnostics`; `fix-r1` (R19.6, R19.8); `fix-r2` (R3.13, R12.3); the reports of `attack-r2-misc`                                                                                         |
| 9     | Threading (C#, Python, Swift, Rust): one drain per process; foreign writes, sends and publications that wait, with the refused wait as a new wait-for row; leaf locks; foreign reads of dirty nodes; a change scope that holds the drain; the member list under the lifecycle lock.                                                                                                                                                                                                                                                                                                                                                                                                                                                            | R18                                               | 1 to 8                        | none; new tests for `RSTATE-037`                                                                                                                                                         |
| 10    | Normative text and conformance, in one pull request: chapter 24; the chapter edits of §5.3; the chapter 12 prefix row and entries; the `RSTATE` markers and the walk's `UTIL` marker in all five flavors; the public-API baselines; the CHANGELOGs and `compatibility-matrix.md`; the ADR-0009 rows; the documentation guides; the version bumps (§7.4); a new ADR (the next free number) that records chapter 24 as the normative form of the decision ADRs and lists the chapter edits, with its registry row and the back-links in the Status lines of the decision ADRs (`spec/ADRs/README.md` §2.3), which `tools/check-spec-adr.py` requires; the internal switch turned on (below).                                                     | all                                               | 0, and 1 to 9 in every flavor | the markers go on the tests of phases 1 to 9                                                                                                                                             |
| 11    | Follow-up, not a gate: a pilot in a second consumer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | none                                              | 10                            | none                                                                                                                                                                                     |

How the phases reach `develop`: each phase of phases 1 to 9 lands on `develop`
as its own pull request, with internal code and unit tests, so the flavor's CI
runs on it (the flavor workflows run only for pull requests into `develop` and
`main`). The public surface, chapter 24 and the IDs arrive together in
phase 10. Until then:

- Internal switch. Phases 3 and 4 install native tracking and tracked
  predicates behind an internal switch that is off by default. On `develop`,
  until phase 10, commands keep their current raises, and library operations
  inside predicates are not refused. Unit tests turn the switch on. Phase 10
  turns it on, together with chapter 24 and the IDs.
- Markers. Before phase 10, no test carries an `RSTATE` or `UTIL-005` marker in
  any form that the coverage scraper reads (`tools/check-conformance-coverage.py`
  reports a marker for an ID outside chapter 12 as ORPHAN and fails under
  `--require`). So no `describe("RSTATE-0NN", …)`, no
  `@pytest.mark.conformance` or `[Trait("Conformance", …)]` with these IDs,
  and in Swift no `//` or `///` comment anywhere under `Tests/VMxTests` that
  starts with the ID followed by an em dash. The tests name the rules instead
  (`// R3.1, R6.1`). Phase 10 adds every marker.
- Errors. Until phase 10, Rust reports the reactive errors as the existing
  `VmxError::Other(String)` or a crate-private error type. Phase 10 adds the
  three public variants together with the Rust breaking bump and the baseline
  move of CONTRIBUTING.md §2.8.

Each flavor keeps the new surface out of its public API and its API baseline
(CONTRIBUTING.md §2.8):

- Python: the instance helpers are underscore methods, which the API baseline
  leaves out, and the module is `vmx._reactive`, which the baseline also leaves
  out. Phase 10 renames the module to `vmx.reactive` and updates the baseline.
- TypeScript: the helpers are module functions in
  `src/reactive/helpers.ts`, one per member of §4.2, with the member's name and
  signature and the VM as an added first parameter
  (`observable(vm, initial, equals?)`, `computed(vm, ...names)`,
  `relayCommandOf(vm, task, canExecute?, options?)`, `member(vm, vm2)` and so
  on). New per-instance state lives in module-private `WeakMap`s or `#private` fields,
  so `api/vmx.api.txt` does not change, and `src/index.ts` does not export the
  functions. Phase 10 adds the protected members and the exports, and updates
  `api/vmx.api.txt`.
- C#: the helpers and types are `internal`. `VMx.Tests` and
  `VMx.Conformance.Tests` see them through the existing `InternalsVisibleTo`.
  Phase 10 makes them `protected` or `public` and adds them to
  `src/VMx/PublicAPI.Unshipped.txt`.
- Swift: the members are `internal`, and the tests use `@testable import VMx`.
  Phase 10 makes them `public`.
- Rust: the items are `pub(crate)`, tested in `#[cfg(test)]` modules of
  `src/reactive.rs`. Phase 10 makes them `pub`, moves the tests to
  `tests/conformance`, and adds their `/// RSTATE-NNN — …` markers there,
  because the marker check reads only that folder.

### 7.2 Files per flavor

| Flavor     | New area                                                                                                                                           | Existing files that change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Unit tests (phases 1 to 9)                        | Conformance tests                                                                                                |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| TypeScript | `langs/typescript/src/reactive/`: the graph, equalities, errors, diagnostics, `read`/`activate`/`explain`, the reaction kinds and the keyed driver | `src/components/componentVMBase.ts` (helpers, activation, sequences, member list, flushes and native commits in the send paths), `componentVMOf.ts`, `readonlyComponentVMOf.ts`, `src/commands/*`, `src/composites/*`, `src/groups/*`, `src/aggregates/*`, `src/hierarchical/*`, `src/collections/*`, `src/capabilities/expandableState.ts`, `searchableState.ts`, `src/state/*`, `src/forms/*`, `src/properties/derivedProperty.ts`, `src/tree/walk.ts`, `src/messages/` (hub helpers), `src/testing/recorders.ts`, `src/forwarding/*`, `src/notifications/*`, `src/dialogs/*`, `src/index.ts`, `api/vmx.api.txt` (phase 10); after phase 10, in the adapter's own release, `packages/react/src/useVm.ts` and `useVmChildren.ts` (R4.5) | `langs/typescript/tests/unit/reactive/`           | `tests/conformance/rstate-*.test.ts`                                                                             |
| C#         | `langs/csharp/src/VMx/Reactive/` (namespace `VMx.Reactive`)                                                                                        | `Components/ComponentVMBase.cs`, `ComponentVMBaseOfM.cs`, `Commands/*`, `Composites/*`, `Groups/*`, `Aggregates/*`, `Hierarchical/*`, `Collections/*`, `Capabilities/*`, `State/*`, `Forms/*`, `Properties/DerivedProperty.cs`, `Tree/Tree.cs`, `Forwarding/*` (the helpers of §4.3), `Dialogs/*`, `src/VMx.Notifications/*`, the hub helpers in `Messages/`, the wait-for graph in `Internal/`, and in phase 10 `PublicAPI.Unshipped.txt` next to `VMx.csproj` (`PublicAPI/net8.0/` only for members that only `net8.0` declares; CONTRIBUTING.md §2.8)                                                                                                                                                                                 | `langs/csharp/tests/VMx.Tests/Reactive/`          | `tests/VMx.Conformance.Tests/RSTATE_*_Tests.cs`                                                                  |
| Python     | `langs/python/src/vmx/_reactive/`, renamed `vmx/reactive/` in phase 10                                                                             | `components/base.py`, `components/component_vm.py`, `components/readonly_component_vm.py`, `commands/*`, the container and collection modules, `capabilities/*`, `state/*`, `forms/*`, `properties/derived.py`, `tree/walk.py`, `forwarding/*`, `notifications/*`, `dialogs/*`, `messages/*`, `_wait_for_graph.py`, `__init__.py`, `api/vmx.api.txt` (phase 10)                                                                                                                                                                                                                                                                                                                                                                          | `langs/python/tests/unit/reactive/`               | `tests/conformance/test_rstate_*.py`                                                                             |
| Swift      | `langs/swift/Sources/VMx/Reactive/`                                                                                                                | `Lifecycle/ComponentVMBase.swift`, `Components/*`, `Commands/*`, `Composites/*`, `Groups/*`, `Aggregates/*`, `Hierarchical/*`, `Collections/*`, `Capabilities/*`, `State/*`, `Forms/*`, `Properties/*`, `Tree/*`, `Forwarding/*`, `Notifications/*`, `Dialogs/*`, `Services/MessageHub.swift` (an internal accessor for the diagnostic handler, §4.5), `Services/ThreadWaitGraph.swift` (the reactive-drain wait)                                                                                                                                                                                                                                                                                                                        | `langs/swift/Tests/VMxTests/Reactive*Tests.swift` | `Tests/VMxTests/RStateTests*.swift`                                                                              |
| Rust       | `langs/rust/src/reactive.rs`                                                                                                                       | `components.rs` (`reactive()`), the other VM types with `on_construct`, `commands.rs`, `async_resource_vm.rs`, `hierarchical.rs` (the walks), `forwarding.rs`, `specialized_vms.rs`, `notifications.rs`, `dialogs.rs`, `modeled_crud.rs`, `paged_composition.rs`, `runtime.rs` (`VmxError`), `wait_for_graph.rs`, `lib.rs`                                                                                                                                                                                                                                                                                                                                                                                                               | `#[cfg(test)]` modules of `src/reactive.rs`       | `tests/conformance/reactive_state*.rs`, each declared in `tests/conformance.rs` (`mod conformance { mod ...; }`) |

### 7.3 Done criteria

A phase is done in a flavor when:

- its rules are implemented, and the ported prototype tests and the new tests
  pass in the flavor's suite;
- the flavor's checks pass (CONTRIBUTING.md §2): build, lint, type checks (mypy
  strict in Python), formatting;
- every existing conformance ID still passes, and, with the internal switch
  off (§7.1), no existing public member changes its behavior;
- with the switch on, a VM that registers nothing behaves as before, except
  the raises that R10.2 and R10.7 add to consumer commands whose predicates
  read native nodes (ADR-0235 §3); the library commands of R10.10 keep their
  exact raises;
- the phase's unit tests name the rules they check, so phase 10 can put the
  `RSTATE` markers on them.

Phase 10 is done when the checks of `tools/check-conformance-*.py` pass: the
marker check and the execution check with `--require` for all five flavors, and
the chapter-structure check. The spec-discipline check passes with the new ADR
of phase 10 (`tools/check-spec-adr.py` requires a new ADR for the chapter
edits), and the public-API baselines record the new surface.

### 7.4 Versioning

- The spec takes a minor bump: chapter 24 and the IDs add behavior, and a VM
  that registers nothing behaves as before, except the added raises of
  consumer commands whose predicates read native nodes (R10.2; ADR-0235 §3).
- C#, Python, TypeScript and Swift add members to the component base and
  release as a minor version, unless the new names break existing subclasses;
  then README §6.1 decides the bump (ADR-0234 §2.9). The new protected members
  can collide with members that a consumer's subclass already declares:
  TypeScript reports TS2416 for an incompatible signature, and C# warns CS0108,
  an error under `TreatWarningsAsErrors`. The names collide with no VMx member,
  and the TypeScript names compiled against the 85 view-model files of the
  production client without a collision. Each CHANGELOG lists the new member
  names.
- Rust takes its breaking bump: the three new `VmxError` variants break
  exhaustive `match` expressions (README §6.1).
- Every flavor raises its declared minimum spec version to the release that
  adds chapter 24.

## 8. Evidence and measurements

### 8.1 The client

The evidence comes from a production Vue client (TypeScript in strict mode) on
the published VMx 3.30.0. Its view-model layer has 85 files and
12,701 code lines (lines that are neither blank nor comments). A study recorded
603 findings in it; 229 depend on a VMx change. They group into 28 themes worth
about 2,650 removable lines, and the five themes that this design answers hold
66% of those lines: tracked computed properties, one-line observable state,
owned commands with tracked predicates, construct-scoped reactions, and a keyed
resource. The client is the Vue consumer of the October plan
(`2026-10-20-upstream-candidates-plan.md`), so its rewrite is also the pilot
that plan row D14 asked for.

| Measure in the view-model layer                       | Today   | Client-side changes only | With TypeScript 3.31.0 (unreleased) and this design |
| ----------------------------------------------------- | ------- | ------------------------ | --------------------------------------------------- |
| Hand-written `_notifyPropertyChanged` calls           | 283     | 194                      | 4                                                   |
| Getters / setters                                     | 553 / 3 | 381 / 2                  | 317 / 1                                             |
| Calls that push a change into another view-model      | 69      | 62                       | 0                                                   |
| Function-typed options                                | 114     | 105                      | 99                                                  |
| Command builder chains                                | 117     | 85                       | 0                                                   |
| `.triggers(` calls / `raiseCanExecuteChanged()` calls | 39 / 13 | 16 / 8                   | 0 / 0                                               |
| `.subscribe(` calls                                   | 74      | 66                       | 16                                                  |
| `hub:` arguments passed to members                    | 139     | 26                       | 8                                                   |
| Overrides of lifecycle hooks                          | 83      | 62                       | 5                                                   |

Two pages of the client released their per-visit subscriptions only in
`_onDestruct`, which a `dispose()` from Constructed never runs; they leaked 5
and 10 hub subscriptions on every visit. R13.3 step 2 removes this class of
leak: `dispose()` tears every reaction down first.

### 8.2 The two rewrites

The whole layer was rewritten twice as type-checked prototypes:

| Rewrite                                                         | Code lines | Change | Removed, not counting moved code              |
| --------------------------------------------------------------- | ---------- | ------ | --------------------------------------------- |
| Today, on VMx 3.30.0                                            | 12,701     |        |                                               |
| Client-side changes only                                        | 9,199      | −27.6% | 17.5% (1,282 lines moved to the models layer) |
| With the TypeScript 3.31.0 (unreleased) helpers and this design | 7,470      | −41.2% | 31.1%                                         |
| The same, as a VMx release would read (no prototype stand-ins)  | 7,438      | −41.4% | 31.3%                                         |

- Both rewrites type-check the whole tree under the client's compiler settings
  (tsc 6.0.3, strict). Independent reviews checked both for behavior parity. A
  runtime smoke test ran the second rewrite through 12 scripted scenarios: all
  105 expectations passed, and no value that a view binds changed without an
  announcement. No view needed a change.
- The second rewrite uses 67 computed registrations, 21 state writers, 60
  members, 57 reactions, 8 keyed resources or drivers, and 88 helper commands.
  It deleted 19 methods that pushed changes between view-models.
- Four lessons of that rewrite became decisions: the keyed-driver policy
  options and the error route (R14.6, R14.7), the immutable exemption of the
  unpublished-getter check (R19.2), and the documented computing of destructed
  view-models (R4.6).

### 8.3 The prototype

- **Size.** 17 source files, 3,567 code lines. The import-time wrappers
  (`library.ts`, 296 lines) and the command wrappers are stand-ins that a VMx
  implementation does not need.
- **Tests.** 282 tests pass in two identical runs: 119 written with the design,
  69 from a first adversarial round, 20 from its fix round, 57 from a second
  adversarial round and 17 from its fix round. The adversarial rounds were
  written to break the design. The first found 28 failures and 18 gaps in the
  rules, the second 23 failures and 18 gaps; the rules of §3 resolve all of
  them.
- **Randomized runs.** The suite runs 5 seeds of 400 random operations each and
  checks the invariants. An informative run of 300 seeds of 600 operations,
  with writes and disposals made by observers, also holds.
- **Benchmark** (Node, production mode, three runs): 70 view-models with 10
  computeds each, 5 of them over one long-lived settings view-model.

| Operation                                                       | Time            |
| --------------------------------------------------------------- | --------------- |
| Create 70 view-models (700 computeds registered)                | 3.1 to 3.2 ms   |
| Activate them (700 baselines)                                   | 1.6 ms          |
| One settings write: 350 computeds evaluated again and announced | 0.43 to 0.44 ms |
| The same, with 1 hub subscriber and 70 local subscribers        | 0.40 to 0.41 ms |
| One view-model's own write: 2 computeds, 3 announcements        | 4.4 µs          |

### 8.4 Limits

- One consumer. ADR-0101 §2.3 asks two independent consumers for an interop
  seam; the owner proceeds on one consumer's full rewrite and the prototype, and
  the second-consumer pilot is a follow-up (§1).
- The client's views and tests were not migrated. The run-time behavior of the
  rewrites was tested by the prototype's suite and one smoke test, not by the
  client's own tests.
- The prototype is TypeScript only. R18 has no test until the threaded flavors
  implement it.
- The line counts of single themes are estimates; the totals of the rewrites are
  measurements.
