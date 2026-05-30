# Plan — testing mobile-forge recipes on CI mobile runners

Status: **DRAFT for user review.** Nothing has been committed to `test-recipes-on-mobile` yet beyond branching off `improve-ci` (HEAD `7c5331c`). This document is gitignored (lives under `playground/`).

---

## TL;DR

Adopt the **Toga/Briefcase architectural pattern** — fail-fast=false matrix of per-recipe × per-backend jobs with conditional log/data artifact upload on failure — **and the print-to-stdout sentinel transplants almost directly**: Flet redirects Python stdout/stderr/logging into a file at `$FLET_APP_CONSOLE` (= `<app temp>/console.log`, unbuffered). Host reads/tails that file instead of `adb logcat` / `xcrun simctl log stream` — verified in `playground/stdout-probe/FINDINGS.md`. Integrate as **two new steps in the existing `build-wheels.yml`** rather than a separate workflow, so the wheel-just-built is tested on the same runner before publish.

Start narrow: **Android x86_64 on `ubuntu-latest` + KVM, one wheel per recipe, only when `recipes/<name>/**` changes**. iOS comes second, after the macos-15 ⇄ macos-26 image situation is verified stable for iOS simulator in 2026.

> **Plan revision history**
> - **v1** (initial draft): assumed Python stdout was dropped by serious_python; designed a file-marker (`result.json` + `done.flag`) ferry channel; proposed per-recipe `test/main.py` Flet apps as the test-code structure.
> - **v2**: user pointed at `flet/sdk/python/templates/build/.../lib/main.dart:195` (`FLET_APP_CONSOLE`). Verified Flet redirects stdout into `<app temp>/console.log` in production builds; the probe's `print()` lines were captured all along, just to a file we didn't know about. Switched ferry channel to the simpler print-sentinel + console.log pull pattern (matches Toga's shape directly).
> - **v3**: user proposed (and survey confirmed) that 20+ recipes already ship `test_<name>.py` files in pytest format — adopt this existing convention instead of inventing per-recipe Flet apps. Generic in-app runner invokes `pytest.main()` on the bundled test file, matches Toga's testbed.py line-for-line. Both `recipes/<name>/test_<name>.py` (no assets) and `recipes/<name>/test/test_<name>.py` (with assets — pillow's pattern) are supported.
> - **v4 — this version**: all open questions resolved (§5 below). Key decisions: no nightlies in scope yet (deferred — decision later); smoke set of 5 representative recipes auto-runs when `tests/recipe-tester/main.py` changes; iOS lane explicitly pins `macos-26` (Tahoe, the image CPython migrated to in March 2026 to escape the macos-15 1-in-11 hang); pytest gets defensive flags from day 1; system-log dump on failure; no test-file backfill in this PR. Phases 4 (nightly full matrix) and 5 (wheel-rebuild loop) marked deferred since they depend on the nightly cron.

---

## 1. What we learned that changes the plan

### 1a. The deep-research verdict (already in chat)

Toga/Briefcase pattern is the de-facto industry standard (cibuildwheel, CPython PEP 730/738 testbed all use it). Adopt the *shape*: fail-fast=false, per-backend matrix, single in-app test entry point that signals completion + artifact-upload-on-failure. **Don't adopt Toga's testbed.py** — it's hard-coupled to Toga widgets and Briefcase. We rebuild the in-app harness around `serious_python` + our existing `recipe-tester` app.

### 1b. The stdout probe verdict (verified locally — v2 revision)

Toga's sentinel — `>>>>>>>>>> EXIT N <<<<<<<<<<` to Python `print()`, host
matches by regex — **works**, with one twist: the print output goes to a
*file*, not to a syslog. Flet's Dart launcher (main.dart line 192-195) sets
`FLET_APP_CONSOLE=<temp>/console.log` and redirects Python stdout/stderr to
that file at app start in production builds. Unbuffered.

| Channel | Android | iOS sim |
|---|---|---|
| Python `print()` → `$FLET_APP_CONSOLE`/console.log | ✅ verified | ✅ verified (STDPROBE lines found in `<app data>/Library/Caches/console.log`) |
| Same via `sys.stderr` / `logging` module | ✅ per Flet docs | ✅ per Flet docs |
| `__android_log_write` via ctypes/liblog.so | ✅ shows in `adb logcat` | N/A |
| App-written file marker (fallback) | ✅ written | ✅ host-readable |

Full evidence: `playground/stdout-probe/FINDINGS.md`.

**Implication for the plan:** the app's CI mode prints `>>>>>>>>>> EXIT N <<<<<<<<<<`
(plus any per-step pretty output it wants); the host pulls/tails `console.log`
and grep-extracts the exit code. Same one-line code on both platforms; the
only platform difference is the path to fetch `console.log`. The file-marker
approach is retained as a fallback for richer structured data (e.g. JSON
per-step results) but not required for the basic gate.

**Console.log paths the host uses:**
- iOS sim: `$(xcrun simctl get_app_container booted <bundle> data)/Library/Caches/console.log` — direct host fs read, no copy
- Android: `/data/data/<pkg>/cache/console.log` — `adb root && adb pull` (works on userdebug AVDs that CI uses; doesn't work on the user-build Pixel emulator I tested locally, but that's not the CI env)

### 1c. The existing CI we're building on

`improve-ci` already gives us a lot of scaffolding to reuse:

- `tj-actions/changed-files@v45` with `files: recipes/**` `dir_names_max_depth: 2` — turns a PR diff into the list of changed recipes. **We get the path-filter behavior for free.**
- The `setup` job emits a JSON matrix `{include: [{arch, package, runner, …}, …]}`. **We extend the matrix entries with the test fields rather than building a new workflow.**
- Existing `runner: ubuntu-latest` for Android, `macos-latest` for iOS. Same machines we need for emulator/sim.
- Upload-on-success and upload-on-failure artifact patterns already exist for logs/errors — copy the shape for test result artifacts.

So the testing layer is **two new steps** appended to the `build` job (after wheel build, before publish). No new workflow file needed; we keep one source of truth per-recipe-per-arch.

---

## 2. Architecture

### 2a. Per-job shape (extending the existing `build` job in `build-wheels.yml`)

Existing steps:
1. Checkout
2. Setup uv + Rust
3. Build wheels (`forge $arch $pkg`)
4. Publish wheels (conditional)
5. Upload logs / upload errors

New steps (inserted between 3 and 4):

**3.5 — Stage the recipe's test file(s) and build the recipe-tester app.**
The recipe-tester is a single generic Flet app at `tests/recipe-tester/`
(committed, lives outside `playground/` since CI needs it). It invokes pytest
on whatever's bundled at `recipe_tests/` (§2c). Per-recipe steps:

- Stage tests: `cp recipes/<name>/test_*.py tests/recipe-tester/recipe_tests/`
  (or `cp -r recipes/<name>/test/.` if the recipe has assets — §2d).
- Substitute the recipe name into `tests/recipe-tester/pyproject.toml`'s
  `[project].dependencies` (`<RECIPE>` placeholder → `<name>==<version>`).
- `PIP_FIND_LINKS=$(pwd)/dist uv run --no-sync flet build apk --arch x86_64`
  (Android lane) or `… flet build ios-simulator` (iOS lane).

**3.6 — Boot emulator/sim, install, launch, wait for EXIT sentinel.**

Android (Ubuntu, x86_64 AVD with KVM):
```yaml
- uses: reactivecircus/android-emulator-runner@v2
  with:
    api-level: 24
    arch: x86_64
    target: default
    script: |
      adb install -r tests/recipe-tester/build/apk/recipe-tester.apk
      adb shell monkey -p com.flet.recipe_tester -c android.intent.category.LAUNCHER 1
      .ci/wait_for_console.sh android
```

iOS (macos-26 — see §5 Q5; not `macos-latest`):
```yaml
- name: Test on iOS Simulator
  shell: bash
  run: |
    xcrun simctl boot "iPhone 15" 2>/dev/null || true
    xcrun simctl install booted tests/recipe-tester/build/ios-simulator/recipe-tester.app
    xcrun simctl launch booted com.flet.recipe-tester
    .ci/wait_for_console.sh ios
```

**3.7 — On failure, upload console.log + system-log + screenshot.**

```yaml
- name: Capture system log on failure (Android)
  if: failure() && matrix.platform == 'android'
  run: adb logcat -d > logcat-on-failure.txt || true

- name: Capture system log on failure (iOS)
  if: failure() && matrix.platform == 'ios'
  run: xcrun simctl spawn booted log show --last 10m > syslog-on-failure.txt || true

- name: Capture screenshot on failure
  if: failure()
  run: |
    case "${{ matrix.platform }}" in
      android) adb exec-out screencap -p > screen-on-failure.png || true ;;
      ios)     xcrun simctl io booted screenshot screen-on-failure.png || true ;;
    esac

- name: Upload test artifacts
  if: always() && hashFiles('console.log', '*-on-failure.*') != ''
  uses: actions/upload-artifact@v4
  with:
    name: test-${{ matrix.artifact_name }}-${{ github.run_id }}-${{ github.run_attempt }}
    path: |
      console.log
      *-on-failure.*
    retention-days: 90       # per §5 Q4
```

### 2b. The wait_for_console.sh helper

Single shell helper, one path per platform, polling Flet's `console.log`:

```bash
#!/usr/bin/env bash
# .ci/wait_for_console.sh — poll the recipe-tester's console.log for the
# Toga-style EXIT sentinel, emit a GH Actions check based on the exit code.
set -euo pipefail
PLATFORM="$1"
ANDROID_PKG="com.flet.recipe_tester"   # Android: underscores
IOS_BUNDLE="com.flet.recipe-tester"    # iOS: hyphens
TIMEOUT="${TIMEOUT:-600}"               # 10 minutes
INTERVAL=2

# Resolve the platform-specific console.log path
case "$PLATFORM" in
  android)
    adb root >/dev/null  # userdebug AVD allows this
    sleep 1
    REMOTE="/data/data/$ANDROID_PKG/cache/console.log"
    fetch() { adb pull "$REMOTE" console.log >/dev/null 2>&1 || true; }
    ;;
  ios)
    DATA=$(xcrun simctl get_app_container booted "$IOS_BUNDLE" data)
    LOCAL="$DATA/Library/Caches/console.log"
    fetch() { [ -f "$LOCAL" ] && cp "$LOCAL" console.log; }
    ;;
esac

end=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$end" ]; do
  fetch
  if [ -f console.log ] && grep -q '>>>>>>>>>> EXIT' console.log; then
    break
  fi
  sleep $INTERVAL
done

[ -f console.log ] && grep -q '>>>>>>>>>> EXIT' console.log || \
  { echo "::error::Timed out waiting for EXIT sentinel"; cat console.log 2>/dev/null; exit 2; }

# Parse the sentinel: >>>>>>>>>> EXIT 0 passed=5 total=5 <<<<<<<<<<
SENTINEL=$(grep -oE '>>>>>>>>>> EXIT [0-9]+ passed=[0-9]+ total=[0-9]+ <<<<<<<<<<' console.log | tail -1)
EXIT_CODE=$(echo "$SENTINEL" | awk '{print $2}')
PASSED=$(echo "$SENTINEL"   | grep -oE 'passed=[0-9]+' | cut -d= -f2)
TOTAL=$(echo "$SENTINEL"    | grep -oE 'total=[0-9]+'  | cut -d= -f2)

{
  echo "## Recipe test — $PLATFORM"
  echo ""
  echo "**$PASSED/$TOTAL steps passed**"
  echo ""
  echo '```'
  tail -50 console.log
  echo '```'
} >> "$GITHUB_STEP_SUMMARY"

exit "$EXIT_CODE"
```

### 2c. The recipe-tester app (one file, one entry point — invokes pytest)

A single committed app at `tests/recipe-tester/main.py`. On startup it runs
pytest on the bundled test file, then prints a Toga-shaped EXIT sentinel to
stdout (which Flet redirects to `console.log` per §1b). This is *exactly*
Toga's `testbed/tests/testbed.py` pattern — `pytest.main()` in a background
thread, sentinel on completion. The GUI renders a live result list as a side
effect; CI ignores it, local dev reads it.

```python
# tests/recipe-tester/main.py
import os, sys, threading, time
import flet as ft

EXIT_CODE: int | None = None

def _run_pytest():
    """Run bundled recipe tests; stash the exit code; emit the EXIT sentinel."""
    global EXIT_CODE
    import pytest
    # Defensive flags — see §5 Q8 for rationale.
    EXIT_CODE = pytest.main([
        "-v",
        "--rootdir", "recipe_tests",   # don't walk the bundled stdlib zip
        "-p", "no:cacheprovider",       # don't try to write .pytest_cache/
        "--capture=no",                  # diagnostic prints reach console.log
        "--no-header",
        "--tb=short",
        "recipe_tests/",                 # bundled at build time (see §2d)
    ])
    # Toga-shaped sentinel — repeated 6x with sleeps to defeat any buffering
    # the unified log buffer or pytest's own teardown might do.
    for _ in range(6):
        print(f">>>>>>>>>> EXIT {EXIT_CODE} <<<<<<<<<<", flush=True)
        time.sleep(0.5)

def main(page: ft.Page) -> None:
    page.appbar = ft.AppBar(title=ft.Text("recipe-tester"))
    page.add(ft.Text("Running pytest on bundled recipe tests…", size=16))
    # Run pytest off the GUI thread so Flet's event loop keeps running and
    # serious_python flushes console.log writes promptly.
    threading.Thread(target=_run_pytest, daemon=True).start()

ft.run(main)
```

`tests/recipe-tester/pyproject.toml` declares the in-app deps. Pytest is pure
Python (~500KB with pluggy + iniconfig + packaging), so we add it as a
runtime dep — Flet bundles it into the app payload:

```toml
[project]
dependencies = [
    "flet",
    "pytest",
    "<RECIPE>",   # ←— substituted per-job by CI: see §2d
]
```

**Why a thread, not synchronous in `main()`:** Flet's event loop must keep
turning so the line-buffered `console.log` writes flush within ~1ms of each
`print()`. A sync pytest.main() blocks the loop until tests complete; the
sentinel might land in the buffer but not flush until the app finally yields.
Background thread = sentinel visible to the host while the GUI is still
"running."

**On crashes:** an uncaught exception inside a test surfaces as pytest's
`failed` status (EXIT non-zero) AND its traceback is captured to console.log
via `--tb=short`. If pytest itself dies (import error in test_x.py),
`_run_pytest` never sets `EXIT_CODE` and never prints the sentinel — host
times out. The artifact-upload-on-failure step (§2 step 3.7) still captures
console.log, surfacing the traceback for diagnosis.

### 2d. Per-recipe test code lives in `test_<name>.py` (existing convention)

**Survey of `recipes/` on `improve-ci`**: 20+ recipes already ship test files
in pytest format. Examples:

| Recipe | File | Shape |
|---|---|---|
| `numpy` | `recipes/numpy/test_numpy.py` | flat, no assets |
| `bcrypt` | `recipes/bcrypt/test_bcrypt.py` | flat |
| `lxml` | `recipes/lxml/test_lxml.py` | flat (uses `unittest.TestCase`) |
| `pandas` | `recipes/pandas/test_pandas.py` | flat |
| `pillow` | `recipes/pillow/test/test_pillow.py` + `Vera.ttf`, `mandrill.jpg` | directory with assets |

Format is pytest-discoverable plain `def test_*()` / `assert` (or
`unittest.TestCase` — pytest auto-collects both). **The tests don't import
flet** — they can also run on desktop with `pytest recipes/numpy/test_numpy.py`
for sanity-check during development.

**Plan: adopt this existing convention as-is.** Two file shapes are
supported, no new structure invented:

1. **Flat** (preferred when no assets): `recipes/<name>/test_<pyname>.py`
2. **Directory** (when assets are needed): `recipes/<name>/test/` containing
   `test_<pyname>.py` + asset files

`<pyname>` is the Python-import-safe form of `<name>` (e.g.,
`argon2-cffi-bindings` → `argon2_cffi`). We don't enforce a strict naming
rule; CI globs `test_*.py` so any pythonic name works.

**At CI build time**, the workflow stages the recipe's test file(s) under
`tests/recipe-tester/recipe_tests/`:

```bash
# In the CI step that builds the app:
RECIPE="$1"
mkdir -p tests/recipe-tester/recipe_tests
if [ -d "recipes/$RECIPE/test" ]; then
  cp -r "recipes/$RECIPE/test/." tests/recipe-tester/recipe_tests/
else
  cp recipes/"$RECIPE"/test_*.py tests/recipe-tester/recipe_tests/
fi
# Substitute the recipe name into pyproject.toml's [project.dependencies]
sed -i.bak "s/<RECIPE>/$RECIPE/" tests/recipe-tester/pyproject.toml
```

**Caveats surfaced by the survey** (these become tracking items, not blockers):

1. `recipes/bcrypt/test_bcrypt.py` has `def test_basic(self):` — leftover
   from a unittest→pytest refactor. Pytest will collection-error on the
   bogus `self` arg. First CI run surfaces it; we fix in the same PR.
2. Many tests use `print()` for diagnostics (numpy prints duration). The
   `--capture=no` flag in §2c routes those to `console.log` for inclusion
   in failure artifacts.
3. **Naming inconsistency**: `argon2-cffi-bindings/` → `test_argon2_cffi.py`
   (drops `-bindings`). The `cp test_*.py` glob handles this — no
   path-construction-from-recipe-name needed.
4. **Recipes we built together this session don't have `test_<name>.py` yet**:
   biopython, psycopg2, apsw, polars, pyzmq, pyzbar, ujson (some of these
   we wired into recipe-tester/main.py instead of writing a pytest file).
   Mechanical port: each session's `step_*()` functions become pytest
   `def test_*()` functions. ~30 min of work for all of them. Include
   alongside the workflow PR — every recipe touched on `test-recipes-on-mobile`
   should have a test file when the branch lands.
5. **Tests requiring extra runtime deps** (e.g. an HTTP fixture) — not common
   in current recipes. If/when needed, `recipes/<name>/test/requirements.txt`
   could be a future extension that CI installs into the app payload. Defer
   until a real case shows up.

**Bonus benefit of this structure:** the same `test_<name>.py` files are
runnable on desktop with plain `pytest`. A new recipe contributor can write
the test, run it locally against the PyPI wheel (for pure-Python recipes) or
against a manually-built crossenv wheel, and only then push for CI. No Flet
machinery needed for desktop iteration.

### 2e. ABI choice on each platform

| Platform | Local dev (you) | CI |
|---|---|---|
| Android emulator | arm64-v8a on macOS (HVF) | **x86_64 on Linux (KVM)** — 2-3× faster, ~10× cheaper than running arm64 AVD on macOS |
| iOS Simulator | arm64 on Apple Silicon Mac | arm64 on `macos-latest` (Apple Silicon since ~macos-14) |

The x86_64 Android test isn't a perfect substitute for arm64-v8a in production. **But it exercises the same C source, same Python C-API, same fix_wheel pipeline, same patches.** The Toga + cibuildwheel projects both rely on this exact heuristic. We accept it.

Optionally, add a **nightly cron** running arm64-v8a AVDs on `macos-latest` for the full matrix (every recipe × ABI) as the more-expensive belt-and-suspenders check.

---

## 3. Phased rollout

### Phase 0 — branch + plan (this PR)
- Branch `test-recipes-on-mobile` exists on fork, no commits yet
- This plan committed under `playground/` for review
- User reads + revises plan before any code lands

### Phase 1 — Android-only, x86_64 on Linux, gated on changed recipes
**Goal:** prove the print-sentinel ferry channel + the in-app pytest runner +
the emulator-runner integration on one platform with full PR signal.

What lands:
- `tests/recipe-tester/{main.py, pyproject.toml}` (the generic app from §2c)
- `.ci/wait_for_console.sh` (the helper from §2b)
- `build-wheels.yml`: extend matrix per (recipe × android-x86_64), add stage-tests
  + build-app + boot-emu + install + wait-for-console + upload-result steps;
  keep iOS arm of matrix building (not testing) for now
- A **starter recipe** with its `test_<name>.py` already present. Suggest
  `numpy` — it already has `recipes/numpy/test_numpy.py`, exercises BLAS and
  C-API heavily, and is itself a transitive dep for many other recipes, so
  proving it works gates a lot of downstream confidence.

Success metric: pushing a change under `recipes/numpy/` triggers a CI run that
builds the wheel AND runs numpy's two existing test functions on a Linux
x86_64 AVD, producing a green check with the pytest output in
`$GITHUB_STEP_SUMMARY`. Flake rate < 5% over 20 consecutive runs.

Wallclock budget: 11 min/job (per Toga's measured numbers — likely faster on
x86_64 + KVM, ~8 min realistic). One recipe × one ABI = one job.

### Phase 2 — backfill `test_<name>.py` for recipes that don't have one
**Goal:** every recipe in `recipes/` has a pytest-discoverable test file.

Most recipes already do (20+ on `improve-ci`). Backfill targets are:
- Recipes we built in our work sessions but never ported to pytest format:
  biopython, psycopg2, apsw, polars, pyzmq, pyzbar, ujson, pyxirr, tokenizers,
  selectolax, duckdb-style additions… (~10 recipes). Each session's `step_*()`
  functions become `def test_*()` in ~10 lines.
- Recipes shipping `meta.yaml` only with no test file. Audit:
  `comm -23 <(ls recipes/ | sort) <(ls recipes/*/test*.py recipes/*/test/test*.py 2>/dev/null | xargs -n1 dirname | sed 's#recipes/##' | sort -u)`.
- Fix the `bcrypt/test_bcrypt.py` `def test_basic(self):` bug surfaced by
  the §2d caveat.

Add a CI check that **rejects new recipes whose `recipes/<name>/test_*.py` is
missing** — keeps the test debt from accumulating after this PR.

### Phase 3 — iOS lane (non-blocking initially)
**Goal:** parallel iOS arm64 simulator test on `macos-26`, marked `continue-on-error: true` for ~2 weeks while we watch flake rate.

Adds:
- iOS branch of `wait_for_console.sh` (already drafted in §2b)
- `xcrun simctl boot`/install/launch glue
- **Explicit pin: `runs-on: macos-26`** — not `macos-latest`. macos-26 (Tahoe)
  is the image CPython migrated to in March 2026 to escape the macos-15
  1-in-11 simulator hang documented in actions/runner-images#12777. Before
  this phase lands, verify macos-26 is on the public-runner image inventory
  (check `actions/runner-images` README's currently-available images). If
  not yet available on free runners, fall back to `macos-14` (last-known-good),
  NOT `macos-15`.

Flip to blocking once 14-day flake rate stays under 5%.

### Phase 4 (deferred) — full 4-ABI Android + 3-slice iOS nightly
**Goal (future):** every wheel slice tested at least once a day.

**Decision deferred.** User explicitly out-of-scope for now; will revisit
after Phase 1-3 are operational. Sketched here so the architecture supports
it without rewrite: a separate `test-recipes-nightly.yml` workflow with
`on: schedule: cron: '0 4 * * *'` fanning out the full matrix (all 4 Android
ABIs × all recipes, all 3 iOS slices × all recipes). Per-PR keeps the cheap
1-ABI lane regardless of nightly state.

### Phase 5 (deferred) — Wheel rebuilding loop
**Goal (future):** when a recipe's test fails for an ABI that's already
published on pypi.flet.dev, open an issue (or auto-rebump build number +
publish). Depends on the nightly cron (Phase 4) to detect regressions, so
also deferred.

---

## 4. Cost / runner budget

`flet-dev/mobile-forge` is a **public OSS repo**, so all GH Actions runner
minutes are free for Linux, Windows, AND macOS. The 10× minute multiplier
that hits paid private repos doesn't apply. The only real budget constraints
are wallclock and concurrency (20 standard + 5 macOS concurrent jobs at a
time on free public-OSS terms).

| Phase | Per-PR wallclock | Concurrency notes |
|---|---|---|
| 1 (Android x86_64, recipe-touched only) | ~8 min × 1 job = 8 min | trivial; well under the 20-concurrent cap |
| 2 (same, with backfilled tests over time) | path filter still cuts this; typical PR touches 1-2 recipes → 8-16 min | trivial |
| 3 (+ iOS arm64 sim on macos-26) | +12 min × 1 job = 12 min on macOS | uses 1 of the 5 macOS-concurrent slots |
| Shared-runner change (`tests/recipe-tester/main.py`) — smoke set | 5 recipes × 8 min ÷ concurrency = ~40 min serialized, ~8 min if all 5 fit | well under cap |
| Manual `workflow_dispatch` full re-run | ~80 recipes × 8 min ÷ 20 concurrency ≈ 35 min | uses full standard-runner cap during run |
| 4 (deferred) — nightly full matrix | ~80 × 7 = 560 jobs nightly, ÷ concurrency ≈ 4-6 hours wallclock per night | macOS-concurrent cap (5) bottlenecks the iOS slices; would queue ~2h |

**Net for current scope (phases 1-3):** every per-PR run costs $0 and
finishes in <15 wallclock minutes. No budget concerns.

---

## 5. Open questions — all resolved (v4)

1. ~~Where do per-recipe test files live?~~ → `recipes/<name>/test_<pyname>.py`
   flat, or `recipes/<name>/test/test_<pyname>.py` with assets (pillow shape).
   Existing 20+ recipes' convention.

2. ~~Generic `tests/recipe-tester/` — committed or generated?~~ → Committed.
   Single `main.py` + `pyproject.toml` with a `<RECIPE>` placeholder that CI
   sed-substitutes per-job.

3. ~~When `tests/recipe-tester/main.py` changes, do we re-run every recipe?~~
   → **Smoke set on PR + manual full-rerun via workflow_dispatch.**
   - Auto-trigger on PR touching `tests/recipe-tester/main.py`: run a 5-recipe
     smoke set covering the main patterns —
     **numpy** (BLAS/C-API heavy), **pillow** (assets/imaging), **lxml**
     (libxml2 native linkage), **pandas** (numpy interop), **bcrypt** (simple
     cffi). ~40 min serialized wallclock; covers most regression classes.
   - Extend the existing `build-wheels.yml`'s `workflow_dispatch.inputs` with
     a `rerun_all_tests: bool` input for opt-in full sweeps when a contributor
     intentionally changes the shared runner.
   - **No nightly backstop in scope** — user explicitly deferred nightlies;
     the smoke set + manual rerun is the only coverage for now.

4. ~~Artifact retention?~~ → Per-PR: **90 days** (GH default; lets devs
   compare a PR's failure across re-pushes). Nightly artifacts (when nightly
   lands, currently deferred): 14 days. Volume is tiny either way (<10 MB/day
   at 5% failure rate).

5. ~~iOS image pinning?~~ → **Pin `runs-on: macos-26` explicitly** in the
   iOS lane. macos-26 (Tahoe) is the image CPython migrated to in March 2026
   to escape the macos-15 simulator hang (actions/runner-images#12777).
   `macos-latest` is a moving target that currently still resolves to
   macos-15. Action item before Phase 3: verify macos-26 is in
   actions/runner-images' currently-available list on free public-runner
   tier; if not yet, fall back to `macos-14` (last-known-good), explicitly
   NOT macos-15.

6. ~~Self-hosted Mac mini for iOS?~~ → No. User won't host. Public-OSS
   GH Actions tier gives free macOS minutes, so the Mac mini cost-savings
   argument doesn't apply anyway.

7. ~~Console.log when the app crashes before sentinel fires?~~ →
   **Add system-log dump to the upload-on-failure step.** Three crash
   sub-cases, all handled:
   - Python exception during pytest collection → traceback already in
     console.log via `--capture=no`; sentinel never emitted; host times out;
     artifact upload surfaces the traceback.
   - serious_python crash on app start (e.g. dlopen failure, ABI mismatch)
     → Python never runs; console.log may be empty. The fallback `adb logcat
     -d > logcat-on-failure.txt` (Android) and `xcrun simctl spawn booted
     log show --last 10m > syslog-on-failure.txt` (iOS) capture the Dart-side
     and native-loader errors.
   - Timeout without crash (hang) → wait_for_console.sh exits code 2; same
     artifact bundle uploads.

8. ~~pytest weirdness under serious_python?~~ → **Add defensive flags from
   day 1.** Don't wait to discover issues:
   ```
   pytest.main([
       "-v",
       "--rootdir", "recipe_tests",   # don't walk the bundled stdlib
       "-p", "no:cacheprovider",       # don't try to write .pytest_cache
       "--capture=no",                  # prints reach console.log
       "--no-header",
       "--tb=short",
       "recipe_tests/",
   ])
   ```

9. ~~Backfill missing `test_<name>.py` in this PR or follow-up?~~ → **Follow-up.**
   User explicit: focus on getting CI working first against existing-test
   recipes (numpy is the natural starter — already has `test_numpy.py`).
   Backfill lands in subsequent small PRs once the green lane is proven.

---

## 6. What the user reviews and approves before any code lands

This document. After your review (and any revisions you want to drop in), the agreed-upon plan turns into a sequence of small commits on `test-recipes-on-mobile`:

1. `tests/recipe-tester/{main.py, pyproject.toml}` — the generic in-app
   pytest runner from §2c; `<RECIPE>` placeholder in pyproject for CI to
   substitute
2. `.ci/wait_for_console.sh` — the helper from §2b
3. `.github/workflows/build-wheels.yml` extension — stage-tests, build-app,
   boot-AVD, install, wait-for-console, upload-result steps. Initially
   limited to the Android x86_64 lane per Phase 1
4. Backfill `test_<name>.py` for the recipes we built together this session
   that don't already have one (biopython, psycopg2, apsw, polars, pyzmq,
   pyzbar, ujson, pyxirr, tokenizers, selectolax). One file per recipe,
   each in its own commit so they're easy to revert independently
5. Fix the `bcrypt/test_bcrypt.py` `(self)` bug surfaced by §2d caveat #1
6. (After Phase 1 lands and is green for 5+ runs) — extend the matrix to
   the iOS lane (Phase 3), nightly cron (Phase 4), etc.

---

## 7. Sources backing this plan

Deep research output: `/private/tmp/claude-501/.../tasks/wx2eybl6x.output` (the 113-agent run with 20 confirmed claims). Highlights:
- Toga `ci.yml`, `testbed/tests/testbed.py`, Briefcase `commands/run`/`configuration` docs — for the pattern shape
- ReactiveCircus/android-emulator-runner README + Toga PR #2230 — Ubuntu+KVM is 2-3× faster than macOS for Android
- actions/runner-images#12777 — the iOS sim flake history on macos-15
- PEP 730 — explicit choice to keep iOS off per-commit GHA CI in upstream CPython
- cibuildwheel platforms docs — confirms the same pattern is the de facto standard

Local probe (this work session): `playground/stdout-probe/FINDINGS.md` — definitive evidence that Python stdout doesn't survive on either platform with Flet/serious_python; file markers do.
