using VMx.Components;

namespace VMx.Composites;

/// <summary>Filters out null scores and orders visible items by descending score.</summary>
public sealed class ScoredFilteredCompositeVM<VM> : FilteredCompositeVM<VM>
    where VM : class, IComponentVM
{
    private readonly Func<VM, double?> _scorer;

    /// <summary>Create a scored filtered projection.</summary>
    public ScoredFilteredCompositeVM(
        CompositeVMBase<VM> source,
        Func<VM, double?> scorer,
        FilteredCursorPolicy cursorPolicy = FilteredCursorPolicy.SnapToFirst)
        : base(source, vm => scorer(vm) is not null, cursorPolicy, deferInitialRecompute: true)
    {
        _scorer = scorer ?? throw new ArgumentNullException(nameof(scorer));
        RefreshScores();
    }

    /// <inheritdoc/>
    protected override IReadOnlyList<VM> OrderedVisible() =>
        Source.Select((vm, index) => new { Vm = vm, Index = index, Score = _scorer(vm) })
            .Where(entry => entry.Score is not null)
            .OrderByDescending(entry => entry.Score!.Value)
            .ThenBy(entry => entry.Index)
            .Select(entry => entry.Vm)
            .ToArray();

    /// <summary>Recompute scores and ordering.</summary>
    public void RefreshScores() => Recompute();
}
