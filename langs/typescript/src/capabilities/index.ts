// VMx capability micro-interfaces. See spec/14-capabilities.md and ADR-0010.

export {
  CAPABILITIES,
  type CapabilityName,
  declareCapabilities,
  hasCapability,
} from "./registry.js";

export type {
  IDeselectable,
  ISelectable,
  ISelectionTogglable,
} from "./selection.js";
export type {
  ICollapsible,
  IExpandable,
  IExpansionTogglable,
} from "./expansion.js";
export type {
  IConstructable,
  IDestructable,
  IReconstructable,
} from "./lifecycleCapabilities.js";
export type { IApprovable, ICancelable, IClosable } from "./dialog.js";
export type { ISearchable } from "./search.js";
export type {
  IDeletable,
  INewCreatable,
  ISavable,
  IUpdatable,
} from "./crud.js";
export type {
  ICurrentDeletable,
  ICurrentUpdatable,
} from "./currentCrud.js";
export type { IManagable } from "./management.js";
export { ExpandableState } from "./expandableState.js";
