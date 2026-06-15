# ADR 0039 — `INotifyPropertyChanging` not supported

**Status:** Accepted (2026-06-13)
**Spec version:** 2.6.0 (teaching ADR; no code change)
**Related:** ADR-0006, ADR-0018, ADR-0040, `spec/proposals/2026-06-13-vmx-absorption-audit-followup.md` §6 L1

## 1. Context

The 2012 predecessors (`My.Architecture.New`, `GuideArch.Older/VMx`) implemented `INotifyPropertyChanging` alongside `INotifyPropertyChanged`. `My.Architecture.New/Core/ObservableBase.cs` exposed paired `RaisePropertyChanging` / `RaisePropertyChanged` methods, and the `MessagingService` bubbled both events through extension helpers (`PropertyChangingMessages`, `BubbleOnPropertyChanging`).

The `dotnet-tag/VMx` ancestor (immediate structural predecessor of current VMx) already dropped this support — `IComponentVM` there inherits `INotifyPropertyChanged` only. Current VMx kept that simplification. The 2026-06-13 absorption-audit follow-up re-surfaced the question.

## 2. Decision

VMx does not support `INotifyPropertyChanging`. None of the four flavors expose a "property is about to change" notification.

## 3. Rationale

- **.NET-only feature.** `INotifyPropertyChanging` is a `System.ComponentModel` interface with no idiomatic Python, TypeScript, or Swift equivalent. Adopting it would either violate ADR-0006 (idiomatic-API-per-language symmetry) or force three roughly-equivalent surrogate idioms.
- **`IMessageHub` covers the underlying use case.** Consumers needing pre-change observation subscribe to `PropertyChangedMessage` and capture the prior value before publishing the setter — explicit, testable, and observable from any flavor.
- **No consumer demand.** No flagship example, no GitHub issue, and no internal use case has surfaced requiring veto-style or pre-change-snapshot semantics. The silent drop between `My.Architecture.New` and `dotnet-tag` was itself a signal of low demand.
- **Veto semantics are out of scope.** "About-to-change with the ability to cancel" is the most cited reason for `INotifyPropertyChanging`. VMx commands cover the veto pattern via `CanExecute`; properties intentionally do not.

## 4. Consequences

- `ComponentVMBase` and `ComponentVMBaseOfM<M>` implement `INotifyPropertyChanged` only (or the per-flavor equivalent).
- A future consumer asking for pre-change observation gets the hub-subscription recipe in the response, not a new interface.
- This ADR may be reconsidered if (a) a `THEME-NNN` scenario requires transactional changing→changed observation, or (b) ADR-0040 (`IProperty<T>`) is reopened — the two are conceptually paired.
