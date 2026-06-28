using System.Collections.Specialized;
using VMx.Components;

namespace VMx.Groups;

/// <summary>
/// A container viewmodel with an ordered list of peer children and no selection slot.
/// Unlike <c>ICompositeVM&lt;VM&gt;</c>, there is no <c>Current</c> property and no
/// child-navigation commands — children are peers, not navigable.
///
/// <para>
/// <c>SelectCommand</c> and <c>DeselectCommand</c> (inherited from <see cref="IComponentVM"/>)
/// ARE present and operate on the group's own selection within its parent, not on the children.
/// </para>
///
/// See spec/07-group-vm.md §Members.
/// </summary>
/// <typeparam name="VM">The child viewmodel type.</typeparam>
public interface IGroupVM<VM> : IComponentVM, IList<VM>, INotifyCollectionChanged
    where VM : class, IComponentVM
{
}
