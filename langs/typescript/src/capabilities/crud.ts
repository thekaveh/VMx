// CRUD capability contracts. See spec/14-capabilities.md §CRUD.

export interface INewCreatable {
  canCreateNew(): boolean;
  createNew(): void;
}

export interface IDeletable<T> {
  canDelete(item: T): boolean;
  delete(item: T): void;
}

export interface IUpdatable<T> {
  canUpdate(item: T): boolean;
  update(item: T): void;
}

export interface ISavable<T> {
  canSave(item: T): boolean;
  save(item: T): void;
}
