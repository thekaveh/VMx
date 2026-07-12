# Issue #98 Consumer Validation

**Issue:** VMx #98 — `SearchableState` source-mutation reactivity\
**VMx artifact:** `@thekaveh/vmx` 3.19.0\
**Artifact SHA-256:**
`a761560af3cac94faf47d8733ec8573eda7973faae7155988238d37f86769da3`

## 1. Applicability audit

The roadmap directive permits consumer pilots only in disposable clones and
only where the affected surface is actually used. Both named consumer
repositories were cloned from their pinned committed state and searched before
any edits.

### 1.1 DayDreams

- Pinned commit:
  `37b899dde1739c02cb5459ec5cd7d674495783d5`
- `SearchableState` references in the disposable clone: one.
- That reference is documentation only:
  `docs/superpowers/reports/2026-07-10-vmx-recommendations.md`, which records
  VMX-093 and links issue #98.
- Production and test references: zero.

An integration rewrite would therefore invent a new DayDreams feature rather
than validate an existing consumer path. No DayDreams file was changed.

### 1.2 Tableau

- Pinned commit:
  `7ad170a1574ded48a7a2c61d06df43ac0c6e4aab`
- Production, test, and documentation references to `SearchableState`: zero.

No Tableau file was changed.

## 2. Packed-artifact consumer smoke

The TypeScript flavor was packed through its real `prepack` path into:

```text
/tmp/vmx-issue98-package/thekaveh-vmx-3.19.0.tgz
```

A fresh external npm project installed only that tarball and RxJS 7. Its
runtime script verified:

1. the public package reports `__version__ === "3.19.0"`;
1. a `Subject<void>` supplied as `sourceChanges` refreshes an unchanged term
   after the backing array gains an item;
1. an upstream source error does not fail `filtered`;
1. explicit `search()` still reads a later supplier mutation after that error;
1. disposal completes without taking ownership of the source signal.

Observed output:

```json
{"version":"3.19.0","snapshots":4,"last":["alpha","beta","gamma"],"errorIsolated":true}
```

The tarball also passed package typecheck, dual ESM/CJS build, and version-sync
checks as part of `npm pack`.

## 3. In-repository consumer coverage

Existing search composition remains covered by the full language suites,
including `COMP-014..018`, `GRP-007..010`, `COL-021` paging composition, and
`HIER-013` hierarchical composition. The new `SRCH-001..007` cases add
source-mutation, ordering, batching transparency, debounce independence,
termination, disposal, and compatibility coverage in all five flavors.

## 4. Safety verification

After both disposable-clone audits:

- the user DayDreams checkout remained on `develop` at `37b899d`, with its
  pre-existing dirty/untracked paths unchanged;
- the user Tableau checkout remained clean on `main` at `7ad170a`; and
- neither consumer repository received a commit, branch, package-lock change,
  or push.

## 5. Conclusion

The consumer audit found no existing `SearchableState` integration to migrate,
so the correct applicability result is "no invasive consumer pilot." The
packed-artifact smoke validates the actual public package boundary and the two
highest-risk runtime behaviors. No API correction was required.
