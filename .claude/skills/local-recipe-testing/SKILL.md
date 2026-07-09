---
name: local-recipe-testing
description: Run a mobile-forge recipe's wheel ON-DEVICE locally — Android emulator and/or iOS simulator — instead of waiting ~1 hour for a CI mobile-test cycle. Covers the recipe-tester app loop (build wheel → stage → flet build → install → read console.log), and the non-obvious gotchas that each cost a wasted cycle: use forge's stripped dist/ wheel, build the recipe against the SAME Python flet bundles, clear flet's build cache between rebuilds, use a rootable (google_apis, not playstore) arm64 AVD to read the app-private console.log (it's in the app's cache/ dir), give the emulator enough RAM/disk, build ALL THREE iOS slices before `flet build ios-simulator`, use explicit simulator UDIDs when more than one sim is booted, and verify the staged-test COUNT so a silently-failed staging can't replay stale tests as false passes. Also covers forge slice syntax, bundling model assets next to recipe tests, test-only deps via tests/requirements.txt, desktop pre-validation via a sys.modules alias shim, and consumer verify-apps for beyond-pytest validation. USE THIS SKILL when iterating on a recipe's on-device behaviour (import works? functions run? crashes?), reproducing or debugging a CI mobile-test failure locally, or whenever someone says the CI mobile test is too slow to iterate on. Sibling of `new-mobile-recipe` (authoring), `forge-ci` (CI runs), `forge-error-catalogue` (build errors), and `native-recipe-bumps` (version bumps); this one is specifically the fast on-device validation loop. macOS + Apple Silicon assumed (the host this was developed on).
---

# Testing a mobile-forge recipe locally

CI mobile-test cycles take **~1 hour**, especially for heavy Rust recipes. The whole loop runs locally in minutes once set up. This skill encodes the loop and the traps — every gotcha below cost at least one wasted cycle to discover (during the `polars` recipe).

The runner is `tests/recipe-tester/` (a generic Flet app that runs a recipe's pytest files on-device and writes the result to `console.log`). See its `README.md` for the canonical commands; this skill adds the hard-won operational detail.

## What local testing CAN and CANNOT validate

| Want to check | Local (Apple Silicon) | Why |
|---|---|---|
| `import <pkg>` works on-device, functions run, native `.so` loads | ✅ arm64 emulator / iOS sim | arm64 is the real phone target — and CI only ever tests x86_64 android, so this is *additional* coverage |
| Build / compile / link errors | ✅ `forge` + `cargo tree`, seconds–minutes | no device needed |
| **x86_64-specific** behaviour (notably the **android x86_64 seccomp `open(2)`** kill) | ❌ | Apple Silicon emulators run arm64 images; arm64 has no `open(2)` syscall. Reproduce on CI, or reason via `cargo tree` / `llvm-readelf` |
| Full matrix (3 pythons × 2 platforms × all arches) | ❌ use CI | local is one slice at a time |

Rule of thumb: **iterate locally, confirm on CI.** Local gets you to a confident fix fast; CI is the authoritative multi-arch/x86_64 sign-off.

## The loop

```bash
REPO=/path/to/mobile-forge ; cd "$REPO"
SDK="$HOME/Library/Android/sdk" ; ADB="$SDK/platform-tools/adb"

# 1. Build the wheel for the slice you want to test (see gotcha #2 re: Python version)
export NDK_HOME=$HOME/ndk/r27d
source ./setup.sh 3.12.13              # MUST match flet's bundled python (gotcha #2); takes ONLY the python version
forge android:arm64-v8a <recipe>       # single arch = fast ; iOS needs ALL 3 slices — see the iOS loop below

# 2. Stage the recipe's tests + a clean find-links dir with ONLY the stripped wheel (gotcha #1)
rm -rf /tmp/rt_dist && mkdir /tmp/rt_dist
cp dist/<recipe>-*-android_24_arm64_v8a.whl /tmp/rt_dist/   # forge's dist/ wheel = STRIPPED
./tests/recipe-tester/stage_recipe.sh <recipe> <version>

# 3. Clear flet's stale bundle (gotcha #3), then build the app
rm -rf tests/recipe-tester/build/site-packages tests/recipe-tester/build/.hash
cd tests/recipe-tester
PIP_FIND_LINKS=/tmp/rt_dist uvx --with flet-cli flet build apk --arch arm64-v8a --yes
cd "$REPO"

# 4. Boot the rootable AVD (gotcha #4/#5), install, launch
"$SDK/emulator/emulator" -avd recipe_tester_root -no-window -no-snapshot -no-audio -gpu swiftshader_indirect &
"$ADB" wait-for-device && for i in $(seq 1 50); do [ "$("$ADB" -e shell getprop sys.boot_completed 2>/dev/null|tr -d '\r')" = 1 ] && break; sleep 3; done
"$ADB" root
"$ADB" uninstall com.flet.recipe_tester 2>/dev/null   # gotcha #7: clear STALE extracted site-packages
"$ADB" install tests/recipe-tester/build/apk/recipe-tester.apk
"$ADB" shell am start -n com.flet.recipe_tester/.MainActivity   # am start, NOT monkey (monkey was flaky)

# 5. Read the result (root → readable). Heavy native imports take 30–90s.
sleep 80
"$ADB" shell "cat /data/data/com.flet.recipe_tester/cache/console.log"   # CACHE dir, NOT files/flet/app/ (gotcha #9)
# look for: ">>>>>>>>>> EXIT 0 <<<<<<<<<<" and "N passed"
```

## The iOS-simulator loop

Simpler than Android — **no root needed**, the host filesystem reads the app container directly. Validated end-to-end during the onnxruntime iOS spike.

```bash
# 1. Build ALL THREE iOS slices, not just the one the sim runs (gotcha #10)
source ./setup.sh 3.12.13              # same python-match rule as gotcha #2
forge iphoneos:arm64 <recipe> ; forge iphonesimulator:arm64 <recipe> ; forge iphonesimulator:x86_64 <recipe>
# (a flet-lib* host dep needs all three slices too)

# 2. Stage + clear flet's cache (gotchas #1/#3 apply unchanged), then build the app
./tests/recipe-tester/stage_recipe.sh <recipe> <version>
rm -rf tests/recipe-tester/build/site-packages tests/recipe-tester/build/.hash
cd tests/recipe-tester
PIP_FIND_LINKS="$(realpath ../../dist)" uvx --with flet-cli flet build ios-simulator --yes

# 3. Boot any available iPhone sim, install, launch — ALWAYS by explicit UDID
#    (gotcha #11: `booted` is ambiguous the moment two sims are booted)
UDID=$(xcrun simctl list devices available | grep -m1 iPhone | grep -o '[0-9A-F-]\{36\}')
xcrun simctl boot "$UDID" 2>/dev/null ; xcrun simctl bootstatus "$UDID" -b
xcrun simctl uninstall "$UDID" com.flet.recipe-tester 2>/dev/null   # gotcha #7's iOS twin
xcrun simctl install "$UDID" build/ios-simulator/recipe-tester.app
xcrun simctl launch "$UDID" com.flet.recipe-tester
# NB bundle id: iOS uses a DASH (com.flet.recipe-tester); android package an UNDERSCORE (com.flet.recipe_tester)

# 4. Poll for the sentinel — the container is host-readable, no fixed sleep needed
DATA=$(xcrun simctl get_app_container "$UDID" com.flet.recipe-tester data)
for i in $(seq 1 30); do grep EXIT "$DATA/Library/Caches/console.log" 2>/dev/null && break; sleep 5; done
```

### forge slice syntax (quick reference)

`android:arm64-v8a` | `android:x86_64` | `android:armeabi-v7a` | `iphonesimulator:arm64` | `iphonesimulator:x86_64` | `iphoneos:arm64` — the first token is the **SDK**, not the OS. `forge iOS:arm64` dies with a raw `KeyError: 'iOS'` (only the bare-platform forms `forge android` / `forge iOS` take the OS name, and those build every arch).

## Gotchas (each cost a cycle)

1. **Use forge's `dist/` wheel, NOT `build/.../target/wheels/`.** The latter is maturin's raw output — **unstripped**. For polars that meant a **1.27 GB** `.so` (vs 130 MB stripped); it blows up install space and may not load. forge strips + repacks into `dist/`. Always test the `dist/` wheel.

2. **Build the recipe against the SAME Python `flet build` bundles (3.12 for flet 0.85.x).** forge's Android Rust `.so` hard-links `libpythonX.Y.so` (`DT_NEEDED`) — so the **`abi3` wheel tag is misleading**; it still needs the matching `libpython` at `dlopen`. A 3.14-built wheel in a 3.12 app fails: `dlopen … libpython3.14.so` missing → the package reports its "binary missing" (e.g. polars `NameError: PySeries`). Verify with `llvm-readelf -d <so> | grep NEEDED`. If you only have a different support tree, you can retag a wheel for flet's python with `uvx --from wheel wheel tags --python-tag cp312 --abi-tag abi3 --remove <whl>`, but the underlying `libpython` link still has to match — so really, build on the right python.

3. **Clear `tests/recipe-tester/build/site-packages` + `build/.hash` between rebuilds.** `flet build` keys its skip-site-packages cache on the requirement *string*, not wheel content — so swapping a same-version wheel is silently ignored and it re-bundles the old `.so`. Tell-tale: the APK size doesn't change after you changed the wheel.

4. **Reading the app-private `console.log` on Android needs a rootable emulator.** `adb root` fails on `*_playstore` (production) images (`adbd cannot run as root`) and release APKs aren't `run-as`-able. Use a **`google_apis`** (non-playstore) image; on Apple Silicon pick **arm64-v8a** (x86/x86_64 android images don't run on M-series). A ready one exists: **`recipe_tester_root`** (android-34 google_apis arm64, 6 GB RAM + 6 GB data baked in). Recreate with:
   ```bash
   echo no | "$SDK/cmdline-tools/latest/bin/avdmanager" create avd -n recipe_tester_root \
     -k "system-images;android-34;google_apis;arm64-v8a" -d pixel --force
   cfg=$HOME/.android/avd/recipe_tester_root.avd/config.ini
   sed -i '' 's/disk.dataPartition.size=.*/disk.dataPartition.size=6144M/' "$cfg" 2>/dev/null || echo 'disk.dataPartition.size=6144M' >> "$cfg"
   sed -i '' 's/hw.ramSize=.*/hw.ramSize=6144/' "$cfg" 2>/dev/null || echo 'hw.ramSize=6144' >> "$cfg"
   ```
   (`aosp_atd` is rootable but headless — it can't run a Flet GUI app, so don't use it here.)

5. **Give the emulator RAM + disk.** A heavy `.so` (polars ~130 MB) + Python + the Flutter engine OOM-kills the app on a default AVD (`lowmemorykiller: Kill 'com.flet.recipe_tester'`). 6 GB RAM avoids it. The ~100–235 MB APK install needs a big `/data` (6 GB partition); if you hit `INSTALL_FAILED_INSUFFICIENT_STORAGE`, free space (uninstall old apps) or use a fresh AVD.

6. **`monkey` launch was unreliable (exits 251 without launching the app — bit again during sherpa-onnx validation); use `am start -n com.flet.recipe_tester/.MainActivity`.** And the recipe-tester GUI is intentionally informational only — the pass/fail is **only** in `console.log`, so a screenshot won't tell you the result.

7. **`adb uninstall` before install — `install -r` reuses the app's STALE extracted site-packages.** serious-python unpacks `libpythonsitepackages.so` into the app's data dir (`/data/user/0/<pkg>/files/flet/python_site_packages/`) on first run and reuses it across reinstalls. `adb install -r` keeps app data, so a new wheel is silently ignored on-device → phantom `ModuleNotFoundError` / old behaviour even though the new APK is correct. Always `adb uninstall com.flet.recipe_tester` (or `pm clear`) before installing. (This cost ~5 wasted on-device cycles debugging pyzbar.) Distinct from gotcha #3 (that's the *host*-side `flet build` cache; this is the *device*-side extraction cache.)

8. **For a ctypes-loaded native lib (Pattern H, e.g. pyzbar→libzbar): test the GENUINE forge wheel, don't retag it.** A pure-Python wrapper's wheel is platform-tagged (`cp3X-cp3X-android`) on purpose — that's what makes `flet build` pull the `flet-lib*` platform dep and surface its `.so` into `lib/<abi>/`. Retagging it to `py3-none-any` makes flet resolve it as a plain pure-Python dep and **drop the `flet-lib*` dep**, so the `.so` never reaches the APK and the loader fails with "Unable to find … shared library". Build the wheel against the right Python (3.12) instead of retagging.

9. **Android `console.log` lives in the app's CACHE dir — `/data/data/com.flet.recipe_tester/cache/console.log` — NOT under `files/flet/app/`** (that's the app code; `python_site_packages` is a SIBLING under `files/flet/`). Polling the wrong dir looks like "the app never wrote a result" and cost ~10 min during the sherpa-onnx validation. Root is still required to read it (gotcha #4): `adb root` then `adb shell cat …`, or `adb shell su 0 cat …` on a google_apis image.

10. **`flet build ios-simulator` resolves the `iphoneos` (device) wheel AS WELL as both simulator ones.** It configures pip for `iphoneos.arm64` + `iphonesimulator.arm64` + `iphonesimulator.x86_64` and needs a wheel for EACH — a partial local matrix fails with `No matching distribution found`. Build all three iOS slices first (for the recipe AND every `flet-lib*` host dep). CI never hits this because it dumps all of `dist/*.whl` into its find-links dir. (`flet build apk` needs only the one `--arch` slice — the asymmetry is iOS-only.) Long-standing gotcha; re-hit during the onnxruntime iOS spike.

11. **Two booted simulators make `simctl booted` ambiguous.** With more than one sim booted, `simctl install booted …` targets one device and your subsequent `get_app_container booted …` may query the OTHER — the app "isn't installed" / the container is empty despite a successful install. Use the explicit `$UDID` for every simctl call (as the loop above does); never rely on `booted` unless you've verified exactly one device is booted (`xcrun simctl list devices | grep -c Booted`).

12. **Verify the staged tests + the on-device test COUNT — staging can fail silently.** `stage_recipe.sh` wipes and re-stages `recipe_tests/`; if the invocation ever fails without you noticing (a scripted loop with a bad variable — zsh does NOT word-split unquoted `$VAR` like bash, so a `for r in $RECIPES`-style loop can pass the whole list as ONE argument), the PREVIOUS recipe's tests are still staged and run happily, reporting "N passed" for the wrong package. Two cheap checks after staging: `ls tests/recipe-tester/recipe_tests/` shows YOUR test files, and the "N passed" in console.log matches your recipe's test count. (Bit during the h5py→keras loop: the same 4 stale h5py tests "passed" three times.)

## Model assets & test-only deps

`stage_recipe.sh` copies **every** file in `recipes/<pkg>/tests/` into the app (`cp -r tests/. recipe_tests/`), so a model dropped next to the test file becomes an app asset. Two tiers:

- **Big models (MBs): drop next to the test locally; the test discovers it by presence and skips otherwise.** Precedent sherpa-onnx `silero_vad.onnx` (2.2 MB): `if not os.path.exists(model): pytest.skip("silero_vad.onnx not bundled")`. CI (no asset) skips; your local loop runs REAL inference. `.gitignore` has `recipes/*/tests/*.onnx` so the asset can never be committed (that would silently flip the CI skip into a real run and embed MBs in git history) — extend the pattern for other formats.
- **Tiny models (~KB): COMMIT them so CI runs real inference too.** Precedent tflite-runtime's 1 KB `dense_relu.tflite` (generated with desktop TF at a fixed seed, expected outputs asserted).

Test-only deps — packages the tests import that are NOT in the recipe's Requires-Dist (e.g. numpy) — go in `recipes/<pkg>/tests/requirements.txt`; `stage_recipe.sh` injects them into the generated tester `pyproject.toml` (merged to main, #98). Each must resolve for the MOBILE target: pure-Python from PyPI, or a recipe on pypi.flet.dev / seeded into `dist/`.

## Desktop pre-validation when no desktop wheel exists

Packages with no host wheel for your platform (tflite-runtime has no macOS wheel at all; onnxruntime does NOT need this — its desktop wheels install fine) can't `pip install` on the host, but the recipe's *pytest logic* can still be validated pre-device: alias an equivalent desktop module into `sys.modules` in a scratch runner, then run the recipe's test file against it. Precedent tflite-runtime (desktop TF provides the same API):

```python
import sys, types, tensorflow as tf
m = types.ModuleType("tflite_runtime"); i = types.ModuleType("tflite_runtime.interpreter")
i.Interpreter = tf.lite.Interpreter; m.interpreter = i
sys.modules["tflite_runtime"] = m; sys.modules["tflite_runtime.interpreter"] = i
# then: pytest.main(["recipes/tflite-runtime/tests/"])
```

This caught a genuine math bug in the tflite test before it ever reached a device. It validates numerics/test logic only — not the on-device loader path.

A second desktop-side method — the **device-emulating venv**: create a scratch venv containing ONLY the wheel's declared runtime deps (nothing else from your dev environment) and run the recipe tests there. This catches *hidden* runtime deps that a normal dev machine masks (keras's numpy backend eagerly imports scipy, which upstream's Requires-Dist omits — found exactly this way, fixed by patching the dep in).

## Beyond pytest: consumer verify-apps

The recipe-tester proves the wheel loads and its own tests pass. For recipes whose real payoff is a downstream consumer (onnxruntime → rapidocr/fastembed/insightface), write a tiny throwaway Flet app under `playground/` (gitignored) — e.g. `playground/<consumer>-emu-verify/` — that exercises the REAL end-to-end flow on the emulator/simulator: download the actual model, run actual inference, print results to the screen and to a log. Same build mechanics as the recipe-tester (`PIP_FIND_LINKS` at `dist/`, same install/launch/read loop). This is what proved FaceAnalysis (15MB model download + real detection matching desktop scores) and fastembed (real 67MB hub download) actually work under flet — a pytest smoke test can't cover that honestly because CI tests must stay network-free.

Note for consumers that are pure-python + sdist-only (insightface): they need no recipe and no wheel — the verify-app's pyproject declares `[tool.flet] source_packages = ["<name>"]` instead (see `new-mobile-recipe` § "When NOT to use").

## Triage when the in-app test fails

Read `console.log` first; if the app died without writing a result, pull logcat:
```bash
"$ADB" logcat -d | grep -iE "recipe_tester|SIGSYS|SECCOMP|SIGSEGV|lowmemorykiller|dlopen|cannot locate|libpython|DartWorker"
```
- `lowmemorykiller … Kill 'com.flet.recipe_tester'` → emulator RAM (gotcha #5).
- `SIGSYS / SYS_SECCOMP … system call 2` → a raw `open(2)`; x86_64-only (jemalloc is a classic culprit — see the polars recipe's allocator patch).
- `dlopen … libpythonX.Y.so` / `cannot locate` → Python-version mismatch (gotcha #2) or a missing `DT_NEEDED` lib.
- `NameError`/"binary missing" with the package's Python code in the trace → its native `.so` failed to load (usually #1 or #2).

## Cleanup

```bash
"$ADB" -e emu kill                                   # stop the emulator (leave the AVD)
# delete a scratch AVD if you made one:
"$SDK/cmdline-tools/latest/bin/avdmanager" delete avd -n <name>
```
