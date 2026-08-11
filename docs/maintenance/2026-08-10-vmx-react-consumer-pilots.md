# VMx React Consumer Pilots — 2026-08-10

## 1. Scope and safety

Issue #80 was exercised through real, disposable migrations of NNx Studio,
Tableau, and DayDreams under `/private/tmp/vmx-issue80-pilot-*`. The source
consumer repositories were not edited, committed, or pushed. Each pilot used
VMx core 3.24.0 and adapter 0.1.0 from the issue branch; packed tarballs were
used where the package manager otherwise linked source-only dev dependencies.

## 2. NNx Studio — focused hook migration

`RunSelector.tsx` migrated its production `useVm` and `useObservableList`
bindings to `@thekaveh/vmx-react`. NNx property filters became selector
projections with `shallowEqual`. React 18.3.1 was retained.

Fresh evidence:

- TypeScript typecheck and focused ESLint passed.
- The RunSelector suite passed 36/36 tests.
- The production Vite build passed with 717 modules transformed.
- The binding's local generic dependencies fell from 131 LOC (`useVm` 69 plus
  `useObservableList` 62) to zero; the component migration was +13/-6 lines.

The pilot also exposed upgrade work outside the adapter: NNx vendors VMx 3.1.0,
and current core owns the public `hub` accessor, so 24 redundant consumer
getters need `override` or removal. A full migration also needs a local
`useVmList` helper, selector projections in place of NNx's property-list
overload, and an audit of callers that assume mutable collection arrays.

## 3. Tableau — official selector, retained product store

Tableau kept its synchronous `refreshShell`, `onShellRefreshed`, queued-drain
reentrancy, and lazy-lifecycle store. That store was made structurally
compatible with `VmxStore`, including reconnect revision catch-up. Only the
generic selector machinery moved to official `useVmx`; all 24 existing calls
across ten source files continued through a six-line compatibility wrapper.

Fresh evidence:

- The complete React suite passed 20 files and 91/91 tests.
- The focused store, selector, and StrictMode suites passed 7/7 tests.
- `@tableau/view-react` typecheck passed.
- The `tableau-web` production build passed with 1,591 modules transformed.
- Local selector machinery fell from eight executable LOC to zero. The retained
  product store is 53 SLOC / 99 physical lines.

This boundary is intentional. Generic `createVmxStore` has no pre-invalidation
product transform or external synchronous invalidation input, so it cannot
replace Tableau's recomputation store without changing timing or leaking
product rules into VMx.

## 4. DayDreams — hub-first compatibility wrapper

DayDreams replaced its local selector/equality implementation with official
`useVmx` and `shallowEqual`. A module-level `WeakMap<IMessageHub, VmxStore>`
preserved nine hub-first production call sites and shared one subscription per
hub. TDD evidence first observed two subscriptions, then one after delegation.

Fresh evidence:

- ViewModel and React typechecks passed.
- The React package passed 43/43 tests, including the new shared-subscription
  proof; the web shell passed 34/34 tests.
- The web production build passed with 506 modules transformed.
- Generic binding code fell from 43 to 20 SLOC (-53.5%); physical size fell
  from 104 to 25 lines.

Current core owns the `hub` accessor, so the disposable upgrade also removed six
redundant DayDreams fields. The remaining 17-line compatibility mechanism would
disappear if a future adapter adds a hub-first overload or an owned
`storeForHub` helper; that is a documented follow-up, not part of issue #80.

## 5. Package-shape finding

Bun directory-linking resolved the adapter's React 19 development dependency
beside DayDreams' React 18 runtime and produced an invalid-hook-call failure.
Installing the packed adapter tarball—the same shape npm publishes—removed the
duplicate React and passed all gates. VMx documentation therefore requires
pack-then-install for unpublished source consumers rather than a live directory
link.

## 6. Disposition

All three representative migrations are feasible with passing behavior,
typecheck, and production-build evidence. The reusable package remains free of
consumer rules: NNx retains `useVmList`, Tableau retains its refresh store, and
DayDreams retains a hub-first lifetime wrapper. Public installation remains
gated on the core npm bootstrap in issue #57.
