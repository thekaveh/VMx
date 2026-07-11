# TypeScript Raw-Message Predicates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three runner-agnostic TypeScript predicates that safely narrow raw VMx hub messages in `Array.filter` and RxJS `filter` while preserving optional sender/source and field constraints.

**Architecture:** A dependency-free `messages/predicates.ts` module classifies the three existing concrete message classes with `instanceof` and exact optional constraints. The package root and message barrel re-export the functions; no delivery code, RxJS operator, cross-flavor API, or conformance catalog entry changes.

**Tech Stack:** TypeScript 5, RxJS, Vitest, tsup declarations, Markdown/spec ADRs, MkDocs three-surface docs.

## Global Constraints

- Implement only `isPropertyChanged`, `isCollectionChanged`, and `isConstructionStatusChanged` in TypeScript.
- Do not add predicates to C#, Python, Swift, or Rust.
- Do not replace `whenPropertyChanged` or `propertyValueChangedMessagesFor`.
- Use strict sender/source identity and exact property/action/status equality.
- Add no runtime dependency and no RxJS-specific wrapper.
- Keep the conformance catalog at 342 library IDs and 347 total scenarios.
- Advance the synchronized current source line to 3.14.0; Rust advances to 0.14.0.
- Publish documentation from the existing canonical source to repo/site/wiki.
- Pilot DayDreams only in a disposable clone; never push consumer changes.

______________________________________________________________________

### Task 1: Add failing runtime and type-narrowing tests

**Files:**

- Create: `langs/typescript/tests/unit/messages/predicates.test.ts`

**Interfaces:**

- Consumes: existing `IMessage`, `PropertyChangedMessage<TSender>`, `CollectionChangedMessage<TItem>`, `CollectionMutationAction`, `ConstructionStatusChangedMessage`, and `ConstructionStatus`.

- Produces: executable requirements for the three public predicates and their Array/RxJS inferred types.

- [ ] **Step 1: Create the test with root and message-barrel imports**

Use real message instances and a no-op compile-time assertion:

```typescript
function expectType<T>(_value: T): void {}

const sender = { name: "sender" };
const other = { name: "other" };
const property = PropertyChangedMessage.create(sender, "sender", "model");
const collection = CollectionChangedMessage.forAdd<string>(sender, "item", 0);
const status = ConstructionStatusChangedMessage.create(
  sender,
  "sender",
  ConstructionStatus.Constructed,
);
const messages: IMessage[] = [property, collection, status];
```

Import the predicates from `../../../src/index.js`, and alias at least one from `../../../src/messages/index.js` to prove both public export paths.

- [ ] **Step 2: Specify property-message behavior and types**

Assert positive classification, wrong family, wrong sender, and wrong property. Then add:

```typescript
const allProperties = messages.filter(isPropertyChanged);
expectType<PropertyChangedMessage<unknown>[]>(allProperties);

const senderProperties = messages.filter((message) =>
  isPropertyChanged(message, sender, "model"),
);
expectType<PropertyChangedMessage<typeof sender>[]>(senderProperties);

const propertyStream = from(messages).pipe(
  filter((message) => isPropertyChanged(message, sender, "model")),
);
expectType<Observable<PropertyChangedMessage<typeof sender>>>(propertyStream);
```

- [ ] **Step 3: Specify collection and construction behavior and types**

Cover wrong source/action/status and add:

```typescript
const additions = messages.filter((message) =>
  isCollectionChanged<string>(message, sender, "add"),
);
expectType<CollectionChangedMessage<string>[]>(additions);

const constructed = from(messages).pipe(
  filter((message) =>
    isConstructionStatusChanged(
      message,
      sender,
      ConstructionStatus.Constructed,
    ),
  ),
);
expectType<Observable<ConstructionStatusChangedMessage>>(constructed);
```

- [ ] **Step 4: Run the red gates**

Run:

```bash
cd langs/typescript
npx vitest run tests/unit/messages/predicates.test.ts
npm run typecheck:tests
```

Expected: failures because the three exports do not exist. Correct any unrelated test syntax error until the only failures are the missing predicate API/type narrowing.

- [ ] **Step 5: Commit the red test**

```bash
git add langs/typescript/tests/unit/messages/predicates.test.ts
git commit -m "test: specify raw message predicates for #88"
```

______________________________________________________________________

### Task 2: Implement and export the minimal predicates

**Files:**

- Create: `langs/typescript/src/messages/predicates.ts`
- Modify: `langs/typescript/src/messages/index.ts`
- Modify: `langs/typescript/src/index.ts`

**Interfaces:**

- Consumes: the exact message classes and enum/type definitions named in Task 1.

- Produces: the three signatures in the committed design document.

- [ ] **Step 1: Implement `isPropertyChanged`**

```typescript
export function isPropertyChanged<TSender = unknown>(
  message: IMessage,
  sender?: TSender,
  propertyName?: string,
): message is PropertyChangedMessage<TSender> {
  return (
    message instanceof PropertyChangedMessage &&
    (sender === undefined || message.sender === sender) &&
    (propertyName === undefined || message.propertyName === propertyName)
  );
}
```

- [ ] **Step 2: Implement collection and construction predicates**

Use the same early-classification/exact-constraint shape:

```typescript
export function isCollectionChanged<TItem = unknown>(
  message: IMessage,
  source?: object,
  action?: CollectionMutationAction,
): message is CollectionChangedMessage<TItem>;

export function isConstructionStatusChanged(
  message: IMessage,
  sender?: object,
  status?: ConstructionStatus,
): message is ConstructionStatusChangedMessage;
```

Do not add factories, overload aliases, observable allocation, or error handling.

- [ ] **Step 3: Export from both public entry points**

Add one grouped export in `src/messages/index.ts` and one in `src/index.ts`:

```typescript
export {
  isCollectionChanged,
  isConstructionStatusChanged,
  isPropertyChanged,
} from "./messages/predicates.js";
```

Use `./predicates.js` from the message barrel.

- [ ] **Step 4: Run focused green and type gates**

```bash
cd langs/typescript
npx vitest run tests/unit/messages/predicates.test.ts
npm run typecheck
npm run typecheck:tests
npm run lint
```

Expected: the focused runtime tests and inferred type assertions pass without casts or explicit predicate annotations. If contextual generic inference fails, adjust overloads in the implementation rather than weakening the test contract.

- [ ] **Step 5: Build and inspect declarations**

```bash
npm run build
rg -n "isPropertyChanged|isCollectionChanged|isConstructionStatusChanged" dist/index.d.ts dist/index.d.cts
```

Expected: both declaration formats expose all three type-predicate signatures.

- [ ] **Step 6: Commit implementation**

```bash
git add langs/typescript/src/messages/predicates.ts langs/typescript/src/messages/index.ts langs/typescript/src/index.ts
git commit -m "feat: add TypeScript raw message predicates #88"
```

______________________________________________________________________

### Task 3: Record the deliberate TypeScript-only contract and release line

**Files:**

- Create: `spec/ADRs/0094-typescript-raw-message-predicates.md`
- Modify: `spec/ADRs/README.md`
- Modify: `spec/03-messages.md`
- Modify: `spec/VERSION`
- Modify: `compatibility-matrix.md`
- Modify: `README.md`
- Modify: `spec/README.md`
- Modify: all five flavor version declarations, manifests, README current-version claims, and CHANGELOGs
- Modify: `langs/typescript/package-lock.json`

**Interfaces:**

- Consumes: the exact API proven in Tasks 1–2.

- Produces: ADR-0094, source version 3.14.0, stable flavor versions 3.14.0, Rust 0.14.0, and unchanged 342/347 counts.

- [ ] **Step 1: Add ADR-0094 and its index row**

Record the consumer evidence, selected predicates, exact matching semantics,
composition with existing helpers, TypeScript-only applicability, and rejection
of a generic matcher/RxJS operators/cross-flavor parity.

- [ ] **Step 2: Add the non-normative TypeScript subsection**

In `spec/03-messages.md`, document the three names and state explicitly that
they classify existing message objects without changing message semantics. Do
not add a conformance ID or other-flavor requirement.

- [ ] **Step 3: Advance synchronized versions**

Set `spec/VERSION` and every stable flavor's current/minimum spec declaration to
`3.14.0`; set Rust package/current line to `0.14.0` with minimum spec `3.14.0`.
Update the TypeScript package lock mechanically with `npm install --package-lock-only`.

- [ ] **Step 4: Update compatibility, changelogs, and current-facing counts**

Add the 3.14.x compatibility row, retain historical 3.13.x, keep 342 library /
347 total everywhere, and add bracketed changelog entries. State in non-TS
changelogs that their runtime surfaces are unchanged.

- [ ] **Step 5: Verify release metadata**

```bash
python3 tools/check-version-consistency.py
uv --project langs/python run python tools/check-conformance-coverage.py \
  --require csharp --require python --require typescript --require swift --require rust
```

Expected: versions are consistent and every flavor remains 342/342.

- [ ] **Step 6: Commit spec and release metadata**

```bash
git add spec compatibility-matrix.md README.md langs
git commit -m "spec: define TypeScript message predicates for #88"
```

______________________________________________________________________

### Task 4: Update canonical and in-repo documentation

**Files:**

- Modify: `docs/content/primitives/services-messages-dispatching.md`
- Modify: `docs/content/flavors/typescript.md`
- Modify: `langs/typescript/README.md`
- Modify other canonical installation/index pages only where their current version text is generated from the release line.

**Interfaces:**

- Consumes: the public names from Task 2 and the distinction from ADR-0094.

- Produces: one canonical raw-stream recipe rendered to repo/site/wiki.

- [ ] **Step 1: Add the raw pipeline recipe**

Show both:

```typescript
hub.messages.pipe(filter(isPropertyChanged))
hub.messages.pipe(
  filter((message) => isPropertyChanged(message, vm, "model")),
)
```

Explain that `whenPropertyChanged` is shorter when the hub/sender/property are
already known, while predicates classify mixed raw streams and arrays.

- [ ] **Step 2: Update TypeScript flavor and package docs**

List all three signatures, collection generic usage, optional constraints, and
the no-cross-flavor-parity rationale. Do not show consumer casts.

- [ ] **Step 3: Run the three-surface docs gate**

```bash
uv run --project langs/python --with-requirements docs/requirements.txt python -m scripts.docs.check_docs
uv run --project langs/python --with-requirements docs/requirements.txt python -m scripts.docs.validate_diagrams
uv run --project langs/python --with-requirements docs/requirements.txt mkdocs build --strict
```

Expected: canonical/site/wiki generation, drift checks, diagrams, and strict
MkDocs build pass. Verify generated site/wiki text contains the three names.

- [ ] **Step 4: Commit documentation**

```bash
git add docs langs/typescript/README.md
git commit -m "docs: explain raw TypeScript message narrowing #88"
```

______________________________________________________________________

### Task 5: Validate the evolved DayDreams consumer surface without pushing

**Files:**

- Disposable clone only: the ten files containing local predicate definitions.
- Do not modify: `/Users/kaveh/repos/daydreams`.

**Interfaces:**

- Consumes: locally built `@thekaveh/vmx` 3.14.0.

- Produces: evidence that all nine property guards and one collection guard are deletable with unchanged consumer behavior.

- [ ] **Step 1: Record the real checkout state and create a disposable clone**

Record the real DayDreams HEAD/status. Clone into
`/Users/kaveh/repos/VMx-worktrees/pilots/daydreams-issue-88`, initialize the VMx
submodule, and point only the disposable submodule/package at this branch.

- [ ] **Step 2: Prove a consumer red state**

Replace one local import/guard with the intended package export before rebuilding
VMx. Run the focused typecheck and confirm the package reports the missing export.

- [ ] **Step 3: Build VMx and replace all ten guards**

Build/package the local TypeScript flavor, refresh DayDreams dependencies, import
the public predicates, remove the local definitions, and preserve call-site
constraints. Prefer the new sender/property/action arguments where they shorten
existing condition chains.

- [ ] **Step 4: Run consumer verification**

Run the viewmodel package typecheck/tests, full workspace tests, and relevant web
and bakeoff production builds. Classify any failure by reproducing it against the
unchanged consumer baseline or by showing it is unrelated to the predicate diff.

- [ ] **Step 5: Record and remove the pilot**

Create one local-only pilot commit for inspectable evidence, record its SHA and
test totals, never push it, remove the disposable clone, and prove the real
DayDreams HEAD/status did not change because of this work.

______________________________________________________________________

### Task 6: Complete repository verification and review

**Files:**

- Review all files in `origin/develop...HEAD`.

**Interfaces:**

- Consumes: all previous tasks.

- Produces: a clean, reviewed branch ready for the develop PR.

- [ ] **Step 1: Run full TypeScript and package gates**

```bash
cd langs/typescript
npm ci
npm run sync-fixtures
npm run typecheck
npm run typecheck:tests
npm run lint
npm run build
npm test
npm audit --audit-level=low
```

- [ ] **Step 2: Run repository/tool/example gates**

Run tool lint/format/tests, version consistency, fixture sync, 342/342 coverage,
all four example-contract scripts, TypeScript console/showcase installs,
typechecks, tests, audit, and Pure-VM ESLint checks.

- [ ] **Step 3: Run all pre-commit hooks and inspect scope**

```bash
pre-commit run --all-files
git diff --check origin/develop...HEAD
git status --short
```

Confirm no other-flavor predicate API, RxJS import in production predicates,
message delivery change, generated site/wiki artifact, or secret entered the
diff.

- [ ] **Step 4: Request independent read-only review**

Review the exact base/head range against this plan. Resolve every Critical or
Important finding and rerun affected gates before publication.

______________________________________________________________________

### Task 7: Publish through develop and main

**Files:**

- GitHub PR/issue/project state only.

**Interfaces:**

- Consumes: the verified feature branch.

- Produces: merged develop/main history, live docs/wiki, and completed #88 card.

- [ ] **Step 1: Push and open a ready PR to `develop`**

Include issue scope, API signatures, version/count evidence, tests, pilot result,
known baseline limitations, and `Relates #88`.

- [ ] **Step 2: Wait for feature CI and merge**

Inspect every check and review thread. Fix failures, rerun until green, then
squash-merge and delete the remote feature branch. Keep #88 open.

- [ ] **Step 3: Open `develop` to `main` promotion PR**

Use `Closes #88`, wait for the second full CI matrix, verify no unresolved
threads, and merge with a merge commit while preserving `develop`.

- [ ] **Step 4: Verify publication and close execution state**

Wait for post-main language, docs, wiki, conformance, and release workflows.
Verify the live site/wiki contain all three predicates; comment final evidence,
set the card Done/Completed, clear priority/work order, and remove the owned
worktree/local branch only after its tree matches released `origin/develop`.
