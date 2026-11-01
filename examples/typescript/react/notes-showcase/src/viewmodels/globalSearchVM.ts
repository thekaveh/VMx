import {
  AsyncRelayCommand,
  ComponentVMBase,
  SearchableState,
  TokenPagedComposition,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

import type { INoteRepository } from "../models/noteRepository.js";
import { NoteVM } from "./noteVM.js";

const SENTINEL = Symbol("not-set");

/** The cursor for the next page. It keeps the term of the loaded pages. */
interface SearchCursor {
  readonly term: string;
  readonly offset: string;
}

/** Token-paged search and lifetime owner for every result VM it creates. */
export class GlobalSearchVM extends ComponentVMBase {
  readonly #repo: INoteRepository;
  readonly #pageSize: number;
  readonly #search: SearchableState<string>;
  readonly #paged: TokenPagedComposition<NoteVM, SearchCursor>;
  readonly #loadMoreCommand: AsyncRelayCommand;
  readonly #ownedResults = new Set<NoteVM>();
  /** The search term that fetched each result. */
  readonly #resultTerms = new WeakMap<NoteVM, string>();
  #ownedResultsDisposed = false;
  /** A search asked for while a refresh was in flight; see `search()`. */
  #searchPending = false;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    repository: INoteRepository;
    pageSize: number;
    searchDebounceMs: number;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#repo = opts.repository;
    this.#pageSize = opts.pageSize;
    this.#search = new SearchableState<string>({
      items: () => ["global-search"],
      predicate: () => true,
      debounceMs: opts.searchDebounceMs,
      scheduler: opts.dispatcher.foreground,
    });
    this.#paged = new TokenPagedComposition<NoteVM, SearchCursor>(
      async (cursor) => {
        // The first page uses the current term. A later page uses the term in
        // the cursor, so "Load more" continues the term of the loaded pages.
        const term = cursor?.term ?? this.searchTerm;
        const page = await this.#repo.searchNotes(term, cursor?.offset ?? null, this.#pageSize);
        return {
          items: page.items.map((model) =>
            this.#ownResult(
              NoteVM.builder()
                .name(`global-${model.id}`)
                .services(this._hub, this._dispatcher)
                .model(model)
                .build(),
              term,
            ),
          ),
          nextToken: page.nextToken === null ? null : { term, offset: page.nextToken },
        };
      },
      {
        autoConstructOnAdd: true,
        // Pages for different terms are never equal, so a refresh for a new
        // term replaces the loaded pages and their cursor.
        pagesEqual: (left, right) =>
          left.length === right.length
          && left.every((item, idx) => {
            const other = right[idx];
            return other !== undefined
              && item.model.id === other.model.id
              && this.#resultTerms.get(item) === this.#resultTerms.get(other);
          }),
      },
    );
    // A refresh replaces the loaded pages, so "Load more" is not available
    // until the refresh is complete. A call made during a refresh does
    // nothing. A load that starts during a refresh makes the composition
    // discard that refresh (spec 21 §6.2).
    this.#loadMoreCommand = AsyncRelayCommand.builder()
      .predicate(
        () => this.#paged.loadMoreCommand.canExecute() && !this.#paged.refreshCommand.isExecuting,
      )
      .triggers(this.#paged.loadMoreCommand.canExecuteChanged)
      .triggers(this.#paged.refreshCommand.canExecuteChanged)
      .task(() => this.#paged.loadMoreCommand.executeAsync())
      .build();
    // Re-run a search that arrived while the previous refresh was busy, once
    // the command goes idle (it announces that through canExecuteChanged).
    this.#paged.refreshCommand.canExecuteChanged.subscribe(() => {
      this.#runPendingSearch();
    });
    this.#paged.propertyChanged.subscribe((name) => {
      if (name === "items") {
        this._notifyPropertyChanged("results");
      }
      if (name === "hasMore") {
        this._notifyPropertyChanged("hasMore");
      }
    });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  get searchTerm(): string {
    return this.#search.searchTerm;
  }

  set searchTerm(value: string) {
    if (this.#search.searchTerm === value) return;
    this.#search.searchTerm = value;
    this._notifyPropertyChanged("searchTerm");
  }

  canSearch(): boolean {
    return this.#search.canSearch();
  }

  /**
   * Requests a refresh for the current term. The refresh command admits one
   * execution at a time and drops calls made while busy, so a request made
   * mid-flight is remembered and re-run when the in-flight fetch settles:
   * the latest term always wins, however fast the user types.
   */
  search(): void {
    this.#search.search();
    this.#searchPending = true;
    this.#runPendingSearch();
  }

  #runPendingSearch(): void {
    if (!this.#searchPending || this.refreshCommand.isExecuting) return;
    this.#searchPending = false;
    this.refreshCommand.execute();
  }

  get results(): readonly NoteVM[] {
    return this.#paged.items;
  }

  get hasMore(): boolean {
    return this.#paged.hasMore;
  }

  get refreshCommand(): AsyncRelayCommand {
    return this.#paged.refreshCommand;
  }

  get loadMoreCommand(): AsyncRelayCommand {
    return this.#loadMoreCommand;
  }

  #ownResult(result: NoteVM, term: string): NoteVM {
    if (this.#ownedResultsDisposed) {
      result.dispose();
    } else {
      this.#ownedResults.add(result);
      this.#resultTerms.set(result, term);
    }
    return result;
  }

  protected override _onDispose(): void {
    this.#ownedResultsDisposed = true;
    for (const result of this.#ownedResults) result.dispose();
    this.#ownedResults.clear();
    this.#search.dispose();
    this.#loadMoreCommand.dispose();
    this.#paged.dispose();
    super._onDispose();
  }

  static builder(): GlobalSearchVMBuilder {
    return new GlobalSearchVMBuilder();
  }
}

export class GlobalSearchVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #repo: INoteRepository | typeof SENTINEL = SENTINEL;
  #pageSize = 5;
  #searchDebounceMs = 150;

  constructor(from?: GlobalSearchVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#repo = from.#repo;
      this.#pageSize = from.#pageSize;
      this.#searchDebounceMs = from.#searchDebounceMs;
    }
  }

  name(value: string): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  repository(repo: INoteRepository): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#repo = repo;
    return b;
  }

  pageSize(value: number): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#pageSize = value;
    return b;
  }

  searchDebounceMs(value: number): GlobalSearchVMBuilder {
    const b = new GlobalSearchVMBuilder(this);
    b.#searchDebounceMs = value;
    return b;
  }

  build(): GlobalSearchVM {
    if (this.#name === null) throw new Error("Missing required field: name");
    if (this.#hub === null) throw new Error("Missing required field: hub");
    if (this.#dispatcher === null) throw new Error("Missing required field: dispatcher");
    if (this.#repo === SENTINEL) throw new Error("Missing required field: repository");
    return new GlobalSearchVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      repository: this.#repo,
      pageSize: this.#pageSize,
      searchDebounceMs: this.#searchDebounceMs,
    });
  }
}
