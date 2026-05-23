using System.Reflection;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for ComponentVM, covering CVM-001..006 and
/// delegated LIFE-*/PROP-* IDs. See spec/12-conformance.md.
/// </summary>
public class ComponentVMConformanceTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (ComponentVM<string> vm, TestHub hub, TestDispatcher dispatcher) BuildVm(
        string name = "vm1", string model = "initial")
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        return (vm, hub, dispatcher);
    }

    private static List<ConstructionStatusChangedMessage> RecordStatusMessages(TestHub hub)
    {
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        return messages;
    }

    // ── CVM-001 / LIFE-001 — Construct emits status messages ────────────────

    /// <summary>
    /// CVM-001 / LIFE-001: construct() from Destructed emits Constructing then Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-001")]
    public void CVM_001_Construct_Emits_Status_Messages()
    {
        var (vm, hub, _) = BuildVm();
        var messages = RecordStatusMessages(hub);

        vm.Construct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Constructing);
        messages[1].Status.Should().Be(ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();
    }

    // ── CVM-002 / PROP-001 — Modeled component fires PropertyChanged("Model") ─

    /// <summary>
    /// CVM-002 / PROP-001: setting Model to a different value publishes PropertyChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-002")]
    public void CVM_002_Modeled_Component_Fires_PropertyChanged_Model_On_Set()
    {
        var (vm, hub, _) = BuildVm(model: "m1");
        var propMessages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<ComponentVMBaseOfM<string>> pcm && pcm.PropertyName == "Model")
                propMessages.Add(m);
        });

        vm.Model = "m2";

        propMessages.Should().HaveCount(1);
    }

    // ── CVM-003 — ReadonlyComponentVM has no Model setter ────────────────────

    /// <summary>
    /// CVM-003: ReadonlyComponentVM&lt;M&gt; exposes no public Model setter.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-003")]
    public void CVM_003_ReadonlyComponentVM_Has_No_Model_Setter()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ReadonlyComponentVM<string>.Builder()
            .Name("ro").Services(hub, dispatcher).Model("fixed").Build();

        // Model value is accessible.
        vm.Model.Should().Be("fixed");

        // No public setter exists.
        var prop = typeof(ReadonlyComponentVM<string>)
            .GetProperty(nameof(ReadonlyComponentVM<string>.Model),
                BindingFlags.Public | BindingFlags.Instance);
        prop.Should().NotBeNull();
        prop!.CanWrite.Should().BeFalse("ReadonlyComponentVM must have no public Model setter");
        prop.GetSetMethod(nonPublic: true).Should().BeNull(
            "ReadonlyComponentVM must have no non-public Model setter either");
    }

    // ── CVM-004 — ModeledHint recomputes when Model changes ──────────────────

    /// <summary>
    /// CVM-004: changing Model causes ModeledHint to recompute and emits
    /// PropertyChangedMessage("ModeledHint").
    /// </summary>
    [Fact, Trait("Conformance", "CVM-004")]
    public void CVM_004_ModeledHint_Recomputes_When_Model_Changes()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<int>.Builder()
            .Name("v").Services(hub, dispatcher).Model(7)
            .ModeledHinter(n => $"hint:{n}")
            .Build();

        var hintMessages = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<ComponentVMBaseOfM<int>> pcm &&
                pcm.PropertyName == nameof(vm.ModeledHint))
                hintMessages.Add(pcm.PropertyName);
        });

        vm.Model = 8;

        vm.ModeledHint.Should().Be("hint:8");
        hintMessages.Should().HaveCount(1);
    }

    // ── CVM-005 — Name and Hint are immutable ────────────────────────────────

    /// <summary>
    /// CVM-005: Name and Hint have no public setters.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-005")]
    public void CVM_005_Name_And_Hint_Are_Immutable()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("orig").Hint("h").Services(hub, dispatcher).Model("m").Build();

        vm.Name.Should().Be("orig");
        vm.Hint.Should().Be("h");

        var nameProp = typeof(ComponentVM<string>)
            .GetProperty(nameof(ComponentVM<string>.Name), BindingFlags.Public | BindingFlags.Instance);
        nameProp!.CanWrite.Should().BeFalse("Name must be read-only");

        var hintProp = typeof(ComponentVM<string>)
            .GetProperty(nameof(ComponentVM<string>.Hint), BindingFlags.Public | BindingFlags.Instance);
        hintProp!.CanWrite.Should().BeFalse("Hint must be read-only");
    }

    // ── CVM-006 — SelectCommand CanExecute reflects selection state ───────────

    /// <summary>
    /// CVM-006: SelectCommand.CanExecute reflects the selection state.
    /// </summary>
    [Fact, Trait("Conformance", "CVM-006")]
    public void CVM_006_SelectCommand_CanExecute_Reflects_Selection_State()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m").Build();
        vm.Construct();

        // No parent: CanSelect is false.
        vm.SelectCommand.CanExecute(null).Should().BeFalse();

        // Set up a mock parent that can select.
        var parent = new MockCompositeVM();
        vm.Parent = parent;

        // Parent has no current: CanSelect is true.
        vm.SelectCommand.CanExecute(null).Should().BeTrue();

        // Simulate selection via the internal setter.
        parent.SetCurrent(vm);
        vm.IsCurrent = true; // use internal setter (InternalsVisibleTo)

        // Now SelectCommand.CanExecute reflects the new state after trigger fires.
        // The trigger fires asynchronously based on status changes, but for selection
        // the predicate is evaluated on-demand via CanExecute().
        vm.SelectCommand.CanExecute(null).Should().BeFalse();
    }

    // ── PROP-001 — Setter publishes PropertyChangedMessage ───────────────────

    /// <summary>
    /// PROP-001: setting Model to a different value publishes exactly one PropertyChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-001")]
    public void PROP_001_Setter_Publishes()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        var messages = new List<IMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<ComponentVMBaseOfM<string>> pcm && pcm.PropertyName == "Model")
                messages.Add(m);
        });

        vm.Model = "m2";

        messages.Should().HaveCount(1);
    }

    // ── PROP-002 — Setter same value is silent ────────────────────────────────

    /// <summary>
    /// PROP-002: setting Model to the same value emits no messages.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-002")]
    public void PROP_002_Setter_Same_Value_Silent()
    {
        var (vm, hub, _) = BuildVm(model: "m1");
        var count = 0;
        hub.Messages.Subscribe(_ => count++);

        vm.Model = "m1"; // same value

        count.Should().Be(0);
    }

    // ── PROP-003 — Sender identity ────────────────────────────────────────────

    /// <summary>
    /// PROP-003: the Sender in the PropertyChangedMessage is the VM instance.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-003")]
    public void PROP_003_Sender_Identity()
    {
        var (vm, hub, _) = BuildVm(name: "vm1", model: "m1");
        IMessage? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<ComponentVMBaseOfM<string>> pcm && pcm.PropertyName == "Model")
                observed = m;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.SenderObject.Should().BeSameAs(vm);
    }

    // ── PROP-004 — PropertyName and SenderName ────────────────────────────────

    /// <summary>
    /// PROP-004: PropertyName is "Model" and SenderName is the VM's Name.
    /// </summary>
    [Fact, Trait("Conformance", "PROP-004")]
    public void PROP_004_PropertyName_SenderName()
    {
        var (vm, hub, _) = BuildVm(name: "n1", model: "m1");
        IPropertyChangedMessage<ComponentVMBaseOfM<string>>? observed = null;
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<ComponentVMBaseOfM<string>> pcm && pcm.PropertyName == "Model")
                observed = pcm;
        });

        vm.Model = "m2";

        observed.Should().NotBeNull();
        observed!.PropertyName.Should().Be("Model");
        observed.SenderName.Should().Be("n1");
    }

    // ── LIFE-002 — Destruct transitions ──────────────────────────────────────

    /// <summary>
    /// LIFE-002: destruct() from Constructed emits Destructing then Destructed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-002")]
    public void LIFE_002_Destruct_Transitions()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Destruct();

        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Destructing);
        messages[1].Status.Should().Be(ConstructionStatus.Destructed);
        vm.IsConstructed.Should().BeFalse();
    }

    // ── LIFE-003 — Reconstruct emits full sequence ────────────────────────────

    /// <summary>
    /// LIFE-003: reconstruct() emits Destructing, Destructed, Constructing, Constructed.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-003")]
    public void LIFE_003_Reconstruct()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Reconstruct();

        messages.Should().HaveCount(4);
        messages.Select(m => m.Status).Should().ContainInOrder(
            ConstructionStatus.Destructing,
            ConstructionStatus.Destructed,
            ConstructionStatus.Constructing,
            ConstructionStatus.Constructed);
    }

    // ── LIFE-004 — Dispose from any state ────────────────────────────────────

    /// <summary>
    /// LIFE-004: dispose() from any non-Disposed state transitions to Disposed
    /// and emits a ConstructionStatusChangedMessage.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-004")]
    public void LIFE_004_Dispose_From_Any_State()
    {
        // Destructed
        {
            var (vm, hub, _) = BuildVm();
            var messages = RecordStatusMessages(hub);
            vm.Dispose();
            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }

        // Constructed
        {
            var (vm, hub, _) = BuildVm();
            vm.Construct();
            var messages = RecordStatusMessages(hub);
            vm.Dispose();
            vm.Status.Should().Be(ConstructionStatus.Disposed);
            messages.Should().Contain(m => m.Status == ConstructionStatus.Disposed);
        }
    }

    // ── LIFE-007 — IsConstructed invariant ───────────────────────────────────

    /// <summary>
    /// LIFE-007: IsConstructed == (Status == Constructed) at all times.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-007")]
    public void LIFE_007_IsConstructed_Invariant()
    {
        var (vm, _, _) = BuildVm();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);

        vm.Construct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeTrue();

        vm.Destruct();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
        vm.IsConstructed.Should().BeFalse();

        vm.Dispose();
        vm.IsConstructed.Should().Be(vm.Status == ConstructionStatus.Constructed);
    }

    // ── LIFE-008 — Concurrent operation raises ────────────────────────────────

    /// <summary>
    /// LIFE-008: invoking construct() while a construct() is already in progress raises.
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-008")]
    public void LIFE_008_Concurrent_Operation_Raises()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        StatusTransitionException? caught = null;
        ComponentVM<string>? vm = null;

        vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                // Re-enter construct while already constructing.
                try { vm!.Construct(); }
                catch (StatusTransitionException ex) { caught = ex; }
            })
            .Build();

        vm.Construct();

        caught.Should().NotBeNull("second concurrent Construct must raise StatusTransitionException");
    }

    // ── LIFE-009 — Idempotent construct ──────────────────────────────────────

    /// <summary>
    /// LIFE-009: construct() from Constructed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-009")]
    public void LIFE_009_Idempotent_Construct()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = RecordStatusMessages(hub);

        vm.Construct(); // already Constructed — idempotent

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── LIFE-010 — Idempotent destruct ───────────────────────────────────────

    /// <summary>
    /// LIFE-010: destruct() from Destructed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-010")]
    public void LIFE_010_Idempotent_Destruct()
    {
        var (vm, hub, _) = BuildVm();
        var messages = RecordStatusMessages(hub);

        vm.Destruct(); // already Destructed — idempotent

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── LIFE-012 — Dispose from Disposed emits no message ────────────────────

    /// <summary>
    /// LIFE-012: dispose() from Disposed is a no-op (no messages emitted).
    /// </summary>
    [Fact, Trait("Conformance", "LIFE-012")]
    public void LIFE_012_Dispose_From_Disposed_Silent()
    {
        var (vm, hub, _) = BuildVm();
        vm.Dispose();
        var messages = RecordStatusMessages(hub);

        vm.Dispose(); // already Disposed — no-op

        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── Mock composite for CVM-006 ────────────────────────────────────────────

    /// <summary>
    /// Minimal mock composite that supports selection for CVM-006 testing.
    /// Implements IParentCompositeVM so it can be assigned to ComponentVMBase.Parent.
    /// </summary>
    private sealed class MockCompositeVM : IParentCompositeVM
    {
        private IComponentVM? _current;

        public IComponentVM? CurrentChild => _current;

        public void SetCurrent(IComponentVM vm) => _current = vm;

        public void SelectChild(IComponentVM vm) => _current = vm;
        public void DeselectChild(IComponentVM vm) { if (_current == vm) _current = null; }
    }
}
