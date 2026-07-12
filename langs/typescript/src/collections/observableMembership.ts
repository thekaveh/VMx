import type { Subscription } from "rxjs";

/** Read-only ordered membership with payload-free structural notifications. */
export interface ObservableMembershipSource<T> {
  snapshot(): readonly T[];
  subscribeMembership(callback: () => void): Subscription;
}
