import type { AsyncResourceState, AsyncResourceVM } from "@thekaveh/vmx";

import { useVm } from "./useVm.js";

/** Observe the complete discriminated state of an AsyncResourceVM. */
export function useAsyncResource<T>(resource: AsyncResourceVM<T>): AsyncResourceState<T> {
  return useVm(resource, (current) => current.state);
}
