namespace VMx.Components;

/// <summary>
/// Modeled ComponentVM: adds a settable <see cref="Model"/> property and
/// a derived <see cref="ModeledHint"/>.
/// See spec/05-component-vm.md §Modeled variant additions.
/// </summary>
/// <typeparam name="M">The model type.</typeparam>
public interface IComponentVM<M> : IComponentVM
{
    /// <summary>
    /// The underlying model. Setting to a different value emits
    /// <c>PropertyChangedMessage("Model")</c> on the hub and raises
    /// <see cref="System.ComponentModel.INotifyPropertyChanged.PropertyChanged"/>.
    /// Setting to the same value (by equality) is a no-op.
    /// </summary>
    M Model { get; set; }

    /// <summary>
    /// Derived hint string computed from the current <see cref="Model"/>
    /// via the <c>ModeledHinter</c> function supplied at build time.
    /// Recomputed (and messaged) whenever <see cref="Model"/> changes.
    /// </summary>
    string ModeledHint { get; }

    /// <summary>
    /// Republishes the retained model without assigning it, recomputing
    /// <see cref="ModeledHint"/>, or invoking the model-changed callback.
    /// </summary>
    void RepublishModel();
}
