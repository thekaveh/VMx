/**
 * CompositeVM<VM> — non-modeled composite viewmodel.
 *
 * See spec/06-composite-vm.md.
 */
import { CompositeVMBase } from "./compositeVMBase.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";

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

  build(): CompositeVM<VM> {
    if (this.#name === null) throw new Error("BuilderValidationError: name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("BuilderValidationError: services (hub, dispatcher) are required");
    if (this.#childrenFactory === null)
      throw new Error("BuilderValidationError: children factory is required");
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
    });
  }
}
