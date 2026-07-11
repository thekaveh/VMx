using System.Reactive.Disposables;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>Owned-resource and public-hub conformance (DISP-007..013).</summary>
public class OwnedResourceConformanceTests
{
    [Fact, Trait("Conformance", "DISP-007")]
    public void DISP_007_Owned_Resources_Are_Cleaned_In_Lifo_Order()
    {
        var trace = new List<string>();
        var vm = new ProbeVM(new TestHub(), () => trace.Add("hook"));
        vm.Register(() => trace.Add("action"));
        vm.Register(Disposable.Create(() => trace.Add("disposable")));
        vm.Register(() => trace.Add("last"));

        vm.Dispose();

        trace.Should().Equal("hook", "last", "disposable", "action");
    }

    [Fact, Trait("Conformance", "DISP-008")]
    public void DISP_008_Repeated_Dispose_Cleans_Each_Resource_Once()
    {
        var count = 0;
        var vm = new ProbeVM(new TestHub());
        vm.Register(() => count++);

        vm.Dispose();
        vm.Dispose();

        count.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-009")]
    public void DISP_009_Cleanup_Failure_Is_Swallowed_And_Does_Not_Stop_Later_Resources()
    {
        var trace = new List<string>();
        var vm = new ProbeVM(new TestHub());
        vm.Register(() => trace.Add("first"));
        vm.Register(() => throw new InvalidOperationException("boom"));
        vm.Register(() => trace.Add("last"));

        var act = vm.Dispose;

        act.Should().NotThrow();
        trace.Should().Equal("last", "first");
    }

    [Fact, Trait("Conformance", "DISP-010")]
    public void DISP_010_Registration_After_Dispose_Cleans_Immediately_Once()
    {
        var count = 0;
        var vm = new ProbeVM(new TestHub());
        vm.Dispose();

        vm.Register(() => count++);
        vm.Dispose();

        count.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-011")]
    public void DISP_011_Owned_Resources_Survive_Reconstruct_Until_Final_Dispose()
    {
        var count = 0;
        var vm = new ProbeVM(new TestHub());
        vm.Register(() => count++);
        vm.Construct();

        vm.Reconstruct();

        count.Should().Be(0);
        vm.Dispose();
        count.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-012")]
    public void DISP_012_Injected_Hub_Is_Publicly_Read_Only()
    {
        var hub = new TestHub();
        var vm = new ProbeVM(hub);

        vm.Hub.Should().BeSameAs(hub);
    }

    [Fact, Trait("Conformance", "DISP-013")]
    public void DISP_013_VM_Disposal_Does_Not_Dispose_Injected_Hub()
    {
        var hub = new MessageHub();
        var vm = new ProbeVM(hub);
        var received = 0;
        using var subscription = hub.Messages.Subscribe(_ => received++);
        vm.Dispose();
        var baseline = received;

        hub.Send(ConstructionStatusChangedMessage.Create(vm, vm.Name, vm.Status));

        received.Should().Be(baseline + 1);
    }

    private sealed class ProbeVM : ComponentVMBase
    {
        private readonly Action? _onDispose;

        public ProbeVM(IMessageHub hub, Action? onDispose = null)
            : base("probe", "", hub, new TestDispatcher(), null, null)
        {
            _onDispose = onDispose;
        }

        public override ViewModelType Type => ViewModelType.Component;

        public void Register(Action cleanup) => Own(cleanup);

        public void Register<T>(T resource) where T : IDisposable => Own(resource);

        protected override void OnDispose() => _onDispose?.Invoke();
    }
}
