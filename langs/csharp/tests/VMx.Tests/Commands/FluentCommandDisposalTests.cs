using System.Reactive;
using System.Reactive.Disposables;
using System.Reactive.Subjects;
using System.Windows.Input;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

/// <summary>
/// VMX-012: the fluent command decorators return <see cref="ICommand"/>, which
/// hides that every decorator is also <see cref="IDisposable"/> and stays rooted
/// to its inner command's <c>CanExecuteChanged</c> event until disposed. The
/// <c>track</c> sink lets a caller collect every chained intermediate and tear
/// the whole chain down in one call.
/// </summary>
public class FluentCommandDisposalTests
{
    [Fact]
    public void Decorators_Are_Disposable_Even_Though_Returned_As_ICommand()
    {
        var inner = RelayCommand.Builder().Task(() => { }).Build();

        var confirm = inner.Confirm(() => Task.FromResult(true));
        var wrap = inner.WrapWith(pre: () => { });
        var precede = inner.PrecedeWith(RelayCommand.Builder().Build());
        var succeed = inner.SucceedWith(RelayCommand.Builder().Build());

        confirm.Should().BeAssignableTo<IDisposable>();
        wrap.Should().BeAssignableTo<IDisposable>();
        precede.Should().BeAssignableTo<IDisposable>();
        succeed.Should().BeAssignableTo<IDisposable>();
    }

    [Fact]
    public void Track_Sink_Collects_Every_Chained_Intermediate()
    {
        var inner = RelayCommand.Builder().Task(() => { }).Build();
        using var bag = new CompositeDisposable();

        // A two-level chain: ConfirmationDecorator wrapped by a DecoratorCommand.
        _ = inner.Confirm(() => Task.FromResult(true), track: bag).WrapWith(track: bag);

        bag.Count.Should().Be(2, "both chained decorators registered themselves in the sink");
    }

    [Fact]
    public void Disposing_The_Track_Sink_Tears_Down_The_Whole_Chain()
    {
        using var trigger = new Subject<Unit>();
        var inner = RelayCommand.Builder()
            .Task(() => { })
            .Predicate(() => true)
            .Triggers(trigger)
            .Build();

        var bag = new CompositeDisposable();
        var outer = inner.Confirm(() => Task.FromResult(true), track: bag).WrapWith(track: bag);

        var raised = 0;
        outer.CanExecuteChanged += (_, _) => raised++;

        // Chain intact: the base command's trigger propagates up to the outer.
        trigger.OnNext(Unit.Default);
        raised.Should().BeGreaterThan(0, "the decorator chain forwards CanExecuteChanged");

        // Dispose every intermediate via the sink — each detaches from its inner.
        bag.Dispose();

        raised = 0;
        trigger.OnNext(Unit.Default);
        raised.Should().Be(0, "after disposing the sink the chain is detached and no longer leaks events");

        ((IDisposable)inner).Dispose();
    }
}
