// Search capability contract. See spec/14-capabilities.md §Search.

export interface ISearchable {
  searchTerm: string;
  canSearch(): boolean;
  search(): void;
}
