using System.Reactive.Linq;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Collections;
using VMx.Commands;
using VMx.Components;
using VMx.Composites;
using VMx.Dialogs;
using VMx.Forms;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Notifications;
using VMx.Properties;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>Cross-cutting disposal invariant (DISP-001..006).</summary>
public class DisposalInvariantConformanceTests
{
    [Fact, Trait("Conformance", "DISP-001")]
    public void DISP_001_Repeated_Parent_Dispose_Emits_One_Terminal_Transition_Per_Node()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = ComponentVM<string>.Builder()
            .Name("child").Services(hub, dispatcher).Model("m").Build();
        var parent = CompositeVM<ComponentVM<string>>.Builder()
            .Name("parent").Services(hub, dispatcher)
            .Children(() => Array.Empty<ComponentVM<string>>()).Build();
        parent.Add(child);
        var disposed = new List<string>();
        hub.Messages.Subscribe(message =>
        {
            if (message is ConstructionStatusChangedMessage change &&
                change.Status == ConstructionStatus.Disposed)
                disposed.Add(change.SenderName);
        });

        parent.Dispose();
        parent.Dispose();

        disposed.Count(name => name == "child").Should().Be(1);
        disposed.Count(name => name == "parent").Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-002")]
    public async Task DISP_002_Repeated_Async_Command_Dispose_Cancels_One_InFlight_Execution()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellations = 0;
        var command = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                started.SetResult();
                try
                {
                    await Task.Delay(Timeout.Infinite, token);
                }
                catch (OperationCanceledException)
                {
                    Interlocked.Increment(ref cancellations);
                    throw;
                }
            })
            .Build();

        var run = command.ExecuteAsync();
        await started.Task;
        command.Dispose();
        command.Dispose();
        await run;

        cancellations.Should().Be(1);
        command.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "DISP-003")]
    public async Task DISP_003_Concurrent_Notification_Hub_Dispose_Completes_Once()
    {
        var hub = new NotificationHub();
        var completions = 0;
        using var subscription = hub.Pending.Subscribe(
            _ => { },
            () => Interlocked.Increment(ref completions));
        var pending = hub.Post(new Notification(NotificationType.Notification, "info"));

        Parallel.For(0, 64, _ => hub.Dispose());

        (await pending).Should().Be(NotificationReaction.Pending);
        completions.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-004")]
    public async Task DISP_004_Interaction_Owners_Complete_Once_And_Preserve_First_Result()
    {
        var form = new FormVM<int>(1, _ => Task.CompletedTask);
        var formCompletions = 0;
        using var subscription = form.OnApproved.Subscribe(
            _ => { },
            () => formCompletions++);
        form.Dispose();
        form.Dispose();
        formCompletions.Should().Be(1);

        var modal = new ModalVM<string>("cancel");
        modal.Dismiss("first");
        modal.Dispose();
        modal.Dispose();
        (await modal.Completion).Should().Be("first");
    }

    [Fact, Trait("Conformance", "DISP-005")]
    public void DISP_005_Reactive_Helper_Dispose_Completes_Once_And_Retains_Last_Value()
    {
        using var source = new BehaviorSubject<int>(7);
        var property = DerivedProperty.From(source, value => value);
        var completions = 0;
        using var subscription = property.ValueChanged.Subscribe(
            _ => { },
            () => completions++);

        property.Dispose();
        property.Dispose();
        source.OnNext(8);

        property.Value.Should().Be(7);
        completions.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-006")]
    public void DISP_006_Batch_Handle_Dispose_Ends_One_Batch_Once()
    {
        var list = new ObservableList<int>();
        var resets = 0;
        list.Reset += (_, _) => resets++;
        var batch = list.BatchUpdate();
        list.Add(1);

        batch.Dispose();
        batch.Dispose();

        resets.Should().Be(1);
    }
}
