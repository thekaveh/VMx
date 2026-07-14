using System.Reactive.Linq;
using FluentAssertions;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

public sealed class FORM_030_SetModelHubPublicationTests
{
    private sealed record Model(string Value);

    private sealed class SignalingHub(IMessageHub inner, Action<IMessage> beforeSend) : IMessageHub
    {
        public IObservable<IMessage> Messages => inner.Messages;

        public void Send<TMessage>(TMessage message) where TMessage : IMessage
        {
            beforeSend(message);
            inner.Send(message);
        }
    }

    [Fact]
    [Trait("Conformance", "FORM-030")]
    public async Task FORM_030_SetModel_Publishes_One_Settled_Hub_Message()
    {
        var trace = new List<string>();
        var hub = new MessageHub();
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                trace.Add("validate");
                return string.IsNullOrEmpty(model.Value) ? "required" : null;
            },
        };
        using var form = new FormVM<Model>(
            new Model(""),
            _ => Task.CompletedTask,
            hub: hub,
            strict: true,
            snapshotter: model => model,
            validators: validators);
        trace.Clear();

        using var errorsSubscription = form.ErrorsChanged.Subscribe(_ => trace.Add("errors"));
        form.ApproveCommand.CanExecuteChanged += (_, _) => trace.Add("can_execute");

        var observed = new List<(string Value, bool IsValid, bool CanApprove)>();
        var reentered = false;
        using var hubSubscription = hub.Messages
            .OfType<PropertyChangedMessage<FormVM<Model>>>()
            .Where(message => ReferenceEquals(message.Sender, form) && message.PropertyName == "Model")
            .Subscribe(_ =>
            {
                observed.Add((form.Model.Value, form.IsValid, form.ApproveCommand.CanExecute(null)));
                trace.Add("model");
                if (!reentered)
                {
                    reentered = true;
                    form.SetModel(new Model("nested"));
                }
            });

        form.SetModel(new Model("outer"));

        observed.Should().Equal(
            ("outer", true, true),
            ("nested", true, true));
        trace.Should().Equal(
            "validate", "errors", "can_execute", "model",
            "validate", "model");

        var retained = form.Model;
        var traceBeforeEqual = trace.Count;
        form.SetModel(new Model("nested"));
        form.Model.Should().BeSameAs(retained, "an equal candidate is a complete no-op");
        trace.Should().HaveCount(traceBeforeEqual);

        form.Dispose();
        var traceAfterDispose = trace.Count;
        form.SetModel(new Model("late"));
        form.Model.Should().BeSameAs(retained);
        trace.Should().HaveCount(traceAfterDispose);

        using var nullHubForm = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: null,
            snapshotter: model => model);
        nullHubForm.SetModel(new Model("changed"));
        nullHubForm.Model.Value.Should().Be("changed");

        var denyHub = new MessageHub();
        var denyMessages = new List<IMessage>();
        using var denySubscription = denyHub.Messages.Subscribe(denyMessages.Add);
        using var denyForm = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: denyHub,
            snapshotter: model => model);
        denyForm.SetModel(new Model("changed"));
        denyMessages.Clear();
        denyForm.DenyCommand.Execute(null);
        denyMessages.Should().HaveCount(2);
        denyMessages[0].Should().BeOfType<FormRevertedMessage>();
        denyMessages[1].Should().BeOfType<PropertyChangedMessage<FormVM<Model>>>()
            .Which.PropertyName.Should().Be("Model");

        var resetHub = new MessageHub();
        var resetMessages = new List<IMessage>();
        using var resetSubscription = resetHub.Messages.Subscribe(resetMessages.Add);
        using var resetForm = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: resetHub,
            snapshotter: model => model,
            resetOnApproved: _ => new Model("reset"));
        resetForm.SetModel(new Model("saved"));
        resetMessages.Clear();

        await resetForm.ApproveAsync();

        resetForm.Model.Value.Should().Be("reset");
        resetMessages.OfType<PropertyChangedMessage<FormVM<Model>>>()
            .Where(message => message.PropertyName == "Model")
            .Should().BeEmpty("approval reset keeps its existing non-hub outcome contract");
    }

    [Fact]
    public async Task Admitted_SetModel_Finishes_Before_Concurrent_Dispose()
    {
        using var releaseValidation = new ManualResetEventSlim();
        var validationEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var disposeFinished = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model =>
            {
                if (model.Value == "accepted")
                {
                    validationEntered.SetResult();
                    releaseValidation.Wait(TimeSpan.FromSeconds(1)).Should().BeTrue();
                }

                return null;
            },
        };
        var form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            snapshotter: model => model,
            validators: validators);

        var setter = Task.Run(() => form.SetModel(new Model("accepted")));
        await validationEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));

        var disposer = Task.Run(() =>
        {
            form.Dispose();
            disposeFinished.SetResult();
        });
        var disposedDuringValidation = await Task.WhenAny(
            disposeFinished.Task,
            Task.Delay(TimeSpan.FromMilliseconds(100))) == disposeFinished.Task;
        releaseValidation.Set();

        await Task.WhenAll(setter, disposer).WaitAsync(TimeSpan.FromSeconds(1));
        disposedDuringValidation.Should().BeFalse();
        form.Model.Should().Be(new Model("accepted"));
    }

    [Fact]
    public void Validator_Observes_The_Accepted_Live_Model()
    {
        FormVM<Model>? form = null;
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = candidate =>
            {
                if (candidate.Value == "accepted")
                    form!.Model.Should().Be(candidate);
                return null;
            },
        };
        form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            snapshotter: model => model,
            validators: validators);

        form.SetModel(new Model("accepted"));

        form.Model.Should().Be(new Model("accepted"));
    }

    [Fact]
    public void Admitted_SetModel_Completes_When_Validator_Disposes_Reentrantly()
    {
        using var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var subscription = hub.Messages.Subscribe(messages.Add);
        FormVM<Model>? form = null;
        var validators = new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = candidate =>
            {
                if (candidate.Value == "accepted") form!.Dispose();
                return null;
            },
        };
        form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: hub,
            snapshotter: model => model,
            validators: validators);

        form.SetModel(new Model("accepted"));
        form.SetModel(new Model("late"));

        form.Model.Should().Be(new Model("accepted"));
        messages.OfType<PropertyChangedMessage<FormVM<Model>>>().Should().ContainSingle();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Form_Mutation_Does_Not_Hold_Gate_While_Waiting_For_Hub_Delivery(bool deny)
    {
        var innerHub = new MessageHub();
        var blockerSender = new object();
        using var releaseBlocker = new ManualResetEventSlim();
        var blockerEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var formSendStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var reentryFinished = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var armed = false;
        var proxyHub = new SignalingHub(innerHub, message =>
        {
            if (armed && ((deny && message is FormRevertedMessage) ||
                (!deny && message is PropertyChangedMessage<FormVM<Model>>)))
                formSendStarted.TrySetResult();
        });
        FormVM<Model>? form = null;
        using var subscription = innerHub.Messages.Subscribe(message =>
        {
            if (message is not FormRevertedMessage reverted ||
                !ReferenceEquals(reverted.Sender, blockerSender)) return;
            blockerEntered.SetResult();
            releaseBlocker.Wait(TimeSpan.FromSeconds(1)).Should().BeTrue();
            form!.SetModel(new Model("nested"));
            reentryFinished.SetResult();
        });
        form = new FormVM<Model>(
            new Model("initial"),
            _ => Task.CompletedTask,
            hub: proxyHub,
            snapshotter: model => model);
        if (deny) form.SetModel(new Model("dirty"));
        armed = true;

        var blocker = Task.Run(() => innerHub.Send(new FormRevertedMessage(blockerSender, "blocker")));
        await blockerEntered.Task.WaitAsync(TimeSpan.FromSeconds(1));
        var mutator = Task.Run(() =>
        {
            if (deny)
                form.DenyCommand.Execute(null);
            else
                form.SetModel(new Model("outer"));
        });
        await formSendStarted.Task.WaitAsync(TimeSpan.FromSeconds(1));
        releaseBlocker.Set();

        var reenteredWithoutDeadlock = await Task.WhenAny(
            reentryFinished.Task,
            Task.Delay(TimeSpan.FromMilliseconds(100))) == reentryFinished.Task;
        if (!reenteredWithoutDeadlock) innerHub.Dispose();
        await Task.WhenAll(mutator, blocker).WaitAsync(TimeSpan.FromSeconds(1));
        if (reenteredWithoutDeadlock) innerHub.Dispose();

        reenteredWithoutDeadlock.Should().BeTrue();
    }
}
