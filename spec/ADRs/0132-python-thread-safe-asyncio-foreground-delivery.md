# ADR 0132 — Use thread-safe asyncio foreground delivery in Python

- **Status:** Accepted
- **Date:** 2026-09-26
- **Spec version:** 3.23.0

## 1. Context

Python background lifecycle work runs on RxPY's `ThreadPoolScheduler` and
marshals terminal and rollback publication to the configured foreground
scheduler. `RxDispatcher.asyncio()` and the Textual adapter used
`AsyncIOScheduler`, whose ordinary asyncio calls are not safe from a pool
worker and may fail in debug mode or leave an idle loop unwoken.

The existing chapter 11 contract already requires background lifecycle terminal
and rollback emissions on `IDispatcher.Foreground`. The defect was therefore a
Python implementation choice, not a new language-neutral threading contract.

## 2. Decision

Use RxPY's existing `AsyncIOThreadSafeScheduler(loop)` for the Python asyncio
factory and Textual adapter foreground channel. It retains the factory
signature, supplied-loop identity, no-argument fresh caller-managed loop,
immediate dispatcher, and custom scheduler injection.

The host owns the supplied loop and RxPY's independent `ThreadPoolScheduler`
executor. A composition root stops new work, awaits admitted hooks while the
loop remains responsive, then disposes its VMs and subscriptions and explicitly
shuts down a host-owned pool from outside that pool. It closes only loops it
created. Async hosts may await `asyncio.to_thread(pool.executor.shutdown, wait=True)`; loop closure alone does not join this executor.

## 3. Consequences

Python now delivers worker-originated lifecycle success, construction rollback,
destruction success, and destruction rollback through the running asyncio loop
thread. Disposal before queued terminal delivery still prevents resurrection.

C# continues to post to its captured `SynchronizationContext`; TypeScript
continues on its single JavaScript event loop; Swift continues to enqueue
off-main work onto `DispatchQueue.main`; and Rust continues to send work to its
dedicated serial workers. Their existing admission mechanisms need no runtime
change from this Python correction.

The spec version, every flavor's minimum-spec declaration, fixtures, and the
403-library/408-total conformance catalog remain unchanged. Python's source
line advances to 3.23.2 without a tag or registry publication.

## 4. Rejected alternatives

- **Keep `AsyncIOScheduler`:** it cannot safely receive lifecycle completion
  from the background pool.
- **Add a VMx scheduler or dependency:** RxPY already ships the required
  scheduler class.
- **Make all VM mutation thread-safe:** foreground delivery does not broaden
  VM mutation guarantees.
- **Treat loop closure as pool cleanup:** asyncio does not own RxPY's separate
  executor.
