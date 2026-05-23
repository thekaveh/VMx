using System.ComponentModel;
using FluentAssertions;
using VMx.Components;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// Unit tests for <see cref="ComponentVM{M}"/> behavior.
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class ComponentVMTests
{
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

    // ── Identity ─────────────────────────────────────────────────────────────

    [Fact]
    public void Name_Is_Set_From_Builder()
    {
        var (vm, _, _) = BuildVm("myVm");
        vm.Name.Should().Be("myVm");
    }

    [Fact]
    public void Hint_Defaults_To_Empty()
    {
        var (vm, _, _) = BuildVm();
        vm.Hint.Should().BeEmpty();
    }

    [Fact]
    public void Hint_Can_Be_Set_In_Builder()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m").Hint("myHint").Build();
        vm.Hint.Should().Be("myHint");
    }

    [Fact]
    public void Type_Is_Component()
    {
        var (vm, _, _) = BuildVm();
        vm.Type.Should().Be(ViewModelType.Component);
    }

    // ── Initial state ────────────────────────────────────────────────────────

    [Fact]
    public void Initial_Status_Is_Destructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Initial_IsConstructed_Is_False()
    {
        var (vm, _, _) = BuildVm();
        vm.IsConstructed.Should().BeFalse();
    }

    [Fact]
    public void Initial_IsCurrent_Is_False()
    {
        var (vm, _, _) = BuildVm();
        vm.IsCurrent.Should().BeFalse();
    }

    // ── Construct ───────────────────────────────────────────────────────────

    [Fact]
    public void Construct_Changes_Status_To_Constructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Construct_Sets_IsConstructed_True()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.IsConstructed.Should().BeTrue();
    }

    [Fact]
    public void Construct_Emits_Two_Hub_Messages()
    {
        var (vm, hub, _) = BuildVm();
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        vm.Construct();
        messages.Should().HaveCount(2);
        messages[0].Status.Should().Be(ConstructionStatus.Constructing);
        messages[1].Status.Should().Be(ConstructionStatus.Constructed);
    }

    [Fact]
    public void Construct_From_Constructed_Is_Noop()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        vm.Construct(); // idempotent call
        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── Destruct ─────────────────────────────────────────────────────────────

    [Fact]
    public void Destruct_Changes_Status_To_Destructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.Destruct();
        vm.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Destruct_From_Destructed_Is_Noop()
    {
        var (vm, hub, _) = BuildVm();
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        vm.Destruct(); // already Destructed
        messages.Should().BeEmpty();
    }

    // ── Reconstruct ──────────────────────────────────────────────────────────

    [Fact]
    public void Reconstruct_Emits_Four_Messages()
    {
        var (vm, hub, _) = BuildVm();
        vm.Construct();
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        vm.Reconstruct();
        messages.Should().HaveCount(4);
        messages.Select(m => m.Status).Should().ContainInOrder(
            ConstructionStatus.Destructing,
            ConstructionStatus.Destructed,
            ConstructionStatus.Constructing,
            ConstructionStatus.Constructed);
    }

    // ── Dispose ──────────────────────────────────────────────────────────────

    [Fact]
    public void Dispose_Transitions_To_Disposed()
    {
        var (vm, _, _) = BuildVm();
        vm.Dispose();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Dispose_From_Constructed_Transitions_To_Disposed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.Dispose();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact]
    public void Dispose_Is_Idempotent()
    {
        var (vm, hub, _) = BuildVm();
        vm.Dispose();
        var messages = new List<ConstructionStatusChangedMessage>();
        hub.Messages.Subscribe(m =>
        {
            if (m is ConstructionStatusChangedMessage csm) messages.Add(csm);
        });
        vm.Dispose(); // second dispose - no-op
        messages.Should().BeEmpty();
        vm.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── Lifecycle predicates ─────────────────────────────────────────────────

    [Fact]
    public void CanConstruct_Returns_True_From_Destructed()
    {
        var (vm, _, _) = BuildVm();
        vm.CanConstruct().Should().BeTrue();
    }

    [Fact]
    public void CanConstruct_Returns_True_From_Constructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.CanConstruct().Should().BeTrue(); // idempotent no-op
    }

    [Fact]
    public void CanDestruct_Returns_True_From_Constructed()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.CanDestruct().Should().BeTrue();
    }

    [Fact]
    public void CanDestruct_Returns_True_From_Destructed()
    {
        var (vm, _, _) = BuildVm();
        vm.CanDestruct().Should().BeTrue(); // idempotent no-op
    }

    [Fact]
    public void CanReconstruct_Returns_True_Only_From_Constructed()
    {
        var (vm, _, _) = BuildVm();
        vm.CanReconstruct().Should().BeFalse(); // Destructed
        vm.Construct();
        vm.CanReconstruct().Should().BeTrue(); // Constructed
    }

    [Fact]
    public void Construct_From_Disposed_Raises()
    {
        var (vm, _, _) = BuildVm();
        vm.Dispose();
        var act = () => vm.Construct();
        act.Should().Throw<StatusTransitionException>();
    }

    // ── Model setter ─────────────────────────────────────────────────────────

    [Fact]
    public void Model_Setter_Updates_Model()
    {
        var (vm, _, _) = BuildVm(model: "initial");
        vm.Model = "updated";
        vm.Model.Should().Be("updated");
    }

    [Fact]
    public void Model_Setter_Emits_PropertyChangedMessage()
    {
        var (vm, hub, _) = BuildVm(model: "initial");
        var messages = new List<IPropertyChangedMessage<IComponentVM>>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm) messages.Add(pcm);
        });
        vm.Model = "changed";
        messages.Should().Contain(m => m.PropertyName == "Model");
    }

    [Fact]
    public void Model_Setter_Same_Value_Does_Not_Emit()
    {
        var (vm, hub, _) = BuildVm(model: "same");
        var count = 0;
        hub.Messages.Subscribe(_ => count++);
        vm.Model = "same"; // same value
        count.Should().Be(0);
    }

    [Fact]
    public void Model_Setter_Raises_PropertyChanged_Event()
    {
        var (vm, _, _) = BuildVm(model: "initial");
        var props = new List<string?>();
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) => props.Add(e.PropertyName);
        vm.Model = "new";
        props.Should().Contain("Model");
    }

    // ── ModeledHint ──────────────────────────────────────────────────────────

    [Fact]
    public void ModeledHint_Default_Is_Empty()
    {
        var (vm, _, _) = BuildVm(model: "anything");
        vm.ModeledHint.Should().BeEmpty();
    }

    [Fact]
    public void ModeledHint_Recomputes_When_Model_Changes()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var vm = ComponentVM<int>.Builder()
            .Name("v").Services(hub, dispatcher).Model(7)
            .ModeledHinter(n => $"hint:{n}")
            .Build();
        vm.ModeledHint.Should().Be("hint:7");
        vm.Model = 8;
        vm.ModeledHint.Should().Be("hint:8");
    }

    [Fact]
    public void ModeledHint_Change_Emits_Message_On_Hub()
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
            if (m is IPropertyChangedMessage<IComponentVM> pcm && pcm.PropertyName == "ModeledHint")
                hintMessages.Add(pcm.PropertyName);
        });
        vm.Model = 8;
        hintMessages.Should().HaveCount(1);
    }

    // ── OnModelChanged callback ───────────────────────────────────────────────

    [Fact]
    public void OnModelChanged_Is_Invoked_After_Model_Changes()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var received = new List<string>();
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("init")
            .OnModelChanged(m => received.Add(m))
            .Build();
        vm.Model = "new";
        received.Should().ContainSingle().Which.Should().Be("new");
    }

    // ── OnConstruct / OnDestruct callbacks ───────────────────────────────────

    [Fact]
    public void OnConstruct_Is_Invoked_During_Construct()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var called = false;
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m")
            .OnConstruct(() => called = true)
            .Build();
        vm.Construct();
        called.Should().BeTrue();
    }

    [Fact]
    public void OnDestruct_Is_Invoked_During_Destruct()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var called = false;
        var vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m")
            .OnDestruct(() => called = true)
            .Build();
        vm.Construct();
        vm.Destruct();
        called.Should().BeTrue();
    }

    // ── Builder validation ────────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_Name_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => ComponentVM<string>.Builder()
            .Services(hub, dispatcher).Model("m").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    [Fact]
    public void Builder_Throws_When_Model_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("Model");
    }

    [Fact]
    public void Builder_Throws_When_Services_Missing()
    {
        var act = () => ComponentVM<string>.Builder()
            .Name("v").Model("m").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>();
    }

    [Fact]
    public void Builder_Is_Immutable()
    {
        var b0 = ComponentVM<string>.Builder();
        var b1 = b0.Name("x");
        b1.Should().NotBeSameAs(b0);
        // b0 is still empty (Name null → would fail validation)
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => b0.Services(hub, dispatcher).Model("m").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .Which.MissingField.Should().Be("Name");
    }

    // ── CanSelect / CanDeselect ───────────────────────────────────────────────

    [Fact]
    public void CanSelect_Returns_False_Without_Parent()
    {
        var (vm, _, _) = BuildVm();
        vm.Construct();
        vm.CanSelect().Should().BeFalse();
    }

    [Fact]
    public void CanDeselect_Returns_False_Without_Parent()
    {
        var (vm, _, _) = BuildVm();
        vm.CanDeselect().Should().BeFalse();
    }

    // ── INPC raises on Status and IsConstructed changes ───────────────────────

    [Fact]
    public void Construct_Raises_INPC_For_Status()
    {
        var (vm, _, _) = BuildVm();
        var props = new List<string?>();
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) => props.Add(e.PropertyName);
        vm.Construct();
        props.Should().Contain("Status");
    }

    [Fact]
    public void Construct_Raises_INPC_For_IsConstructed()
    {
        var (vm, _, _) = BuildVm();
        var props = new List<string?>();
        ((INotifyPropertyChanged)vm).PropertyChanged += (_, e) => props.Add(e.PropertyName);
        vm.Construct();
        props.Should().Contain("IsConstructed");
    }

    // ── Concurrent operation guard ────────────────────────────────────────────

    [Fact]
    public void Concurrent_Construct_During_Constructing_Raises()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        StatusTransitionException? caught = null;
        ComponentVM<string>? vm = null;
        vm = ComponentVM<string>.Builder()
            .Name("v").Services(hub, dispatcher).Model("m")
            .OnConstruct(() =>
            {
                // Simulate a concurrent call during the construct callback.
                try { vm!.Construct(); }
                catch (StatusTransitionException ex) { caught = ex; }
            })
            .Build();
        vm.Construct();
        caught.Should().NotBeNull();
    }
}
