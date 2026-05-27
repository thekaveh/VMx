// Management capability contract. See spec/14-capabilities.md §Management.

export interface IManagable<T> {
  canManage(item: T): boolean;
  manage(item: T): void;
}
