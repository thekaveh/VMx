/**
 * Internal helper — resolve a VM's hub.
 *
 * VMx TS's `ComponentVMBase` stores the hub on a `protected` getter `_hub`
 * (private field; not directly reachable from outside the class). The
 * notes-showcase Phase 3.c VMs each expose a public `hub` getter (parity with
 * the Python flavour's `hub` accessor — see Phase 4.b
 * `_hub_accessor.resolve_hub`). Adapter code therefore relies on the public
 * surface; if a caller passes a bare VMx VM with no `hub` getter, we raise
 * early with a clear error rather than silently no-op.
 *
 * See scenario doc §6.1 (Pure-VM contract): only the adapter is permitted to
 * subscribe to the hub, so this helper is the single place that has to know
 * the convention.
 */
import type { IMessageHub } from "vmx";

interface HasHub {
  readonly hub: IMessageHub;
}

export function resolveHub(vm: object): IMessageHub {
  const candidate = (vm as Partial<HasHub>).hub;
  if (candidate === undefined || candidate === null) {
    throw new Error(
      `VM ${vm.constructor.name} does not expose a public 'hub' getter; ` +
        "adapter bridges cannot subscribe. Add `get hub(): IMessageHub { return this._hub; }` " +
        "as the Phase 3.c notes-showcase VMs do.",
    );
  }
  return candidate;
}
