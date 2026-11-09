using System.Reactive.Linq;
using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-044 — when a send of the outermost update's queue
/// fails, no later notification of that queue is sent. A nested approval
/// whose persister has not started never calls it and is no longer in
/// flight. The failure propagates from the outermost update after its
/// replays. See spec/20-form-vm.md §5.4 rule 7 and ADR-0216.
/// </summary>
public sealed class FORM_044_FailedQueueSend_Tests
{
    private sealed record Model(string Value);

    // Counts the form's model PropertyChangedMessage sends and fails the
    // first one.
    private sealed class FailingHub : IMessageHub
    {
        public Exception Failure { get; } = new InvalidOperationException("send failed");

        public int ModelMessages { get; private set; }

        public IObservable<IMessage> Messages => Observable.Empty<IMessage>();

        public void Send<TMessage>(TMessage message) where TMessage : IMessage
        {
            if (message is not PropertyChangedMessage<FormVM<Model>> { PropertyName: "Model" }) return;
            if (++ModelMessages == 1) throw Failure;
        }
    }

    private static Dictionary<string, Func<Model, string?>> Validator(Func<Model, string?> validate) =>
        new() { ["Value"] = validate };

    [Fact, Trait("Conformance", "FORM-044")]
    public async Task FORM_044_A_Failed_Send_Stops_The_Queue_And_Releases_A_Nested_Approval()
    {
        FormVM<Model>? form = null;
        var persisted = 0;
        var nestedCalls = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "a" && nestedCalls++ == 0)
            {
                form!.ApproveCommand.Execute(null);
                form.SetModel(new Model("b"));
                form.SetModel(new Model("c"));
            }
            return null;
        });
        var hub = new FailingHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: m => m,
            validators: validators);
        using var disposeForm = form;
        var approveErrors = new List<Exception>();
        using var errorsSubscription = form.ApproveErrors.Subscribe(approveErrors.Add);
        var canExecuteChanged = 0;
        form.ApproveCommand.CanExecuteChanged += (_, _) => canExecuteChanged++;

        var act = () => form.SetModel(new Model("a"));

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(hub.Failure);
        await Task.Delay(TimeSpan.FromMilliseconds(100));
        hub.ModelMessages.Should().Be(1, "the send of c's model message never runs");
        canExecuteChanged.Should().Be(2, "the admission edge was sent, so the release edge follows");
        Volatile.Read(ref persisted).Should().Be(0, "the released approval never calls its persister");
        approveErrors.Should().BeEmpty();
        form.ApproveCommand.CanExecute(null).Should().BeTrue("the approval is no longer in flight");
        form.Model.Should().Be(new Model("c"), "the nested updates committed at once");
    }

    [Fact, Trait("Conformance", "FORM-044")]
    public async Task FORM_044_A_Released_Nested_ApproveAsync_Completes_Normally()
    {
        FormVM<Model>? form = null;
        Task? approval = null;
        var persisted = 0;
        var validators = Validator(model =>
        {
            if (model.Value == "a" && approval is null)
            {
                approval = form!.ApproveAsync();
                form.SetModel(new Model("b"));
            }
            return null;
        });
        var hub = new FailingHub();
        form = new FormVM<Model>(
            new Model("initial"),
            _ =>
            {
                Interlocked.Increment(ref persisted);
                return Task.CompletedTask;
            },
            hub: hub,
            snapshotter: m => m,
            validators: validators);
        using var disposeForm = form;

        var act = () => form.SetModel(new Model("a"));

        act.Should().Throw<InvalidOperationException>().Which.Should().BeSameAs(hub.Failure);
        approval.Should().NotBeNull();
        await approval!.WaitAsync(HangGuard);
        approval.IsCompletedSuccessfully.Should().BeTrue();
        Volatile.Read(ref persisted).Should().Be(0);
        form.ApproveCommand.CanExecute(null).Should().BeTrue();
    }
}
