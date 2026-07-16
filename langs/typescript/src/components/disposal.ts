/** Run terminal teardown actions in order, then rethrow the first failure. */
export function disposeBestEffort(actions: Iterable<() => void>): void {
  let failed = false;
  let firstError: unknown;
  for (const action of actions) {
    try {
      action();
    } catch (error) {
      if (!failed) {
        failed = true;
        firstError = error;
      }
    }
  }
  if (failed) throw firstError;
}
