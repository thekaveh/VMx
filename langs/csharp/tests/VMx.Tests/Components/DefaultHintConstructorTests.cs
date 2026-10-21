using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// The protected base constructors have overloads without <c>hint</c> that
/// default it to an empty string, and the modeled base defaults its hinter to
/// an empty hint, as the builders do (spec/10 §4, BLD-004). No conformance ID
/// (C# constructor ergonomics, #663).
/// </summary>
public class DefaultHintConstructorTests
{
    private sealed class PanelVM : ComponentVMBase
    {
        public PanelVM() : base("panel", new TestHub(), new TestDispatcher())
        {
        }

        public override ViewModelType Type => ViewModelType.Component;
    }

    private sealed class CountVM : ComponentVMBaseOfM<int>
    {
        public CountVM(int model, Func<int, string>? modeledHinter = null)
            : base("count", model, new TestHub(), new TestDispatcher(), modeledHinter)
        {
        }

        public override ViewModelType Type => ViewModelType.Component;

        public int Model
        {
            get => ModelValue;
            set => ModelValue = value;
        }
    }

    private sealed class TitleVM : ComponentVMBaseOfM<string>
    {
        public TitleVM(string model)
            : base("title", model, new TestHub(), new TestDispatcher())
        {
        }

        public override ViewModelType Type => ViewModelType.Component;
    }

    private sealed class PanelsVM : CompositeVMBase<PanelVM>
    {
        public PanelsVM() : base("panels", new TestHub(), new TestDispatcher())
        {
        }
    }

    private sealed class PanelGroupVM : GroupVMBase<PanelVM>
    {
        public PanelGroupVM() : base("group", new TestHub(), new TestDispatcher())
        {
        }
    }

    [Fact]
    public void ComponentVMBase_DefaultsHint()
    {
        new PanelVM().Hint.Should().BeEmpty();
    }

    [Fact]
    public void ComponentVMBaseOfM_DefaultsHintAndModeledHint()
    {
        var vm = new CountVM(1);

        vm.Hint.Should().BeEmpty();
        vm.ModeledHint.Should().BeEmpty();
        vm.Model = 2;
        vm.ModeledHint.Should().BeEmpty();
    }

    [Fact]
    public void ComponentVMBaseOfM_KeepsASuppliedHinter()
    {
        var vm = new CountVM(1, m => $"#{m}");

        vm.Hint.Should().BeEmpty();
        vm.ModeledHint.Should().Be("#1");
        vm.Model = 2;
        vm.ModeledHint.Should().Be("#2");
    }

    [Fact]
    public void ComponentVMBaseOfM_WithAStringModel_BindsTheHintlessOverload()
    {
        var vm = new TitleVM("draft");

        vm.Hint.Should().BeEmpty();
        vm.ModeledHint.Should().BeEmpty();
    }

    [Fact]
    public void CompositeVMBase_AndGroupVMBase_DefaultHint()
    {
        new PanelsVM().Hint.Should().BeEmpty();
        new PanelGroupVM().Hint.Should().BeEmpty();
    }
}
