using FluentAssertions;
using VMx.Forms;
using Xunit;
using static VMx.Tests.Helpers.Liveness;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-043 — an update raises
/// <c>ApproveCommand.CanExecuteChanged</c> exactly once when it changes
/// <c>IsValid</c>, or <c>IsDirty</c> in strict mode. An approval in flight does
/// not suppress it. See spec/20-form-vm.md §5.2/§5.3 and ADR-0196.
/// </summary>
public sealed class FORM_043_ApproveNotificationForUpdates_Tests
{
    private sealed record Model(string Value);

    private static readonly IReadOnlyDictionary<string, Func<Model, string?>> RejectsBad =
        new Dictionary<string, Func<Model, string?>>
        {
            ["Value"] = model => model.Value == "bad" ? "bad value" : null,
        };

    [Fact, Trait("Conformance", "FORM-043")]
    public void FORM_043_Strict_Update_Raises_Once_When_Validity_Or_Dirty_State_Changes()
    {
        using var form = new FormVM<Model>(
            new("snapshot"),
            _ => Task.CompletedTask,
            strict: true,
            validators: RejectsBad);
        form.SetModel(new("bad"));
        form.IsDirty.Should().BeTrue();
        form.IsValid.Should().BeFalse();
        var raised = 0;
        form.ApproveCommand.CanExecuteChanged += (_, _) => Interlocked.Increment(ref raised);

        form.SetModel(new("snapshot"));

        Volatile.Read(ref raised).Should().Be(1, "the update changed IsValid and IsDirty");
        form.ApproveCommand.CanExecute(null).Should().BeFalse("a strict, pristine form cannot approve");

        form.SetModel(new("a"));

        Volatile.Read(ref raised).Should().Be(2, "the update changed IsDirty in strict mode");
        form.ApproveCommand.CanExecute(null).Should().BeTrue();

        form.SetModel(new("b"));

        Volatile.Read(ref raised).Should().Be(2, "the update changed neither IsValid nor IsDirty");
    }

    [Fact, Trait("Conformance", "FORM-043")]
    public async Task FORM_043_Update_During_An_Approval_Still_Raises_Once()
    {
        FormVM<Model>? form = null;
        var raised = 0;
        var afterAdmission = -1;
        var insidePersister = -1;
        form = new FormVM<Model>(
            new("valid"),
            _ =>
            {
                afterAdmission = Volatile.Read(ref raised);
                form!.SetModel(new("bad"));
                insidePersister = Volatile.Read(ref raised);
                return Task.CompletedTask;
            },
            validators: RejectsBad);
        using var disposeForm = form;
        form.ApproveCommand.CanExecuteChanged += (_, _) => Interlocked.Increment(ref raised);

        await form.ApproveAsync().WaitAsync(HangGuard);

        afterAdmission.Should().Be(1, "admission raises the approve notification once");
        insidePersister.Should().Be(afterAdmission + 1, "the update changed IsValid during the approval");
        Volatile.Read(ref raised).Should().Be(insidePersister + 1, "settlement raises exactly one more notification");
    }
}
