/**
 * AggregateVM2<VM1, VM2> — arity-2 aggregate viewmodel.
 *
 * See spec/08-aggregate-vm.md.
 */
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";

const SENTINEL = Symbol("not-set");

export class AggregateVM2<VM1 extends ComponentVMBase, VM2 extends ComponentVMBase>
  extends ComponentVMBase
{
  readonly #factory1: () => VM1;
  readonly #factory2: () => VM2;
  #component1: VM1 | null = null;
  #component2: VM2 | null = null;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    factory1: () => VM1;
    factory2: () => VM2;
  }) {
    super(opts);
    this.#factory1 = opts.factory1;
    this.#factory2 = opts.factory2;
  }

  get type(): ViewModelType { return ViewModelType.Aggregate; }
  get component1(): VM1 | null { return this.#component1; }
  get component2(): VM2 | null { return this.#component2; }

  protected override _onConstruct(): void {
    this.#component1 = this.#factory1();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "Component1"));
    this._raisePropertyChanged("component1");

    this.#component2 = this.#factory2();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "Component2"));
    this._raisePropertyChanged("component2");

    this.#component1.construct();
    this.#component2.construct();
  }

  protected override _onDestruct(): void {
    this.#component1?.destruct();
    this.#component2?.destruct();
  }

  protected override _onDispose(): void {
    this.#component1?.dispose();
    this.#component2?.dispose();
  }

  static builder<VM1 extends ComponentVMBase, VM2 extends ComponentVMBase>(): AggregateVM2Builder<VM1, VM2> {
    return new AggregateVM2Builder<VM1, VM2>();
  }
}

export class AggregateVM2Builder<VM1 extends ComponentVMBase, VM2 extends ComponentVMBase> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #factory1: (() => VM1) | typeof SENTINEL = SENTINEL;
  #factory2: (() => VM2) | typeof SENTINEL = SENTINEL;

  constructor(from?: AggregateVM2Builder<VM1, VM2>) {
    if (from) {
      this.#name = from.#name; this.#hint = from.#hint;
      this.#hub = from.#hub; this.#dispatcher = from.#dispatcher;
      this.#factory1 = from.#factory1; this.#factory2 = from.#factory2;
    }
  }

  name(v: string): this { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#name = v; return b as unknown as this; }
  hint(v: string): this { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#hint = v; return b as unknown as this; }
  services(hub: IMessageHub, disp: IDispatcher): this { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#hub = hub; b.#dispatcher = disp; return b as unknown as this; }
  component1(f: () => VM1): this { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#factory1 = f; return b as unknown as this; }
  component2(f: () => VM2): this { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#factory2 = f; return b as unknown as this; }

  build(): AggregateVM2<VM1, VM2> {
    if (this.#name === null) throw new Error("BuilderValidationError: name is required");
    if (this.#hub === null || this.#dispatcher === null) throw new Error("BuilderValidationError: services (hub, dispatcher) are required");
    if (this.#factory1 === SENTINEL) throw new Error("BuilderValidationError: component1 factory is required");
    if (this.#factory2 === SENTINEL) throw new Error("BuilderValidationError: component2 factory is required");
    const factory1 = this.#factory1;
    const factory2 = this.#factory2;
    return new AggregateVM2<VM1, VM2>({ name: this.#name, hint: this.#hint, hub: this.#hub, dispatcher: this.#dispatcher, factory1, factory2 });
  }
}
