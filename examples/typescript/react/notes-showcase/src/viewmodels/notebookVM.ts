/**
 * NotebookVM — leaf VM for a notebook tree node.
 *
 * Capabilities (scenario §6.2): ISelectable, IExpandable, ICollapsible,
 * IExpansionTogglable, IReconstructable.
 *
 * VMx-API adaptation: the modeled `ComponentVMOf<M>` would force a fixed
 * model setter pipeline; we layer the capability mix-ins manually by
 * subclassing `ComponentVMBase` (TypeScript doesn't seal classes, but the
 * structural shape we need is bespoke enough that direct subclassing is
 * cleaner than composing `ComponentVMOf`). Mirrors the C# pattern verbatim
 * (`NotebookVM : ComponentVMBase, ISelectable, …`).
 */
import {
  ComponentVMBase,
  declareCapabilities,
  ExpandableState,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

import type { NotebookModel } from "../models/notebookModel.js";

const SENTINEL = Symbol("not-set");

export class NotebookVM extends ComponentVMBase {
  readonly #expansion: ExpandableState;
  #model: NotebookModel;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    model: NotebookModel;
    initiallyExpanded: boolean;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#model = opts.model;
    this.#expansion = new ExpandableState(opts.initiallyExpanded);
    declareCapabilities(
      this,
      "ISelectable",
      "IExpandable",
      "ICollapsible",
      "IExpansionTogglable",
      "IReconstructable",
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  /** Public hub accessor — see C# `NotebookVM.Hub` for the rationale. */
  get hub(): IMessageHub {
    return this._hub;
  }

  /** Current notebook model. Equality-guarded setter emits hub messages. */
  get model(): NotebookModel {
    return this.#model;
  }

  set model(value: NotebookModel) {
    if (this.#model === value) return;
    this.#model = value;
    this._notifyPropertyChanged("model");
    this._notifyPropertyChanged("notebookName");
  }

  /** Notebook display name (proxy on `model`). */
  get notebookName(): string {
    return this.#model.name;
  }

  // ── IExpandable / ICollapsible / IExpansionTogglable ──────────────────────

  get isExpanded(): boolean {
    return this.#expansion.isExpanded;
  }

  canExpand(): boolean {
    return this.#expansion.canExpand();
  }

  expand(): void {
    if (!this.#expansion.canExpand()) return;
    this.#expansion.expand();
    this.#emitExpansionChange();
  }

  canCollapse(): boolean {
    return this.#expansion.canCollapse();
  }

  collapse(): void {
    if (!this.#expansion.canCollapse()) return;
    this.#expansion.collapse();
    this.#emitExpansionChange();
  }

  canToggleExpansion(): boolean {
    return this.#expansion.canToggleExpansion();
  }

  toggleExpansion(): void {
    if (this.#expansion.isExpanded) this.collapse();
    else this.expand();
  }

  #emitExpansionChange(): void {
    this._notifyPropertyChanged("isExpanded");
  }

  protected override _onDispose(): void {
    this.#expansion.dispose();
    super._onDispose();
  }

  /** Returns a new empty builder. */
  static builder(): NotebookVMBuilder {
    return new NotebookVMBuilder();
  }
}

export class NotebookVMBuilder {
  #name: string | null = null;
  #hint = "";
  #model: NotebookModel | typeof SENTINEL = SENTINEL;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #initiallyExpanded = false;

  constructor(from?: NotebookVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#model = from.#model;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#initiallyExpanded = from.#initiallyExpanded;
    }
  }

  name(value: string): NotebookVMBuilder {
    const b = new NotebookVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NotebookVMBuilder {
    const b = new NotebookVMBuilder(this);
    b.#hint = value;
    return b;
  }

  model(value: NotebookModel): NotebookVMBuilder {
    const b = new NotebookVMBuilder(this);
    b.#model = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NotebookVMBuilder {
    const b = new NotebookVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  initiallyExpanded(value: boolean): NotebookVMBuilder {
    const b = new NotebookVMBuilder(this);
    b.#initiallyExpanded = value;
    return b;
  }

  build(): NotebookVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#model === SENTINEL) throw new Error("model is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services (hub + dispatcher) are required");
    return new NotebookVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      model: this.#model,
      initiallyExpanded: this.#initiallyExpanded,
    });
  }
}
