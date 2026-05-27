# 17 — Localization hooks

VMx ships a minimal localization contract — `ILocalizer` — plus a null-default
implementation that returns input keys unchanged. The actual localized strings
are out of scope for the core spec; per-application localizers map keys to
their host platform's idiomatic i18n (e.g., `IStringLocalizer<T>` on .NET,
`gettext` on Python, `i18next` on web).

The 2012 VMx predecessor shipped 9 satellite assemblies (de/es/fr/it/ja/ko/ru/
zh-Hans/zh-Hant) as empty resource shells. VMx 2.0 absorbs the *convention* (a
pluggable localizer hook) without the satellite shells.

## 1. Contract

```
ILocalizer:
    Localize(key: string) : string                       # required
    Localize(key: string, args: Iterable<object>) : string?   # optional, format with positional args
```

Semantics:

- `Localize(key)` returns a string. Implementations MAY return the localized
  text for `key`, the input `key` itself (passthrough), or an empty string
  for unknown keys.
- The default null-localizer (`NullLocalizer`) returns the input `key`
  unchanged for both overloads.
- The localizer is stateless from VMx's perspective: implementations may
  cache internally, but the contract surface is referentially transparent
  for a given key.

## 2. Null variant — `NullLocalizer`

Per the convention from ADR-0017, `NullLocalizer` is the null-object variant:

- `Localize(key)` returns `key` verbatim.
- `Localize(key, args)` returns `key` verbatim (no formatting applied).

`NullLocalizer` is the default when no consumer-supplied localizer is wired
into the framework. Components that emit user-visible text (notification
messages, default command labels) should resolve via the configured
`ILocalizer`.

## 3. Per-flavor distribution

The contract ships in the core `vmx` / `VMx` package. Consumers may bridge
to platform-specific i18n libraries via a thin adapter; VMx does not depend
on any platform localizer.

## 4. Conformance

`LOC-001` through `LOC-003` in `12-conformance.md` cover:

- The `ILocalizer` contract exists and returns a string from a key
- `NullLocalizer.Localize(key)` returns the key verbatim
- A custom localizer can be substituted for the null variant
