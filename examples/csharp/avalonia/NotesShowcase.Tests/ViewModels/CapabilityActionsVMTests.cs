using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Commands;
using VMx.Notifications;
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

    // ── Round-3 Critical-1 parity: capability-bar Delete reuses
    // NoteVM.DeleteCommand (the wrapped ConfirmationDecoratorCommand) so the
    // action-bar Delete cancels on "No" and fires the "Note deleted"
    // notification on "Yes" — identical behaviour to the in-list delete
    // button. Mirrors Py / TS tests of the same name.

    private static NoteVM NoteWithConfirm(bool confirmResult, INotificationHub? nh = null, Action<NoteVM>? onDelete = null)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var model = new NoteModel("n-cap", "nb-cap", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var builder = NoteVM.Builder()
            .Name("note:cap").Services(hub, dispatcher).Model(model)
            .OnDelete(onDelete ?? (_ => { }))
            .ConfirmDelete(_ => Task.FromResult(confirmResult));
        if (nh is not null) builder = builder.NotificationHub(nh);
        var vm = builder.Build();
        vm.Construct();
        return vm;
    }

    [Fact]
    public async Task Capability_bar_Delete_reuses_note_DeleteCommand_confirm_false_does_NOT_delete()
    {
        var deleted = new List<bool>();
        var note = NoteWithConfirm(confirmResult: false, onDelete: _ => deleted.Add(true));
        Assert.IsType<ConfirmationDecoratorCommand>(note.DeleteCommand);
        var caps = Build(() => note);
        var delete = caps.Actions.Value.First(a => a.Label == "Delete");
        // Same wrapped reference (parity contract with Py / TS).
        Assert.Same(note.DeleteCommand, delete.Command);
        await ((ConfirmationDecoratorCommand)delete.Command).ExecuteAsync(null);
        Assert.Empty(deleted);
    }

    [Fact]
    public async Task Capability_bar_Delete_with_confirm_true_invokes_OnDelete_and_publishes_notification()
    {
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snap =>
        {
            foreach (var n in snap) if (!observed.Contains(n)) observed.Add(n);
        });
        var deleted = new List<bool>();
        var note = NoteWithConfirm(confirmResult: true, nh: notificationHub,
            onDelete: _ => deleted.Add(true));
        var caps = Build(() => note);
        var delete = caps.Actions.Value.First(a => a.Label == "Delete");
        await ((ConfirmationDecoratorCommand)delete.Command).ExecuteAsync(null);
        Assert.Single(deleted);
        Assert.Contains(observed, n => n.Message.Contains("Note deleted"));
    }
}
