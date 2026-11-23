/**
 * The canonical sender identity that the chapter 03 §7 hub subscription helpers
 * match (spec/03-messages.md §7, ADR-0233).
 *
 * A forwarding decorator sends no message of its own: its wrapped VM is the
 * sender of each message the decorator causes (ADR-0221). Walking the public
 * `wrappedBase` chain reaches the innermost VM, which is the canonical identity
 * shared by every decorator layer (ADR-0124). A VM that wraps nothing, or whose
 * `wrappedBase` getter throws, is its own identity.
 */
export function canonicalSender(sender: object): object {
  const seen = new Set<object>([sender]);
  let current: object = sender;
  for (;;) {
    let next: unknown;
    try {
      next = (current as { readonly wrappedBase?: unknown }).wrappedBase;
    } catch {
      return current;
    }
    if (typeof next !== "object" || next === null || seen.has(next)) return current;
    seen.add(next);
    current = next;
  }
}
