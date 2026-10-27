/**
 * ExpandableState — composition-friendly helper for expand/collapse.
 *
 * See spec/05-component-vm.md §8 (`IExpandable` integration), ADR-0015 and
 * ADR-0159 (expansion commands).
 */
import { Subject, type Observable } from "rxjs";
import { RelayCommand } from "../commands/relayCommand.js";
import { disposeBestEffort } from "../components/disposal.js";
import {
  declareCapabilities,
  type CapabilityName,
} from "./registry.js";
import type {
  ICollapsible,
  IExpandable,
  IExpansionTogglable,
} from "./expansion.js";

const CAPS: CapabilityName[] = [
  "IExpandable",
  "ICollapsible",
  "IExpansionTogglable",
];

export class ExpandableState
  implements IExpandable, ICollapsible, IExpansionTogglable
{
  #expanded: boolean;
  readonly #changes = new Subject<boolean>();
  #disposed = false;
  // Built on first read (ADR-0159), so a helper whose commands are never read
  // holds no trigger subscriptions and disposal creates none.
  #expandCommand: RelayCommand | null = null;
  #collapseCommand: RelayCommand | null = null;
  #toggleExpansionCommand: RelayCommand | null = null;

  constructor(initiallyExpanded = false) {
    this.#expanded = initiallyExpanded;
    declareCapabilities(this, ...CAPS);
  }

  get isExpanded(): boolean {
    return this.#expanded;
  }

  get isExpandedChanged(): Observable<boolean> {
    return this.#changes.asObservable();
  }

  /**
   * Runs `expand()` when `canExpand()` is true. Owned by this helper:
   * `dispose()` disposes it, and callers must not.
   */
  get expandCommand(): RelayCommand {
    this.#expandCommand ??= this.#buildCommand(
      () => this.canExpand(),
      () => this.expand(),
    );
    return this.#expandCommand;
  }

  /**
   * Runs `collapse()` when `canCollapse()` is true. Owned by this helper:
   * `dispose()` disposes it, and callers must not.
   */
  get collapseCommand(): RelayCommand {
    this.#collapseCommand ??= this.#buildCommand(
      () => this.canCollapse(),
      () => this.collapse(),
    );
    return this.#collapseCommand;
  }

  /**
   * Runs `toggleExpansion()` when `canToggleExpansion()` is true. Owned by
   * this helper: `dispose()` disposes it, and callers must not.
   */
  get toggleExpansionCommand(): RelayCommand {
    this.#toggleExpansionCommand ??= this.#buildCommand(
      () => this.canToggleExpansion(),
      () => this.toggleExpansion(),
    );
    return this.#toggleExpansionCommand;
  }

  canExpand(): boolean {
    return !this.#expanded;
  }

  expand(): void {
    if (this.#disposed) return;
    if (this.#expanded) return;
    this.#expanded = true;
    this.#changes.next(true);
  }

  canCollapse(): boolean {
    return this.#expanded;
  }

  collapse(): void {
    if (this.#disposed) return;
    if (!this.#expanded) return;
    this.#expanded = false;
    this.#changes.next(false);
  }

  canToggleExpansion(): boolean {
    return true;
  }

  toggleExpansion(): void {
    if (this.#expanded) this.collapse();
    else this.expand();
  }

  /**
   * Disposes the commands that were read, then completes `isExpandedChanged`.
   * Every step runs; the first failure is rethrown. Idempotent: subsequent
   * calls are a no-op.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    const commands = [
      this.#expandCommand,
      this.#collapseCommand,
      this.#toggleExpansionCommand,
    ].filter((command) => command !== null);
    disposeBestEffort([
      ...commands.map((command) => () => command.dispose()),
      () => this.#changes.complete(),
    ]);
  }

  // A command read after disposal is built without the completed trigger and
  // disposed at once, so it is inert like the others (ADR-0068).
  #buildCommand(predicate: () => boolean, task: () => void): RelayCommand {
    let builder = RelayCommand.builder().predicate(predicate).task(task);
    if (!this.#disposed) {
      builder = builder.triggers(this.#changes);
    }
    const command = builder.build();
    if (this.#disposed) command.dispose();
    return command;
  }
}
