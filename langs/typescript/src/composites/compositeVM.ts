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
    this._attachPopulation(this.#childrenFactory());
  }

  static builder<VM extends ComponentVMBase>(): CompositeVMBuilder<VM> {
    return new CompositeVMBuilder<VM>();
  }

  /**
   * Constructs a {@link CompositeVM} from an options object in a single call —
   * an additive alternative to the fluent {@link CompositeVMBuilder}. Delegates
   * to that builder, so the required-field validation
   * ({@link BuilderValidationError} on a missing name/services/children) and the
   * resulting VM are identical to the fluent path.
   */
  static create<VM extends ComponentVMBase>(
    options: CompositeVMOptions<VM>,
  ): CompositeVM<VM> {
    // Widen to Partial so the required-field guards remain meaningful for JS
    // callers / casts that bypass the type; validation is delegated to build().
    const o = options as Partial<CompositeVMOptions<VM>>;
    let b = new CompositeVMBuilder<VM>();
    if (o.children !== undefined) b = b.children(o.children);
    if (o.name !== undefined) b = b.name(o.name);
    if (o.hint !== undefined) b = b.hint(o.hint);
    if (o.hub !== undefined && o.dispatcher !== undefined) b = b.services(o.hub, o.dispatcher);
    if (o.asyncSelection !== undefined) b = b.asyncSelection(o.asyncSelection);
    if (o.autoConstructOnAdd !== undefined) b = b.autoConstructOnAdd(o.autoConstructOnAdd);
    if (o.current !== undefined) b = b.current(o.current);
    if (o.onCurrentChanged !== undefined) b = b.onCurrentChanged(o.onCurrentChanged);
    if (o.onConstruct !== undefined) b = b.onConstruct(o.onConstruct);
    if (o.onDestruct !== undefined) b = b.onDestruct(o.onDestruct);
    return b.build();
  }
}

/**
 * Options for the additive {@link CompositeVM.create} construction form
 * (ADR-0055 / VMX-020). A one-call alternative to the fluent
 * {@link CompositeVMBuilder}.
 */
export interface CompositeVMOptions<VM extends ComponentVMBase> {
  /** Required VM name. */
  name: string;
  /** Required message hub. */
  hub: IMessageHub;
  /** Required dispatcher. */
  dispatcher: IDispatcher;
  /** Required children factory (invoked lazily on construct; `() => []` for empty). */
  children: () => Iterable<VM>;
  /** Optional hint (default: ""). */
  hint?: string;
  /** Optional async-selection flag (default: false). */
  asyncSelection?: boolean;
  /** Optional auto-construct-on-add flag (default: false). */
  autoConstructOnAdd?: boolean;
  /** Optional initial-current selector (see ADR-0042). */
  current?: (xs: Iterable<VM>) => VM | null;
  /** Optional current-changed callback (see ADR-0042). */
  onCurrentChanged?: (vm: VM | null) => void;
  /** Optional OnConstruct lifecycle callback. */
  onConstruct?: () => void;
  /** Optional OnDestruct lifecycle callback. */
  onDestruct?: () => void;
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
   * spec/06 §3.2.
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
   * See ADR-0042 and spec/06 §3.2.
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
