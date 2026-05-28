// Capability registry. Spec/14-capabilities.md, ADR-0010.
//
// TypeScript interfaces are structural, so a runtime answer to
// "does this object satisfy ISelectable?" requires an explicit marker, not
// structural matching (otherwise a bare ComponentVM with a `select()` method
// would falsely report true — violating spec rule 2 and CAP-020).
//
// Implementers opt in by calling `declareCapabilities(this, "ISelectable", ...)`
// from their constructor. The `hasCapability` helper consults the marker.

export const CAPABILITIES = Symbol("vmx.capabilities");

export type CapabilityName =
  | "ISelectable"
  | "IDeselectable"
  | "ISelectionTogglable"
  | "IExpandable"
  | "ICollapsible"
  | "IExpansionTogglable"
  | "IConstructable"
  | "IDestructable"
  | "IReconstructable"
  | "IClosable"
  | "IApprovable"
  | "ICancelable"
  | "ISearchable"
  | "INewCreatable"
  | "IDeletable"
  | "IUpdatable"
  | "ISavable"
  | "ICurrentDeletable"
  | "ICurrentUpdatable"
  | "IManagable"
  | "IFilterable"
  | "IPageable";

interface CapabilityHolder {
  [CAPABILITIES]?: Set<CapabilityName>;
}

export function declareCapabilities(
  obj: object,
  ...caps: CapabilityName[]
): void {
  const holder = obj as CapabilityHolder;
  let set = holder[CAPABILITIES];
  if (!set) {
    set = new Set<CapabilityName>();
    Object.defineProperty(obj, CAPABILITIES, {
      value: set,
      writable: false,
      enumerable: false,
      configurable: false,
    });
  }
  for (const cap of caps) set.add(cap);
}

export function hasCapability(
  obj: unknown,
  cap: CapabilityName,
): boolean {
  if (typeof obj !== "object" || obj === null) return false;
  const holder = obj as CapabilityHolder;
  const set = holder[CAPABILITIES];
  return set !== undefined && set.has(cap);
}
