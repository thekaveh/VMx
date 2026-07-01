using FluentAssertions;
using System.Diagnostics.CodeAnalysis;
using VMx.Dialogs;
using Xunit;

namespace VMx.Conformance.Tests;

[SuppressMessage("Performance", "CA1859", Justification = "Conformance tests intentionally exercise interface-typed dialog contracts.")]
public class DIA_009_to_013_ModalPresentation_Tests
{
    [Fact, Trait("Conformance", "DIA-009")]
    public async Task DIA_009_Present_Returns_Modal_Result()
    {
        var modal = new ModalVM<string>("cancel");
        var service = new HostDialogService();

        var result = await service.Present(modal);

        result.Should().Be("accepted");
        modal.Result.Should().Be("accepted");
    }

    [Fact, Trait("Conformance", "DIA-010")]
    public async Task DIA_010_Null_Present_Uses_Cancellation_Result()
    {
        var modal = new ModalVM<string>("cancel");

        var result = await NullDialogService.Instance.Present(modal);

        result.Should().Be("cancel");
        modal.IsDismissed.Should().BeTrue();
        modal.Result.Should().Be("cancel");
    }

    [Fact, Trait("Conformance", "DIA-011")]
    public async Task DIA_011_Modal_Dispose_Completes_With_Cancellation_Result()
    {
        var modal = new ModalVM<string>("cancel");

        modal.Dispose();

        (await modal.Completion).Should().Be("cancel");
        modal.IsDismissed.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "DIA-012")]
    public async Task DIA_012_Modal_Dismiss_Is_Idempotent()
    {
        var modal = new ModalVM<string>("cancel");

        modal.Dismiss("first");
        modal.Dismiss("second");

        (await modal.Completion).Should().Be("first");
        modal.Result.Should().Be("first");
    }

    [Fact, Trait("Conformance", "DIA-013")]
    public async Task DIA_013_Existing_Dialog_Methods_Remain_Source_Compatible()
    {
        IDialogService sut = NullDialogService.Instance;

        (await sut.PickFileToOpen()).Should().BeNull();
        (await sut.PickFileToSave()).Should().BeNull();
        (await sut.Confirm("Proceed?")).Should().BeFalse();
        await sut.Notify("Done");
    }

    private sealed class HostDialogService : IModalDialogService
    {
        public Task<string?> PickFileToOpen(FileFilter? filter = null, string? title = null)
            => Task.FromResult<string?>(null);

        public Task<string?> PickFileToSave(
            FileFilter? filter = null,
            string? title = null,
            string? suggestedName = null)
            => Task.FromResult<string?>(null);

        public Task<bool> Confirm(string message, string? title = null)
            => Task.FromResult(false);

        public Task Notify(
            string message,
            string? title = null,
            NotificationSeverity severity = NotificationSeverity.Info)
            => Task.CompletedTask;

        public Task<T> Present<T>(IModalVM<T> modal, CancellationToken cancellationToken = default)
        {
            modal.Dismiss((T)(object)"accepted");
            return modal.Completion;
        }
    }
}
