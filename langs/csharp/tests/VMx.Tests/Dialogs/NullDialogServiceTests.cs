using FluentAssertions;
using VMx.Dialogs;
using Xunit;

namespace VMx.Tests.Dialogs;

/// <summary>
/// Unit tests for <see cref="NullDialogService"/>.
/// Each Fact covers one independently verifiable behavioural requirement.
/// </summary>
public class NullDialogServiceTests
{
    // ── Construction ─────────────────────────────────────────────────────────

    [Fact]
    public void Instance_Is_Not_Null()
    {
        NullDialogService.Instance.Should().NotBeNull();
    }

    [Fact]
    public void Instance_Implements_IDialogService()
    {
        NullDialogService.Instance.Should().BeAssignableTo<IDialogService>();
    }

    [Fact]
    public void Instance_Returns_Same_Object_Each_Time()
    {
        NullDialogService.Instance.Should().BeSameAs(NullDialogService.Instance);
    }

    // ── PickFileToOpen ────────────────────────────────────────────────────────

    [Fact]
    public async Task PickFileToOpen_No_Args_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.PickFileToOpen();
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToOpen_With_Filter_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var filter = new FileFilter("Images", ["*.png", "*.jpg"]);
        var result = await sut.PickFileToOpen(filter: filter);
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToOpen_With_Title_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.PickFileToOpen(title: "Choose a file");
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToOpen_Multiple_Successive_Calls_All_Return_Null()
    {
        var sut = NullDialogService.Instance;
        for (var i = 0; i < 3; i++)
        {
            var result = await sut.PickFileToOpen();
            result.Should().BeNull($"call {i} should return null");
        }
    }

    // ── PickFileToSave ────────────────────────────────────────────────────────

    [Fact]
    public async Task PickFileToSave_No_Args_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.PickFileToSave();
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToSave_With_All_Args_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var filter = new FileFilter("Text files", ["*.txt"]);
        var result = await sut.PickFileToSave(
            filter: filter,
            title: "Save as",
            suggestedName: "output.txt");
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToSave_Null_Filter_Returns_Null()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.PickFileToSave(filter: null);
        result.Should().BeNull();
    }

    [Fact]
    public async Task PickFileToSave_Multiple_Successive_Calls_All_Return_Null()
    {
        var sut = NullDialogService.Instance;
        for (var i = 0; i < 3; i++)
        {
            var result = await sut.PickFileToSave();
            result.Should().BeNull($"call {i} should return null");
        }
    }

    // ── Confirm ───────────────────────────────────────────────────────────────

    [Fact]
    public async Task Confirm_Returns_False_For_Safest_Default()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.Confirm("Delete item?");
        result.Should().BeFalse("NullDialogService returns false to avoid triggering destructive ops");
    }

    [Fact]
    public async Task Confirm_With_Title_Returns_False()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.Confirm("Overwrite?", title: "Confirm");
        result.Should().BeFalse();
    }

    [Fact]
    public async Task Confirm_Null_Title_Returns_False()
    {
        var sut = NullDialogService.Instance;
        var result = await sut.Confirm("msg", title: null);
        result.Should().BeFalse();
    }

    [Fact]
    public async Task Confirm_Multiple_Successive_Calls_All_Return_False()
    {
        var sut = NullDialogService.Instance;
        for (var i = 0; i < 3; i++)
        {
            var result = await sut.Confirm($"message {i}");
            result.Should().BeFalse($"call {i} should return false");
        }
    }

    // ── Notify ────────────────────────────────────────────────────────────────

    [Fact]
    public async Task Notify_Default_Severity_Info_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("Hello");
        await act.Should().NotThrowAsync("Notify is a no-op");
    }

    [Fact]
    public async Task Notify_Info_Severity_Explicit_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("Info", severity: NotificationSeverity.Info);
        await act.Should().NotThrowAsync();
    }

    [Fact]
    public async Task Notify_Warning_Severity_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("Warn", severity: NotificationSeverity.Warning);
        await act.Should().NotThrowAsync();
    }

    [Fact]
    public async Task Notify_Error_Severity_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("Error", severity: NotificationSeverity.Error);
        await act.Should().NotThrowAsync();
    }

    [Fact]
    public async Task Notify_Null_Title_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("msg", title: null);
        await act.Should().NotThrowAsync();
    }

    [Fact]
    public async Task Notify_With_Title_No_Throw()
    {
        var sut = NullDialogService.Instance;
        var act = async () => await sut.Notify("msg", title: "My title");
        await act.Should().NotThrowAsync();
    }

    [Fact]
    public async Task Notify_Multiple_Successive_Calls_No_Throw()
    {
        var sut = NullDialogService.Instance;
        for (var i = 0; i < 3; i++)
        {
            var act = async () => await sut.Notify($"message {i}");
            await act.Should().NotThrowAsync($"call {i} should not throw");
        }
    }

    // ── FileFilter ────────────────────────────────────────────────────────────

    [Fact]
    public void FileFilter_Stores_Description_And_Extensions()
    {
        var filter = new FileFilter("Images", ["*.png", "*.jpg"]);
        filter.Description.Should().Be("Images");
        filter.Extensions.Should().Equal("*.png", "*.jpg");
    }

    [Fact]
    public void FileFilter_Empty_Extensions_Is_Valid()
    {
        var filter = new FileFilter("All files", []);
        filter.Extensions.Should().BeEmpty();
    }

    // ── NotificationSeverity ──────────────────────────────────────────────────

    [Fact]
    public void NotificationSeverity_Has_Info_Warning_Error_Values()
    {
        var values = Enum.GetValues<NotificationSeverity>();
        values.Should().Contain(NotificationSeverity.Info);
        values.Should().Contain(NotificationSeverity.Warning);
        values.Should().Contain(NotificationSeverity.Error);
    }
}
