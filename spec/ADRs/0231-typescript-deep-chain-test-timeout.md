# ADR 0231 — The TypeScript 10,000-level chain tests get an explicit 30 s timeout

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (`spec/ADRs` only; no spec chapter, conformance ID or library behavior changes)
- **Related:** #1912 (the issue this change refs; the chain tests check its iterative walks), #2061 (the commit that made the walks iterative and added the `DeepChain` tests), CI run 43774159913 (the failing run cited as evidence).

## 1. Context

Commit `5acc8b5c` (#2061) made TypeScript tree walks and `depth` iterative. It added a `describe("DeepChain")` block to `langs/typescript/tests/unit/hierarchicalVm.test.ts`. The block builds a chain of `DEEP_CHAIN_LEVELS = 10_000` nodes with children factories and runs the walks on it.

Vitest's default per-test timeout is 5,000 ms. On the CI runners the walk test takes longer than that. CI run 43774159913 failed three TypeScript jobs with `Test timed out in 5000ms` in `deep chain: walk, walkExpanded, find and depth reach the last level`:

- `build & test (macos-latest / node22)`, test duration 5,611 ms
- `build & test (macos-latest / node24)`, test duration 5,425 ms
- `build & test (ubuntu-latest / node24)`

The second test in the block, `deep chain: a materialized chain moves under a new parent`, took 4,675 ms and 4,647 ms on the same macOS jobs. It passed, but it is close to the same limit.

The same tests take about 1.5 s each on the development machine. A lowered global timeout (`--testTimeout=1000`) makes both tests fail with `Test timed out in 1000ms`, so the timeout is the failing check and not an assertion.

The library behavior is correct on develop. The timeout is a CI cost of the test, not a defect in the walks.

## 2. Decision

1. Each of the two `it(...)` calls in `describe("DeepChain")` takes an explicit timeout of `30_000` ms as its third argument. The value is 30,000 ms.
1. The change applies to these two calls only. `vitest.config.ts` keeps the default, so the rest of the suite still fails fast on a real hang.
1. The second test gets the same budget as the first. Both build the same 10,000-level chain on the same runners, and the second took 4.6 to 4.7 s there, close to the default.
1. `DEEP_CHAIN_LEVELS` stays at `10_000`. The depth is the point of the test, and the issue requires a 10,000-level chain.
1. A comment above the `describe` states the reason: the walk test takes about 5.5 s on the CI runners, over the 5,000 ms default, and the budget covers its CI cost. The comment also says that the change alters no assertion.
1. No assertion, test name or test helper changes. The Python tests are not touched.
1. No library behavior changes. Therefore no `CHANGELOG.md` entry, no spec chapter change, no conformance ID change, and no public API change.

## 3. Consequences

- The two chain tests can take up to 30 s each on a slow runner before vitest reports a timeout. The suite still fails on a real hang, but the hang is reported later.
- A future regression to recursive walks would not show as a timeout. Recursion fails at this depth with a stack-overflow `RangeError` on some engines, and the depth and count assertions remain, so the tests still catch it.
- Each chain test exercises a 10,000-level tree. If the cost on CI grows past 30 s, the budget must be revisited. That is a test-budget change, not a library change.
- The explicit per-test timeout takes precedence over the global `--testTimeout`. This was checked: with `--testTimeout=1000`, the two tests fail on the old code and pass with the explicit 30 s budget.

### 3.1 Mutation evidence

This change adds no test, so there is no new test to show failing under a library mutation. The evidence is the timeout check: before the change, both tests fail at `--testTimeout=1000` with `Test timed out in 1000ms`. After the change, the same run passes with the explicit 30 s budget, so the explicit value is what decides the outcome.

## 4. Rejected alternatives

- **Raise `testTimeout` in `vitest.config.ts`.** This would loosen the timeout for every TypeScript test, including tests that do not build deep trees. The fault is in two tests, so the fix stays in those two tests.
- **Lower `DEEP_CHAIN_LEVELS`.** The depth is what proves the walks no longer recurse. Below 10,000 the tests would stop covering the failure that issue #1912 names, which is the TypeScript limit below 10,000 levels.
- **Skip the chain tests on CI.** This removes coverage on the platforms where the cost appears.
- **Speed up node construction, or split the tests.** This could cut the CI cost, but it changes the test structure and needs its own measurements. It is out of scope for a timeout fix.
- **Use 60 s.** The observed worst case is about 5.6 s, so 30 s leaves a margin of about five times. A larger budget only hides a slowdown.
