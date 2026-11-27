# ADR 0256 — The Python development drain bound is opt-in

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec version:** 3.30.0 (chapter 03 §3.3, a Python rule; no conformance ID)
- **Extends:** [ADR-0082](0082-message-hub-transactions.md) (adds a Python switch to §2.4 and keeps its rules). Related: issues #1910 and #1761.

## 1. Context

ADR-0082 §2.4 bounds one drain cycle in a development build and says release
configurations disable the bound. Python has no build configuration. The hub
applied its bound under `if __debug__:`, which is true in every interpreter run
without `-O`. A normal production start therefore raised after 10,000 messages
in one drain and abandoned the queue, although the transaction was finite and
valid. Reproduced with one transaction of 10,001 serviced-collection appends: a
default run raised after it delivered 10,000 messages, and a run under `-O`
delivered all 10,001.

TypeScript already has the matching rule. Node enables the bound in its
development and test processes, and browser hosts opt in (chapter 03 §3.3).

## 2. Decision

### 2.1 The switch is a constructor option

`MessageHub` takes a keyword-only `development_diagnostics` option:

- `None`, the default: the bound is on when `sys.flags.dev_mode` is true, which
  is `python -X dev` or `PYTHONDEVMODE=1`.
- `True`: the bound is on, under any interpreter mode.
- `False`: the bound is off, under any interpreter mode.

The constructor resolves the option once. The bound value (10,000), the
overflow error text and the abandoned queue after an overflow do not change.

### 2.2 The interpreter mode is the development signal

`__debug__` is not a development signal. It is true in production starts, so
it no longer selects the bound. `sys.flags.dev_mode` is set only when a
developer asks for development behavior. Python therefore follows the
ADR-0082 §2.4 rule that a release configuration does not bound a finite drain.

### 2.3 Scope

Chapter 03 §3.3 states the Python rule after the TypeScript rule. The rule
adds no MUST and no conformance ID. The bound's conformance ID is covered by
issue #1761. The C#, Swift and Rust build-configuration switches stay as they
are.

## 3. Consequences

- A default Python start delivers a finite transaction of any size. It does not
  raise or drop queued messages.
- A publish cycle in a default Python run is no longer bounded. It does not
  raise and does not end on its own. A process that relied on the default
  overflow to detect a cycle must pass `development_diagnostics=True` or run
  with `-X dev`.
- The Python API gains one keyword-only constructor parameter. The API baseline
  records it.

## 4. Rejected alternatives

- **Keep the `__debug__` check and raise the bound.** Rejected: a finite
  transaction would still be truncated in a production start once it passed the
  new limit. The defect is that the bound applies outside development.
- **Enable the bound only in the test suite.** Rejected: the bound is a property
  of the hub, and a test configuration would hide the default that applications
  get.

## 5. Known limits

A default-run publish cycle in production is not bounded. Without `-X dev` and
without `development_diagnostics=True`, a subscriber that keeps sending
messages keeps `_drain` running on the sending thread, so the `send` call never
returns. The pending queue also grows without bound when each delivery enqueues
more than one message. The bound was the only guard that turned such a cycle
into an error. The owner decided to leave the bound opt-in, and to record this
remaining risk here rather than make it default-on. The default stays unbounded
so a finite transaction of any length is delivered whole (section 2.2), and the
Python switch matches the TypeScript rule (chapter 03 section 3.3), which keeps
the flavors uniform. An application that needs cycle detection in production
passes `development_diagnostics=True`.
