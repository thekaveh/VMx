# 15 — Derived properties

A **derived property** is a read-only-or-read-write value computed from one
or more source observables via a pure transform function. It recomputes when
any source emits a new value, publishes its own change notifications, and is
disposable.

Derived properties are the modern equivalent of the 2012 VMx
`TransformationProperty<S,P,V>` (which hard-capped at 5 sources). Per
ADR-0011, the v2.0 contract supports **N sources** (with N ≥ 5 required of
every flavor).

## 1. Shape

```
DerivedProperty<TValue>:
    Value : TValue                              # current value; recomputed on source change
    ValueChanged : Observable<TValue>           # emits when Value changes (distinct)

    CanSet(value: TValue) : bool                # validator; default returns false (read-only)
    SetValue(value: TValue) : void              # write-back; raises if CanSet returns false

    Dispose() : void                            # tear down source subscriptions
```

`Value` is recomputed whenever any source emits. The recomputed value is
emitted on `ValueChanged` **only if** it differs (by `==` semantics per
language) from the previous value (distinct-until-changed).

## 2. Construction

A derived property is built from:

- **Sources** — one or more `Observable<TSrc>` instances. The number of
  sources is unbounded in the spec; every flavor MUST support ≥5.
- **Transform** — a pure function `(s1, s2, …, sN) -> TValue` that produces
  the derived value from the latest values of the sources.
- **(Optional) Validator** — a `Func<TValue, bool>` that gates `SetValue`. If
  omitted, the property is read-only and `CanSet` returns false for all
  inputs.
- **(Optional) Write-back action** — an `Action<TValue>` invoked by
  `SetValue` after the validator passes. Use this to propagate the value
  back to the originating source(s) (e.g., set a model field).

A factory per flavor provides the canonical build entry point. The factory
takes a sequence of sources and a transform; validator and write-back are
added via chained builder methods.

## 3. Source semantics

Sources are plain `Observable<T>` instances. A common pattern is to derive a
source from the message hub:

```
source = hub.Messages
              .filter(msg => msg is PropertyChangedMessage
                          && msg.SenderObject == sourceVm
                          && msg.PropertyName == "ModelField")
              .map(_ => sourceVm.ModelField)
```

The spec does not prescribe how sources are created; it only requires that
the transform receive each source's most recent value at the moment any
source emits.

## 4. Lifecycle

A derived property holds one or more subscriptions to its sources. These
remain active until `Dispose()` is called. Consumers SHOULD treat derived
properties as owning resources and dispose them when their owning VM
destructs.

When `Dispose()` is called:

- All source subscriptions are unsubscribed.
- `ValueChanged` completes.
- Subsequent reads of `Value` return the last-computed value.
- Subsequent calls to `SetValue` are no-ops (or raise — implementation
  defined; the spec only forbids further emissions on `ValueChanged`).

## 5. Write-back

If both a validator and a write-back action are configured, `SetValue(v)`:

1. Calls `CanSet(v)`. If false, raises an error (`InvalidOperationException`
   in C#, `ValueError` in Python, an `Error` in TypeScript).
1. Otherwise, invokes the write-back action with `v`.

The write-back action is responsible for propagating `v` to the source(s).
The next emission from that source flows through the transform and updates
`Value`. The derived property does NOT short-circuit the source path.

## 6. Distinct-until-changed

Emission on `ValueChanged` is gated by equality. The exact semantics:

- C#: `EqualityComparer<TValue>.Default.Equals(prev, next)`
- Python: `prev == next` (built-in equality)
- TypeScript: `Object.is(prev, next)` (matches `distinctUntilChanged` default)

If equal, the new value still replaces `Value`, but no `ValueChanged`
emission is published. The semantics match the existing
`PROP-002` rule for VM properties.

## 7. Fixture

`fixtures/derived-properties.json` encodes scenarios the `DPROP-NNN` tests
load. Each scenario has:

- `sources`: an ordered list of source value-sequences.
- `transform`: a symbolic name resolved by the test runner (e.g., `"sum"`,
  `"concat"`).
- `mutations`: ordered `(source_index, new_value)` events.
- `expected_values`: the expected `Value` after each mutation.

## 8. Conformance

`DPROP-001` through `DPROP-012` in `12-conformance.md` cover:

- Single-source derived value computes on construction
- Source change triggers recompute
- Two-source derived value
- Five-source derived value (the spec's minimum upper bound)
- Mutation of any source recomputes
- Default-built derived property is read-only (`CanSet` returns false)
- Validator + write-back enables `SetValue`
- Write-back action receives the value
- `ValueChanged` emits on recompute
- `ValueChanged` does NOT emit if recomputed value equals previous
- `Dispose` ends subscriptions and `ValueChanged` completes
- Fixture-driven scenarios
