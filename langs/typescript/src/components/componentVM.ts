/**
 * ComponentVM — non-modeled leaf viewmodel.
 *
 * See spec/05-component-vm.md §Variants.
 */
import { ComponentVMBase } from "./componentVMBase.js";
import { ViewModelType } from "./types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

export class ComponentVM extends ComponentVMBase {
  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  static builder(): ComponentVMBuilder {
    return new ComponentVMBuilder();
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
