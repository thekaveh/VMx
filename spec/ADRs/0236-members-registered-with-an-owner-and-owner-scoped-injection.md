# ADR 0236 — Members registered with an owner, owner-scoped injection, and walks that visit members

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (decision record; chapter 24 and the chapter edits
  land with the implementations)
- **Extends:** [ADR-0162](0162-supported-child-transition-helper.md) §2.2, with
  members that follow the lifecycle of their owner;
  [ADR-0107](0107-atomic-container-ownership-transfer.md) §2 and
  [ADR-0105](0105-atomic-hierarchy-attachment.md) §2, whose preflights also
  refuse a view-model that has an owner
- **Related:** [ADR-0003](0003-constructor-injection.md),
  [ADR-0018](0018-flat-vm-hierarchy-vs-old-chain.md),
  [ADR-0090](0090-owned-resource-registration-and-public-hub.md),
  [ADR-0161](0161-reverse-child-destruct-order.md),
  [ADR-0229](0229-csharp-subclass-dispatcher-access.md),
  [ADR-0234](0234-registered-reactive-state-with-tracked-dependencies.md),
  [ADR-0237](0237-construct-scoped-reactions.md),
  [ADR-0238](0238-owner-declared-keyed-resource-driver.md), rows D15, D19 and
  D20 and §1.8.4 of the
  [upstream-candidates plan](../proposals/2026-10-20-upstream-candidates-plan.md),
  the design proposal
  [`2026-11-15-registered-reactive-state.md`](../proposals/2026-11-15-registered-reactive-state.md),
  #669, #144, #1612, #1611, #1619.

## 1. Context

### 1.1 Members today

A leaf view-model often keeps member view-models in fields. ADR-0162 gives it
two tools: the child-transition helper and the member-disposal helper
(`ownMember` in TypeScript). The author still lists the members again in the
construct and destruct hooks, passes the hub and the dispatcher into the
constructor of every member, and keeps a `components()` list or a container
only so that `walk()` finds the members.

### 1.2 Evidence

In the production Vue client of ADR-0234 §1.2, 139 `hub:` arguments pass the hub
to members, and 8 remain in the tier B rewrite, which registers 60 members. The
study counts about 271 removable lines for members that follow their owner's
lifecycle, about 214 lines for the hub and dispatcher plumbing, and 13 lines for
walks that reach members, and 11 member findings (123 lines) keep a
`components()` or walk list that only the walk needs. Hand-written member lists
drift: in one of the client's view-models, the construct order and the destruct
order of the members differ. The October plan counted 26 `components()` lists
and one leaf class with 11 children (plan §1.6 and §1.8.4). The flagship
`WorkspaceVM` of VMx cascades three lifecycles by hand (#1611).

### 1.3 The decisions in the way

ADR-0162 §2.2: "A member is not a container child. It has no parent link and no
selection, and registration does not construct it. The helper of §2.1
transitions it." Chapter 02 §7.1 repeats the first two sentences.

Plan D15 (`adopt(child)`), disposition "Defer to a design gate": "Would turn
every leaf into a container (ADR-0018). A supported helper gives most of the
value first." Plan §1.8.4 step 3 says that `adopt` would have to "set a parent
link like the aggregate's fixed-slot parent" and "extend `walk()` to visit both
items and adopted members (spec 13, a new UTIL ID)". #669 holds the design gate.

Plan D19 (a services bundle), disposition "Fold into #144": "Needs a
five-flavor decision on dispatcher exposure." Plan D20 (a `parent` option),
disposition "Decline": "The name collides with the internal container `Parent`;
ambient inheritance was declined by ADR-0003 §3." ADR-0003 §3: "Constructor
injection is testable, explicit, and removes the ambient-state failure mode
where a forgotten registration produces a confusing null reference deep in a
VM's lifecycle."

ADR-0107 §4 rejects multiple parents: "selection delegation, current state,
disposal, and parent-derived commands require one authoritative owner."

Chapter 13 §2: "A leaf `ComponentVM` yields exactly itself." #1612 reports that
the flavors descend into user-defined view-models anyway, each by its own
mechanism, and that Swift has no such mechanism.

## 2. Decision

### 2.1 Registration

1. `member(vm)` registers `vm` as a member of the calling view-model, its
   owner, and returns `vm`. It builds on the member-disposal registration of
   ADR-0162 §2.2 and adds an owner link and lifecycle participation: the member
   follows the construct, destruct and dispose of its owner (§2.2), joins the
   activation of its owner (ADR-0234 §2.5), and is visited by walks (§2.4).
   Registering a member again with the same owner returns it unchanged.
1. These registrations are usage errors and register nothing: the owner
   itself or its ownership identity; a view-model that has another owner; a
   view-model that has a container parent; and a registration that would close
   an owner cycle. A container (`CompositeVM`, `GroupVM`, an aggregate slot,
   or a `HierarchicalVM` parent) refuses to add a view-model that has an
   owner, before it changes anything. This refusal joins the preflights of
   ADR-0107 §2 and ADR-0105 §2.
1. A member gets no parent link and no selection. A leaf with members stays a
   leaf (ADR-0018), and a view-model has at most one authoritative owner
   (ADR-0107).
1. A member that reaches `Disposed` leaves its owner's member list, whoever
   disposed it. The owner keeps no reference to it, and walks and the owner's
   lifecycle skip it, so a long-lived owner keeps no disposed member alive.
   Registering a view-model whose disposal has started registers nothing and
   returns it. A release without disposal, which would move a live member to
   another owner, is not added until a consumer needs it.
1. A view-model that only the member-disposal helper registers keeps the rules
   of ADR-0162 §2.2 unchanged.

### 2.2 The lifecycle of members

1. Construct. After the owner's `_onConstruct`, the owner constructs its
   members in registration order with the rules of the child-transition
   helper (ADR-0162 §2.1). The owner waits for a member that constructs in the
   background. A member that does not reach `Constructed` fails the construct
   of the owner, and the owner rolls back. Members that reached `Constructed`
   stay `Constructed`. Undoing those siblings stays an open question
   (`docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` §1.3).
1. Destruct. After the construct-scoped reactions of the owner stop (ADR-0237),
   the owner destructs its members in reverse registration order, with the
   rules of the child-transition helper, and then its `_onDestruct` runs. A
   member therefore still sees the resources that the owner's `_onConstruct`
   set up while it destructs; the owner's reactions have already stopped
   (ADR-0237 §2.3). A member or an `_onDestruct` that fails
   rolls the owner back to `Constructed`.
1. Dispose. The owner disposes its container children in the container's
   dispose order (chapter 02 §7, ADR-0161), and then its members in
   registration order, each depth-first, before it publishes `Disposed`
   (ADR-0162 §2.2, `LIFE-018`).
1. A late registration follows the status of the owner. A `Constructed` owner
   constructs the member at once; a failure propagates from `member()`, and the
   member stays registered. A `Constructing` owner adds the member to its member
   walk, or constructs it at once when the walk is over. A `Destructing` or
   `Destructed` owner constructs it at its next construct. An owner whose
   disposal has started disposes it at once.

### 2.3 Owner-scoped injection

1. `member(Type, options)` constructs the member with the owner's hub and
   dispatcher added to `options`, and then registers it as §2.1 says. In
   TypeScript it calls
   `new Type({ ...options, hub: owner.hub, dispatcher: <the owner's dispatcher> })`,
   and its type rejects `hub` and `dispatcher` in `options`. Each flavor
   passes the two services in its own idiom (ADR-0006): C#, Swift and Rust take
   a factory that receives the hub and the dispatcher, and Python passes them
   as keyword arguments (the proposal §4).
1. This is constructor injection by the owner, at the construction call
   (ADR-0003). There is no ambient lookup, no context object and no inherited
   hub, and a member keeps the hub that it was constructed with.
1. Plan D20 stays declined: there is no `parent` option. Plan D19 is answered
   without a services bundle: the owner reads its own dispatcher inside the
   call, so VMx adds no dispatcher accessor. The subclass accessors that the
   flavors already have stay as they are, among them the protected C#
   `Dispatcher` of ADR-0229. #144 is answered for members:
   `member(Type, options)` passes the owner's dispatcher, so consumers no
   longer pass a dispatcher to members. A library-owned default dispatcher on
   the builders is not decided here; #144 keeps that question, reshaped to the
   root view-models that a host builds.

### 2.4 Walks

1. `walk`, `walkExpanded` and `find` visit the members of each view-model
   after its container children or its aggregate components, in registration
   order and depth-first, for every kind of node. A member that `components()`
   already yielded is not visited twice.
1. When the flavors implement this rule, chapter 13 §2 states it as one child
   rule, and a new `UTIL` conformance ID pins it in all five flavors: a leaf
   yields itself and then its members. #1612 widens to this rule.

### 2.5 The design gate of plan D15

1. Members registered with an owner answer the design gate of plan D15 and
   #669 for members without a parent link. ADR-0162 is extended, not replaced.
   An `adopt(child)` that sets a parent link is declined.
1. Undoing siblings after a failed member walk stays open.

## 3. Consequences

- The Status of ADR-0162 and its registry cell name this ADR for §2.2. The
  Status of ADR-0107 and of ADR-0105 and their registry cells name this ADR as
  an extension.
- When the flavors implement this ADR, chapter 02 (§2.2, §6.1 and §7.1),
  chapters 06, 07, 08 and 18 (containers, aggregate slots and hierarchy
  attachment refuse a view-model that has an owner) and chapter 13 (§2)
  change. Chapter 24 adds the conformance IDs of members and
  injection, and chapter 13 adds one `UTIL` ID.
- A leaf view-model drops its member loops, the `components()` lists kept only
  for walks, and the hub and dispatcher plumbing for its members. A container
  stays the tool for a set of children that changes.
- `AggregateVM` keeps its slots, which its factories rebuild on each construct.
  Members are created once, by their owner.

## 4. Rejected alternatives

- **`adopt(child)` with a parent link (plan D15 as the catalogue proposed
  it).** It turns a leaf into a container (ADR-0018). A parent link also
  implies selection and parent-derived commands that a member does not have.
- **An ambient or inherited hub, a context object, or a `parent` option (plan
  D20).** They bring back the ambient-state failure mode that ADR-0003 removed,
  and a node that is built before it is attached has no parent to inherit
  from.
- **A services bundle or a public dispatcher accessor (plan D19 as proposed).**
  The owner already holds both services. Passing them inside `member()` needs
  no new public member.
- **Members that are never unregistered.** A long-lived owner, such as a shell
  that replaces its pages, would keep every disposed member alive.
- **Members disposed in reverse registration order.** ADR-0162 §4 rejected it:
  members follow the container default. Destruct runs in reverse order because
  it mirrors construct (ADR-0237).
- **Walk lists kept by hand in `components()`.** They exist only for the walk,
  and they drift from the real members.
