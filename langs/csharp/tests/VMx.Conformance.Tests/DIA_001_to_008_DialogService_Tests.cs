using System.Windows.Input;
using FluentAssertions;
using VMx.Commands;
using VMx.Dialogs;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: DIA-001..DIA-008 — IDialogService (host modal interactions).
/// See spec/19-dialogs.md and ADR-0029.
/// </summary>
public class DIA_001_to_008_DialogService_Tests
{
    // ── DIA-001 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-001: PickFileToOpen — optional filter/title; returns path or null on cancel.</summary>
    [Fact]
    [Trait("Conformance", "DIA-001")]
    public async Task DIA_001_PickFileToOpen_Contract()
    {
        // NullDialogService is a valid IDialogService; it returns null (cancel).
        NullDialogService sut = NullDialogService.Instance;

        // All parameters are optional.
        var r1 = await sut.PickFileToOpen();
        var r2 = await sut.PickFileToOpen(filter: null, title: null);
        var r3 = await sut.PickFileToOpen(
            filter: new FileFilter("Images", ["*.png", "*.jpg"]),
            title: "Open image");

        r1.Should().BeNull();
        r2.Should().BeNull();
        r3.Should().BeNull();
    }

    // ── DIA-002 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-002: PickFileToSave — optional filter/title/suggestedName; returns path or null.</summary>
    [Fact]
    [Trait("Conformance", "DIA-002")]
    public async Task DIA_002_PickFileToSave_Contract()
    {
        NullDialogService sut = NullDialogService.Instance;

        var r1 = await sut.PickFileToSave();
        var r2 = await sut.PickFileToSave(filter: null, title: null, suggestedName: null);
        var r3 = await sut.PickFileToSave(
            filter: new FileFilter("Text files", ["*.txt"]),
            title: "Save as",
            suggestedName: "output.txt");

        r1.Should().BeNull();
        r2.Should().BeNull();
        r3.Should().BeNull();
    }

    // ── DIA-003 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-003: Confirm — message + optional title; returns bool (false on cancel).</summary>
    [Fact]
    [Trait("Conformance", "DIA-003")]
    public async Task DIA_003_Confirm_Contract()
    {
        NullDialogService sut = NullDialogService.Instance;

        var r1 = await sut.Confirm("Are you sure?");
        var r2 = await sut.Confirm("Delete this item?", title: "Confirm delete");

        // NullDialogService always returns false (safest default).
        r1.Should().BeFalse();
        r2.Should().BeFalse();
    }

    // ── DIA-004 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-004: Notify — message/title/severity; completes without error.</summary>
    [Fact]
    [Trait("Conformance", "DIA-004")]
    public async Task DIA_004_Notify_Contract()
    {
        NullDialogService sut = NullDialogService.Instance;

        // Default severity (Info).
        await sut.Invoking(s => s.Notify("Hello")).Should().NotThrowAsync();

        // Explicit severities.
        await sut.Invoking(s => s.Notify("Info msg", severity: NotificationSeverity.Info))
            .Should().NotThrowAsync();
        await sut.Invoking(s => s.Notify("Warn msg", title: "Warning", severity: NotificationSeverity.Warning))
            .Should().NotThrowAsync();
        await sut.Invoking(s => s.Notify("Err msg", title: "Error", severity: NotificationSeverity.Error))
            .Should().NotThrowAsync();
    }

    // ── DIA-005 ──────────────────────────────────────────────────────────────

    /// <summary>DIA-005: NullDialogService — full surface: PickFile* null; Confirm false; Notify no-op.</summary>
    [Fact]
    [Trait("Conformance", "DIA-005")]
    public async Task DIA_005_NullDialogService_Null_Object_Behavior()
    {
        var sut = NullDialogService.Instance;

        (await sut.PickFileToOpen()).Should().BeNull("PickFileToOpen returns null per ADR-0017");
        (await sut.PickFileToSave()).Should().BeNull("PickFileToSave returns null per ADR-0017");
        (await sut.Confirm("msg")).Should().BeFalse("Confirm returns false (safest default)");

        var notifyAct = async () => await sut.Notify("msg");
        await notifyAct.Should().NotThrowAsync("Notify is a no-op");
    }

    // ── DIA-006 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// DIA-006: Reentrancy is implementation-defined; both queueing and
    /// immediate-rejecting implementations conform to the contract.
    /// </summary>
    [Fact]
    [Trait("Conformance", "DIA-006")]
    public async Task DIA_006_Reentrancy_Implementation_Defined()
    {
        // --- Queueing implementation: serialises concurrent calls. ---
        var queuing = new QueuingDialogService();
        var t1 = queuing.Confirm("first");
        var t2 = queuing.Confirm("second");

        queuing.CompleteNext(true);   // resolves t1
        queuing.CompleteNext(false);  // resolves t2

        var r1 = await t1;
        var r2 = await t2;
        r1.Should().BeTrue("first call resolved with true");
        r2.Should().BeFalse("second call resolved with false");

        // --- Immediate-rejecting implementation: second call returns false synchronously. ---
        var rejecting = new RejectingDialogService();
        var tA = rejecting.Confirm("active");
        var tB = rejecting.Confirm("reentrant");

        // tB must resolve immediately with false (no exception).
        tB.IsCompleted.Should().BeTrue("reentrant call completes immediately");
        (await tB).Should().BeFalse("reentrant call returns safe default false");

        // Complete the first call — no exception.
        rejecting.CompleteActive(true);
        (await tA).Should().BeTrue("first call still resolves normally");
    }

    // ── DIA-007 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// DIA-007: Cancellation completes the awaitable with safe default (null/false);
    /// does not throw OperationCanceledException.
    /// </summary>
    [Fact]
    [Trait("Conformance", "DIA-007")]
    public async Task DIA_007_Cancellation_Completes_With_Safe_Default()
    {
        var svc = new CancellationAwareDialogService();

        // PickFileToOpen — cancelled token → null, no throw.
        using var cts1 = new CancellationTokenSource();
        cts1.Cancel();
        var path = await svc.PickFileToOpen(ct: cts1.Token);
        path.Should().BeNull("cancelled PickFileToOpen returns null");

        // Confirm — cancelled token → false, no throw.
        using var cts2 = new CancellationTokenSource();
        cts2.Cancel();
        var confirmed = await svc.Confirm("msg", ct: cts2.Token);
        confirmed.Should().BeFalse("cancelled Confirm returns false");
    }

    // ── DIA-008 ──────────────────────────────────────────────────────────────

    /// <summary>
    /// DIA-008: ConfirmationDecoratorCommand with () => dialogService.Confirm(prompt)
    /// constructs a valid command graph that respects ADR-0012.
    /// </summary>
    [Fact]
    [Trait("Conformance", "DIA-008")]
    public async Task DIA_008_ConfirmationDecoratorCommand_Integration()
    {
        // Arrange: use a controllable dialog service.
        var dialog = new ControllableDialogService();
        var innerExecuted = false;
        var inner = RelayCommand.Builder().Task(() => innerExecuted = true).Build();

        // Wire: fluent Confirm overload taking a Func<Task<bool>> delegate.
        var safeCmd = inner.Confirm(() => dialog.Confirm("Proceed?"));

        safeCmd.Should().BeAssignableTo<ICommand>("result is a valid ICommand");
        safeCmd.CanExecute(null).Should().BeTrue("delegates CanExecute to inner");

        // When dialog returns false: inner must NOT execute.
        dialog.NextResult = false;
        await ((ConfirmationDecoratorCommand)safeCmd).ExecuteAsync(null);
        innerExecuted.Should().BeFalse("inner not executed when Confirm returns false");

        // When dialog returns true: inner MUST execute.
        dialog.NextResult = true;
        await ((ConfirmationDecoratorCommand)safeCmd).ExecuteAsync(null);
        innerExecuted.Should().BeTrue("inner executed when Confirm returns true");

        // Also exercise the dedicated Confirm(IDialogService, prompt) overload.
        // Spec DIA-008 explicitly covers both the lambda form above and this
        // fluent overload.
        var overloadExecuted = false;
        var inner2 = RelayCommand.Builder().Task(() => overloadExecuted = true).Build();
        var overloadCmd = inner2.Confirm(dialog, "Proceed?");

        overloadCmd.Should().BeAssignableTo<ICommand>("overload result is a valid ICommand");
        overloadCmd.CanExecute(null).Should().BeTrue("overload delegates CanExecute to inner");

        dialog.NextResult = false;
        await ((ConfirmationDecoratorCommand)overloadCmd).ExecuteAsync(null);
        overloadExecuted.Should().BeFalse("overload: inner not executed when Confirm returns false");

        dialog.NextResult = true;
        await ((ConfirmationDecoratorCommand)overloadCmd).ExecuteAsync(null);
        overloadExecuted.Should().BeTrue("overload: inner executed when Confirm returns true");
    }

    // ── Test doubles ─────────────────────────────────────────────────────────

    /// <summary>
    /// Controllable dialog service: result is set by the test before each call.
    /// </summary>
    private sealed class ControllableDialogService : IDialogService
    {
        public bool NextResult { get; set; }

        public Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
            => Task.FromResult<string?>(null);

        public Task<string?> PickFileToSave(
            FileFilter? filter = null,
            string? title = null,
            string? suggestedName = null)
            => Task.FromResult<string?>(null);

        public Task<bool> Confirm(string message, string? title = null)
            => Task.FromResult(NextResult);

        public Task Notify(
            string message,
            string? title = null,
            NotificationSeverity severity = NotificationSeverity.Info)
            => Task.CompletedTask;
    }

    /// <summary>
    /// Queueing IDialogService: concurrent Confirm calls are serialised via a queue.
    /// The test driver pumps each call via CompleteNext(result).
    /// </summary>
    private sealed class QueuingDialogService : IDialogService
    {
        private readonly Queue<TaskCompletionSource<bool>> _queue = new();

        public Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
            => Task.FromResult<string?>(null);

        public Task<string?> PickFileToSave(
            FileFilter? filter = null,
            string? title = null,
            string? suggestedName = null)
            => Task.FromResult<string?>(null);

        public Task<bool> Confirm(string message, string? title = null)
        {
            var tcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            _queue.Enqueue(tcs);
            return tcs.Task;
        }

        public Task Notify(
            string message,
            string? title = null,
            NotificationSeverity severity = NotificationSeverity.Info)
            => Task.CompletedTask;

        public void CompleteNext(bool result) => _queue.Dequeue().SetResult(result);
    }

    /// <summary>
    /// Immediate-rejecting IDialogService: while a Confirm call is pending,
    /// any additional Confirm call resolves immediately with false.
    /// </summary>
    private sealed class RejectingDialogService : IDialogService
    {
        private TaskCompletionSource<bool>? _active;

        public Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
            => Task.FromResult<string?>(null);

        public Task<string?> PickFileToSave(
            FileFilter? filter = null,
            string? title = null,
            string? suggestedName = null)
            => Task.FromResult<string?>(null);

        public Task<bool> Confirm(string message, string? title = null)
        {
            if (_active is not null)
                return Task.FromResult(false); // reentrant — reject immediately

            _active = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            return _active.Task;
        }

        public Task Notify(
            string message,
            string? title = null,
            NotificationSeverity severity = NotificationSeverity.Info)
            => Task.CompletedTask;

        public void CompleteActive(bool result)
        {
            _active?.SetResult(result);
            _active = null;
        }
    }

    /// <summary>
    /// Cancellation-aware dialog service (not IDialogService): exposes CT overloads
    /// to verify DIA-007 — cancellation completes with safe default, no throw.
    /// </summary>
    private sealed class CancellationAwareDialogService
    {
        private readonly bool _pendingResult;

        public CancellationAwareDialogService(bool pendingResult = false)
        {
            _pendingResult = pendingResult;
        }

        public Task<string?> PickFileToOpen(
            FileFilter? filter = null,
            string? title = null,
            CancellationToken ct = default)
        {
            if (ct.IsCancellationRequested)
                return Task.FromResult<string?>(null);
            return Task.FromResult<string?>(_pendingResult ? "/some/path" : null);
        }

        public Task<bool> Confirm(
            string message,
            string? title = null,
            CancellationToken ct = default)
        {
            if (ct.IsCancellationRequested)
                return Task.FromResult(false);
            return Task.FromResult(_pendingResult);
        }
    }
}
