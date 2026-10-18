# ADR 0148 — Spec prose corrections from maintenance review

- **Status:** Accepted
- **Date:** 2026-10-17
- **Spec version:** 3.29.0
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md)
  (cross-flavor divergence catalogue),
  [ADR-0052](0052-v3-public-surface-breaking-removals.md) (removal of C#
  `LinqHelpers`),
  [ADR-0099](0099-searchable-source-reactivity.md) (§2.7, Rust searchable
  facade),
  [ADR-0121](0121-current-five-flavor-contract-clarifications.md) (current
  prose names all five flavors),
  [ADR-0147](0147-name-all-flavors-in-lifecycle-message-property-and-dictionary-prose.md)
  (the same correction for other chapters)

## 1. Context

A maintenance review compared spec prose with the code in all five flavors. It
found three kinds of problems:

- Prose that disagreed with every flavor:
  - Chapter 00 §6 described the C# `LinqHelpers` type as shipped. ADR-0052
    removed it in v3.0.0, and the ADR-0009 catalogue row still listed it.
  - Chapter 05 §3 said `ModeledHint` notification follows every model change.
    All five flavors notify only when the recomputed hint differs.
  - Chapter 05 §6 omitted the not-disposed condition of `can_deselect`, which
    all five flavors apply. It also said that all five flavors apply the
    "parent supports child selection" guard to `can_deselect`; only Rust's base
    component and Swift's `ForwardingComponentVM` do.
  - Chapter 06 §7 said Python and TypeScript compose the `ModeledCrudCommands`
    `current_changed` reactivity. Their helpers accept no trigger input.
  - Chapter 17 §2 said components resolve text through a framework-wired
    `ILocalizer`. No component in any flavor consumes a localizer.
- Per-flavor lists that did not name all five flavors (ADR-0121): the internal
  parent interface and the dispatcher schedulers and defaults (chapter 01), the
  `ICompositeVM` realization (chapter 06 §2.1), the builder validation error and
  the options factories (chapter 10), and the forwarding decorator shapes
  (chapter 09).
- Prose that states behavior Rust does not have, with no Rust note.

## 2. Decision

Correct the prose as the code ships it:

- Chapter 00 §6: `LinqHelpers` is described as removed by ADR-0052. The
  ADR-0009 catalogue row says the same instead of deleting the history.
- Chapter 05 §3: `PropertyChangedMessage("ModeledHint")` is emitted only when the
  recomputed hint differs from the previous hint.
- Chapter 05 §6: `can_deselect` lists `Status != Disposed`. The parenthetical
  says all five flavors apply the selection guard to `can_select`, and that
  Rust's base component and Swift's `ForwardingComponentVM` also apply it to
  `can_deselect`; the observable outcome is the same because a group has no
  current child.
- Chapter 06 §7: C#, Swift, and Rust (`with_current_changed`) accept the
  `current_changed` trigger. The Python and TypeScript helpers accept none.
- Chapter 17 §2: `ILocalizer` and `NullLocalizer` are application-level
  services that the framework does not inject.
- Chapter 01 §1.3: Swift `ParentVM` and the Rust type-erased `ParentHandle` join
  the parent-interface list.
- Chapter 01 §2, §3, and §6: C#, Python, and TypeScript dispatchers expose Rx
  schedulers; Swift and Rust dispatchers are closure-based. The default
  dispatcher is listed for all five flavors (TypeScript `queueScheduler`
  foreground and `asyncScheduler` background; Swift main queue and global
  queue; Rust `vmx-foreground` and `vmx-background` worker threads). Swift uses
  Combine and Rust uses VMx-owned streams instead of an Rx library.
- Chapter 06 §2.1: Swift realizes `ICompositeVM` as `open class CompositeVM`;
  Rust uses the concrete `CompositeVm` struct.
- Chapter 09: only the C# decorators are abstract. Python and TypeScript ship
  concrete classes, Swift ships open classes, and Rust exposes
  `with_hint_override` and `with_model_hint` instead of subclass overrides, with
  no `ForwardingCompositeVm` hooks.
- Chapter 10 §3 and §7: Rust returns `VmxError::BuilderValidation` and ships
  `ComponentVm::create`, `CompositeVm::create`, and `GroupVm::create` for the
  null-dispatcher form.
- Open Rust gaps are recorded where the chapter states behavior Rust does not
  have:
  - `Hint` and `ModeledHint` are `Option<String>` with a `None` default
    (chapters 01, 05, and 10).
  - The builder has no `OnModelChanged` callback (chapters 05 and 10).
  - `ExpandableState::expanded_changed()` returns a `MessageHub`, not an
    `Observable<bool>` (chapter 05 §8).
  - `SearchableState` has no `SearchTermChanged` stream and no debounce
    (chapter 06 §8, cross-referencing ADR-0099 §2.7).
  - The composite and group `children` factories run at `build()`, not on
    `construct()` (chapters 06 §1 and 07 §3).
  - `Localizer` has only `localize(key)`, with no args overload (chapter 17).

The change is editorial. It adds no normative behavior and no conformance ID.

## 3. Consequences

- The corrected sections agree with the code and satisfy ADR-0121.
- The Rust gaps stay open. Each is recorded, not closed; closing one changes the
  public Rust surface and needs its own decision and change.
- Python and TypeScript `ModeledCrudCommands` stay non-reactive. Adding a trigger
  input to them needs its own change.
