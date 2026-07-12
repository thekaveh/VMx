# Issue 139 DayDreams Pilot

**Issue:** VMx #139 — `AsyncResourceVM<T>`\
**Consumer:** DayDreams at `b0c43abe9ee7eb17f3b14c00bb6dd9fc8f675d10`\
**VMx artifact:** `@thekaveh/vmx` 3.20.0\
**Pilot policy:** disposable local clone; no commit and no push

## Finding

The issue's original React evidence is now partly historical. Current
DayDreams has already moved both generic route-loading state machines from
`GalleryView.tsx` and `DreamscapeView.tsx` into `GalleryScreenVM` and
`DreamscapeScreenVM`. The React views are pure binders and required no pilot
change. The duplication still exists one layer lower: both screen VMs carry
their own abort controller, epoch/latest-wins gate, state transitions, retry,
late-result suppression, and teardown ordering.

The pilot therefore replaced those two screen-VM loading cores with the packed
VMx `AsyncResourceVM` while preserving DayDreams' product-specific assembly:

- gallery entry loading still builds `GalleryVM` and wires open-to-navigation;
- dreamscape summary loading still builds `WorldVM`, seeds the manifest,
  configures navigation/camera/focus, and creates the stream controller;
- cleanup callbacks still unsubscribe/dispose the gallery or stop/dispose the
  controller and world;
- the existing DayDreams screen-state unions remain as compatibility adapters
  for the unchanged React bindings.

The pilot also removed six obsolete `readonly hub` property overrides. VMx now
exposes its injected hub publicly from the base class; TypeScript correctly
rejects overriding that accessor with an instance field. This was a consumer
upgrade adjustment, not an `AsyncResourceVM` behavior change.

## Artifact And LOC Evidence

The tarball `/tmp/thekaveh-vmx-3.20.0.tgz` had SHA-256
`99abe069787bc2751f724c2c5148446879f9927ea5008d67a81fcb242f3b97a1`.

`git diff --numstat` in the disposable clone reported:

| Consumer file                          |   Added | Removed |
| -------------------------------------- | ------: | ------: |
| `galleryScreenVm.ts`                   |      52 |      58 |
| `dreamscapeScreenVm.ts`                |      81 |      60 |
| four other VM hub-accessor adjustments |       2 |      10 |
| **Total**                              | **135** | **128** |

The two duplicated loading cores lost 118 lines. The pilot is net +7 lines
because it deliberately retains both existing product-specific public state
unions and adds explicit mapping/cleanup adapters; a consumer-native migration
could instead bind directly to the VMx state snapshot and remove those adapters.
No React view LOC was changed because current DayDreams had already completed
that architectural move.

## Verification

Executed in the disposable clone:

```text
bun run --filter @daydreams/viewmodel typecheck
  exit 0
bun run --filter web typecheck
  exit 0
bun run --filter @daydreams/viewmodel test
  10 files passed; 141 tests passed
bun run --filter web test -- GalleryView
  1 file passed; 3 tests passed
git diff --check
  exit 0
```

The 41 focused gallery/dreamscape screen-VM tests are included in the 141-test
viewmodel run. They cover initial/success/error/retry behavior, latest-route
wins, aborted signals, ready-value replacement, dispose during load, late load
and explore completion, command policy, child/controller teardown, navigation,
and hub completion. DayDreams has no `DreamscapeView.test.tsx`; its dreamscape
route behavior is covered by the 21 `DreamscapeScreenVM` tests.

## Conclusion

The primitive is applicable and removes the duplicated cancellation/race
policy at the correct current boundary. The pilot found no behavior regression.
It also confirms the intended scope boundary: VMx owns one async value and its
operation lifecycle, while DayDreams continues to own route IDs, product VM
construction, navigation, renderer/controller setup, and domain-specific
explore behavior.
