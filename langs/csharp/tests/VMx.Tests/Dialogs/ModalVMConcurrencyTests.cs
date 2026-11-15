using FluentAssertions;
using VMx.Dialogs;
using Xunit;

namespace VMx.Tests.Dialogs;

/// <summary>
/// Concurrency tests for <see cref="ModalVM{T}"/>. The first dismissal claims the modal,
/// and <see cref="ModalVM{T}.Result"/> always equals the awaited
/// <see cref="ModalVM{T}.Completion"/>, even when two threads race.
/// </summary>
public class ModalVMConcurrencyTests
{
    private const int Iterations = 10_000;

    [Fact]
    public async Task Racing_Dismissals_Keep_Result_Equal_To_Completion()
    {
        for (var i = 0; i < Iterations; i++)
        {
            var modal = new ModalVM<string>("cancel");

            await RunOnTwoThreadsAsync(() => modal.Dismiss("a"), () => modal.Dismiss("b"));

            var completed = await modal.Completion.WaitAsync(TimeSpan.FromSeconds(5));
            modal.IsDismissed.Should().BeTrue($"iteration {i}");
            modal.Result.Should().Be(completed, $"iteration {i}");
        }
    }

    [Fact]
    public async Task Racing_Dismissal_And_Disposal_Keep_Result_Equal_To_Completion()
    {
        for (var i = 0; i < Iterations; i++)
        {
            var modal = new ModalVM<string>("cancel");

            await RunOnTwoThreadsAsync(() => modal.Dismiss("a"), modal.Dispose);

            var completed = await modal.Completion.WaitAsync(TimeSpan.FromSeconds(5));
            modal.IsDismissed.Should().BeTrue($"iteration {i}");
            modal.Result.Should().Be(completed, $"iteration {i}");
        }
    }

    /// <summary>Starts both actions on dedicated threads at the same moment.</summary>
    private static async Task RunOnTwoThreadsAsync(Action first, Action second)
    {
        using var start = new Barrier(2);
        var a = Task.Factory.StartNew(
            () => { start.SignalAndWait(); first(); },
            TaskCreationOptions.LongRunning);
        var b = Task.Factory.StartNew(
            () => { start.SignalAndWait(); second(); },
            TaskCreationOptions.LongRunning);
        await Task.WhenAll(a, b);
    }
}
