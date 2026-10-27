# 11. Contributing & Releases

This page is the site's contributor and release guide. It covers the
contribution flow, local checks, coverage and performance review, and the
release procedure for every flavor.

## 11.1. Start With

- Contributing guide:
  [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Spec index:
  [spec/README.md](../../spec/README.md)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## 11.2. Contribution Flow

- Open an issue for non-trivial work.
- Branch from `develop`, open the feature PR to `develop`, and run the relevant
  flavor checks locally.
- Promote `develop` to protected `main` only through a separate maintainer PR.
- Direct pushes to `develop` and `main` are blocked. Both PR stages require the
  always-present conformance, C#, Python, TypeScript, Swift, Rust, docs,
  examples, security, and spec-discipline aggregate checks against the latest
  target branch. Maintainer review is expected when another reviewer is
  available; the single-collaborator repository does not require self-approval.
- For behavior changes, start in `spec/` and follow the ADR discipline.
- Keep all supported flavors visible when a change affects shared behavior.

## 11.3. Validation Entry Points

The main local check families are:

- C#: restore, build, test, and `dotnet format`
- Python: `uv run pytest`, `ruff`, and `mypy --strict`
- TypeScript: `npm ci`, fixture sync, typecheck, lint, build, and test.
  Vitest global setup runs `npm run build`, including fixture and schema
  synchronization, before test workers start. This also applies to watch
  reruns, direct `npx vitest`, and coverage runs. Generated writes do not
  trigger reruns. Rerun manually after changing spec inputs outside Vitest's
  import graph. Do not run a separate build of the package while tests run.
- Swift: `swift build` and `swift test`
- Rust: `cargo fmt --check`,
  `cargo clippy --locked --all-targets --all-features -- -D warnings`, and
  `cargo test --locked --all-features`
- Repo-wide coverage and example-contract tools

The repository's `CONTRIBUTING.md` lists the full commands for each flavor.

For reproducible Python checks, set `UV_PYTHON` to a supported version
(3.10–3.14) before locked sync and every later uv command. Installing Python
alone does not select it for an existing compatible environment. The Ubuntu
3.10 CI cell first seeds a 3.14 environment and checks that a selected sync
repairs it.

### 11.3.1. Reproduce Controlled Interleavings

A controlled interleaving acknowledges the exact runtime boundary that creates
the tested ordering. A worker-start signal proves only that a worker began.
Elapsed time proves only that a deadline passed. Neither proves that VMx
entered a specific wait. The selected lifecycle and notification regressions
acknowledge the exact per-instance wait and inspect the protected state while
it is active.

The Swift command regression cancels from the synchronous executing
notification. This happens inside the admission window, before the body task
installs its cancellation handle.

The test owns every participant and error channel. It releases gates in
cleanup, joins workers, awaits task results, and reports callback failures to
the coordinator. The test fails on premature completion, missing terminal
delivery, a swallowed worker or subscriber error, or cleanup that leaves work
running. A diagnostic timeout fails the test; it never proves that an operation
was correctly blocked.

Negative controls mutate the production boundary that the test exercises. They
run in a subprocess group with a watchdog and restore the original source bytes
in `finally`. A valid control reaches the selected assertion or ends as a
demonstrated deadlock mutant. A compilation failure, zero matched tests, an
unrelated assertion, a crash, or watchdog expiry is not proof. The Swift lane
records five normal passes, five failures without admission-cancellation
forwarding, and a rebuilt restored pass.

Order test infrastructure like runtime participants. A build that rewrites
imported fixtures or schemas must finish before workers read them; TypeScript
enforces this with global setup and an awaited rerun hook. A filesystem error
alone does not identify the process that holds a lock. Trace the actual writer
and reader before you assign a cause.

Each technique answers a different question:

- Controlled thread interleavings force and acknowledge a particular runtime
  boundary.
- Stress tests sample many schedules and remain supplementary evidence.
- Event-loop drains let queued continuations run, but do not prove that a
  foreign thread reached a boundary.
- Virtual schedulers advance modeled time deterministically, but do not
  establish native-thread scheduling behavior.

The controls establish the named paths, not exhaustive freedom from races.
Linux CPU affinity does not represent macOS scheduling. An external watchdog
contains a stuck process but does not prove in-process cleanup.

Run the selected regressions from the repository root with the same locked
inputs used by CI:

```bash
dotnet test langs/csharp/tests/VMx.Tests/VMx.Tests.csproj -c Release \
  --filter 'FullyQualifiedName~Foreign_Dispose_Waits' \
  -- RunConfiguration.TreatNoTestsAsError=true
UV_PYTHON=3.12 uv --directory langs/python run python \
  ../../tools/check-python-interpreter.py --venv .venv -- \
  -m pytest tests/unit/components/test_lifecycle_race.py \
  -k foreign_dispose_waits
cargo test --locked --all-features --manifest-path langs/rust/Cargo.toml
swift test --package-path langs/swift \
  --filter AsyncRelayCommandTests.testCmd012ImmediateCancelDuringAdmissionIsNeverLost
```

The Python command assumes the locked environment has already been synchronized
with `UV_PYTHON=3.12 uv --directory langs/python sync --locked --all-extras`.
CI additionally repeats the Linux commands three times normally and three times
under `taskset` on a CPU returned by `os.sched_getaffinity(0)`. Do not substitute
CPU 0: hosted runners may exclude it. The Swift mutation experiment belongs in
the macOS workflow because it requires supported Xcode XCTest; local machines
without an accepted Xcode license cannot supply that evidence.

The
[Concurrency Test Audit](../maintenance/2026-09-24-controlled-interleavings-audit.md)
records exact test locations, the maintained scope, follow-up dispositions, and
limitations.

### 11.3.2. Checked Documentation Snippets

A fence in `docs/content` or a package README can be tied to code that CI runs.
Put the code in a test or example, mark it, and put a marker comment directly
above the fence:

```text
<!-- checked-snippet: path/to/source.ts -->              whole file
<!-- checked-snippet: path/to/source.ts#region-name -->  one region
```

A region is every line between `docs-snippet:start region-name` and
`docs-snippet:end region-name` comments in the source, dedented. A source may
split one region into several start/end pairs, for example around a namespace
line the page leaves out; the parts are joined in order. `make docs-check`
fails when a fence differs from its source, including in the generated site
and wiki pages.

### 11.3.3. Coverage Floors

Every flavor gates CI on a coverage floor over its library sources:

| Flavor     | Gate                                                              | Metrics                                |
| ---------- | ----------------------------------------------------------------- | -------------------------------------- |
| C#         | `tools/check-cobertura-threshold.py` in `csharp.yml`              | line, branch                           |
| Python     | `fail_under` in `langs/python/pyproject.toml`                     | combined line and branch               |
| TypeScript | `coverage.thresholds` in `langs/typescript/vitest.config.ts`      | statements, branches, functions, lines |
| Rust       | `tools/check-coverage-floor.py` with `tools/coverage-floors.json` | lines, regions, functions              |
| Swift      | `tools/check-coverage-floor.py` with `tools/coverage-floors.json` | lines, regions, functions              |

For Rust and Swift, the `coverage floor` job runs in `rust.yml` or
`swift.yml`. It fails when line, region, or function coverage falls below the
flavor's floors in `tools/coverage-floors.json`. Rust measures with
`cargo-llvm-cov` on a pinned toolchain:

```bash
cargo install cargo-llvm-cov --version 0.9.1 --locked
cargo llvm-cov --locked --all-features --manifest-path langs/rust/Cargo.toml \
  --json --output-path rust-coverage.json
python3 tools/check-coverage-floor.py --flavor rust --report rust-coverage.json
```

Swift runs the library tests once with coverage on `macos-15` and the default
Xcode:

```bash
swift test --package-path langs/swift --enable-code-coverage \
  -Xswiftc -Xllvm -Xswiftc -instrprof-atomic-counter-update-all
python3 tools/check-coverage-floor.py --flavor swift \
  --report "$(swift test --package-path langs/swift --show-codecov-path)"
```

The denominator is library sources only: `langs/rust/src/` and
`langs/swift/Sources/VMx/`. Tests, examples, bundled resources, and build
output are not counted. A change that touches only generated or resource files
therefore cannot fail the gate. Removing a test that exercised library code
lowers the figure and can fail it.

A failure names each source file that gained uncovered lines since the
recorded baseline, with the unexecuted line ranges that `llvm-cov show` marks.
Each job uploads the llvm-cov export and a provenance file with the commit,
toolchain, and measured figures. Instrumented code stays in the coverage job:
`cargo-llvm-cov` uses its own target directory, and Swift instruments only that
job's debug build. No release build, package, or published crate contains it.

Two flavor details affect the figures:

- Rust counts come from llvm-cov summaries, which count a line once for each
  function that spans it. A closure's lines count twice, so a file's ranges can
  hold fewer lines than its count.
- The Swift build updates counters atomically. Coverage counts the code after a
  `guard` as the function's entries minus its early returns. Plain counter
  updates can lose entries when many threads call one function, as DISP-003
  does with `NotificationHub.dispose()`. A region that ran could then read as
  unexecuted and fail the floor without a code change (#513).

Each Rust and Swift floor is the lowest figure measured across repeated runs of
the baseline commit, truncated to two decimals. Only run-to-run variation in
scheduling-dependent paths is tolerated.

The floors file records the commit, toolchain, every measured run, and each
source file's uncovered lines. `tools/compare-coverage-runs.py` compares the
llvm-cov exports of repeated runs. It names every line that some runs execute
and others do not. Cover such a line with a deterministic test rather than
lowering a floor.

Raise a floor when coverage improves. Never lower one to make a change pass. If
deleting code legitimately lowers coverage, explain it in the pull request and
record the new baseline. Percentages are not comparable across flavors, because
each tool counts differently.

Coverage shows which lines ran, not whether a test would catch a wrong result.
It does not replace the conformance assertions.

### 11.3.4. Review Performance Changes

A change that touches a hot path, such as hub delivery, batching, property
publication, collections, or lifecycle, should include a benchmark comparison.
Run the flavor's harness on the change and compare it with the committed
baseline, or with a baseline you record from the base branch on the same
machine. [Baselines](performance-methodology.md#137-baselines) gives the
commands.

Explain every case the tool marks `SLOWER` and every probe that is not bounded
in the pull request. The comparison is a review signal, not a CI gate. The
method, cases, report format, and thresholds are in
[Performance Methodology](performance-methodology.md).

### 11.3.5. Rust Ownership-Test Conventions

The caller controls each stored VM's construct, destruct, and dispose
operations. A Rust serviced collection retains a member item as an ordinary
value; that retention does not transfer lifecycle ownership. A returned old
value, lookup result, or snapshot can keep a shared item alive after removal.
Cloning the collection shares its backing store without cloning items. Rust's
collection-change history has no item payload to retain.

`COL-055` and `COL-062` wrap real `ComponentVm` instances in test-private
shared wrappers. After each operation, including failed keyed preflight and
empty operations, they count every known wrapper handle. They also check
lifecycle hooks and parent state. After returned and snapshot handles are
released, the caller disposes each VM exactly once and releases its last
wrapper. The test then checks weak-reference expiration and a separate native
release counter.

Rust `Drop` is not VM disposal. The exact counts are deterministic because the
tests control every holder and run mutations synchronously. They do not count
the VM's internal references.

A retained caller `Arc` always has at least one strong reference. A check of
`strong_count >= 1` therefore cannot prove that a collection released its item
handles. A temporary mutation that leaks items inside both `clear`
implementations fails both tests; the unmodified implementations pass. These
tests strengthen `COL-055` and `COL-062` and add no catalog IDs.

The C#, Python, TypeScript, and Swift counterparts use direct lifecycle
observables, with different probe coverage. C# observes disposal. Swift omits
some lifecycle categories. Python's keyed test does not retain failed-operation
candidates, and TypeScript's keyed test instruments one item. None asserts
exactly-once caller cleanup. These are limits of the test evidence, not proof of
a collection defect.

## 11.4. Spec Discipline

Two repo rules matter most:

- semantic changes under `spec/` require a matching ADR unless the change is in
  an exempt path
- new conformance IDs require matching stubs in every catalog-complete flavor

Those rules are enforced in CI and described in the contributing guide and
repository automation.

## 11.5. Release Shape

Flavor packages version independently and release from verified `main` commits
through `<lang>-vX.Y.Z` operational tags. C# uses that form for core and
package-specific `csharp-notifications-vX.Y.Z` and
`csharp-dependency-injection-vX.Y.Z` tags for its companions, so independent
versions cannot collide. The spec uses `spec-vX.Y.Z`; Swift also pairs its
operational tag with the semantic `vX.Y.Z` tag required by SwiftPM.
Registry-backed channels are protected by environment approval, OIDC,
pre-publish checks of the exact locally built artifact, public-artifact checks,
and fresh-consumer verification. The Python channel pins its isolated PEP 517
backend and installs/smokes the wheel from `dist/` before the irreversible PyPI
action, then repeats the consumer check from the public registry.

Live channels: PyPI for Python, npm for the TypeScript core and the React
adapter (`typescript-v*` and `react-v*` tags, npm trusted publishing), and
repository tags for Swift through SwiftPM. The NuGet (C#) and crates.io (Rust)
channels are prepared but unpublished.

Each registry channel's protected environment restricts deployments to its tag
pattern, requires a maintainer reviewer, and disables administrator bypass.
Self-review stays allowed while one maintainer holds the reviewer role.
Publication uses a trusted publisher bound to `release.yml` and that
environment, not a long-lived token.

### 11.5.1. Release Checklist

Use this sequence for every flavor:

1. Start from a clean, freshly fetched `origin/main`; never release from
   `develop` or an unmerged feature branch.
1. Confirm the source/package version and minimum-spec declaration agree, and
   prove both the intended operational tag and public registry version are
   unused.
1. Run the flavor's complete release gate and build the exact package locally.
   Inspect that artifact, install it into a clean consumer, and retain the check
   evidence before creating a tag.
1. Create the immutable annotated `<lang>-vX.Y.Z` tag
   (`git tag -a "<tag>" -m "<package> <version>" origin/main`) on the verified
   `main` commit. For Swift, create the paired semantic `vX.Y.Z` tag on the same
   commit. For C# companion packages, use their package-specific tag prefixes.
   Python release-please tags are lightweight; the workflow accepts both.
1. Monitor the matching release workflow, approve its protected environment
   only after the pre-publish jobs identify the expected artifact, and do not
   bypass a failed gate.
1. Verify the exact version on the public registry and install it into a second
   fresh consumer. Confirm the GitHub release points to the tagged commit and
   contains the expected artifacts and notes.
1. Only after public verification, update the repository docs and regenerate
   this site and the wiki through `develop` and `main` PRs.
1. If source, build, package-publication, or package behavior fails after tag
   creation, keep the tag immutable. Correct the source or workflow on `main`,
   bump the affected package to a new patch version, and publish through a new
   tag. For the React adapter only, a missing GitHub Release after successful
   registry, provenance, and fresh-consumer gates is metadata-only recovery;
   follow the [React-specific recovery runbook](#1153-recover-react-release-metadata).

### 11.5.2. Validate Python Release Tests

Run `gh workflow run release.yml --ref develop` to validate only the
five-version Ubuntu Python test matrix. Dispatch has no publication inputs.
All other release jobs require a tag push, including when dispatch targets an
existing release tag. This does not exercise the protected build/publish job;
normal Python CI separately checks wheel and extracted-sdist packaging. Real
tag pushes retain their main-ancestry and publication gates.

Rerun a successful revision to collect warm-cache evidence. The 3.10 cell must
report `cache-hit=true`, list both managed versions, and log the seeded 3.14
and selected 3.10 identities. A setup-uv package-cache hit is neither a restored
virtualenv nor necessarily a cached Python installation. Record the run URL
and revision.

### 11.5.3. Recover React Release Metadata

Use this procedure only when the exact npm version, provenance, and both fresh
React consumers have passed. A broken published package requires a new patch;
a missing GitHub Release alone is a metadata-only recovery.

Before recovery, read the old run's evidence and independently confirm the
immutable remote tag SHA, its ancestry from `main`, the package version at that
tag, the exact public npm version, its provenance, and the successful fresh
React 18 and React 19 consumer checks. These checks establish publication
facts; the extraction commands below do not. npm forbids reusing a published
package name and version, even after unpublishing; see the
[npm publish documentation](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
Do not republish, move or recreate the tag, or reuse a version. Do not rerun
the historical workflow: a GitHub Actions rerun retains the original SHA and
ref, so it also retains the old extraction code. See GitHub's
[rerun documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
and [workflow documentation](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows).

From a current, verified `main` checkout that contains the fixed helper, use
the changelog bytes from the original immutable tag. Substitute the actual
already-published version; never run this procedure for a package that has not
passed the checks above.

```bash
set -euo pipefail
version=0.1.0 # Replace with the version whose npm upload already succeeded.
tag="react-v${version}"
git fetch --no-tags origin "refs/tags/${tag}:refs/tags/${tag}"
tag_sha="$(git rev-parse "${tag}^{commit}")"
remote_tag_ref="$(git ls-remote --exit-code origin "refs/tags/${tag}" | awk '{print $1}')"
test "$remote_tag_ref" = "$(git rev-parse "$tag")"
git fetch --no-tags origin main:refs/remotes/origin/main
git merge-base --is-ancestor "$tag_sha" origin/main
notes="$(mktemp)"
git show "${tag_sha}:packages/react/CHANGELOG.md" |
  awk -v v="$version" -f tools/extract-release-notes.awk > "$notes"
test -s "$notes" && grep -q '[^[:space:]]' "$notes" || {
  echo "No adapter release notes." >&2
  exit 1
}
cat "$notes"
```

The fetch and `ls-remote` equality confirm the remote tag ref, and
`^{commit}` peels an annotated tag to its original commit. Any failed fetch or
remote query stops this script; do not infer a confirmed tag from a failure.
Inspect the rendered notes before continuing. Check whether a GitHub Release
already exists, and distinguish confirmed absence from an authentication or
network failure. If absent, create only release metadata:

```bash
gh release create "$tag" --verify-tag --target "$tag_sha" \
  --title "React adapter v${version} (npm)" --notes-file "$notes"
```

If it exists, verify its tag and update only its title and notes:

```bash
gh release edit "$tag" --title "React adapter v${version} (npm)" --notes-file "$notes"
```

Verify the release URL, tag SHA, and notes; retain the recovery evidence and
remove the temporary notes file. This changes GitHub Release metadata only.
