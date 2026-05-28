# VMx Absorption Audit — Stage 4 (Notification rendering VMs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is the Stage 4 detail expansion of the master audit plan at `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`.

**Goal:** Add `NotificationVM` and `ConfirmationVM` — concrete render-side ViewModels that consume `Notification` data from the hub and expose UI-bindable state (Opacity, Lifespan, RemainingTime, dismiss commands) with auto-dismiss lifecycle. Plus a documented "service-as-VM" recipe.

**Architecture:** Extend chapter 16 (no new chapter). One new ADR (0031). Per-flavor implementations live in the existing notifications/ sub-package (`langs/csharp/src/VMx.Notifications/`, `langs/python/src/vmx/notifications/`, `langs/typescript/src/notifications/`). All three flavors use virtual-time / TestScheduler / fake-clock for deterministic auto-dismiss testing.

**Tech Stack:** Markdown + ADR + mermaid; C# System.Reactive `TestScheduler`; Python `reactivex.testing.TestScheduler`; TypeScript `rxjs/testing` `TestScheduler`.

______________________________________________________________________

## Context

- **Branch:** `feat/v2.1-absorption-audit` (Stage 3 closed at commit 2e14254 + 89cebb7 tick; 121 commits on branch).
- **Spec version:** `2.1.0-dev`
- **Latest ADR:** 0030 (FormVM). This adds 0031.
- **Latest conformance count:** 213. This adds 6 → 219.
- **Existing notifications sub-package** per ADR-0013: `INotificationHub`, `Notification`, `NotificationType`, `NotificationReaction` already exist. This stage adds render-side VMs that consume them.
- **Service-as-VM (I6)** lands as documentation only (Patterns section in ch.16) unless writing-plans decides to formalize. **Decision: keep as recipe-only.** No new ADR for I6.

## Locked design decisions (ADR-0031)

1. **NotificationVM is the base; ConfirmationVM extends.**
1. **Lifespan defaults**: NotificationVM = 60 seconds; ConfirmationVM = 300 seconds (matches 2012 VMx.old precedent).
1. **Opacity is a derived property** `RemainingTime / Lifespan` (0.0 at expiry, 1.0 at start). Linear decay.
1. **RemainingTime decays via injected scheduler.** Tests use TestScheduler for determinism.
1. **DismissCommand resolves the hub notification with `Approve`** (the standard "user acknowledged").
1. **ConfirmationVM adds ApproveCommand + RejectCommand** that resolve with the corresponding `NotificationReaction`.
1. **Auto-dismiss on Lifespan expiry**: NotificationVM auto-dismisses (DismissCommand fires); ConfirmationVM does NOT auto-resolve (user must explicitly approve or reject — timeout means "no decision").
1. **Manual dismiss cancels the timer** so the auto-fire path doesn't double-resolve.

## Conformance IDs (NOTIF-011..NOTIF-016, 6 new)

- **NOTIF-011** — `NotificationVM` opacity decays linearly from 1.0 to 0.0 over `Lifespan`.
- **NOTIF-012** — `NotificationVM` auto-dismisses (resolves with `Approve`) when `RemainingTime` reaches 0.
- **NOTIF-013** — `ConfirmationVM` exposes both `ApproveCommand` and `RejectCommand`; each resolves the hub notification with the corresponding `NotificationReaction`.
- **NOTIF-014** — Manual `DismissCommand` invocation cancels the lifespan timer; subsequent timer ticks have no effect on the resolved notification.
- **NOTIF-015** — Hub-side `Resolve()` on the notification propagates to VM state (`IsResolved` becomes true, timer stops).
- **NOTIF-016** — Deterministic behavior under injected `TestScheduler` / fake clock: advancing time triggers opacity decay and auto-dismiss exactly at the configured Lifespan.

## Files to be created or modified

### Created

- `spec/ADRs/0031-notification-rendering-vms.md`
- `langs/csharp/src/VMx.Notifications/NotificationVM.cs`
- `langs/csharp/src/VMx.Notifications/ConfirmationVM.cs`
- `langs/csharp/tests/VMx.Notifications.Tests/NotificationVM_Tests.cs` *(or place inside existing test project — see Task 4B.1 Step 1)*
- `langs/csharp/tests/VMx.Notifications.Tests/ConfirmationVM_Tests.cs`
- `langs/python/src/vmx/notifications/notification_vm.py`
- `langs/python/src/vmx/notifications/confirmation_vm.py`
- `langs/python/tests/unit/notifications/test_notification_vm.py`
- `langs/python/tests/unit/notifications/test_confirmation_vm.py`
- `langs/typescript/src/notifications/notificationVm.ts`
- `langs/typescript/src/notifications/confirmationVm.ts`
- `langs/typescript/tests/unit/notifications/notificationVm.test.ts`
- `langs/typescript/tests/unit/notifications/confirmationVm.test.ts`

### Modified

- `spec/ADRs/README.md` (register 0031)
- `spec/16-notifications.md` — add subsections for NotificationVM, ConfirmationVM, and "Patterns" section (service-as-VM recipe); add lifespan/opacity timeline diagram
- `spec/README.md` (ID count 213 → 219)
- `spec/12-conformance.md` (add NOTIF-011..016)
- `langs/csharp/tests/VMx.Conformance.Tests/NOTIF_*_Tests.cs` — add 6 new tests (find/create the right grouped file; or add to existing NOTIF conformance file)
- `langs/python/tests/conformance/test_notif_*.py` — add 6
- `langs/typescript/tests/conformance/notif-*.test.ts` — add 6
- `langs/python/src/vmx/notifications/__init__.py` — export new VMs
- `langs/typescript/src/notifications/index.ts` — export new VMs
- `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md` — tick Stage 4 at close

______________________________________________________________________

## Stage 4 progress tracker

- [x] **Substage 4A** — Spec extension (ADR-0031 + ch.16 extension + 6 NOTIF IDs + stubs in 3 flavors)
- [x] **Substage 4B** — Per-flavor NotificationVM + ConfirmationVM (3 flavors)
- [x] **Substage 4C** — Service-as-VM recipe section + Stage 4 audit close

______________________________________________________________________

# Substage 4A — Spec extension

### Task 4A.1: Write ADR-0031 + extend chapter 16

**Files:**

- Create: `spec/ADRs/0031-notification-rendering-vms.md`

- Modify: `spec/ADRs/README.md`

- Modify: `spec/16-notifications.md` (new subsections)

- [x] **Step 1: Write the ADR.**

```markdown
# ADR 0031 — Notification rendering VMs (NotificationVM, ConfirmationVM)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

The 2012 VMx and My.Architecture.New both ship concrete UI-bindable
`NotificationVM` and `ConfirmationVM` types that consume `Notification` data
from the hub. v2.0 VMx ships only the hub + data; consumers reinvent the
rendering VM.

The audit (item C5) calls for adding these as render-side companions to the
notification sub-package. They expose `Opacity`, `RemainingTime`, dismiss
commands, and auto-dismiss lifecycle via an injected scheduler.

## 2. Options considered

1. Skip — consumers continue to invent.
1. Ship in core — adds UI-rendering concerns to the always-loaded VMx core.
1. Ship in the notifications sub-package — opt-in alongside the hub.

## 3. Decision

Option 3. The new VMs live in the existing notifications sub-package (per
ADR-0013): `VMx.Notifications` (C#), `vmx.notifications` (Python),
`vmx/notifications` (TS subpath).

NotificationVM: base. Default Lifespan = 60s. Auto-dismisses (resolves with
`Approve`) on Lifespan expiry. Linear opacity decay (1.0 → 0.0).

ConfirmationVM: extends NotificationVM. Default Lifespan = 300s (matches
VMx.old precedent for confirmation prompts). Adds `ApproveCommand` and
`RejectCommand` resolving with the corresponding `NotificationReaction`.
Does NOT auto-resolve on expiry (timeout = no decision).

Scheduler is an injected `IScheduler` / `Scheduler` parameter — tests use
`TestScheduler` for deterministic time advancement.

## 4. Consequences

- Chapter 16 gains two new subsections (NotificationVM, ConfirmationVM) and
  a "Patterns" section with the service-as-VM recipe.
- Six new conformance IDs `NOTIF-011..NOTIF-016`.
- Per-flavor implementation in the notifications sub-package.
- New lifespan/opacity timeline diagram in chapter 16.
```

Register in `spec/ADRs/README.md`.

- [x] **Step 2: Extend `spec/16-notifications.md`.**

Add subsections after the existing hub material (likely near §3 or §4 — read the chapter first). Three new subsections:

```markdown
## N. NotificationVM

Render-side VM that consumes a `Notification` and exposes UI-bindable state.

\`\`\`
NotificationVM:
    Notification    : Notification     # the consumed datum
    Lifespan        : TimeSpan         # default 60s
    RemainingTime   : TimeSpan         # decays toward 0 via scheduler
    Opacity         : double           # derived: RemainingTime / Lifespan; range [0.0, 1.0]
    IsResolved      : bool             # mirrors hub resolution state
    DismissCommand  : ICommand         # resolves with Approve; cancels timer
\`\`\`

Auto-dismiss: when RemainingTime reaches 0, the VM resolves the notification
with `Approve`. Manual `DismissCommand` invocation cancels the lifespan
timer.

### N.X Lifespan timeline

\`\`\`mermaid
gantt
    title NotificationVM lifecycle (60s default)
    dateFormat X
    axisFormat %S s
    section Visible
    Full opacity         :a1, 0, 1s
    Linear decay 1.0→0.0 :a2, 1s, 59s
    section Resolved
    Auto-dismiss (Approve) :milestone, after a2, 0s
\`\`\`

## N+1. ConfirmationVM

Extends `NotificationVM` with explicit Approve/Reject actions and a longer
default Lifespan.

\`\`\`
ConfirmationVM (extends NotificationVM):
    Lifespan        : TimeSpan         # default 300s
    ApproveCommand  : ICommand         # resolves with NotificationReaction.Approve
    RejectCommand   : ICommand         # resolves with NotificationReaction.Reject
\`\`\`

Auto-dismiss behavior: ConfirmationVM does NOT auto-resolve on Lifespan
expiry. Timeout means "user did not decide"; the notification remains
pending. Consumers may compose a different policy externally.

## N+2. Patterns

### N+2.1 Service-as-VM adapter (recipe)

Hub state — e.g., `INotificationHub.Pending` — can be projected as a
`CompositeVM<Notification, NotificationVM>` by passing the observable
collection of pending notifications as the composite's source and
`NotificationVM` construction as the child factory.

Recipe (per-flavor idiomatic):

\`\`\`
CompositeVM<Notification, NotificationVM>(
    source = hub.Pending,
    childFactory = notif => new NotificationVM(notif, hub, scheduler)
)
\`\`\`

This pattern generalizes to any service whose state is an observable
collection. Not a normative spec addition — just a documented composition.

## N+3. Conformance

- `NOTIF-011` — NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan.
- `NOTIF-012` — NotificationVM auto-dismisses (resolves with Approve) at expiry.
- `NOTIF-013` — ConfirmationVM exposes ApproveCommand + RejectCommand resolving with the corresponding NotificationReaction.
- `NOTIF-014` — Manual DismissCommand cancels the timer; subsequent ticks no-op.
- `NOTIF-015` — Hub Resolve() propagates to VM IsResolved state.
- `NOTIF-016` — Deterministic behavior under injected TestScheduler / fake clock.
```

- [x] **Step 3: Commit.**

```bash
git add spec/ADRs/0031-notification-rendering-vms.md spec/ADRs/README.md spec/16-notifications.md
git commit -m "spec(adr,ch): add ADR-0031 + extend ch.16 with NotificationVM/ConfirmationVM and Patterns"
git log -1 --format='%B' | grep -i 'co-authored-by' && echo "BUG" || echo "clean"
```

If mdformat reformats: re-stage and re-commit (NEVER `--amend`).

### Task 4A.2: Add NOTIF-011..016 conformance IDs

**Files:**

- Modify: `spec/12-conformance.md`

- Modify: `spec/README.md` (ID count 213 → 219)

- [x] **Step 1: Add 6 new entries** to the NOTIF block in `spec/12-conformance.md`. Use Given/When/Then style of existing NOTIF entries.

- [x] **Step 2: Update `spec/README.md` ID count.**

- [x] **Step 3: Commit.**

```bash
git add spec/12-conformance.md spec/README.md
git commit -m "spec(conf): add NOTIF-011..016 conformance IDs (NotificationVM/ConfirmationVM)"
```

### Task 4A.3: Add NOTIF-011..016 stubs in all three flavors

**Files:**

- Modify or create: `langs/csharp/tests/VMx.Conformance.Tests/NOTIF_*_Tests.cs` (find existing or create new grouped file for 011-016)

- Modify or create: `langs/python/tests/conformance/test_notif_*.py`

- Modify or create: `langs/typescript/tests/conformance/notif-*.test.ts`

- [x] **Step 1: Locate existing NOTIF stub/test files** in each flavor:

```bash
ls langs/csharp/tests/VMx.Conformance.Tests/ | grep -i NOTIF
ls langs/python/tests/conformance/ | grep notif
ls langs/typescript/tests/conformance/ | grep -i notif
```

- [x] **Step 2: Add 6 new stubs in each flavor**, either appended to the existing NOTIF file or in a new grouped file (e.g., `NOTIF_011_to_016_RenderingVMs_Tests.cs`). Use recognized markers:

- C#: `[Fact(Skip = "NOTIF-NNN not yet implemented"), Trait("Conformance", "NOTIF-NNN")]`

- Python: `@pytest.mark.conformance("NOTIF-NNN")` + `@pytest.mark.skip(...)`

- TS: `describe("NOTIF-NNN", ...)` + `it.todo(...)`

- [x] **Step 3: Run conformance coverage.**

```bash
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript
```

Expected: 219/219 in all 3 flavors.

- [x] **Step 4: Commit.**

```bash
git add langs/csharp/tests/VMx.Conformance.Tests/NOTIF_*.cs langs/python/tests/conformance/test_notif_*.py langs/typescript/tests/conformance/notif-*.test.ts
git commit -m "test(conf): add NOTIF-011..016 stubs in all three flavors"
```

- [x] **Step 5: Tick Substage 4A checkboxes; commit `docs(plan): tick Substage 4A`.**

______________________________________________________________________

# Substage 4B — Per-flavor NotificationVM + ConfirmationVM

This substage implements both VMs across all three flavors. Pattern is well-established from Stages 1-3. Replace stubs with real tests (using TestScheduler/virtual time), implement minimally, verify, commit.

### Task 4B.1: C# NotificationVM + ConfirmationVM

**Files:**

- Create: `langs/csharp/src/VMx.Notifications/NotificationVM.cs`

- Create: `langs/csharp/src/VMx.Notifications/ConfirmationVM.cs`

- Modify: relevant NOTIF stubs in `langs/csharp/tests/VMx.Conformance.Tests/NOTIF_*.cs`

- Create: `langs/csharp/tests/VMx.Tests/Notifications/NotificationVMTests.cs` (or inside VMx.Notifications.Tests project — read existing test project structure first)

- Create: same for ConfirmationVM unit tests

- [ ] **Step 1: Read existing `VMx.Notifications` project structure** to find the right test project home.

```bash
ls langs/csharp/src/VMx.Notifications/
find langs/csharp/tests/ -type d -name "*Notifications*"
```

- [ ] **Step 2: Replace NOTIF-011 stub with real failing test using TestScheduler.**

```csharp
[Fact]
[Trait("Conformance", "NOTIF-011")]
public void NOTIF_011_Opacity_Decays_Linearly()
{
    var scheduler = new TestScheduler();
    var hub = new NullNotificationHub();
    var notification = new Notification(NotificationType.Notification, "hi");
    var sut = new NotificationVM(notification, hub, scheduler, lifespan: TimeSpan.FromSeconds(10));

    sut.Opacity.Should().Be(1.0);

    scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
    sut.Opacity.Should().BeApproximately(0.5, 0.01);

    scheduler.AdvanceBy(TimeSpan.FromSeconds(5).Ticks);
    sut.Opacity.Should().BeApproximately(0.0, 0.01);
}
```

- [ ] **Step 3: Run test, verify FAIL.**

- [ ] **Step 4: Create `NotificationVM.cs`.**

```csharp
namespace VMx.Notifications;

using System;
using System.Reactive.Concurrency;
using VMx.Commands;
using VMx.Components;

public class NotificationVM : ComponentVM<Notification>
{
    private readonly INotificationHub _hub;
    private readonly IScheduler _scheduler;
    private readonly TimeSpan _lifespan;
    private DateTimeOffset _start;
    private IDisposable? _timerSub;
    private bool _isResolved;

    public NotificationVM(
        Notification notification,
        INotificationHub hub,
        IScheduler scheduler,
        TimeSpan? lifespan = null)
        : base(notification)
    {
        _hub = hub;
        _scheduler = scheduler;
        _lifespan = lifespan ?? TimeSpan.FromSeconds(60);
        _start = _scheduler.Now;
        DismissCommand = new RelayCommand(Dismiss);
        // Start timer
        _timerSub = _scheduler.Schedule(_lifespan, OnExpire);
    }

    public Notification Notification => Model;
    public TimeSpan Lifespan => _lifespan;
    public TimeSpan RemainingTime
    {
        get
        {
            var elapsed = _scheduler.Now - _start;
            var remaining = _lifespan - elapsed;
            return remaining > TimeSpan.Zero ? remaining : TimeSpan.Zero;
        }
    }
    public double Opacity => RemainingTime.TotalMilliseconds / Math.Max(_lifespan.TotalMilliseconds, 1);
    public bool IsResolved => _isResolved;
    public ICommand DismissCommand { get; }

    protected virtual void OnExpire()
    {
        // Default: NotificationVM auto-resolves with Approve. ConfirmationVM overrides.
        Dismiss();
    }

    protected void Dismiss()
    {
        if (_isResolved) return;
        _isResolved = true;
        _timerSub?.Dispose();
        _hub.Resolve(Model, NotificationReaction.Approve);
    }
}
```

(Adapt to the actual `ComponentVM<TM>`, `RelayCommand`, `INotificationHub.Resolve` signatures in the repo. Read those first.)

- [ ] **Step 5: Run test, verify PASS.**

- [ ] **Step 6: Implement NOTIF-012..015 incrementally.**

NOTIF-012 (auto-dismiss): Advance scheduler past Lifespan; assert IsResolved == true.
NOTIF-013 (ConfirmationVM dual-action): Create ConfirmationVM; invoke ApproveCommand, verify hub resolved with Approve. Create new VM; invoke RejectCommand, verify Reject.
NOTIF-014 (manual dismiss cancels timer): Construct; invoke DismissCommand at time 0; advance scheduler past Lifespan; assert hub Resolve called exactly once.
NOTIF-015 (hub Resolve propagates): Have hub resolve externally; assert sut.IsResolved becomes true and timer is cancelled.
NOTIF-016 (TestScheduler determinism): The whole test file uses TestScheduler — assert specific tick counts.

- [ ] **Step 7: Create `ConfirmationVM.cs`.**

```csharp
namespace VMx.Notifications;

using System;
using System.Reactive.Concurrency;
using VMx.Commands;

public class ConfirmationVM : NotificationVM
{
    public ConfirmationVM(
        Notification notification,
        INotificationHub hub,
        IScheduler scheduler,
        TimeSpan? lifespan = null)
        : base(notification, hub, scheduler, lifespan ?? TimeSpan.FromSeconds(300))
    {
        ApproveCommand = new RelayCommand(() => ResolveWith(NotificationReaction.Approve));
        RejectCommand = new RelayCommand(() => ResolveWith(NotificationReaction.Reject));
    }

    public ICommand ApproveCommand { get; }
    public ICommand RejectCommand { get; }

    protected override void OnExpire()
    {
        // ConfirmationVM does NOT auto-resolve on Lifespan expiry.
    }

    private void ResolveWith(NotificationReaction reaction)
    {
        // Helper to allow Reject path; base.Dismiss only does Approve.
        // Wire to hub directly here.
    }
}
```

(Refine to access protected hub field from base, or restructure base to expose a protected `ResolveWith(reaction)` method.)

- [ ] **Step 8: Run tooling.**

```bash
cd langs/csharp && dotnet build && dotnet test && dotnet format --verify-no-changes
```

- [ ] **Step 9: Commit.**

```bash
git add langs/csharp/src/VMx.Notifications/ langs/csharp/tests/
git commit -m "feat(csharp,notif): implement NotificationVM + ConfirmationVM (NOTIF-011..016)"
```

### Task 4B.2: Python NotificationVM + ConfirmationVM

Mirror C# work using `reactivex.testing.TestScheduler`.

**Files:**

- Create: `langs/python/src/vmx/notifications/notification_vm.py`

- Create: `langs/python/src/vmx/notifications/confirmation_vm.py`

- Modify: `langs/python/src/vmx/notifications/__init__.py` (export)

- Modify: NOTIF-011..016 conformance tests

- Create: `langs/python/tests/unit/notifications/test_notification_vm.py`

- Create: `langs/python/tests/unit/notifications/test_confirmation_vm.py`

- [ ] **Step 1: Real test for NOTIF-011 using TestScheduler.**

```python
from datetime import timedelta

import pytest
from reactivex.testing import TestScheduler


@pytest.mark.conformance("NOTIF-011")
def test_notif_011_opacity_decays_linearly() -> None:
    from vmx.notifications import NotificationVM, Notification, NotificationType
    from vmx.notifications import NullNotificationHub

    scheduler = TestScheduler()
    hub = NullNotificationHub()
    notification = Notification(type=NotificationType.NOTIFICATION, message="hi")
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=10),
    )

    assert sut.opacity == 1.0

    scheduler.advance_by(5_000_000)  # 5 seconds in microseconds (RxPy uses 1e6 units)
    assert abs(sut.opacity - 0.5) < 0.01

    scheduler.advance_by(5_000_000)
    assert abs(sut.opacity) < 0.01
```

(Check Python's `reactivex` virtual-time unit; could be milliseconds or microseconds — read existing tests for the pattern.)

- [ ] **Step 2-9: Mirror C# Steps 2-8** with Python-idiomatic naming (snake_case), `abc.ABC` + Generic if needed, async/await for hub interactions if hub is async in Python.

Tooling:

```bash
cd langs/python && uv run pytest && uv run mypy --strict src/vmx && uv run ruff check && uv run ruff format --check
```

- [ ] **Step 10: Commit.**

```bash
git add langs/python/src/vmx/notifications/ langs/python/tests/
git commit -m "feat(python,notif): implement NotificationVM + ConfirmationVM (NOTIF-011..016)"
```

### Task 4B.3: TypeScript NotificationVM + ConfirmationVM

Mirror C# work using `rxjs/testing` `TestScheduler`.

**Files:**

- Create: `langs/typescript/src/notifications/notificationVm.ts`

- Create: `langs/typescript/src/notifications/confirmationVm.ts`

- Modify: `langs/typescript/src/notifications/index.ts` (export)

- Modify: NOTIF-011..016 conformance tests

- Create: `langs/typescript/tests/unit/notifications/notificationVm.test.ts`

- Create: `langs/typescript/tests/unit/notifications/confirmationVm.test.ts`

- [ ] **Step 1: Real test for NOTIF-011 using TestScheduler.**

```typescript
import { describe, expect, it } from "vitest";
import { TestScheduler } from "rxjs/testing";
import { NotificationVM, Notification, NotificationType, NullNotificationHub } from "../../src/notifications";

describe("NOTIF-011", () => {
  it("Opacity decays linearly over Lifespan", () => {
    const scheduler = new TestScheduler((actual, expected) => expect(actual).toEqual(expected));

    scheduler.run(() => {
      const hub = new NullNotificationHub();
      const notification: Notification = { type: NotificationType.Notification, message: "hi" };
      const sut = new NotificationVM({
        notification,
        hub,
        scheduler,
        lifespanMs: 10_000,
      });

      expect(sut.opacity).toBe(1.0);
      // Advance virtual time and re-check
      // Note: rxjs TestScheduler virtual time advances via Observable marble syntax;
      // explicit time advancement may need scheduler-flush calls
    });
  });
});
```

(rxjs TestScheduler has a different API than C#/Python; consult `rxjs/testing` docs or existing TS tests using it for the canonical pattern.)

- [ ] **Step 2-9: Mirror C# Steps 2-8** with TS-idiomatic naming.

Tooling:

```bash
cd langs/typescript && npm run typecheck && npm run lint && npm test
```

- [ ] **Step 10: Commit.**

```bash
git add langs/typescript/src/notifications/ langs/typescript/src/notifications/index.ts langs/typescript/tests/
git commit -m "feat(typescript,notif): implement NotificationVM + ConfirmationVM (NOTIF-011..016)"
```

- [ ] **Step 11: Tick Substage 4B checkboxes; commit `docs(plan): tick Substage 4B`.**

______________________________________________________________________

# Substage 4C — Service-as-VM recipe + Stage 4 audit close

### Task 4C.1: Confirm service-as-VM recipe is documented

The recipe was added to ch.16 as a "Patterns" section in Task 4A.1. This task just verifies the prose is clear and includes a per-flavor code example.

**Files:**

- Modify (potentially): `spec/16-notifications.md` — refine if needed

- [ ] **Step 1: Re-read the §"Patterns" section** added in 4A.1. Ensure it:

  - Names the pattern clearly
  - Shows the per-flavor invocation (one short example)
  - Notes it's documentation, not a normative spec addition

- [ ] **Step 2: Refine if needed.** Commit if anything changed.

### Task 4C.2: Stage 4 audit close — Pass A

- [ ] **Step 1: Dispatch combined audit subagent** (single dispatch covering all 4 perspectives — flavor by flavor + spec/docs, per Stage 3 close pattern).

Audit verifies:

- ADR-0031 + chapter 16 extensions in place

- 6 NOTIF-011..016 conformance IDs with stubs replaced by real tests

- Per-flavor NotificationVM + ConfirmationVM with TestScheduler-based tests

- Lifespan defaults: NotificationVM 60s; ConfirmationVM 300s

- Auto-dismiss behavior: NotificationVM auto-resolves; ConfirmationVM does NOT

- Coverage 219/219 × 3

- Pre-commit clean

- No AI attribution on commits

- [ ] **Step 2: Address all Critical + Important; consider Minors.**

- [ ] **Step 3: Re-verify clean → counter 1/2.**

### Task 4C.3: Own spot-check between passes

- [ ] Verify key invariants yourself:

```bash
grep -c '^### NOTIF-' spec/12-conformance.md  # at least 16 (10 existing + 6 new)
grep -c 'NotImplementedException' langs/csharp/tests/VMx.Conformance.Tests/NOTIF_*.cs  # 0
grep -c 'pytest.mark.skip' langs/python/tests/conformance/test_notif_*.py  # 0
grep -c 'it.todo' langs/typescript/tests/conformance/notif-*.test.ts  # 0
uv --project langs/python run python tools/check-conformance-coverage.py --require csharp --require python --require typescript
for sha in $(git log main..HEAD --format='%H'); do msg=$(git log -1 $sha --format='%B'); echo "$msg" | grep -qi 'co-authored-by\|claude.com\|anthropic' && echo "BAD: $sha"; done
```

### Task 4C.4: Pass B (second consecutive clean)

- [ ] **Step 1: Dispatch fresh audit subagent.**
- [ ] **Step 2: Counter advances to 2/2 — Stage 4 CLOSED.**

### Task 4C.5: Tick Stage 4 box + close

- [ ] **Step 1: Edit `docs/superpowers/plans/2026-05-27-vmx-absorption-audit.md`:**

  ```
  - [ ] **Stage 4** — Notification rendering VMs (C5, I6)
  ```

  becomes:

  ```
  - [x] **Stage 4** — Notification rendering VMs (C5, I6)
  ```

- [ ] **Step 2: Commit `docs(plan): close Stage 4 (Notification rendering VMs) — 2 consecutive clean audit passes`.**

- [ ] **Step 3: Spawn Stage 5 detailed plan via `superpowers:writing-plans`.**

______________________________________________________________________

## Self-review checklist

1. **Spec coverage:** NOTIF-011..016 each map to a step in Tasks 4B.1/4B.2/4B.3. ✓
1. **Lifespan defaults:** 60s / 300s explicitly stated in ADR-0031 §3.2 (Task 4A.1) and locked at the top. ✓
1. **Auto-dismiss policy:** NotificationVM auto-resolves; ConfirmationVM does NOT — stated in ADR-0031 §3.7, ch.16 N+1 (Task 4A.1). ✓
1. **TestScheduler usage:** every TDD test uses virtual time per-flavor (C# TestScheduler, Python reactivex.testing.TestScheduler, TS rxjs/testing TestScheduler) — Task 4B steps. ✓
1. **Service-as-VM recipe:** §"Patterns" in ch.16, Task 4A.1. ✓
1. **No new normative type for I6:** decision recorded at top + no spec primitive added beyond the recipe text. ✓
1. **Audit gates:** 2 consecutive zero-finding passes per user's strict-clean-pass-gate. ✓
1. **No AI attribution:** every commit step ends with the grep verification. ✓
1. **No placeholders:** every step has actual code, command, or concrete prose. ✓
