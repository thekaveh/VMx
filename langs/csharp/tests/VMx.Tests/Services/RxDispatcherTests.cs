using System.Reactive.Concurrency;
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

    [Fact]
    public void Immediate_Uses_ImmediateScheduler_For_Both_Slots()
    {
        var d = RxDispatcher.Immediate();
        d.Foreground.Should().BeSameAs(ImmediateScheduler.Instance);
        d.Background.Should().BeSameAs(ImmediateScheduler.Instance);
    }
}
