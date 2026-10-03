using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using System.Reactive.Subjects;
using System.Reflection;
using FluentAssertions;
using Microsoft.Reactive.Testing;
using VMx.Capabilities;
using VMx.Notifications;
using VMx.Properties;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// #538: teardown runs every step when one throws, then rethrows the first
/// failure, as <c>FormVM</c> and <c>TokenPagedComposition</c> already do. A second
/// <c>Dispose()</c> stays a no-op. Flavor-local repair; no new conformance ID.
/// </summary>
public class TeardownStepIsolationTests
{
    private static bool SubjectIsDisposed(object owner, string field)
    {
        var subject = owner.GetType().GetField(field, BindingFlags.Instance | BindingFlags.NonPublic)
            ?.GetValue(owner)
            ?? throw new InvalidOperationException($"{owner.GetType().Name}.{field} was not found.");
        return (bool)subject.GetType().GetProperty("IsDisposed")!.GetValue(subject)!;
    }

    [Fact]
    public void DerivedProperty_Disposes_Its_Subject_When_A_Completion_Observer_Throws()
    {
        var sut = DerivedProperty.From(new Subject<int>(), value => value);
        var boom = new InvalidOperationException("boom");
        sut.ValueChanged.Subscribe(_ => { }, () => throw boom);

        var act = () => sut.Dispose();

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(boom);
        SubjectIsDisposed(sut, "_changes").Should().BeTrue("the step after the failing one still runs");
        sut.Invoking(s => s.Dispose()).Should().NotThrow("a second Dispose is a no-op");
    }

    [Fact]
    public void SearchableState_Finishes_Every_Subject_When_A_Completion_Observer_Throws()
    {
        var sut = new SearchableState<string>(() => ["a"], (_, _) => true, TimeSpan.Zero);
        var boom = new InvalidOperationException("boom");
        sut.Filtered.Subscribe(_ => { }, () => throw boom);

        var act = () => sut.Dispose();

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(boom);
        SubjectIsDisposed(sut, "_termSubject").Should().BeTrue();
        SubjectIsDisposed(sut, "_filteredSubject").Should().BeTrue("the step after the failing one still runs");
        SubjectIsDisposed(sut, "_forceSearchSubject").Should().BeTrue("later steps still run");
        sut.Invoking(s => s.Dispose()).Should().NotThrow("a second Dispose is a no-op");
    }

    // Every disposable the scheduler hands out throws on disposal, so the
    // notification's own teardown fails at its first step (the lifespan timer).
    private sealed class ThrowingDisposalScheduler(IScheduler inner, Exception failure) : IScheduler
    {
        public DateTimeOffset Now => inner.Now;

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
            => Throwing(inner.Schedule(state, action));

        public IDisposable Schedule<TState>(
            TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
            => Throwing(inner.Schedule(state, dueTime, action));

        public IDisposable Schedule<TState>(
            TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => Throwing(inner.Schedule(state, dueTime, action));

        private IDisposable Throwing(IDisposable scheduled) => Disposable.Create(() =>
        {
            scheduled.Dispose();
            throw failure;
        });
    }

    [Fact]
    public void NotificationVM_Disposes_Its_Command_When_A_Subscription_Disposal_Throws()
    {
        var boom = new InvalidOperationException("boom");
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "note");
        hub.Post(notification);
        var sut = new NotificationVM(
            notification, hub, new ThrowingDisposalScheduler(new TestScheduler(), boom),
            TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(1));
        sut.DismissCommand.CanExecute(null).Should().BeTrue();

        var act = () => sut.Dispose();

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(boom);
        sut.DismissCommand.CanExecute(null).Should().BeFalse("the command is disposed after the failing step");
        sut.Invoking(s => s.Dispose()).Should().NotThrow("a second Dispose is a no-op");
    }

    [Fact]
    public void ConfirmationVM_Disposes_Its_Commands_When_The_Base_Teardown_Throws()
    {
        var boom = new InvalidOperationException("boom");
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Confirmation, "confirm");
        hub.Post(notification);
        var sut = new ConfirmationVM(
            notification, hub, new ThrowingDisposalScheduler(new TestScheduler(), boom),
            TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(1));
        sut.ApproveCommand.CanExecute(null).Should().BeTrue();
        sut.RejectCommand.CanExecute(null).Should().BeTrue();

        var act = () => sut.Dispose();

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(boom);
        sut.DismissCommand.CanExecute(null).Should().BeFalse();
        sut.ApproveCommand.CanExecute(null).Should().BeFalse("the commands are disposed even when the base throws");
        sut.RejectCommand.CanExecute(null).Should().BeFalse();
        sut.Invoking(s => s.Dispose()).Should().NotThrow("a second Dispose is a no-op");
    }
}
