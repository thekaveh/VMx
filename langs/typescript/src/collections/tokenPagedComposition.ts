/**
 * TokenPagedComposition<TVM, TToken> — accumulated, forward-only token pagination.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import { AsyncRelayCommand } from "../commands/asyncRelayCommand.js";
import { ComponentVMBase } from "../components/componentVMBase.js";
import {
  makeCollectionChangedEvent,
  type CollectionChangedEvent,
} from "./collectionChangedEvent.js";

export interface TokenPage<TVM, TToken> {
  readonly items: readonly TVM[];
  readonly nextToken: TToken | null;
}

export interface TokenPagedCompositionOptions<TVM> {
  readonly autoConstructOnAdd?: boolean;
  readonly pagesEqual?: (left: readonly TVM[], right: readonly TVM[]) => boolean;
}

export class TokenPagedComposition<TVM, TToken> {
  readonly #fetchNext: (token: TToken | null) => Promise<TokenPage<TVM, TToken>>;
  readonly #autoConstructOnAdd: boolean;
  readonly #pagesEqual: (left: readonly TVM[], right: readonly TVM[]) => boolean;
  readonly #collectionChanged = new Subject<CollectionChangedEvent>();
  readonly #propertyChanged = new Subject<string>();
  readonly #commandChanged = new Subject<void>();
  readonly #loadMoreCommand: AsyncRelayCommand;
  readonly #refreshCommand: AsyncRelayCommand;
  #items: TVM[] = [];
  #currentToken: TToken | null = null;
  #loadedOnce = false;
  #disposed = false;

  constructor(
    fetchNext: (token: TToken | null) => Promise<TokenPage<TVM, TToken>>,
    options: TokenPagedCompositionOptions<TVM> = {},
  ) {
    this.#fetchNext = fetchNext;
    this.#autoConstructOnAdd = options.autoConstructOnAdd ?? false;
    this.#pagesEqual = options.pagesEqual ?? shallowEqual;
    this.#loadMoreCommand = AsyncRelayCommand.builder()
      .predicate(() => this.hasMore && !this.#disposed)
      .triggers(this.#commandChanged)
      .task(async () => { await this.#loadMore(); })
      .build();
    this.#refreshCommand = AsyncRelayCommand.builder()
      .predicate(() => !this.#disposed)
      .triggers(this.#commandChanged)
      .task(async () => { await this.#refresh(); })
      .build();
  }

  get items(): TVM[] {
    return [...this.#items];
  }

  get currentToken(): TToken | null {
    return this.#currentToken;
  }

  get hasMore(): boolean {
    return !this.#loadedOnce || this.#currentToken !== null;
  }

  get loadMoreCommand(): AsyncRelayCommand {
    return this.#loadMoreCommand;
  }

  get refreshCommand(): AsyncRelayCommand {
    return this.#refreshCommand;
  }

  get collectionChanged(): Observable<CollectionChangedEvent> {
    return this.#collectionChanged.asObservable();
  }

  get propertyChanged(): Observable<string> {
    return this.#propertyChanged.asObservable();
  }

  async #loadMore(): Promise<void> {
    const page = await this.#fetchNext(this.#currentToken);
    this.#items.push(...page.items);
    this.#constructIfNeeded(page.items);
    this.#currentToken = page.nextToken;
    this.#loadedOnce = true;
    this.#notifyReset();
  }

  async #refresh(): Promise<void> {
    const page = await this.#fetchNext(null);
    const head = this.#items.slice(0, page.items.length);
    if (this.#pagesEqual(page.items, head)) {
      this.#currentToken = page.nextToken;
      this.#loadedOnce = true;
      this.#notifyProperties();
      return;
    }
    this.#items = [...page.items];
    this.#constructIfNeeded(page.items);
    this.#currentToken = page.nextToken;
    this.#loadedOnce = true;
    this.#notifyReset();
  }

  #constructIfNeeded(items: readonly TVM[]): void {
    if (!this.#autoConstructOnAdd) return;
    for (const item of items) {
      if (item instanceof ComponentVMBase && !item.isConstructed) {
        item.construct();
      }
    }
  }

  #notifyReset(): void {
    this.#collectionChanged.next(makeCollectionChangedEvent("reset"));
    this.#notifyProperties();
  }

  #notifyProperties(): void {
    for (const name of ["items", "currentToken", "hasMore"]) {
      this.#propertyChanged.next(name);
    }
    this.#commandChanged.next();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#loadMoreCommand.dispose();
    this.#refreshCommand.dispose();
    this.#collectionChanged.complete();
    this.#propertyChanged.complete();
    this.#commandChanged.complete();
  }
}

function shallowEqual<T>(left: readonly T[], right: readonly T[]): boolean {
  return left.length === right.length && left.every((item, index) => Object.is(item, right[index]));
}
