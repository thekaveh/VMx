# TypeScript DevTools DayDreams pilot — 2026-08-11

## 1. Scope

Issue #96 was validated in a disposable clone of DayDreams at
`c6052513030ce674beaf5a6b8b7703c2159b6724`. The real checkout remained on
`feat/ultra-village-v4` with its pre-existing work untouched. Nothing in the
consumer repository was committed or pushed.

The pilot installed the packed local `@thekaveh/vmx` 3.24.0 artifact and
replaced the representative AppVM conformance test's ad-hoc
`hub.messages.subscribe` message collector with `observeHub()`. Its allow filter
kept property changes, its action mapper preserved the existing fixture trace,
and an explicit named route snapshot exercised the consumer-controlled state
contract. The focused migration changed the consumer test by +9/-2 lines.

## 2. Verification

- Focused AppVM suite: 4/4 tests passed.
- Full `@daydreams/viewmodel` suite: 10 files and 144/144 tests passed.
- `@daydreams/viewmodel` strict TypeScript check passed.

DayDreams vendors an older VMx source line. Installing current 3.24.0 also
required removing six redundant consumer `readonly hub` fields/assignments so
the inherited core accessor is used. That mechanical compatibility adjustment
is independent of the DevTools migration and remained only in the disposable
clone.

## 3. Disconnected overhead

A Node 24.1.0 microbenchmark sent the same property-change message 150,000 times
per scenario, used two warm-up rounds, rotated scenario order, and reported the
median of nine measured rounds. Two fresh runs produced:

| Scenario                                         | Run 1 ns/message | Run 2 ns/message |
| ------------------------------------------------ | ---------------: | ---------------: |
| Plain hub                                        |           550.32 |           565.92 |
| `connectReduxDevtools(..., { extension: null })` |           556.57 |           564.97 |
| Active transport-neutral observer                |         1,493.81 |         1,487.36 |

The disconnected delta was +1.14% in run 1 and -0.17% in run 2, within the
observed run-to-run noise. This matches the implementation contract: an absent
or explicitly disabled extension returns a frozen no-op before creating a hub
subscription, snapshot, or timer. Active observation is intentionally not free;
in this metadata-only benchmark it added roughly 0.93 microseconds per message.

These measurements describe this machine and harness, not a universal latency
guarantee. Consumers with large snapshots must measure their own selectors,
serializers, redactors, and transport, and should use sampling or throttling for
high-frequency streams.

## 4. Result

The pilot passed without consumer behavior changes. DayDreams can replace an
ad-hoc hub message collector with the bridge while retaining its trace format
and adding explicit state. No replay, time-travel, inverse mutation, or generic
state-reconstruction behavior was tested or promised.
