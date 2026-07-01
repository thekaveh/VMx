/**
 * ScoredFilteredCompositeVM — score-ranked visible projection.
 */
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { CompositeVMBase } from "./compositeVMBase.js";
import {
  FilteredCompositeVM,
  type FilteredCompositeOptions,
} from "./filteredCompositeVM.js";

export interface ScoredFilteredCompositeOptions<VM extends ComponentVMBase>
  extends Omit<FilteredCompositeOptions<VM>, "predicate"> {
  readonly scorer: (vm: VM) => number | null;
}

export class ScoredFilteredCompositeVM<VM extends ComponentVMBase> extends FilteredCompositeVM<VM> {
  readonly #scorer: (vm: VM) => number | null;

  constructor(
    source: CompositeVMBase<VM>,
    options: ScoredFilteredCompositeOptions<VM>,
  ) {
    const scorer = options.scorer;
    super(source, {
      predicate: (vm) => scorer(vm) !== null,
      deferInitialRecompute: true,
      ...(options.cursorPolicy === undefined ? {} : { cursorPolicy: options.cursorPolicy }),
    });
    this.#scorer = scorer;
    this._recompute();
  }

  protected override orderedVisible(): VM[] {
    return [...this.source]
      .map((vm, index) => ({ vm, index, score: this.#scorer(vm) }))
      .filter((entry): entry is { vm: VM; index: number; score: number } => entry.score !== null)
      .sort((a, b) => b.score - a.score || a.index - b.index)
      .map((entry) => entry.vm);
  }

  refreshScores(): void {
    this._recompute();
  }
}
