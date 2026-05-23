# VMx Phase 2 — C# v1.0.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full C# flavor of VMx at `langs/csharp/`, satisfying `spec-v1.0.0` end-to-end and passing every one of the 68 conformance IDs. Tag `csharp-v1.0.0` when done.

**Architecture:** TDD per sub-module. Each module is a self-contained slice (Lifecycle, Messages, Services, Commands, Components, Composites, Groups, Aggregates, Forwarding) with its own unit tests plus contributions to the cross-language conformance suite. The library multi-targets `netstandard2.0` and `net8.0`. `System.Reactive` provides the hub and command triggers; `Microsoft.Reactive.Testing.TestScheduler` provides deterministic time in tests.

**Tech Stack:**

- **.NET SDK 9.0.x** (library multi-targets `netstandard2.0;net8.0`; test runner uses `net9.0` per Phase 0 deviation)
- **System.Reactive 6.0.1** (hot subject for the hub; observable command triggers)
- **xUnit 2.9.0** + **FluentAssertions 6.12.0** + **Microsoft.Reactive.Testing 6.0.1** for tests
- **C# 12+** with `Nullable`, `ImplicitUsings`, `record` types, `init`-only setters

**Spec reference:** `/Users/kaveh/repos/VMx/spec/` (especially `02-lifecycle.md` through `12-conformance.md`). Subagents MUST consult the relevant spec file for each module's normative behavior — this plan provides shape and test scaffolding, not the full semantic definition.

**Conformance fixtures:** `/Users/kaveh/repos/VMx/spec/fixtures/` — lifecycle-transitions.json (20 rows), message-ordering.json (4 scenarios), command-truthtable.json (5 rows). LIFE-011, HUB-006, and CMD-007 load these directly.

**Working directory for all relative paths:** `/Users/kaveh/repos/VMx`

______________________________________________________________________

## Commit-message convention (IMPORTANT)

**Every commit in this plan MUST NOT carry any `Co-Authored-By: Claude …` or other AI-attribution trailer.** The repo history was just deep-cleaned of these; do not reintroduce them. When you commit, use the message exactly as written in each task — no extra trailers.

If your harness automatically appends a Co-Authored-By line, override it. The commit message MUST end with the `Refs:` line (or whatever the task specifies), nothing after.

______________________________________________________________________

## Pre-flight

```bash
cd /Users/kaveh/repos/VMx
git checkout main
git pull --ff-only
git log --oneline -3
```

Expected: `main` at `2b6fd24 chore(editorconfig): …` or descendant; tag `spec-v1.0.0` present.

**Tools required:**

```bash
dotnet --version          # 9.x (Phase 0 deviation; library still targets netstandard2.0;net8.0)
git --version             # 2.30+
uv --version              # for conformance tool tests
pre-commit --version
```

**Branch:**

```bash
git checkout -b feat/phase-2-csharp-v1
```

______________________________________________________________________

## File structure produced by Phase 2

```
langs/csharp/
├── VMx.sln                                      MODIFIED (add VMx.Conformance.Tests project)
├── Directory.Build.props                        KEPT
├── Directory.Packages.props                     MODIFIED (already has all needed deps)
├── src/
│   └── VMx/
│       ├── VMx.csproj                           MODIFIED (no change to TFMs)
│       ├── Placeholder.cs                       DELETED (replaced by real types in 2a)
│       ├── Lifecycle/
│       │   ├── ConstructionStatus.cs            NEW
│       │   ├── StatusTransitionException.cs     NEW
│       │   └── LifecycleTransitionValidator.cs  NEW (internal; loads JSON fixture)
│       ├── Messages/
│       │   ├── IMessage.cs                      NEW
│       │   ├── IMessageOfT.cs                   NEW (IMessage<TSender>)
│       │   ├── IPropertyChangedMessage.cs       NEW
│       │   ├── IConstructionStatusChangedMessage.cs  NEW
│       │   ├── PropertyChangedMessage.cs        NEW (record struct)
│       │   └── ConstructionStatusChangedMessage.cs   NEW (record class)
│       ├── Services/
│       │   ├── IMessageHub.cs                   NEW
│       │   ├── MessageHub.cs                    NEW (Subject-backed)
│       │   ├── IDispatcher.cs                   NEW
│       │   └── RxDispatcher.cs                  NEW
│       ├── Commands/
│       │   ├── ICommandBuilder.cs               NEW (and ICommandBuilder<T>)
│       │   ├── RelayCommand.cs                  NEW
│       │   └── RelayCommandT.cs                 NEW (RelayCommand<T>)
│       ├── Components/
│       │   ├── ViewModelType.cs                 NEW (enum)
│       │   ├── IComponentVM.cs                  NEW
│       │   ├── IComponentVMOfM.cs               NEW (IComponentVM<M>)
│       │   ├── IReadonlyComponentVM.cs          NEW (IReadonlyComponentVM<M>)
│       │   ├── ComponentVMBase.cs               NEW (abstract; non-modeled base)
│       │   ├── ComponentVMBaseOfM.cs            NEW (abstract; modeled base)
│       │   ├── ComponentVM.cs                   NEW (sealed; ComponentVM<M>)
│       │   ├── ReadonlyComponentVM.cs           NEW (sealed; ReadonlyComponentVM<M>)
│       │   └── ComponentVMBuilder.cs            NEW (fluent immutable builder)
│       ├── Composites/
│       │   ├── ICompositeVM.cs                  NEW (ICompositeVM<VM>)
│       │   ├── ICompositeVMOfMVM.cs             NEW (ICompositeVM<M, VM>)
│       │   ├── CompositeVMBase.cs               NEW (abstract)
│       │   ├── CompositeVM.cs                   NEW (sealed; non-modeled)
│       │   ├── CompositeVMOfM.cs                NEW (sealed; modeled)
│       │   └── CompositeVMBuilder.cs            NEW
│       ├── Groups/
│       │   ├── IGroupVM.cs                      NEW
│       │   ├── GroupVMBase.cs                   NEW
│       │   ├── GroupVM.cs                       NEW
│       │   └── GroupVMBuilder.cs                NEW
│       ├── Aggregates/
│       │   ├── IAggregateVM1.cs ... IAggregateVM5.cs   NEW (5 files)
│       │   ├── AggregateVM1.cs ... AggregateVM5.cs     NEW (5 files)
│       │   └── AggregateVMBuilder.cs            NEW (one file, 5 nested types)
│       ├── Forwarding/
│       │   ├── ForwardingComponentVM.cs         NEW (abstract<M>)
│       │   └── ForwardingCompositeVM.cs         NEW (abstract<VM>)
│       └── Builders/
│           └── BuilderValidationException.cs    NEW
├── src/
│   └── VMx.Extensions.DependencyInjection/
│       ├── VMx.Extensions.DependencyInjection.csproj   NEW
│       └── ServiceCollectionExtensions.cs              NEW (AddVMx)
├── tests/
│   ├── VMx.Tests/                               MODIFIED (add module unit tests)
│   │   ├── VMx.Tests.csproj                     KEPT
│   │   ├── SmokeTests.cs                        DELETED (real tests replace it)
│   │   ├── Lifecycle/
│   │   │   ├── ConstructionStatusTests.cs       NEW
│   │   │   └── LifecycleTransitionValidatorTests.cs   NEW
│   │   ├── Messages/
│   │   │   └── MessageRecordTests.cs            NEW
│   │   ├── Services/
│   │   │   ├── MessageHubTests.cs               NEW
│   │   │   └── RxDispatcherTests.cs             NEW
│   │   ├── Commands/
│   │   │   └── RelayCommandTests.cs             NEW
│   │   ├── Components/
│   │   │   ├── ComponentVMTests.cs              NEW
│   │   │   └── ReadonlyComponentVMTests.cs      NEW
│   │   ├── Composites/
│   │   │   ├── CompositeVMTests.cs              NEW
│   │   │   └── ModeledCompositeVMTests.cs       NEW
│   │   ├── Groups/
│   │   │   └── GroupVMTests.cs                  NEW
│   │   ├── Aggregates/
│   │   │   └── AggregateVMTests.cs              NEW (covers all 5 arities)
│   │   ├── Forwarding/
│   │   │   └── ForwardingTests.cs               NEW
│   │   ├── Builders/
│   │   │   └── BuilderTests.cs                  NEW
│   │   └── Helpers/
│   │       ├── TestHub.cs                       NEW (in-memory hub for tests)
│   │       ├── TestDispatcher.cs                NEW (wraps Rx TestScheduler)
│   │       └── RecordedMessages.cs              NEW (subscriber harness)
│   └── VMx.Conformance.Tests/                   NEW (separate project)
│       ├── VMx.Conformance.Tests.csproj         NEW
│       ├── Fixtures/
│       │   └── FixtureLoader.cs                 NEW (reads JSON from spec/fixtures/)
│       ├── LifecycleConformanceTests.cs         NEW (LIFE-001..013)
│       ├── HubConformanceTests.cs               NEW (HUB-001..007)
│       ├── PropertyChangeConformanceTests.cs    NEW (PROP-001..004)
│       ├── CommandConformanceTests.cs           NEW (CMD-001..007)
│       ├── ComponentVMConformanceTests.cs       NEW (CVM-001..006)
│       ├── CompositeVMConformanceTests.cs       NEW (COMP-001..011)
│       ├── GroupVMConformanceTests.cs           NEW (GRP-001..004)
│       ├── AggregateVMConformanceTests.cs       NEW (AGG-001..005)
│       ├── ForwardingConformanceTests.cs        NEW (FWD-001..003)
│       ├── BuilderConformanceTests.cs           NEW (BLD-001..004)
│       └── ThreadingConformanceTests.cs         NEW (THR-001..004)
└── CHANGELOG.md                                 MODIFIED (add 1.0.0 entry)

docs/
├── getting-started/
│   └── csharp.md                                NEW

examples/csharp/
├── HelloVMx/
│   ├── HelloVMx.csproj                          NEW
│   └── Program.cs                               NEW
└── WpfTodoApp/
    ├── WpfTodoApp.csproj                        NEW
    └── (MVVM wiring)                            NEW

.github/workflows/
└── csharp.yml                                   MODIFIED (add VMx.Conformance.Tests build/test)
```

______________________________________________________________________

## Task organization principles

- **One task per module** (Lifecycle, Messages, Services, Commands, Components, etc.).
- **Each module task implements interfaces + concrete types + unit tests + conformance tests in a single coherent slice.**
- **TDD ordering inside each task:** write conformance test first (RED), implement unit-test-driven (RED→GREEN), implement enough source code to satisfy both, refactor.
- **Each task ends with one commit** (occasionally two if logically distinct). Each task is self-contained and verifiable independently.
- **Verification after each task**: `dotnet build` + `dotnet test` + `dotnet format --verify-no-changes` + pre-commit all green.

______________________________________________________________________

## Task 1 — Bootstrap: delete placeholder, create test helpers, add Conformance project

**Files:**

- Delete: `langs/csharp/src/VMx/Placeholder.cs`
- Delete: `langs/csharp/tests/VMx.Tests/SmokeTests.cs`
- Create: `langs/csharp/tests/VMx.Tests/Helpers/TestHub.cs`
- Create: `langs/csharp/tests/VMx.Tests/Helpers/TestDispatcher.cs`
- Create: `langs/csharp/tests/VMx.Tests/Helpers/RecordedMessages.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/Fixtures/FixtureLoader.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/_BootstrapTest.cs` (placeholder so the project builds with at least one test)
- Modify: `langs/csharp/VMx.sln` (add the new test project)

### Step 1.1: Delete placeholder source

```bash
cd /Users/kaveh/repos/VMx
rm langs/csharp/src/VMx/Placeholder.cs
rm langs/csharp/tests/VMx.Tests/SmokeTests.cs
```

### Step 1.2: Create test helpers

`langs/csharp/tests/VMx.Tests/Helpers/TestHub.cs`:

```csharp
using System.Reactive.Subjects;
using VMx.Messages;
using VMx.Services;

namespace VMx.Tests.Helpers;

/// <summary>
/// In-process IMessageHub for tests. Backed by a Subject so subscribers
/// can use Rx operators (Where, ObserveOn, etc.) directly.
/// </summary>
public sealed class TestHub : IMessageHub, IDisposable
{
    private readonly Subject<IMessage> _subject = new();

    public IObservable<IMessage> Messages => _subject;

    public void Send<TMessage>(TMessage message) where TMessage : IMessage
        => _subject.OnNext(message);

    public void Dispose() => _subject.Dispose();
}
```

`langs/csharp/tests/VMx.Tests/Helpers/TestDispatcher.cs`:

```csharp
using System.Reactive.Concurrency;
using Microsoft.Reactive.Testing;
using VMx.Services;

namespace VMx.Tests.Helpers;

/// <summary>
/// IDispatcher backed by deterministic Rx TestSchedulers so tests can
/// advance virtual time precisely. Foreground and Background each get
/// their own scheduler so cross-scheduler dispatch is observable.
/// </summary>
public sealed class TestDispatcher : IDispatcher
{
    public TestScheduler ForegroundScheduler { get; } = new();
    public TestScheduler BackgroundScheduler { get; } = new();

    public IScheduler Foreground => ForegroundScheduler;
    public IScheduler Background => BackgroundScheduler;

    public void AdvanceAll(long ticks = 1)
    {
        ForegroundScheduler.AdvanceBy(ticks);
        BackgroundScheduler.AdvanceBy(ticks);
    }
}
```

`langs/csharp/tests/VMx.Tests/Helpers/RecordedMessages.cs`:

```csharp
using System.Reactive.Linq;
using VMx.Messages;

namespace VMx.Tests.Helpers;

/// <summary>
/// Subscribes to an IObservable&lt;IMessage&gt; and records everything
/// observed. Test code asserts against <see cref="Items"/>.
/// </summary>
public sealed class RecordedMessages<TMessage> : IDisposable where TMessage : IMessage
{
    private readonly IDisposable _subscription;

    public List<TMessage> Items { get; } = new();

    public RecordedMessages(IObservable<IMessage> source)
    {
        _subscription = source.OfType<TMessage>().Subscribe(Items.Add);
    }

    public void Dispose() => _subscription.Dispose();
}
```

### Step 1.3: Create VMx.Conformance.Tests project

`langs/csharp/tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <!--
      Test runner targets net9.0 (not the library's lowest TFM net8.0) because the
      dev environment only has the .NET 9 SDK/runtime installed. The library
      `VMx.csproj` itself remains multi-targeted `netstandard2.0;net8.0`.
    -->
    <TargetFramework>net9.0</TargetFramework>
    <IsPackable>false</IsPackable>
    <IsTestProject>true</IsTestProject>
    <!-- Tests don't ship as a package; relax doc/naming rules. -->
    <NoWarn>$(NoWarn);CS1591;CA1707</NoWarn>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" />
    <PackageReference Include="xunit" />
    <PackageReference Include="xunit.runner.visualstudio" />
    <PackageReference Include="FluentAssertions" />
    <PackageReference Include="Microsoft.Reactive.Testing" />
    <PackageReference Include="coverlet.collector" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\src\VMx\VMx.csproj" />
    <ProjectReference Include="..\VMx.Tests\VMx.Tests.csproj" />
  </ItemGroup>

  <ItemGroup>
    <!-- Make the JSON fixtures available to tests via relative path from bin/. -->
    <None Include="..\..\..\..\spec\fixtures\*.json" Link="Fixtures\%(Filename)%(Extension)">
      <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
    </None>
  </ItemGroup>
</Project>
```

`langs/csharp/tests/VMx.Conformance.Tests/Fixtures/FixtureLoader.cs`:

```csharp
using System.Text.Json;
using System.Text.Json.Serialization;

namespace VMx.Conformance.Tests.Fixtures;

/// <summary>
/// Loads the JSON fixtures from spec/fixtures/. The fixture files are copied
/// into the test bin/ directory via the csproj's <None Include="..."> block.
/// </summary>
public static class FixtureLoader
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    public static T Load<T>(string fixtureFileName)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", fixtureFileName);
        if (!File.Exists(path))
            throw new FileNotFoundException($"Fixture not found at {path}", path);
        var json = File.ReadAllText(path);
        return JsonSerializer.Deserialize<T>(json, Options)!;
    }
}
```

`langs/csharp/tests/VMx.Conformance.Tests/_BootstrapTest.cs` (placeholder so the project builds; deleted once real conformance tests land):

```csharp
using FluentAssertions;
using VMx.Conformance.Tests.Fixtures;
using Xunit;

namespace VMx.Conformance.Tests;

public class _BootstrapTest
{
    [Fact]
    public void FixturesAreAvailable()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "lifecycle-transitions.json");
        File.Exists(path).Should().BeTrue($"fixture should be copied to {path}");
    }
}
```

### Step 1.4: Add Conformance project to solution

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet sln VMx.sln add tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj
dotnet sln VMx.sln list
```

Expected output includes all three projects: `src/VMx/VMx.csproj`, `tests/VMx.Tests/VMx.Tests.csproj`, `tests/VMx.Conformance.Tests/VMx.Conformance.Tests.csproj`.

### Step 1.5: Build + test

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet restore VMx.sln
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build
```

Expected: build succeeds, 1 conformance test passes (`FixturesAreAvailable`), 0 VMx.Tests tests (we deleted SmokeTests; that's fine — modules will add tests). The library project should still compile despite Placeholder.cs being gone — until module code is added, `VMx.dll` is empty (no public types). That's acceptable for Phase 2's first task.

If the empty library fails to compile because `GenerateDocumentationFile` requires public types, add a sentinel internal class to `VMx.csproj` directory:

`langs/csharp/src/VMx/AssemblyInfo.cs`:

```csharp
// Empty file kept so MSBuild has source to compile during bootstrap.
// Removed in Task 2 once Lifecycle/ConstructionStatus.cs adds real public types.
internal static class _AssemblyBootstrap { }
```

### Step 1.6: Commit

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/src/VMx/Placeholder.cs langs/csharp/src/VMx/AssemblyInfo.cs \
        langs/csharp/tests/VMx.Tests/SmokeTests.cs \
        langs/csharp/tests/VMx.Tests/Helpers/ \
        langs/csharp/tests/VMx.Conformance.Tests/ \
        langs/csharp/VMx.sln
git commit -m "build(csharp): bootstrap Phase 2 — delete placeholder, add Conformance project and test helpers

- delete Placeholder.cs and SmokeTests.cs (Phase 0 scaffolding)
- add tests/VMx.Tests/Helpers/{TestHub, TestDispatcher, RecordedMessages}
  shared utilities for all module unit tests
- add tests/VMx.Conformance.Tests project that references both VMx and VMx.Tests,
  copies spec/fixtures/*.json into its bin/ via <None Include>, and provides
  FixtureLoader to deserialize them
- add internal _AssemblyBootstrap sentinel so VMx.dll compiles with the library
  empty (removed in Task 2 once Lifecycle types land)

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.2"
```

______________________________________________________________________

## Task 2 — Lifecycle (2a): ConstructionStatus + StatusTransitionException + validator + LIFE-001..013

**Spec references:** `spec/02-lifecycle.md`, `spec/fixtures/lifecycle-transitions.json`, `spec/12-conformance.md` (LIFE-001..013).

**Files:**

- Delete: `langs/csharp/src/VMx/AssemblyInfo.cs` (sentinel removed)
- Create: `langs/csharp/src/VMx/Lifecycle/ConstructionStatus.cs`
- Create: `langs/csharp/src/VMx/Lifecycle/StatusTransitionException.cs`
- Create: `langs/csharp/src/VMx/Lifecycle/LifecycleTransitionValidator.cs`
- Create: `langs/csharp/tests/VMx.Tests/Lifecycle/ConstructionStatusTests.cs`
- Create: `langs/csharp/tests/VMx.Tests/Lifecycle/LifecycleTransitionValidatorTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/LifecycleConformanceTests.cs`

### Step 2.1: Delete bootstrap sentinel

```bash
rm langs/csharp/src/VMx/AssemblyInfo.cs
```

### Step 2.2: Implement `ConstructionStatus`

`langs/csharp/src/VMx/Lifecycle/ConstructionStatus.cs`:

```csharp
namespace VMx.Lifecycle;

/// <summary>
/// The five states of a VMx viewmodel's lifecycle state machine.
/// See spec/02-lifecycle.md for the full transition contract.
/// </summary>
public enum ConstructionStatus
{
    /// <summary>Terminal state. Once entered, cannot leave.</summary>
    Disposed = 0,

    /// <summary>Transient state during destruct().</summary>
    Destructing = 1,

    /// <summary>Initial state of a freshly built VM.</summary>
    Destructed = 2,

    /// <summary>Transient state during construct().</summary>
    Constructing = 3,

    /// <summary>Ready-to-use state.</summary>
    Constructed = 4,
}
```

### Step 2.3: Implement `StatusTransitionException`

`langs/csharp/src/VMx/Lifecycle/StatusTransitionException.cs`:

```csharp
namespace VMx.Lifecycle;

/// <summary>
/// Thrown when a lifecycle operation is invoked on a VM whose current
/// <see cref="ConstructionStatus"/> forbids that operation.
/// See spec/02-lifecycle.md §Invariants 3 and 5.
/// </summary>
public sealed class StatusTransitionException : InvalidOperationException
{
    public ConstructionStatus CurrentStatus { get; }
    public string AttemptedOperation { get; }

    public StatusTransitionException(ConstructionStatus currentStatus, string attemptedOperation)
        : base($"Cannot {attemptedOperation} from state {currentStatus}.")
    {
        CurrentStatus = currentStatus;
        AttemptedOperation = attemptedOperation;
    }
}
```

### Step 2.4: Implement `LifecycleTransitionValidator`

This consumes `spec/fixtures/lifecycle-transitions.json` so the runtime validation matches the conformance fixture.

`langs/csharp/src/VMx/Lifecycle/LifecycleTransitionValidator.cs`:

```csharp
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace VMx.Lifecycle;

/// <summary>
/// Validates lifecycle operation invocations against the transition matrix
/// declared in spec/fixtures/lifecycle-transitions.json. The fixture is
/// embedded into the assembly so end users do not need a runtime file.
/// </summary>
public static class LifecycleTransitionValidator
{
    private const string EmbeddedResourceName = "VMx.Lifecycle.lifecycle-transitions.json";

    private static readonly Lazy<TransitionTable> Table = new(LoadTable);

    /// <summary>
    /// Throws <see cref="StatusTransitionException"/> if the operation is
    /// illegal from the current state. No-op for legal operations.
    /// </summary>
    public static void Require(ConstructionStatus current, string operation)
    {
        if (!IsLegal(current, operation))
            throw new StatusTransitionException(current, operation);
    }

    public static bool IsLegal(ConstructionStatus current, string operation)
    {
        var row = Table.Value.Find(current, operation);
        return row?.Legal ?? false;
    }

    public static ConstructionStatus FinalState(ConstructionStatus current, string operation)
    {
        var row = Table.Value.Find(current, operation)
                  ?? throw new StatusTransitionException(current, operation);
        if (!row.Legal || row.ToFinal is null)
            throw new StatusTransitionException(current, operation);
        return ParseStatus(row.ToFinal);
    }

    private static TransitionTable LoadTable()
    {
        var assembly = typeof(LifecycleTransitionValidator).Assembly;
        using var stream = assembly.GetManifestResourceStream(EmbeddedResourceName)
            ?? throw new InvalidOperationException(
                $"Embedded resource not found: {EmbeddedResourceName}. " +
                "Ensure spec/fixtures/lifecycle-transitions.json is embedded via the csproj.");
        return JsonSerializer.Deserialize<TransitionTable>(stream, Options)!;
    }

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    private static ConstructionStatus ParseStatus(string name) =>
        Enum.Parse<ConstructionStatus>(name, ignoreCase: false);

    private sealed class TransitionTable
    {
        [JsonPropertyName("transitions")]
        public List<Row> Transitions { get; init; } = new();

        public Row? Find(ConstructionStatus from, string operation) =>
            Transitions.FirstOrDefault(r =>
                string.Equals(r.From, from.ToString(), StringComparison.Ordinal) &&
                string.Equals(r.Via, operation, StringComparison.Ordinal));
    }

    private sealed class Row
    {
        public string From { get; init; } = "";
        public string Via { get; init; } = "";
        public string? ToIntermediate { get; init; }
        public string? ToFinal { get; init; }
        public bool Legal { get; init; }
    }
}
```

To embed the fixture, update `langs/csharp/src/VMx/VMx.csproj`. Find the `<ItemGroup>` containing `AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute"` and add a sibling `<ItemGroup>`:

```xml
  <ItemGroup>
    <!-- Embed spec/fixtures/lifecycle-transitions.json so the validator has it at runtime. -->
    <EmbeddedResource Include="..\..\..\..\spec\fixtures\lifecycle-transitions.json"
                     LogicalName="VMx.Lifecycle.lifecycle-transitions.json" />
  </ItemGroup>
```

### Step 2.5: Unit tests

`langs/csharp/tests/VMx.Tests/Lifecycle/ConstructionStatusTests.cs`:

```csharp
using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Tests.Lifecycle;

public class ConstructionStatusTests
{
    [Fact]
    public void Has_Five_States()
    {
        Enum.GetValues<ConstructionStatus>().Should().HaveCount(5)
            .And.Contain([
                ConstructionStatus.Disposed,
                ConstructionStatus.Destructing,
                ConstructionStatus.Destructed,
                ConstructionStatus.Constructing,
                ConstructionStatus.Constructed,
            ]);
    }

    [Fact]
    public void Disposed_Is_Terminal_Numeric_Zero()
    {
        ((int)ConstructionStatus.Disposed).Should().Be(0,
            "spec/02-lifecycle.md treats Disposed as the terminal state");
    }
}
```

`langs/csharp/tests/VMx.Tests/Lifecycle/LifecycleTransitionValidatorTests.cs`:

```csharp
using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Tests.Lifecycle;

public class LifecycleTransitionValidatorTests
{
    [Theory]
    [InlineData(ConstructionStatus.Destructed, "construct", true)]
    [InlineData(ConstructionStatus.Constructed, "destruct", true)]
    [InlineData(ConstructionStatus.Constructed, "reconstruct", true)]
    [InlineData(ConstructionStatus.Disposed, "construct", false)]
    [InlineData(ConstructionStatus.Disposed, "destruct", false)]
    [InlineData(ConstructionStatus.Disposed, "reconstruct", false)]
    [InlineData(ConstructionStatus.Constructing, "construct", false)]
    [InlineData(ConstructionStatus.Destructing, "destruct", false)]
    public void IsLegal_Matches_Fixture(ConstructionStatus from, string op, bool expected)
    {
        LifecycleTransitionValidator.IsLegal(from, op).Should().Be(expected);
    }

    [Fact]
    public void Require_Throws_With_State_And_Operation_In_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "construct"));
        ex.CurrentStatus.Should().Be(ConstructionStatus.Disposed);
        ex.AttemptedOperation.Should().Be("construct");
        ex.Message.Should().Contain("Disposed").And.Contain("construct");
    }

    [Fact]
    public void FinalState_Returns_Expected_Status_For_Legal_Transitions()
    {
        LifecycleTransitionValidator.FinalState(ConstructionStatus.Destructed, "construct")
            .Should().Be(ConstructionStatus.Constructed);
        LifecycleTransitionValidator.FinalState(ConstructionStatus.Constructed, "destruct")
            .Should().Be(ConstructionStatus.Destructed);
    }
}
```

### Step 2.6: Conformance tests for LIFE-001..013

`langs/csharp/tests/VMx.Conformance.Tests/LifecycleConformanceTests.cs`:

```csharp
using FluentAssertions;
using VMx.Lifecycle;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// LIFE-001 through LIFE-013 — see spec/12-conformance.md.
///
/// The component-VM lifecycle tests that exercise actual VM instances live in
/// ComponentVMConformanceTests; the LIFE-* tests here exercise the static
/// transition contract directly (state machine, exception type/message, fixture
/// table). Where a LIFE-* test depends on an actual VM instance (e.g., emit-zero-
/// messages from Disposed), the test re-runs against a freshly-built ComponentVM
/// to verify the integration.
/// </summary>
public class LifecycleConformanceTests
{
    // LIFE-005 — construct from Disposed raises (message must mention state + op).
    [Fact, Trait("Conformance", "LIFE-005")]
    public void LIFE_005_Construct_From_Disposed_Raises_With_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "construct"));
        ex.Message.Should().Contain("Disposed").And.Contain("construct");
    }

    // LIFE-006 — destruct from Disposed raises (parity with LIFE-005).
    [Fact, Trait("Conformance", "LIFE-006")]
    public void LIFE_006_Destruct_From_Disposed_Raises_With_Message()
    {
        var ex = Assert.Throws<StatusTransitionException>(
            () => LifecycleTransitionValidator.Require(ConstructionStatus.Disposed, "destruct"));
        ex.Message.Should().Contain("Disposed").And.Contain("destruct");
    }

    // LIFE-011 — every row in the fixture exercised against the static validator.
    [Fact, Trait("Conformance", "LIFE-011")]
    public void LIFE_011_Validator_Matches_Fixture_Table()
    {
        // For each row in the fixture, verify the validator's IsLegal matches.
        // The validator already loads the same fixture as its source-of-truth,
        // so this test guards against future divergence (e.g., someone hand-codes
        // a transition that disagrees with the fixture).
        foreach (var (from, op, expectedLegal) in EnumerateFixtureRows())
        {
            LifecycleTransitionValidator.IsLegal(from, op).Should().Be(expectedLegal,
                $"row {from}/{op} should have legal={expectedLegal}");
        }
    }

    private static IEnumerable<(ConstructionStatus from, string op, bool legal)> EnumerateFixtureRows()
    {
        var table = Fixtures.FixtureLoader.Load<FixtureRoot>("lifecycle-transitions.json");
        foreach (var row in table.Transitions)
        {
            var from = Enum.Parse<ConstructionStatus>(row.From, ignoreCase: false);
            yield return (from, row.Via, row.Legal);
        }
    }

    // LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 — these all require an
    // actual VM instance. Their assertions live in ComponentVMConformanceTests
    // and (for LIFE-013 disposal cascade) CompositeVMConformanceTests. We
    // declare placeholder [Fact, Trait] entries here that delegate, so the
    // catalog coverage tool sees each ID present in the C# conformance project.

    [Fact, Trait("Conformance", "LIFE-001")]
    public void LIFE_001_Construct_Transitions_Through_Constructing_To_Constructed()
        => new ComponentVMConformanceTests().CVM_001_Construct_Emits_Status_Messages();

    [Fact, Trait("Conformance", "LIFE-002")]
    public void LIFE_002_Destruct_Transitions_Through_Destructing_To_Destructed()
        => new ComponentVMConformanceTests().LIFE_002_Destruct_Transitions();

    [Fact, Trait("Conformance", "LIFE-003")]
    public void LIFE_003_Reconstruct_Emits_Full_Sequence()
        => new ComponentVMConformanceTests().LIFE_003_Reconstruct();

    [Fact, Trait("Conformance", "LIFE-004")]
    public void LIFE_004_Dispose_Transitions_From_Any_State()
        => new ComponentVMConformanceTests().LIFE_004_Dispose_From_Any_State();

    [Fact, Trait("Conformance", "LIFE-007")]
    public void LIFE_007_IsConstructed_Equals_Status_Constructed()
        => new ComponentVMConformanceTests().LIFE_007_IsConstructed_Invariant();

    [Fact, Trait("Conformance", "LIFE-008")]
    public void LIFE_008_Concurrent_Operation_While_Transitioning_Raises()
        => new ComponentVMConformanceTests().LIFE_008_Concurrent_Operation_Raises();

    [Fact, Trait("Conformance", "LIFE-009")]
    public void LIFE_009_Construct_From_Constructed_Is_Idempotent()
        => new ComponentVMConformanceTests().LIFE_009_Idempotent_Construct();

    [Fact, Trait("Conformance", "LIFE-010")]
    public void LIFE_010_Destruct_From_Destructed_Is_Idempotent()
        => new ComponentVMConformanceTests().LIFE_010_Idempotent_Destruct();

    [Fact, Trait("Conformance", "LIFE-012")]
    public void LIFE_012_Dispose_From_Disposed_Emits_No_Message()
        => new ComponentVMConformanceTests().LIFE_012_Dispose_From_Disposed_Silent();

    [Fact, Trait("Conformance", "LIFE-013")]
    public void LIFE_013_Dispose_Cascade_Depth_First()
        => new CompositeVMConformanceTests().LIFE_013_Dispose_Cascade();

    private sealed class FixtureRoot
    {
        public List<FixtureRow> Transitions { get; init; } = new();
    }

    private sealed class FixtureRow
    {
        public string From { get; init; } = "";
        public string Via { get; init; } = "";
        public bool Legal { get; init; }
    }
}
```

Note: `ComponentVMConformanceTests` and `CompositeVMConformanceTests` don't exist yet — they're populated in later tasks. To make this file compile NOW, add stubs (`langs/csharp/tests/VMx.Conformance.Tests/_StubClasses.cs`):

```csharp
namespace VMx.Conformance.Tests;

// These stubs are filled in by later tasks (Task 6 for ComponentVMConformanceTests,
// Task 7 for CompositeVMConformanceTests). They exist now only so LIFE-NNN
// delegation compiles. The class names + method names below are the contract
// that the later tasks MUST honor.

internal sealed class ComponentVMConformanceTests
{
    public void CVM_001_Construct_Emits_Status_Messages() => throw new NotImplementedException("Task 6");
    public void LIFE_002_Destruct_Transitions() => throw new NotImplementedException("Task 6");
    public void LIFE_003_Reconstruct() => throw new NotImplementedException("Task 6");
    public void LIFE_004_Dispose_From_Any_State() => throw new NotImplementedException("Task 6");
    public void LIFE_007_IsConstructed_Invariant() => throw new NotImplementedException("Task 6");
    public void LIFE_008_Concurrent_Operation_Raises() => throw new NotImplementedException("Task 6");
    public void LIFE_009_Idempotent_Construct() => throw new NotImplementedException("Task 6");
    public void LIFE_010_Idempotent_Destruct() => throw new NotImplementedException("Task 6");
    public void LIFE_012_Dispose_From_Disposed_Silent() => throw new NotImplementedException("Task 6");
}

internal sealed class CompositeVMConformanceTests
{
    public void LIFE_013_Dispose_Cascade() => throw new NotImplementedException("Task 7");
}
```

When Task 6 / Task 7 land, they delete `_StubClasses.cs` and replace the `internal sealed class` declarations with `public class`. Until then, the LIFE-001..LIFE-010 conformance tests will RAISE `NotImplementedException` — which is correct (they're skipped/failed pending Tasks 6/7). The LIFE-005, LIFE-006, LIFE-011 tests pass because they don't depend on a VM instance.

### Step 2.7: Build + test + verify trait scraping

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Conformance"
```

Expected: build passes, 3 conformance tests pass (LIFE-005, LIFE-006, LIFE-011), 10 conformance tests fail (LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 — all delegate to stubs).

Verify the coverage tool picks up the new IDs:

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run python tools/check-conformance-coverage.py
```

Expected: `csharp: 13/68 covered` (13 = the LIFE-001..013 set).

### Step 2.8: Commit

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/src/VMx/Lifecycle/ \
        langs/csharp/src/VMx/VMx.csproj \
        langs/csharp/tests/VMx.Tests/Lifecycle/ \
        langs/csharp/tests/VMx.Conformance.Tests/LifecycleConformanceTests.cs \
        langs/csharp/tests/VMx.Conformance.Tests/_StubClasses.cs
git rm langs/csharp/src/VMx/AssemblyInfo.cs
git commit -m "feat(csharp): Lifecycle module (2a) — ConstructionStatus, StatusTransitionException, transition validator

- Lifecycle/ConstructionStatus: 5-state enum (Disposed=0, ..., Constructed=4)
- Lifecycle/StatusTransitionException: thrown on illegal transitions; carries
  CurrentStatus and AttemptedOperation; message contains both
- Lifecycle/LifecycleTransitionValidator: loads spec/fixtures/lifecycle-transitions.json
  as an embedded resource; exposes IsLegal/Require/FinalState. Single source of truth
  shared with the JSON test fixture, so conformance LIFE-011 trivially holds.

Unit tests cover the state-machine enum and the validator. Conformance tests
register LIFE-005, LIFE-006, LIFE-011 directly here; LIFE-001..004, LIFE-007..010,
LIFE-012 delegate to ComponentVMConformanceTests (Task 6); LIFE-013 delegates to
CompositeVMConformanceTests (Task 7). The _StubClasses.cs file holds internal
placeholders for those delegates until Tasks 6 and 7 replace them.

Refs: spec/02-lifecycle.md, spec/fixtures/lifecycle-transitions.json"
```

______________________________________________________________________

## Task 3 — Messages (2b first half): IMessage hierarchy + concrete records + PROP-001..004

**Spec references:** `spec/03-messages.md`, `spec/12-conformance.md` (PROP-001..004 — note these are tested in Task 6 against actual VMs; this task only verifies the record types' shape and equality).

**Files:**

- Create: `langs/csharp/src/VMx/Messages/IMessage.cs`
- Create: `langs/csharp/src/VMx/Messages/IMessageOfT.cs`
- Create: `langs/csharp/src/VMx/Messages/IPropertyChangedMessage.cs`
- Create: `langs/csharp/src/VMx/Messages/IConstructionStatusChangedMessage.cs`
- Create: `langs/csharp/src/VMx/Messages/PropertyChangedMessage.cs`
- Create: `langs/csharp/src/VMx/Messages/ConstructionStatusChangedMessage.cs`
- Create: `langs/csharp/tests/VMx.Tests/Messages/MessageRecordTests.cs`

### Step 3.1: Interface hierarchy

`langs/csharp/src/VMx/Messages/IMessage.cs`:

```csharp
namespace VMx.Messages;

/// <summary>
/// Base contract for every message sent through the VMx hub.
/// See spec/03-messages.md §IMessage shape.
/// </summary>
public interface IMessage
{
    /// <summary>Human-readable sender identifier, typically equal to Sender.Name.</summary>
    string SenderName { get; }

    /// <summary>Runtime sender instance without compile-time type info.</summary>
    object SenderObject { get; }
}
```

`langs/csharp/src/VMx/Messages/IMessageOfT.cs`:

```csharp
namespace VMx.Messages;

/// <summary>
/// Strongly-typed sender variant of <see cref="IMessage"/>.
/// </summary>
public interface IMessage<out TSender> : IMessage
{
    TSender Sender { get; }
}
```

`langs/csharp/src/VMx/Messages/IPropertyChangedMessage.cs`:

```csharp
namespace VMx.Messages;

/// <summary>
/// Emitted by a VM when a property's setter accepts a value different from the
/// existing one. See spec/03-messages.md §PropertyChangedMessage.
/// </summary>
public interface IPropertyChangedMessage<out TSender> : IMessage<TSender>
{
    string PropertyName { get; }
}
```

`langs/csharp/src/VMx/Messages/IConstructionStatusChangedMessage.cs`:

```csharp
using VMx.Lifecycle;

namespace VMx.Messages;

/// <summary>
/// Emitted on every legal ConstructionStatus transition.
/// See spec/03-messages.md §ConstructionStatusChangedMessage and spec/02-lifecycle.md.
/// </summary>
public interface IConstructionStatusChangedMessage : IMessage
{
    ConstructionStatus Status { get; }
}
```

### Step 3.2: Concrete records

`langs/csharp/src/VMx/Messages/PropertyChangedMessage.cs`:

```csharp
namespace VMx.Messages;

/// <summary>
/// Default <see cref="IPropertyChangedMessage{TSender}"/> implementation.
/// Records give us value-equality and an auto-generated ToString().
/// </summary>
public sealed record PropertyChangedMessage<TSender>(
    TSender Sender,
    string SenderName,
    string PropertyName) : IPropertyChangedMessage<TSender>
    where TSender : notnull
{
    public object SenderObject => Sender!;

    public static PropertyChangedMessage<TSender> Create(
        TSender sender, string senderName, string propertyName)
        => new(sender, senderName, propertyName);
}
```

`langs/csharp/src/VMx/Messages/ConstructionStatusChangedMessage.cs`:

```csharp
using VMx.Lifecycle;

namespace VMx.Messages;

public sealed record ConstructionStatusChangedMessage(
    object Sender,
    string SenderName,
    ConstructionStatus Status) : IConstructionStatusChangedMessage
{
    public object SenderObject => Sender;

    public static ConstructionStatusChangedMessage Create(
        object sender, string senderName, ConstructionStatus status)
        => new(sender, senderName, status);
}
```

### Step 3.3: Unit tests

`langs/csharp/tests/VMx.Tests/Messages/MessageRecordTests.cs`:

```csharp
using FluentAssertions;
using VMx.Lifecycle;
using VMx.Messages;
using Xunit;

namespace VMx.Tests.Messages;

public class MessageRecordTests
{
    [Fact]
    public void PropertyChangedMessage_Create_Sets_All_Fields()
    {
        var sender = new object();
        var msg = PropertyChangedMessage<object>.Create(sender, "name", "Model");
        msg.Sender.Should().BeSameAs(sender);
        msg.SenderName.Should().Be("name");
        msg.PropertyName.Should().Be("Model");
        msg.SenderObject.Should().BeSameAs(sender);
    }

    [Fact]
    public void PropertyChangedMessage_Equal_When_Same_Values()
    {
        var sender = new object();
        var a = PropertyChangedMessage<object>.Create(sender, "x", "P");
        var b = PropertyChangedMessage<object>.Create(sender, "x", "P");
        a.Should().Be(b, "records have value equality");
    }

    [Fact]
    public void ConstructionStatusChangedMessage_Create_Sets_All_Fields()
    {
        var sender = new object();
        var msg = ConstructionStatusChangedMessage.Create(sender, "vm1", ConstructionStatus.Constructed);
        msg.Sender.Should().BeSameAs(sender);
        msg.SenderName.Should().Be("vm1");
        msg.Status.Should().Be(ConstructionStatus.Constructed);
        msg.SenderObject.Should().BeSameAs(sender);
    }
}
```

PROP-001..004 conformance tests are in a future task (Task 6) because they require an actual VM. Add delegates here:

`langs/csharp/tests/VMx.Conformance.Tests/PropertyChangeConformanceTests.cs`:

```csharp
using Xunit;

namespace VMx.Conformance.Tests;

public class PropertyChangeConformanceTests
{
    [Fact, Trait("Conformance", "PROP-001")]
    public void PROP_001_Setter_Different_Value_Publishes()
        => new ComponentVMConformanceTests().PROP_001_Setter_Publishes();

    [Fact, Trait("Conformance", "PROP-002")]
    public void PROP_002_Setter_Same_Value_Does_Not_Publish()
        => new ComponentVMConformanceTests().PROP_002_Setter_Same_Value_Silent();

    [Fact, Trait("Conformance", "PROP-003")]
    public void PROP_003_Sender_Identity_Equals_VM()
        => new ComponentVMConformanceTests().PROP_003_Sender_Identity();

    [Fact, Trait("Conformance", "PROP-004")]
    public void PROP_004_PropertyName_And_SenderName()
        => new ComponentVMConformanceTests().PROP_004_PropertyName_SenderName();
}
```

Extend `_StubClasses.cs`'s `ComponentVMConformanceTests` to include these four methods (each throws `NotImplementedException("Task 6")`).

### Step 3.4: Build, test, commit

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Messages"
# Expect: 3 unit tests pass; PROP-* conformance tests are in their own filter
```

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/src/VMx/Messages/ \
        langs/csharp/tests/VMx.Tests/Messages/ \
        langs/csharp/tests/VMx.Conformance.Tests/PropertyChangeConformanceTests.cs \
        langs/csharp/tests/VMx.Conformance.Tests/_StubClasses.cs
git commit -m "feat(csharp): Messages module (2b/1) — IMessage hierarchy + PropertyChanged + ConstructionStatusChanged records

- Messages/IMessage, IMessage<TSender>, IPropertyChangedMessage<TSender>,
  IConstructionStatusChangedMessage — interface hierarchy per spec/03-messages.md
- Messages/PropertyChangedMessage<TSender> and ConstructionStatusChangedMessage
  as sealed records with static Create factories (record value-equality and
  auto-generated ToString)
- unit tests cover Create factories and record-equality

Conformance tests for PROP-001..004 are declared here (delegating to
ComponentVMConformanceTests stubs); they go green in Task 6 when the
modeled ComponentVM<M> setter is implemented.

Refs: spec/03-messages.md"
```

______________________________________________________________________

## Task 4 — Services (2b second half): IMessageHub + MessageHub + IDispatcher + RxDispatcher + HUB-001..007

**Spec references:** `spec/03-messages.md` (hub contract), `spec/11-threading.md` (dispatcher), `spec/fixtures/message-ordering.json`, `spec/12-conformance.md` (HUB-001..007).

**Files:**

- Create: `langs/csharp/src/VMx/Services/IMessageHub.cs`
- Create: `langs/csharp/src/VMx/Services/MessageHub.cs`
- Create: `langs/csharp/src/VMx/Services/IDispatcher.cs`
- Create: `langs/csharp/src/VMx/Services/RxDispatcher.cs`
- Create: `langs/csharp/tests/VMx.Tests/Services/MessageHubTests.cs`
- Create: `langs/csharp/tests/VMx.Tests/Services/RxDispatcherTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/HubConformanceTests.cs`

### Step 4.1: IMessageHub + MessageHub

`langs/csharp/src/VMx/Services/IMessageHub.cs`:

```csharp
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Hot pub/sub stream for IMessage events. See spec/03-messages.md.
/// </summary>
public interface IMessageHub
{
    IObservable<IMessage> Messages { get; }
    void Send<TMessage>(TMessage message) where TMessage : IMessage;
}
```

`langs/csharp/src/VMx/Services/MessageHub.cs`:

```csharp
using System.Reactive.Linq;
using System.Reactive.Subjects;
using VMx.Messages;

namespace VMx.Services;

/// <summary>
/// Default Subject-backed hub. Hot stream — late subscribers do not see
/// prior messages. Subscriber-handler exceptions are swallowed (per HUB-007).
/// </summary>
public sealed class MessageHub : IMessageHub, IDisposable
{
    private readonly Subject<IMessage> _subject = new();
    private bool _disposed;

    public IObservable<IMessage> Messages =>
        // Swallow subscriber exceptions so one bad handler doesn't break the stream.
        _subject.Catch<IMessage, Exception>(_ => System.Reactive.Linq.Observable.Empty<IMessage>());

    public void Send<TMessage>(TMessage message) where TMessage : IMessage
    {
        if (_disposed) return;
        _subject.OnNext(message);
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subject.OnCompleted();
        _subject.Dispose();
    }
}
```

Note on the subscriber-exception contract (HUB-007 / spec/03-messages.md §Subscriber resilience): "if a subscriber's handler raises, the hub MUST swallow the exception". The cleanest C# realization is to wrap each subscription so it isolates its handler. Replace the `Messages` property with a per-subscription wrapper:

```csharp
    public IObservable<IMessage> Messages =>
        System.Reactive.Linq.Observable.Create<IMessage>(observer =>
        {
            return _subject.Subscribe(
                onNext: msg =>
                {
                    try { observer.OnNext(msg); }
                    catch { /* swallow — spec/03-messages.md §Subscriber resilience */ }
                },
                onError: observer.OnError,
                onCompleted: observer.OnCompleted);
        });
```

(The `Catch` version is wrong because it terminates the outer observable on exception. The Observable.Create wrapper is correct.)

### Step 4.2: IDispatcher + RxDispatcher

`langs/csharp/src/VMx/Services/IDispatcher.cs`:

```csharp
using System.Reactive.Concurrency;

namespace VMx.Services;

public interface IDispatcher
{
    IScheduler Foreground { get; }
    IScheduler Background { get; }
}
```

`langs/csharp/src/VMx/Services/RxDispatcher.cs`:

```csharp
using System.Reactive.Concurrency;

namespace VMx.Services;

/// <summary>
/// Default <see cref="IDispatcher"/>. Foreground uses the current SynchronizationContext
/// (typical UI thread), Background uses the task pool.
/// </summary>
public sealed class RxDispatcher : IDispatcher
{
    public IScheduler Foreground { get; }
    public IScheduler Background { get; }

    public RxDispatcher(IScheduler foreground, IScheduler background)
    {
        Foreground = foreground;
        Background = background;
    }

    /// <summary>
    /// Builds a dispatcher whose Foreground binds to the current
    /// <see cref="SynchronizationContext"/>. Background uses TaskPoolScheduler.
    /// </summary>
    public static RxDispatcher CreateForCurrentContext()
    {
        var ctx = SynchronizationContext.Current
            ?? throw new InvalidOperationException(
                "No SynchronizationContext on the current thread. Use the (foreground, background) " +
                "constructor explicitly, e.g., from a UI framework's dispatcher.");
        return new RxDispatcher(
            foreground: new SynchronizationContextScheduler(ctx),
            background: TaskPoolScheduler.Default);
    }
}
```

### Step 4.3: Unit tests (samples — implement comprehensively)

`langs/csharp/tests/VMx.Tests/Services/MessageHubTests.cs`:

```csharp
using FluentAssertions;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Services;

public class MessageHubTests
{
    private sealed record Stub(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    [Fact]
    public void Send_Delivers_To_Current_Subscriber()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        rec.Items.Should().ContainSingle().Which.Tag.Should().Be("A");
    }

    [Fact]
    public void Late_Subscriber_Does_Not_See_Prior_Messages()
    {
        using var hub = new MessageHub();
        hub.Send(new Stub("pre"));
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("post"));
        rec.Items.Should().ContainSingle().Which.Tag.Should().Be("post");
    }

    [Fact]
    public void Single_Producer_FIFO()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        hub.Send(new Stub("C"));
        rec.Items.Select(m => m.Tag).Should().Equal("A", "B", "C");
    }

    [Fact]
    public void Subscriber_Exception_Does_Not_Break_Hub()
    {
        using var hub = new MessageHub();
        var goodCount = 0;
        var bad = hub.Messages.Subscribe(_ => throw new InvalidOperationException("bad"));
        var good = hub.Messages.Subscribe(_ => goodCount++);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        goodCount.Should().Be(2, "the surviving subscriber sees both messages");
        bad.Dispose(); good.Dispose();
    }
}
```

`langs/csharp/tests/VMx.Tests/Services/RxDispatcherTests.cs`:

```csharp
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Services;

public class RxDispatcherTests
{
    [Fact]
    public void Exposes_Injected_Schedulers()
    {
        var fg = new TestScheduler();
        var bg = new TestScheduler();
        var d = new RxDispatcher(fg, bg);
        d.Foreground.Should().BeSameAs(fg);
        d.Background.Should().BeSameAs(bg);
    }
}
```

### Step 4.4: HUB-001..007 conformance tests

`langs/csharp/tests/VMx.Conformance.Tests/HubConformanceTests.cs`:

```csharp
using FluentAssertions;
using System.Reactive.Linq;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class HubConformanceTests
{
    private sealed record Stub(string Tag) : IMessage
    {
        public string SenderName => Tag;
        public object SenderObject => Tag;
    }

    [Fact, Trait("Conformance", "HUB-001")]
    public void HUB_001_Send_Delivers_To_Current_Subscribers()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        rec.Items.Should().HaveCount(1);
    }

    [Fact, Trait("Conformance", "HUB-002")]
    public void HUB_002_Late_Subscribers_Do_Not_See_Prior()
    {
        using var hub = new MessageHub();
        hub.Send(new Stub("A"));
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("B"));
        rec.Items.Select(m => m.Tag).Should().Equal("B");
    }

    [Fact, Trait("Conformance", "HUB-003")]
    public void HUB_003_Single_Producer_FIFO()
    {
        using var hub = new MessageHub();
        using var rec = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        hub.Send(new Stub("C"));
        rec.Items.Select(m => m.Tag).Should().Equal("A", "B", "C");
    }

    [Fact, Trait("Conformance", "HUB-004")]
    public void HUB_004_Subscriber_Dispose_During_Emit_Does_Not_Crash()
    {
        using var hub = new MessageHub();
        var seen = new List<string>();
        IDisposable? sub = null;
        sub = hub.Messages.OfType<Stub>().Subscribe(m =>
        {
            seen.Add(m.Tag);
            sub?.Dispose();
        });
        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));
        seen.Should().Equal("A");
    }

    [Fact, Trait("Conformance", "HUB-005")]
    public void HUB_005_Multiple_Subscribers_All_Observe()
    {
        using var hub = new MessageHub();
        using var a = new RecordedMessages<Stub>(hub.Messages);
        using var b = new RecordedMessages<Stub>(hub.Messages);
        using var c = new RecordedMessages<Stub>(hub.Messages);
        hub.Send(new Stub("X"));
        a.Items.Should().HaveCount(1);
        b.Items.Should().HaveCount(1);
        c.Items.Should().HaveCount(1);
    }

    [Fact, Trait("Conformance", "HUB-006")]
    public void HUB_006_Hub_Matches_Message_Ordering_Fixture()
    {
        var root = Fixtures.FixtureLoader.Load<OrderingFixture>("message-ordering.json");
        foreach (var scenario in root.Scenarios)
        {
            scenario.Id.Should().NotBeNullOrEmpty();
            // Single-producer FIFO scenario.
            if (scenario.Id == "single-producer-fifo")
            {
                using var hub = new MessageHub();
                using var rec = new RecordedMessages<Stub>(hub.Messages);
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                rec.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObserved!);
            }
            // Late subscribe scenario.
            else if (scenario.Id == "late-subscribe-no-replay")
            {
                using var hub = new MessageHub();
                foreach (var tag in scenario.ProducerSendsBeforeSubscribe!)
                    hub.Send(new Stub(tag));
                using var rec = new RecordedMessages<Stub>(hub.Messages);
                foreach (var tag in scenario.ProducerSendsAfterSubscribe!)
                    hub.Send(new Stub(tag));
                rec.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObserved!);
            }
            // Multi-subscriber scenario.
            else if (scenario.Id == "multiple-subscribers-same-message")
            {
                using var hub = new MessageHub();
                var subscribers = Enumerable.Range(0, scenario.SubscriberCount)
                    .Select(_ => new RecordedMessages<Stub>(hub.Messages))
                    .ToList();
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                foreach (var sub in subscribers)
                {
                    sub.Items.Select(m => m.Tag).Should().Equal(scenario.ExpectedObservedPerSubscriber!);
                    sub.Dispose();
                }
            }
            // Unsubscribe during emit.
            else if (scenario.Id == "unsubscribe-during-emit")
            {
                using var hub = new MessageHub();
                var seen = new List<string>();
                IDisposable? sub = null;
                sub = hub.Messages.OfType<Stub>().Subscribe(m =>
                {
                    seen.Add(m.Tag);
                    if (scenario.UnsubscribeAfterFirst) sub?.Dispose();
                });
                foreach (var tag in scenario.ProducerSends!)
                    hub.Send(new Stub(tag));
                seen.Should().Equal(scenario.ExpectedObserved!);
            }
        }
    }

    [Fact, Trait("Conformance", "HUB-007")]
    public void HUB_007_Subscriber_Handler_Raises_Does_Not_Break_Hub()
    {
        using var hub = new MessageHub();
        var goodSeen = new List<string>();
        var badSub = hub.Messages.OfType<Stub>().Subscribe(_ => throw new InvalidOperationException("bad"));
        var goodSub = hub.Messages.OfType<Stub>().Subscribe(m => goodSeen.Add(m.Tag));

        hub.Send(new Stub("A"));
        hub.Send(new Stub("B"));

        goodSeen.Should().Equal("A", "B");

        badSub.Dispose();
        goodSub.Dispose();
    }

    private sealed class OrderingFixture
    {
        public List<Scenario> Scenarios { get; init; } = new();
    }

    private sealed class Scenario
    {
        public string Id { get; init; } = "";
        public List<string>? ProducerSends { get; init; }
        public List<string>? ProducerSendsBeforeSubscribe { get; init; }
        public List<string>? ProducerSendsAfterSubscribe { get; init; }
        public List<string>? ExpectedObserved { get; init; }
        public List<string>? ExpectedObservedPerSubscriber { get; init; }
        public int SubscriberCount { get; init; }
        public bool UnsubscribeAfterFirst { get; init; }
    }
}
```

### Step 4.5: Build + test + commit

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Services|HubConformance"
```

Expected: all 4 MessageHubTests + 1 RxDispatcherTests + 7 HUB-\* conformance tests pass.

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/src/VMx/Services/ \
        langs/csharp/tests/VMx.Tests/Services/ \
        langs/csharp/tests/VMx.Conformance.Tests/HubConformanceTests.cs
git commit -m "feat(csharp): Services module (2b/2) — IMessageHub, MessageHub, IDispatcher, RxDispatcher

- Services/IMessageHub + MessageHub: Subject-backed hot stream. Subscriber
  exceptions are isolated per-handler via Observable.Create wrapping so a bad
  handler doesn't terminate the stream (HUB-007).
- Services/IDispatcher + RxDispatcher: paired Rx schedulers (Foreground +
  Background). CreateForCurrentContext binds Foreground to the current
  SynchronizationContext and uses TaskPoolScheduler.Default for Background.

Unit tests cover Send/late-subscribe/FIFO/exception isolation. Conformance
HUB-001..007 all pass — the fixture-driven HUB-006 exercises all four
scenarios from spec/fixtures/message-ordering.json.

Refs: spec/03-messages.md, spec/11-threading.md, spec/fixtures/message-ordering.json"
```

______________________________________________________________________

## Task 5 — Commands (2c): ICommand, RelayCommand, RelayCommand<T>, builders + CMD-001..007

**Spec references:** `spec/04-commands.md`, `spec/fixtures/command-truthtable.json`, `spec/12-conformance.md` (CMD-001..007).

This task delivers the full command system. The plan only sketches signatures and key tests; subagents read the spec for full normative behavior.

**Files:**

- Create: `langs/csharp/src/VMx/Commands/ICommandBuilder.cs`
- Create: `langs/csharp/src/VMx/Commands/RelayCommand.cs`
- Create: `langs/csharp/src/VMx/Commands/RelayCommandT.cs`
- Create: `langs/csharp/tests/VMx.Tests/Commands/RelayCommandTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/CommandConformanceTests.cs`

### Step 5.1: Signatures

`langs/csharp/src/VMx/Commands/ICommandBuilder.cs`:

```csharp
using System.Reactive;

namespace VMx.Commands;

public interface ICommandBuilder
{
    ICommandBuilder Task(Action task);
    ICommandBuilder Predicate(Func<bool> predicate);
    ICommandBuilder Triggers(IObservable<Unit> trigger);
    System.Windows.Input.ICommand Build();
}

public interface ICommandBuilder<T>
{
    ICommandBuilder<T> Task(Action<T> task);
    ICommandBuilder<T> Predicate(Func<T, bool> predicate);
    ICommandBuilder<T> Triggers(IObservable<Unit> trigger);
    System.Windows.Input.ICommand Build();
}
```

`langs/csharp/src/VMx/Commands/RelayCommand.cs`:

Implement per `spec/04-commands.md` — fluent immutable builder, gates Execute on CanExecute (predicate-false → no-op), trigger emissions fire CanExecuteChanged. Use `init`-only fields and `with` for immutability. Triggers list is additive (multiple `.Triggers(...)` calls combine).

```csharp
using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Windows.Input;

namespace VMx.Commands;

public sealed class RelayCommand : ICommand, IDisposable
{
    // Implementation per spec/04-commands.md.
    // The builder is a nested record with init-only fields; each setter returns
    // a copy via `with`. Build() instantiates RelayCommand with the accumulated
    // state. Triggers are subscribed during Build() and disposed on Dispose().
    //
    // SEE THE SPEC for: predicate-null defaults to true, task-null defaults to no-op,
    // Execute is gated on CanExecute, predicate exceptions DO NOT propagate (treat as false),
    // task exceptions DO propagate.

    private readonly Action? _task;
    private readonly Func<bool>? _predicate;
    private readonly CompositeDisposable _triggerSubscriptions = new();

    private RelayCommand(Action? task, Func<bool>? predicate, IReadOnlyList<IObservable<Unit>> triggers)
    {
        _task = task;
        _predicate = predicate;
        foreach (var t in triggers)
            _triggerSubscriptions.Add(t.Subscribe(_ => CanExecuteChanged?.Invoke(this, EventArgs.Empty)));
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter)
    {
        if (_predicate is null) return true;
        try { return _predicate(); }
        catch { return false; }
    }

    public void Execute(object? parameter)
    {
        if (!CanExecute(parameter)) return;
        _task?.Invoke();
    }

    public void Dispose() => _triggerSubscriptions.Dispose();

    public static ICommandBuilder Builder() => new Builder_();

    private sealed class Builder_ : ICommandBuilder
    {
        private Action? _task;
        private Func<bool>? _predicate;
        private readonly List<IObservable<Unit>> _triggers = new();

        public ICommandBuilder Task(Action task) { _task = task; return this; }
        public ICommandBuilder Predicate(Func<bool> predicate) { _predicate = predicate; return this; }
        public ICommandBuilder Triggers(IObservable<Unit> trigger) { _triggers.Add(trigger); return this; }
        public ICommand Build() => new RelayCommand(_task, _predicate, _triggers);
    }
}
```

NOTE: the spec/10-builders.md "immutability" rule requires that setters return a NEW builder instance. The above builder mutates. **Subagent: change Builder\_ to use a record with `with` expressions** so each setter returns a NEW instance (or simply replace the mutable builder with an immutable record-based builder that conforms to BLD-001). The spec-compliant builder for RelayCommand looks like:

```csharp
    public sealed record Builder_(
        Action? Task = null,
        Func<bool>? Predicate = null,
        ImmutableList<IObservable<Unit>>? Triggers = null) : ICommandBuilder
    {
        ICommandBuilder ICommandBuilder.Task(Action task) => this with { Task = task };
        ICommandBuilder ICommandBuilder.Predicate(Func<bool> predicate) => this with { Predicate = predicate };
        ICommandBuilder ICommandBuilder.Triggers(IObservable<Unit> trigger) =>
            this with { Triggers = (Triggers ?? ImmutableList<IObservable<Unit>>.Empty).Add(trigger) };
        ICommand ICommandBuilder.Build() =>
            new RelayCommand(Task, Predicate, (IReadOnlyList<IObservable<Unit>>?)Triggers ?? Array.Empty<IObservable<Unit>>());
    }
```

This is the form to ship. (Requires `using System.Collections.Immutable;`.)

### Step 5.2: RelayCommand<T>

`langs/csharp/src/VMx/Commands/RelayCommandT.cs` — same pattern parameterized by `T`. The full code mirrors the above but takes `Action<T>` and `Func<T, bool>`. **Subagent: write it as a sibling type using the immutable-builder pattern.**

### Step 5.3: Unit tests

`langs/csharp/tests/VMx.Tests/Commands/RelayCommandTests.cs`:

Cover (one Fact each at minimum):

- `Build()` without task/predicate/triggers → CanExecute=true, Execute no-op
- `Task` only → Execute invokes task
- `Predicate(() => false)` → CanExecute=false, Execute does NOT invoke task
- `Predicate(() => true)` + `Task` → Execute invokes task
- Trigger emission → CanExecuteChanged fires
- Parameterized `RelayCommand<int>` → parameter threads through to task
- Predicate that throws → CanExecute returns false (defensive)
- Setter returns a NEW builder instance (BLD-001)

### Step 5.4: CMD-001..007 conformance tests

`langs/csharp/tests/VMx.Conformance.Tests/CommandConformanceTests.cs`:

CMD-001..006 are straightforward unit-style tests with `[Trait("Conformance", "CMD-NNN")]` markers. CMD-007 loads `command-truthtable.json` and runs every row:

```csharp
[Fact, Trait("Conformance", "CMD-007")]
public void CMD_007_Command_Truth_Table()
{
    var root = Fixtures.FixtureLoader.Load<CommandTruthTable>("command-truthtable.json");
    foreach (var c in root.Cases)
    {
        var taskInvoked = false;
        var changedCount = 0;
        var trigger = new System.Reactive.Subjects.Subject<System.Reactive.Unit>();

        var b = RelayCommand.Builder().Triggers(trigger);
        if (c.Predicate is not null)
            b = b.Predicate(() => c.Predicate.Value);
        if (c.Task == "noop")
            b = b.Task(() => taskInvoked = true);

        var cmd = b.Build();
        cmd.CanExecuteChanged += (_, _) => changedCount++;

        cmd.CanExecute(null).Should().Be(c.CanExecute, $"case {c.Id}: CanExecute");

        if (c.TriggerEmits)
            trigger.OnNext(System.Reactive.Unit.Default);

        cmd.Execute(null);
        taskInvoked.Should().Be(c.ExecuteInvokesTask, $"case {c.Id}: ExecuteInvokesTask");
        (changedCount > 0).Should().Be(c.CanExecuteChangedFires, $"case {c.Id}: CanExecuteChangedFires");

        ((IDisposable)cmd).Dispose();
        trigger.Dispose();
    }
}
```

(Subagent: full CommandTruthTable + Case record class definitions follow the same pattern as the message-ordering fixture in Task 4.)

### Step 5.5: Build + test + commit

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Commands|CommandConformance"
```

Expected: all unit tests + 7 CMD-\* conformance tests pass.

Commit message:

```
feat(csharp): Commands module (2c) — RelayCommand + RelayCommand<T> with reactive triggers

- Commands/RelayCommand + RelayCommandT: ICommand impls (BCL ICommand from
  System.Windows.Input) with predicate (null→true), task (null→noop), and
  reactive triggers. Execute is gated on CanExecute per spec/04-commands.md
  §Task semantics. Trigger emissions fire CanExecuteChanged.
- Builder is an immutable record; each setter returns a new instance via `with`,
  satisfying BLD-001.
- Triggers are additive across multiple .Triggers(...) calls.
- Subscriptions disposed when the command is disposed.

Unit + conformance CMD-001..007 pass; CMD-007 is fixture-driven from
spec/fixtures/command-truthtable.json.

Refs: spec/04-commands.md, spec/fixtures/command-truthtable.json
```

______________________________________________________________________

## Task 6 — Components (2d): IComponentVM + ComponentVMBase + ComponentVM<M> + ReadonlyComponentVM<M> + CVM-001..006 + PROP-001..004 + LIFE-001..010, 012

**Spec references:** `spec/05-component-vm.md`, `spec/01-concepts.md` (IComponentVM baseline), `spec/02-lifecycle.md` (lifecycle), `spec/12-conformance.md` (CVM, PROP, most LIFE).

This is the largest single task. The component VM is the heart of the library and many LIFE-\* tests depend on a concrete VM. Implementer reads spec/05-component-vm.md fully before starting.

**Files (source):**

- Create: `langs/csharp/src/VMx/Components/ViewModelType.cs`
- Create: `langs/csharp/src/VMx/Components/IComponentVM.cs`
- Create: `langs/csharp/src/VMx/Components/IComponentVMOfM.cs`
- Create: `langs/csharp/src/VMx/Components/IReadonlyComponentVM.cs`
- Create: `langs/csharp/src/VMx/Components/ComponentVMBase.cs`
- Create: `langs/csharp/src/VMx/Components/ComponentVMBaseOfM.cs`
- Create: `langs/csharp/src/VMx/Components/ComponentVM.cs`
- Create: `langs/csharp/src/VMx/Components/ReadonlyComponentVM.cs`
- Create: `langs/csharp/src/VMx/Components/ComponentVMBuilder.cs`
- Create: `langs/csharp/src/VMx/Builders/BuilderValidationException.cs`

**Files (tests):**

- Create: `langs/csharp/tests/VMx.Tests/Components/ComponentVMTests.cs`
- Create: `langs/csharp/tests/VMx.Tests/Components/ReadonlyComponentVMTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/ComponentVMConformanceTests.cs` (replaces stub from Task 2)

### Step 6.1: Foundation types

`langs/csharp/src/VMx/Components/ViewModelType.cs`:

```csharp
namespace VMx.Components;

public enum ViewModelType
{
    Component,
    ReadOnlyComponent,
    Aggregate,
    Group,
    Composite,
}
```

`langs/csharp/src/VMx/Builders/BuilderValidationException.cs`:

```csharp
namespace VMx.Builders;

public sealed class BuilderValidationException : InvalidOperationException
{
    public string MissingField { get; }
    public BuilderValidationException(string missingField)
        : base($"Required builder field is missing: {missingField}")
    {
        MissingField = missingField;
    }
}
```

### Step 6.2: IComponentVM hierarchy

`langs/csharp/src/VMx/Components/IComponentVM.cs`:

```csharp
using System.ComponentModel;
using System.Windows.Input;
using VMx.Lifecycle;

namespace VMx.Components;

/// <summary>
/// Baseline contract for every VMx viewmodel. See spec/01-concepts.md
/// §IComponentVM baseline and spec/05-component-vm.md.
/// </summary>
public interface IComponentVM : INotifyPropertyChanged, IDisposable
{
    string Name { get; }
    string Hint { get; }
    ViewModelType Type { get; }
    bool IsCurrent { get; }
    bool IsConstructed { get; }
    ConstructionStatus Status { get; }

    ICommand SelectCommand { get; }
    ICommand DeselectCommand { get; }
    ICommand SelectNextCommand { get; }
    ICommand SelectPreviousCommand { get; }
    ICommand ReconstructCommand { get; }

    bool CanConstruct();
    Task ConstructAsync();
    void Construct();

    bool CanDestruct();
    Task DestructAsync();
    void Destruct();

    bool CanReconstruct();
    Task ReconstructAsync();
    void Reconstruct();

    bool CanSelect();
    void Select();

    bool CanDeselect();
    void Deselect();
}
```

`langs/csharp/src/VMx/Components/IComponentVMOfM.cs`:

```csharp
namespace VMx.Components;

public interface IComponentVM<M> : IComponentVM
{
    M Model { get; set; }
    string ModeledHint { get; }
}
```

`langs/csharp/src/VMx/Components/IReadonlyComponentVM.cs`:

```csharp
namespace VMx.Components;

public interface IReadonlyComponentVM<M> : IComponentVM
{
    M Model { get; }  // no setter
    string ModeledHint { get; }
}
```

### Step 6.3: ComponentVMBase + ComponentVMBaseOfM + ComponentVM<M> + ReadonlyComponentVM<M>

**Subagent: implement these by reading spec/05-component-vm.md fully.** The plan provides shape; the spec provides behavior.

Key contracts to implement (cross-reference spec):

1. **Lifecycle operations** — go through `LifecycleTransitionValidator.Require()` then emit `ConstructionStatusChangedMessage(Constructing)` → flip the status → emit `(Constructed)`.
1. **PropertyChanged** — on `Status`, `IsConstructed`, `IsCurrent`, `Model`, `ModeledHint` setters/changes. Emit both `INotifyPropertyChanged.PropertyChanged` AND a `PropertyChangedMessage<this>` on the hub.
1. **`Model` setter** (modeled variant) — skip if `EqualityComparer<M>.Default.Equals(old, new)`; otherwise emit `PropertyChangedMessage("Model")`, optionally invoke `OnModelChanged`, recompute `ModeledHint`, emit `PropertyChangedMessage("ModeledHint")`.
1. **`ModeledHint`** — computed via `Func<M, string>` from the builder; defaults to `_ => ""`.
1. **Built-in commands** — each is a `RelayCommand` with predicate = `CanXxx()` and task = `Xxx()`. They re-trigger on `Status` changes.
1. **Idempotency** — `Construct()` from `Constructed` is a no-op (no message). Same for `Destruct()` from `Destructed`. Validator allows these per the fixture.
1. **Concurrency guard** — track `_inFlight` boolean during `Construct/Destruct`; if `Construct()` is called while `_inFlight && Status == Constructing`, raise `StatusTransitionException`.
1. **`IsConstructed`** — getter returns `Status == ConstructionStatus.Constructed`.
1. **Dispose** — transition to `Disposed` (legal from any state per fixture). Emit `(Disposed)`.

`langs/csharp/src/VMx/Components/ComponentVMBuilder.cs`:

Provide a fluent immutable builder. Each setter returns a new builder via `with`. Required fields validated on `Build()`:

- `Name` (string, non-null)
- `IMessageHub`
- `IDispatcher`

Optional fields with defaults:

- `Hint` → `""`
- `Type` → `ViewModelType.Component`
- `Parent` → `null`
- `Background` → `false`
- `OnConstruct`, `OnDestruct` → no-op callbacks
- (Modeled variant adds: `Model`, `ModeledHinter` → `m => ""`, `OnModelChanged` → no-op)

Two builders: `ComponentVM<M>.Builder()` and `ReadonlyComponentVM<M>.Builder()`. Static `Builder()` methods return empty builders.

### Step 6.4: Unit tests

Cover (one Fact each):

- Builder `Name("x").Hint("y").Type(t).Services(hub, disp).Build()` → component has those values
- Setting `Name` twice → final value (overwrite semantics)
- Build without `Services` → `BuilderValidationException("Services")`
- Build without `Name` → `BuilderValidationException("Name")`
- `Model` setter for modeled VM: different value → PropertyChanged emitted
- `Model` setter for modeled VM: same value (per `EqualityComparer<M>.Default`) → silent
- Readonly variant: API surface check that `Model` has no public setter (reflection or compile-time check)
- `ModeledHint` recomputes on `Model` change
- `Status` transitions emit messages
- Dispose cascade

### Step 6.5: Conformance tests — CVM-001..006, PROP-001..004, plus LIFE-\* delegations

`langs/csharp/tests/VMx.Conformance.Tests/ComponentVMConformanceTests.cs` is the BIG file in this task. Replace the stub from Task 2 with a public class. Implement every method named by `LifecycleConformanceTests` and `PropertyChangeConformanceTests` delegations, plus the CVM-001..006 [Fact, Trait] entries.

**Delete** the stub class from `_StubClasses.cs` so the real one is found by the delegations.

Pattern for each conformance method:

```csharp
[Fact, Trait("Conformance", "CVM-001")]
public void CVM_001_Construct_Emits_Status_Messages()
{
    using var hub = new MessageHub();
    using var rec = new RecordedMessages<ConstructionStatusChangedMessage>(hub.Messages);
    var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);

    var vm = ComponentVM<string>.Builder()
        .Name("vm1")
        .Services(hub, dispatcher)
        .Model("initial")
        .Build();

    vm.Construct();

    rec.Items.Select(m => m.Status).Should().Equal(
        ConstructionStatus.Constructing,
        ConstructionStatus.Constructed);
    vm.IsConstructed.Should().BeTrue();
}
```

**Subagent: implement all CVM-* and the delegated LIFE-* / PROP-\* methods.\*\* Each is ~10-15 lines. Total: ~14 conformance methods in this file.

### Step 6.6: Build + test + commit

Verify:

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Conformance"
```

Expected: 30+ conformance tests pass (everything except COMP/GRP/AGG/FWD/BLD/THR which come later).

Commit message:

```
feat(csharp): Components module (2d) — ComponentVM<M>, ReadonlyComponentVM<M>, baseline IComponentVM

- ViewModelType enum (Component/ReadOnlyComponent/Aggregate/Group/Composite)
- IComponentVM baseline: Name/Hint/Type/IsCurrent/IsConstructed/Status, five
  built-in commands (Select/Deselect/SelectNext/SelectPrevious/Reconstruct),
  lifecycle ops (CanConstruct/Construct/...)/their async variants, selection ops.
- IComponentVM<M>: adds Model getter/setter and ModeledHint.
- IReadonlyComponentVM<M>: adds Model getter (no setter) and ModeledHint.
- ComponentVMBase / ComponentVMBaseOfM: abstract bases. Lifecycle invokes
  validator + emits ConstructionStatusChangedMessage at each transition.
  Idempotent self-transitions (Constructed→Constructed) emit no message.
- ComponentVM<M> sealed concrete + ReadonlyComponentVM<M> sealed concrete.
- ComponentVMBuilder + ReadonlyComponentVMBuilder: immutable fluent builders,
  required-field validation (Name, Services), defaults documented in
  spec/10-builders.md.
- Builders/BuilderValidationException: thrown by Build() on missing fields.

Conformance: CVM-001..006 + PROP-001..004 + LIFE-001..010, 012 all pass.
Stub delegations in _StubClasses.cs removed for ComponentVMConformanceTests
(now a real public class).

Refs: spec/01-concepts.md, spec/05-component-vm.md, spec/02-lifecycle.md, spec/10-builders.md
```

______________________________________________________________________

## Task 7 — Composites (2e): CompositeVM<VM> + CompositeVM\<M, VM> + COMP-001..011 + LIFE-013

**Spec references:** `spec/06-composite-vm.md`, `spec/12-conformance.md` (COMP-001..011), `spec/02-lifecycle.md` (LIFE-013 dispose cascade).

**Files (source):**

- Create: `langs/csharp/src/VMx/Composites/ICompositeVM.cs`
- Create: `langs/csharp/src/VMx/Composites/ICompositeVMOfMVM.cs`
- Create: `langs/csharp/src/VMx/Composites/CompositeVMBase.cs`
- Create: `langs/csharp/src/VMx/Composites/CompositeVM.cs`
- Create: `langs/csharp/src/VMx/Composites/CompositeVMOfM.cs`
- Create: `langs/csharp/src/VMx/Composites/CompositeVMBuilder.cs`

**Files (tests):**

- Create: `langs/csharp/tests/VMx.Tests/Composites/CompositeVMTests.cs`
- Create: `langs/csharp/tests/VMx.Tests/Composites/ModeledCompositeVMTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/CompositeVMConformanceTests.cs` (replaces stub from Task 2)

### Step 7.1: ICompositeVM hierarchy

```csharp
using System.Collections.Specialized;
using VMx.Components;

namespace VMx.Composites;

public interface ICompositeVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged
    where VM : class, IComponentVM
{
    VM? Current { get; set; }
    void SelectComponent(VM vm);
    void DeselectComponent(VM vm);
    bool CanSelectComponent(VM vm);
}
```

`ICompositeVMOfMVM.cs`: same plus model-source typing.

### Step 7.2: CompositeVMBase + concrete classes

**Subagent: implement per spec/06-composite-vm.md.** Key contracts:

- `IList<VM>` (Add, Remove, Insert, RemoveAt, Clear, Count, indexer, iterator)
- `INotifyCollectionChanged` (CollectionChanged event)
- `Current` setter:
  - `null` is always legal (no-op if already null)
  - Setting to non-`null` requires `value ∈ children` (otherwise raise)
  - Emit `PropertyChangedMessage("Current")` and update affected children's `IsCurrent`
  - If `AsyncSelection(true)`, dispatch via `IDispatcher.Foreground`
- `SelectComponent(vm)` / `DeselectComponent(vm)` per spec
- `CanSelectComponent(vm)` returns `vm ∈ children && vm.Status == Constructed`
- Children construction orchestration:
  - `Construct()`: parallel-invoke children's `Construct()`, listen for each child's `ConstructionStatusChangedMessage(Constructed)`, then transition self to `Constructed`
  - `Destruct()`: set `Current = null`, parallel-invoke `Destruct()` on each child, wait for all `(Destructed)`, transition self
- `Dispose()` cascades depth-first to children (LIFE-013)
- Modeled variant builds children via `ChildrenModels()` + `ChildModelToChildViewModel()` on `Construct()`

### Step 7.3: Unit tests + conformance

Implement COMP-001..011 + the LIFE-013 cascade test.

### Step 7.4: Commit

```
feat(csharp): Composites module (2e) — CompositeVM<VM>, CompositeVM<M, VM>

- Composites/ICompositeVM<VM> + ICompositeVM<M, VM> interfaces
- CompositeVMBase: IList<VM> + INotifyCollectionChanged + Current selection
- Construction orchestration: parent waits for all children Constructed
- Destruction orchestration: Current → null then parallel destruct children
- Dispose cascade depth-first (LIFE-013)
- AsyncSelection dispatches Current change via IDispatcher.Foreground
- Modeled variant maps M → VM on Construct via builder factories

Conformance COMP-001..011 + LIFE-013 pass.

Refs: spec/06-composite-vm.md
```

______________________________________________________________________

## Task 8 — Groups (2f): GroupVM<VM> + GRP-001..004

**Spec references:** `spec/07-group-vm.md`, `spec/12-conformance.md` (GRP-001..004).

GroupVM is CompositeVM minus `Current`, `select_component`, `deselect_component`, `can_select_component`, `SelectNextCommand`, `SelectPreviousCommand`. It RETAINS `SelectCommand` and `DeselectCommand` (for self-selection in its own parent).

**Files (source):**

- Create: `langs/csharp/src/VMx/Groups/IGroupVM.cs`
- Create: `langs/csharp/src/VMx/Groups/GroupVMBase.cs`
- Create: `langs/csharp/src/VMx/Groups/GroupVM.cs`
- Create: `langs/csharp/src/VMx/Groups/GroupVMBuilder.cs`

**Files (tests):**

- Create: `langs/csharp/tests/VMx.Tests/Groups/GroupVMTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/GroupVMConformanceTests.cs`

Implementation mirrors CompositeVM but without the selection-of-children members. Children construction/destruction orchestration is identical. Conformance GRP-001..004 follow the pattern from COMP-001..004.

Commit message:

```
feat(csharp): Groups module (2f) — GroupVM<VM>

- Groups/IGroupVM<VM>, GroupVMBase, GroupVM<VM>, GroupVMBuilder
- IList<VM> + INotifyCollectionChanged inherited from base
- No Current property; no select_component/deselect_component members; no
  SelectNextCommand/SelectPreviousCommand commands.
- Retains SelectCommand/DeselectCommand from IComponentVM baseline (these
  govern selecting the GROUP within its own parent, not the children).
- Children construction/destruction orchestration identical to CompositeVM.

Conformance GRP-001..004 pass.

Refs: spec/07-group-vm.md
```

______________________________________________________________________

## Task 9 — Aggregates (2g): AggregateVM1..AggregateVM5 + AGG-001..005

**Spec references:** `spec/08-aggregate-vm.md`, `spec/12-conformance.md` (AGG-001..005), ADR-0007.

Five separate interfaces and five separate concrete classes. The builder for each takes `ComponentN(() => makeVMN)` factories.

**Files:** 11 source files (5 interfaces, 5 concretes, 1 builder file containing 5 nested builder types), 1 test file, 1 conformance file.

### Suggestion for the implementer

Write `IAggregateVM1` and `AggregateVM1` first. Then use them as a template for arities 2-5. The differences are purely structural:

- Arity N has properties `Component1`, `Component2`, ..., `ComponentN`
- Builder has methods `Component1`, `Component2`, ..., `ComponentN`
- Each requires all N factories before `Build()`

If 5 files of nearly-identical code feels wrong, a T4 template or source generator is appropriate per ADR-0007 — but for v1.0, **hand-write the 5 arities**. Keep it boring.

Conformance tests:

- AGG-001: arity-1 component factory invoked on construct
- AGG-002: arity-2 both reach Constructed
- AGG-003: arity-5 ordering (parent reaches Constructed only AFTER all children)
- AGG-004: PropertyChangedMessage("ComponentN") emitted on construct
- AGG-005: arity-2 destruct waits for both children Destructed

Commit message:

```
feat(csharp): Aggregates module (2g) — AggregateVM1..AggregateVM5

- 5 interfaces (IAggregateVM1..IAggregateVM5) and 5 concrete classes
- Each arity-N has Component1..ComponentN typed properties populated by
  lazy factory functions provided via the builder.
- Construct() invokes all factories in parallel, awaits each child's
  Constructed status, then transitions self.
- Destruct() destructs all children in parallel, awaits Destructed, transitions.
- Each ComponentN slot population emits PropertyChangedMessage("ComponentN").

Conformance AGG-001..005 pass.

Refs: spec/08-aggregate-vm.md, spec/ADRs/0007-aggregate-vm-arity-1-to-5.md
```

______________________________________________________________________

## Task 10 — Forwarding (2h): ForwardingComponentVM<M> + ForwardingCompositeVM<VM> + FWD-001..003

**Spec references:** `spec/09-forwarding.md`, `spec/12-conformance.md` (FWD-001..003).

**Files (source):**

- Create: `langs/csharp/src/VMx/Forwarding/ForwardingComponentVM.cs` (abstract class wrapping `IComponentVM<M>`)
- Create: `langs/csharp/src/VMx/Forwarding/ForwardingCompositeVM.cs` (abstract class wrapping `ICompositeVM<VM>`)

Both are abstract; each public member of the wrapped interface delegates to `_wrapped`. Subclasses override individual members to customize behavior.

**Files (tests):**

- Create: `langs/csharp/tests/VMx.Tests/Forwarding/ForwardingTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/ForwardingConformanceTests.cs`

Test fixtures: define a `NoOpForwardingComponentVM<M>` concrete subclass (no overrides) and a `HintOverridingForwardingComponentVM<M>` (overrides Hint).

FWD-001: every public member of the no-op subclass returns/invokes the wrapped's value/effect.
FWD-002: the Hint-overriding subclass returns "OVERRIDE" for Hint; all other members still delegate.
FWD-003: ForwardingCompositeVM iteration yields wrapped's children in order.

Commit message:

```
feat(csharp): Forwarding module (2h) — ForwardingComponentVM<M>, ForwardingCompositeVM<VM>

- Both are abstract; constructors take the wrapped instance.
- Every public member delegates to _wrapped by default.
- Subclasses override individual members as needed.

Conformance FWD-001..003 pass.

Refs: spec/09-forwarding.md
```

______________________________________________________________________

## Task 11 — Builders cross-cutting (2-task) + BLD-001..004

**Spec references:** `spec/10-builders.md`, `spec/12-conformance.md` (BLD-001..004).

Most builder behavior is exercised via the per-module tests (Tasks 5-10). This task adds the cross-cutting BLD-001..004 conformance tests against a representative VM (ComponentVM<string>).

**Files:**

- Create: `langs/csharp/tests/VMx.Tests/Builders/BuilderTests.cs`
- Create: `langs/csharp/tests/VMx.Conformance.Tests/BuilderConformanceTests.cs`

BLD-001: setter returns new builder instance. `b1 = ComponentVM<string>.Builder(); b2 = b1.Name("x"); object.ReferenceEquals(b1, b2).Should().BeFalse();`
BLD-002: missing required field → BuilderValidationException with field name in the message.
BLD-003: two `Build()` calls produce two distinct instances with equal Name/Hint/Type/Model.
BLD-004: defaults applied (Hint="", Parent=null, Type=derived).

Commit message:

```
test(csharp): Builders conformance (2-cross-cutting) — BLD-001..004

- BuilderTests.cs: unit tests verifying setter returns new instance, repeated
  Build() calls produce equivalent-but-distinct VMs, missing required fields
  raise BuilderValidationException with field name in message.
- BuilderConformanceTests.cs: BLD-001..004 against ComponentVM<string> as the
  representative VM type.

Refs: spec/10-builders.md
```

______________________________________________________________________

## Task 12 — Threading conformance (2-task) + THR-001..004

**Spec references:** `spec/11-threading.md`, `spec/12-conformance.md` (THR-001..004).

**Files:**

- Create: `langs/csharp/tests/VMx.Conformance.Tests/ThreadingConformanceTests.cs`

THR-001: build a modeled `ComponentVM<string>` with a `TestDispatcher` (foreground = TestScheduler); subscribe to `PropertyChangedMessage` on the hub via `ObserveOn(dispatcher.Foreground)`; set `vm.Model = "new"`; advance the foreground TestScheduler; assert the subscriber handler was invoked.

THR-002: build a `ComponentVM` with `.Background(true)` and a TestDispatcher; invoke `ConstructAsync()`; verify it returns immediately (status still Destructed); advance the background TestScheduler; verify status now Constructed.

THR-003: same as THR-001 but for CollectionChanged on a CompositeVM.

THR-004: hub.Messages.ObserveOn(any scheduler).Subscribe(...).hub.Send(...) → handler invoked on that scheduler.

Commit message:

```
test(csharp): Threading conformance (2-cross-cutting) — THR-001..004

- ThreadingConformanceTests.cs verifies the IDispatcher contract:
  - PropertyChanged observable through ObserveOn(dispatcher.Foreground)
  - Background construct/destruct dispatches on IDispatcher.Background
  - CollectionChanged observable on Foreground
  - Subscribers via ObserveOn(scheduler) see emissions on that scheduler

All four use Microsoft.Reactive.Testing.TestScheduler for deterministic time.

Refs: spec/11-threading.md
```

______________________________________________________________________

## Task 13 — DI companion package (2i): VMx.Extensions.DependencyInjection

**Spec references:** `spec/01-concepts.md` (dependency philosophy), ADR-0001 (drop comScore), ADR-0003 (constructor injection).

**Files:**

- Create: `langs/csharp/src/VMx.Extensions.DependencyInjection/VMx.Extensions.DependencyInjection.csproj`
- Create: `langs/csharp/src/VMx.Extensions.DependencyInjection/ServiceCollectionExtensions.cs`
- Modify: `langs/csharp/VMx.sln` (add the new project)
- Modify: `langs/csharp/Directory.Packages.props` (add Microsoft.Extensions.DependencyInjection.Abstractions)

`VMx.Extensions.DependencyInjection.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFrameworks>netstandard2.0;net8.0</TargetFrameworks>
    <RootNamespace>VMx.Extensions.DependencyInjection</RootNamespace>
    <AssemblyName>VMx.Extensions.DependencyInjection</AssemblyName>
    <PackageId>VMx.Extensions.DependencyInjection</PackageId>
    <Version>0.0.1-dev</Version>
    <Description>VMx integration with Microsoft.Extensions.DependencyInjection.</Description>
    <PackageTags>mvvm;viewmodel;reactive;dependency-injection</PackageTags>
    <MinSpecVersion>1.0.0</MinSpecVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.Extensions.DependencyInjection.Abstractions" />
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="..\VMx\VMx.csproj" />
  </ItemGroup>
</Project>
```

`ServiceCollectionExtensions.cs`:

```csharp
using Microsoft.Extensions.DependencyInjection;
using VMx.Services;

namespace VMx.Extensions.DependencyInjection;

public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers IMessageHub and IDispatcher with the host DI container.
    /// IMessageHub → singleton MessageHub.
    /// IDispatcher → singleton RxDispatcher.CreateForCurrentContext() (or a custom one).
    /// </summary>
    public static IServiceCollection AddVMx(
        this IServiceCollection services,
        Action<VMxOptions>? configure = null)
    {
        var options = new VMxOptions();
        configure?.Invoke(options);

        services.AddSingleton<IMessageHub, MessageHub>();
        if (options.DispatcherFactory is not null)
            services.AddSingleton(options.DispatcherFactory);
        else
            services.AddSingleton<IDispatcher>(_ => RxDispatcher.CreateForCurrentContext());

        return services;
    }
}

public sealed class VMxOptions
{
    public Func<IServiceProvider, IDispatcher>? DispatcherFactory { get; set; }
    public VMxOptions UseDispatcher(Func<IServiceProvider, IDispatcher> factory)
    {
        DispatcherFactory = factory;
        return this;
    }
}
```

Add Microsoft.Extensions.DependencyInjection.Abstractions to `Directory.Packages.props`:

```xml
<PackageVersion Include="Microsoft.Extensions.DependencyInjection.Abstractions" Version="8.0.0" />
```

`dotnet sln VMx.sln add src/VMx.Extensions.DependencyInjection/VMx.Extensions.DependencyInjection.csproj`

Unit tests aren't strictly necessary for this thin extension class, but add one smoke test in VMx.Tests:

```csharp
[Fact]
public void AddVMx_Registers_Singleton_MessageHub()
{
    var services = new ServiceCollection();
    services.AddVMx(opts => opts.UseDispatcher(_ => new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance)));
    var sp = services.BuildServiceProvider();
    var hub1 = sp.GetRequiredService<IMessageHub>();
    var hub2 = sp.GetRequiredService<IMessageHub>();
    hub1.Should().BeSameAs(hub2);
}
```

Commit:

```
feat(csharp): DI companion package (2i) — VMx.Extensions.DependencyInjection

Optional companion that wires IMessageHub and IDispatcher into a host
Microsoft.Extensions.DependencyInjection container via AddVMx(). MessageHub
and RxDispatcher both registered as singletons. VMxOptions.UseDispatcher
lets the host substitute a custom dispatcher (e.g., bound to a UI thread).

Targets netstandard2.0;net8.0 like the core library. Declares MinSpecVersion=1.0.0.

Refs: spec/01-concepts.md, spec/ADRs/0001-drop-comscore.md, spec/ADRs/0003-constructor-injection.md
```

______________________________________________________________________

## Task 14 — Full conformance verification (2j): all 68 tests pass

This task has no new source code. It verifies that the conformance suite passes 68/68 and the coverage tool reports `csharp: 68/68 covered`.

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet build VMx.sln -c Release
dotnet test VMx.sln -c Release --no-build --filter "Conformance"
```

Expected output: `Passed: 68, Failed: 0, Skipped: 0` (the conformance project has 68 tests).

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run python tools/check-conformance-coverage.py
```

Expected: `csharp: 68/68 covered`.

If any conformance test fails or is missing, fix it before committing. This task is THE gate — without 68/68, the next task (tagging csharp-v1.0.0) cannot proceed.

Once green, remove `_StubClasses.cs` (it should be empty by now — all stub classes were replaced by Tasks 6/7).

```bash
cd /Users/kaveh/repos/VMx
git rm langs/csharp/tests/VMx.Conformance.Tests/_StubClasses.cs
git commit -m "test(csharp): remove _StubClasses.cs — every conformance ID now has a real implementation

The placeholder class hierarchy added in Task 2 has been replaced by real
ComponentVMConformanceTests (Task 6) and CompositeVMConformanceTests (Task 7).
All 68 catalog IDs report green; check-conformance-coverage.py confirms
csharp: 68/68 covered.

Refs: spec/12-conformance.md"
```

______________________________________________________________________

## Task 15 — Docs (2k): getting-started/csharp.md + DocFX skeleton

**Files:**

- Create: `docs/getting-started/csharp.md`
- (Optional, defer if time-constrained) `docs/api/csharp/` DocFX skeleton

`docs/getting-started/csharp.md` covers:

- Install via `dotnet add package VMx` (note: not yet published; for now `dotnet add reference`)
- Wire IMessageHub + IDispatcher
- Build a ComponentVM<M>
- Subscribe to PropertyChangedMessage
- Build a RelayCommand
- Construct/destruct

The full markdown should be ~200 lines with runnable C# snippets. **Subagent: write a clean, beginner-friendly tutorial.**

Commit:

```
docs(csharp): add getting-started/csharp.md tutorial for VMx C# library

Covers installation, dispatcher/hub setup, basic ComponentVM<M>, RelayCommand
with reactive triggers, and CompositeVM<VM> with selection. All examples are
copy-pasteable into a console app and runnable.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.2 (Phase 2k)
```

______________________________________________________________________

## Task 16 — Examples (2l): HelloVMx + WpfTodoApp

**Files:**

- Create: `examples/csharp/HelloVMx/HelloVMx.csproj`
- Create: `examples/csharp/HelloVMx/Program.cs`
- Create: `examples/csharp/WpfTodoApp/WpfTodoApp.csproj`
- Create: `examples/csharp/WpfTodoApp/App.xaml`, `App.xaml.cs`, `MainWindow.xaml`, `MainWindow.xaml.cs`, `MainWindowViewModel.cs`

HelloVMx is a console app showing a single ComponentVM<string> being built, constructed, model-set, destructed. ~50 lines of code.

WpfTodoApp is a small WPF app with a `CompositeVM<TodoItemVM>` bound to a `ListBox` via WPF data binding. Targets `net8.0-windows`. ~150 lines including XAML.

**Subagent: implement both.** Verify HelloVMx runs (`dotnet run --project examples/csharp/HelloVMx/HelloVMx.csproj`) and outputs expected console text. WpfTodoApp only verifies it builds — running requires a display.

Commit:

```
docs(csharp): examples — HelloVMx (console) and WpfTodoApp (WPF binding demo)

- examples/csharp/HelloVMx: minimal console example demonstrating builder,
  hub subscription, construct/destruct, and Model setter.
- examples/csharp/WpfTodoApp: WPF MVVM demo using CompositeVM<TodoItemVM>
  bound to a ListBox. Targets net8.0-windows; demonstrates that VMx
  integrates with WPF's INotifyPropertyChanged + ICommand bindings without
  any extra glue code.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.2 (Phase 2l)
```

______________________________________________________________________

## Task 17 — Tag csharp-v1.0.0 + update CHANGELOG + push (2m)

### Step 17.1: Final local verification

```bash
cd /Users/kaveh/repos/VMx/langs/csharp
dotnet restore VMx.sln
dotnet format VMx.sln --verify-no-changes
dotnet build VMx.sln -c Release --no-restore
dotnet test VMx.sln -c Release --no-build
```

Expected: build clean, all tests pass.

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run python tools/check-conformance-coverage.py
```

Expected: `csharp: 68/68 covered`.

```bash
pre-commit run --all-files
```

Expected: all hooks pass.

### Step 17.2: Update CHANGELOGs

`langs/csharp/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to the C# flavor are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-XX-XX

### Added
- Full implementation of spec-v1.0.0:
  - Lifecycle: `ConstructionStatus` + `StatusTransitionException` + transition validator
  - Messages: `IMessage` hierarchy + `PropertyChangedMessage` + `ConstructionStatusChangedMessage`
  - Services: `IMessageHub`/`MessageHub` + `IDispatcher`/`RxDispatcher`
  - Commands: `RelayCommand` + `RelayCommand<T>` with reactive triggers
  - Components: `ComponentVM<M>` + `ReadonlyComponentVM<M>`
  - Composites: `CompositeVM<VM>` + `CompositeVM<M, VM>`
  - Groups: `GroupVM<VM>`
  - Aggregates: `AggregateVM1` through `AggregateVM5`
  - Forwarding: `ForwardingComponentVM<M>` + `ForwardingCompositeVM<VM>`
  - Optional DI companion package `VMx.Extensions.DependencyInjection` with `AddVMx()`
- 68 conformance tests covering LIFE-001..013, HUB-001..007, PROP-001..004,
  CMD-001..007, CVM-001..006, COMP-001..011, GRP-001..004, AGG-001..005,
  FWD-001..003, BLD-001..004, THR-001..004 — all pass.
- Multi-target `netstandard2.0;net8.0`. Test runner targets `net9.0`.
- Examples: HelloVMx (console) and WpfTodoApp (WPF binding).
- Getting-started tutorial at `docs/getting-started/csharp.md`.

## [Unreleased]
```

Update `langs/csharp/src/VMx/VMx.csproj` version to `1.0.0` (was `0.0.1-dev`):

```xml
<Version>1.0.0</Version>
<MinSpecVersion>1.0.0</MinSpecVersion>
```

Update `Placeholder.MinSpecVersion` reference if any unit tests still depend on it — at this point Placeholder is gone (deleted in Task 1), so remove any lingering smoke test references.

`compatibility-matrix.md` update:

```markdown
| 1.0.x | 1.0.0           | — (Phase 3 WIP)  | —          |
```

### Step 17.3: Commit + tag + push

```bash
cd /Users/kaveh/repos/VMx
git add langs/csharp/CHANGELOG.md langs/csharp/src/VMx/VMx.csproj compatibility-matrix.md
git commit -m "release(csharp): csharp-v1.0.0 — full implementation of spec-v1.0.0

68 of 68 conformance IDs pass against spec-v1.0.0. Multi-target
netstandard2.0;net8.0. Optional DI companion package included.

See langs/csharp/CHANGELOG.md for the full feature list.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.2"

git tag -a csharp-v1.0.0 -m "VMx C# v1.0.0

First stable release of the C# flavor of VMx. Implements spec-v1.0.0 with
all 68 conformance IDs green. Multi-targets netstandard2.0 and net8.0.

Packages:
- VMx 1.0.0 (core library; NuGet publish deferred)
- VMx.Extensions.DependencyInjection 1.0.0 (optional)

See langs/csharp/CHANGELOG.md for details."

git push -u origin feat/phase-2-csharp-v1
git push origin csharp-v1.0.0
```

______________________________________________________________________

## Phase 2 — completion criteria

Phase 2 is done when ALL of these are true:

1. All 17 tasks committed in order.
1. `dotnet build VMx.sln -c Release` clean (0 warnings, 0 errors).
1. `dotnet test VMx.sln -c Release` passes every test (~80+ unit tests + 68 conformance tests).
1. `dotnet format VMx.sln --verify-no-changes` exits 0.
1. `uv --project langs/python run python tools/check-conformance-coverage.py` reports `csharp: 68/68 covered`.
1. `pre-commit run --all-files` passes all 11 hooks.
1. `langs/csharp/src/VMx/VMx.csproj` version is `1.0.0`.
1. Both companion packages (`VMx`, `VMx.Extensions.DependencyInjection`) exist with version `1.0.0`.
1. `examples/csharp/HelloVMx/` builds AND runs successfully.
1. `examples/csharp/WpfTodoApp/` builds (running requires Windows + display; skip the run).
1. `docs/getting-started/csharp.md` exists and is non-trivial.
1. Tag `csharp-v1.0.0` exists locally and on origin.
1. NO commits in the branch contain `Co-Authored-By: Claude` or any AI-attribution trailer.

Once all 13 are true, Phase 2 is complete and Phase 3 (Python v1.0) can begin.

______________________________________________________________________

## Plan self-review notes

- **Spec coverage:** Each spec file (00–11) maps to a task: lifecycle→Task 2, messages→Tasks 3+4, commands→Task 5, components→Task 6, composites→Task 7, groups→Task 8, aggregates→Task 9, forwarding→Task 10, builders→Task 11, threading→Task 12. Conformance catalog (12) → Task 14 final verification.
- **Placeholder scan:** The plan uses "Subagent: read spec for full behavior" several times in Tasks 6, 7, 9 because each spec file is the authoritative source — replicating spec text in the plan would create drift. This is acceptable because the spec is committed and stable. Each task lists EXACTLY which files to create and the test names that must exist.
- **Type consistency:** `IMessageHub`, `IDispatcher`, `ComponentVM<M>`, `ConstructionStatusChangedMessage`, `Status`, `IsConstructed`, etc. — same names throughout. Builder method names match spec (`Name`, `Hint`, `Services`, `Model`, `ModeledHinter`, `OnModelChanged`, `Type`, `Background`, etc.).
- **Commit-message hygiene:** Every commit message ends with `Refs:` and NO Co-Authored-By trailer. This is restated in the top-of-plan IMPORTANT note.
