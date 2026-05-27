# ADR 0005 — Drop virtualization from the core library

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## 1. Context

The legacy `CompositeVM` used `AlphaChiTech.VirtualizingObservableCollection` for paged virtualization of large child lists. The dependency is tied to WPF's `ItemsControl` virtualization, has not been updated since 2017, and has no direct equivalent in Python or TypeScript.

## 2. Options considered

1. **Keep paged virtualization in core.** Replace AlphaChiTech with a modern equivalent (e.g., DynamicData, or a custom paged collection). Preserves behavior parity but ports awkwardly across languages.
1. **Drop from core; optional adapter package planned for later.** Core `CompositeVM` exposes `IList<VM>` + `INotifyCollectionChanged`. An optional `VMx.Virtualization` package can ship later for users who want paged behavior.
1. **Drop permanently.** Users handle virtualization at the UI layer themselves; we never ship it.

## 3. Decision

Option 2. Virtualization is a UI-layer concern — WPF, Avalonia, and MAUI each have their own item virtualization. Putting it in the core couples the spec to one platform's primitives. A future optional adapter can ship if demand surfaces.

## 4. Consequences

- `CompositeVM<VM>` (and modeled variant) exposes only `IList<VM>` + `INotifyCollectionChanged`-equivalent semantics; no paging.
- No `VMx.Virtualization` package ships in 1.0; it's a post-1.0 follow-on.
- Existing legacy users migrating to the new library who relied on virtualization must wire it at their UI layer or wait for the adapter package.
