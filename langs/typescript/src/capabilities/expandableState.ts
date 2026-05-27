/**
 * ExpandableState — composition-friendly helper for expand/collapse.
 *
 * See spec/05-component-vm.md §IExpandable integration and ADR-0015.
 */
import { Subject, type Observable } from "rxjs";
import {
  declareCapabilities,
  type CapabilityName,
} from "./registry.js";
import type {
  ICollapsible,
  IExpandable,
  IExpansionTogglable,
} from "./expansion.js";

const CAPS: CapabilityName[] = [
  "IExpandable",
  "ICollapsible",
  "IExpansionTogglable",
];

export class ExpandableState
  implements IExpandable, ICollapsible, IExpansionTogglable
{
  #expanded: boolean;
  readonly #changes = new Subject<boolean>();
  #disposed = false;

  constructor(initiallyExpanded = false) {
    this.#expanded = initiallyExpanded;
    declareCapabilities(this, ...CAPS);
  }

  get isExpanded(): boolean {
    return this.#expanded;
  }

  get isExpandedChanged(): Observable<boolean> {
    return this.#changes.asObservable();
  }

  canExpand(): boolean {
    return !this.#expanded;
  }

  expand(): void {
    if (this.#expanded) return;
    this.#expanded = true;
    this.#changes.next(true);
  }

  canCollapse(): boolean {
    return this.#expanded;
  }

  collapse(): void {
    if (!this.#expanded) return;
    this.#expanded = false;
    this.#changes.next(false);
  }

  canToggleExpansion(): boolean {
    return true;
  }

  toggleExpansion(): void {
    if (this.#expanded) this.collapse();
    else this.expand();
  }

  /** Idempotent: subsequent calls are a no-op. */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#changes.complete();
  }
}
