/**
 * CompositeVMOf<M, VM> — modeled composite viewmodel.
 *
 * Children come from a model factory: () => Iterable<M> plus a mapper M => VM.
 * See spec/06-composite-vm.md §Modeled variant.
 */
import { CompositeVMBase } from "./compositeVMBase.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

export class CompositeVMOf<M, VM extends ComponentVMBase> extends CompositeVMBase<VM> {
  readonly #childrenModels: () => Iterable<M>;
  readonly #childModelToChildVM: (m: M) => VM;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    asyncSelection?: boolean;
    autoConstructOnAdd?: boolean;
    childrenModels: () => Iterable<M>;
    childModelToChildViewModel: (m: M) => VM;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    currentSelector?: ((xs: Iterable<VM>) => VM | null) | null;
    onCurrentChanged?: ((vm: VM | null) => void) | null;
  }) {
    super(opts);
    this.#childrenModels = opts.childrenModels;
    this.#childModelToChildVM = opts.childModelToChildViewModel;
  }

  protected override _populateChildren(): void {
    for (const model of this.#childrenModels()) {
      const child = this.#childModelToChildVM(model);
      this.add(child);
    }
  }

  static builder<M, VM extends ComponentVMBase>(): CompositeVMOfBuilder<M, VM> {
    return new CompositeVMOfBuilder<M, VM>();
  }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export class CompositeVMOfBuilder<M, VM extends ComponentVMBase> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #asyncSelection = false;
  #autoConstructOnAdd = false;
  #childrenModels: (() => Iterable<M>) | null = null;
  #childModelToChildViewModel: ((m: M) => VM) | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;
  #currentSelector: ((xs: Iterable<VM>) => VM | null) | null = null;
  #onCurrentChanged: ((vm: VM | null) => void) | null = null;

  constructor(from?: CompositeVMOfBuilder<M, VM>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#asyncSelection = from.#asyncSelection;
      this.#autoConstructOnAdd = from.#autoConstructOnAdd;
      this.#childrenModels = from.#childrenModels;
      this.#childModelToChildViewModel = from.#childModelToChildViewModel;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
      this.#currentSelector = from.#currentSelector;
      this.#onCurrentChanged = from.#onCurrentChanged;
    }
  }

  name(value: string): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#name = value;
    return b;
  }

  hint(value: string): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  asyncSelection(value: boolean): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#asyncSelection = value;
    return b;
  }

  autoConstructOnAdd(value: boolean): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#autoConstructOnAdd = value;
    return b;
  }

  childrenModels(factory: () => Iterable<M>): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#childrenModels = factory;
    return b;
  }

  childModelToChildViewModel(mapper: (m: M) => VM): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#childModelToChildViewModel = mapper;
    return b;
  }

  onConstruct(cb: () => void): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#onDestruct = cb;
    return b;
  }

  /**
   * Sets an optional selector that picks the initial `current` child during
   * `construct()`, after every child has reached `Constructed` but before the
   * composite itself reaches `Constructed`. If the selector returns `null` or
   * a value not in the composite, `current` is left unchanged and no
   * `PropertyChangedMessage("current")` is published. See ADR-0042 and
   * spec/06 §3.X.
   */
  current(
    selector: (xs: Iterable<VM>) => VM | null,
  ): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#currentSelector = selector;
    return b;
  }

  /**
   * Sets an optional callback invoked synchronously after every `current`
   * change, immediately after the hub `PropertyChangedMessage("current")` is
   * published. Receives the new `current` value (or `null` on deselection).
   * Fires once for the initial assignment driven by `current(selector)`.
   * See ADR-0042 and spec/06 §3.X.
   */
  onCurrentChanged(
    callback: (vm: VM | null) => void,
  ): CompositeVMOfBuilder<M, VM> {
    const b = new CompositeVMOfBuilder<M, VM>(this);
    b.#onCurrentChanged = callback;
    return b;
  }

  build(): CompositeVMOf<M, VM> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");
    if (this.#childrenModels === null)
      throw new BuilderValidationError("childrenModels");
    if (this.#childModelToChildViewModel === null)
      throw new BuilderValidationError("childModelToChildViewModel");
    return new CompositeVMOf<M, VM>({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      asyncSelection: this.#asyncSelection,
      autoConstructOnAdd: this.#autoConstructOnAdd,
      childrenModels: this.#childrenModels,
      childModelToChildViewModel: this.#childModelToChildViewModel,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
      currentSelector: this.#currentSelector,
      onCurrentChanged: this.#onCurrentChanged,
    });
  }
}
