---
name: forge-ci
description: >-
  Run, dispatch, and debug mobile-forge's GitHub Actions CI (build-wheels.yml)
  for recipe branches. Covers the push-trigger vs workflow_dispatch decision
  (and why doing both races), prebuild_recipes for BOTH kinds of recipe chains
  (build-time host_build deps AND runtime deps between recipes in the same
  run), the canonical-python gate that skips build.sh recipes on non-3.12
  legs, the [skip ci] + dispatch pattern, reading failures (job logs vs the
  on-device console.log artifacts), and telling infra flakes (runner-shutdown
  exit 143, phantom emulator, stray cancelled runs) from real failures. USE
  THIS SKILL when pushing a recipe branch for CI, when a CI run fails or gets
  cancelled, when a mobile test can't resolve a wheel that "was just built",
  when deciding how to CI a multi-recipe chain, or for any
  `gh workflow run build-wheels.yml` invocation. Sibling of
  `new-mobile-recipe` (authoring), `local-recipe-testing` (on-device loop),
  `forge-error-catalogue` (build errors), `native-recipe-bumps` (bumps).
---

# mobile-forge CI: triggering, chains, and triage

Everything here is about `.github/workflows/build-wheels.yml` (the parent) and
`build-wheels-version.yml` (the per-Python child it fans out to). Read those
files when behavior surprises you — this skill encodes the operational rules,
each bought with a wasted CI cycle.

## How a run is shaped

```
build-wheels.yml (push / workflow_dispatch / workflow_call)
└── detect            — which packages? which pythons?
    └── build (matrix: one child workflow per Python version 3.12/3.13/3.14)
        └── jobs (matrix: package × platform)   e.g. "Python 3.12 / foo 1.2.3 #1 (android)"
            ├── Build wheels        — prebuild_recipes first, then the package(s), all slices
            ├── mobile test (3.12 legs only by default) — recipe-tester APK on an
            │   emulator (android) / .app on a simulator (ios), polls console.log
            │   for the ">>>>>>>>>> EXIT N <<<<<<<<<<" sentinel
            └── upload artifacts    — wheels + test console.log
```

Key structural facts:

- **On push**, `detect` diffs `recipes/**` against the base and builds every
  changed recipe. The detected package list is ordered like `git diff` output
  (pathname-sorted) — do not rely on that ordering for dependency chains.
- **Each matrix job builds ONLY its own package(s).** Its `dist/` (and the
  `dist-test/` find-links dir the mobile test resolves from) contains that
  job's wheels plus whatever `prebuild_recipes` added — nothing from sibling
  jobs. This is the root cause of most "works locally, fails in CI" resolution
  surprises (see Chains below).
- **The canonical-python gate:** `build.sh` recipes produce `py3-none-<plat>`
  wheels that are identical on every Python leg, so they build **only on the
  canonical (first-listed, i.e. 3.12) leg**. On the 3.13/3.14 legs they are
  filtered out of the package list entirely.
- **Mobile tests run only on the legs listed in `mobile_test_pythons`**
  (default `3.12` — and per hard experience, 3.12 is the only leg whose mobile
  tests pass on this fork; never dispatch `mobile_test_pythons=ALL`).
- The mobile test bumps local wheels' build tag to `9999` in `dist-test/` so
  pip prefers them over same-version wheels already published on
  pypi.flet.dev.

## Trigger decision tree

```
Is the branch's changed-recipe set self-sufficient?
(every changed recipe's host/host_build/runtime deps are either published on
 pypi.flet.dev, pure-python on PyPI, or irrelevant to its mobile test)
│
├── YES → plain `git push`. detect does the rest. Do NOT also dispatch —
│         branch-level concurrency cancels one of the pair nondeterministically.
│
└── NO (it's a chain — see below) →
    1. commit with `[skip ci]` in the message (subject or body; GitHub honors it)
    2. push
    3. dispatch with explicit inputs:
       gh workflow run build-wheels.yml --repo <fork> --ref <branch> \
         -f packages="<consumer>:,<other>:" \
         -f prebuild_recipes="<dep1>,<dep2>"
```

Never do both for the same commit. If you accidentally end up with two live
runs on one branch (double dispatch, a late push, a killed script whose last
`gh workflow run` line still fired), concurrency keeps the **newest** and
cancels the rest — check `gh run list --branch <branch>` and make sure the
survivor has the inputs you meant.

## Chains: when and how to use `prebuild_recipes`

`prebuild_recipes` is a comma-separated list of recipes each job builds
*before* its main package(s), so their wheels are present in that job's
`dist/`/`dist-test/`. **List order is build order** (dependencies of
prebuilds go first: `flet-libhdf5,h5py`). Prebuilds honor each recipe's
`platforms:` declaration (an android-only lib is skipped on iOS jobs), and
they run on **every** Python leg — which is exactly what defeats the
canonical-python gate.

Both of these situations are chains — the second is easy to miss:

1. **Build-time chain** — the recipe has `requirements.host` /
   `requirements.host_build` on a not-yet-published recipe (usually a
   `flet-lib*`). Without prebuilding, the 3.13/3.14 legs strand: the gate
   skipped the build.sh lib there, and pip can't resolve it from
   pypi.flet.dev because it isn't published.
   *Example:* `packages="sherpa-onnx:" prebuild_recipes="flet-libonnxruntime"`.

2. **Runtime chain between recipes in the same run** — package A's
   `Requires-Dist` names package B, both changed on this branch. Their BUILDS
   are independent (all legs green), but A's **mobile test** fails at APK/app
   packaging with `No matching distribution found for B` — because A's job
   never built B (per-job isolation). Prebuild B in A's job:
   *Example:* `packages="ml-dtypes:,onnx:" prebuild_recipes="ml-dtypes"`
   (onnx's Requires-Dist includes ml_dtypes; ml-dtypes runs as both a package
   and a prebuild — that's fine and cheap).

   **Silent variant — the dep resolves to an UNPATCHED published copy.** If B is
   a *pure-Python* recipe that ALSO exists on pypi.flet.dev/PyPI, A's job won't
   error at resolution — it silently pulls the published B (which lacks B's
   not-yet-published 0.86 fix) and then fails at **runtime on device** with B's
   own loader error, not `No matching distribution`. Seen with opaque →
   `pysodium`: opaque's app pulled upstream pysodium, whose `__init__` raised
   `ValueError: Unable to find libsodium` (no bare-soname fallback), even though
   `flet-libsodium` was prebuilt. Fix: prebuild the **patched dep recipe** too so
   its `-9999` wheel wins — `packages="opaque:"
   prebuild_recipes="flet-libopaque,flet-libsodium,pysodium"`. Tell: a device
   traceback whose failing frame is in a *dependency* package, not the one under
   test → that dep is resolving to its unpatched published build.

If a chain dep lives on a *different* branch, merge that branch in first
(`git merge machine/<dep-branch>`) so the recipe dir exists for the prebuild.

## Meta rules the CI will enforce before anything builds

- **Jinja-guard the whole key, not just its entries.** An android-only host
  dep written as a guarded list item under an unguarded `host:` key renders
  `host:` as `None` on iOS and fails schema validation
  (`None is not of type 'array'`) on every iOS leg. Guard the key:
  ```yaml
  # {% if sdk == 'android' %}
    host:
      - flet-libcpp-shared >=27.2.12479018
  # {% endif %}
  ```
  (Entry-level guards are fine when other entries keep the list non-empty.)
- `verify_render.py` (in the `new-mobile-recipe` skill's scripts) checks that
  meta.yaml *parses* per SDK — it does **not** catch empty-list schema
  violations or `{NDK_ROOT}`-style vars leaking into the wrong lane. After
  editing lanes, render both SDKs and content-check the values.

## Reading a failed run

```bash
gh run view <run-id> --repo <fork> --json conclusion,jobs \
  --jq '{conclusion, failed: [.jobs[] | select(.conclusion=="failure") | .name]}'
```

The failing-leg *pattern* is the first diagnostic:

| Pattern | Meaning |
|---|---|
| One leg failed, siblings green | Usually infra flake (below) — or a genuinely version-specific break (rare; read the log) |
| All 3.12 legs failed, 3.13/3.14 green | The **mobile test** failed, not the build (3.12 = the test leg). Get the console.log artifact |
| All iOS legs failed, android green | Platform-lane problem — often a meta rendering issue (see rules above) or an iOS-only build gap |
| Everything failed at detect/setup | Workflow or input problem, not the recipe |

Then the two log sources:

```bash
# Job log (build phase, staging, packaging errors):
gh api repos/<fork>/actions/jobs/<job-id>/logs > job.log
grep -nE "error:|CMake Error|No matching distribution|FAILED" job.log

# On-device test output (the actual pytest run) — it is an ARTIFACT, usually
# NOT echoed into the job log:
gh run download <run-id> --repo <fork> -D artifacts/
cat artifacts/test-py3.12-<platform>-<pkg>-*/console.log
```

A missing console.log artifact for a failed 3.12 job means the job died
*before* the device test — almost always at recipe-tester packaging
(resolution: see Chains) rather than on the device.

## Infra flakes vs real failures

Seen repeatedly on this fork; all are safe to retry once:

- **`The runner has received a shutdown signal` / exit 143** — GitHub pulled
  the runner. Rerun the failed jobs (`gh run rerun <id> --failed` — only
  works after the whole run completes; if siblings are still running, wait).
- **Phantom emulator** — the android test step can't find the emulator it
  just booted. Rerun.
- **A run shows `cancelled` with no sibling run and no human action** —
  stray infra cancel. Re-dispatch with the same inputs.
- **`gh workflow run` returns HTTP 500** — retry after ~20s; then verify with
  `gh run list` that exactly one run was created (a 500 can be
  create-then-error).

Real failures reproduce on rerun. Don't retry more than once without reading
the log.

## Dispatch inputs quick reference

| Input | Notes |
|---|---|
| `packages` | `"name:"` entries, comma-separated; `:` suffix means default version. `ALL` expands to every recipe |
| `prebuild_recipes` | comma-separated, **ordered**, built per-job before packages |
| `python_versions` | defaults to all three; narrow for a quick re-run (e.g. `3.12.13`) |
| `mobile_test_pythons` | default `3.12` — leave it; never `ALL` on this fork. Pass `""` to build wheels WITHOUT the on-device test (e.g. when the test can't pass yet because the fix lives in unreleased serious_python — you'll test locally) |
| `archs` | default `android,iOS` |
| `python_build_run_id` | a `flet-dev/python-build` Actions run-id whose artifacts to use instead of the pinned release; empty → the hardcoded FALLBACK in `build-wheels-version.yml` (grep `PYTHON_BUILD_RUN_ID: ${{ … || '<id>' }}`). Bump that fallback to ship an unreleased python-build fix to every job |

## Testing recipes against UNRELEASED serious_python / python-build (pre-PR validation)

When a recipe's green depends on an sp/python-build fix that isn't in a published
release yet (e.g. sp #223 iOS framework relocation, python-build iOS `_posixshmem`),
wire CI + local to the fix so recipes validate BEFORE the PR:
- **python-build fix** → bump the `PYTHON_BUILD_RUN_ID` fallback constant in
  `build-wheels-version.yml` to the python-build CI run that has it (verify that run
  is `success` and has the `python-darwin-<ver>` / `python-android-<ver>` artifacts).
- **serious_python fix** → add a `[tool.flet.flutter.pubspec.dependency_overrides]`
  block to `tests/recipe-tester/pyproject.toml.tpl` with **git** deps for
  serious_python + `_darwin` + `_android` + `_platform_interface`, each
  `{ git = { url = "…/serious-python.git", ref = "<branch>", path = "src/<pkg>" } }`.
  flet merges [tool.flet.flutter.pubspec] via a recursive merge, so the nested git
  table passes through to the Flutter pubspec; dart pub clones the branch and runs its
  darwin scripts. Mark it TEMPORARY — remove once sp is released. (Local old-Xcode
  builds also need `device_info_plus`/`connectivity_plus` pins, but keep those OUT of
  the committed template — add post-staging; CI's Xcode doesn't need them.)
- The on-device iOS/APK test in CI still uses PUBLISHED sp, so it can't pass until the
  release — dispatch wheel builds with `mobile_test_pythons=""` and verify the recipe
  LOCALLY (git or path sp override + local flet-cli + `--python-version 3.12`; see the
  local-recipe-testing skill). CI goes green only after the sp/python-build release.

## Watching a run without babysitting

Poll `gh run view <id> --json status` in a loop (240–300s interval — these
runs take 30min–3h) and print the conclusion + failed-job list when it
completes. One watcher per run; kill stale watchers when you supersede a run,
and remember a killed multi-line script may still fire its remaining lines —
put dispatches *before* long build loops in scripts, or in separate commands.
