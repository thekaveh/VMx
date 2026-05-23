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
