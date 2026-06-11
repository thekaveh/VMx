# ADR 0038 — Spec accuracy corrections (ch. 14/16/20/21) and FORM-014

**Status:** Accepted (2026-06-11)
**Spec version:** 2.5.0

## 1. Context

A maintenance audit cross-checked chapters 14–21 against all three full-parity
implementations and found four classes of drift where the spec described
behavior no flavor implements (or omitted behavior every flavor implements):

1. **Chapter 21 batch scope.** §1.2 claimed `ObservableList<T>` and
   `ServicedObservableCollection<T>` "participate in" `CompositeVM.BatchUpdate()`
   suppression "when they are held by a VM that initiates a batch", and §3.5
   framed batching as "a `BatchUpdate()` scope … active on the owning VM".
   In every flavor, batching is **local to each type**: `CompositeVM` has its
   own `BatchUpdate()` (spec/06), `ObservableList` has its own
   (`BatchUpdate()` / `batch_update()` / `withBatch()`), and
   `ServicedObservableCollection` has **no batch mechanism at all**. There is
   no cross-object participation, and COL-009 exercises the list's own scope
   with no VM involved.
1. **Chapter 21 message shape.** §2.4 documented
   `CollectionChangedMessage.Action : CollectionAction` and
   `StartingIndex : int`. No flavor has a `CollectionAction` type (C# reuses
   BCL `NotifyCollectionChangedAction`, Python uses action strings, TypeScript
   `CollectionMutationAction`), and all three ship the index member as
   `Index` / `index`.
1. **Chapter 21 dictionary internals.** §4.1 described the two-key
   `ObservableDictionary` as "a thin typed wrapper over a base
   `ObservableDictionary<TKey, TValue>`". No base type exists in any flavor;
   each is a standalone class over a per-flavor compound-key backing store
   (and TypeScript's internal key is a serialized string, not an object
   literal).
1. **Chapter 20 post-dispose behavior.** All three flavors guard
   `ApproveCommand`/`DenyCommand` (and the awaitable approve entry point) so a
   disposed form is a **full no-op** — in particular the persister delegate is
   never invoked after `Dispose()`. The chapter and the FORM catalog were
   silent; only unit tests pinned it.

Two smaller documentation bugs ride along: the chapter 16 §8.1 composition
recipe read `hub.Pending.Value`, a snapshot accessor no flavor exposes; and
chapter 14's Rule 4 ("every capability with a verb also exposes a `can_*`
predicate") contradicts §2.10's `IPageable`, whose four `move_to_*` verbs are
deliberately bound-safe and predicate-free.

## 2. Decision

- **Spec text follows the implementations** for items 1–3 (the implementations
  are mutually consistent and predate the prose): batch suppression is
  re-scoped to the type that owns the scope, the message members are renamed
  (`Index`; per-flavor action type noted), and the dictionary wording drops the
  non-existent base type.
- **Item 4 is promoted to normative**: chapter 20 gains a disposal rule and a
  new conformance ID **FORM-014** ("disposed form is inert: approve does not
  invoke the persister; deny does not revert"), with stubs in all three
  full-parity flavors (the behavior and unit tests shipped in v2.5.0
  maintenance; this ADR adds the catalog entry and conformance markers).
  The library ID count goes from 229 to 230 (235 total with THEME).
- The chapter 16 recipe is rewritten to a subscribe-and-cache snapshot, and
  chapter 14's Rule 4 is scoped to exclude documented bound-safe verb families.
- C# `ServicedObservableCollection.Move` skipping the hub message (it raises
  only the platform `CollectionChanged` event) is recorded in the ADR-0009
  divergence catalogue rather than respecified.

## 3. Consequences

- No code changes in any flavor; the three FORM-014 conformance tests pin
  behavior that already exists.
- Chapter 21's prose can no longer be read as requiring cross-object batch
  participation, which previous audits repeatedly flagged as an apparent
  implementation gap.
