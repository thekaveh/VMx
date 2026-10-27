using System.Reactive;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.ExceptionServices;
using System.Windows.Input;
using VMx.Commands;
using VMx.Internal;

namespace VMx.Capabilities;

/// <summary>
/// Composition-friendly helper that bundles <see cref="IExpandable"/>,
/// <see cref="ICollapsible"/>, and <see cref="IExpansionTogglable"/> with a
/// change observable and the matching commands. See
/// spec/05-component-vm.md §8, ADR-0015, and ADR-0159.
/// </summary>
public sealed class ExpandableState : IExpandable, ICollapsible, IExpansionTogglable, IDisposable
{
    private readonly Subject<bool> _changes = new();
    private bool _isExpanded;
    private bool _disposed;

    // Built on first read (ADR-0159), so a helper whose commands are never read
    // holds no trigger subscriptions and disposal creates none.
    private RelayCommand? _expandCommand;
    private RelayCommand? _collapseCommand;
    private RelayCommand? _toggleExpansionCommand;

    /// <summary>Creates a new <see cref="ExpandableState"/> (initial: collapsed).</summary>
    public ExpandableState(bool initiallyExpanded = false)
    {
        _isExpanded = initiallyExpanded;
    }

    /// <inheritdoc/>
    public bool IsExpanded => _isExpanded;

    /// <summary>Emits the new value every time <see cref="IsExpanded"/> changes.</summary>
    public IObservable<bool> IsExpandedChanged => _changes.AsObservable();

    /// <summary>
    /// Runs <see cref="Expand"/> when <see cref="CanExpand"/> is true. This
    /// helper owns the command: <see cref="Dispose"/> disposes it, and callers
    /// must not.
    /// </summary>
    public ICommand ExpandCommand => _expandCommand ??= BuildCommand(CanExpand, Expand);

    /// <summary>
    /// Runs <see cref="Collapse"/> when <see cref="CanCollapse"/> is true. This
    /// helper owns the command: <see cref="Dispose"/> disposes it, and callers
    /// must not.
    /// </summary>
    public ICommand CollapseCommand => _collapseCommand ??= BuildCommand(CanCollapse, Collapse);

    /// <summary>
    /// Runs <see cref="ToggleExpansion"/> when <see cref="CanToggleExpansion"/>
    /// is true. This helper owns the command: <see cref="Dispose"/> disposes
    /// it, and callers must not.
    /// </summary>
    public ICommand ToggleExpansionCommand =>
        _toggleExpansionCommand ??= BuildCommand(CanToggleExpansion, ToggleExpansion);

    /// <inheritdoc/>
    public bool CanExpand() => !_isExpanded;

    /// <inheritdoc/>
    public void Expand()
    {
        if (_disposed) return;
        if (_isExpanded) return;
        _isExpanded = true;
        _changes.OnNext(true);
    }

    /// <inheritdoc/>
    public bool CanCollapse() => _isExpanded;

    /// <inheritdoc/>
    public void Collapse()
    {
        if (_disposed) return;
        if (!_isExpanded) return;
        _isExpanded = false;
        _changes.OnNext(false);
    }

    /// <inheritdoc/>
    public bool CanToggleExpansion() => true;

    /// <inheritdoc/>
    public void ToggleExpansion()
    {
        if (_isExpanded) Collapse(); else Expand();
    }

    /// <summary>
    /// Disposes the commands that were read, then completes the
    /// <see cref="IsExpandedChanged"/> observable.
    /// </summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        // A throwing observer must not skip a later step. Run every step, then
        // rethrow the first failure (#768).
        ExceptionDispatchInfo? firstError = null;
        if (_expandCommand is not null) FirstFailure.Capture(ref firstError, _expandCommand.Dispose);
        if (_collapseCommand is not null) FirstFailure.Capture(ref firstError, _collapseCommand.Dispose);
        if (_toggleExpansionCommand is not null)
            FirstFailure.Capture(ref firstError, _toggleExpansionCommand.Dispose);
        FirstFailure.Capture(ref firstError, _changes.OnCompleted);
        FirstFailure.Capture(ref firstError, _changes.Dispose);
        firstError?.Throw();
    }

    // A command read after disposal is built without the disposed trigger
    // subject and disposed at once, so it is inert like the others (ADR-0068).
    private RelayCommand BuildCommand(Func<bool> predicate, Action task)
    {
        var builder = RelayCommand.Builder().Predicate(predicate).Task(task);
        if (!_disposed)
            builder = builder.Triggers(_changes.Select(static _ => Unit.Default));
        var command = builder.Build();
        if (_disposed) command.Dispose();
        return command;
    }
}
