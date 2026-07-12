# ADR 0100 — Add a cancellable single-resource presentation viewmodel

**Status:** Accepted (2026-07-12)
**Spec version:** introduced in 3.20.0

## 1. Context

Consumers repeatedly own route-level asynchronous state machines that differ
only in domain data: start loading, publish progress, retain or clear an old
value, show failure, retry, cancel during navigation, reject stale completion,
and dispose a successfully acquired resource. DayDreams carries two concrete
copies in GalleryView and DreamscapeView.

VMx already provides `ComponentVM`, `AsyncRelayCommand`, idiomatic cancellation,
ordinary property/hub notification, and disposal-lifetime ownership. Asking
each UI to compose these correctly leaves race and teardown policy duplicated;
adding another event or cancellation system would duplicate VMx itself.

## 2. Decision

### 2.1 Add one narrow component viewmodel

Add `AsyncResourceVM<T>` for one asynchronously acquired value. It is a normal
component viewmodel with one immutable discriminated `State`/`state` binding
property, existing load/reload async relay commands, an existing relay cancel
command, direct intents, and idempotent disposal.

The primitive is domain-, UI-, and transport-neutral. Routing, caching,
pagination, factories, child VMs, and scheduler policy remain consumer-owned.

### 2.2 Use four immutable states

`Idle`, `Loading`, `Ready`, and `Error` discriminate legal value/error presence.
`Loading` and `Error` may carry the previous accepted value only when retention
is configured. One effective transition publishes one normal property-change
pair for the immutable state property; no second resource stream is added.

### 2.3 Make latest start authoritative

Every admitted start advances a monotonic identity, cancels the prior operation,
captures its cancellation baseline, and installs loading state. Only the current
identity may install success, failure, or cancellation. Stale completion is
silent except for cleanup of a value it newly produced.

### 2.4 Compose existing command cancellation

The load and reload commands are `AsyncRelayCommand` instances and link their
host cancellation channel to the resource operation. Direct intents share the
same core. Cancel uses that operation channel and cancels command execution; no
new token, signal, exception, or error observable becomes public.

Expected loader failure is presentation state. Awaitable intents complete
normally after installing `Error`, and fire-and-forget commands do not duplicate
the same fault on their command error stream. Cancellation restores the stable
pre-operation state and is never an error.

### 2.5 Default to discarding previous data

`DiscardPrevious` is the explicit conservative default: reload relinquishes an
accepted value at start and cancellation falls back to idle. `RetainPrevious`
is opt-in and keeps the prior value visible through loading/error and available
as the cancellation baseline. Neither policy changes loader inputs or creates a
cache.

### 2.6 Make value ownership opt-in and acquisition-based

An optional cleanup callback transfers ownership of each successful loader
return. Cleanup is exactly once on discard, replacement, stale/post-dispose
success, or terminal disposal. VMx never infers disposal from `T`; without the
callback the value remains opaque. Cleanup failures are best-effort and
isolated, matching ADR-0090.

### 2.7 Keep construction lifecycle independent

The state machine does not auto-load on construct or cancel on destruct.
Disposal alone is terminal: it invalidates identity, cancels work/commands,
releases the accepted value, and makes later intents and notifications inert.

## 3. Consequences

- Screens bind one exhaustive state instead of coordinating booleans and
  nullable fields.
- Latest-start-wins and late-dispose suppression become framework invariants.
- Existing async command and component adapters work without another protocol.
- Consumers explicitly choose stale-value presentation and ownership transfer.
- A loader fault has one observable representation, the retryable error state.
- Rust maps async work to its established VMx-owned thread/token facade rather
  than adding a runtime dependency.
- `ARES-001..011` raise library coverage from 380 to 391 and total catalog
  coverage from 385 to 396 including five `THEME` scenarios.
- The additive feature releases as spec/C#/Python/TypeScript/Swift 3.20.0 and
  Rust 0.20.0.

## 4. Rejected alternatives

### 4.1 Add only a React hook

Rejected. The state and race policy are UI-neutral and recur outside React.

### 4.2 Expose independent booleans and nullable fields

Rejected. Invalid combinations remain representable and exhaustive rendering
is impossible.

### 4.3 Propagate loader faults from load/reload

Rejected. Screens require retryable error state, and fire-and-forget execution
would otherwise create a second error path.

### 4.4 Always retain or always discard previous values

Rejected. Stale-value presentation is a product decision, while a conservative
default plus explicit opt-in keeps the portable contract clear.

### 4.5 Infer cleanup from value type

Rejected. No portable disposable constraint covers arbitrary values, and
implicit ownership would risk disposing caller-owned data.

### 4.6 Couple loading to construct/destruct

Rejected. View attachment and route activation are separate product policies;
only terminal disposal has portable teardown meaning.
