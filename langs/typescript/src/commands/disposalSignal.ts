/**
 * Wrapper-command change streams that also notify once at disposal (spec/04
 * §8.4). Internal; not exported from the package.
 */
import { Observable } from "rxjs";

/**
 * Passes `source` through in full, including its completion, and adds one
 * `next` for each value of `disposal`. A plain merge would hide the inner
 * completion that a disposed `AsyncRelayCommand` sends (#771).
 */
export function withDisposalSignal(
  source: Observable<void>,
  disposal: Observable<void>,
): Observable<void> {
  return new Observable<void>((subscriber) => {
    const subscription = source.subscribe(subscriber);
    subscription.add(disposal.subscribe({ next: () => subscriber.next() }));
    return subscription;
  });
}
