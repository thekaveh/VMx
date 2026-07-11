using VMx.Lifecycle;
using VMx.Services;

namespace VMx.Components;

/// <summary>
/// Abstract base that extends <see cref="ComponentVMBase"/> with a typed
/// model field, equality-guarded setter, and derived ModeledHint recomputation.
///
/// See spec/05-component-vm.md §Modeled variant additions.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public abstract class ComponentVMBaseOfM<M> : ComponentVMBase
{
    private M _model;
    private string _modeledHint;
    private readonly Func<M, string> _modeledHinter;
    private readonly Action<M>? _onModelChanged;

    /// <summary>Derived hint string computed from the current model.</summary>
    public string ModeledHint => _modeledHint;

    /// <summary>
    /// Protected model getter/setter used by concrete subclasses.
    /// </summary>
    protected M ModelValue
    {
        get => _model;
        set => SetModel(value);
    }

    /// <summary>
    /// Initializes the modeled base. <paramref name="initialModel"/> is stored without
    /// raising any events (this is construction time, not a change).
    /// </summary>
    protected ComponentVMBaseOfM(
        string name,
        string hint,
        M initialModel,
        Func<M, string> modeledHinter,
        Action<M>? onModelChanged,
        IMessageHub hub,
        IDispatcher dispatcher,
        System.Action? onConstruct,
        System.Action? onDestruct,
        bool background = false)
        : base(name, hint, hub, dispatcher, onConstruct, onDestruct, background)
    {
        _model = initialModel;
        _modeledHinter = modeledHinter;
        _onModelChanged = onModelChanged;
        _modeledHint = modeledHinter(initialModel);
    }

    /// <summary>
    /// Applies equality-guarded model update:
    /// <list type="number">
    ///   <item><description>No-op if new value equals current value.</description></item>
    ///   <item><description>Sets field, emits PropertyChangedMessage("Model").</description></item>
    ///   <item><description>Raises INotifyPropertyChanged.PropertyChanged.</description></item>
    ///   <item><description>Recomputes ModeledHint; if changed, emits its message.</description></item>
    ///   <item><description>Invokes OnModelChanged callback if configured.</description></item>
    /// </list>
    /// </summary>
    private void SetModel(M value)
    {
        if (Status == ConstructionStatus.Disposed) return;
        if (EqualityComparer<M>.Default.Equals(_model, value)) return;

        _model = value;

        NotifyPropertyChanged("Model");

        // Recompute ModeledHint.
        var newHint = _modeledHinter(value);
        if (!string.Equals(_modeledHint, newHint, StringComparison.Ordinal))
        {
            _modeledHint = newHint;
            NotifyPropertyChanged(nameof(ModeledHint));
        }

        // Invoke OnModelChanged callback.
        _onModelChanged?.Invoke(value);
    }
}
