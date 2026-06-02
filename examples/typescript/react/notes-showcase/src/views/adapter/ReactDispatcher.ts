/**
 * ReactDispatcher — VMx `IDispatcher` for browser-hosted React apps.
 *
 * See scenario doc §7.1 (Dispatcher) and §7.3 (TS adapter signature) and plan
 * §4.c. Mirrors `AvaloniaDispatcher` (Phase 4.a) and `TextualDispatcher`
 * (Phase 4.b).
 *
 * VMx's `IDispatcher` (`langs/typescript/src/services/dispatcher.ts`) exposes
 * two rxjs `SchedulerLike` properties:
 *
 *   - `foreground` — UI-thread work. In React/browser hosts there is no
 *     dedicated UI thread, but we still want foreground work to settle on a
 *     microtask so it runs after the current React render commit (avoiding
 *     "set-state-during-render" warnings). rxjs's `asapScheduler` queues
 *     `Promise.resolve().then(...)` — exactly the microtask semantics React
 *     itself uses for batched-update scheduling.
 *   - `background` — off-main work. We use `asyncScheduler`, which posts
 *     `setTimeout(fn, 0)` (a macrotask) — yields to the browser event loop
 *     for any UI paint / input handling between batches. That matches the
 *     scenario doc's "background = next-tick" intent.
 *
 * **Why not `queueScheduler` for foreground?**
 *   `queueScheduler` is synchronous (drains in place). Calling it during a
 *   React render would re-enter React state updaters mid-commit and trigger
 *   the same warnings React's `act()` is designed to prevent. The microtask
 *   queue (`asapScheduler`) gives the smallest delay that still respects
 *   commit boundaries.
 *
 * **Constructor**: no arguments needed — the browser microtask/timer queues
 * are global. The class is exported (rather than a single static instance)
 * because tests want to construct fresh instances per case, mirroring
 * `RxDispatcher.default()` usage.
 */
import {
  asapScheduler,
  asyncScheduler,
  type SchedulerLike,
} from "rxjs";
import type { IDispatcher } from "@thekaveh/vmx";

export class ReactDispatcher implements IDispatcher {
  readonly foreground: SchedulerLike = asapScheduler;
  readonly background: SchedulerLike = asyncScheduler;
}
