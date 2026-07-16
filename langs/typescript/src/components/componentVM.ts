/**
 * ComponentVM — non-modeled leaf viewmodel.
 *
 * See spec/05-component-vm.md §Variants.
 */
import { ComponentVMBase } from "./componentVMBase.js";
import { ViewModelType } from "./types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { NullMessageHub } from "../services/nullMessageHub.js";
import { NullDispatcher } from "../services/nullDispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

const optionHub = Symbol("optionHub");
const optionDispatcher = Symbol("optionDispatcher");

/**
 * Options for the additive {@link ComponentVM.create} construction form
 * (ADR-0055 / VMX-020). A one-call alternative to the fluent
 * {@link ComponentVMBuilder}.
 */
export interface ComponentVMOptions {
  /** Required VM name. */
  name: string;
  /** Required message hub. */
  hub: IMessageHub;
  /** Required dispatcher. */
  dispatcher: IDispatcher;
  /** Optional hint (default: ""). */
  hint?: string;
  /** Optional OnConstruct lifecycle callback. */
  onConstruct?: () => void;
  /** Optional OnDestruct lifecycle callback. */
  onDestruct?: () => void;
  /** Optional background-construction flag (default: false). */
  background?: boolean;
}

export class ComponentVM extends ComponentVMBase {
  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  static builder(): ComponentVMBuilder {
    return new ComponentVMBuilder();
  }

  /**
   * Constructs a {@link ComponentVM} from an options object in a single call —
   * an additive alternative to the fluent {@link ComponentVMBuilder}. Delegates
   * to that builder, so the required-field validation
   * ({@link BuilderValidationError} on a missing name/services) and the
   * resulting VM are identical to the fluent path.
   */
  static create(options: ComponentVMOptions): ComponentVM {
    // Widen to Partial so the required-field guards remain meaningful for JS
    // callers / casts that bypass the type; validation is delegated to build().
    const o = options as Partial<ComponentVMOptions>;
    let b = new ComponentVMBuilder();
    if (o.name !== undefined) b = b.name(o.name);
    if (o.hint !== undefined) b = b.hint(o.hint);
    if (o.hub !== undefined) b = b[optionHub](o.hub);
    if (o.dispatcher !== undefined) b = b[optionDispatcher](o.dispatcher);
    if (o.onConstruct !== undefined) b = b.onConstruct(o.onConstruct);
    if (o.onDestruct !== undefined) b = b.onDestruct(o.onDestruct);
    if (o.background !== undefined) b = b.background(o.background);
    return b.build();
  }
}

// ---------------------------------------------------------------------------
// Builder (colocated per Python flavor pattern)
// ---------------------------------------------------------------------------

export class ComponentVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;
  #background = false;

  constructor(from?: ComponentVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
      this.#background = from.#background;
    }
  }

  name(value: string): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  [optionHub](hub: IMessageHub): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#hub = hub;
    return b;
  }

  [optionDispatcher](dispatcher: IDispatcher): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#dispatcher = dispatcher;
    return b;
  }

  onConstruct(cb: () => void): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#onDestruct = cb;
    return b;
  }

  background(value: boolean): ComponentVMBuilder {
    const b = new ComponentVMBuilder(this);
    b.#background = value;
    return b;
  }

  /**
   * Chainable Wither that wires {@link NullMessageHub.INSTANCE} +
   * {@link NullDispatcher.INSTANCE} in a single call. Mirrors C#'s
   * `WithNullServices()` and Python's `with_null_services()` per
   * spec/10-builders.md / ADR-0035. Intended for tests, samples, and
   * exploration code; production VMs should call `services(hub, dispatcher)`
   * with real services.
   */
  withNullServices(): ComponentVMBuilder {
    return this.services(NullMessageHub.INSTANCE, NullDispatcher.INSTANCE);
  }

  build(): ComponentVM {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");
    return new ComponentVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
      background: this.#background,
    });
  }
}
