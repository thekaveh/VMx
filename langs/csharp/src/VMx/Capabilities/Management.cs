namespace VMx.Capabilities;

// Capability interface from spec/14-capabilities.md §Management.

/// <summary>Capability: the implementer can manage an item of type <typeparamref name="T"/>.</summary>
public interface IManagable<in T>
{
    /// <summary>Returns true when <see cref="Manage"/> is valid to call for <paramref name="item"/>.</summary>
    bool CanManage(T item);

    /// <summary>Manages <paramref name="item"/>.</summary>
    void Manage(T item);
}
