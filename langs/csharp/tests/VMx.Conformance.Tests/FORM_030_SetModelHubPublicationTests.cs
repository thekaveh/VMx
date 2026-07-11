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
}
