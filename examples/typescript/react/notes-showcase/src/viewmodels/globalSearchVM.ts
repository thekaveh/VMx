import {
  ComponentVMBase,
  PropertyChangedMessage,
  SearchableState,
  TokenPagedComposition,
  ViewModelType,
  type AsyncRelayCommand,
  type IDispatcher,
  type IMessageHub,
} from "@thekaveh/vmx";

import type { INoteRepository } from "../models/noteRepository.js";
import { NoteVM } from "./noteVM.js";

const SENTINEL = Symbol("not-set");

export class GlobalSearchVM extends ComponentVMBase {
  readonly #repo: INoteRepository;
  readonly #pageSize: number;
  readonly #search: SearchableState<string>;
  readonly #paged: TokenPagedComposition<NoteVM, string>;

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
    this.#paged = new TokenPagedComposition<NoteVM, string>(
      async (token) => {
        const page = await this.#repo.searchNotes(this.searchTerm, token, this.#pageSize);
        return {
          items: page.items.map((model) =>
            NoteVM.builder()
              .name(`global-${model.id}`)
              .services(this._hub, this._dispatcher)
              .model(model)
              .build(),
          ),
          nextToken: page.nextToken,
        };
      },
      {
        autoConstructOnAdd: true,
        pagesEqual: (left, right) =>
          left.length === right.length
          && left.every((item, idx) => item.model.id === right[idx]?.model.id),
      },
    );
    this.#paged.propertyChanged.subscribe((name) => {
      if (name === "items") {
        this._hub.send(PropertyChangedMessage.create(this, this._name, "results"));
        this._raisePropertyChanged("results");
      }
      if (name === "hasMore") {
        this._hub.send(PropertyChangedMessage.create(this, this._name, "hasMore"));
        this._raisePropertyChanged("hasMore");
      }
    });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get searchTerm(): string {
    return this.#search.searchTerm;
  }

  set searchTerm(value: string) {
    if (this.#search.searchTerm === value) return;
    this.#search.searchTerm = value;
    this._hub.send(PropertyChangedMessage.create(this, this._name, "searchTerm"));
    this._raisePropertyChanged("searchTerm");
  }

  canSearch(): boolean {
    return this.#search.canSearch();
  }

  search(): void {
    this.#search.search();
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
    return this.#paged.loadMoreCommand;
  }

  protected override _onDispose(): void {
    this.#search.dispose();
    this.#paged.dispose();
    for (const result of this.#paged.items) result.dispose();
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
