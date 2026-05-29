# ADR 0019 — Localization hooks

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor shipped 9 satellite assemblies as empty resource
shells (de/es/fr/it/ja/ko/ru/zh-Hans/zh-Hant). The intent was to localize
user-visible strings emitted by the framework — notification messages,
default command labels, confirmation prompts. The shells were never filled
in; localization was deferred indefinitely.

The current VMx has no localization contract. User-visible strings emerge
from notifications (ADR-0013) and confirmation prompts (ADR-0012); without a
localizer, those strings ship raw.

## 2. Options considered

1. **Skip — consumers handle localization in their applications.**
   Smallest spec surface; misses the legacy parity goal.
1. **Ship a localization hook (`ILocalizer`) + null-default.** Contract
   only; consumers wire their own implementations (gettext, i18next,
   `IStringLocalizer<T>`, etc.).
1. **Ship a full localizer plus 9 language packs.** Maximum parity with
   the predecessor; massive ongoing maintenance burden.

## 3. Decision

Option 2. Add:

- A minimal `ILocalizer` contract in the core package per flavor.
- A `NullLocalizer` null-object variant (per ADR-0017) that returns input
  keys unchanged.

The framework itself does NOT use `ILocalizer` to translate any string in
v2.0 — its purpose is to give consumers a documented hook for plugging in
their own i18n. Future spec versions MAY introduce specific keys that VMx
emits (e.g., for default command labels), but not in v2.0.

## 4. Consequences

- Three conformance IDs `LOC-001..LOC-003` cover the contract and the null
  variant.
- Each flavor exposes `ILocalizer` and `NullLocalizer` in a `localization/`
  directory.
- The 9-language satellite shells from the legacy predecessor are NOT
  reproduced. Consumers wishing for localized strings provide their own
  implementation.
- This ADR does not require the framework's existing strings (error
  messages, exception text) to be localized — they continue to ship in
  English.
- A future ADR could introduce a key catalog for VMx-emitted strings; this
  is explicitly out of scope for v2.0.
