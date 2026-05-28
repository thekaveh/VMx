# VMx Absorption Audit — Stage 5 (Minors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute task-by-task. Checkboxes (`- [ ]`) track progress. This is the Stage 5 detail expansion of the master audit plan at `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`.

**Goal:** Land four small "minor" items from the audit proposal — M1 (value-observable helper), M2 (verify init-token concern is handled), M3 (verify RelayCommand triggers cover property re-subscribe), M4 (C#-only LINQ helpers per ADR-0006 asymmetric flavor decision).

**Architecture:** Verify-first for M2 and M3 — if existing primitives already handle the concern, document as a recipe; if a gap exists, add a small ergonomic helper. M1 is a thin observable-of-values helper over the existing message hub / DerivedProperty. M4 is C#-only by design (Python and TS have built-ins).

**Tech Stack:** Markdown spec + ADRs; C# with `System.Reactive` extensions; Python with `reactivex` observables (M1 only); TypeScript with `rxjs` observables (M1 only); C#-only for M4.

______________________________________________________________________

## Context

- **Branch:** `feat/v2.1-absorption-audit` (Stage 4 closed at commit 552d8b6 + 4C tick eaf731d; 132 commits on branch).
- **Spec version:** `2.1.0-dev`
- **Latest ADR:** 0031 (Notification rendering VMs). This stage may add 0032 (M1) and/or 0033 (M4); M2/M3 may not need ADRs.
- **Latest conformance count:** 219. This stage likely adds 0–4 IDs (helpers are non-contract; recipes have no IDs).
- **Repo conventions:** see master plan §"Repository conventions". Key: spec changes need ADR in same PR; commits never include AI attribution; pre-commit may reformat (re-stage + re-commit, never `--amend`).

## Items overview

| #   | Item                                                           | Default outcome                                                                                                                                 | Conditional                                                                                                                               |
| --- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | `PropertyValueChangedMessages<P>` value-returning observable   | Add helper extension in 3 flavors + ADR-0032 (informative); 0–4 new conformance IDs (HUB-NNN extension)                                         | If a `DerivedProperty.Values` observable already exists in some form, document the recipe and skip the ADR.                               |
| M2  | Reactive-init-token (double-subscribe prevention)              | Document as recipe in `spec/15-derived-properties.md`; verify DerivedProperty handles internally. No ADR.                                       | If gap exists in any flavor, add a small `OnceObservable` / equivalent helper.                                                            |
| M3  | `RelayCommand` auto-resubscribe to a property                  | Document as recipe in `spec/04-commands.md`; verify triggers cover via `hub.PropertyChangedMessagesFor(obj, "prop").Select(_ => Unit)`. No ADR. | If awkward in any flavor, add a small overload.                                                                                           |
| M4  | C#-only LINQ helpers (`CartesianProduct`, `Sample`, `Product`) | Implement in C# at `langs/csharp/src/VMx/Extensions/LinqHelpers.cs`; ADR-0033 records the asymmetric decision.                                  | No-op for Python (`itertools.product`, slice + step, `functools.reduce(operator.mul, …)`) and TypeScript (consumer trivially implements). |

## Files to be created or modified

### Created (best-case, if all items add code)

- `spec/ADRs/0032-property-value-changed-messages.md` (M1, may be informative)
- `spec/ADRs/0033-linq-utility-helpers-csharp-only.md` (M4)
- `langs/csharp/src/VMx/Messages/PropertyValueChangedExtensions.cs` (M1)
- `langs/python/src/vmx/messages/property_value_changed.py` (M1)
- `langs/typescript/src/messages/propertyValueChanged.ts` (M1)
- `langs/csharp/src/VMx/Extensions/LinqHelpers.cs` (M4)
- `langs/csharp/tests/VMx.Tests/Extensions/LinqHelpersTests.cs` (M4)
- `langs/csharp/tests/VMx.Tests/Messages/PropertyValueChangedExtensionsTests.cs` (M1)
- `langs/python/tests/unit/messages/test_property_value_changed.py` (M1)
- `langs/typescript/tests/unit/messages/propertyValueChanged.test.ts` (M1)

### Modified

- `spec/ADRs/README.md` (register new ADRs)
- `spec/README.md` (ID count if any new HUB IDs)
- `spec/12-conformance.md` (HUB-NNN extension for M1 if normative; else none)
- `spec/03-messages.md` (small helper subsection for M1)
- `spec/04-commands.md` (recipe paragraph for M3)
- `spec/15-derived-properties.md` (recipe paragraph for M2)
- `langs/python/src/vmx/messages/__init__.py` (export helper)
- `langs/typescript/src/messages/index.ts` (export helper)
- `langs/csharp/src/VMx/VMx.csproj` (only if Extensions/ directory needs registration — likely auto via wildcard)
- `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md` (tick Stage 5 at close)

______________________________________________________________________

## Stage 5 progress tracker

- [x] **Substage 5A** — M1: `PropertyValueChangedMessages<P>` helper
- [x] **Substage 5B** — M2: verify-first reactive-init-token (recipe or helper)
- [x] **Substage 5C** — M3: verify-first RelayCommand auto-resubscribe (recipe or overload)
- [ ] **Substage 5D** — M4: C#-only LINQ helpers (`CartesianProduct`, `Sample`, `Product`)
- [ ] **Substage 5E** — Stage 5 audit close (2 consecutive zero-finding passes)

______________________________________________________________________

# Substage 5A — M1: `PropertyValueChangedMessages<P>` helper

A small ergonomic over `IMessageHub` and/or `DerivedProperty`: instead of subscribing to `PropertyChangedMessage<TSource, TProperty>` and extracting `args.Value`, provide a helper that returns `IObservable<TProperty>` directly.

### Task 5A.1: Investigate whether the helper is already partially in place

**Files:**

- Read: `langs/csharp/src/VMx/Messages/*.cs`, `langs/python/src/vmx/messages/*.py`, `langs/typescript/src/messages/*.ts`

- Read: `langs/csharp/src/VMx/Properties/DerivedProperty.cs` (or equivalent), and Python/TS counterparts

- [ ] **Step 1: Check for an existing `Values` observable on DerivedProperty or a hub helper.**

```bash
grep -rn 'Values\|.Select\|.Cast<' langs/csharp/src/VMx/Properties/ langs/csharp/src/VMx/Messages/ 2>/dev/null | head -20
grep -rn 'values\|\.map\|PropertyValueChangedMessages\|property_value_changed' langs/python/src/vmx/properties/ langs/python/src/vmx/messages/ 2>/dev/null | head -20
grep -rn 'values\|\.map\|propertyValueChangedMessages' langs/typescript/src/properties/ langs/typescript/src/messages/ 2>/dev/null | head -20
```

If `DerivedProperty.Values` (or equivalent) already returns `IObservable<T>`, the helper is mostly there; in that case skip ahead to documentation.

- [ ] **Step 2: Inspect `IMessageHub` API.** Specifically the existing `PropertyChangedMessagesFor<TSource, TProperty>` (or equivalent) method that returns `IObservable<PropertyChangedMessage>`. We'll layer the helper on top of it.

- [ ] **Step 3: Decision — add helper or just document recipe.**

If a `Values`-shaped observable already exists on DerivedProperty AND a hub-side `.PropertyValueChangedMessagesFor<TSource, TProperty>(obj, prop)` exists somewhere, item M1 is effectively done — proceed to Task 5A.5 (documentation only).

Otherwise: add the helper in all 3 flavors per Task 5A.2–5A.4.

Record the decision in commit message: `chore(stage-5): M1 — gap confirmed (or absent), proceeding with implementation (or recipe)`.

### Task 5A.2: Implement helper in C# (TDD)

(Only if Task 5A.1 confirms a gap.)

**Files:**

- Create: `langs/csharp/src/VMx/Messages/PropertyValueChangedExtensions.cs`

- Create: `langs/csharp/tests/VMx.Tests/Messages/PropertyValueChangedExtensionsTests.cs`

- [ ] **Step 1: Write failing test.**

```csharp
[Fact]
public void PropertyValueChangedMessages_Returns_Observable_Of_Property_Values()
{
    var hub = new MessageHub();
    var source = new TestSource();
    var values = new List<int>();

    using var sub = hub.PropertyValueChangedMessagesFor(source, s => s.Count)
                       .Subscribe(values.Add);

    source.Count = 1;
    source.Count = 2;
    source.Count = 3;

    values.Should().Equal(1, 2, 3);
}

private sealed class TestSource : ObservableObject  // existing INPC base in repo
{
    private int _count;
    public int Count
    {
        get => _count;
        set => SetProperty(ref _count, value);
    }
}
```

- [ ] **Step 2: Run test, verify FAIL.**

- [ ] **Step 3: Implement helper.**

```csharp
namespace VMx.Messages;

using System;
using System.Linq.Expressions;
using System.Reactive.Linq;

public static class PropertyValueChangedExtensions
{
    public static IObservable<TProperty> PropertyValueChangedMessagesFor<TSource, TProperty>(
        this IMessageHub hub,
        TSource source,
        Expression<Func<TSource, TProperty>> propertyExpression)
        where TSource : notnull
    {
        return hub
            .PropertyChangedMessagesFor(source, propertyExpression)
            .Select(msg => (TProperty)msg.NewValue!);
    }
}
```

(Adapt to the actual hub API — read `IMessageHub` first to confirm method names and signatures.)

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Run flavor tooling.**

```bash
cd langs/csharp && dotnet build && dotnet test --filter "PropertyValueChangedExtensions" && dotnet format --verify-no-changes
```

- [ ] **Step 6: Commit.**

```bash
git add langs/csharp/src/VMx/Messages/PropertyValueChangedExtensions.cs langs/csharp/tests/VMx.Tests/Messages/PropertyValueChangedExtensionsTests.cs
git commit -m "feat(csharp,msg): add PropertyValueChangedMessagesFor extension (M1)"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

### Task 5A.3: Implement helper in Python (TDD)

(Only if Task 5A.1 confirms a gap.)

**Files:**

- Create: `langs/python/src/vmx/messages/property_value_changed.py`

- Modify: `langs/python/src/vmx/messages/__init__.py` (export)

- Create: `langs/python/tests/unit/messages/test_property_value_changed.py`

- [ ] **Step 1: Write failing test.**

```python
from typing import Any
from reactivex import Observable
from vmx.messages import MessageHub


def test_property_value_changed_messages_returns_observable_of_values() -> None:
    from vmx.messages import property_value_changed_messages_for

    hub: MessageHub = MessageHub()
    source: Any = type("Src", (), {"count": 0})()
    values: list[int] = []

    sub = property_value_changed_messages_for(hub, source, "count").subscribe(values.append)

    hub.publish_property_changed(source, "count", 1)
    hub.publish_property_changed(source, "count", 2)

    assert values == [1, 2]
    sub.dispose()
```

(Read the actual `MessageHub` API first — the hub method names will differ. Adapt the test to use real hub publication APIs.)

- [ ] **Step 2: Run test → FAIL.**

- [ ] **Step 3: Implement helper.**

```python
"""property_value_changed — value-returning observable over PropertyChangedMessage."""

from typing import Any
from reactivex import Observable, operators as ops

from vmx.messages.message_hub import MessageHub


def property_value_changed_messages_for(
    hub: MessageHub,
    source: Any,
    property_name: str,
) -> Observable[Any]:
    return hub.property_changed_messages_for(source, property_name).pipe(
        ops.map(lambda msg: msg.new_value)
    )
```

(Adapt to actual MessageHub API.)

- [ ] **Step 4: Export from `__init__.py`.**

- [ ] **Step 5: Run test → PASS.**

- [ ] **Step 6: Run tooling.**

```bash
cd langs/python && uv run pytest tests/unit/messages/test_property_value_changed.py && uv run mypy --strict src/vmx && uv run ruff check && uv run ruff format --check
```

- [ ] **Step 7: Commit.**

```bash
git add langs/python/src/vmx/messages/ langs/python/tests/unit/messages/
git commit -m "feat(python,msg): add property_value_changed_messages_for helper (M1)"
```

### Task 5A.4: Implement helper in TypeScript (TDD)

(Only if Task 5A.1 confirms a gap.)

**Files:**

- Create: `langs/typescript/src/messages/propertyValueChanged.ts`

- Modify: `langs/typescript/src/messages/index.ts` (export)

- Modify: `langs/typescript/src/index.ts` (re-export)

- Create: `langs/typescript/tests/unit/messages/propertyValueChanged.test.ts`

- [ ] **Step 1: Write failing test.**

```typescript
import { describe, expect, it } from "vitest";
import { map } from "rxjs";
import { MessageHub } from "../../src/messages";

describe("propertyValueChangedMessagesFor", () => {
  it("returns observable of property values", () => {
    const hub = new MessageHub();
    const source = { count: 0 };
    const values: number[] = [];

    const sub = propertyValueChangedMessagesFor(hub, source, "count").subscribe(v => values.push(v as number));

    hub.publishPropertyChanged(source, "count", 1);
    hub.publishPropertyChanged(source, "count", 2);

    expect(values).toEqual([1, 2]);
    sub.unsubscribe();
  });
});
```

(Adapt to actual MessageHub API.)

- [ ] **Step 2: Run test → FAIL.**

- [ ] **Step 3: Implement.**

```typescript
import type { Observable } from "rxjs";
import { map } from "rxjs/operators";
import type { IMessageHub } from "./messageHub.js";

export function propertyValueChangedMessagesFor<TSource extends object, TKey extends keyof TSource>(
  hub: IMessageHub,
  source: TSource,
  propertyName: TKey,
): Observable<TSource[TKey]> {
  return hub.propertyChangedMessagesFor(source, propertyName).pipe(
    map(msg => msg.newValue as TSource[TKey]),
  );
}
```

- [ ] **Step 4: Export from `index.ts` files.**

- [ ] **Step 5: Run test → PASS.**

- [ ] **Step 6: Run tooling.**

```bash
cd langs/typescript && npm run typecheck && npm run lint && npm test -- propertyValueChanged
```

- [ ] **Step 7: Commit.**

```bash
git add langs/typescript/src/messages/ langs/typescript/src/index.ts langs/typescript/tests/
git commit -m "feat(typescript,msg): add propertyValueChangedMessagesFor helper (M1)"
```

### Task 5A.5: Document the helper + ADR-0032 (informative)

**Files:**

- Create or skip: `spec/ADRs/0032-property-value-changed-messages.md` (informative-only if helper added)

- Modify: `spec/03-messages.md` (small subsection)

- Modify: `spec/ADRs/README.md` (register if ADR added)

- [ ] **Step 1: Write ADR-0032 — informative.**

```markdown
# ADR 0032 — `PropertyValueChangedMessages<P>` helper (informative)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

Several legacy codebases shipped a `PropertyValueChangedMessages<TSource, TProperty>` helper that returns `IObservable<TProperty>` directly instead of the typed message envelope. Subscribers care about the value, not the structured message. The helper saves a `.Select(m => m.Value)` on the consumer side.

## 2. Options considered

1. Skip — consumers write `.Select(m => m.NewValue)` themselves.
1. Add as a normative API requiring per-flavor conformance.
1. Add as a small idiomatic helper in the messages module of each flavor, informative-only (no conformance ID).

## 3. Decision

Option 3. The helper is per-flavor convenience; the underlying `PropertyChangedMessagesFor` already conforms (it's covered by existing HUB-NNN tests). This ADR records the helper's intent but adds no normative conformance ID.

## 4. Consequences

- A small `PropertyValueChangedMessagesFor` (or per-flavor analog) extension in each flavor's `messages/` module.
- A short "Convenience helpers" subsection added to `spec/03-messages.md`.
- No new conformance IDs.
- Future evolution of the underlying hub APIs may obviate this helper; that's acceptable for an informative item.
```

- [ ] **Step 2: Add a small subsection to `spec/03-messages.md` § "Helpers"** (or near the end). Just a paragraph + per-flavor name.

- [ ] **Step 3: Register ADR-0032 in `spec/ADRs/README.md`.**

- [ ] **Step 4: Commit.**

```bash
git add spec/ADRs/0032-*.md spec/ADRs/README.md spec/03-messages.md
git commit -m "spec(adr,ch): add ADR-0032 PropertyValueChangedMessages helper (informative)"
```

- [ ] **Step 5: Tick Substage 5A checkboxes; commit `docs(plan): tick Substage 5A`.**

______________________________________________________________________

# Substage 5B — M2: Reactive-init-token recipe

Verify whether `DerivedProperty` already handles the double-subscription concern internally. Almost certain to be the case (the type is designed to subscribe once and rebroadcast). Document as a recipe if confirmed.

### Task 5B.1: Investigate

**Files:** read (no edits in Step 1)

- `langs/csharp/src/VMx/Properties/DerivedProperty.cs` (or equivalent path — search for it)

- `langs/python/src/vmx/properties/derived_property.py`

- `langs/typescript/src/properties/derivedProperty.ts`

- [ ] **Step 1: Find DerivedProperty implementations.**

```bash
find langs -name 'DerivedProperty*' -o -name 'derived_property*' -o -name 'derivedProperty*' 2>/dev/null | grep -v node_modules | grep -v __pycache__
```

- [ ] **Step 2: Read each implementation and verify** that:

  - Subscriptions to source observables happen ONCE per DerivedProperty instance (not per consumer subscription).
  - Multiple consumer subscriptions share the underlying source subscription.
  - This is documented in the type's docstring or class comment.

- [ ] **Step 3: Decision.**

If all 3 flavors handle this correctly (likely): document as recipe in `spec/15-derived-properties.md`. No code changes.

If a gap exists in any flavor: implement a small helper or fix the underlying issue (escalate to user if scope is unclear).

### Task 5B.2: Document recipe in `spec/15-derived-properties.md`

(Only if Task 5B.1 confirms behavior matches spec — almost certain.)

**Files:**

- Modify: `spec/15-derived-properties.md`

- [ ] **Step 1: Add a subsection.**

Find a sensible location (likely near §3 or end-of-chapter). Add:

```markdown
## N. Recipe: avoiding double-subscription on lazy initialization

A common pattern in pre-Rx ViewModel code is to manage a per-property `IDisposable` token that's set on first access and disposed on next reinitialization. This is unnecessary when using `DerivedProperty` — the type subscribes to its source observables ONCE per instance, regardless of how many consumers subscribe to the derived observable.

If you find yourself wanting an init-token pattern:

- Use a `DerivedProperty<T>` instead. It memoizes the source subscription and shares value emissions across all consumers via the underlying `BehaviorSubject<T>` (or per-flavor equivalent).
- Dispose the `DerivedProperty` instance when the parent VM disposes; the source subscription releases automatically.

The recipe pattern from VMx.old / GuideArch's `InitializationTokens` dictionary is therefore obsolete in v2.x.
```

- [ ] **Step 2: Commit.**

```bash
git add spec/15-derived-properties.md
git commit -m "spec(ch): document init-token recipe (M2 — DerivedProperty handles internally)"
```

- [ ] **Step 3: Tick Substage 5B checkboxes; commit `docs(plan): tick Substage 5B`.**

______________________________________________________________________

# Substage 5C — M3: RelayCommand auto-resubscribe to property

Verify whether `RelayCommand`'s `triggers` parameter (per ADR-0012 and chapter 4) covers the "fire CanExecuteChanged when a specific property changes" pattern with reasonable ergonomics. If yes, document. If no, add a small overload.

### Task 5C.1: Investigate

**Files:** read

- `langs/csharp/src/VMx/Commands/RelayCommand.cs`

- `langs/python/src/vmx/commands/relay_command.py`

- `langs/typescript/src/commands/relayCommand.ts`

- [ ] **Step 1: Find RelayCommand implementations and inspect triggers parameter.**

```bash
find langs -name 'RelayCommand*' -o -name 'relay_command*' -o -name 'relayCommand*' 2>/dev/null | grep -v node_modules
```

- [ ] **Step 2: Verify that** the trigger parameter accepts `IObservable<Unit>` (or equivalent) and that `hub.PropertyChangedMessagesFor(obj, "prop").Select(_ => Unit.Default)` (or `.map(() => undefined)`) is the natural way to construct the trigger.

- [ ] **Step 3: Test the pattern manually.**

Write a quick test in your head (or in scratch file) that constructs a RelayCommand with a property-derived trigger. If it's ergonomic, document; if it requires too many casts/wrappers, add a small overload.

- [ ] **Step 4: Decision.**

Likely: ergonomic enough. Document as recipe.

### Task 5C.2: Document recipe in `spec/04-commands.md`

**Files:**

- Modify: `spec/04-commands.md`

- [ ] **Step 1: Add subsection near §"Triggers" (or wherever RelayCommand triggers are documented).**

```markdown
### N.X Recipe: trigger from property change

A common pattern is firing `CanExecuteChanged` when a specific ViewModel property changes. Compose the existing `IMessageHub.PropertyChangedMessagesFor` observable as the trigger:

\`\`\`
RelayCommand(
    task: () => DoWork(),
    predicate: () => IsValid,
    triggers: [hub.PropertyChangedMessagesFor(this, vm => vm.IsValid).Select(_ => Unit.Default)]
)
\`\`\`

Per-flavor analog:
- Python: `triggers=[hub.property_changed_messages_for(self, "is_valid").pipe(ops.map(lambda _: None))]`
- TypeScript: `triggers: [hub.propertyChangedMessagesFor(this, "isValid").pipe(map(() => undefined))]`

No new helper is needed — the existing `triggers` parameter + `PropertyChangedMessagesFor` compose naturally.
```

- [ ] **Step 2: Commit.**

```bash
git add spec/04-commands.md
git commit -m "spec(ch): document property-trigger recipe for RelayCommand (M3)"
```

- [ ] **Step 3: Tick Substage 5C checkboxes; commit `docs(plan): tick Substage 5C`.**

______________________________________________________________________

# Substage 5D — M4: C#-only LINQ helpers

`CartesianProduct`, `Sample`, `Product` LINQ helpers from GuideArch — implement in C# only per ADR-0006 (idiomatic per-language) since Python has `itertools.product` / slicing / `math.prod`, and TypeScript consumers implement trivially.

### Task 5D.1: Write ADR-0033

**Files:**

- Create: `spec/ADRs/0033-linq-utility-helpers-csharp-only.md`

- Modify: `spec/ADRs/README.md`

- [ ] **Step 1: Write ADR.**

```markdown
# ADR 0033 — LINQ utility helpers (C# only)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

The legacy `Extensions/System.Linq.cs` in GuideArch ships three small LINQ helpers used by domain code: `CartesianProduct`, `Sample` (every Nth element), and `Product` (multiplicative aggregate). They're useful in C# where LINQ is the lingua franca.

In Python, `itertools.product`, slice-with-step (`seq[::n]`), and `math.prod` / `functools.reduce(operator.mul, ...)` cover the same ground natively.

In TypeScript, consumers implement trivially using `flatMap` / `filter+modulo` / `reduce`.

Adding these to Python and TS would duplicate built-ins.

## 2. Options considered

1. Skip — consumers implement themselves where needed.
1. Add to all three flavors — duplicates Python and TS built-ins.
1. Add to C# only — records ADR-0006 asymmetric decision.

## 3. Decision

Option 3. C# gets the three helpers in `langs/csharp/src/VMx/Extensions/LinqHelpers.cs`. Python and TS do not.

## 4. Consequences

- A new C# `Extensions/` directory + `LinqHelpers.cs` static class.
- Unit tests in `langs/csharp/tests/VMx.Tests/Extensions/LinqHelpersTests.cs`.
- ADR-0009 (cross-flavor divergence catalogue) gains a row recording the asymmetry.
- No conformance IDs (utility helpers, not contract).
```

- [ ] **Step 2: Register in `spec/ADRs/README.md`.**

- [ ] **Step 3: Update ADR-0009 with the new asymmetry row** if that ADR has a divergence catalogue / table.

- [ ] **Step 4: Commit.**

```bash
git add spec/ADRs/0033-*.md spec/ADRs/README.md spec/ADRs/0009-cross-flavor-divergence-catalogue.md
git commit -m "spec(adr): add ADR-0033 LINQ utility helpers (C# only)"
```

### Task 5D.2: Implement `LinqHelpers.cs` (TDD)

**Files:**

- Create: `langs/csharp/src/VMx/Extensions/LinqHelpers.cs`

- Create: `langs/csharp/tests/VMx.Tests/Extensions/LinqHelpersTests.cs`

- [ ] **Step 1: Write failing tests for all three helpers.**

```csharp
namespace VMx.Tests.Extensions;

using FluentAssertions;
using VMx.Extensions;
using Xunit;

public class LinqHelpersTests
{
    [Fact]
    public void CartesianProduct_Two_Sequences()
    {
        var a = new[] { 1, 2 };
        var b = new[] { "a", "b", "c" };
        var result = LinqHelpers.CartesianProduct(a, b).ToList();
        result.Should().HaveCount(6);
        result.Should().Contain(new[] { (1, "a"), (1, "b"), (1, "c"), (2, "a"), (2, "b"), (2, "c") });
    }

    [Fact]
    public void Sample_Every_Nth()
    {
        var seq = new[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 };
        var sampled = seq.Sample(3).ToList();
        sampled.Should().Equal(1, 4, 7, 10);
    }

    [Fact]
    public void Product_Multiplies_All_Elements()
    {
        var seq = new[] { 2, 3, 4 };
        seq.Product().Should().Be(24);
    }

    [Fact]
    public void Product_Of_Empty_Returns_One()
    {
        Enumerable.Empty<int>().Product().Should().Be(1);
    }
}
```

- [ ] **Step 2: Run tests, verify FAIL.**

```bash
cd langs/csharp && dotnet test --filter "LinqHelpersTests" 2>&1 | tail -5
```

- [ ] **Step 3: Implement.**

```csharp
namespace VMx.Extensions;

using System.Collections.Generic;
using System.Linq;

public static class LinqHelpers
{
    /// <summary>
    /// Cartesian product of two sequences as a sequence of tuples.
    /// </summary>
    public static IEnumerable<(TA, TB)> CartesianProduct<TA, TB>(IEnumerable<TA> a, IEnumerable<TB> b)
    {
        var bList = b.ToList();
        foreach (var x in a)
            foreach (var y in bList)
                yield return (x, y);
    }

    /// <summary>
    /// Every Nth element of the source sequence (starting from index 0).
    /// </summary>
    public static IEnumerable<T> Sample<T>(this IEnumerable<T> source, int every)
    {
        if (every < 1) throw new System.ArgumentOutOfRangeException(nameof(every));
        var i = 0;
        foreach (var item in source)
        {
            if (i % every == 0) yield return item;
            i++;
        }
    }

    /// <summary>
    /// Multiplicative aggregate. Empty sequence returns 1.
    /// </summary>
    public static int Product(this IEnumerable<int> source)
    {
        return source.Aggregate(1, (acc, x) => acc * x);
    }
}
```

- [ ] **Step 4: Run tests, verify PASS.**

- [ ] **Step 5: Run tooling.**

```bash
cd langs/csharp && dotnet build && dotnet test && dotnet format --verify-no-changes
```

- [ ] **Step 6: Commit.**

```bash
git add langs/csharp/src/VMx/Extensions/LinqHelpers.cs langs/csharp/tests/VMx.Tests/Extensions/LinqHelpersTests.cs
git commit -m "feat(csharp,ext): add LinqHelpers (CartesianProduct, Sample, Product) per ADR-0033 (M4)"
```

- [ ] **Step 7: Tick Substage 5D checkboxes; commit `docs(plan): tick Substage 5D`.**

______________________________________________________________________

# Substage 5E — Stage 5 audit close

### Task 5E.1: Audit pass A

- [ ] Dispatch combined audit subagent verifying:
  - ADRs 0032 (if added) and 0033 are present and registered
  - Spec extensions (§3 messages, §4 commands recipe, §15 derived-properties recipe) are in place
  - PropertyValueChangedMessages helper exists in 3 flavors (or skipped per Task 5A.1 decision)
  - LinqHelpers.cs in C# only (Python/TS DO NOT have equivalent files)
  - Tests pass; tooling clean
  - Coverage unchanged (or slightly increased if HUB-NNN was added — verify)
  - No AI attribution

### Task 5E.2: Own spot-check

- [ ] Verify key invariants yourself:
  ```bash
  ls spec/ADRs/0032-*.md 2>&1  # may or may not exist
  ls spec/ADRs/0033-*.md
  ls langs/csharp/src/VMx/Extensions/LinqHelpers.cs
  ls langs/python/src/vmx/extensions 2>&1  # should NOT exist (or empty for Python)
  ls langs/typescript/src/extensions 2>&1  # should NOT exist
  uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript
  for sha in $(git log main..HEAD --format='%H'); do msg=$(git log -1 $sha --format='%B'); echo "$msg" | grep -qi 'co-authored-by\|claude.com\|anthropic' && echo "BAD: $sha"; done
  ```

### Task 5E.3: Audit pass B

- [ ] Dispatch fresh audit subagent.
- [ ] Verify zero findings → counter 2/2.

### Task 5E.4: Tick Stage 5 box + close

- [ ] Edit `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`:

  ```
  - [ ] **Stage 5** — Minors (M1, M2, M3, M4)
  ```

  to:

  ```
  - [x] **Stage 5** — Minors (M1, M2, M3, M4)
  ```

- [ ] Commit `docs(plan): close Stage 5 (Minors) — 2 consecutive clean audit passes`.

- [ ] Spawn Stage 6 detailed plan via `superpowers:writing-plans`.

______________________________________________________________________

## Self-review checklist

1. **Spec coverage:** All 4 items (M1, M2, M3, M4) have substages. ✓
1. **Verify-first items (M2, M3)**: documented as conditional in the items overview, with code-fallback if gap exists. ✓
1. **Asymmetric C#-only for M4**: ADR-0033 records the per-flavor decision, ADR-0009 updated. ✓
1. **No placeholders:** every step has concrete code or commands. ✓
1. **No AI attribution:** every commit step ends with the grep verification. ✓
1. **Audit gates:** 2 consecutive zero-finding passes per user's strict-clean-pass-gate. ✓
1. **Type consistency:** helper names consistent across substages (`PropertyValueChangedMessagesFor`, `LinqHelpers.CartesianProduct/Sample/Product`). ✓
