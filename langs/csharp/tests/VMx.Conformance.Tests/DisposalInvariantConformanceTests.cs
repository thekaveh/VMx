using System.Reactive.Linq;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Capabilities;
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
    private sealed class OwnedHookVM : ComponentVMBase
    {
        public int OwnedCleanups;
        public int DisposeHooks;

        public OwnedHookVM(string name, TestHub hub, TestDispatcher dispatcher)
            : base(name, "", hub, dispatcher, null, null)
        {
            Own(() => Interlocked.Increment(ref OwnedCleanups));
        }

        public override ViewModelType Type => ViewModelType.Component;

        protected override void OnDispose() => Interlocked.Increment(ref DisposeHooks);
    }

    [Fact, Trait("Conformance", "DISP-001")]
    public void DISP_001_Repeated_Parent_Dispose_Emits_One_Terminal_Transition_Per_Node()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var child = new OwnedHookVM("child", hub, dispatcher);
        var parent = CompositeVM<OwnedHookVM>.Builder()
            .Name("parent").Services(hub, dispatcher)
            .Children(() => Array.Empty<OwnedHookVM>()).Build();
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
        parent.Status.Should().Be(ConstructionStatus.Disposed);
        child.Status.Should().Be(ConstructionStatus.Disposed);
        child.OwnedCleanups.Should().Be(1, "an owned disposal hook runs at most once");
        child.DisposeHooks.Should().Be(1, "the OnDispose hook runs at most once");
        child.Dispose();
        child.OwnedCleanups.Should().Be(1);
        child.DisposeHooks.Should().Be(1);
    }

    [Fact, Trait("Conformance", "DISP-002")]
    public async Task DISP_002_Repeated_Async_Command_Dispose_Cancels_One_InFlight_Execution()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellations = 0;
        var invocations = 0;
        var command = AsyncRelayCommand.Builder()
            .Task(async token =>
            {
                Interlocked.Increment(ref invocations);
                started.TrySetResult();
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

        var errorCompletions = 0;
        var errorTerminations = 0;
        var errorValues = 0;
        using var errorsSub = command.Errors.Subscribe(
            _ => errorValues++,
            _ => errorTerminations++,
            () => errorCompletions++);

        var run = command.ExecuteAsync();
        await started.Task;
        command.IsExecuting.Should().BeTrue();
        command.Dispose();
        command.Dispose();
        await run;

        cancellations.Should().Be(1, "the in-flight operation observes exactly one cancellation");
        command.IsExecuting.Should().BeFalse("the command returns to a non-executing terminal state");
        command.CanExecute(null).Should().BeFalse();

        // Later execution attempts are inert.
        command.Execute(null);
        await command.ExecuteAsync();
        invocations.Should().Be(1, "post-dispose execution never starts the operation");
        cancellations.Should().Be(1);
        command.IsExecuting.Should().BeFalse();

        // No terminal/error channel completes more than once (and the
        // cancellation is not reported as an error).
        command.Dispose();
        errorCompletions.Should().BeLessThanOrEqualTo(1);
        errorTerminations.Should().Be(0);
        errorValues.Should().Be(0);
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
        var persisted = new List<int>();
        var form = new FormVM<int>(1, value => { persisted.Add(value); return Task.CompletedTask; });
        var formCompletions = 0;
        var approvals = new List<int>();
        using var subscription = form.OnApproved.Subscribe(
            approvals.Add,
            () => formCompletions++);
        // The interaction resolves before disposal.
        form.SetModel(2);
        await form.ApproveAsync();
        approvals.Should().Equal(2);
        form.Dispose();
        form.Dispose();
        formCompletions.Should().Be(1);

        // The disposed form keeps its documented inert behavior (spec/20 §10).
        form.SetModel(3);
        form.Model.Should().Be(2, "SetModel on a disposed form is a full no-op");
        form.IsDirty.Should().BeFalse();
        form.DenyCommand.Execute(null);
        form.ApproveCommand.Execute(null);
        await form.ApproveAsync();
        persisted.Should().Equal([2], "a disposed form never invokes the persister");
        approvals.Should().Equal(2);
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

        var expansion = new ExpandableState(initiallyExpanded: false);
        expansion.Dispose();
        expansion.Expand();
        expansion.Collapse();
        expansion.ToggleExpansion();
        expansion.IsExpanded.Should().BeFalse();
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
