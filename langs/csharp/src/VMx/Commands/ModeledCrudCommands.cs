#pragma warning disable CA1715 // Spec uses M / VM for model / viewmodel per ADR-0006
using System.Windows.Input;

namespace VMx.Commands;

/// <summary>
/// Composes the three modeled-CRUD commands (Create/Update/Delete-current) against
/// a current-VM provider and per-action callbacks. See spec/06-composite-vm.md
/// §Modeled CRUD commands and ADR-0016.
/// </summary>
public sealed class ModeledCrudCommands<M, VM> : IDisposable
    where VM : class
{
    /// <summary>Command that invokes the create-new action.</summary>
    public ICommand CreateNewCommand { get; }

    /// <summary>Command that invokes update_current with the current VM. CanExecute requires current != null.</summary>
    public ICommand UpdateCurrentCommand { get; }

    /// <summary>Command that invokes delete_current with the current VM. CanExecute requires current != null.</summary>
    public ICommand DeleteCurrentCommand { get; }

    private readonly List<IDisposable> _disposables = new();

    /// <summary>Creates a new CRUD command set.</summary>
    /// <param name="current">Provider returning the current VM (or null).</param>
    /// <param name="createNew">Action invoked by CreateNewCommand.</param>
    /// <param name="updateCurrent">Action invoked by UpdateCurrentCommand with the current VM.</param>
    /// <param name="deleteCurrent">Action invoked by DeleteCurrentCommand with the current VM.</param>
    /// <param name="confirmUpdate">Optional async confirm gate for update.</param>
    /// <param name="confirmDelete">Optional async confirm gate for delete.</param>
    public ModeledCrudCommands(
        Func<VM?> current,
        Action createNew,
        Action<VM> updateCurrent,
        Action<VM> deleteCurrent,
        Func<Task<bool>>? confirmUpdate = null,
        Func<Task<bool>>? confirmDelete = null)
    {
        var create = RelayCommand.Builder().Task(createNew).Build();
        var update = RelayCommand.Builder()
            .Task(() => { var c = current(); if (c is not null) updateCurrent(c); })
            .Predicate(() => current() is not null)
            .Build();
        var delete = RelayCommand.Builder()
            .Task(() => { var c = current(); if (c is not null) deleteCurrent(c); })
            .Predicate(() => current() is not null)
            .Build();
        _disposables.Add((IDisposable)create);
        _disposables.Add((IDisposable)update);
        _disposables.Add((IDisposable)delete);

        CreateNewCommand = create;
        if (confirmUpdate is not null)
        {
            var wrapped = new ConfirmationDecoratorCommand(update, confirmUpdate);
            _disposables.Add(wrapped);
            UpdateCurrentCommand = wrapped;
        }
        else
        {
            UpdateCurrentCommand = update;
        }
        if (confirmDelete is not null)
        {
            var wrapped = new ConfirmationDecoratorCommand(delete, confirmDelete);
            _disposables.Add(wrapped);
            DeleteCurrentCommand = wrapped;
        }
        else
        {
            DeleteCurrentCommand = delete;
        }
    }

    /// <summary>Disposes the underlying commands.</summary>
    public void Dispose()
    {
        foreach (var d in _disposables) d.Dispose();
    }
}
