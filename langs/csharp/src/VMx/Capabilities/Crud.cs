namespace VMx.Capabilities;

// Capability interfaces from spec/14-capabilities.md §CRUD.

/// <summary>Capability: the implementer can create a new item.</summary>
public interface INewCreatable
{
    /// <summary>Returns true when <see cref="CreateNew"/> is valid to call.</summary>
    bool CanCreateNew();

    /// <summary>Creates a new item.</summary>
    void CreateNew();
}

/// <summary>Capability: the implementer can delete an item of type <typeparamref name="T"/>.</summary>
public interface IDeletable<in T>
{
    /// <summary>Returns true when <see cref="Delete"/> is valid to call for <paramref name="item"/>.</summary>
    bool CanDelete(T item);

    /// <summary>Deletes <paramref name="item"/>.</summary>
    void Delete(T item);
}

/// <summary>Capability: the implementer can update an item of type <typeparamref name="T"/>.</summary>
public interface IUpdatable<in T>
{
    /// <summary>Returns true when <see cref="Update"/> is valid to call for <paramref name="item"/>.</summary>
    bool CanUpdate(T item);

    /// <summary>Updates <paramref name="item"/>.</summary>
    void Update(T item);
}

/// <summary>Capability: the implementer can save an item of type <typeparamref name="T"/>.</summary>
public interface ISavable<in T>
{
    /// <summary>Returns true when <see cref="Save"/> is valid to call for <paramref name="item"/>.</summary>
    bool CanSave(T item);

    /// <summary>Saves <paramref name="item"/>.</summary>
    void Save(T item);
}
