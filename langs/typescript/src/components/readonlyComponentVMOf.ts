/**
 * ReadonlyComponentVMOf<M> — readonly modeled leaf viewmodel.
 *
 * Model is fixed at build time; no setter is exposed.
 * See spec/05-component-vm.md §Readonly variant.
 */
import { ComponentVMBase } from "./componentVMBase.js";
import { ViewModelType } from "./types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

export class ReadonlyComponentVMOf<M> extends ComponentVMBase {
  readonly #model: M;
  readonly #modeledHint: string;

  constructor(opts: {
    name: string;
    hint: string;
    model: M;
    modeledHinter: (m: M) => string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    background?: boolean;
  }) {
    super(opts);
    this.#model = opts.model;
    this.#modeledHint = opts.modeledHinter(opts.model);
  }

  get type(): ViewModelType {
    return ViewModelType.ReadOnlyComponent;
  }

  get model(): M {
    return this.#model;
  }

  get modeledHint(): string {
    return this.#modeledHint;
  }

  static builder<M>(): ReadonlyComponentVMOfBuilder<M> {
    return new ReadonlyComponentVMOfBuilder<M>();
  }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

const SENTINEL = Symbol("not-set");

export class ReadonlyComponentVMOfBuilder<M> {
  #name: string | null = null;
  #hint = "";
  #model: M | typeof SENTINEL = SENTINEL;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #modeledHinter: ((m: M) => string) | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;
  #background = false;

  constructor(from?: ReadonlyComponentVMOfBuilder<M>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#model = from.#model;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#modeledHinter = from.#modeledHinter;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
      this.#background = from.#background;
    }
  }

  name(value: string): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#name = value;
    return b;
  }

  hint(value: string): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#hint = value;
    return b;
  }

  model(value: M): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#model = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  modeledHinter(fn: (m: M) => string): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#modeledHinter = fn;
    return b;
  }

  onConstruct(cb: () => void): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#onDestruct = cb;
    return b;
  }

  background(value: boolean): ReadonlyComponentVMOfBuilder<M> {
    const b = new ReadonlyComponentVMOfBuilder<M>(this);
    b.#background = value;
    return b;
  }

  build(): ReadonlyComponentVMOf<M> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#model === SENTINEL) throw new BuilderValidationError("model");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");

    const hinter = this.#modeledHinter ?? ((): string => "");
    const model = this.#model;
    return new ReadonlyComponentVMOf<M>({
      name: this.#name,
      hint: this.#hint,
      model,
      modeledHinter: hinter,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
      background: this.#background,
    });
  }
}
