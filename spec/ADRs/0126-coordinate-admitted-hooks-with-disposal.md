# ADR 0126 — Coordinate admitted hooks with disposal

**Status:** Accepted (2026-07-22)
**Spec version:** clarified in 3.22.0
**Extends:** [ADR-0117](0117-callback-safe-lifecycle-publication.md)

## 1. Context

ADR-0117 moved consumer publication callbacks outside the lifecycle state lock,
but it did not define the interval after a construct/destruct hook is admitted.
A foreign disposal could tear down streams and owned resources while that hook
was still running. Simply waiting creates a deadlock when two active hooks each
dispose the other VM.

## 2. Decision

- Atomically lease every admitted construct/destruct hook and its associated
  container action to the executing thread.
- Foreign disposal publishes `Disposed`, then waits for the lease before
  terminal hooks, resources, commands, and streams are torn down.
- Recheck terminal supersession between the consumer hook and any post-hook
  container action; a disposed parent starts no new child lifecycle work.
- Route foreign hook waits through the process-wide lifecycle wait graph. If a
  new edge closes a cycle, defer one target's terminal cleanup until its hook
  releases the lease instead of blocking.
- Run both teardown paths exactly once and preserve the earliest
  already-propagating failure. Deferred cleanup failures cannot replace an
  earlier hook/disposal failure. Swift remains nonthrowing and TypeScript cannot
  form a foreign-thread hook cycle.

## 3. Consequences

- Disposal is synchronous for ordinary foreign callers and safely deferred
  only to break a proven wait cycle.
- Hooks never race VM-local terminal teardown, and container actions do not
  start after terminal supersession.
- Cross-VM callback graphs remain deadlock-free without weakening terminal
  status or exactly-once cleanup.
- This clarifies existing 3.22.0 lifecycle IDs and adds no API, fixture,
  conformance ID, package version, or minimum-spec change.

## 4. Rejected alternatives

- Hold the lifecycle state lock while invoking hooks: consumer code could
  acquire unrelated VM locks in the opposite order.
- Always skip the wait: terminal cleanup could overlap admitted user code.
- Always wait: opposing active hooks can deadlock permanently.
