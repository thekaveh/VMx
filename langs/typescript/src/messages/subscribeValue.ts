import type { Subscription } from "rxjs";
import type { IComponentVM } from "../components/types.js";
import { isPropertyChanged } from "./predicates.js";

export interface SubscribeValueOptions<TValue> {
  readonly equality?: (current: TValue, next: TValue) => boolean;
  readonly fireImmediately?: boolean;
}

export function subscribeValue<TSource extends IComponentVM, TValue>(
  source: TSource,
  selector: (source: TSource) => TValue,
  callback: (current: TValue, previous: TValue) => void,
  options?: SubscribeValueOptions<TValue>,
): Subscription {
  let current = selector(source);
  if (options?.fireImmediately === true) callback(current, current);
  const equality = options?.equality ?? Object.is;

  return source.hub.messages.subscribe((message) => {
    if (!isPropertyChanged(message, { sender: source })) return;
    const next = selector(source);
    if (equality(current, next)) return;
    const previous = current;
    current = next;
    callback(next, previous);
  });
}
