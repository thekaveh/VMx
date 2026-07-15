/**
 * AggregateVM2<VM1, VM2> — arity-2 aggregate viewmodel.
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

export class AggregateVM2<VM1 extends ComponentVMBase, VM2 extends ComponentVMBase>
  extends ComponentVMBase
{
  readonly #aggregateParent: AggregateParent;
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
    this.#aggregateParent = new AggregateParent(this, () => this.components());
    this.#factory1 = opts.factory1;
    this.#factory2 = opts.factory2;
  }

  get type(): ViewModelType { return ViewModelType.Aggregate; }
  get component1(): VM1 | null { return this.#component1; }
  get component2(): VM2 | null { return this.#component2; }

  /**
   * VMX-023: component slots in declaration order (null slots omitted). Tree
   * traversal uses this typed accessor instead of `component${i}` reflection.
   */
  components(): readonly ComponentVMBase[] {
    const slots: readonly (ComponentVMBase | null)[] = [
      this.#component1,
      this.#component2,
    ];
    return slots.filter((c): c is ComponentVMBase => c !== null);
  }

  protected override _onConstruct(): void {
    const next1 = this.#factory1();
    const next2 = this.#factory2();
    validateAggregateSlots(this.#aggregateParent, [next1, next2]);
    const previous = [this.#component1, this.#component2];
    // On Reconstruct, dispose previous slot instances before overwriting
    // so their hub subscriptions and command Subjects don't leak.
    this.#component1?.dispose();
    this.#component2?.dispose();

    this.#component1 = next1;
    this._notifyPropertyChanged("component1");

    this.#component2 = next2;
    commitAggregateSlots(this.#aggregateParent, previous, [next1, next2]);
    this._notifyPropertyChanged("component2");

    this.#component1.construct();
    this.#component2.construct();
  }

  protected override _onDestruct(): void {
    this.#component1?.destruct();
    this.#component2?.destruct();
  }

  override dispose(): void {
    // Depth-first dispose (LIFE-013): each component slot first, then self.
    this.#component1?.dispose();
    this.#component2?.dispose();
    super.dispose();
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

  name(v: string): AggregateVM2Builder<VM1, VM2> { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#name = v; return b; }
  hint(v: string): AggregateVM2Builder<VM1, VM2> { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#hint = v; return b; }
  services(hub: IMessageHub, disp: IDispatcher): AggregateVM2Builder<VM1, VM2> { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#hub = hub; b.#dispatcher = disp; return b; }
  component1(f: () => VM1): AggregateVM2Builder<VM1, VM2> { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#factory1 = f; return b; }
  component2(f: () => VM2): AggregateVM2Builder<VM1, VM2> { const b = new AggregateVM2Builder<VM1, VM2>(this); b.#factory2 = f; return b; }

  build(): AggregateVM2<VM1, VM2> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null) throw new BuilderValidationError("services");
    if (this.#factory1 === SENTINEL) throw new BuilderValidationError("component1");
    if (this.#factory2 === SENTINEL) throw new BuilderValidationError("component2");
    const factory1 = this.#factory1;
    const factory2 = this.#factory2;
    return new AggregateVM2<VM1, VM2>({ name: this.#name, hint: this.#hint, hub: this.#hub, dispatcher: this.#dispatcher, factory1, factory2 });
  }
}
