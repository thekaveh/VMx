using System.ComponentModel;
using FluentAssertions;
using VMx.Components;
using VMx.Forms;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

public class PostDisposeModeledAssignmentConformanceTests
{
    private sealed class CountingModel(int value, Action onEquals) : IEquatable<CountingModel>
    {
        public int Value { get; } = value;

        public bool Equals(CountingModel? other)
        {
            onEquals();
            return other is not null && Value == other.Value;
        }

        public override bool Equals(object? obj) => obj is CountingModel other && Equals(other);

        public override int GetHashCode() => Value;
    }

    private sealed record FormModel(string Name);

    [Fact, Trait("Conformance", "DISP-014")]
    public void DISP_014_Modeled_Assignment_After_Disposal_Is_Inert()
    {
        var componentHub = new TestHub();
        var equalityCalls = 0;
        var hinterCalls = 0;
        var callbackCalls = 0;
        var initial = new CountingModel(1, () => equalityCalls++);
        var replacement = new CountingModel(2, () => equalityCalls++);
        var component = ComponentVM<CountingModel>.Builder()
            .Name("component")
            .Services(componentHub, new TestDispatcher())
            .Model(initial)
            .ModeledHinter(model =>
            {
                hinterCalls++;
                return $"hint:{model.Value}";
            })
            .OnModelChanged(_ => callbackCalls++)
            .Build();
        var localChanges = new List<string?>();
        ((INotifyPropertyChanged)component).PropertyChanged +=
            (_, args) => localChanges.Add(args.PropertyName);
        var componentHubChanges = new List<IMessage>();
        componentHub.Messages.Subscribe(componentHubChanges.Add);

        component.Dispose();
        equalityCalls = 0;
        hinterCalls = 0;
        callbackCalls = 0;
        localChanges.Clear();
        componentHubChanges.Clear();
        Action lateComponentCompletion = () => component.Model = replacement;

        lateComponentCompletion();

        component.Model.Should().BeSameAs(initial);
        component.ModeledHint.Should().Be("hint:1");
        equalityCalls.Should().Be(0);
        hinterCalls.Should().Be(0);
        callbackCalls.Should().Be(0);
        localChanges.Should().BeEmpty();
        componentHubChanges.Should().BeEmpty();

        var formHub = new TestHub();
        var validatorCalls = 0;
        var form = new FormVM<FormModel>(
            new FormModel("valid"),
            _ => Task.CompletedTask,
            hub: formHub,
            strict: true,
            validators: new Dictionary<string, Func<FormModel, string?>>
            {
                ["Name"] = model =>
                {
                    validatorCalls++;
                    return string.IsNullOrEmpty(model.Name) ? "required" : null;
                },
            });
        var initialFormModel = form.Model;
        var initialSnapshot = form.Snapshot;
        var initialErrors = form.Errors.ToDictionary(pair => pair.Key, pair => pair.Value);
        var initialDirty = form.IsDirty;
        var errorsSignals = 0;
        var commandSignals = 0;
        var formHubChanges = new List<IMessage>();
        form.ErrorsChanged.Subscribe(_ => errorsSignals++);
        form.ApproveCommand.CanExecuteChanged += (_, _) => commandSignals++;
        formHub.Messages.Subscribe(formHubChanges.Add);

        form.Dispose();
        validatorCalls = 0;
        errorsSignals = 0;
        commandSignals = 0;
        formHubChanges.Clear();
        Action lateFormCompletion = () => form.SetModel(new FormModel(""));

        lateFormCompletion();
        Action lateNullFormCompletion = () => form.SetModel(null!);

        form.Model.Should().Be(initialFormModel);
        form.Snapshot.Should().Be(initialSnapshot);
        form.Errors.Should().BeEquivalentTo(initialErrors);
        form.IsDirty.Should().Be(initialDirty);
        form.IsValid.Should().BeTrue();
        validatorCalls.Should().Be(0);
        errorsSignals.Should().Be(0);
        commandSignals.Should().Be(0);
        formHubChanges.Should().BeEmpty();
        lateNullFormCompletion.Should().NotThrow(
            "disposal admission precedes candidate null inspection");
    }
}
