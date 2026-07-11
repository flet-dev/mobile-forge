---
name: new-mobile-recipe
description: Authoring playbook for brand-new mobile-forge recipes (flet-dev/mobile-forge) — cross-compiled Python wheels for iOS and Android distributed via pypi.flet.dev. Covers deciding whether a package needs a recipe at all (pure-Python sdist-only packages need `[tool.flet] source_packages` in the app, NOT a recipe), picking the right recipe shape (minimal C-extension, Rust/PyO3, C-ext with patches, meson-python, scikit-build-core, native library, native-library consumer, PEP 517 shim for no-sdist CMake giants, prebuilt-repackage + host_build chain), running the build, and diagnosing the recurring local-dev pitfalls (NDK r27d install fragility, Android libc++_shared runtime linkage, stale pre-2026-06 support tarballs). USE THIS SKILL whenever the user asks to add a new recipe to mobile-forge, mentions "forge recipe", "mobile-forge", "recipe for <package>", "build a wheel for mobile/iOS/Android", "add <package> to pypi.flet.dev", or wants to cross-compile a Python package for Flet's mobile targets. Use proactively if the user pastes a flet-dev/flet discussions URL from the Packages category (https://github.com/flet-dev/flet/discussions/categories/packages) and asks to make a recipe for it. Sibling skills — `local-recipe-testing`: run the finished wheel on an emulator/simulator; `forge-ci`: push/dispatch and triage CI runs; `forge-error-catalogue`: concrete build-error → fix mappings; `native-recipe-bumps`: bump versions of existing `flet-lib*` recipes (use that, not this, for bumps).
---

# Authoring new mobile-forge recipes

This skill walks through the full lifecycle of adding a brand-new recipe to `flet-dev/mobile-forge`: deciding whether a package needs a recipe at all, picking the right shape, running the build for iOS and Android, diagnosing the failures that real packages produce, and verifying the result inside a real Flet app before shipping the branch.

The workflow is opinionated and biased toward the fastest iteration loop. Most of the painful local-dev gotchas (CI-baked Linux paths in the Android Python tarball, NDK 7-zip extraction bugs, libc++_shared runtime linkage) are encoded as bundled scripts and templates — use them instead of reinventing.

## Workflow at a glance

1. **Scope** — is this a recipe candidate? If yes, which shape?
2. **Preflight** — verify env once, apply any one-time local fixes
3. **Author** — write `recipes/<name>/meta.yaml` (+ test, + optional patches/build.sh) from a template
4. **Build** — fastest iOS sim slice → all iOS → arm64-v8a → all Android
5. **Diagnose** — work through any failures (see the `forge-error-catalogue` skill)
6. **End-to-end test** — stage the recipe into the committed `tests/recipe-tester` app, verify on device/emulator (details in the `local-recipe-testing` skill)
7. **Ship** — branch from `main`, structured commit, push, run CI (details in the `forge-ci` skill)

If any phase fails, fix forward in that phase before moving on. Don't skip ahead.

## When NOT to use this skill

- **Pure-Python packages** (no `.c`/`.cpp`/`.rs` source). PyPI's `py3-none-any` wheels already work on iOS and Android via serious-python's sitecustomize. No recipe needed. Confirm by checking PyPI: if the package only has a `py3-none-any.whl`, skip it. If it has `manylinux*` / `macosx_*` / `cp3X-cp3X-*` wheels, it's a recipe candidate.
- **Pure-Python but SDIST-ONLY packages** (no wheel at all, but the sdist contains no native source — e.g. insightface's pure-Python releases). Still no recipe: the app opts in with `[tool.flet] source_packages = ["<name>"]` in its pyproject.toml, which makes `flet build` set `SERIOUS_PYTHON_ALLOW_SOURCE_DISTRIBUTIONS` and pip builds the sdist for the target. A recipe is only for packages that need *cross-compilation*.
- **Bumping an existing `flet-lib*` recipe to a new upstream version** — use the sibling skill `native-recipe-bumps` instead. It encodes the version-conditional Jinja patterns specific to that workflow.
- **Debugging a build failure in an existing recipe** — that's a different shape. This skill focuses on creation; for fixing, inspect `errors/<pkg>-*.log` directly and cross-reference the `forge-error-catalogue` skill.

---

## Phase 1: Scope

### Is this a candidate?

```
PyPI tags?
├── only py3-none-any                → SKIP — pure-Python, no recipe needed
├── manylinux*, macosx_*, win_*      → CANDIDATE — needs cross-compile for mobile
├── no wheels at all (sdist-only)
│   ├── sdist is pure-Python         → NO RECIPE — app declares it in
│   │                                   `[tool.flet] source_packages` (see
│   │                                   "When NOT to use" above)
│   └── sdist has native source      → CANDIDATE — same compile path
└── no sdist either (wheels-only)    → CANDIDATE — set `source.url` to a GitHub
                                        release/tag tarball (e.g. pyzbar). forge's
                                        PythonPackageBuilder honors source.url
                                        (build.py); only truly source-less
                                        packages are not viable.
```

Also dig into the upstream:
- **Is the build active?** Check last release date on PyPI / GitHub.
- **Does upstream use a Rust toolchain?** (Look for `maturin` or `setuptools-rust` in `pyproject.toml::build-system.requires`.) — this is fine, just selects a different template.
- **Does it depend on a native C library that isn't bundled?** (Look for `find_library`, `pkg-config` calls in `setup.py`, or a list of system deps in the README.) — if so, you may need to write a `flet-lib*` recipe first.
- **Does upstream explicitly forbid mobile?** (Some maintainers say "I won't accept mobile patches.") Doesn't actually block you — recipes live in mobile-forge, not upstream. The disclaimer is about whether upstream merges patches, not whether the code cross-compiles.

### Pick a recipe shape

Match the package to one of these shapes. Each maps to a template in `templates/`:

| Shape                                      | When                                                                                                    | Template                                                           |
|--------------------------------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| Minimal C-extension, well-behaved upstream | C/C++ source, plain setuptools, no system deps                                                          | `templates/meta-minimal.yaml`                                      |
| Minimal C-ext + Android C++ runtime        | Same as above but C++ source (bundled or upstream) → needs libc++_shared on Android                     | `templates/meta-minimal-with-android-libcpp.yaml`                  |
| Rust via PyO3 / maturin                    | `[build-system].requires` contains `maturin` or `setuptools-rust`                                       | `templates/meta-rust.yaml`                                         |
| C-ext needing patches                      | Upstream `setup.py` reaches for host `/usr/include`, has `if sys.platform` branches, or hardcodes paths | `templates/meta-with-patches.yaml` + patch file in `patches/`      |
| meson-python build backend                 | `[build-system].build-backend = "mesonpy"` (scipy, scikit-image, scikit-learn, pywavelets, contourpy)   | No template — copy from `recipes/pywavelets/` (on main): `build.backend-args:` list with `-Csetup-args=--cross-file` + `-Csetup-args={MESON_CROSS_FILE}`; extra meson options ride the same way (`-Csetup-args=-D<opt>=<val>`) |
| scikit-build-core / CMake with sdist       | `[build-system].build-backend = "scikit_build_core.build"` (duckdb, onnx, ml-dtypes)                     | No template — copy from `recipes/duckdb/` (on main) or `recipes/onnx/` (branch `machine/onnx-insightface`); CMake args via `script_env` `CMAKE_ARGS` (skbuild appends it after its own defaults) |
| C-ext consuming an existing flet-lib       | Already-built `flet-libX` covers the C dep (libxml2, libcurl, libssl via openssl, etc.)                 | Adapt `templates/meta-with-patches.yaml` + add `requirements.host` |
| Native library itself (flet-lib*), **static** | New C library a Python C-extension links at build time (libxml2, libcurl, libgeos…)                  | `templates/meta-flet-lib.yaml` + `templates/build-flet-lib.sh`     |
| Native library, **ctypes-loaded (shared)** | A pure-Python wrapper `dlopen`s the lib at runtime via `ctypes` (pyzbar→libzbar, python-magic→libmagic) | `templates/meta-flet-lib.yaml` + `templates/build-flet-lib-shared.sh`; see Pattern H |
| C-ext that links a lib via a `*-config` tool | Compiled C-ext whose `setup.py` shells out to `pg_config`/`mysql_config`/… (psycopg2→libpq, mysqlclient→libmysqlclient) | A **static+PIC** `flet-lib*` (`build-flet-lib.sh` + `-fPIC`) shipping a config-shim, + consumer `script_env`/patch; see Pattern I |
| CMake giant, **no sdist AND no setup.py/pyproject.toml** | Upstream's only wheel path is a host==target build script (onnxruntime's `ci_build/build.py`, TF's `build_pip_package_with_cmake.sh`) | No template — copy from `recipes/onnxruntime/` or `recipes/tflite-runtime/` (branches `machine/onnxruntime` / `machine/tflite-runtime`); see "PEP 517 shim" deep-dive below |
| **Prebuilt-repackage + host_build chain**  | Upstream publishes official prebuilt mobile archives of the native lib AND the consumer's own cmake links + re-ships the `.so` (flet-libonnxruntime→sherpa-onnx) | `build.sh` repackager + consumer `requirements.host_build`; copy from `recipes/flet-libonnxruntime/` + `recipes/sherpa-onnx/` (branch `machine/sherpa-onnx`); see "prebuilt-repackage" deep-dive below |

If unsure, start with **minimal C-extension** and let the build tell you what's missing. Iterate up the table as failures surface.

### Shape deep-dive: PEP 517 shim for no-sdist CMake giants (onnxruntime, tflite-runtime)

**When:** no sdist and no usable `setup.py`/`pyproject.toml` at the source root — upstream's supported wheel path is a host==target script. Forge's `PythonPackageBuilder` is PEP 517-only, so the recipe's `mobile.patch` **ADDs** the PEP 517 entry instead of fighting the script: a `pyproject.toml` with `build-backend = "forge_<pkg>_backend"` + `backend-path = ["_forge"]`, plus a new `_forge/forge_<pkg>_backend.py` that wraps `setuptools.build_meta` (`from setuptools.build_meta import *`, then override the hooks). `source.url` points at the GitHub tag tarball.

The shim's load-bearing rules (each one bought with a failed build):

- **Run the cmake configure+build before EVERY hook, guarded by a marker file** in the build dir. PEP 517 hooks are separate subprocesses, and `setup.py`/setuptools touch the staged tree as early as `egg_info` (setuptools validates every declared package dir there).
- **Per-slice build dirs** (`.forge_build/<key>` inside the source tree), keyed by `ANDROID_ABI` on Android and `CMAKE_OSX_SYSROOT`+`CMAKE_OSX_ARCHITECTURES` on iOS — forge **reuses the unpacked source tree across slices** within one invocation. A shared build dir shipped arm64 code inside onnxruntime's x86_64 wheel on CI round 1 (`llvm-readelf -h` showed e_machine 183 = AArch64).
- **Stage the python package fresh on every hook** (overlay / rm+copy from the current slice's build dir into the source root) so the current slice always wins.
- Prefer **`-D<pkg>_BUILD_SHARED_LIB=OFF` → one statically-linked pybind module**: no ctypes/dylib gate, and it is exactly the wheel shape that works on BOTH platforms today (onnxruntime's Android design turned out to BE the iOS wheel shape; pywhispercpp/ncnn are the same shape).
- CMake args ride in a recipe `script_env` var (`FORGE_CMAKE_ARGS`) that the shim `shlex.split`s. **Multi-token `-D` values cannot ride inside it** — give linker-flag strings their own env var and let the shim assemble the single `-D` argument (tflite's `FORGE_SHARED_LINKER_FLAGS: -Wl,-z,max-page-size=16384 -L{HOST_PYTHON_HOME}/lib -lpython{py_version_short}`).
- **Trap — `setup.py` platform predicates:** under the crossenv `platform.system()` returns `"Android"` / `"iOS"`, which may match NO upstream branch → the libs list stays unset and the wheel silently ships **without the pybind `.so`** (onnxruntime extends upstream's predicate to `("Linux", "AIX", "Android", "iOS")`; the Darwin branch stays intact for real macOS builds).
- **Name the staged extension with the target `EXT_SUFFIX`, never a plain `.so`.** A shim that hand-stages the pybind module (`shutil.copy2(built, pkg / "_foo.so")`) must instead write `pkg / f"_foo{sysconfig.get_config_var('EXT_SUFFIX')}"` (android cp312 → `_foo.cpython-312.so`). Flet 0.86's serious_python only relocates ABI-tagged (`cpython-*`/`abi3`) extension modules into an importable jniLibs/`.soref` slot on Android; a plain `<name>.so` is misfiled as a dependency lib and fails on-device with `cannot import name` (builds green, iOS fine — a nasty android-only surprise). `.cpython-*.so` is a valid CPython suffix so the import still resolves. If `setup.py` builds `package_data` by globbing hardcoded plain `.so` names, patch that too (wildcard the pybind name, package the real basename) or the retagged file is dropped. See the `forge-error-catalogue` entry "cannot import name … for a native `.so` — Android, Flet ≥ 0.86".
  - **Cross-slice cleanup:** forge reuses the unpacked source tree across arch slices in one invocation, so if the shim stages into a dir it does NOT wipe each hook (e.g. an overlay `copytree(dirs_exist_ok=True)`), a prior slice's tagged `.so` lingers. Android is safe (all ABIs share `.cpython-312.so` → overwritten), but **iOS suffixes differ per slice** (`.cpython-312-iphoneos.so` vs `-iphonesimulator.so`) so the wheel ships BOTH and serious_python's `.so`→framework conversion fails on-device. Either `rmtree` the package dir before staging (tflite's shim) or, after retagging, delete every sibling `<name>*.so` that isn't the current slice's target (onnxruntime's shim).

**Real examples:** `machine/onnxruntime:recipes/onnxruntime/` and `machine/tflite-runtime:recipes/tflite-runtime/` — read via `git show <branch>:<path>` if not on those branches. Both are ONE `mobile.patch` (description as text preamble above the first `---` header, per repo convention).

### Shape deep-dive: prebuilt-repackage + host_build chain (flet-libonnxruntime → sherpa-onnx)

**When:** upstream publishes an official prebuilt mobile archive of a big native lib AND the consumer's own build system knows how to link + re-ship it (sherpa-onnx's `cmake/onnxruntime.cmake` reads `SHERPA_ONNXRUNTIME_{INCLUDE,LIB}_DIR` env vars). Nobody has to cross-compile the big lib:

1. **A `flet-lib*` build.sh recipe repackages the prebuilt archive** — `source.url` → the zip (csukuangfj/onnxruntime-libs repackages Microsoft's official Maven AAR), build.sh stages `$ANDROID_ABI/libonnxruntime.so` + headers into `$PREFIX/{lib,include}`. **Verify 16KB alignment of the prebuilt `.so` first** (`llvm-readelf -l`: every `LOAD` align `0x4000`) — prebuilt-`.so`-in-wheel is the classic 16KB-crash class. Gotcha: forge strips the archive's leading path component on unpack (`jni/` and `headers/` dirs are gone), so build.sh paths are relative to the unpack root.
2. **The consumer declares it in `requirements.host_build`** — installed into the cross env for the build (link time only), **NOT promoted to `Requires-Dist`**. That's the whole difference from `requirements.host`.
3. **The consumer's build re-ships the `.so` inside the consumer wheel** (sherpa's cmake `install(FILES … lib)` → `sherpa_onnx/lib/`), and a patch adds an **RTLD_GLOBAL ctypes preload** at the top of `__init__.py` — forge/NDK-built modules carry no RUNPATH on Android, so the dynamic linker can't resolve the DT_NEEDED entry by itself. The preload tries `libonnxruntime.so` then `libonnxruntime.fwork` (covers a future iOS build).

**CI consequence:** this is a chain recipe — plain push strands it; see "CI: push vs dispatch" in Phase 7.

**Real example:** `machine/sherpa-onnx:recipes/flet-libonnxruntime/` + `machine/sherpa-onnx:recipes/sherpa-onnx/` (patches `android-no-jni.patch` + `android-preload-ort.patch`).

### Naming

- Recipe directory name and `package.name` in meta.yaml must match the PyPI sdist filename exactly (case-sensitive). `MarkupSafe`, not `markupsafe`. `cffi`, not `CFFI`. Look at `<pypi-name>-<version>.tar.gz` filename on PyPI for the ground truth.
- **Quote two-component versions like `1.87`** as `version: "1.87"` — bare `1.87` is parsed by YAML as a float, then forge does `Path / version` and dies with `TypeError: unsupported operand type(s) for /: 'PosixPath' and 'float'`. Three-component versions (`1.2.3`) parse as strings already; the float bite is two-segment only.
- For `flet-lib*` native-library wheels, prefix with `flet-lib` followed by the C library's name (no version). `flet-libzbar`, `flet-libfreetype`, etc. These are mobile-forge inventions, not PyPI packages.

---

## Phase 2: Preflight

Most of preflight is one-time setup per checkout. If the user already has a working env 
(e.g., they've built recipes before in this clone), most of this is a no-op. Run the bundled check first:

```bash
bash .claude/skills/new-mobile-recipe/scripts/preflight.sh
```

It verifies:

- The mobile-forge venv is active (`venv3.12/bin/activate` sourced)
- `MOBILE_FORGE_IOS_SUPPORT_PATH` and `MOBILE_FORGE_ANDROID_SUPPORT_PATH` are set and contain the expected Python interpreters
- `NDK_HOME` points to a real NDK r27d (or compatible) install
- `forge` resolves on `$PATH`
- `dist/` has the precompiled dep wheels (bzip2, openssl, libffi, mpdecimal, xz) for both iOS slices and Android ABIs

If any check fails, the script prints what to do. **The one non-trivial fix has its own script:**

### Fix: NDK install (one-time)

Mobile-forge pins NDK r27d. If `$NDK_HOME` is empty or points at a wrong version, run:

```bash
bash .claude/skills/new-mobile-recipe/scripts/install_ndk_r27d.sh
```

This is a more robust version of `.ci/install_ndk.sh` — it passes `-snld` to 7-zip to 
suppress the "dangerous symbolic link" warning that aborts the upstream installer on macOS. 
Falls back to `hdiutil` if 7-zip extraction fails entirely. Outputs an `export NDK_HOME=...` 
line for you to add to your shell.

If you already have Android Studio installed with NDK 27.x or 28.x at `~/Library/Android/sdk/ndk/`, 
you can `export NDK_HOME=~/Library/Android/sdk/ndk/<version>` and use that — for most recipes 
the differences between r27 / r27d / r28 are immaterial. CI builds against r27d; your local r27 
should produce equivalent wheels.

### Note: Android sysconfigdata CI paths — self-healing, nothing to fix

Historically the `python-android-mobile-forge-3.12.tar.gz` broke macOS local dev: CI-runner
paths (`/home/runner/...`) baked into `_sysconfigdata__linux_.py` meant crossenv couldn't
find the cross-compiler. **Fixed upstream in python-build** (PRs
[#5](https://github.com/flet-dev/python-build/pull/5) /
[#8](https://github.com/flet-dev/python-build/pull/8) /
[#9](https://github.com/flet-dev/python-build/pull/9)): releases since 2026-06 ship
SELF-RELOCATING sysconfigdata, and `setup.sh` pins a release ≥ 20260701 — so a normal setup
needs nothing. Two things worth knowing:

- The `/home/runner` strings are still in the file *by design* (build-time constants that an
  injected `_mobile_forge_relocate_sysconfig()` rewrites at import time), so grep-counting
  them tells you nothing. `preflight.sh` checks for the relocator marker instead.
- If you ever see `Cannot find cross-compiler ('/home/runner/...')`: on a modern tarball it
  means the relocator found no NDK — set `NDK_HOME` (or `ANDROID_NDK_HOME`) and retry. If the
  relocator marker is genuinely absent, your extracted tree predates 2026-06 — delete
  `downloads/support/python-android-*` and re-run `setup.sh` rather than patching it.

---

## Phase 3: Author the recipe

### 3.1 — Create the directory and copy a template

```bash
mkdir -p recipes/<pypi-name>/tests
cp .claude/skills/new-mobile-recipe/templates/meta-<shape>.yaml recipes/<pypi-name>/meta.yaml
cp .claude/skills/new-mobile-recipe/templates/test_template.py recipes/<pypi-name>/tests/test_<py_safe_name>.py
```

Where `<py_safe_name>` is the package name with hyphens replaced by underscores (Python module convention). `lru-dict` → `test_lru_dict.py`. `MarkupSafe` → `test_markupsafe.py`.

### 3.2 — Customize meta.yaml

Open the template and replace placeholders. The templates are self-documenting — read 
the comments for what each field does. Quick reference:

- `package.name` — case-sensitive, match sdist filename
- `package.version` — always a double-quoted string (e.g. `"2.0.1"`), never a bare value
- `source` — omit if PyPI sdist; specify `url:` for native libs from GitHub/GNOME/etc.
- `requirements.host` — peer-built native deps (other recipes, especially `flet-lib*`)
- `requirements.build` — host-side build tools (cython, ninja, meson, etc.)
- `build.script_env` — env vars passed to the upstream build (CFLAGS, OPENSSL_DIR, etc.)
- `patches` — list of filenames in `patches/` to apply

For deep dives on each shape, see `references/recipe-patterns.md`.

### 3.3 — Customize the test

Open `tests/test_<name>.py` and replace the placeholder with a real smoke test:

- `import <package>` (the most important line — proves the wheel loads)
- One simple call that exercises the C-extension path (constructing the main type, doing a round-trip, etc.)
- Don't try to mirror upstream's test suite — that's not the goal. A 5-line smoke test that proves loading and basic use is correct is the bar.

**Repo test conventions (enforced in review):**

- **NO version-assertion tests** (`assert <pkg>.__version__ == "X.Y.Z"`). They add nothing
  over the pinned wheel install and break on every version bump.
- **Every test function has a docstring** — one line saying what behavior it proves.
- Tests must be **network-free and deterministic** (fixed seeds, committed tiny assets) —
  they run on an emulator with no guarantees about connectivity.

For ML/inference recipes, raise the bar from import-only to real compute:

- **Test-only deps** go in `tests/requirements.txt` (PEP 508 lines; the recipe-tester expands them into its pyproject — merged in #98). E.g. tflite-runtime's tests need numpy without numpy being a recipe dep of the test app.
- **A tiny committed model asset (~1KB) beats an import-only test** — CI's emulator then runs REAL inference: tflite's `dense_relu.tflite` (1KB, generated with desktop TF at a fixed seed), onnxruntime's `tiny_mlp.onnx` (170 bytes, hand-built relu graph).
- **Big assets use the discovered-by-presence pattern**: the test looks for the model file next to itself — dropped there for the local on-device loop, absent in CI → the test skips (sherpa-onnx's silero VAD, 2.2MB). These MUST stay gitignored (the `recipes/*/tests/*.onnx` rule exists) — committing one flips the CI skip into a mandatory download-free run and embeds megabytes in the repo.
- **No desktop wheel to test against? Validate the test LOGIC on desktop via a module-alias shim**: tflite's test ran on desktop TF with the `tflite_runtime.interpreter` module aliased to `tf.lite` — that caught a real math bug before ever touching a device.

### 3.4 — Render-check meta.yaml

```bash
python .claude/skills/new-mobile-recipe/scripts/verify_render.py recipes/<name>/meta.yaml
```

Renders the meta.yaml for all SDK contexts (iphoneos, iphonesimulator, android) and prints the parsed dict for each. If Jinja syntax is broken or YAML doesn't parse, you'll see it here cheaply — before spending minutes on a `forge` build. Common rookie mistakes:

- Forgot to wrap `{% if %}` in `# {% ... %}` comments — YAML parser chokes on bare Jinja
- Used `sdk == 'iOS'` instead of `sdk == 'iphoneos'` / `sdk == 'iphonesimulator'` — branch never matches
- Forgot to quote a version that's also a valid YAML float (`2.0` → `2`)

### 3.5 — Patch hygiene

- **Generate patches mechanically**: unpack the sdist twice (`a/`, `b/`), edit `b/`, then
  `diff -ruN a b > recipes/<name>/patches/mobile.patch`. Hand-edited hunks with wrong line
  counts fail at apply time.
- **The patch's description lives INSIDE the patch file** — as a plain-text preamble above
  the first `---` header (`patch(1)` skips everything before it). The `patches:` list in
  meta.yaml is bare filenames, no comments.
- **Never concatenate regenerated diffs onto an existing patch file.** If you regenerate,
  regenerate the WHOLE file. Concatenation duplicates hunks, and `patch --dry-run` cannot
  catch it (each duplicate hunk validates independently against the pristine tree, then the
  second application corrupts the file).
- **Verify by REALLY applying, not dry-running**: unpack a scratch copy of the sdist, apply
  the patch for real, then content-grep the tree for a marker from each hunk. This is the
  only check that catches duplicated hunks, wrong-strip-level paths, and hunks that applied
  with fuzz somewhere unintended.
- Same discipline for any scripted edit (`python -c "...str.replace..."`): `str.replace`
  with a non-matching needle silently no-ops. Always `assert needle in text` before
  replacing, or grep the output file for the new content after.

### 3.6 — Cross-cutting conventions from the ML wave (CMake-heavy recipes)

- **Version as a Jinja constant.** A bare `{% set version = "X.Y.Z" %}` as the first line, reused in `package.version` AND `source.url` — bumps become one-line edits. See `recipes/faiss-cpu/meta.yaml`; onnxruntime uses the same idiom.
- **iOS lane for CMake projects.** Split `script_env` with `# {% if sdk == 'android' %} … # {% else %} … # {% endif %}`. The iOS args: `-DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT={{ sdk }} -DCMAKE_OSX_ARCHITECTURES={{ arch }} -DCMAKE_OSX_DEPLOYMENT_TARGET={{ sdk_version }}` plus `-DPython_LIBRARY={HOST_PYTHON_HOME}/lib/libpython{py_version_short}.dylib` (`.so` on Android). **No `-GNinja` on the iOS lane** — let it default to Unix Makefiles (the faiss/duckdb/pywhispercpp tell; Android keeps Ninja). And `flet-libcpp-shared` is **Android-only** — iOS links the system libc++, so Jinja-gate that host dep.
- **Python/numpy/pybind11 headers without imports.** The target numpy can never be imported on the build host, so never let the build "ask numpy" for its include dir. Instead: `requirements.host: numpy ^2.0.0` + `pybind11`, then inject `-I{HOST_PYTHON_HOME}/include/python{py_version_short} -I{platlib}/numpy/_core/include -I{platlib}/pybind11/include` (tflite's `FORGE_WRAPPER_INCLUDES`) — or `-DPython_NumPy_INCLUDE_DIR={platlib}/numpy/_core/include` when FindPython runs (onnxruntime). numpy-2 headers yield wheels that run on numpy 1.x AND 2.x.
- **Host tools during a cross build** — three escalating patterns:
  1. *Self-fetched by the project*: leave it alone. With no `ONNX_CUSTOM_PROTOC_EXECUTABLE` set, ORT's own cmake fetches the pinned `protoc_mac_universal` v21.12 on macOS hosts — zero plumbing.
  2. *Standalone host tool, built once and cached*: build it in the system tempdir **keyed by the upstream-pinned version** (tflite's flatc, from the `GIT_TAG` parsed out of `tools/cmake/modules/flatbuffers.cmake`). Host-arch tools are safe to share across slices — unlike per-arch artifacts (the stale-static-lib cache trap that bit ckzg).
  3. *Scrub the cross env for the host-tool cmake invocation*: pop `CC`/`CXX`/`AR`/`LD`/`RANLIB`/`STRIP`/`READELF`/`NM`, `CFLAGS`/`CXXFLAGS`/`CPPFLAGS`/`LDFLAGS`, `_PYTHON_SYSCONFIGDATA_NAME`, `PYTHONPATH` — they all point at the NDK/iOS cross toolchain and poison a host build.

---

## Phase 4: Build iteratively

**Always start with one slice.** A full `forge iOS <name>` takes 3-5 minutes per slice × 3 slices ≈ 15 minutes. 
A single `forge iphonesimulator:arm64 <name>` is 1-2 minutes. Fail fast.

The order to build in:

```bash
# 1. Fastest validation — same arch, just different OS. Will surface meta.yaml errors,
#    upstream patches needed, missing deps. Usually the most informative single slice.
forge iphonesimulator:arm64 <name>

# 2. If green, do all 3 iOS slices. The x86_64-sim build is a true cross
#    (arm64 host → x86_64 target) and surfaces any cross-arch issues iOS might have.
forge iOS <name>

# 3. Move to Android. arm64-v8a first — same archetype.
forge android:arm64-v8a <name>

# 4. If green, all 4 Android slices.
forge android <name>
```

**On success**, the wheel lands in `dist/` with the platform-tagged filename. For each slice you should see exactly one new wheel file.

**On failure**, the log moves from `logs/<name>-...log` to `errors/<name>-...log`. Read it. The bottom of the error log includes the full environment that was passed to the build (debug=True lines starting with `>>>` and `    KEY=value`) — these are gold for diagnosing why something wasn't found.

```bash
tail -100 errors/<name>-5.12.1-cp312-<slice>.log
```

For specific failure modes and their fixes, see the `forge-error-catalogue` skill. **Key recurring ones to watch for:**

- `Cannot find cross-compiler ('/home/runner/...')` → Android only: on a modern tarball the sysconfig relocator found no NDK (set `NDK_HOME`); on a pre-June-2026 tarball the Phase 2 rewrite wasn't run
- `dlopen failed: library "libc++_shared.so" not found` (at runtime, not build) → add `flet-libcpp-shared` host dep, Android-only via Jinja
- `fatal error: 'X.h' file not found` → missing host dep; add to `requirements.host`
- `ld: library not found for -lY` → same, missing host dep
- `Invalid configuration 'arm64-apple-ios': machine 'arm64-apple' not recognized` → patch `config.sub` (see flet-libxml2 for canonical patch)
- `PT_LOAD alignment is X, expected >= 16384` → Android 16KB alignment violation; recipe LDFLAGS override stripped the alignment flag
- `relocation R_AARCH64_… cannot be used against symbol '…'; recompile with -fPIC` → a static `flet-lib*.a` folded into a C-extension `.so` wasn't built PIC; add `export CFLAGS="${CFLAGS:-} -fPIC"` to the flet-lib's build.sh (Pattern I)
- `pg_config executable not found` during **`uv run flet build`** (host phase, sdist-only pkg like psycopg2) → use `uv run --no-sync flet build …`
- iOS autotools lib: `use of undeclared identifier '<path-component>'` (e.g. `'Users'`, `'playground'`) → forge's iOS LDFLAGS has `-F "…"` with literal quotes that break a baked-in C string; `export LDFLAGS=$(printf '%s' "$LDFLAGS" | tr -d '"')` (Pattern I)

---

## Phase 5: Diagnose failures

When a build fails:

1. **Look at the error log**, specifically the last ~100 lines. Find the first hard error (not warning).
2. **Match the error pattern** in the `forge-error-catalogue` skill. Most failures fit a known shape.
3. **Apply the documented fix.**
4. **Rebuild** with `forge --clean <slice> <name>` — `--clean` wipes the build tree so the next run starts fresh (necessary if you changed patches or recipe deps).

If the failure doesn't match a known pattern, the categories to investigate are:

- **Missing system header / library** — add a host dep (search the recipes/ dir for a `flet-lib*` that ships it; if none, write one)
- **Build script reaching for paths that don't exist on iOS/Android** — write a patch (`patches/mobile.patch`) that filters those paths from `setup.py` / `configure` / `Makefile`
- **Linker flag that's macOS-specific being used on iOS** (e.g., `-undefined dynamic_lookup`) — usually safe to keep; iOS clang accepts it
- **Same flag being rejected on Android** — Jinja-gate the flag to non-Android

Don't go down rabbit holes. If you spend more than 30 minutes on a single failure without finding the pattern, that's a signal the package isn't a "minimal C-ext" — bump it up the template table from Phase 1.

---

## Phase 6: End-to-end test

Before shipping, prove the wheel actually loads and works on a real device/simulator/emulator.
The runner is **committed in this repo**: `tests/recipe-tester/` — the same app CI uses for its
mobile tests, driven by `stage_recipe.sh`. There is nothing to copy or scaffold; your recipe's
`tests/` directory (written in Phase 3.3) IS the test payload.

**Quick version** (full loop, gotchas, and emulator/simulator setup live in the
`local-recipe-testing` skill — use it for anything beyond this happy path):

```bash
# From the repo root — stages recipes/<name>/tests/ into the app and
# generates its pyproject.toml pinning the recipe under test:
./tests/recipe-tester/stage_recipe.sh <name>
cd tests/recipe-tester

# Android (needs a running emulator):
PIP_FIND_LINKS="$(realpath ../../dist)" \
  uvx --with flet-cli flet build apk --arch arm64-v8a --yes
adb install -r build/apk/recipe-tester.apk
adb shell monkey -p com.flet.recipe_tester -c android.intent.category.LAUNCHER 1
# …then pull /data/data/com.flet.recipe_tester/cache/console.log and
# grep for '>>>>>>>>>> EXIT 0'

# iOS Simulator (needs a booted sim; use an explicit UDID if several exist):
PIP_FIND_LINKS="$(realpath ../../dist)" \
  uvx --with flet-cli flet build ios-simulator --yes
xcrun simctl install booted build/ios-simulator/recipe-tester.app
xcrun simctl launch booted com.flet.recipe-tester
# …then grep the app container's Library/Caches/console.log
```

`PIP_FIND_LINKS` pointing at `dist/` is what makes the app bundle YOUR freshly-built wheels
instead of pypi.flet.dev's — don't skip it. `tests/recipe-tester/README.md` documents the
runner itself (EXIT sentinel, `tests/requirements.txt` handling, what's committed vs
generated).

`>>>>>>>>>> EXIT 0 <<<<<<<<<<` in console.log on both platforms = ready to ship.

### Wheel hygiene checklist (before commit)

Unzip the wheel(s) from `dist/` and inspect every native binary:

- **Android, per ABI:**
  - `llvm-readelf -h` → `Machine` matches the ABI (`AArch64` for arm64-v8a, etc.). An x86_64 wheel carrying e_machine 183 (AArch64) means another slice's build leaked in — the per-slice build-dir rule was violated (onnxruntime CI round 1).
  - `llvm-readelf -l` → every `LOAD` segment has align `0x4000` (the 16KB rule). Applies to prebuilt/repackaged `.so`s too.
  - `llvm-readelf -d` → `DT_NEEDED` is minimal: bionic libs (`libc`/`libm`/`libdl`/`liblog`), `libc++_shared.so`, `libpythonX.Y.so`, plus only libs shipped in-wheel or via a declared flet-lib dep. Anything else will fail to resolve on device.
- **iOS, per slice:**
  - `otool -L` → system libraries only (anything else needs the ctypes/.fwork delivery story).
  - `otool -l | grep -A4 LC_BUILD_VERSION` → `platform 2` on device slices, `platform 7` on simulator slices, with a sane `minos` (onnxruntime: 13.0 device; upstream flooring the sim at 14.0 vs the 13.0 tag is cosmetic).
- **METADATA:** `Requires-Dist` promotion is correct — forge promotes ONLY `flet-*`-prefixed `requirements.host` entries (bare versions become `==`, ranges pass through); `requirements.host_build` deps absent; other runtime deps (e.g. numpy) must come from the project's own `install_requires`.
- **Wheel layout matches upstream's**, file-for-file where possible (tflite ships upstream's exact 5-file `tflite_runtime/` layout) — downstream code and docs written against the PyPI package should Just Work.
- **Bounded `-j` everywhere.** Never let a sub-make run a bare `-j` (unlimited jobs): sherpa-onnx's ~228 simultaneously-ready TUs OOM'd the 4-vCPU/16GB swap-less CI runner — leaving `SHERPA_ONNX_MAKE_ARGS` unset picked upstream's bounded `make -j4`, and the PEP 517 shims use `-j{os.cpu_count()}`. Related tell: `{CPU_COUNT}` exists only for build.sh recipes — in a `PythonPackageBuilder` `script_env` it KeyErrors at format time.

---

## Phase 7: Ship the branch

```bash
# Branch from main, the active dev branch
git checkout main
git pull
git checkout -b <name>          # or machine/<name> for agent-driven batches

git add recipes/<name>/
git status   # confirm no other files crept in
git diff --cached --stat

git commit -m "recipes: <package> <version>

<one paragraph explaining the recipe shape, any patches applied, and notable
gotchas — mirror the style of recent commits (git log --oneline -10).>"

git push -u origin <name>
```

The build artifacts in `dist/` are gitignored — only the recipe files (in `recipes/<name>/`)
end up in the commit.

**CI:** for a self-sufficient single recipe, the push itself triggers the full correct
matrix — do NOT also dispatch. For chain recipes (an unpublished `flet-lib*` dep, or two
recipes in one branch where one's `Requires-Dist` names the other), you need
`[skip ci]` + a dispatch with `prebuild_recipes`. The decision tree, dispatch inputs, and
failure triage all live in the sibling `forge-ci` skill — use it for everything from here on.

Whether and when the branch becomes a pull request is the maintainer's call — stop at the
pushed branch unless explicitly told otherwise.

---

## Pointers to bundled files

- `references/recipe-patterns.md` — every recipe shape with full meta.yaml + when to use each
- `templates/meta-*.yaml` — copy-paste-ready meta.yaml starters
- `templates/build-flet-lib.sh` — autotools cross-compile template for **static** `flet-lib*` recipes (linked into a C extension)
- `templates/build-flet-lib-shared.sh` — **shared**-library template for ctypes-loaded `flet-lib*` (Pattern H: pyzbar→libzbar etc.)
- `templates/test_template.py` — smoke test scaffold (follows the repo test conventions)
- `scripts/preflight.sh` — env verification
- `scripts/install_ndk_r27d.sh` — robust NDK r27d installer
- `scripts/verify_render.py` — Jinja meta.yaml render check
- shipped ML-wave archetypes (fork branches; read via `git show <branch>:<path>`): `machine/onnxruntime` + `machine/tflite-runtime` (PEP 517 shim), `machine/sherpa-onnx` (prebuilt-repackage + host_build chain incl. `flet-libonnxruntime`), `machine/onnx-insightface` (scikit-build-core + host-protoc), `machine/scikit-image` + `machine/h5py` (meson lanes, build.sh lib chain)

Sibling skills (each fact lives in exactly one place — follow the pointer instead of duplicating):
- `local-recipe-testing` — the on-device loop in detail (emulator/simulator setup, console.log retrieval, its 10+ gotchas)
- `forge-ci` — push vs dispatch, prebuild_recipes chains, run triage
- `forge-error-catalogue` — concrete build-error → fix mappings (50+ catalogued failures)
- `native-recipe-bumps` — bumping existing `flet-lib*` versions

Also relevant in the parent project:
- `MOBILE_FORGE_GUIDE.md` (at repo root) — full architecture overview and reference
- `tests/recipe-tester/README.md` — the committed test-runner app's own docs
- `src/forge/build.py`, `src/forge/cross.py` — the forge source; read these when a recipe builds in a way that surprises you
