#pragma warning disable CA1715 // Spec uses 'VM' for child VM type parameter per ADR-0006
#pragma warning disable CA1051 // Protected field _wrappedComposite is intentional: subclasses use it to override individual members
using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;
using VMx.Components;
using VMx.Composites;

namespace VMx.Forwarding;

/// <summary>
/// Abstract forwarding decorator for <see cref="ICompositeVM{VM}"/>.
/// Every public member — including <see cref="IList{VM}"/> and
/// <see cref="INotifyCollectionChanged"/> — delegates to <see cref="_wrappedComposite"/>
/// by default. Subclasses override individual members to customise behaviour.
///
/// See spec/09-forwarding.md §ForwardingCompositeVM and FWD-003 in spec/12-conformance.md.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public abstract class ForwardingCompositeVM<VM> : ICompositeVM<VM>, IDisposable
    where VM : class, IComponentVM
{
    /// <summary>The wrapped composite instance that all members delegate to by default.</summary>
    protected readonly ICompositeVM<VM> _wrappedComposite;

    /// <summary>Initialises the decorator with the composite to wrap.</summary>
    protected ForwardingCompositeVM(ICompositeVM<VM> wrapped)
        => _wrappedComposite = wrapped ?? throw new ArgumentNullException(nameof(wrapped));

    // ── IComponentVM: identity ─────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual string Name => _wrappedComposite.Name;

    /// <inheritdoc/>
    public virtual string Hint => _wrappedComposite.Hint;

    /// <inheritdoc/>
    public virtual ViewModelType Type => _wrappedComposite.Type;

    // ── IComponentVM: state ────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool IsCurrent => _wrappedComposite.IsCurrent;

    /// <inheritdoc/>
    public virtual bool IsConstructed => _wrappedComposite.IsConstructed;

    /// <inheritdoc/>
    public virtual Lifecycle.ConstructionStatus Status => _wrappedComposite.Status;

    // ── IComponentVM: commands ─────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual System.Windows.Input.ICommand SelectCommand => _wrappedComposite.SelectCommand;

    /// <inheritdoc/>
    public virtual System.Windows.Input.ICommand DeselectCommand => _wrappedComposite.DeselectCommand;

    /// <inheritdoc/>
    public virtual System.Windows.Input.ICommand SelectNextCommand => _wrappedComposite.SelectNextCommand;

    /// <inheritdoc/>
    public virtual System.Windows.Input.ICommand SelectPreviousCommand => _wrappedComposite.SelectPreviousCommand;

    /// <inheritdoc/>
    public virtual System.Windows.Input.ICommand ReconstructCommand => _wrappedComposite.ReconstructCommand;

    // ── IComponentVM: lifecycle ────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool CanConstruct() => _wrappedComposite.CanConstruct();

    /// <inheritdoc/>
    public virtual void Construct() => _wrappedComposite.Construct();

    /// <inheritdoc/>
    public virtual Task ConstructAsync() => _wrappedComposite.ConstructAsync();

    /// <inheritdoc/>
    public virtual bool CanDestruct() => _wrappedComposite.CanDestruct();

    /// <inheritdoc/>
    public virtual void Destruct() => _wrappedComposite.Destruct();

    /// <inheritdoc/>
    public virtual Task DestructAsync() => _wrappedComposite.DestructAsync();

    /// <inheritdoc/>
    public virtual bool CanReconstruct() => _wrappedComposite.CanReconstruct();

    /// <inheritdoc/>
    public virtual void Reconstruct() => _wrappedComposite.Reconstruct();

    /// <inheritdoc/>
    public virtual Task ReconstructAsync() => _wrappedComposite.ReconstructAsync();

    // ── IComponentVM: selection ────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual bool CanSelect() => _wrappedComposite.CanSelect();

#pragma warning disable CA1716 // 'Select' is the spec-mandated name per spec/05-component-vm.md
    /// <inheritdoc/>
    public virtual void Select() => _wrappedComposite.Select();
#pragma warning restore CA1716

    /// <inheritdoc/>
    public virtual bool CanDeselect() => _wrappedComposite.CanDeselect();

    /// <inheritdoc/>
    public virtual void Deselect() => _wrappedComposite.Deselect();

    // ── ICompositeVM<VM>: Current and selection ────────────────────────────

    /// <inheritdoc/>
    public virtual VM? Current
    {
        get => _wrappedComposite.Current;
        set => _wrappedComposite.Current = value;
    }

    /// <inheritdoc/>
    public virtual void SelectComponent(VM vm) => _wrappedComposite.SelectComponent(vm);

    /// <inheritdoc/>
    public virtual void DeselectComponent(VM vm) => _wrappedComposite.DeselectComponent(vm);

    /// <inheritdoc/>
    public virtual bool CanSelectComponent(VM vm) => _wrappedComposite.CanSelectComponent(vm);

    // ── IList<VM>: query ───────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual int Count => _wrappedComposite.Count;

    /// <inheritdoc/>
    public virtual bool IsReadOnly => _wrappedComposite.IsReadOnly;

    /// <inheritdoc/>
    public virtual VM this[int index]
    {
        get => _wrappedComposite[index];
        set => _wrappedComposite[index] = value;
    }

    /// <inheritdoc/>
    public virtual int IndexOf(VM item) => _wrappedComposite.IndexOf(item);

    /// <inheritdoc/>
    public virtual bool Contains(VM item) => _wrappedComposite.Contains(item);

    /// <inheritdoc/>
    public virtual void CopyTo(VM[] array, int arrayIndex) => _wrappedComposite.CopyTo(array, arrayIndex);

    // ── IList<VM>: mutation ────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual void Add(VM item) => _wrappedComposite.Add(item);

    /// <inheritdoc/>
    public virtual bool Remove(VM item) => _wrappedComposite.Remove(item);

    /// <inheritdoc/>
    public virtual void Insert(int index, VM item) => _wrappedComposite.Insert(index, item);

    /// <inheritdoc/>
    public virtual void RemoveAt(int index) => _wrappedComposite.RemoveAt(index);

    /// <inheritdoc/>
    public virtual void Clear() => _wrappedComposite.Clear();

    // ── IEnumerable<VM> ────────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual IEnumerator<VM> GetEnumerator() => _wrappedComposite.GetEnumerator();

    /// <inheritdoc/>
    IEnumerator IEnumerable.GetEnumerator() => ((IEnumerable)_wrappedComposite).GetEnumerator();

    // ── INotifyCollectionChanged ───────────────────────────────────────────

    /// <inheritdoc/>
    public event NotifyCollectionChangedEventHandler? CollectionChanged
    {
        add => _wrappedComposite.CollectionChanged += value;
        remove => _wrappedComposite.CollectionChanged -= value;
    }

    // ── INotifyPropertyChanged ─────────────────────────────────────────────

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged
    {
        add => _wrappedComposite.PropertyChanged += value;
        remove => _wrappedComposite.PropertyChanged -= value;
    }

    // ── IDisposable ────────────────────────────────────────────────────────

    /// <inheritdoc/>
    public virtual void Dispose()
    {
        _wrappedComposite.Dispose();
        GC.SuppressFinalize(this);
    }
}
#pragma warning restore CA1051
#pragma warning restore CA1715
