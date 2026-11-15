import { useCallback, useRef } from "react";
import { useSyncExternalStoreWithSelector } from "use-sync-external-store/with-selector";

export type Equality<T> = (current: T, next: T) => boolean;
export type SourceSubscribe = (invalidate: () => void) => () => void;

/**
 * Adapt a directly observable value to a cached monotonic selector token.
 * `serverVersion`, when given, is the version that server renders and
 * hydration read. A selector can return a fixed value for it and skip work
 * that needs a live subscription.
 */
export function useVersionedSelector<T>(
  sourceSubscribe: SourceSubscribe,
  selector: (version: number) => T,
  equality: Equality<T> = Object.is,
  serverVersion?: number,
): T {
  const versionRef = useRef(0);
  const selectionRef = useRef<{ readonly value: T } | null>(null);
  const selectorRef = useRef(selector);
  const equalityRef = useRef(equality);
  selectorRef.current = selector;
  equalityRef.current = equality;

  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      let active = true;
      const invalidate = (): void => {
        if (!active) return;
        versionRef.current += 1;
        notify();
      };
      const unsubscribe = sourceSubscribe(invalidate);
      const previous = selectionRef.current;
      const current = selectorRef.current(versionRef.current);
      if (previous === null || !equalityRef.current(previous.value, current)) {
        versionRef.current += 1;
      }
      return () => {
        active = false;
        unsubscribe();
      };
    },
    [sourceSubscribe],
  );

  const getSnapshot = useCallback(() => versionRef.current, []);
  const getServerSnapshot = useCallback(
    () => serverVersion ?? versionRef.current,
    [serverVersion],
  );
  const trackedSelector = useCallback(
    (version: number): T => {
      const selected = selector(version);
      selectionRef.current = { value: selected };
      return selected;
    },
    [selector],
  );
  return useSyncExternalStoreWithSelector(
    subscribe,
    getSnapshot,
    getServerSnapshot,
    trackedSelector,
    equality,
  );
}
