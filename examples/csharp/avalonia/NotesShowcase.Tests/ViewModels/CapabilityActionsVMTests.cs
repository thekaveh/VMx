using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class CapabilityActionsVMTests
{
    private static CapabilityActionsVM Build(Func<object?> getter)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var vm = CapabilityActionsVM.Builder()
            .Name("caps").Services(hub, dispatcher).FocusedGetter(getter).Build();
        vm.Construct();
        return vm;
    }

    private static NotebookVM SampleNotebook()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var vm = NotebookVM.Builder()
            .Name("nb").Services(hub, dispatcher)
            .Model(new NotebookModel("nb-1", "Work", null))
            .Build();
        vm.Construct();
        return vm;
    }

    private static NoteVM SampleNote()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var model = new NoteModel("n-1", "nb-1", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model).Build();
        vm.Construct();
        return vm;
    }

    [Fact]
    public void Notebook_in_focus_yields_Expand_Collapse_Toggle_Select_actions()
    {
        var nb = SampleNotebook();
        var vm = Build(() => nb);
        var labels = vm.Actions.Value.Select(a => a.Label).ToList();
        Assert.Contains("Expand", labels);
        Assert.Contains("Collapse", labels);
        Assert.Contains("Toggle Expansion", labels);
        Assert.Contains("Select", labels);
        // No note-specific actions.
        Assert.DoesNotContain("Close", labels);
        Assert.DoesNotContain("Delete", labels);
    }

    [Fact]
    public void Note_in_focus_yields_Close_Save_Delete_Select_actions()
    {
        var note = SampleNote();
        var vm = Build(() => note);
        var labels = vm.Actions.Value.Select(a => a.Label).ToList();
        Assert.Contains("Close", labels);
        Assert.Contains("Save", labels);
        Assert.Contains("Delete", labels);
        Assert.Contains("Select", labels);
        // No notebook expansion actions.
        Assert.DoesNotContain("Expand", labels);
    }

    [Fact]
    public void Null_focus_yields_empty_actions()
    {
        var vm = Build(() => null);
        Assert.Empty(vm.Actions.Value);
    }

    [Fact]
    public void RecomputeActions_picks_up_focus_change()
    {
        object? focused = SampleNotebook();
        var vm = Build(() => focused);
        Assert.Contains("Expand", vm.Actions.Value.Select(a => a.Label));
        focused = SampleNote();
        vm.RecomputeActions();
        Assert.Contains("Close", vm.Actions.Value.Select(a => a.Label));
        Assert.DoesNotContain("Expand", vm.Actions.Value.Select(a => a.Label));
    }

    [Fact]
    public void Each_action_CanExecute_follows_underlying_predicate()
    {
        var nb = SampleNotebook(); // initially collapsed
        var vm = Build(() => nb);
        var expand = vm.Actions.Value.First(a => a.Label == "Expand");
        var collapse = vm.Actions.Value.First(a => a.Label == "Collapse");
        Assert.True(expand.Command.CanExecute(null));
        Assert.False(collapse.Command.CanExecute(null));
        nb.Expand();
        // Stale actions reflect the old predicate snapshot — by spec §14.4 the
        // host re-projects on focus changes; here we re-project to confirm
        // the new state is captured.
        vm.RecomputeActions();
        var collapse2 = vm.Actions.Value.First(a => a.Label == "Collapse");
        Assert.True(collapse2.Command.CanExecute(null));
    }
}
