using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
using VMx.Components;
using VMx.Commands;
using VMx.Messages;
using VMx.Notifications;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NoteVMTests
{
    private static (NoteVM vm, MessageHub hub) Build(string title = "Hello", bool starred = false)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        var model = new NoteModel(
            Id: "note-01",
            NotebookId: "nb-reviews",
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
        return (vm, hub);
    }

    [Fact]
    public void Capability_set_is_exactly_the_five_declared_interfaces()
    {
        var (vm, _) = Build();
        Assert.IsAssignableFrom<ISelectable>(vm);
        Assert.IsAssignableFrom<IClosable>(vm);
        Assert.IsAssignableFrom<IDeletable<NoteVM>>(vm);
        Assert.IsAssignableFrom<ISavable<NoteVM>>(vm);
        Assert.IsAssignableFrom<IReconstructable>(vm);
        // Capabilities NOT applicable to a note:
        Assert.IsNotAssignableFrom<IExpandable>(vm);
        Assert.IsNotAssignableFrom<INewCreatable>(vm);
    }

    [Fact]
    public void Modeled_Title_change_publishes_Title_PropertyChangedMessage()
    {
        var (vm, hub) = Build(title: "Old");
        vm.Construct();
        var observed = new List<string>();
        using var sub = hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Subscribe(m => observed.Add(m.PropertyName));

        vm.Model = vm.Model with { Title = "New" };

        Assert.Contains(nameof(NoteVM.Title), observed);
        Assert.Contains(nameof(NoteVM.Model), observed);
        Assert.Equal("New", vm.Title);
    }

    [Fact]
    public void Modeled_Starred_change_publishes_Starred_PropertyChangedMessage()
    {
        var (vm, hub) = Build(starred: false);
        vm.Construct();
        var observed = new List<string>();
        using var sub = hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Subscribe(m => observed.Add(m.PropertyName));

        vm.Model = vm.Model with { Starred = true };

        Assert.Contains(nameof(NoteVM.Starred), observed);
    }

    [Fact]
    public void CloseCommand_invokes_OnClose_callback_with_self()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        NoteVM? closed = null;
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnClose(n => closed = n)
            .Build();
        vm.Construct();

        vm.CloseCommand.Execute(null);

        Assert.Same(vm, closed);
    }

    [Fact]
    public void SaveCommand_invokes_OnSave_callback()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        NoteVM? saved = null;
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnSave(n => saved = n)
            .Build();
        vm.Construct();

        vm.SaveCommand.Execute(null);

        Assert.Same(vm, saved);
    }

    [Fact]
    public void DeleteCommand_invokes_OnDelete_callback()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        NoteVM? deleted = null;
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnDelete(n => deleted = n)
            .Build();
        vm.Construct();

        vm.DeleteCommand.Execute(null);

        Assert.Same(vm, deleted);
    }

    [Fact]
    public void Predicates_reject_when_not_constructed()
    {
        var (vm, _) = Build();
        // Pre-construct: Constructed status is false → cannot close/save/delete.
        Assert.False(vm.CanClose());
        Assert.False(vm.CanSave(vm));
        Assert.False(vm.CanDelete(vm));
    }

    // ── Audit pass #1, B1: DeleteCommand wraps in ConfirmationDecoratorCommand ──

    [Fact]
    public async Task DeleteCommand_with_confirm_returning_false_does_NOT_invoke_OnDelete()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        NoteVM? deleted = null;
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnDelete(n => deleted = n)
            .ConfirmDelete(_ => Task.FromResult(false))   // user clicks "No"
            .Build();
        vm.Construct();

        Assert.IsType<ConfirmationDecoratorCommand>(vm.DeleteCommand);
        await ((ConfirmationDecoratorCommand)vm.DeleteCommand).ExecuteAsync(null);

        Assert.Null(deleted);   // delete was rejected by the confirm gate
    }

    [Fact]
    public async Task DeleteCommand_with_confirm_returning_true_invokes_OnDelete()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        NoteVM? deleted = null;
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnDelete(n => deleted = n)
            .ConfirmDelete(_ => Task.FromResult(true))    // user clicks "Yes"
            .Build();
        vm.Construct();

        Assert.IsType<ConfirmationDecoratorCommand>(vm.DeleteCommand);
        await ((ConfirmationDecoratorCommand)vm.DeleteCommand).ExecuteAsync(null);

        Assert.Same(vm, deleted);
    }

    // ── Audit pass #1, B2: NoteVM publishes "Note deleted" notification ──

    [Fact]
    public async Task DeleteCommand_publishes_Note_deleted_notification_on_success()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot) if (!observed.Contains(n)) observed.Add(n);
        });
        var model = new NoteModel("n", "nb", "Important", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnDelete(_ => { })
            .ConfirmDelete(_ => Task.FromResult(true))
            .NotificationHub(notificationHub)
            .Build();
        vm.Construct();

        await ((ConfirmationDecoratorCommand)vm.DeleteCommand).ExecuteAsync(null);

        Assert.Contains(observed, n => n.Message.Contains("Note deleted") && n.Message.Contains("Important"));
    }

    [Fact]
    public async Task DeleteCommand_does_NOT_publish_notification_when_confirm_returns_false()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot) if (!observed.Contains(n)) observed.Add(n);
        });
        var model = new NoteModel("n", "nb", "T", Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder()
            .Name("note").Services(hub, dispatcher).Model(model)
            .OnDelete(_ => { })
            .ConfirmDelete(_ => Task.FromResult(false))
            .NotificationHub(notificationHub)
            .Build();
        vm.Construct();

        await ((ConfirmationDecoratorCommand)vm.DeleteCommand).ExecuteAsync(null);

        Assert.DoesNotContain(observed, n => n.Message.Contains("Note deleted"));
    }
}
