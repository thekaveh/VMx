# 1. Registered Reactive State Prototype

## 1.1. Status

| Field    | Value                                                                                                                                                                                      |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Status   | Reference code for the implementers of the [registered reactive state proposal](../../2026-11-15-registered-reactive-state.md). Not shipped, not published, and not built or tested by CI. |
| Date     | 2026-11-15                                                                                                                                                                                 |
| Baseline | The published VMx TypeScript package 3.30.0 (`@thekaveh/vmx`, tag `typescript-v3.30.0`), unchanged.                                                                                        |
| Result   | 282 tests in 97 suites pass, 0 fail, 0 skipped (measured with Node 26.12.1 and TypeScript 6.0.3).                                                                                          |
| Rules    | The proposal is normative for the implementations. Where this code differs from the proposal, the proposal wins (§1.6).                                                                    |

## 1.2. What This Folder Is

The folder holds a working TypeScript implementation of the design: registered state (V1), computed properties with
tracked dependencies (V2), commands created and owned on the view-model (V3), members with automatic lifecycle (V4),
owner-scoped service injection (V5), construct-scoped reactions (V6), and the keyed resource driver (V7).

It runs as a layer on top of the unchanged VMx 3.30.0 package. When `src/index.ts` is imported, it adds the helpers
to `ComponentVMBase.prototype` and wraps a fixed list of VMx methods (`src/library.ts`). At run time it hooks each
view-model that it touches.

Use it in three ways:

- Read the rules as code. Comments cite the rule numbers of the proposal (§1.7).
- Run the tests as executable examples. Their `describe` blocks name the draft conformance IDs or the rules that they
  cover (§1.7).
- Port the engine. The graph in `src/graph.ts` does not import VMx; its nodes, frames, settles and drain are the same
  in every flavor.

A VMx implementation puts this logic into `ComponentVMBase`, the commands, and the library classes. It needs none of
the stand-ins that §1.5 lists.

## 1.3. Build and Test

Build the prototype in a scratch folder outside the repository, so that `build/` and `node_modules/` never enter the
tracked tree. The prototype links four packages from a build of the VMx TypeScript 3.30.0 tag:

- `@thekaveh/vmx`: the package under test.
- `rxjs`: VMx's own copy, so that the prototype and VMx share one rxjs instance and one `config.onUnhandledError`.
  The tests observe that route.
- `typescript`: the compiler that the package scripts call.
- `@types/node`: the Node types that `tsconfig.json` names.

```bash
VMX=/path/to/a/VMx/checkout
SCRATCH="$(mktemp -d)"

# The published VMx TypeScript 3.30.0, built from its tag.
git -C "$VMX" worktree add "$SCRATCH/vmx-3.30.0" typescript-v3.30.0
cd "$SCRATCH/vmx-3.30.0/langs/typescript"
npm ci
npm run build
VMX_TS="$PWD"

# A scratch copy of the prototype, with its four links.
cp -R "$VMX/spec/proposals/2026-11-15-registered-reactive-state/prototype" "$SCRATCH/prototype"
cd "$SCRATCH/prototype"
mkdir -p node_modules/@thekaveh node_modules/@types
ln -s "$VMX_TS" node_modules/@thekaveh/vmx
ln -s "$VMX_TS/node_modules/rxjs" node_modules/rxjs
ln -s "$VMX_TS/node_modules/typescript" node_modules/typescript
ln -s "$VMX_TS/node_modules/@types/node" node_modules/@types/node

# Build the sources and the tests to build/, then run every test.
node node_modules/typescript/bin/tsc -p tsconfig.json
NODE_ENV=test node --expose-gc --test build/tests/
```

`NODE_ENV=test` turns on the development diagnostics that the tests expect. `--expose-gc` enables the WeakRef
retention probes; without it, those tests skip. When you are done, remove the scratch worktree with
`git -C "$VMX" worktree remove "$SCRATCH/vmx-3.30.0"`.

The package scripts run the same commands:

| Script              | What it does                                                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `npm run build`     | Compiles `src/` and `tests/` to `build/` (`tsconfig.json`: strict, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`). |
| `npm run check:src` | Type-checks `src/` alone with ES2020 and DOM libraries, no Node types, and `isolatedModules` (`tsconfig.src.json`).           |
| `npm test`          | Runs every test.                                                                                                              |
| `npm run bench`     | Informative micro-benchmark (`bench/settle.mjs`): activation and settle costs for 70 view-models.                             |
| `npm run stress`    | Informative randomized stress run (`bench/random-r2.mjs`): 300 seeds of 600 operations each.                                  |

`bench/` needs a build first. Its numbers are informative and depend on the machine.

## 1.4. Files

| Path                                                     | Content                                                                                                                                                                                                             |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/graph.ts`                                           | Nodes and versions, tracking frames, writes, settles, change scopes, equalities in their own context, the drain, producer flushes, release. It does not import VMx.                                                 |
| `src/vmState.ts`                                         | Per-view-model state, the construct, destruct and dispose sequences, activation, members, registration scopes, deferred diagnostics.                                                                                |
| `src/helpers.ts`                                         | The instance helpers (`observable`, `signal`, `computed`, `memo`, `invalidate`, `change`, the command helpers, `member`, `effect`, `reaction`, `whileConstructed`, `keyedResource`, `followKey`) and their handles. |
| `src/commands.ts`                                        | Tracked predicates for every VMx command, the decorator's merged raises, the helper commands.                                                                                                                       |
| `src/reaction.ts`, `src/reactions.ts`                    | The reaction base with registration scopes, and the reaction kinds, including the keyed driver.                                                                                                                     |
| `src/interop.ts`, `src/bridge.ts`                        | Announcement nodes, library publications, tracking accessors; `read`, `tracked`, `activate`, `explain`.                                                                                                             |
| `src/library.ts`                                         | A stand-in: the wrappers of VMx 3.30.0 methods that make the library rules hold (§1.5).                                                                                                                             |
| `src/augment.ts`, `src/types.ts`                         | The TypeScript API, declared on `@thekaveh/vmx` by module augmentation.                                                                                                                                             |
| `src/equality.ts`, `src/errors.ts`, `src/diagnostics.ts` | Equalities (`shallowEqual`, structural, errors), the three error classes, development diagnostics.                                                                                                                  |
| `src/util.ts`, `src/walk.ts`, `src/index.ts`             | Runtime helpers, the walks that visit members, the exports.                                                                                                                                                         |
| `tests/`                                                 | The tests (§1.7) and `support.ts`, the common services and the event recorder.                                                                                                                                      |
| `tests/samples/`                                         | Two sample view-models in the consumer shape: `CollapsibleSectionVM` and `FavoriteToggleVM`.                                                                                                                        |
| `bench/`                                                 | The informative benchmark and stress run.                                                                                                                                                                           |

The exports of `src/index.ts` that are not part of the proposed API are prototype-only: `tracked`,
`configureReactiveDiagnostics`, and the walks `walk`, `walkExpanded` and `find`.

## 1.5. Stand-Ins a VMx Implementation Does Not Need

The prototype changes no file of VMx. At the first registration, a view-model gets own properties that call the
prototype-chain methods: `_onConstruct`, `_onDestruct`, `_onDispose` and `_setStatus` (the lifecycle sequences), the
`propertyChanged` getter (activation at the first subscription), and the library getters `status`, `isConstructed`,
`isCurrent`, `model`, `modeledHint`, `state` and `current` (native tracking). At import time, `src/library.ts` wraps
the lifecycle calls, the command executions, the library mutations, the publications, `MessageHub.send`, and the
`canExecute` methods of the VMx commands. A VMx implementation moves this logic into the classes themselves.

The prototype has these limits. Code comments cite them by number ("README.md, limit 2").

1. The helpers are public, not protected, because a module augmentation can add only public interface members. Call
   sites type-check the same way.
1. Native nodes are announcement nodes (R15.5). Direct reads are tracked on the view-models that the prototype touches
   (registered view-models, members, keyed resources) and on the instances passed to `tracked()`. Other library
   objects need `read()` or `tracked()`. View-model publications, command raises and expansion changes commit before
   they deliver (R15.2). `DiscriminatorVM`, `FormVM` and `DerivedProperty` still commit at their stream emission,
   because their state changes in private code that the prototype cannot reach first. A subscriber that subscribed to
   those streams before the prototype did reads a dependent computed one change late. A forwarding decorator's
   `read(decorator, name)` commits at the wrapped view-model's local emission, after its hub message.
1. One settle per library operation (R15.2) holds for the methods that `src/library.ts` wraps and for every view-model
   publication. Another VMx method settles once per emission.
1. The construct sequence does not wait for a member that constructs in the background (R13.1 step 4). VMx 3.30.0
   cannot defer the owner's terminal status from a hook.
1. A library mutation inside an evaluation frame throws before it changes anything (R16) only for the methods that
   `src/library.ts` wraps. A publication inside an evaluation frame commits nothing and reports a
   `ReactiveWriteError` on the stream-fed route.
1. Containers refuse an owned view-model (R11.3) through the `_ownershipInProgress` flag of the member's ownership
   identity, which the parent transfer and aggregate slot paths of 3.30.0 read before they change anything.
1. The development diagnostics follow one process-wide switch with the hub's Node default (`NODE_ENV` is
   `development` or `test`), because `MessageHub` keeps its flag private. `configureReactiveDiagnostics` stands in
   for the browser opt-in and for a diagnostic sink.
1. Forwarding decorators (R3.8): members, reactions, activation and disposal follow the canonical identity. On VMx
   3.30.0 the helper of a decorator names the decorator itself as the sender.
1. The walks that visit members (R11.6) are separate exports. The walks of VMx are unchanged.
1. The producer flush (R9.8) happens at the dual-channel helper, the local-only raise, and the status transition of
   every view-model. A library send that bypasses them, such as the collection and tree messages of containers, is
   not ordered against the container's queued announcements.
1. Deliveries run untracked (R5.8) through `MessageHub.send`. The messages that `MessageHub.batch` delivers at its
   exit run inside the `batch()` call, so a frame that calls `batch()` records the reads of those observers.
1. Activation by the hub helpers of VMx (R4.2 f: `whenPropertyChanged`, `propertyValueChangedMessagesFor`,
   `subscribeValue`) needs VMx itself, because the prototype cannot hook the exports of a module. Test X6 calls
   `activate()` instead.
1. A `DecoratorCommand` recognizes its inner command by the identity of the inner command's change stream. When the
   inner command is not a VMx command, the decorator's frame also records the inner reads, and its listeners can get
   a second raise for one change. VMx holds the inner command and needs no such test.

## 1.6. Where the Decisions Differ From This Code

The prototype was written before the final decisions. The proposal records them, and it wins:

1. The error route of the keyed driver. When the promise of a load that the driver starts rejects, the prototype
   reports the error on the stream-fed route (`#startLoad` in `src/reactions.ts`). The decided rule reports it
   through the resource's own error channel instead.
1. The policy options of the keyed driver. The decided driver adds options for sites whose rules differ: no retry on
   re-enable, and a first load that a disable cancelled stays on demand. The prototype has `autoLoad` and
   `cancelWhenDisabled` only.
1. The unpublished-getter check (R19.2). The prototype reports every public getter that reads a node and is not
   registered. The decided check exempts getters that read only immutable state.
1. The graph's own announcements and announcement nodes (R15.3, proposal §6 question 1). The prototype does not bump
   an announcement node when the graph announces a registered name (`src/interop.ts`). The decided rule bumps it, so a
   frame that read the name through `read()` before the registration follows later announcements.
1. Container membership (R15.1, proposal §6 question 5). The prototype follows a container's `count` only through
   `read(container, "count")`, on the collection channel. A direct read of `count` or of the children records no
   dependency. The decided rule makes `count` and the children native nodes, so a direct read is tracked.
1. Library commands (R10.10, proposal §6 question 17). The prototype tracks the predicate of every VMx command,
   also the commands that VMx library classes build over their own state, such as the approve command of `FormVM`
   and the commands of `ExpandableState` and `AsyncResourceVM`: `src/library.ts` wraps `canExecute` on the command
   prototypes. The decided rule builds these commands with tracking off, so they keep today's raises only.
1. Activation at the first construct (R4.2 a). VMx activates every view-model at the start of its first construct,
   also a view-model that registered nothing. The prototype installs its construct hook only on a view-model that
   calls a helper (and on the canonical identity of a decorator that calls one). For example, a container that
   registers nothing is not activated at its construct, so a child added to it later is not activated by that
   addition (R4.2 c).
1. The decorator list of the activation cascade (R3.8). The prototype's cascade reaches the forwarding decorators
   through a strong list (`dependents` in `src/vmState.ts`), so the canonical view-model keeps each of them
   reachable. The decided rule keeps a weak list of the decorators that registered nodes on the canonical identity.
1. The rules that the proposal marks *(new in this proposal)* (proposal §3) are not in this code, and the proposal
   decides the open questions of the prototype (proposal §6). Where one of them changes a behavior, the proposal's
   rule applies, not this code.

Destructed view-models keep computing, as the prototype does: computed publication works in every status except
Disposed. The decision documents this behavior and adds no pause option.

## 1.7. Tests and References

The comments and test names use these references:

- `R12.10` is one rule of the proposal. `R12.*` is the group of rules with that prefix. `R16` is the group of error
  rules. `R13.1` to `R13.3` are the construct, destruct and dispose sequences.
- "Fix round 1" and "fix round 2" mark rules that two adversarial review rounds added or changed. The test
  expectations that a fix round moved say so in a comment.
- "Design goal" marks a quoted goal of the design (one of V1 to V7 of §1.2, or a general goal) that the adversarial
  rounds tested against.
- Names such as `K1`, `R6b`, `OR5`, `DD7` or `KD4` identify the scenarios of the adversarial rounds. They are test
  names, not rule numbers.

| Test file                                                   | Scope                                                                                                                                      |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `state.test.ts`                                             | RSTATE-001 to RSTATE-005: state, registration errors, accepted writes, patches, plain getters.                                             |
| `activation.test.ts`                                        | RSTATE-006 to RSTATE-008: activation triggers and cascade, silent baselines, memoization.                                                  |
| `settle.test.ts`                                            | RSTATE-009 to RSTATE-015: announcements, glitch freedom, losslessness, ordering, change scopes, hub batches, re-entrant FIFO.              |
| `errors.test.ts`                                            | RSTATE-016 to RSTATE-019: `ReactiveWriteError`, error states, cycles, the development drain bound.                                         |
| `tracking.test.ts`                                          | RSTATE-020 and RSTATE-021: tracking through call chains, `untracked`, `peek`; `invalidate`.                                                |
| `commands.test.ts`                                          | RSTATE-022 and RSTATE-023: tracked predicates; owned commands and triggers.                                                                |
| `members.test.ts`                                           | RSTATE-024 to RSTATE-026: injection and refusals, member lifecycle and late registration, walks (two IDs differ from the plan; see below). |
| `reactions.test.ts`                                         | RSTATE-027 to RSTATE-031: the reaction scope, `effect`, `reaction`, alive reactions, failures.                                             |
| `dispose.test.ts`                                           | RSTATE-032: dispose order and retention (WeakRef probe).                                                                                   |
| `keyed.test.ts`                                             | RSTATE-033 and RSTATE-034: `keyedResource`, `followKey`.                                                                                   |
| `interop.test.ts`                                           | RSTATE-035 and RSTATE-036: native nodes, `read()` interop.                                                                                 |
| `diagnostics.test.ts`                                       | R19.1 to R19.4: staleness check, unpublished-getter probe, hand-written notifications, `explain`.                                          |
| `rules.test.ts`                                             | Rules that span several draft IDs.                                                                                                         |
| `samples.test.ts`                                           | The two sample view-models.                                                                                                                |
| `attack-r1-*.test.ts`, `attack-r2-*.test.ts`                | The scenarios of the two adversarial review rounds.                                                                                        |
| `fix-r1.test.ts`, `fix-r1-random.test.ts`, `fix-r2.test.ts` | The rules that the fix rounds added or changed, and a seeded randomized consistency test.                                                  |

The draft IDs are the prototype's numbering; the conformance plan of the proposal (§5.1) is the reference for the
conformance IDs. Two `describe` blocks of `members.test.ts` differ from the plan. Port them under the plan's IDs:

- Prototype `RSTATE-025` checks plan RSTATE-025 (member sequences, a failing member) and plan RSTATE-026 (late
  registration, removal at disposal).
- Prototype `RSTATE-026` checks plan `UTIL-005` (walks that visit members).

RSTATE-037 to RSTATE-046 have no `describe` block of their own. Proposal §5.1 maps RSTATE-038 to RSTATE-041 and
RSTATE-044 to RSTATE-046 to tests in `fix-r1.test.ts`, `fix-r1-random.test.ts`, `fix-r2.test.ts`,
`diagnostics.test.ts` and `rules.test.ts`. RSTATE-037, RSTATE-042 and RSTATE-043 have no prototype test. The
TypeScript clause of RSTATE-037 (a write in a later job settles and delivers before it returns) still applies, and
every flavor carries the ID.
