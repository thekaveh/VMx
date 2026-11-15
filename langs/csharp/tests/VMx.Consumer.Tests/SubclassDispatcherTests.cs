using System.Reactive.Concurrency;
using VMx.Components;
using VMx.Services;
using Xunit;

namespace VMx.Consumer.Tests;

/// <summary>
/// A subclass in another assembly reads the dispatcher its base was constructed
/// with, the way same-assembly container subclasses do (ADR-0229).
/// </summary>
public class SubclassDispatcherTests
{
    private sealed class ScheduledVM : ComponentVMBase
    {
        public ScheduledVM(IMessageHub hub, IDispatcher dispatcher)
            : base("scheduled", hub, dispatcher)
        {
        }

        public IDispatcher ReadDispatcher() => Dispatcher;

        public override ViewModelType Type => ViewModelType.Component;
    }

    private sealed class StubDispatcher : IDispatcher
    {
        public IScheduler Foreground => ImmediateScheduler.Instance;
        public IScheduler Background => ImmediateScheduler.Instance;
    }

    [Fact]
    public void Subclass_ReadsTheDispatcherItWasConstructedWith()
    {
        using var hub = new MessageHub();
        var dispatcher = new StubDispatcher();
        var vm = new ScheduledVM(hub, dispatcher);

        Assert.Same(dispatcher, vm.ReadDispatcher());
    }
}
