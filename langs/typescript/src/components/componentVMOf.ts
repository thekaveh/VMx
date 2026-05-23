/**
 * ComponentVMOf<M> — modeled leaf viewmodel with settable model.
 *
 * See spec/05-component-vm.md §Modeled variant.
 */
import { ComponentVMBase } from "./componentVMBase.js";
import { ViewModelType } from "./types.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";

export class ComponentVMOf<M> extends ComponentVMBase {
  #model: M;
  readonly #modeledHinter: (m: M) => string;
  readonly #onModelChangedCb: ((m: M) => void) | null;
  #modeledHint: string;
  readonly #vmType: ViewModelType;

  constructor(opts: {
    name: string;
    hint: string;
    initialModel: M;
    modeledHinter: (m: M) => string;
    onModelChanged?: ((m: M) => void) | null;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    background?: boolean;
    vmType?: ViewModelType;
  }) {
    super(opts);
    this.#model = opts.initialModel;
    this.#modeledHinter = opts.modeledHinter;
    this.#onModelChangedCb = opts.onModelChanged ?? null;
    this.#modeledHint = opts.modeledHinter(opts.initialModel);
    this.#vmType = opts.vmType ?? ViewModelType.Component;
  }

  get type(): ViewModelType {
    return this.#vmType;
  }

  get model(): M {
    return this.#model;
  }

  set model(value: M) {
    this._setModel(value);
  }

  get modeledHint(): string {
    return this.#modeledHint;
  }

  protected _setModel(value: M): void {
    if (this.#model === value) return;
    this.#model = value;

    this._hub.send(PropertyChangedMessage.create(this, this._name, "Model"));
    this._raisePropertyChanged("model");

    const newHint = this.#modeledHinter(value);
    if (this.#modeledHint !== newHint) {
      this.#modeledHint = newHint;
      this._hub.send(PropertyChangedMessage.create(this, this._name, "ModeledHint"));
      this._raisePropertyChanged("modeledHint");
    }

    if (this.#onModelChangedCb !== null) {
      this.#onModelChangedCb(value);
    }
  }

  static builder<M>(): ComponentVMOfBuilder<M> {
    return new ComponentVMOfBuilder<M>();
  }
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

const SENTINEL = Symbol("not-set");

export class ComponentVMOfBuilder<M> {
  #name: string | null = null;
  #hint = "";
  #model: M | typeof SENTINEL = SENTINEL;
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #modeledHinter: ((m: M) => string) | null = null;
  #onModelChanged: ((m: M) => void) | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;
  #background = false;
  #vmType: ViewModelType = ViewModelType.Component;

  constructor(from?: ComponentVMOfBuilder<M>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#model = from.#model;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#modeledHinter = from.#modeledHinter;
      this.#onModelChanged = from.#onModelChanged;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
      this.#background = from.#background;
      this.#vmType = from.#vmType;
    }
  }

  name(value: string): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#name = value;
    return b;
  }

  hint(value: string): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#hint = value;
    return b;
  }

  model(value: M): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#model = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  modeledHinter(fn: (m: M) => string): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#modeledHinter = fn;
    return b;
  }

  onModelChanged(cb: (m: M) => void): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#onModelChanged = cb;
    return b;
  }

  onConstruct(cb: () => void): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#onDestruct = cb;
    return b;
  }

  background(value: boolean): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#background = value;
    return b;
  }

  vmType(value: ViewModelType): ComponentVMOfBuilder<M> {
    const b = new ComponentVMOfBuilder<M>(this);
    b.#vmType = value;
    return b;
  }

  build(): ComponentVMOf<M> {
    if (this.#name === null) throw new Error("BuilderValidationError: name is required");
    if (this.#model === SENTINEL) throw new Error("BuilderValidationError: model is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("BuilderValidationError: services (hub, dispatcher) are required");

    const hinter = this.#modeledHinter ?? ((): string => "");
    const initialModel = this.#model;
    return new ComponentVMOf<M>({
      name: this.#name,
      hint: this.#hint,
      initialModel,
      modeledHinter: hinter,
      onModelChanged: this.#onModelChanged,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
      background: this.#background,
      vmType: this.#vmType,
    });
  }
}
