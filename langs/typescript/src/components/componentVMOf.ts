/**
 * ComponentVMOf<M> — modeled leaf viewmodel with settable model.
 *
 * See spec/05-component-vm.md §Modeled variant.
 */
import { ComponentVMBase } from "./componentVMBase.js";
import { ViewModelType } from "./types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { NullMessageHub } from "../services/nullMessageHub.js";
import { NullDispatcher } from "../services/nullDispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

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

    this._notifyPropertyChanged("model");

    const newHint = this.#modeledHinter(value);
    if (this.#modeledHint !== newHint) {
      this.#modeledHint = newHint;
      this._notifyPropertyChanged("modeledHint");
    }

    if (this.#onModelChangedCb !== null) {
      this.#onModelChangedCb(value);
    }
  }

  static builder<M>(): ComponentVMOfBuilder<M> {
    return new ComponentVMOfBuilder<M>();
  }

  /**
   * Constructs a {@link ComponentVMOf} from an options object in a single call —
   * an additive alternative to the fluent {@link ComponentVMOfBuilder}.
   * Delegates to that builder, so the required-field validation
   * ({@link BuilderValidationError} on a missing name/services) and the
   * resulting VM are identical to the fluent path.
   */
  static create<M>(options: ComponentVMOfOptions<M>): ComponentVMOf<M> {
    // Widen to Partial so the required-field guards remain meaningful for JS
    // callers / casts that bypass the type; validation is delegated to build().
    const o = options as Partial<ComponentVMOfOptions<M>>;
    let b = new ComponentVMOfBuilder<M>().model(options.model);
    if (o.name !== undefined) b = b.name(o.name);
    if (o.hint !== undefined) b = b.hint(o.hint);
    if (o.hub !== undefined && o.dispatcher !== undefined) b = b.services(o.hub, o.dispatcher);
    if (o.modeledHinter !== undefined) b = b.modeledHinter(o.modeledHinter);
    if (o.onModelChanged !== undefined) b = b.onModelChanged(o.onModelChanged);
    if (o.onConstruct !== undefined) b = b.onConstruct(o.onConstruct);
    if (o.onDestruct !== undefined) b = b.onDestruct(o.onDestruct);
    if (o.background !== undefined) b = b.background(o.background);
    if (o.vmType !== undefined) b = b.vmType(o.vmType);
    return b.build();
  }
}

/**
 * Options for the additive {@link ComponentVMOf.create} construction form
 * (ADR-0055 / VMX-020). A one-call alternative to the fluent
 * {@link ComponentVMOfBuilder}.
 */
export interface ComponentVMOfOptions<M> {
  /** Required VM name. */
  name: string;
  /** Required message hub. */
  hub: IMessageHub;
  /** Required dispatcher. */
  dispatcher: IDispatcher;
  /** Required model value. */
  model: M;
  /** Optional hint (default: ""). */
  hint?: string;
  /** Optional modeled-hint projection (default: () => ""). */
  modeledHinter?: (m: M) => string;
  /** Optional OnModelChanged callback. */
  onModelChanged?: (m: M) => void;
  /** Optional OnConstruct lifecycle callback. */
  onConstruct?: () => void;
  /** Optional OnDestruct lifecycle callback. */
  onDestruct?: () => void;
  /** Optional background-construction flag (default: false). */
  background?: boolean;
  /** Optional VM type (default: ViewModelType.Component). */
  vmType?: ViewModelType;
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

  /**
   * Chainable Wither that wires {@link NullMessageHub.INSTANCE} +
   * {@link NullDispatcher.INSTANCE} in a single call. Mirrors C#'s
   * `WithNullServices<M>()` and Python's `with_null_services()` per
   * spec/10-builders.md / ADR-0035.
   */
  withNullServices(): ComponentVMOfBuilder<M> {
    return this.services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE);
  }

  build(): ComponentVMOf<M> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#model === SENTINEL) throw new BuilderValidationError("model");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");

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
