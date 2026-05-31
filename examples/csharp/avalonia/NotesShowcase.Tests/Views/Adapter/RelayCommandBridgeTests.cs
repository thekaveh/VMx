using System.Reactive;
using System.Reactive.Subjects;
using System.Windows.Input;
using NotesShowcase.Views.Adapter;
using VMx.Commands;
using Xunit;

namespace NotesShowcase.Tests.Views.Adapter;

/// <summary>
/// Adapter contract (plan §4.a, scenario §7.1 CommandBridge): wraps a VMx
/// <see cref="ICommand"/>, forwards <see cref="ICommand.CanExecute"/> / <see cref="ICommand.Execute"/>
/// and re-raises <see cref="ICommand.CanExecuteChanged"/> whenever the source command does.
/// </summary>
public sealed class RelayCommandBridgeTests
{
    [Fact]
    public void Forwards_CanExecute_from_source_command()
    {
        var allow = true;
        var source = RelayCommand.Builder()
            .Predicate(() => allow)
            .Task(() => { })
            .Build();
        using var bridge = new RelayCommandBridge(source);

        Assert.True(bridge.CanExecute(null));
        allow = false;
        Assert.False(bridge.CanExecute(null));
    }

    [Fact]
    public void Forwards_Execute_to_source_command()
    {
        var calls = 0;
        var source = RelayCommand.Builder()
            .Task(() => calls++)
            .Build();
        using var bridge = new RelayCommandBridge(source);

        bridge.Execute(null);

        Assert.Equal(1, calls);
    }

    [Fact]
    public void Reraises_CanExecuteChanged_when_source_publishes_a_trigger()
    {
        // Wire a trigger so CanExecuteChanged on the source fires when the trigger emits.
        var trigger = new Subject<Unit>();
        var source = RelayCommand.Builder()
            .Predicate(() => true)
            .Task(() => { })
            .Triggers(trigger)
            .Build();
        using var bridge = new RelayCommandBridge(source);

        var raised = 0;
        bridge.CanExecuteChanged += (_, _) => raised++;

        trigger.OnNext(Unit.Default);
        trigger.OnNext(Unit.Default);

        Assert.Equal(2, raised);
    }

    [Fact]
    public void Dispose_unsubscribes_from_source_CanExecuteChanged()
    {
        var trigger = new Subject<Unit>();
        var source = RelayCommand.Builder()
            .Predicate(() => true)
            .Task(() => { })
            .Triggers(trigger)
            .Build();
        var bridge = new RelayCommandBridge(source);

        var raised = 0;
        bridge.CanExecuteChanged += (_, _) => raised++;
        bridge.Dispose();

        trigger.OnNext(Unit.Default);

        Assert.Equal(0, raised);
    }

    [Fact]
    public void Constructor_rejects_null_source()
    {
        Assert.Throws<ArgumentNullException>(() => new RelayCommandBridge(null!));
    }
}
