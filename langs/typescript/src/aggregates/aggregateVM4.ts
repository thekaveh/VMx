/**
 * AggregateVM4<VM1..VM4> — arity-4 aggregate viewmodel.
 *
 * See spec/08-aggregate-vm.md.
 */
import { ComponentVMBase } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { BuilderValidationError } from "../builders/exceptions.js";
import { AggregateParent, commitAggregateSlots, validateAggregateSlots } from "./ownership.js";

const SENTINEL = Symbol("not-set");

export class AggregateVM4<
  VM1 extends ComponentVMBase,
  VM2 extends ComponentVMBase,
  VM3 extends ComponentVMBase,
  VM4 extends ComponentVMBase,
> extends ComponentVMBase {
  readonly #aggregateParent: AggregateParent;
  readonly #factory1: () => VM1;
  readonly #factory2: () => VM2;
  readonly #factory3: () => VM3;
  readonly #factory4: () => VM4;
  #component1: VM1 | null = null;
  #component2: VM2 | null = null;
  #component3: VM3 | null = null;
  #component4: VM4 | null = null;

  constructor(opts: {
    name: string; hint: string; hub: IMessageHub; dispatcher: IDispatcher;
    factory1: () => VM1; factory2: () => VM2; factory3: () => VM3; factory4: () => VM4;
  }) {
    super(opts);
    this.#aggregateParent = new AggregateParent(this, () => this.components());
    this.#factory1 = opts.factory1; this.#factory2 = opts.factory2;
    this.#factory3 = opts.factory3; this.#factory4 = opts.factory4;
  }

  get type(): ViewModelType { return ViewModelType.Aggregate; }
  get component1(): VM1 | null { return this.#component1; }
  get component2(): VM2 | null { return this.#component2; }
  get component3(): VM3 | null { return this.#component3; }
  get component4(): VM4 | null { return this.#component4; }

  /**
   * VMX-023: component slots in declaration order (null slots omitted). Tree
   * traversal uses this typed accessor instead of `component${i}` reflection.
   */
  components(): readonly ComponentVMBase[] {
    const slots: readonly (ComponentVMBase | null)[] = [
      this.#component1,
      this.#component2,
      this.#component3,
      this.#component4,
    ];
    return slots.filter((c): c is ComponentVMBase => c !== null);
  }

  protected override _onConstruct(): void {
    const next1 = this.#factory1();
    const next2 = this.#factory2();
    const next3 = this.#factory3();
    const next4 = this.#factory4();
    validateAggregateSlots(this.#aggregateParent, [next1, next2, next3, next4]);
    const previous = [this.#component1, this.#component2, this.#component3, this.#component4];
    // On Reconstruct, dispose previous slot instances before overwriting
    // so their hub subscriptions and command Subjects don't leak.
    this.#component1?.dispose();
    this.#component2?.dispose();
    this.#component3?.dispose();
    this.#component4?.dispose();

    this.#component1 = next1;
    this._notifyPropertyChanged("component1");

    this.#component2 = next2;
    this._notifyPropertyChanged("component2");

    this.#component3 = next3;
    this._notifyPropertyChanged("component3");

    this.#component4 = next4;
    commitAggregateSlots(this.#aggregateParent, previous, [next1, next2, next3, next4]);
    this._notifyPropertyChanged("component4");

    this.#component1.construct();
    this.#component2.construct();
    this.#component3.construct();
    this.#component4.construct();
  }

  protected override _onDestruct(): void {
    this.#component1?.destruct();
    this.#component2?.destruct();
    this.#component3?.destruct();
    this.#component4?.destruct();
  }

  override dispose(): void {
    // Depth-first dispose (LIFE-013): each component slot first, then self.
    this.#component1?.dispose();
    this.#component2?.dispose();
    this.#component3?.dispose();
    this.#component4?.dispose();
    super.dispose();
  }

  static builder<
    VM1 extends ComponentVMBase,
    VM2 extends ComponentVMBase,
    VM3 extends ComponentVMBase,
    VM4 extends ComponentVMBase,
  >(): AggregateVM4Builder<VM1, VM2, VM3, VM4> {
    return new AggregateVM4Builder<VM1, VM2, VM3, VM4>();
  }
}

export class AggregateVM4Builder<
  VM1 extends ComponentVMBase,
  VM2 extends ComponentVMBase,
  VM3 extends ComponentVMBase,
  VM4 extends ComponentVMBase,
> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #factory1: (() => VM1) | typeof SENTINEL = SENTINEL;
  #factory2: (() => VM2) | typeof SENTINEL = SENTINEL;
  #factory3: (() => VM3) | typeof SENTINEL = SENTINEL;
  #factory4: (() => VM4) | typeof SENTINEL = SENTINEL;

  constructor(from?: AggregateVM4Builder<VM1, VM2, VM3, VM4>) {
    if (from) {
      this.#name = from.#name; this.#hint = from.#hint;
      this.#hub = from.#hub; this.#dispatcher = from.#dispatcher;
      this.#factory1 = from.#factory1; this.#factory2 = from.#factory2;
      this.#factory3 = from.#factory3; this.#factory4 = from.#factory4;
    }
  }

  name(v: string): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#name = v; return b; }
  hint(v: string): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#hint = v; return b; }
  services(hub: IMessageHub, disp: IDispatcher): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#hub = hub; b.#dispatcher = disp; return b; }
  component1(f: () => VM1): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#factory1 = f; return b; }
  component2(f: () => VM2): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#factory2 = f; return b; }
  component3(f: () => VM3): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#factory3 = f; return b; }
  component4(f: () => VM4): AggregateVM4Builder<VM1, VM2, VM3, VM4> { const b = new AggregateVM4Builder<VM1, VM2, VM3, VM4>(this); b.#factory4 = f; return b; }

  build(): AggregateVM4<VM1, VM2, VM3, VM4> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null) throw new BuilderValidationError("services");
    if (this.#factory1 === SENTINEL) throw new BuilderValidationError("component1");
    if (this.#factory2 === SENTINEL) throw new BuilderValidationError("component2");
    if (this.#factory3 === SENTINEL) throw new BuilderValidationError("component3");
    if (this.#factory4 === SENTINEL) throw new BuilderValidationError("component4");
    const factory1 = this.#factory1;
    const factory2 = this.#factory2;
    const factory3 = this.#factory3;
    const factory4 = this.#factory4;
    return new AggregateVM4<VM1, VM2, VM3, VM4>({
      name: this.#name, hint: this.#hint, hub: this.#hub, dispatcher: this.#dispatcher,
      factory1, factory2, factory3, factory4,
    });
  }
}
