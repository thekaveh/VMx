// Expansion capability contracts. See spec/14-capabilities.md §Expansion.

export interface IExpandable {
  readonly isExpanded: boolean;
  canExpand(): boolean;
  expand(): void;
}

export interface ICollapsible {
  canCollapse(): boolean;
  collapse(): void;
}

export interface IExpansionTogglable {
  canToggleExpansion(): boolean;
  toggleExpansion(): void;
}
