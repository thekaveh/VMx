namespace VMx.Forms;

/// <summary>
/// Optional interface-shaped alternative to the <c>Func&lt;TM, Task&gt;</c> delegate persister.
/// Consumers whose persister is a class may implement this interface and pass it to the
/// <see cref="FormVM{TM}"/> constructor overload that accepts an <see cref="IFormPersister{TM}"/>.
///
/// See spec/20-form-vm.md §2 and ADR-0030 §4.
/// </summary>
/// <typeparam name="TM">Domain model type.</typeparam>
public interface IFormPersister<in TM>
{
    /// <summary>Persist <paramref name="model"/>. Throw on failure.</summary>
    Task PersistAsync(TM model);
}
