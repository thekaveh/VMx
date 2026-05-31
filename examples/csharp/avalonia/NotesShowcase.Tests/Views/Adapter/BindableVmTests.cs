using System.ComponentModel;
using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views.Adapter;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.Views.Adapter;

/// <summary>
/// Adapter contract (plan §4.a, scenario §7.1 PropertyBridge): given a VM that
/// publishes <see cref="PropertyChangedMessage{TSender}"/> to a hub,
/// <see cref="BindableVm"/> raises <see cref="INotifyPropertyChanged.PropertyChanged"/>
/// for the same property name. Subscriptions are released on <see cref="IDisposable.Dispose"/>.
/// </summary>
public sealed class BindableVmTests
{
    private static (NoteVM vm, MessageHub hub) BuildNoteVm(string title = "Hello", bool starred = false)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var model = new NoteModel(
            Id: "note-01",
            NotebookId: "nb",
            Title: title,
            Tags: Array.Empty<string>(),
            Body: "",
            Starred: starred,
            CreatedAt: DateTimeOffset.UtcNow,
            UpdatedAt: DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note")
            .Services(hub, dispatcher)
            .Model(model)
            .Build();
        vm.Construct();
        return (vm, hub);
    }

    [Fact]
    public void Raises_PropertyChanged_when_source_VM_publishes_PropertyChangedMessage()
    {
        var (vm, hub) = BuildNoteVm(title: "Old");
        using var bindable = new BindableVm(vm, hub);
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        vm.Model = vm.Model with { Title = "New" };

        Assert.Contains(nameof(NoteVM.Title), observed);
        Assert.Contains(nameof(NoteVM.Model), observed);
    }

    [Fact]
    public void Exposes_the_source_VM_as_the_DataContext_target()
    {
        var (vm, hub) = BuildNoteVm();
        using var bindable = new BindableVm(vm, hub);

        // BindableVm is an INPC sidecar — the source VM is the actual binding target
        // (consumers set DataContext = vm and route INPC through bindable when needed).
        Assert.Same(vm, bindable.Source);
    }

    [Fact]
    public void Ignores_PropertyChangedMessage_whose_source_is_a_different_VM()
    {
        var (vm1, hub) = BuildNoteVm(title: "VM1");
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var vm2 = NoteVM.Builder()
            .Name("other")
            .Services(hub, dispatcher)
            .Model(new NoteModel("n2", "nb", "T", Array.Empty<string>(), "", false,
                DateTimeOffset.UtcNow, DateTimeOffset.UtcNow))
            .Build();
        vm2.Construct();

        using var bindable = new BindableVm(vm1, hub);
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        // Mutate vm2 — bindable wraps vm1 and must NOT see vm2 messages.
        vm2.Model = vm2.Model with { Title = "Changed" };

        Assert.Empty(observed);
    }

    [Fact]
    public void Dispose_releases_subscription_and_stops_raising_PropertyChanged()
    {
        var (vm, hub) = BuildNoteVm();
        var bindable = new BindableVm(vm, hub);
        var observed = new List<string?>();
        bindable.PropertyChanged += (_, e) => observed.Add(e.PropertyName);

        bindable.Dispose();

        vm.Model = vm.Model with { Title = "After-dispose" };

        Assert.Empty(observed);
    }

    [Fact]
    public void Dispose_is_idempotent()
    {
        var (vm, hub) = BuildNoteVm();
        var bindable = new BindableVm(vm, hub);
        bindable.Dispose();
        bindable.Dispose(); // second call must not throw
    }
}
