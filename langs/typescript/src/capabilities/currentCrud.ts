// Container-current capability contracts. See spec/14-capabilities.md §Container-current.

export interface ICurrentDeletable {
  canDeleteCurrent(): boolean;
  deleteCurrent(): void;
}

export interface ICurrentUpdatable {
  canUpdateCurrent(): boolean;
  updateCurrent(): void;
}
