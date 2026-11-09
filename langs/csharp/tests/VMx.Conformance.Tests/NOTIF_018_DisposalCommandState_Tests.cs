using FluentAssertions;
using Microsoft.Reactive.Testing;
using System.Windows.Input;
using VMx.Notifications;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: NOTIF-018 — from the start of <c>Dispose()</c>, every
/// command that a <c>NotificationVM</c> or <c>ConfirmationVM</c> owns reports
/// <c>CanExecute == false</c>, also inside disposal notifications. See
/// spec/16-notifications.md §6.2 and ADR-0196.
/// </summary>
public sealed class NOTIF_018_DisposalCommandState_Tests
{
    [Fact, Trait("Conformance", "NOTIF-018")]
    public void NOTIF_018_ConfirmationVM_Commands_Report_False_During_Dispose()
    {
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Confirmation, "confirm?");
        var posted = hub.Post(notification);
        IReadOnlyList<Notification> pending = [];
        using var pendingSubscription = hub.Pending.Subscribe(list => pending = list);
        var vm = new ConfirmationVM(notification, hub, new TestScheduler());
        ICommand[] commands = [vm.DismissCommand, vm.ApproveCommand, vm.RejectCommand];
        var handlerCalls = 0;
        var reads = new List<bool>();
        foreach (var command in commands)
        {
            command.CanExecuteChanged += (_, _) =>
            {
                handlerCalls++;
                foreach (var read in commands) reads.Add(read.CanExecute(null));
                vm.RejectCommand.Execute(null);
            };
        }

        vm.Dispose();

        handlerCalls.Should().BeGreaterThan(0, "disposing the commands raises CanExecuteChanged");
        reads.Should().NotBeEmpty().And.OnlyContain(canExecute => !canExecute);
        vm.IsResolved.Should().BeFalse("disposal does not resolve the notification");
        pending.Should().Contain(notification, "the notification is still pending in the hub");
        posted.IsCompleted.Should().BeFalse("the Post awaitable has not resolved");

        var callsAfterFirstDispose = handlerCalls;
        vm.Dispose();

        handlerCalls.Should().Be(callsAfterFirstDispose, "a second Dispose() raises no notification");
        pending.Should().Contain(notification);
        posted.IsCompleted.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "NOTIF-018")]
    public void NOTIF_018_NotificationVM_DismissCommand_Reports_False_During_Dispose()
    {
        using var hub = new NotificationHub();
        var notification = new Notification(NotificationType.Notification, "hi");
        _ = hub.Post(notification);
        var vm = new NotificationVM(notification, hub, new TestScheduler());
        var reads = new List<bool>();
        vm.DismissCommand.CanExecuteChanged += (_, _) => reads.Add(vm.DismissCommand.CanExecute(null));

        vm.Dispose();

        reads.Should().NotBeEmpty().And.OnlyContain(canExecute => !canExecute);
    }
}
