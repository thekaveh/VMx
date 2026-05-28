using FluentAssertions;
using VMx.Commands;
using VMx.Dialogs;
using VMx.Forms;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests: FORM-001..FORM-010 — FormVM&lt;TM&gt; (snapshot/revert edit lifecycle).
/// See spec/20-form-vm.md and ADR-0030.
/// </summary>
public class FORM_001_to_010_FormVM_Tests
{
    // ── shared model ─────────────────────────────────────────────────────────

    /// <summary>Simple record model used across all FORM tests.</summary>
    private sealed record Model(string Name, int Value);

    // ── FORM-001 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-001: Snapshot captured at construct; Model == Snapshot; IsDirty == false.</summary>
    [Fact]
    [Trait("Conformance", "FORM-001")]
    public void FORM_001_Snapshot_Captured_At_Construct()
    {
        var initial = new Model("Alice", 1);
        using var sut = MakeFormVM(initial);

        sut.Model.Should().Be(initial);
        sut.Snapshot.Should().Be(initial);
        sut.IsDirty.Should().BeFalse();
    }

    // ── FORM-002 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-002: Model mutation reflected in IsDirty; Snapshot unchanged.</summary>
    [Fact]
    [Trait("Conformance", "FORM-002")]
    public void FORM_002_Model_Mutation_Reflected_In_IsDirty()
    {
        var initial = new Model("Alice", 1);
        using var sut = MakeFormVM(initial);

        sut.SetModel(new Model("Bob", 2));

        sut.IsDirty.Should().BeTrue();
        sut.Snapshot.Should().Be(initial, "Snapshot is unchanged after SetModel");
        sut.Model.Should().Be(new Model("Bob", 2));
    }

    // ── FORM-003 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-003: IsDirty derivation via structural inequality.</summary>
    [Fact]
    [Trait("Conformance", "FORM-003")]
    public void FORM_003_IsDirty_Structural_Inequality()
    {
        var initial = new Model("Alice", 1);
        using var sut = MakeFormVM(initial);

        // Setting the same value-equal (but distinct reference) model → not dirty.
        sut.SetModel(new Model("Alice", 1));
        sut.IsDirty.Should().BeFalse("equal value → not dirty");

        // Setting a structurally different model → dirty.
        sut.SetModel(new Model("Alice", 99));
        sut.IsDirty.Should().BeTrue("different value → dirty");
    }

    // ── FORM-004 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-004: DenyCommand reverts Model to Snapshot; IsDirty == false after revert.</summary>
    [Fact]
    [Trait("Conformance", "FORM-004")]
    public void FORM_004_DenyCommand_Reverts_To_Snapshot()
    {
        var initial = new Model("Alice", 1);
        using var sut = MakeFormVM(initial);

        sut.SetModel(new Model("Bob", 2));
        sut.IsDirty.Should().BeTrue();

        sut.DenyCommand.Execute(null);

        sut.Model.Should().Be(initial, "Model reverted to Snapshot value");
        sut.IsDirty.Should().BeFalse("no longer dirty after revert");
    }

    // ── FORM-005 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-005: ApproveCommand invokes persister; Snapshot advances on success.</summary>
    [Fact]
    [Trait("Conformance", "FORM-005")]
    public async Task FORM_005_ApproveCommand_Persists_And_Advances_Snapshot()
    {
        var initial = new Model("Alice", 1);
        var persisted = new List<Model>();

        using var sut = new FormVM<Model>(
            initial,
            m => { persisted.Add(m); return Task.CompletedTask; });

        var updated = new Model("Bob", 2);
        sut.SetModel(updated);

        await sut.ApproveAsync();

        persisted.Should().ContainSingle().Which.Should().Be(updated, "persister called with Model");
        sut.Snapshot.Should().Be(updated, "Snapshot advanced to Model after success");
        sut.IsDirty.Should().BeFalse("no longer dirty after approve");
    }

    // ── FORM-006 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-006: OnApproved fires only after successful persist.</summary>
    [Fact]
    [Trait("Conformance", "FORM-006")]
    public async Task FORM_006_OnApproved_Fires_Only_After_Success()
    {
        var initial = new Model("Alice", 1);
        var approvedValues = new List<Model>();

        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask);
        using var __ = sut.OnApproved.Subscribe(approvedValues.Add);

        // Before approve: not yet fired.
        approvedValues.Should().BeEmpty();

        sut.SetModel(new Model("Bob", 2));
        await sut.ApproveAsync();

        approvedValues.Should().ContainSingle().Which.Should().Be(new Model("Bob", 2));
    }

    // ── FORM-007 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-007: Persist failure leaves state unchanged; exception propagates.</summary>
    [Fact]
    [Trait("Conformance", "FORM-007")]
    public async Task FORM_007_Persist_Failure_Leaves_State_Unchanged()
    {
        var initial = new Model("Alice", 1);
        var updated = new Model("Bob", 2);
        var approvedFired = false;

        using var sut = new FormVM<Model>(initial, _ => throw new InvalidOperationException("DB error"));
        using var __ = sut.OnApproved.Subscribe(_ => approvedFired = true);

        sut.SetModel(updated);

        // Await directly to observe the persister exception.
        var ex = await Record.ExceptionAsync(() => sut.ApproveAsync());
        ex.Should().BeOfType<InvalidOperationException>("persister exception propagates");

        sut.Model.Should().Be(updated, "Model unchanged after failed persist");
        sut.Snapshot.Should().Be(initial, "Snapshot unchanged after failed persist");
        sut.IsDirty.Should().BeTrue("still dirty after failed persist");
        approvedFired.Should().BeFalse("OnApproved not fired on failure");
    }

    // ── FORM-008 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-008: Hub messages on revert — FormRevertedMessage + PropertyChangedMessage("Model").</summary>
    [Fact]
    [Trait("Conformance", "FORM-008")]
    public void FORM_008_Hub_Messages_On_Revert()
    {
        var hub = new MessageHub();
        var messages = new List<IMessage>();
        using var sub = hub.Messages.Subscribe(messages.Add);

        var initial = new Model("Alice", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, hub: hub);

        sut.SetModel(new Model("Bob", 2));
        sut.DenyCommand.Execute(null);

        messages.Should().HaveCount(2, "two messages published on revert");

        var revertMsg = messages.OfType<FormRevertedMessage>().SingleOrDefault();
        revertMsg.Should().NotBeNull("FormRevertedMessage published");
        revertMsg!.Sender.Should().BeSameAs(sut);

        var propMsg = messages.OfType<PropertyChangedMessage<FormVM<Model>>>().SingleOrDefault();
        propMsg.Should().NotBeNull("PropertyChangedMessage published");
        propMsg!.PropertyName.Should().Be("Model");
    }

    // ── FORM-009 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-009: Strict mode — ApproveCommand.CanExecute gates on IsDirty.</summary>
    [Fact]
    [Trait("Conformance", "FORM-009")]
    public void FORM_009_Strict_Mode_ApproveCanExecute_Gates_On_IsDirty()
    {
        var initial = new Model("Alice", 1);
        using var sut = new FormVM<Model>(initial, _ => Task.CompletedTask, strict: true);

        // Initially not dirty → CanExecute is false.
        sut.IsDirty.Should().BeFalse();
        sut.ApproveCommand.CanExecute(null).Should().BeFalse("strict: not dirty → cannot approve");

        // Dirty → CanExecute is true.
        sut.SetModel(new Model("Bob", 2));
        sut.ApproveCommand.CanExecute(null).Should().BeTrue("strict: dirty → can approve");

        // Non-strict (default): always true regardless of IsDirty.
        using var nonStrict = new FormVM<Model>(initial, _ => Task.CompletedTask, strict: false);
        nonStrict.ApproveCommand.CanExecute(null).Should().BeTrue("non-strict: can approve even when not dirty");
    }

    // ── FORM-010 ──────────────────────────────────────────────────────────────

    /// <summary>FORM-010: Integration with IDialogService.Confirm — confirm guard prevents revert on false.</summary>
    [Fact]
    [Trait("Conformance", "FORM-010")]
    public async Task FORM_010_IDialogService_Confirm_Integration()
    {
        var initial = new Model("Alice", 1);
        using var sut = MakeFormVM(initial);

        sut.SetModel(new Model("Bob", 2));
        sut.IsDirty.Should().BeTrue();

        // Wrap DenyCommand with NullDialogService.Confirm (returns false → guard blocks revert).
        var guardedDeny = sut.DenyCommand.Confirm(() => NullDialogService.Instance.Confirm("Discard changes?"));

        await ((ConfirmationDecoratorCommand)guardedDeny).ExecuteAsync(null);

        // Model should NOT have been reverted (dialog returned false).
        sut.IsDirty.Should().BeTrue("DenyCommand blocked by Confirm returning false");
        sut.Model.Should().Be(new Model("Bob", 2), "Model unchanged when Confirm returns false");

        // Now with a confirm that returns true → revert proceeds.
        var confirmingDeny = sut.DenyCommand.Confirm(() => Task.FromResult(true));
        await ((ConfirmationDecoratorCommand)confirmingDeny).ExecuteAsync(null);

        sut.IsDirty.Should().BeFalse("Model reverted when Confirm returns true");
        sut.Model.Should().Be(initial, "Model restored to Snapshot");
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private static FormVM<Model> MakeFormVM(Model initial)
        => new(initial, _ => Task.CompletedTask);
}
