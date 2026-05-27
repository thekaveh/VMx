// Selection capability contracts. See spec/14-capabilities.md §Selection.

export interface ISelectable {
  canSelect(): boolean;
  select(): void;
}

export interface IDeselectable {
  canDeselect(): boolean;
  deselect(): void;
}

export interface ISelectionTogglable {
  canToggleSelection(): boolean;
  toggleSelection(): void;
}
