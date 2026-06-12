/**
 * AggregateVM6<VM1..VM6> — arity-6 aggregate viewmodel.
 *
 * See spec/08-aggregate-vm.md.
 */
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";

const SENTINEL = Symbol("not-set");

export class AggregateVM6<
  VM1 extends ComponentVMBase,
  VM2 extends ComponentVMBase,
  VM3 extends ComponentVMBase,
  VM4 extends ComponentVMBase,
  VM5 extends ComponentVMBase,
  VM6 extends ComponentVMBase,
> extends ComponentVMBase {
  readonly #factory1: () => VM1;
  readonly #factory2: () => VM2;
  readonly #factory3: () => VM3;
  readonly #factory4: () => VM4;
  readonly #factory5: () => VM5;
  readonly #factory6: () => VM6;
  #component1: VM1 | null = null;
  #component2: VM2 | null = null;
  #component3: VM3 | null = null;
  #component4: VM4 | null = null;
  #component5: VM5 | null = null;
  #component6: VM6 | null = null;

  constructor(opts: {
    name: string; hint: string; hub: IMessageHub; dispatcher: IDispatcher;
    factory1: () => VM1; factory2: () => VM2; factory3: () => VM3;
    factory4: () => VM4; factory5: () => VM5; factory6: () => VM6;
  }) {
    super(opts);
    this.#factory1 = opts.factory1; this.#factory2 = opts.factory2;
    this.#factory3 = opts.factory3; this.#factory4 = opts.factory4;
    this.#factory5 = opts.factory5; this.#factory6 = opts.factory6;
  }

  get type(): ViewModelType { return ViewModelType.Aggregate; }
  get component1(): VM1 | null { return this.#component1; }
  get component2(): VM2 | null { return this.#component2; }
  get component3(): VM3 | null { return this.#component3; }
  get component4(): VM4 | null { return this.#component4; }
  get component5(): VM5 | null { return this.#component5; }
  get component6(): VM6 | null { return this.#component6; }

  protected override _onConstruct(): void {
    // On Reconstruct, dispose previous slot instances before overwriting
    // so their hub subscriptions and command Subjects don't leak.
    this.#component1?.dispose();
    this.#component2?.dispose();
    this.#component3?.dispose();
    this.#component4?.dispose();
    this.#component5?.dispose();
    this.#component6?.dispose();

    this.#component1 = this.#factory1();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component1"));
    this._raisePropertyChanged("component1");

    this.#component2 = this.#factory2();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component2"));
    this._raisePropertyChanged("component2");

    this.#component3 = this.#factory3();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component3"));
    this._raisePropertyChanged("component3");

    this.#component4 = this.#factory4();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component4"));
    this._raisePropertyChanged("component4");

    this.#component5 = this.#factory5();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component5"));
    this._raisePropertyChanged("component5");

    this.#component6 = this.#factory6();
    this._hub.send(PropertyChangedMessage.create(this, this._name, "component6"));
    this._raisePropertyChanged("component6");

    this.#component1.construct();
    this.#component2.construct();
    this.#component3.construct();
    this.#component4.construct();
    this.#component5.construct();
    this.#component6.construct();
  }

  protected override _onDestruct(): void {
    this.#component1?.destruct();
    this.#component2?.destruct();
    this.#component3?.destruct();
    this.#component4?.destruct();
    this.#component5?.destruct();
    this.#component6?.destruct();
  }

  override dispose(): void {
    // Depth-first dispose (LIFE-013): each component slot first, then self.
    // Mirrors AggregateVM1..AggregateVM5 so subscribers observe child Disposed
    // transitions before the aggregate's own Disposed transition — a single
    // dispose-ordering rule across all aggregate arities.
    this.#component1?.dispose();
    this.#component2?.dispose();
    this.#component3?.dispose();
    this.#component4?.dispose();
    this.#component5?.dispose();
    this.#component6?.dispose();
    super.dispose();
  }

  static builder<
    VM1 extends ComponentVMBase, VM2 extends ComponentVMBase,
    VM3 extends ComponentVMBase, VM4 extends ComponentVMBase,
    VM5 extends ComponentVMBase, VM6 extends ComponentVMBase,
  >(): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> {
    return new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>();
  }
}

export class AggregateVM6Builder<
  VM1 extends ComponentVMBase, VM2 extends ComponentVMBase,
  VM3 extends ComponentVMBase, VM4 extends ComponentVMBase,
  VM5 extends ComponentVMBase, VM6 extends ComponentVMBase,
> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #factory1: (() => VM1) | typeof SENTINEL = SENTINEL;
  #factory2: (() => VM2) | typeof SENTINEL = SENTINEL;
  #factory3: (() => VM3) | typeof SENTINEL = SENTINEL;
  #factory4: (() => VM4) | typeof SENTINEL = SENTINEL;
  #factory5: (() => VM5) | typeof SENTINEL = SENTINEL;
  #factory6: (() => VM6) | typeof SENTINEL = SENTINEL;

  constructor(from?: AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>) {
    if (from) {
      this.#name = from.#name; this.#hint = from.#hint;
      this.#hub = from.#hub; this.#dispatcher = from.#dispatcher;
      this.#factory1 = from.#factory1; this.#factory2 = from.#factory2;
      this.#factory3 = from.#factory3; this.#factory4 = from.#factory4;
      this.#factory5 = from.#factory5; this.#factory6 = from.#factory6;
    }
  }

  name(v: string): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#name = v; return b; }
  hint(v: string): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#hint = v; return b; }
  services(hub: IMessageHub, disp: IDispatcher): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#hub = hub; b.#dispatcher = disp; return b; }
  component1(f: () => VM1): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory1 = f; return b; }
  component2(f: () => VM2): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory2 = f; return b; }
  component3(f: () => VM3): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory3 = f; return b; }
  component4(f: () => VM4): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory4 = f; return b; }
  component5(f: () => VM5): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory5 = f; return b; }
  component6(f: () => VM6): AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6> { const b = new AggregateVM6Builder<VM1, VM2, VM3, VM4, VM5, VM6>(this); b.#factory6 = f; return b; }

  build(): AggregateVM6<VM1, VM2, VM3, VM4, VM5, VM6> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null) throw new BuilderValidationError("services");
    if (this.#factory1 === SENTINEL) throw new BuilderValidationError("component1");
    if (this.#factory2 === SENTINEL) throw new BuilderValidationError("component2");
    if (this.#factory3 === SENTINEL) throw new BuilderValidationError("component3");
    if (this.#factory4 === SENTINEL) throw new BuilderValidationError("component4");
    if (this.#factory5 === SENTINEL) throw new BuilderValidationError("component5");
    if (this.#factory6 === SENTINEL) throw new BuilderValidationError("component6");
    const factory1 = this.#factory1;
    const factory2 = this.#factory2;
    const factory3 = this.#factory3;
    const factory4 = this.#factory4;
    const factory5 = this.#factory5;
    const factory6 = this.#factory6;
    return new AggregateVM6<VM1, VM2, VM3, VM4, VM5, VM6>({
      name: this.#name, hint: this.#hint, hub: this.#hub, dispatcher: this.#dispatcher,
      factory1, factory2, factory3, factory4, factory5, factory6,
    });
  }
}
