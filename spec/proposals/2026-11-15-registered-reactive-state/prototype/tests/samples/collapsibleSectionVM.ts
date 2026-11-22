/**
 * Sample view-model: a section that collapses to a placeholder while it has no results, unless the user opens it or
 * it is forced open. One prototype-only change (R15.5): the ExpandableState is wrapped in `tracked(...)`, because
 * VMx 3.30.0 does not track `isExpanded` natively.
 */
import { ComponentVM, ExpandableState, type IDispatcher, type IMessageHub } from "@thekaveh/vmx";
import { tracked } from "../../src/index.js";

export const SECTION_TEXT = { show: "Show", hide: "Hide" } as const;

export interface CollapsibleSectionVMOptions {
  readonly hub: IMessageHub;
  readonly dispatcher: IDispatcher;
  readonly key: string;
  readonly noResults: boolean;
  readonly placeholder: string;
  readonly onCollapsedChange?: () => void;
}

export class CollapsibleSectionVM extends ComponentVM {
  readonly toggleCommand = this.relayCommand(
    () => this.#expansion.toggleExpansion(),
    () => this.noResults && !this.forcedOpen,
  );
  declare readonly placeholder: string;
  declare readonly noResults: boolean;
  declare readonly forcedOpen: boolean;
  readonly #expansion = this.own(tracked(new ExpandableState(false)));
  readonly #set;

  constructor(o: CollapsibleSectionVMOptions) {
    super({ name: `section:${o.key}`, hint: "", hub: o.hub, dispatcher: o.dispatcher });
    this.#set = this.observable({
      placeholder: o.noResults ? o.placeholder : "",
      noResults: o.noResults,
      forcedOpen: false,
    });
    this.computed("isCollapsed", "toggleLabel", "showsToggle");
    if (o.onCollapsedChange) this.reaction(() => this.isCollapsed, o.onCollapsedChange, { alive: true });
  }

  update(noResults: boolean, placeholder: string, forcedOpen = false): void {
    this.#set({ placeholder: noResults ? placeholder : "", noResults, forcedOpen });
  }

  get isCollapsed(): boolean {
    return this.noResults && !this.forcedOpen && !this.#expansion.isExpanded;
  }

  get showsToggle(): boolean {
    return this.noResults && this.toggleCommand.canExecute();
  }

  get toggleLabel(): string {
    return this.isCollapsed ? SECTION_TEXT.show : SECTION_TEXT.hide;
  }

  reveal(): void {
    if (this.isCollapsed) this.#expansion.expand();
  }
}
