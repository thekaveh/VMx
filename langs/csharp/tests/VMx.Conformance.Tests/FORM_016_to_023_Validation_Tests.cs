using FluentAssertions;
using VMx.Forms;
using Xunit;

namespace VMx.Conformance.Tests;

public class FORM_016_to_023_ValidationTests
{
    private sealed record Model(string Name, int Value);

    [Fact, Trait("Conformance", "FORM-016")]
    public void FORM_016_FieldValidatorPopulatesFieldError()
    {
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => Task.CompletedTask,
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = m => m.Name == "" ? "required" : null });
        sut.FieldError("Name").Should().Be("required");
        sut.Errors.Should().ContainKey("Name").WhoseValue.Should().Be("required");
    }

    [Fact, Trait("Conformance", "FORM-017")]
    public void FORM_017_ModelValidatorPopulatesErrors()
    {
        using var sut = new FormVM<Model>(
            new Model("x", -1),
            _ => Task.CompletedTask,
            modelValidator: _ => new Dictionary<string, string?> { ["Value"] = "negative" });
        sut.Errors.Should().ContainKey("Value").WhoseValue.Should().Be("negative");
    }

    [Fact, Trait("Conformance", "FORM-018")]
    public void FORM_018_IsValidReflectsErrors()
    {
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => Task.CompletedTask,
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = _ => "required" });
        sut.IsValid.Should().BeFalse();
    }

    [Fact, Trait("Conformance", "FORM-019")]
    public async Task FORM_019_InvalidFormBlocksApproval()
    {
        var calls = 0;
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => { calls++; return Task.CompletedTask; },
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = _ => "required" });
        sut.ApproveCommand.CanExecute(null).Should().BeFalse();
        await sut.ApproveAsync();
        calls.Should().Be(0);
    }

    [Fact, Trait("Conformance", "FORM-020")]
    public void FORM_020_ValidationRerunsAfterModelMutation()
    {
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => Task.CompletedTask,
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = m => m.Name == "" ? "required" : null });
        sut.SetModel(new Model("ok", 1));
        sut.Errors.Should().BeEmpty();
        sut.IsValid.Should().BeTrue();
    }

    [Fact, Trait("Conformance", "FORM-021")]
    public void FORM_021_ErrorsChangedFiresOnlyOnEffectiveChanges()
    {
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => Task.CompletedTask,
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = m => m.Name == "" ? "required" : null });
        var seen = new List<IReadOnlyDictionary<string, string>>();
        using var sub = sut.ErrorsChanged.Subscribe(seen.Add);
        sut.SetModel(new Model("", 2));
        sut.SetModel(new Model("ok", 2));
        seen.Should().ContainSingle().Which.Should().BeEmpty();
    }

    [Fact, Trait("Conformance", "FORM-022")]
    public void FORM_022_BuilderRegistersValidatorsImmutably()
    {
        var baseBuilder = FormVM<Model>.Builder()
            .Initial(new Model("", 1))
            .Persister(_ => Task.CompletedTask);
        var withValidator = baseBuilder.Validator("Name", _ => "required");
        withValidator.Should().NotBeSameAs(baseBuilder);
        using var sut = withValidator.Build();
        sut.FieldError("Name").Should().Be("required");
    }

    [Fact, Trait("Conformance", "FORM-023")]
    public void FORM_023_ClearingErrorsEnablesApprovalWhenOtherGatesPass()
    {
        using var sut = new FormVM<Model>(
            new Model("", 1),
            _ => Task.CompletedTask,
            strict: true,
            validators: new Dictionary<string, Func<Model, string?>> { ["Name"] = m => m.Name == "" ? "required" : null });
        sut.SetModel(new Model("ok", 2));
        sut.ApproveCommand.CanExecute(null).Should().BeTrue();
    }
}
