// Lifecycle capability contracts. See spec/14-capabilities.md §Lifecycle.
// These three are baseline: every core VM trivially satisfies them.

export interface IConstructable {
  canConstruct(): boolean;
  construct(): void;
}

export interface IDestructable {
  canDestruct(): boolean;
  destruct(): void;
}

export interface IReconstructable {
  canReconstruct(): boolean;
  reconstruct(): void;
}
