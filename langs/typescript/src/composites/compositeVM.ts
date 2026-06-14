/**
 * CompositeVM<VM> — non-modeled composite viewmodel.
 *
 * See spec/06-composite-vm.md.
 */
import { CompositeVMBase } from "./compositeVMBase.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

export class CompositeVM<VM extends ComponentVMBase> extends CompositeVMBase<VM> {
  readonly #childrenFactory: (() => Iterable<VM>) | null;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    asyncSelection?: boolean;
    autoConstructOnAdd?: boolean;
    childrenFactory?: (() => Iterable<VM>) | null;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    currentSelector?: ((xs: Iterable<VM>) => VM | null) | null;
    onCurrentChanged?: ((vm: VM | null) => void) | null;
  }) {
    super(opts);
    this.#childrenFactory = opts.childrenFactory ?? null;
  }

  protected override _populateChildren(): void {
    if (this.#childrenFactory === null) return;
    for (const child of this.#childrenFactory()) {
      this.add(child);
    }
  }

  static builder<VM extends ComponentVMBase>(): CompositeVMBuilder<VM> {
    return new CompositeVMBuilder<VM>();
  }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export class CompositeVMBuilder<VM extends ComponentVMBase> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #asyncSelection = false;
  #autoConstructOnAdd = false;
  #childrenFactory: (() => Iterable<VM>) | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;
  #currentSelector: ((xs: Iterable<VM>) => VM | null) | null = null;
  #onCurrentChanged: ((vm: VM | null) => void) | null = null;

  constructor(from?: CompositeVMBuilder<VM>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#asyncSelection = from.#asyncSelection;
      this.#autoConstructOnAdd = from.#autoConstructOnAdd;
      this.#childrenFactory = from.#childrenFactory;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
      this.#currentSelector = from.#currentSelector;
      this.#onCurrentChanged = from.#onCurrentChanged;
    }
  }

  name(value: string): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#name = value;
    return b;
  }

  hint(value: string): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  asyncSelection(value: boolean): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#asyncSelection = value;
    return b;
  }

  autoConstructOnAdd(value: boolean): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#autoConstructOnAdd = value;
    return b;
  }

  children(factory: () => Iterable<VM>): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#childrenFactory = factory;
    return b;
  }

  onConstruct(cb: () => void): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
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
  current(selector: (xs: Iterable<VM>) => VM | null): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
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
  ): CompositeVMBuilder<VM> {
    const b = new CompositeVMBuilder<VM>(this);
    b.#onCurrentChanged = callback;
    return b;
  }

  build(): CompositeVM<VM> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");
    if (this.#childrenFactory === null)
      throw new BuilderValidationError("children");
    return new CompositeVM<VM>({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      asyncSelection: this.#asyncSelection,
      autoConstructOnAdd: this.#autoConstructOnAdd,
      childrenFactory: this.#childrenFactory,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
      currentSelector: this.#currentSelector,
      onCurrentChanged: this.#onCurrentChanged,
    });
  }
}
