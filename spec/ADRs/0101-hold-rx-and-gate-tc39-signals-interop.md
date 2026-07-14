# ADR 0101 — Hold Rx as the reactive primitive and gate TC39 Signals interop

**Status:** Accepted (2026-07-12)
**Spec version:** 3.20.0 (decision ADR; no API or behavior change)
**Related:** ADR-0002, ADR-0006, ADR-0011, ADR-0082, ADR-0095, ADR-0103,
issues #80, #93, and #97

## 1. Context

The TC39 Signals proposal may eventually provide a shared reactive graph for
JavaScript frameworks. Its current official status does not justify changing
VMx, however:

- On 2026-07-12, the pinned
  [proposal README](https://github.com/tc39/proposal-signals/blob/9124ed91b24bb02ff7408b2fcf5abb6e18b095d7/README.md)
  labels Signals **Stage 1**, calls the API an early common direction, and says
  significant multi-framework prototyping should precede advancement.
- The contemporaneous official
  [TC39 proposal tracker](https://github.com/tc39/proposals/blob/cae61138d3872cb9748effe04b729b7152f71369/stage-1-proposals.md)
  lists Signals among Stage 1 proposals. The
  [TC39 process](https://tc39.es/process-document/) is authoritative for what
  each standards stage means.

Repository project phases, issue labels, prototype milestones, and historical
planning prose in a proposal repository are not TC39 stage advancement. Only a
committee-approved stage recorded by TC39 is standards status.

VMx already has deliberate reactive boundaries. ADR-0002 assigns one idiomatic
Rx implementation to each flavor: System.Reactive, reactivex, RxJS, Combine,
and what was then documented as the Rust facade over rxrust. ADR-0103 later
corrected that unused-backend claim without changing the facade. Replacing the
observable reactive boundaries would still be a
cross-flavor architectural change, while TC39 Signals is currently a mutable
JavaScript-only proposal.

## 2. Decision

### 2.1 Keep the current reactive architecture

VMx will not replace its Rx/Combine/reactivex or VMx-owned Rust hot-stream
internals while TC39 Signals remains Stage 1. VMx will not add `signal-polyfill`, a `toSignal`
helper, or a supported Signal package subpath under this decision. Framework
adapters continue translating VMx notifications into their host framework's
reactivity primitive.

### 2.2 Treat the existing seams as the interop surface

Signals interop does not require a new VMx core notification channel today:

| Existing seam             | Intended use                                                                                                     |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Typed hub messages        | Cross-VM observation, sender/property filtering, transactions, and isolated subscriber failures                  |
| VM-local property streams | Direct binding when an adapter already owns one VM's lifecycle                                                   |
| `DerivedProperty`         | Owned, equality-aware computed state over explicit reactive sources                                              |
| ADR-0095 `subscribeValue` | Fixed-source selected state with initial delivery, equality, current/previous values, and deterministic teardown |
| UI adapters and recipes   | Translation into React, Vue, Svelte, Solid, SwiftUI, desktop, or terminal host primitives                        |

These seams are sufficient for an eventual adapter to observe VMx without
making Signal graphs normative across all five flavors.

### 2.3 Require three objective revisit gates

A proposal to add supported Signals interop must demonstrate all of the
following in a new issue and ADR:

1. TC39 has advanced Signals to Stage 2 or later in the official proposal
   tracker.
1. A stable, production-grade implementation exists with versioned semantics,
   tests, performance evidence, and a credible compatibility/release policy.
1. At least two independent VMx consumers or framework adapters have piloted
   the same interop seam and reported concrete benefit over existing VMx
   subscriptions. Two demos in one consumer do not count as independent
   evidence.

Stage advancement is necessary but not sufficient. The review decides whether
the result belongs in a TypeScript ecosystem adapter, an experimental package,
or a supported VMx surface; this ADR does not pre-authorize any of them.

### 2.4 Preserve compatibility invariants in any future adapter

The future review must specify and test:

- **Ownership and disposal:** one owner for the VMx subscription and Signal
  watcher, idempotent teardown, and no post-dispose callback.
- **Batching:** hub transactions remain lossless and framework scheduling does
  not expose intermediate or duplicate graph states.
- **Equality:** VMx selector equality and Signal equality compose without
  suppressing required changes or causing duplicate work.
- **Scheduling:** `Signal.subtle.Watcher` notification restrictions and the
  host framework's render scheduler remain explicit; core VMx does not choose
  a JavaScript UI scheduler.
- **Error routing:** selector, watcher, and adapter failures preserve VMx's
  subscriber isolation and do not become unhandled asynchronous errors.
- **Graph identity:** duplicate polyfill versions, realms, or incompatible
  Signal graphs are detected, prevented, or bounded explicitly rather than
  silently splitting dependency tracking.

## 3. Consequences

- VMx keeps its stable five-flavor reactive architecture and adds no dependency,
  package export, conformance ID, or version bump.
- JavaScript hosts can continue using hub filters, local property streams,
  `DerivedProperty`, `subscribeValue`, and framework adapters without waiting
  for the standards proposal.
- Maintainers have evidence-based gates for reopening the decision instead of
  periodically re-litigating an unstable proposal.
- A later adapter remains possible, but it must earn supported API status in a
  separate reviewed change.

## 4. Rejected alternatives

### 4.1 Publish an experimental `toSignal` adapter now

Rejected. Selecting a polyfill and package subpath creates supported API,
versioning, graph-identity, and disposal obligations before the proposal is
stable enough to satisfy them.

### 4.2 Rebuild TypeScript internals around Signals

Rejected. It would make one flavor architecturally exceptional, replace proven
RxJS contracts, and still require adapters for framework-specific ownership and
scheduling.

### 4.3 Treat proposal-project milestones as standards advancement

Rejected. Project phases describe work planning. TC39 stages are committee
decisions with process-defined entrance criteria and are the only standards
status used by the revisit gate.
