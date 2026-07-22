# VMx Framework — Verified-Merged Critique Report

> Historical audit record. This document captures a point-in-time review and may contain superseded paths, versions, findings, or conclusions. For current behavior, use the specification and current documentation.

> Fuses an adversarial verification of `docs/audit/opencode-20260627.md` with an independent no-ceiling audit. 2026-06-27. Phase 1 of 3 (Critique → Fixing → Swift full-parity).

______________________________________________________________________

## 1. Executive summary

This report reconciles two independent passes over the VMx framework: **Stream 1**, an adversarial verification of the third-party *opencode* audit, and **Stream 2**, a fresh no-ceiling audit run with no awareness of opencode's conclusions. Every opencode claim was re-derived from source; every independent finding was cross-checked against the same evidence. The result is **137 active findings** plus **14 disproven opencode claims** retired to the appendix.

### Head-to-head scorecard

| Stream-1 outcome (vs the opencode audit)                                    | Verdict tags                                   | Count                           |
| --------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------- |
| **Confirmed as-is** — opencode right, I concur                              | CONFIRMED / SUPPORTED · AGREE                  | 37 (`both-agree`)               |
| **Confirmed but materially corrected** — claim holds, framing/figures fixed | CONFIRMED-WITH-CORRECTION · AGREE-WITH-CAVEATS | 21 (`both-I-corrected`)         |
| **Opencode-only, verified & retained** — opencode found it, I confirmed it  | CONFIRMED / PARTIAL · AGREE                    | 33 (`opencode-only`, active)    |
| **Refuted → Appendix** — opencode claim did not survive verification        | REFUTED / DISAGREE                             | 14 (`opencode-only`, disproven) |
| **Independent-only ADDED** — real defects opencode missed entirely          | n/a · mine-only                                | 43 (`mine-only`)                |
| **Completeness-critic NEW** — surfaced during final assembly                | n/a · new                                      | 3 (VMX-135/136/137)             |

*opencode true-positive rate:* of 47 opencode-raised items, 33 stood as-is or after correction within the 21 shared-corrected set, **14 were disproven** (≈30% of opencode's distinct claims were wrong on the facts or the recommendation). The single largest block of value — **43 findings (31% of the active ledger)** — comes from the independent stream catching defects opencode never looked at (the Swift background data race, the post-dispose `IsCurrent` leak, the live-Subject read-only-contract leaks, an entire class of conformance-gaming wrappers, and the spec/tag integrity gaps).

### Severity profile (137 active)

| Severity      | Count |
| ------------- | ----- |
| **Critical**  | 3     |
| **Important** | 50    |
| **Minor**     | 84    |

> Recount note: the base ledger carried 134 active (3 / 49 / 82). Completeness-critic added VMX-135 (Important), VMX-136 (Minor), VMX-137 (Minor) → **3 / 50 / 84**. VMX-079 (Python NotificationVM, Minor) is retained at its original tag and is re-scoped/elevated through its cross-flavor twin **VMX-135** to avoid double-counting the same defect.

### The 3 Criticals

- **VMX-001 (C#)** — `ComponentVMBase` background `SetStatus()` races `Dispose()`: non-volatile `_status` read → VM resurrection + post-dispose hub publish + `ObjectDisposedException` on the pool thread (only reachable under the real `TaskPoolScheduler`).
- **VMX-002 (Swift)** — the same lifecycle is an **unsynchronized data race (UB)** on plain `var status`/`inFlight`/`triggersDisposed` with *no* volatile/lock/actor; weaker than C# and ThreadSanitizer-flaggable. opencode never analyzed the Swift race.
- **VMX-003 (TypeScript)** — `FormVM.isDirty` uses `JSON.stringify`: a **hard crash** on BigInt/circular and **silently wrong** on Map/Set/Date/undefined/NaN/-0/key-order, while the default `structuredClone` snapshotter advertises exactly the types the comparison cannot handle.

### Highest-leverage themes

1. **Lifecycle/dispose concurrency is the framework's structural weak point.** The background `construct → SetStatus` path races `Dispose()` in *every* flavor (VMX-001/002/004), all four guards are non-atomic check-then-act (VMX-054), and there is no foreground-marshalling primitive so status flips, Subject emissions, and child-collection mutations all fire on the pool thread (VMX-025). The defect is masked in CI only because every test picks the inline `immediate()`/`Null` dispatcher.

1. **Forms dirty-tracking and snapshot integrity are broken or shallow across flavors.** TS `isDirty` crashes/misreports (VMX-003), Python and C# default snapshotters are shallow copies that make nested mutation invisible and un-revertable (VMX-010/064), and `ApproveCommand` swallows persister failures fire-and-forget with no error channel (VMX-008).

1. **Release & version integrity is fabricated or unenforced.** A v2.5.0 release row is advertised in the matrix, README, and every CHANGELOG with **zero git tags** and no publish run (VMX-033); the current 2.6.x line is itself only 4/6-tagged with no repo-wide or spec tag (VMX-034/035/061); and the C#/TS/Swift release jobs publish to NuGet/npm/GitHub Releases with **no test gate** (VMX-036/037/038). No tool reconciles manifests ↔ matrix ↔ tags (VMX-060).

1. **Conformance "232/232 green" is largely a presence metric, not behavior.** The coverage scraper is a raw string-match that counts commented-out marks and assertion-free stubs (VMX-029); the conformance gate runs *zero* test bodies (VMX-030); C# and Python ship self-admitted placeholder/delegator wrappers that assert nothing (VMX-032/055/056); and Swift has no scraper at all (VMX-031).

1. **Swift carries a distinct recoverability/safety gap that Phase 3 must close.** Illegal lifecycle transitions, the in-flight guard, and a non-child `current` set are **uncatchable `preconditionFailure` traps** (VMX-026/028), HUB-007 subscriber isolation is structurally unsatisfiable so a throwing subscriber **kills the process** (VMX-027), and the lifecycle state is fully unsynchronized (VMX-002). 27 findings touch Swift; they are indexed in §5 for the full-parity phase.

1. **Boilerplate and dead ceremony dominate the surface.** ~3,951 LOC of near-identical arity-1..6 aggregate classes (VMX-019), ~1,000–1,200 LOC/flavor of copy-on-write builders (VMX-020), and five eagerly-built RelayCommands per VM of which four are permanently inert on leaf nodes (VMX-018).

______________________________________________________________________

## 2. Methodology

**Two streams, fused.**

- *Stream 1 (adversarial verification):* each claim in `docs/audit/opencode-20260627.md` was re-checked against source. Findings inherit an **opencode-verdict** and a **recommendation assessment**.
- *Stream 2 (independent no-ceiling audit):* a fresh pass with no ceiling on scope or count, run blind to opencode's conclusions, producing the `mine-only` set (= what opencode missed).

**Verification verdict taxonomy (Stream-1 claims):**

- `CONFIRMED` — claim reproduced exactly.
- `CONFIRMED-WITH-CORRECTION` — defect is real, but a figure, line cite, or framing was wrong and is corrected here.
- `PARTIAL` — part of the claim holds, part does not.
- `REFUTED` — claim does not survive verification (→ Appendix §7).
- `UNVERIFIABLE` — could not be confirmed or denied from available evidence.

**Recommendation assessment (for opencode's fixes):** `AGREE` / `AGREE-WITH-CAVEATS` / `DISAGREE`.

**Provenance legend:**

- `both-agree` — opencode raised it, I independently confirmed it, no correction needed.
- `both-I-corrected` — opencode raised it, real, but I corrected facts/framing/figures.
- `opencode-only` — opencode raised it, I verified it; independent pass did not separately surface it.
- `mine-only` — opencode missed it entirely; surfaced only by the independent stream.

**Process gates.** Findings were produced by read-only multi-agent exploration (no source mutated) with a per-cluster validation gate: every numeric claim (LOC counts, pragma counts, tag lists, grep tallies) was re-run against the tree before a finding was admitted, which is what reduced opencode's "~4,400 LOC" / "~90 pragmas" / "22 types" headlines to their verified values.

**Controller adjudications applied verbatim** (the four cross-stream tie-breaks the ledger was built on):

1. `GC.SuppressFinalize(this)` has exactly **4** real direct call sites (NotificationVM:117, ForwardingComponentVM:137, ForwardingCompositeVM:205, ComponentVMBase:493) — not "~6 types" or "20" (VMX-066).
1. "Zero test bodies" is true **only** for `conformance.yml` (coverage-only); the per-flavor workflows (`python.yml:65`, etc.) **do** run the full suites — state both (VMX-030).
1. The WPF off-Windows build failure is **EXPECTED** (WPF is Windows-only); reframe any "contradicts README" claim to a Minor doc-gap (VMX-126).
1. **8 opencode claims refuted** outright (39→41 Swift reconciliation, spec/README ADR-exemption, descendant cache invalidation, TS `.sender` filter, builder-immutability test coverage, showcase-parity matcher, etc.) → Appendix §7.

______________________________________________________________________

## 3. Ranked action table (top ~30)

Sorted Critical → Important → Minor, then by blast radius (breaking > minor > patch), then by ID. The remaining 107 findings (and all blast=patch/cosmetic items) are rendered in full in §4.

| ID      | Sev       | Blast    | Title                                                                                  | Flavors                        | Effort | Provenance       |
| ------- | --------- | -------- | -------------------------------------------------------------------------------------- | ------------------------------ | ------ | ---------------- |
| VMX-001 | Critical  | breaking | Background `SetStatus()` races `Dispose()` — resurrection + post-dispose publish + ODE | csharp                         | M      | both-I-corrected |
| VMX-002 | Critical  | breaking | Lifecycle is an unsynchronized data race (UB) — no volatile/lock/actor                 | swift                          | M      | mine-only        |
| VMX-003 | Critical  | breaking | `FormVM.isDirty` `JSON.stringify` — crash on BigInt/circular, wrong on Map/Set/Date    | typescript                     | M      | both-I-corrected |
| VMX-004 | Important | minor    | Background `_set_status` vs `dispose` resurrection (GIL-bounded TOCTOU)                | python                         | M      | both-agree       |
| VMX-005 | Important | minor    | Non-`Equatable` model publishes on every set — violates HUB-005                        | swift                          | M      | mine-only        |
| VMX-006 | Important | minor    | Post-dispose `IsCurrent` change leaks a hub `PropertyChangedMessage`                   | csharp/python/typescript       | S      | mine-only        |
| VMX-007 | Important | minor    | Hook exception wedges the VM permanently in the transient state                        | python                         | S      | mine-only        |
| VMX-008 | Important | minor    | `ApproveCommand` swallows persister failures (no error channel)                        | csharp/python/typescript       | M      | both-agree       |
| VMX-009 | Important | minor    | `ConfirmationDecoratorCommand` swallows reject AND inner throw                         | python/typescript              | S      | mine-only        |
| VMX-010 | Important | minor    | FormVM shallow snapshot/revert — nested mutation invisible                             | python                         | S      | mine-only        |
| VMX-011 | Important | minor    | CRUD Update/Delete `CanExecute` has no trigger — stale buttons                         | csharp                         | M      | mine-only        |
| VMX-012 | Important | minor    | Fluent command decorators return `ICommand`, hide `IDisposable` (leak)                 | csharp                         | M      | mine-only        |
| VMX-015 | Important | minor    | Builders require concrete `MessageHub` — defeats `MessageHubProto`                     | python                         | S      | mine-only        |
| VMX-016 | Important | minor    | Untyped `senderObject` vs typed `sender` — base-API field split                        | typescript                     | M      | both-agree       |
| VMX-018 | Important | minor    | 5 eager RelayCommands/VM; 4 permanently inert on leaf VMs                              | csharp/python                  | M      | both-agree       |
| VMX-019 | Important | minor    | AggregateVM per-arity explosion — ~3,951 LOC arity-1..6                                | csharp/python/typescript/swift | L      | both-I-corrected |
| VMX-020 | Important | minor    | Copy-on-write builders ~1,000–1,200 LOC/flavor + ceremony                              | csharp/python/typescript/swift | M      | both-I-corrected |
| VMX-022 | Important | minor    | netstandard2.0 build path has zero runtime test coverage                               | csharp                         | M      | both-agree       |
| VMX-023 | Important | minor    | `walk.ts` reflects `component1..6` — AggregateVM7 slot dropped                         | typescript                     | M      | both-agree       |
| VMX-024 | Important | minor    | Dual-entry build duplicates classes — `instanceof` breaks across bundles               | typescript                     | S      | both-agree       |
| VMX-025 | Important | minor    | No foreground-marshalling primitive — status/Subject/collection on pool thread         | csharp/python/typescript/swift | M      | both-agree       |
| VMX-026 | Important | minor    | `CompositeVM.current` setter traps on non-child — undocumented                         | swift                          | S      | both-agree       |
| VMX-027 | Important | minor    | HUB-007 unsatisfiable — a throwing subscriber kills the process                        | swift                          | M      | both-agree       |
| VMX-028 | Important | minor    | Illegal lifecycle transitions are uncatchable `preconditionFailure` traps              | swift                          | n/a    | both-agree       |
| VMX-031 | Important | minor    | Swift conformance entirely unenforced — no scraper, no IDs                             | swift                          | M      | both-agree       |
| VMX-033 | Important | minor    | Fabricated v2.5.0 release row — advertised, zero tags, never published                 | all                            | M      | both-agree       |
| VMX-034 | Important | minor    | No repo-wide v2.5.0/v2.6.0 git tags despite manifests                                  | all                            | S      | both-I-corrected |
| VMX-035 | Important | minor    | No spec-v2.5.0/spec-v2.6.0 tags — implementers cannot pin                              | spec                           | S      | mine-only        |
| VMX-036 | Important | minor    | `release.yml` C# publishes to NuGet with NO test gate                                  | csharp                         | S-M    | both-agree       |
| VMX-037 | Important | minor    | `release.yml` TS publishes to npm with NO test gate / no provenance                    | typescript                     | S-M    | both-agree       |

______________________________________________________________________

## 4. Findings by theme

> Every active finding is rendered once, here. §5 and §6 are cross-reference indexes only. Format: **VMX-NNN** [severity/blast · flavors · provenance] — title. **Evidence:** file:line. **Fix:** … (effort).

### 4.A Specification

**VMX-039** [Important/minor · spec+csharp+python+typescript+swift · mine-only] — SelectNext/SelectPrevious command navigation is normatively underspecified with zero conformance coverage. **Evidence:** 05-component-vm.md:97-98 prose only; sole ref GRP-002 asserts presence+always-false. **Fix:** define predicate semantics (wrap/clamp/Current==null) in ch.05/06 + add COMP-0NN moving Current across siblings (M).

**VMX-040** [Important/minor · spec+csharp+python+typescript+swift · mine-only] — `Parent` is load-bearing in every selection predicate but never declared as a VM member (no type/nullability/update-timing/observability). **Evidence:** 05-component-vm.md:108-118 reads `Parent`/`Parent.Current`; baseline 01-concepts.md:93-106 and 05:18-48 never declare it. **Fix:** add `Parent : ICompositeVM?` to ch.01 §1.3, specify set/clear on Add/Remove + emission, add a conformance ID (M).

**VMX-041** [Important/minor · spec+csharp+python+typescript+swift · mine-only] — Lifecycle hooks OnConstruct/OnDestruct/OnDispose (ADR-0041's per-construct vs long-lived split) have no conformance ID. **Evidence:** 02-lifecycle.md:66-84 specifies them; grep of 12-conformance.md returns nothing. **Fix:** add LIFE-0NN: OnConstruct fires on construct/reconstruct, OnDestruct on destruct, OnDispose once; subscription registered in OnConstruct released in OnDestruct (M).

**VMX-042** [Important/minor · spec+csharp+python+typescript · mine-only] — ConfirmationVM's defining behavior ("does NOT auto-resolve at lifespan expiry") has no conformance ID. **Evidence:** 16-notifications.md:179-182; NOTIF-011..016 never advance a ConfirmationVM past its 300s Lifespan. **Fix:** add a NOTIF-0NN under a TestScheduler advancing past Lifespan asserting IsResolved==false + still-pending; pin the 300s default (S).

**VMX-043** [Important/minor · spec+csharp+python+typescript · mine-only] — ApproveCommand.Execute fire-and-forget semantics are unspecified in ch.20 and FORM-007 cites a §2 that does not contain the statement. **Evidence:** 20-form-vm.md:43 vs FORM-007's dangling "per chapter 20 §2". **Fix:** add a normative §2/§8 paragraph defining Execute() as fire-and-forget + fix the cross-reference (S).

**VMX-044** [Important/minor · spec+python+typescript · mine-only] — Async confirm/persist gating inside synchronous `ICommand.Execute` is unspecified across the confirmation decorators. **Evidence:** 04-commands.md:151-154 "Execute invokes confirm()" but confirm is `()->Task<bool>` (04:150) while Execute is `():void` (04:11). **Fix:** specify the per-flavor realization (continuation, does not block) + observable ordering; pin in CMD-008/CMDD-007 (M).

**VMX-045** [Important/minor · spec · mine-only] — CompositeVM initial-current selector "via the SelectComponent path" contradicts §3.1/COMP-009 (raise on non-child) and ADR-0042 §5.4 (silent no-op). **Evidence:** 06-composite-vm.md:72 vs §3.1 (:60-62) + ADRs/0042.md:44,58. **Fix:** route the selector through a non-raising validated assignment OR specify it raises; pin in COMP-025 (S).

**VMX-046** [Important/minor · spec · opencode-only] — Child construction order is unspecified-but-sequential, with no conformance ID enforcing visitation order — a concurrent-construction flavor passes every test. **Evidence:** 02-lifecycle.md:126-129 "order is unspecified". **Fix:** make sequential normative with a conformance ID, or state subscribers MUST NOT rely on order (S).

**VMX-047** [Important/minor · csharp+python+typescript · opencode-only] — FormVM.OnApproved diverges cross-flavor (C# emits pre-await snapshot; Py/TS emit live post-await model); FORM-006 only checks equality absent concurrent re-mutation. **Evidence:** ADRs/0009 ~314-328 documents the divergence + defers alignment. **Fix:** pin OnApproved to the persisted value across flavors + a FORM ID exercising concurrent SetModel during await (M).

**VMX-048** [Important/minor · spec · opencode-only] — Ch.11 foreground-emission rule offers two observably non-equivalent MAY options; THR-001 tests only the opt-in case. **Evidence:** 11-threading.md:42-48 (Send foreground vs Send+ObserveOn). **Fix:** pin one option, or normatively state non-ObserveOn subscribers have no thread guarantee (M).

**VMX-049** [Important/minor · spec+python+typescript+swift · both-agree] — Background construct is racy on non-C# flavors (no-replay buffer + terminal-message-only await; async lifecycle is C#-only); a composite "wait for all children" collides with background-enabled children. **Evidence:** 11-threading.md:54-58 + 03-messages.md:82-84 + 02-lifecycle.md:31-37. **Fix:** add a replay-last-status/completion-future await primitive on all flavors + specify composite orchestration + a conformance ID (M).

**VMX-050** [Important/minor · spec · opencode-only] — `proposals/` is labeled "historical, not part of published spec" yet 12-conformance §28 references the ThemeVM scenario contract (THEME-001..005) normatively. **Evidence:** spec/README:170-171 vs 12-conformance.md §28. **Fix:** elevate the ThemeVM scenario to a spec chapter, or caveat that normatively-referenced proposals aren't "historical" (S).

**VMX-051** [Important/minor · spec+all · opencode-only] — No validation framework; strict-mode FormVM gates only on IsDirty and flagships hand-roll isValid via DerivedProperty. **Evidence:** 20-form-vm.md:156-165; notes-showcase-scenario.md:343-345. **Fix:** add an optional IValidator<T> + IsValid/validation-error surface, or document validation is composed via DerivedProperty (M).

**VMX-052** [Important/minor · spec+all · opencode-only] — No async-command cancellation / IAsyncCommand; dialogs have a cancellation contract (DIA-007) but long-running command tasks have none. **Evidence:** 04-commands.md:11 `Execute():void` vs 19-dialogs §6/DIA-007. **Fix:** add an IAsyncCommand with cancellation aligned with the dialog story (L).

**VMX-107** [Minor/cosmetic · swift+spec · both-agree] — ADR-0036/0037 carry no in-body forward reference — the 39→41 reconciliation lives only in 01-concepts.md:48. **Evidence:** ADRs/README.md:57 vs 0036:53 "(53 of 232)" vs 0037 §2.6:78 "39 IDs". **Fix:** add an in-body forward link 0036 §2.E → 0037 §2.6 → ADR-0042 (S).

**VMX-108** [Minor/cosmetic · spec/fixtures · both-agree] — The derived-properties "distinct-until-changed" fixture cannot encode suppression and uses ints where C#/Py/TS equality coincide; the real rule is exercised only by hand-written DPROP-010. **Evidence:** fixtures/derived-properties.json sources [5,5] mutations \[[0,3],[1,7]\] expected [10,8,10]. **Fix:** rename the scenario + add an equal-but-not-identical reference-value scenario + an emission-count field (S).

**VMX-109** [Minor/patch · spec · both-agree] — Nested-batch ref-counting and empty-batch-no-event are normative but untested (CompositeVM, GroupVM, ObservableList §3.5 nesting unspecified). **Evidence:** 06-composite-vm.md:96-100; COMP-013 tests a single batch only. **Fix:** extend COMP-013/GRP-006/COL-009 to nested→one Reset + empty→no event; add one sentence to 21 §3.5 (S).

**VMX-110** [Minor/patch · spec/fixtures · both-agree] — Command exception-handling contracts have no conformance coverage (throwing task must propagate; throwing predicate → CanExecute=false); fixture omits both + parameterized execute. **Evidence:** 04-commands.md:41-42,31; command-truthtable.json:4-8 = 5 happy cases. **Fix:** add CMD-0NN tests + fixture rows for parameterized execute / predicate-raise / task-raise (S).

**VMX-111** [Minor/cosmetic · spec · both-I-corrected] — README v2.5 changelog (§1.7) omits ADR-0038, mis-attributes FORM-014 to ADR-0037, and leaves ADR-0037's catalog total (234) stale vs the v2.5 end-state (235). **Evidence:** README.md:127-136 vs ADR-0038:1-4 §2 vs ADR-0037 §3:107-108. **Fix:** add an ADR-0038 bullet to §1.7 + reconcile ADR-0037's 234 with a forward note (S).

**VMX-112** [Minor/patch · spec · mine-only] — `walk_expanded` does not descend into AggregateVM slots (diverging from `walk`) and is untested for aggregates. **Evidence:** 13-tree-utilities.md:69-75 (children only) vs walk (:22-27, special-cases `.components`). **Fix:** mirror walk's descent (Composite/Group children AND AggregateVM .components) + a conformance case (S).

**VMX-113** [Minor/cosmetic · spec · mine-only] — Ch.14 §2.10 "CurrentPageIndex clamped to [0, PageCount-1]" contradicts the empty-source case (PageCount==0 → [0,-1]) that ch.21 §5.4 / COL-020 handle. **Evidence:** 14-capabilities.md:171 vs 21-collections:347-349. **Fix:** reword to "clamped to [0, max(0, PageCount-1)]" (trivial).

**VMX-114** [Minor/patch · spec · mine-only] — Hub cross-producer ordering MUST (per-producer order preserved across concurrent Send) has no conformance ID or fixture scenario. **Evidence:** 03-messages.md:88-90; HUB-003 is single-producer; message-ordering.json has no multi-producer scenario. **Fix:** add a multi-producer scenario + a HUB-0NN, or downgrade to SHOULD/informative (S).

**VMX-115** [Minor/cosmetic · spec · opencode-only] — Several explicitly impl-defined/MAY behaviors carry no conformance ID (post-Dispose SetValue, duplicate Post, late-arriving events on disposed VMs, AutoConstructOnAdd ordering). **Evidence:** 15-derived-properties.md:79-80; 16-notifications.md:68-73; 02-lifecycle.md:142-143; 06-composite-vm.md:128-132. **Fix:** pin each to one behavior with a covering ID or add to ADR-0009's divergence catalogue (S).

**VMX-116** [Minor/cosmetic · spec · opencode-only] — IDialogService cancellation is opt-in, making DIA-007's no-throw assertion non-universal. **Evidence:** 19-dialogs.md:104-106 opt-in clause. **Fix:** make non-throwing cancellation normative, or split DIA-007 into throwing/non-throwing variants (S).

**VMX-117** [Minor/cosmetic · spec · opencode-only] — LIFE-008 mandates "second concurrent invocation MUST raise" but names no enforcement primitive (lock/CAS/dispatcher). **Evidence:** 02-lifecycle.md:97-98; connects to the non-atomic in-flight guard (VMX-054). **Fix:** note that detection requires a memory-safe guard so flavors don't rely on unsynchronized status reads (trivial).

**VMX-118** [Minor/cosmetic · spec+swift · opencode-only] — The default-dispatchers table (ch.11) omits Swift; ADR-0036 §2.E actually defers the `RxDispatcher.default()` equivalent. **Evidence:** 11-threading.md:24-28 (C#/Py/TS only); ADR-0036 §2.E:55. **Fix:** add a Swift row/footnote noting the Combine presets + the deferred default() (trivial).

**VMX-119** [Minor/patch · spec/fixtures · opencode-only] — Fixtures carry only a bare `$schema-version` string — no JSON Schema, no `$schema` URI, no CI validation; message-ordering.json uses bare single-char symbolic IDs. **Evidence:** each file line 2 `"$schema-version":"1.0.0"`; message-ordering.json:8,15,22,29. **Fix:** add a JSON Schema per fixture + a CI gate; optionally enrich the ordering fixture (S).

**VMX-120** [Minor/cosmetic · spec · opencode-only] — ADR consolidation opportunities — 0020/0021 (editorial-only), the 0044/0045/0046 triple (consecutive days, identical templates), and the 0039/0040/0041 teaching ADRs (0041 is a KEEP). **Evidence:** 0044:55-56 / 0045:52-53 / 0046:36-37 identical clauses; 0039:4. **Fix:** consolidate each cluster into one ADR with a corrected label (S).

**VMX-121** [Minor/cosmetic · spec/docs · opencode-only] — ADR/spec metadata nits — ADR-0009 is 386 lines / 26 subsections (one with no table row); status vocabulary degenerate (44/46 "Accepted"); `###` count is 238 vs README's 237; spec/README §1 is a 159-line hybrid; spec/VERSION is a bare string. **Evidence:** wc/grep on 0009 + 12-conformance.md + spec/README + spec/VERSION. **Fix:** split/forward-link ADR-0009; add Superseded/Deprecated/Rejected statuses; move §1.4-1.8 to CHANGELOG; structure spec/VERSION (S).

**VMX-123** [Minor/minor · spec · opencode-only] — Capability micro-interfaces over-fragment (22 interfaces) — togglable triples mirror lifecycle, the CRUD cluster is 7, and IManagable has no defined semantics. **Evidence:** 14-capabilities.md:9,24; §2.1-2.3 triples; §2.7-2.9 CRUD; §2.9 manage() undefined. **Fix:** collapse togglable triples into one toggle interface + CRUD into fewer parameterized contracts; give IManagable semantics or drop it (M).

**VMX-124** [Minor/cosmetic · spec · opencode-only] — Spec organization — FormVM overlaps ComponentVM<M>+OnModelChanged; ch.07 GroupVM paraphrases ch.06; ICompositeVM<VM> is referenced as canonical but declared only inline in ch.09; \*State helpers scattered ch.05/06/13 vs ch.14; 15:139 InitializationTokens note has no ADR pointer. **Evidence:** 20:31-41 vs 05:77-81; 07 (78 lines); 09-forwarding.md:15-17 vs 06:21. **Fix:** justify FormVM in ADR-0030; reduce ch.07 to a delta; declare ICompositeVM<VM> in ch.06; consolidate \*State; add an ADR pointer at 15:139 (M).

**VMX-125** [Minor/minor · spec+all · opencode-only] — No persistence port and no undo/redo — FormVM takes a consumer persister yet flagships reinvent INoteRepository; commands are fire-only with no inverse. **Evidence:** 00-overview.md:79; 20-form-vm.md:16-17; notes-showcase-scenario.md:287-294; 18-hierarchical:118-122. **Fix:** optionally formalize an IRepository<T>/IPersistence port + an undo/redo stack as opt-in sub-packages, or document flagships own them (M-L).

______________________________________________________________________

### 4.B Cross-cutting (multiple flavors)

**VMX-006** [Important/minor · csharp+python+typescript · mine-only] — Post-dispose `IsCurrent` change leaks a hub `PropertyChangedMessage` (spec/02 invariant 3); Swift suppresses it. **Evidence:** ComponentVMBase.cs:142-151 (equal-value guard only, no disposed guard); base.py:186; componentVMBase.ts:150; Swift :160-169 added the guard. **Fix:** add a `status==Disposed` early-return to the IsCurrent setter in C#/Py/TS (mirror Swift) (S).

**VMX-008** [Important/minor · csharp+python+typescript · both-agree] — FormVM `ApproveCommand` swallows persister failures fire-and-forget — no onApproved, no error event, no canExecuteChanged. **Evidence:** formVm.ts:103; form_vm.py:215-230; FormVM.cs:84-88. **Fix:** expose a failure channel (onApproveFailed/onError) fed from the catch path; document fire-and-forget (M).

**VMX-009** [Important/minor · python+typescript · mine-only] — `ConfirmationDecoratorCommand.execute()` swallows BOTH confirm-rejection AND inner throw — diverges from RelayCommand's propagate contract. **Evidence:** confirmationDecoratorCommand.ts:34-44; confirmation_decorator_command.py:38-47 (loop-dependent). **Fix:** route the caught error to an injected sink/log; make both Python branches consistent (S).

**VMX-017** [Important/patch · csharp+python+typescript · both-agree] — Cross-VM hub subscriptions are hand-wired filters (OfType/instanceof + ReferenceEquals/===) repeated across all three flagships; a typed helper is missing. **Evidence:** WorkspaceVM.cs:184-185; workspace_vm.py:193-194; workspaceVM.ts:194-198. **Fix:** add a `hub.whenPropertyChanged(sender, prop)` typed Observable helper (M).

**VMX-018** [Important/minor · csharp+python (all) · both-agree] — Every ComponentVMBase eagerly builds 5 RelayCommands + Rx subscriptions; SelectNext/SelectPrevious (and 4 of 5 for leaf VMs) are permanently inert. **Evidence:** ComponentVMBase.cs:203-231 (predicates always false :516-520); base.py:112-146. **Fix:** lazily build select/nav commands on first access, or share a disabled-command singleton (M).

**VMX-019** [Important/minor · csharp+python+typescript+swift · both-I-corrected] — AggregateVM per-arity explosion — ~3,951 LOC of near-identical arity-1..6 classes (Py 1,104 / C# 1,329 / TS 833 / Swift 685); the arity-7 deferral trigger is met by intent. **Evidence:** aggregateVM6.ts:55-95; aggregate_vm.py dispose hand-written 6×; theme-vm-scenario.md:113-125. **Fix:** collapse to a tuple/variadic `AggregateVM<TTuple>` (one class/flavor) or hard-cap at 5/6 and route extras through Composite/Group (L).

**VMX-020** [Important/minor · csharp+python+typescript+swift · both-I-corrected] — Immutable copy-on-write builders are large (~1,000–1,200 LOC/flavor) with a 4-call+Build happy-path ceremony. **Evidence:** componentVMOf.ts:85-160; ComponentVMBuilder.cs (422 lines); Python non-aggregate builders ~993 LOC. **Fix:** add a positional-options ctor or DI-aware builder as an additive shortcut (M).

**VMX-025** [Important/minor · csharp+python+typescript+swift · both-agree] — No foreground-marshalling primitive — background status transitions, Subject emissions, and child-collection mutations all fire on the pool thread with no hop. **Evidence:** `grep observeOn` src = 0; ComponentVMBase.cs:267-284; base.py:270-280; TS asapScheduler stays single-threaded. **Fix:** ship an `ObserveOn(Foreground)` helper / marshal SetStatus+Subject emission to foreground inside the bg callback; document the collection single-thread contract (M).

**VMX-053** [Minor/patch · csharp+python+typescript · both-I-corrected] — NotificationHub publishes Subject.OnNext inside the lock (held-lock-across-callback tradeoff); the alleged re-entry deadlock is **refuted**. **Evidence:** NotificationHub.cs:41,55,76 under `lock(_lock)`; notification_hub.py:63 RLock. **Fix:** keep as-is (documented; reentrant lock is the gold-standard pattern) or snapshot under lock + emit outside (S).

**VMX-054** [Minor/patch · csharp+python+typescript+swift · mine-only] — The in-flight reentrancy guard is a non-atomic check-then-set — safe only under the documented single-foreground-thread contract; the C# `_inFlight`-volatile / `_status`-non-volatile asymmetry is the root of VMX-001. **Evidence:** ComponentVMBase.cs:258-260; Py/TS/Swift structurally identical. **Fix:** if multi-thread lifecycle is ever supported, use Interlocked.CompareExchange/atomic CAS/lock (S).

**VMX-069** [Minor/patch · csharp+python+typescript · opencode-only] — All flavors embed spec fixtures via fragile relative paths / unbounded walks — builds break or exit 1 outside the monorepo. **Evidence:** VMx.csproj:30-32 (4 levels up); pyproject.toml:48-52 + transition_validator.py:42-53 unbounded parents walk; sync-fixtures.mjs:13 + package.json:46,50 `process.exit(1)`. **Fix:** bundle fixtures inside each package tree / use a repo-root MSBuild property / short-circuit sync when present (S).

**VMX-083** [Minor/cosmetic · csharp+python+typescript+swift · both-I-corrected] — Cross-flavor naming/INPC-shape divergences are real but documented — `ComponentVM<M>` (C#) vs `ComponentVMOf<M>`; INPC (sender+args) vs `Observable<string>` (name only). **Evidence:** docs csharp.md:97; ComponentVMOf.swift:4; ADR-0009. **Fix:** none warranted for naming; reconcile the ADR-0009 Python member name; optionally expose a uniform sender (S).

**VMX-094** [Minor/minor · typescript+csharp · both-agree] — TS hand-rolls `Subscription[]` + for-loop unsubscribe everywhere (zero takeUntil) and the loops are not exception-safe; C# mixes CompositeDisposable with raw `List<IDisposable>`. **Evidence:** relayCommand.ts:29/66/122/159 (`grep takeUntil` = 0); :66 loop aborts on a throwing unsubscribe. **Fix:** aggregate via a single root Subscription (`root.add(child)`) or `takeUntil(destroy$)` (M).

**VMX-095** [Minor/cosmetic · typescript+python · both-I-corrected] — RelayCommand vs RelayCommandOf<T> duplication; Python RelayCommandOf alias deferred to v3.0.0; TS `#disposed` set-but-never-read in 3 command classes. **Evidence:** relayCommand.ts:25/118; relay_command.py:277-278; decoratorCommand.ts:20/61 et al. **Fix:** collapse the TS pair via `RelayCommand<T=void>`; delete the dead `#disposed` flags; keep aliases until v3.0.0 (S).

**VMX-135** [Important/minor · python+csharp+typescript · new (completeness-critic)] — NotificationVM exposes decaying UI-bindable state (remaining_time/opacity/is_resolved) with **no change-notification** in any binding-capable flavor — more impactful in C#/TS (real WPF/Avalonia/React views never repaint the fade-out). **Evidence:** NotificationVM.cs:70-93 plain computed getters (`grep PropertyChanged|.Send(` = 0); notificationVm.ts:110-117 plain getters (`grep propertyChanged|.next(|emit` = 0); Python origin VMX-079. **Fix:** emit a periodic PropertyChangedMessage on each scheduler tick, or document the three properties as poll-only in spec ch.16 (S). *Consolidates/elevates the Python-only VMX-079.*

______________________________________________________________________

### 4.C Per-flavor

#### 4.C.1 C\#

**VMX-001** [Critical/breaking · csharp · both-I-corrected] — Background `SetStatus()` races `Dispose()` → resurrection + post-dispose hub publish + `ObjectDisposedException` on the pool thread. **Evidence:** ComponentVMBase.cs:74 `_status` NOT volatile (only `_inFlight` is); bg lambda :273, SetStatus :528 — no acquire barrier; exploitable under TaskPoolScheduler. **Fix:** guard `_status` RMW + Subject emission under one lock/Interlocked CAS; re-check Disposed under sync before OnNext (M).

**VMX-011** [Important/minor · csharp · mine-only] — ModeledCrudCommands Update/Delete CanExecute depends on `current()` but wires no trigger — bound buttons never refresh. **Evidence:** ModeledCrudCommands.cs:42-49 `.Predicate(()=>current() is not null)` with no `.Triggers(...)`; RelayCommand.cs:32-33 raises only from triggers. **Fix:** accept an optional selection-changed trigger feeding the builders, or have CompositeVM push current-changed in (M).

**VMX-012** [Important/minor · csharp · mine-only] — Fluent command decorators return `ICommand`, hiding `IDisposable` — chained intermediates stay event-rooted and leak. **Evidence:** FluentCommandExtensions.cs:18-58; ConfirmationDecoratorCommand.cs:26 subscribes in ctor, detaches only on Dispose. **Fix:** return the concrete IDisposable decorator (or `ICommand & IDisposable`); outer decorators own+dispose inner (M).

**VMX-021** [Important/patch · csharp · opencode-only] — Builders mandate `Services(hub,dispatcher)` with no `IServiceProvider`/DI overload despite shipping VMx.Extensions.DependencyInjection. **Evidence:** BuilderValidationException.Require on unset Services(); no SP bridge. **Fix:** add a `Services(IServiceProvider)` overload (S).

**VMX-022** [Important/minor · csharp · both-agree] — The netstandard2.0 build path (its `#if` branches + polyfills) has zero runtime coverage — tests target net9.0 only and resolve the net8.0 asset. **Evidence:** VMx.csproj multi-targets `netstandard2.0;net8.0`; both test projects single `net9.0`. **Fix:** add a test TFM forcing the netstandard2.0 reference path (M).

**VMX-063** [Minor/patch · csharp · both-agree] — `default!` lies — DerivedProperty stores `default!` for reference TValue, and RelayCommand<T> coerces a null/mismatched parameter to `default!` then hands it to the user delegate. **Evidence:** DerivedProperty.cs:16; RelayCommandT.cs:49/62. **Fix:** gate via `_hasValue` / treat `parameter is not T` as CanExecute=false; or require `where T:notnull` (S).

**VMX-064** [Minor/patch · csharp · both-agree] — FormVM.DefaultSnapshotter resolves `MemberwiseClone` by reflection on every snapshot (uncached) and `notnull` permits value types (double-boxes the struct); also a shallow clone. **Evidence:** FormVM.cs:225-234 re-resolves MethodInfo each call (construct :76, Approve :217, Deny :189). **Fix:** hoist GetMethod into a static readonly per closed generic, or use a compiled delegate / require record `with{}` (S).

**VMX-065** [Minor/cosmetic · csharp · both-I-corrected] — ~73 `#pragma warning disable` — the project-wide CA1715/CA1000/CA1716 suppressions (49) belong in .editorconfig, not per-file. **Evidence:** src pragma count 73 (CA1715=34, CA1000=15, CA1816=8, …); langs/csharp/.editorconfig is the canonical home. **Fix:** move blanket CA1715/CA1000/CA1716 to .editorconfig; keep pragmas only for local CS8601/CA1711/CA1051 (S).

**VMX-066** [Minor/cosmetic · csharp · both-I-corrected] — `GC.SuppressFinalize(this)` is dead — exactly **4** real call sites, zero finalizers, plus 8 CA1816 pragma pairs in derived overrides. **Evidence:** zero `~Type(`; sites NotificationVM:117, ForwardingComponentVM:137, ForwardingCompositeVM:205, ComponentVMBase:493 (controller-fixed count). **Fix:** drop the 4 calls + the now-unneeded CA1816 pragmas; centralize CA1816=none in .editorconfig (S).

**VMX-067** [Minor/patch · csharp · both-I-corrected] — Disposal-pattern inconsistency — ModeledCrudCommands uses a raw `List<IDisposable>` while RelayCommand uses CompositeDisposable; the "22 types each with its own bool" framing is overstated (17 types, 13 fields). **Evidence:** ModeledCrudCommands.cs:23 vs RelayCommand.cs:26. **Fix:** use CompositeDisposable in ModeledCrudCommands; optionally a shared dispose-guard base (S).

**VMX-068** [Minor/cosmetic · csharp · opencode-only] — LinqHelpers ships CartesianProduct/Sample/Product (domain-unrelated, ADR-0033 C#-only) in the `VMx.Extensions` namespace. **Evidence:** LinqHelpers.cs:21/40/67. **Fix:** relocate to a `VMx.Linq` namespace or drop (S).

**VMX-070** [Minor/patch · csharp · opencode-only] — Explicit PackageReference Microsoft.Bcl.AsyncInterfaces is dead — no IAsync\*/await-using/ValueTask usage anywhere. **Evidence:** Directory.Packages.props:18 + VMx.csproj:17; 0 hits for IAsyncDisposable/IAsyncEnumerable/await using/ValueTask. **Fix:** drop the explicit PackageReference (verify not needed transitively on ns2.0) (S).

**VMX-071** [Minor/patch · csharp · mine-only] — ObservableDictionary.TryGetValue suppresses CS8601 instead of carrying `[MaybeNullWhen(false)]` — lies to caller nullable flow. **Evidence:** ObservableDictionary.cs:271-278 `#pragma disable CS8601` around `out value!`. **Fix:** `[MaybeNullWhen(false)] out TValue value` (polyfill for ns2.0) + delete the pragma (S).

**VMX-072** [Minor/cosmetic · csharp · mine-only] — net8.0 target carries 6 CA1510 suppressions for `ArgumentNullException.ThrowIfNull` it could actually call. **Evidence:** 6 pragma pairs (FormVM.cs:65,159; FormVMBuilder.cs:64; HierarchicalVM.cs:184,207,235). **Fix:** add a `#if NETSTANDARD2_0` ThrowIfNull polyfill + call the BCL helper; remove the 6 pragmas (S).

**VMX-073** [Minor/cosmetic · csharp · mine-only] — LifecycleTransitionValidator.Find does an O(n) linear scan recomputing `from.ToString()` per row on every guarded lifecycle op. **Evidence:** LifecycleTransitionValidator.cs:81-84 (enum→string alloc inside the lambda). **Fix:** hoist `from.ToString()` out of the predicate; build a `Dictionary<(string,string),Row>` index at load (S).

**VMX-097** [Minor/patch · csharp · both-agree] — MessageHub.Send swallows ObjectDisposedException behind a non-atomic `_disposed` pre-check — a benign, documented shutdown-time drop (verified SAFE). **Evidence:** MessageHub.cs:35/38/40-46. **Fix:** optional `Debug.Assert` in the catch to surface shutdown races in tests; optionally mark `_disposed` volatile (S).

**VMX-136** [Minor/patch · csharp · new (completeness-critic)] — DI `AddVMx` is non-idempotent — uses `AddSingleton` (not `TryAddSingleton`), so calling it twice (library + app) double-registers and constructs+disposes two MessageHub/RxDispatcher singletons. **Evidence:** ServiceCollectionExtensions.cs:39/42/50; DependencyInjectionTests.cs covers only single-call registration. **Fix:** use `TryAddSingleton` for IMessageHub/IDispatcher (or document AddVMx as call-once); add an idempotency test asserting one descriptor after two calls (S).

#### 4.C.2 Python

**VMX-004** [Important/minor · python · both-agree] — `_ComponentVMBase` background `_set_status()` vs `dispose()` resurrection race (GIL-bounded TOCTOU). **Evidence:** base.py:94-104 plain attrs, no Lock; `_bg_construct` :274 check-then-act; RxDispatcher.asyncio() bg = real thread. **Fix:** RLock around `_set_status` RMW and dispose()'s status flip; re-check DISPOSED under lock (M).

**VMX-007** [Important/minor · python · mine-only] — An exception in `_on_construct`/`_on_destruct` wedges the VM permanently in the transient state (un-retryable). **Evidence:** base.py:281-288 leaves status CONSTRUCTING on hook throw; only dispose() is then legal. **Fix:** roll status back to the pre-transition value on hook exception before re-raising, or transition to a documented error state (S).

**VMX-010** [Important/minor · python · mine-only] — FormVM snapshot/revert uses shallow copy — nested mutation is invisible to is_dirty and un-revertable. **Evidence:** form_vm.py:64-69 default `snapshotter=copy.copy`; is_dirty :113; revert :201. **Fix:** default to `copy.deepcopy`, or document consumers must replace the whole model via set_model (S).

**VMX-013** [Important/patch · python · both-agree] — Returns live Subjects from Observable-typed (and one Subject-typed) properties — external code can inject/tear down internal streams. **Evidence:** base.py:200; relay_command.py:95,208; observable_list.py:58-78; group_vm.py:103 (typed `Subject`, worst); +5 more sites. **Fix:** return `subject.pipe(operators.as_observable())` everywhere a Subject backs a public property (S).

**VMX-014** [Important/patch · python · mine-only] — ObservableDictionary.keys1/keys2 hand out the live, fully-mutable backing ObservableList — key-axis view desyncs silently. **Evidence:** observable_dictionary.py:90-98 return `self._keys1`/`_keys2`. **Fix:** expose a read-only projection (tuple + on_keys1_changed, or a read-only wrapper) (S).

**VMX-015** [Important/minor · python · mine-only] — Builders/ctors require the concrete MessageHub, defeating MessageHubProto (the advertised extension point) and forcing `type: ignore`. **Evidence:** builders.py:58,155,270; base.py:79; NULL_MESSAGE_HUB typed Proto but needs `# type: ignore` (builders.py:92,194,301). **Fix:** type hub params as `MessageHubProto[Message]` throughout (S).

**VMX-074** [Minor/patch · python · both-I-corrected] — ForwardingCompositeVM calls a mutation surface absent from CompositeVMProto — 10 `# type: ignore` mask a real Protocol/wrapper mismatch. **Evidence:** forwarding/composite.py:176-214 call add/insert/remove_at/etc. not on the Proto. **Fix:** add the MutableSequence-mutation members to CompositeVMProto, or type `_wrapped` as concrete `_CompositeVMBase` (S).

**VMX-075** [Minor/patch · python · mine-only] — Serviced collections type the hub as bare `object` then `# type: ignore[attr-defined]` to call `.send` — a mypy soundness hole. **Evidence:** serviced_observable_collection.py:36/142; observable_dictionary.py:46/257. **Fix:** type `hub: MessageHubProto[...] | None` and drop the ignore (S).

**VMX-076** [Minor/minor · python · mine-only] — RxDispatcher.asyncio() creates an event loop it never closes (FD leak) and never runs (foreground.schedule silently no-ops). **Evidence:** dispatcher.py:79-83 `asyncio.new_event_loop()` stored only inside the scheduler, never started/closed. **Fix:** require the caller to pass a running loop, or expose+document the loop and register cleanup (S).

**VMX-077** [Minor/patch · python · mine-only] — GroupVM allocates a throwaway `_GroupParent` per child op, and group children's inherited select_command reports CanExecute=true yet is a no-op. **Evidence:** group_vm.py:279-281 new `_GroupParent(self)` per op; `_GroupParent.current_child` always None (:307); can_select True but select() no-ops. **Fix:** cache a single \_GroupParent; make group children's can_select False (or omit their select_command) (S).

**VMX-078** [Minor/patch · python · mine-only] — HierarchicalVM.children/path return the live cached list under a `Sequence` hint — a caller mutating it corrupts the HIER-004 cache + every descendant's path. **Evidence:** hierarchical_vm.py:137-148 (`children`), :152-162 (`path`). **Fix:** return `tuple(...)` / a read-only view, or document the identity guarantee is internal and return a copy (S). *Distinct from the refuted opencode `_path_cache` staleness claim (VMX-A10).*

**VMX-079** [Minor/minor · python · mine-only] — NotificationVM exposes time-varying "UI-bindable" state (remaining_time/opacity/is_resolved) with no change-notification observable. **Evidence:** notification_vm.py:24 docstring "UI-bindable" but no `property_changed`; is_resolved flips in \_dismiss/\_resolve_with (:163-191). **Fix:** add an INPC-style property_changed Subject from the resolve paths, or document poll-only (S). *Re-scoped/elevated per completeness-critic to a cross-flavor Important defect — see the consolidated **VMX-135** (adds C#/TS evidence + the spec ch.16 doc fix).*

**VMX-080** [Minor/patch · python · opencode-only] — Module-import side effects — IConstructable/IDestructable/IReconstructable `.register(...)` runs 9 ABC registrations at import; HierarchicalVM silently fabricates an isolated MessageHub default. **Evidence:** __init__.py:281-289 nine `.register()`; hierarchical_vm.py:67-68 defaults hub/dispatcher while base + builders make them required. **Fix:** register via `__init_subclass__`; require hub/dispatcher on HierarchicalVM (or warn on cross-hub child add) (S).

**VMX-081** [Minor/cosmetic · python · opencode-only] — Public surface is large/redundant — `__all__` exports 126 symbols including 18 aggregate entries under two parallel builder-naming schemes. **Evidence:** AST `__all__`=126; aggregate=18 (6 classes + 12 builders via two schemes); ~21 I-capability entries. **Fix:** drop one redundant aggregate-builder naming scheme; reconsider exporting all ~20 capability micro-interfaces (S).

**VMX-082** [Minor/patch · python · opencode-only] — MessageHub.\_subscribe_safely swallows handler exceptions silently (`except Exception: pass`) with no logging hook. **Evidence:** message_hub.py:58-62. **Fix:** add a `logging.getLogger(__name__).exception(...)` (or injectable error hook) inside the except, keeping HUB-007 isolation (S).

**VMX-096** [Minor/patch · python · both-I-corrected] — ObservableList/ObservableDictionary have no dispose() — their 5/4 backing Subjects are never on_completed()'d. **Evidence:** `grep 'def dispose'` → only batch.py + paged_composition.py; observable_list.py:46-51 (5 Subjects), observable_dictionary.py:59-62 (4). **Fix:** add dispose() calling on_completed() on each subject (mirror paged_composition.py:196) (S).

**VMX-137** [Minor/cosmetic · python · new (completeness-critic)] — tree `walk.py` aggregate-slot probe hardcodes `range(1, 7)`, silently coupled to max arity 6 — adding AggregateVM7 makes walk()/walk_expanded()/find() drop slot 7+ with no test failure. **Evidence:** langs/python/src/vmx/tree/walk.py:62 `for i in range(1, 7): getattr(node, f"component_{i}")`. **Fix:** derive the slot count from declared arity (an IAggregateSlots/__slots_count__ probe) or add a max-arity conformance test; at minimum bind the literal to MAX_AGGREGATE_ARITY (S). *Mirrors the TS impl bug VMX-023 and the spec divergence VMX-112.*

#### 4.C.3 TypeScript

**VMX-003** [Critical/breaking · typescript · both-I-corrected] — `FormVM.isDirty` uses `JSON.stringify` — hard crash on BigInt/circular, silently wrong on Map/Set/Date/undefined/NaN/-0/key-order. **Evidence:** formVm.ts:127; default snapshotter is structuredClone, so it clones faithfully but compares brokenly; isDirty throw cascades to setModel/deny/approve predicate. **Fix:** structural deep-equal mirroring structuredClone semantics (order-insensitive), or a stable structural hash, or constrain TM AND guard isDirty against throw (M).

**VMX-016** [Important/minor · typescript · both-agree] — Message base uses untyped `senderObject` while Python/C# expose a single typed `sender` — a structural field-name split across every hub subscriber. **Evidence:** types.ts:9-10 `senderObject:object`; typed `sender` only on `ITypedMessage<TSender>`. **Fix:** expose a typed `sender` fallback on the base or align naming (M).

**VMX-023** [Important/minor · typescript · both-agree] — `walk.ts` reflects `component${i}` for i=1..6 only — AggregateVM7's component7 slot is silently dropped from traversal. **Evidence:** walk.ts:48-51 stringly-typed reflection bounded at 6. **Fix:** have aggregates expose a typed `components()` iterable / Symbol.iterator instead of slot reflection (M).

**VMX-024** [Important/minor · typescript · both-agree] — Dual-entry build (`splitting:false`) duplicates first-party classes — `dismissCommand instanceof RelayCommand` is false across "@vmx" and "@vmx/notifications". **Evidence:** tsup.config.ts two entries; dist/notifications.js:101 redefines RelayCommand; also emits a hashed dts chunk. **Fix:** enable `splitting:true` (esm) so shared chunks hoist, or single-entry + re-export (S).

**VMX-084** [Minor/cosmetic · typescript · both-I-corrected] — `hierarchicalVm.ts` is a 488-line CRTP god-file (recursive-VM/path-cache/structural-mutation) with a 137-line embedded builder and 12 `as unknown as TVM` self-casts. **Evidence:** wc -l 488; builder spans 351-488; `grep -c "as unknown as"`=12. **Fix:** introduce a HierarchicalNode<TModel> interface to remove the casts; extract the builder; separate cache/mutation mixins (M).

**VMX-085** [Minor/patch · typescript · both-agree] — HUB-007 swallow is partial and test-only-safe — a global no-op `config.onUnhandledError` in tests/setup.ts masks rxjs errors suite-wide; production has no such patch. **Evidence:** messageHub.ts try/catch + class doc :8-11; tests/setup.ts:14 global patch. **Fix:** scope the test suppression to HUB-007 tests; funnel swallowed errors to an injectable diagnostic sink (M).

**VMX-086** [Minor/patch · typescript · both-agree] — RxDispatcher.immediate() uses queueScheduler for BOTH fg+bg — asyncSelection=true and background scheduling are no-ops and the TOCTOU re-check guard (compositeVMBase.ts:342) is dead code in every conformance test. **Evidence:** dispatcher.ts:28; guard :342 can never fire. **Fix:** add a conformance dispatcher with a truly async foreground to exercise asyncSelection + the TOCTOU guard (M).

**VMX-087** [Minor/cosmetic · typescript · mine-only] — RxDispatcher.default() uses asapScheduler (microtask) for "background" — it drains before paint/timers/I-O and can starve the loop; the name implies macrotask deferral. **Evidence:** dispatcher.ts:31-40; doc :35-36 admits asyncScheduler is the macrotask path. **Fix:** use asyncScheduler for default() background, or rename/doc (S).

**VMX-088** [Minor/cosmetic · typescript · opencode-only] — Commits src/fixtures/\*.json with no AUTO-GENERATED marker / no linguist-generated attribute, and pretest auto-syncs them — hiding contributor drift. **Evidence:** 4 JSON fixtures; no langs/typescript/.gitattributes; package.json:47 `pretest: sync-fixtures`. **Fix:** add `linguist-generated` for src/fixtures + a CI drift gate (S).

**VMX-089** [Minor/cosmetic · typescript · opencode-only] — eslint disables `@typescript-eslint/no-unsafe-return` globally for a local SENTINEL + copy-constructor builder problem. **Evidence:** eslint.config.js:46 (rule off in the main block). **Fix:** introduce a branded `Sentinel<T>` / cast at the sentinel boundary and re-enable the rule (M).

**VMX-090** [Minor/cosmetic · typescript · both-agree] — `as T`/`as TValue` casts re-widen noUncheckedIndexedAccess across collections — invariant violations surface as `undefined` masquerading as a value, not a loud throw. **Evidence:** observableDictionary.ts:180/224/320-322; observableList.ts:130/144/169; +more (dictionary-iterator casts sound only while 4 maps stay in sync). **Fix:** `const x=map.get(k); if(x===undefined)throw` to convert silent masking into a loud failure (S).

**VMX-091** [Minor/patch · typescript · mine-only] — transitionValidator.finalState casts `row.to_final as keyof typeof ConstructionStatus` unchecked — a fixture typo yields `undefined` typed as ConstructionStatus, flowing into \_setStatus. **Evidence:** transitionValidator.ts:71-72; guard only checks `===null`, not membership. **Fix:** validate `key in ConstructionStatus` before indexing and throw on miss, or validate the fixture at load (S).

**VMX-092** [Minor/cosmetic · typescript · mine-only] — ConfirmationVM arms a full-lifespan (default 300s) no-op expiry timer on every instance, pinning a scheduler action + closure for no effect. **Evidence:** notificationVm.ts:67-71 ctor schedules onExpire; confirmationVm.ts:50-52 overrides it to a no-op. **Fix:** let subclasses opt out of arming the expiry timer, or have ConfirmationVM not schedule (S).

**VMX-093** [Minor/cosmetic · typescript · mine-only] — SearchableState.filtered does not react to source item mutations — only term change / explicit search() refresh it (unlike PagedComposition). **Evidence:** searchableState.ts:42-58,84-90; `#items` is an unobserved thunk; same-term setter early-returns (:67). **Fix:** document that callers must call search() after mutating the source, or subscribe to a mutation observable (S).

**VMX-104** [Minor/cosmetic · typescript · mine-only] — selectNext/selectPrevious commands omit the status trigger, so their canExecuteChanged never fires (C#/Py/Swift wire it) — undocumented drift. **Evidence:** componentVMBase.ts:90-101 `.predicate(()=>false).build()` (no `.triggers`). **Fix:** add `.triggers(trigger)` to the two placeholder commands, or document the omission (S). *Distinct from the refuted "Swift selectNext inert" claim (VMX-A11).*

#### 4.C.4 Swift

**VMX-002** [Critical/breaking · swift · mine-only] — `ComponentVMBase` background lifecycle is an unsynchronized data race (UB) on plain `var status`/`inFlight`/`triggersDisposed` — no volatile/lock/actor; ThreadSanitizer-flaggable. **Evidence:** ComponentVMBase.swift:58-59,71; DefaultDispatcher.scheduleBackground (Dispatcher.swift:40) = real bg thread. **Fix:** serialize lifecycle state behind a DispatchQueue/os_unfair_lock or model the VM as `actor`/`@MainActor`; re-check `.disposed` under the lock in `_setStatus` (M). *opencode never analyzed the Swift race.*

**VMX-005** [Important/minor · swift · mine-only] — Non-Equatable modeled VMs publish on EVERY model set — violates HUB-005 idempotent-set and diverges from C#/Py/TS identity suppression. **Evidence:** ComponentVMOf.swift:22/57-78 defaults `modelEquals = {_,_ in false}` (builder :106). **Fix:** default modelEquals to reference identity when Model is a class (`is AnyObject`) (M).

**VMX-026** [Important/minor · swift · both-agree] — CompositeVM.current setter traps (`preconditionFailure`) on a non-child — an additional undocumented uncatchable trap vs C#/Py/TS catchable throw. **Evidence:** CompositeVM.swift:133-137 reachable from the public setter (:68-71); ADR-0037 §2.5 enumerates only two traps. **Fix:** document the membership trap, or (preferred) make it throwing (S).

**VMX-027** [Important/minor · swift · both-agree] — HUB-007 is structurally unsatisfiable — a throwing subscriber crashes the whole process (acknowledged in source, not mitigated). **Evidence:** MessageHub.swift:6-13 header admission; send() :41-44 bare PassthroughSubject.send, no per-subscriber isolation. **Fix:** an isolating dispatch / custom multicast catching per-subscriber — worth elevating above "documented" (it is a process-kill) (M).

**VMX-028** [Important/minor · swift · both-agree] — Illegal lifecycle transitions (and the in-flight reentrancy guard) surface as uncatchable `preconditionFailure` traps vs C#/Py/TS catchable exceptions. **Evidence:** ComponentVMBase.swift:205-216, :219-224. **Fix:** documented (ADR-0037 §2.5) — pre-flight via canConstruct()/canDestruct()/canReconstruct(); a throwing variant is a possible future major (n/a).

**VMX-098** [Minor/minor · swift · mine-only] — GroupVM/CompositeVM selectChild/deselectChild silently no-op on an illegal selection (where C# throws), and the select-through-child path drops the Constructed-status gate. **Evidence:** CompositeVM.swift:47-58 (no `vm.status==.constructed` check) vs C# ComponentVMBase.cs:498-514. **Fix:** add a `status==.constructed` guard in selectChild (mirror CanSelectComponent) (S).

**VMX-099** [Minor/minor · swift · both-agree] — DefaultDispatcher is effectively dead/untested — scheduleForeground has zero internal callers and the async background hop is never exercised. **Evidence:** `grep scheduleForeground` Sources = protocol+impls only; `grep DefaultDispatcher` Tests/ = 0. **Fix:** add a test scheduling on DefaultDispatcher and awaiting the async hop, or exclude from the public surface until covered (S).

**VMX-100** [Minor/cosmetic · swift · both-I-corrected] — `ReadonlyComponentVMOf.builder()` (inherited) returns a WRITABLE ComponentVMOf — a static-resolution footgun (callers must use ReadonlyComponentVMOfBuilder directly). **Evidence:** ReadonlyComponentVMOf.swift:34-43 documents the inexpressible shadow; the `model` setter IS narrowed (:23-32). **Fix:** provide a distinctly named `readonlyBuilder()`/free function and call it out louder than a class comment (S).

**VMX-101** [Minor/minor · swift · both-I-corrected] — CompositeVM.add omits CollectionChanged and auto-construct — a documented, advertised subset omission (not the "silent ADR-0006 violation" opencode alleged). **Evidence:** CompositeVM.swift:72-75; langs/swift/README §5:146-148 lists it under "Not claimed". **Fix:** only if Swift promotes COMP-001 into its claimed set (then implement emit); otherwise documented, no action (M if promoting).

**VMX-102** [Minor/cosmetic · swift · mine-only] — `_setModel` short-circuits the model FIELD update (not just the publish) after dispose — the disposed-VM model getter returns a stale value, unlike C#. **Evidence:** ComponentVMOf.swift:59-61 guard placed BEFORE `_model=value`; C# field updates (only the send no-ops). **Fix:** move the disposed guard to wrap only the publish/callback side, or document the divergence (S).

**VMX-103** [Minor/cosmetic · swift · both-I-corrected] — The hand-rolled lifecycle transition table is correct today but a drift risk — hand-encoded + default-branch fallthrough, with LIFE-011 (load the JSON) explicitly deferred. **Evidence:** ComponentVMBase.swift:405-421 matches all 12 fixture rows; no JSON copy under langs/swift; comment :399-403 defers. **Fix:** implement LIFE-011 (load the shared JSON) + a test asserting the table equals the fixture (M).

**VMX-105** [Minor/cosmetic · swift · mine-only] — Confirmed-correct Swift divergences (recorded so reviewers don't re-flag) — predicate-throws-to-false unreachable, HUB-007 isolation structurally unavailable, concurrent-raise trap; ConstructionStatus ints + NullMessageHub Empty match C#/TS. **Evidence:** RelayCommand.swift:6-14,44-50; MessageHub.swift:7-13; NullMessageHub `Empty(completeImmediately:true)`. **Fix:** none — all documented (ADR-0037, README §5) and behave as claimed (n/a). *Some have actionable siblings: VMX-027, VMX-005.*

### 4.D Examples & ergonomics

**VMX-106** [Minor/cosmetic · csharp+python+typescript · both-I-corrected] — "Round-3 Critical-2" / "real-wiring audit" comments are duplicated across all three flagships — the same WorkspaceVM wiring bug was re-discovered/fixed per flavor (copy-paste). **Evidence:** WorkspaceVM.cs:42,165 / workspace_vm.py:167 / workspaceVM.ts:68,174. **Fix:** extract a shared WorkspaceVMBase / notes-showcase-core, or ship the cross-VM binding helper (VMX-017) (M).

**VMX-126** [Minor/cosmetic · csharp/wpf · both-I-corrected] — WPF TodoApp does not build off-Windows (EXPECTED — WPF is Windows-only); the Minor residue is that the WPF README does not state it is Windows-only. **Evidence:** `dotnet build` on macOS fails CS0246; README makes no cross-platform claim (controller adjudication #3). **Fix:** add a Windows-only note to the WPF README (optionally a `<Compile Remove>` guard off-Windows) (S).

**VMX-127** [Minor/cosmetic · csharp · mine-only] — C# console/avalonia examples require `DOTNET_ROLL_FORWARD` on a .NET-9-only host — they pin net8.0 while the README implies "runs anywhere the SDK runs". **Evidence:** HelloVMx builds clean but `dotnet run` fails "8.0.0 not found, found 9.0.5"; roll-forward runs to completion. **Fix:** multitarget net8.0;net9.0 or document the roll-forward / net8.0 runtime requirement (S).

**VMX-128** [Minor/cosmetic · csharp (all) · opencode-only] — Hello-world examples impose high cognitive load — ~7 concepts (Hub, Dispatcher, two downcast subscriptions, 9-line builder chain, construct/destruct/dispose) before the first model read. **Evidence:** Program.cs (113 lines): :28/:29/:35/:39/:49-57/:67/:96/:103/:104. **Fix:** provide a leaner facade for first contact (M).

**VMX-129** [Minor/minor · csharp+typescript+python · opencode-only] — Examples need framework-owned view bridges and carry stale wiring TODOs — hand-rolled WPF/Avalonia ICommand bridges, ThemeVM built-but-unwired in all three flagships, WPF uses ObservableCollection (not CompositeVM), C# uses a reflection PropertyChangedMessage cache. **Evidence:** TodoItemVM.cs:90-112; RelayCommandBridge.cs (61 lines); themeVM.ts:6 / ThemeVM.cs:42 / theme_vm.py:28 TODOs; MainWindowViewModel:34; BindableVm.cs:66. **Fix:** ship a framework-owned ICommand bridge; wire ThemeVM into the workspace; consider adopting Swift's non-generic message base in C# (M).

**VMX-130** [Minor/minor · all · opencode-only] — Five spec chapters have zero real example coverage — ch.09 Forwarding, ch.13 walkExpanded/find, ch.14 capability micro-interfaces, ch.17 Localization, ch.18 HierarchicalVM (flagships substitute a flat ParentId collection). **Evidence:** no Forward\*/walkExpanded/Localization/HierarchicalVM usage in example source; NotebooksRootVM.cs:20-31 uses a flat ParentId list. **Fix:** add forwarding/localization/HierarchicalVM examples (M).

**VMX-131** [Minor/cosmetic · python+csharp+typescript · opencode-only] — Example code smells — Python triple async-launch wrappers; C# untyped boxed `_focused`; TS SENTINEL symbol for a mandatory dependency; hardcoded-locale curly quotes (parity enforces fragile string-equality); committed-tree Avalonia bin/Debug native libs (gitignored). **Evidence:** workspace_vm.py:415-438; WorkspaceVM.cs:96-106; workspaceVM.ts:42; NoteVM.cs:179. **Fix:** one `_fire(coro)` helper; typed focus; mandatory ctor param; externalize strings (S).

**VMX-132** [Minor/minor · all · opencode-only] — The showcase-parity check is filename-only and content-blind — a \*Tests.cs with zero test bodies passes on name alone, and the parity matrix is hand-curated, not machine-verified. **Evidence:** check-showcase-parity.py:23-25 docstring + :105-106 `_stem_contains`; tool never opens file content. **Fix:** strengthen the parity check to inspect test CONTENT (≥1 assertion per slug) (M). *The "latent substring bug" sub-claim is refuted (VMX-A12).*

**VMX-133** [Minor/cosmetic · csharp+python+typescript · both-I-corrected] — Misc example/coverage nits — the boilerplate-ratio table's flagship totals are unreproducible auditor estimates; the inspector example has only 2 tests + no coverage gate; the React flagship reports 3 npm-audit advisories. **Evidence:** flagship "~totals" (Avalonia ~3,946 etc.) measure higher (4,845 / 5,741 / 5,430); inspector `pytest -q`=2; React `npm install`=3 vulns. **Fix:** recompute the flagship LOC rows from a defined file subset; add inspector tests + a coverage gate; optional `npm audit fix` (S).

### 4.E Documentation, tooling, CI

**VMX-029** [Important/patch · python+csharp+typescript · both-agree] — The conformance coverage scraper is a raw string-match — commented-out marks, empty describe() blocks, and assertion-free stubs all register as "covered" (false green). **Evidence:** check-conformance-coverage.py:85-92 `read_text()` + `finditer`; patterns :72-82 anchor with no comment lookbehind. **Fix:** parse AST / require an enclosing test with ≥1 assertion; at minimum strip comments before matching (M).

**VMX-030** [Important/patch · python+csharp+typescript+swift · mine-only] — The conformance gate (conformance.yml) executes ZERO test bodies — it only string-scrapes coverage; behavioral enforcement lives only in the separate per-flavor workflows. **Evidence:** conformance.yml:30-91 runs ruff/unit-tests/mdformat/coverage-check, no dotnet test/vitest/pytest; suites run in python.yml:65 / csharp.yml:63 / typescript.yml:71 (path-filtered). **Fix:** have the gate invoke each flavor's suite (filtered by Trait/mark), or document that conformance.yml is a coverage-presence check (M). *Controller #2: "zero test bodies" is true ONLY for conformance.yml; the per-flavor workflows DO run the suites.*

**VMX-031** [Important/minor · swift · both-agree] — Swift conformance is entirely unenforced — no Swift scraper; Swift tests carry no conformance IDs, so any Swift parity claim is unsubstantiated by tooling. **Evidence:** check-conformance-coverage.py:120-130 registers only py/cs/ts; conformance.yml:84-90 comment "no swift scraper yet"; Swift Tests/ has 7 files vs ~34/flavor. **Fix:** register a swift scraper, or explicitly document Swift as out-of-scope for conformance gating (M).

**VMX-032** [Important/patch · csharp · mine-only] — The C# conformance project self-admittedly ships placeholder delegators only to satisfy the scraper; spec-id LIFE-001 has NO method asserting under it. **Evidence:** LifecycleConformanceTests.cs:136-144 comment "placeholder [Fact,Trait] entries… so the catalog coverage tool sees each ID"; LIFE-001's sole carrier delegates to a DIFFERENT id (CVM-001). **Fix:** give LIFE-001 a real [Fact,Trait] with its own assertions; gate on execution not string presence (M).

**VMX-033** [Important/minor · all · both-agree] — Fabricated v2.5.0 release row — compatibility-matrix and README advertise four shipped 2.5.0 packages and a 2.5.x row with zero tags that never ran the publish pipeline. **Evidence:** `git tag --list '*2.5.0*'`=empty; compatibility-matrix.md:10 + README.md:159; every CHANGELOG `## [2.5.0] — 2026-06-10`; CONTRIBUTING §4.3:156-162 forbids exactly this. **Fix:** mark the 2.5.x row "(unreleased/superseded by 2.6.0)" in matrix+README+CHANGELOGs, or cut the missing tag family (M).

**VMX-034** [Important/minor · all · both-I-corrected] — No repo-wide v2.5.0/v2.6.0 git tags despite all manifests declaring 2.6.0 — `git checkout v2.6.0` fails, the exact breakage CONTRIBUTING §4 says the tag prevents. **Evidence:** C#/TS 2.6.0, Python 2.6.1; `git tag --list 'v*'`=v2.0.0..v2.4.0; only 4/6 flavor tags for 2.6.0. **Fix:** create v2.5.0/v2.6.0 repo-wide tags or revert the source-version claim; add a release-gate requiring sibling tags (S).

**VMX-035** [Important/minor · spec · mine-only] — No spec-v2.5.0/spec-v2.6.0 tags despite spec/VERSION=2.6.0 — third-party implementers told to "pin to spec-vX.Y.Z" cannot pin 2.5 or 2.6. **Evidence:** spec/VERSION=2.6.0; `git tag --list 'spec-*'` stops at spec-v2.4.0. **Fix:** tag spec-v2.5.0/spec-v2.6.0 at the SHAs where spec/VERSION read those values, or correct docs (S).

**VMX-036** [Important/minor · csharp · both-agree] — release.yml C# job publishes to NuGet with NO test gate — a csharp-v\* tag on an untested commit pushes a permanent package. **Evidence:** release.yml csharp job (25-55) = checkout→pack→`nuget push --skip-duplicate`; no `needs:` test job (Python gates via `needs: python-test`). **Fix:** add a csharp-test `needs:` gate + tag-version-match before push (S-M).

**VMX-037** [Important/minor · typescript · both-agree] — release.yml TypeScript job publishes to npm with NO test gate, no verify-published job, and no provenance/OIDC. **Evidence:** typescript job (262-292) = build→`npm publish`; no test/typecheck; `provenance:true`/`id-token:write` disabled (266-269). **Fix:** add a typescript-test gate, a verify-published job, npm provenance via OIDC, and a package.json-vs-tag check (S-M).

**VMX-038** [Important/minor · swift · opencode-only] — release.yml Swift job has no swift test gate and swift.yml is not tag-triggered — a GitHub Release can point at an untested swift-v\* tag. **Evidence:** release.yml swift job (294-317) = `gh release create` only; swift.yml `on:` (6-18) has no `tags:` trigger. **Fix:** add `swift test` to the release swift job, or trigger swift.yml on swift-v\* tags (S).

**VMX-055** [Minor/patch · python · both-agree] — Python conformance "delegation wrapper" tests assert nothing and double-count — e.g. test_lifecycle.py has 10 one-line delegates whose failures report under the delegate's node, not the conformance ID. **Evidence:** test_property_change.py:20-72 + test_lifecycle.py:150-247 (14 `test_*_delegated`, asserts=0); real marked tests carry the same mark → double-counted, run twice. **Fix:** delete the delegator wrappers (real marked tests already satisfy the scraper) (S).

**VMX-056** [Minor/patch · python+csharp+typescript · mine-only] — No-exception-only conformance tests assert nothing observable (Python DIA-004, CMD-006, COL-022) and are weaker than the C#/TS equivalents. **Evidence:** test_dia_001_to_008.py:94-104 (4× notify, 0 asserts); test_commands.py:72-75; test_col_010_to_015.py:296-307 (no spy). **Fix:** assert the observable invariant (hub-spy received nothing / return value / state-unchanged); standardize per-ID convention (S).

**VMX-057** [Minor/cosmetic · python · mine-only] — Python LIFE-013 delegator is rescued only by a test-prefixed alias (not broken, but the body runs 3×) — a fragility of the delegation anti-pattern. **Evidence:** test_lifecycle.py:244 imports the delegate; real def at test_composite_vm.py:448; alias :548 is itself `test_`-prefixed → collected too. **Fix:** remove the alias + delegator; reference the real test name if delegation is kept (S).

**VMX-058** [Minor/patch · spec · both-agree] — No machine validation cross-checks the README "237" citation against the actual `###` ID count or the scraper catalog. **Evidence:** check-conformance-coverage.py reports 232 catalog but never asserts README "237". **Fix:** extend the scraper to assert the README/spec citation equals the catalog (S).

**VMX-059** [Minor/cosmetic · csharp+python+typescript · both-agree] — README "237 conformance IDs verified on every commit" overstates CI — 232 library IDs are coverage-checked (not behavior), only on path-filtered triggers. **Evidence:** catalog 237 = 232 library + 5 THEME (excluded); conformance.yml + per-language workflows are `paths:`-filtered. **Fix:** reword to "232 library IDs (+5 THEME scenarios) checked for full coverage in CI on changes to spec/tests/tools" (S).

**VMX-060** [Minor/patch · all · both-agree] — No tool reconciles manifest versions ↔ README/compatibility-matrix ↔ git tags — the root cause that let VMX-033/034/035 drift undetected. **Evidence:** tools/ has no `git tag`/`describe`/matrix checker; compatibility-matrix.md:3 "Maintained by hand"; TS check-version-sync.mjs is intra-flavor only. **Fix:** add a CI tool asserting manifest version, matrix row, CHANGELOG top, spec/VERSION agree and have a matching git tag (M).

**VMX-061** [Minor/cosmetic · all · mine-only] — CONTRIBUTING §4.2 "all six tags at one SHA" is not honored for 2.6.0 (only 4/6 families exist). **Evidence:** §4.2:149-150; only csharp-/python-/typescript-/swift-v2.6.0 (+python-v2.6.1); spec + repo-wide absent. **Fix:** add the missing spec + repo-wide tags, or a CI release-gate refusing a flavor tag without siblings (S). *Overlaps VMX-034/035.*

**VMX-062** [Minor/cosmetic · csharp+python+typescript+swift · opencode-only] — spec/README:5-6 pins per-flavor package versions inline (C# 2.6.0 / Python 2.6.1 / TS 2.6.0 / Swift 2.6.0) — Python has already drifted ahead. **Evidence:** spec/README.md:5-6. **Fix:** move version-pinning to the compatibility-matrix; keep the spec README generic (S).

**VMX-122** [Minor/patch · all · both-agree] — No API-surface / cross-flavor parity diff tool exists — the ADR-0006 parity contract is unverified, so the E3.x divergences sit unflagged. **Evidence:** tools/ has only axaml/conformance/layer/showcase-parity/textual checks; the unflagged divergences VMX-016/083/101 corroborate. **Fix:** optional API-surface diff tool comparing the public surface across flavors (L).

**VMX-134** [Minor/cosmetic · all · opencode-only] — Docs/tooling hygiene nits — orphaned docs/superpowers planning content; no langs/typescript or langs/csharp RELEASING.md; missing CI badges; VMx.Notifications 1.2.0 vs spec 2.6.x warrants a note; pre-commit pins (ruff v0.11.11, mdformat 0.7.22, no Swift hook, fragile dotnet-format prefix-strip). **Evidence:** docs/superpowers/plans/...stage-6-release.md:15; `find langs -name RELEASING.md`→python only; README:3-8 badges; .pre-commit-config.yaml:19/33-35/43-70. **Fix:** move/delete docs/superpowers; add TS/C# RELEASING.md; add 3 badges; add a companion-versioning note; add a swift-format hook (S).

______________________________________________________________________

## 5. Swift deep-dive (index for Phase 3)

All 27 findings that touch Swift, for the full-parity phase. Each is rendered in full in §4 (section noted) — this is a pointer list only.

- **VMX-002** [§4.C.4] — Lifecycle is an unsynchronized data race (UB); no volatile/lock/actor. *(Critical)*
- **VMX-005** [§4.C.4] — Non-Equatable model publishes on every set (HUB-005 violation).
- **VMX-019** [§4.B] — AggregateVM per-arity explosion (Swift 685 LOC of arity-1..6).
- **VMX-020** [§4.B] — Copy-on-write builder ceremony (Swift included in the ~1k LOC/flavor).
- **VMX-025** [§4.B] — No foreground-marshalling primitive (Swift DefaultDispatcher hops to a real bg thread).
- **VMX-026** [§4.C.4] — `current` setter traps on a non-child (undocumented uncatchable trap).
- **VMX-027** [§4.C.4] — HUB-007 unsatisfiable; a throwing subscriber kills the process.
- **VMX-028** [§4.C.4] — Illegal lifecycle transitions are uncatchable `preconditionFailure` traps.
- **VMX-030** [§4.E] — Conformance gate runs zero test bodies (Swift among the affected flavors).
- **VMX-031** [§4.E] — Swift conformance entirely unenforced — no scraper, no IDs.
- **VMX-038** [§4.E] — release.yml Swift job has no test gate; swift.yml not tag-triggered.
- **VMX-039** [§4.A] — SelectNext/Previous navigation underspecified (Swift among targeted flavors).
- **VMX-040** [§4.A] — `Parent` never declared as a VM member (Swift among targeted flavors).
- **VMX-041** [§4.A] — Lifecycle hooks have no conformance ID (Swift among targeted flavors).
- **VMX-049** [§4.A] — Background construct racy on non-C# flavors (Swift included).
- **VMX-054** [§4.B] — Non-atomic in-flight reentrancy guard (Swift structurally identical).
- **VMX-062** [§4.E] — spec/README inline version pins (Swift 2.6.0 row).
- **VMX-083** [§4.B] — Naming/INPC-shape divergence `ComponentVMOf<M>` + `AnyPublisher<String>` (documented).
- **VMX-098** [§4.C.4] — selectChild/deselectChild silently no-op on illegal selection; drops Constructed gate.
- **VMX-099** [§4.C.4] — DefaultDispatcher effectively dead/untested.
- **VMX-100** [§4.C.4] — Inherited `builder()` returns a writable VM (static-resolution footgun).
- **VMX-101** [§4.C.4] — CompositeVM.add omits CollectionChanged + auto-construct (documented subset).
- **VMX-102** [§4.C.4] — `_setModel` short-circuits the field update after dispose (stale getter).
- **VMX-103** [§4.C.4] — Hand-rolled lifecycle table is a drift risk; LIFE-011 deferred.
- **VMX-105** [§4.C.4] — Confirmed-correct documented divergences (predicate-throw, HUB-007, traps) — audit record.
- **VMX-107** [§4.A] — ADR-0036/0037 lack an in-body forward reference for the 39→41 reconciliation.
- **VMX-118** [§4.A] — Ch.11 dispatcher table omits Swift; ADR-0036 §2.E defers the default() equivalent.

______________________________________________________________________

## 6. What opencode missed (independent-only)

All 43 `mine-only` findings — the head-to-head value of the independent stream. Each is rendered in full in §4 (section noted).

- **VMX-002** [§4.C.4] — Swift lifecycle data race (UB). *(Critical)*
- **VMX-005** [§4.C.4] — Swift non-Equatable model publishes on every set (HUB-005).
- **VMX-006** [§4.B] — Post-dispose IsCurrent leaks a hub message (C#/Py/TS).
- **VMX-007** [§4.C.2] — Python hook exception wedges the VM in the transient state.
- **VMX-009** [§4.B] — ConfirmationDecoratorCommand swallows reject AND inner throw.
- **VMX-010** [§4.C.2] — Python FormVM shallow snapshot/revert.
- **VMX-011** [§4.C.1] — C# CRUD CanExecute has no trigger (stale buttons).
- **VMX-012** [§4.C.1] — C# fluent command decorators hide IDisposable (leak).
- **VMX-014** [§4.C.2] — Python ObservableDictionary.keys hand out the live backing list.
- **VMX-015** [§4.C.2] — Python builders require concrete MessageHub (defeats Proto).
- **VMX-030** [§4.E] — Conformance gate executes zero test bodies.
- **VMX-032** [§4.E] — C# conformance placeholder delegators; LIFE-001 asserts nothing.
- **VMX-035** [§4.E] — No spec-v2.5/2.6 tags.
- **VMX-039** [§4.A] — SelectNext/Previous navigation underspecified, no coverage.
- **VMX-040** [§4.A] — `Parent` never declared as a VM member.
- **VMX-041** [§4.A] — Lifecycle hooks (ADR-0041) have no conformance ID.
- **VMX-042** [§4.A] — ConfirmationVM no-auto-resolve behavior untested.
- **VMX-043** [§4.A] — ApproveCommand.Execute fire-and-forget unspecified; FORM-007 dangling ref.
- **VMX-044** [§4.A] — Async confirm gating inside sync Execute unspecified.
- **VMX-045** [§4.A] — CompositeVM initial-current selector contradicts §3.1/COMP-009 + ADR-0042.
- **VMX-054** [§4.B] — Non-atomic in-flight reentrancy guard (root of VMX-001).
- **VMX-056** [§4.E] — No-exception-only conformance tests assert nothing observable.
- **VMX-057** [§4.E] — Python LIFE-013 delegator runs 3× (delegation-pattern fragility).
- **VMX-061** [§4.E] — CONTRIBUTING "six tags at one SHA" not honored for 2.6.0.
- **VMX-071** [§4.C.1] — C# TryGetValue suppresses CS8601 instead of `[MaybeNullWhen(false)]`.
- **VMX-072** [§4.C.1] — C# 6 CA1510 suppressions for ThrowIfNull it could call.
- **VMX-073** [§4.C.1] — C# LifecycleTransitionValidator.Find O(n) scan + per-row alloc.
- **VMX-075** [§4.C.2] — Python serviced collections type the hub as bare `object`.
- **VMX-076** [§4.C.2] — Python RxDispatcher.asyncio() leaks a never-closed/never-run loop.
- **VMX-077** [§4.C.2] — Python GroupVM throwaway \_GroupParent + enabled-but-inert select.
- **VMX-078** [§4.C.2] — Python HierarchicalVM.children/path return the live cached list.
- **VMX-079** [§4.C.2] — Python NotificationVM decaying state has no change-notification (→ VMX-135).
- **VMX-087** [§4.C.3] — TS RxDispatcher.default() asapScheduler "background" starves the loop.
- **VMX-091** [§4.C.3] — TS transitionValidator.finalState unchecked enum cast.
- **VMX-092** [§4.C.3] — TS ConfirmationVM arms a 300s no-op expiry timer per instance.
- **VMX-093** [§4.C.3] — TS SearchableState.filtered ignores source-item mutations.
- **VMX-098** [§4.C.4] — Swift selectChild no-ops on illegal selection; drops Constructed gate.
- **VMX-102** [§4.C.4] — Swift `_setModel` short-circuits the field update after dispose.
- **VMX-104** [§4.C.3] — TS selectNext/Previous omit the status trigger (no canExecuteChanged).
- **VMX-105** [§4.C.4] — Swift confirmed-correct documented divergences (audit record).
- **VMX-112** [§4.A] — walk_expanded does not descend AggregateVM slots.
- **VMX-113** [§4.A] — Ch.14 CurrentPageIndex clamp contradicts the empty-source case.
- **VMX-114** [§4.A] — Hub cross-producer ordering MUST has no conformance ID.
- **VMX-127** [§4.D] — C# examples require DOTNET_ROLL_FORWARD on a .NET-9 host.

> Plus 3 further independent discoveries surfaced at final assembly by the completeness-critic: **VMX-135** (NotificationVM cross-flavor, §4.B), **VMX-136** (DI AddVMx non-idempotent, §4.C.1), **VMX-137** (walk.py range(1,7) arity coupling, §4.C.2).

______________________________________________________________________

## 7. Appendix — claims that did not survive verification

The 14 opencode claims refuted or disagreed-with under verification. Each is retired with its disproof. (Real, actionable residue from several of these is preserved as active findings — cross-referenced.)

**VMX-A01** [swift · REFUTED · DISAGREE] — "No ADR reconciles the 39→41 Swift subset" / "README 41 vs ADR-0037 39 is an honesty gap". **Disproof:** the 39→41 progression IS reconciled at 01-concepts.md:48 (ADR-0037 §2.6 = 39; ADR-0042 §35 adds COMP-025/026 = 41; 00-overview.md:67 confirms 41/237). Controller #4 (A2-06). Actionable residue (add an in-body forward link) → active **VMX-107**.

**VMX-A02** [spec · REFUTED · DISAGREE] — "A patch bump requires editing spec/README.md, which requires an ADR". **Disproof:** spec-discipline.yml:43 `grep -v '^spec/README.md$'` exempts spec/README.md; editing it NEVER requires an ADR. Controller #4 (A10-05). The version-drift half stands as active **VMX-062**.

**VMX-A03** [spec · REFUTED · DISAGREE] — "ADR-0044/0045/0046 share the exact title". **Disproof:** 0044:1 (ch.02/ch.15), 0045:1 (ch.06/20/21), 0046:1 (ch.14 IPageable.PageCount) are three distinct H1s with a common prefix only. The consolidation recommendation itself stands as active **VMX-120**.

**VMX-A04** [spec · REFUTED] — "Aggregate PropertyChangedMessage('ComponentN') has no AGG conformance ID". **Disproof:** 12-conformance.md:603-608 AGG-004 asserts exactly the per-slot behavior (three PropertyChangedMessage events with PropertyName ∈ {Component1,Component2,Component3}); 08-aggregate-vm.md:99 lists it.

**VMX-A05** [spec · REFUTED] — "16-notifications.md:84 self-references instead of pointing at 19-dialogs §4". **Disproof:** 16:84 is the section header `### 2.3 Pending`, not a cross-reference; the §5 pointer is at 19-dialogs.md:84 (a valid companion ref) and 16:120 correctly references ch.19. Wrong file and wrong line.

**VMX-A06** [spec · REFUTED] — "13:100 links chapter 18 but chapter 18 never links back". **Disproof:** 18-hierarchical-vm.md:23 and :127 both link back to ch.13 (walk/walk_expanded). The asserted dangling reference does not exist.

**VMX-A07** [spec · CONFIRMED-WITH-CORRECTION · DISAGREE] — "Accessibility is treated as a view concern (00-overview:79); promote AccessibleName/Role to VM state". **Disproof:** 00-overview:79 is about persistence/navigation, NOT accessibility (which appears once, 01-concepts.md:147, scoped out); Hint already carries a human-readable label. Promoting AccessibleName/Role to VM state is a debatable preference, not a defect.

**VMX-A08** [typescript · REFUTED · DISAGREE] — "Builder immutability is asserted in exactly one test". **Disproof:** builders.test.ts:20,25,181,184; formVMBuilder.test.ts:69-75; hierarchicalVMBuilder.test.ts:199 — tested in ≥3 files. Controller #4 (B2-ONETEST).

**VMX-A09** [typescript · REFUTED · DISAGREE] — "The TS flagship uses msg.senderObject". **Disproof:** workspaceVM.ts:197 uses typed `m.sender === notesViewRef`; senderObject is a getter but is not used in the filter. Controller #4 (B3-TSFILTER). The real base-interface split is active **VMX-016**.

**VMX-A10** [python · REFUTED · DISAGREE] — "Python hierarchical \_path_cache is stale after reparent (descendants never invalidated)". **Disproof:** `_set_hierarchical_parent` (:262) sets `_path_cache=None` (:298) AND recursively nulls every descendant's cache (:299→:302-307); add/remove/reparent all route through it. Controller #4. The separate read-only-contract gap (children/path return the live list) is active **VMX-078**.

**VMX-A11** [swift · PARTIALLY REFUTED · DISAGREE] — "Swift selectNext/selectPrevious are inert stubs while other flavors actually work". **Disproof:** C# :516-517, Python :425-435, TS :95-101 all ship permanently-false predicates with no-op/absent tasks — this is PARITY, not a Swift defect. Controller #4. The real, narrower TS-only trigger-wiring gap is active **VMX-104**.

**VMX-A12** [all · REFUTED · DISAGREE] — "check-showcase-parity.py has a latent substring bug (workspace_vm.test in workspacevm.test is False)". **Disproof:** executed `_expected_keys('typescript','workspace_vm')` → `['workspacevm.test']` (the code applies `_camel()` then `.lower()`, removing the underscore), so the membership check is True and the tool exits 0. Controller #4 (D4). The real "filename-only / content-blind" weakness stands as active **VMX-132**.

**VMX-A13** [n/a · REFUTED · opencode's counter-claim is WRONG] — "conformance.yml's git-globstar comment is misleading (modern globstar matches top-level spec/*.md)". **Disproof:** reproduced — `git ls-files 'spec/*.md'`=74 vs `spec/**/*.md`=51; the 23 single-star-only files ARE the top-level spec/*.md, so `spec/**/*.md` genuinely misses them. The comment is correct; only its literal figure ("41 of 64" → "51 of 74") is stale (cosmetic refresh). Controller #4 (E5.4).

**VMX-A14** [docs/hygiene · REFUTED · rec is MOOT] — "Committed .DS_Store files in docs/ and docs/superpowers/". **Disproof:** .DS_Store exist on disk but `git ls-files | grep -i ds_store` = NONE TRACKED; .gitignore:2 = `.DS_Store`. The "git rm committed .DS_Store" recommendation applies to nothing.

______________________________________________________________________

## 8. How to use this report (Phase 2 triage)

1. **Critical + Important first.** The 3 Criticals (VMX-001/002/003) and the 50 Important findings are the Phase-2 backlog; start from the §3 ranked table. The three Criticals plus VMX-004/025/054 form one **lifecycle-concurrency cluster** best fixed together (shared root cause: non-atomic status RMW + no foreground hop).

1. **Cheap-win cluster (trivial/small effort).** A large share of findings are effort `S`/`trivial` and independently shippable: the analyzer/pragma cleanups (VMX-065/066/070/071/072), the nullable/perf nits (VMX-063/073), the spec wording fixes (VMX-113/117/118), the dead-code and read-only-contract returns (VMX-013/014/078/096), and the doc/version reword items (VMX-059/062/107/111). Batch these for fast ledger burn-down.

1. **The breaking-change cluster needs a v3 decision.** Several fixes change observable contracts or public surface and should be gated behind a major: the variadic AggregateVM collapse (VMX-019), positional-options builders (VMX-020), IAsyncCommand + cancellation (VMX-052), making Swift traps throwing (VMX-026/028), the RelayCommandOf alias removal (VMX-095, already v3.0.0-targeted), and any uniform-sender API alignment (VMX-016/083). Decide the v3 scope before touching these.

1. **Release & conformance integrity is a pre-req, not a feature.** Fix the fabricated/missing tags and untested publish pipelines (VMX-033/034/035/036/037/038/060/061) and the conformance-theater items (VMX-029/030/031/032/055/056) before trusting any "232/232 green" or version claim in the rest of triage — they are the measurement layer everything else is reported against.

1. **Swift findings feed Phase 3.** The 27 Swift items indexed in §5 are the input to the full-parity phase; the recoverability/safety set (VMX-002 data race, VMX-026/028 traps, VMX-027 process-kill, VMX-098 selection gate) should be resolved as part of promoting Swift out of its documented subset rather than piecemeal.
