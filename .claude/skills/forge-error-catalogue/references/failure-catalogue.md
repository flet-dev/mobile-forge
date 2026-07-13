# Failure catalogue — error → fix mappings

Each entry: the error pattern (paste-search-friendly), why it happens, and what to do.

## Build-time failures

### `Cannot find cross-compiler ('/home/runner/ndk/r27d/toolchains/llvm/prebuilt/linux-x86_64/...')`

**Cause:** the Python Android support tarball has CI-runner paths baked into `_sysconfigdata__linux_.py`. CPython's `configure` records absolute `CC`/`CXX`/etc. paths at build time, and the upstream `python-build` repo builds on Linux CI with NDK at `/home/runner/ndk/r27d/`. On macOS local dev, those paths point nowhere.

**Fix — depends on the tarball's age.** python-build releases since 2026-06 (PRs #5/#8/#9) ship SELF-RELOCATING sysconfigdata: an injected `_mobile_forge_relocate_sysconfig()` rewrites the baked paths at import time (the `/home/runner` strings staying in the file is expected — don't grep-count them). Check with `grep -l _mobile_forge_relocate_sysconfig <sysconfigdata files>`:
- **Relocator present + error anyway** → the relocator found no NDK. Set `NDK_HOME` (or `ANDROID_NDK_HOME`), or install an NDK under `~/ndk/` / `~/Library/Android/sdk/ndk/`.
- **Relocator absent** → your extracted tree predates 2026-06 (`setup.sh` has pinned a fixed release since then). Don't patch it — delete `downloads/support/python-android-*` and re-run `source ./setup.sh <python-version>` to fetch the current tarball.

**Doesn't apply to iOS** — the iOS support tarball uses CPython's modern Apple toolchain which writes platform-config files at run-time, no path baking.

---

### `Invalid configuration 'arm64-apple-ios': machine 'arm64-apple' not recognized`

**Cause:** the project ships an old `config.sub` that doesn't recognize Apple's mobile triplets. Affects autotools-based native libraries.

**Fix:** write a `patches/config.patch` to add `arm64`, `aarch64`, and `ios-simulator*` cases. Canonical patch in `recipes/flet-libxml2/patches/mobile-2.15.x.patch`. The minimal addition:

```diff
--- a/config.sub
+++ b/config.sub
@@ -1245,6 +1245,9 @@ case $os in
     linux-android* | linux-musl* | ...)
         ;;
+    ios-simulator*)
+        kernel=ios; os=$basic_os
+        ;;
     ...
```

If upstream's `config.sub` is recent (timestamp 2020+), it usually handles `*-apple-ios` natively but still rejects `*-apple-ios-simulator`. Patch only the simulator case.

---

### `configure: error: unable to link against -lpthread` (Android, autotools)

**Cause:** Android bionic folds pthread into libc — there's no separate
`libpthread`. autotools projects that probe for `-lpthread` fail the link test.

**Fix:** `./configure ... --disable-pthread` (zbar's own error message suggests
it). Synchronous/single-threaded library use doesn't need it. If the project has
no such flag, set `ac_cv_lib_pthread_pthread_create=yes` in the environment so
the check passes (pthread symbols resolve from libc at link time anyway).

---

### `call to undeclared function 'iconv_open'` / `iconv` (Android, autotools build)

**Cause:** Android bionic only exposes `iconv()` at **API ≥ 28**, and its
`<iconv.h>` hides the declarations behind `__ANDROID_API__ >= 28`. We target API
24. A C source that uses iconv *unconditionally* (e.g. zbar's `qrdectxt.c`) then
fails to compile/link. configure may correctly detect "no iconv" yet the source
uses it anyway.

**Two fixes, by ecosystem convention:**
- **If the project has a `--without-iconv` flag and the feature is optional**
  (libxml2, libxslt) — use it. This is the dominant flet pattern.
- **If iconv is mandatory** (zbar's QR text decoder) — provide it via the
  **`flet-libiconv`** recipe (GNU libiconv, static). Its `opt/include` is placed
  ahead of the NDK sysroot, so its `<iconv.h>` (which declares `libiconv_open`
  etc. and `#define`s `iconv_open libiconv_open`) wins, and `libiconv.a` is
  folded into the consumer's `.so`. Add it Android-only: `requirements.host:
  [flet-libiconv 1.17]` under `# {% if sdk == 'android' %}`, and configure with
  `--with-libiconv-prefix=$PLATLIB/opt`. iOS ships a system iconv — not needed.

---

### `clang: error: no such file or directory: '.../libX.N.dylib'` / libtool versioned dylib (iOS, autotools)

**Cause:** libtool's darwin shared-library path breaks under cross-compile — it
tries to emit a *versioned* `libX.N.dylib` into the not-yet-existing install dir.

**Fix:** build **static**, then hand-link the shared dylib from the archive:

```bash
./configure --host=$host --prefix=$PREFIX --enable-static --disable-shared ...
make -j $CPU_COUNT && make install
cd "$PREFIX/lib"
$CC $CFLAGS -shared -Wl,-all_load libX.a -l<deps> \
    -install_name @rpath/libX.so -o libX.so
rm -f libX.a
```

`-all_load` pulls in every archive object; `@rpath` install_name lets
serious-python embed it as a framework. Name it `.so` so serious-python's
`*.so`→framework conversion picks it up. (Also recall iOS autotools needs the
config.sub Darwin-triplet rewrite — see the `Invalid configuration` entry.) Real
example: `recipes/flet-libzbar/build.sh` iOS branch.

---

### `fatal error: '<header>.h' file not found`

**Cause:** a C/C++ header from a system library is missing. The header is supposed to come from a peer-built `flet-lib*` recipe via `requirements.host`.

**Fix:** find which flet-lib provides the header, add it as a host requirement.

```bash
# Search the recipes/ directory
grep -rln '<missing-header>' recipes/flet-lib*/build.sh
# Or check what flet-libX installs
find recipes -name 'meta.yaml' | xargs grep -l '<library-name>'
```

If no recipe provides it, that's a missing prerequisite — write a `flet-lib*` recipe first using `templates/meta-flet-lib.yaml` + `templates/build-flet-lib.sh`.

---

### `ld: library not found for -lXXX` (iOS)

**Cause:** linker can't find a library. Either the host dep wasn't installed into the crossenv, or upstream's `setup.py` is using a library name without -L pointing at where it lives.

**Fix:** check `requirements.host` includes the right `flet-lib*` recipe. If it does, check the build's compile_env log (top of the build log, debug=True lines) — confirm `-L<install_root>/lib` is in `LDFLAGS`.

If upstream hardcodes `-L/usr/lib/X` somewhere, write a `mobile.patch` to strip that path.

---

### `ImportError: dlopen failed: library "/abs/path/.../libpython3.12.so" not found` (Android, at runtime)

**Cause:** The Android `libpython3.12.so` from the `flet-dev/python-build` tarball is built without a SONAME (no `-Wl,-soname,libpython3.12.so` at libpython link time). When a recipe uses CMake's `target_link_libraries(... Python::Python)` to link explicitly against libpython (which pyzmq does on Android via `EXTRA_PYTHON_COMPONENT=Development.Embed`), the linker can't use a SONAME and falls back to using the input argument as DT_NEEDED. With `-DPython_LIBRARY=<absolute path>`, that path gets embedded verbatim. At runtime, Android's loader looks for the absolute build-host path and fails.

**Symptoms:**
- `unzip -p <wheel> ... | llvm-readelf -d` shows `(NEEDED) Shared library: [/Users/.../python-build/.../libpython3.12.so]` (absolute path)
- App crashes at first import with the long-absolute-path error

**Fix (one-time per python-build tarball extraction):**

```bash
source venv3.12/bin/activate
pip install patchelf  # bundles the binary as a Python package

for so in playground/python-build/android/install/android/*/python-3.12.12/lib/libpython3.12.so; do
    patchelf --set-soname libpython3.12.so "$so"
done

# Verify
/path/to/ndk/.../bin/llvm-readelf -d <one-libpython.so> | grep SONAME
# Expected: SONAME) Library soname: [libpython3.12.so]
```

After this, rebuild the recipe with `forge --clean android <pkg>`. The new pyzmq wheel will have `(NEEDED) Shared library: [libpython3.12.so]` — just the SONAME, no path. Android's loader finds it because gradle's `copyOpt_<abi>` task surfaces libpython into `jniLibs/<abi>/`.

**Long-term fix:** patch `flet-dev/python-build/android/build.sh` to pass `-Wl,-soname,libpython3.12.so` during the libpython link, so future tarballs ship with SONAME baked in. The local patchelf workaround makes this transparent.

Only Python-build-tarball-side recipes hit this — recipes that don't link libpython (Rust packages like orjson, jiter, and most C-extension recipes that use only `Development.Module`) are unaffected.

---

### `unable to find library -lstdc++` (Android)

**Cause:** old NDK versions had a `libstdc++` symlink for libc++; newer NDKs (r25+) removed it. Upstream `setup.py` uses `-lstdc++` directly.

**Fix:** depends on whether you actually need C++ or it's vestigial. Two options:

1. **Patch** to swap `-lstdc++` → `-lc++_shared` in upstream `setup.py`.
2. **Override via script_env** if the upstream supports an env var:
   ```yaml
   build:
     script_env:
   # {% if sdk == 'android' %}
       LDFLAGS: '-lc++_shared'    # appended to base LDFLAGS
   # {% endif %}
   ```

Note: NDK r27d's clang actually accepts `-lstdc++` silently (treats as alias for libc++). So this failure is less common on r27d than on r25-26. If you hit it, you may be on a non-pinned NDK version.

---

### iOS `lipo: ... have the same architectures (arm64) and can't be in the same fat output file` (silent during build, observed during `flet build ios-simulator`)

**Cause:** CMake on iOS doesn't auto-honor forge's cross-compile environment. When a recipe uses CMake/scikit-build-core/scikit-build, setting `CC=x86_64-apple-ios-simulator-clang` and friends via `compile_env` isn't enough — CMake auto-detects the macOS host arch and silently produces native-arch (arm64 on Apple Silicon) binaries even when targeting `x86_64-sim`. The build "succeeds", the wheel gets tagged correctly, but the embedded `.so` has the wrong arch.

**The failure is silent until app build time.** serious-python's iOS xcframework wrap then runs `lipo -create <arm64-sim>.so <x86_64-sim>.so` — and lipo refuses because both inputs are arm64. The lipo error scrolls past during `flet build`; the xcframework wrap fails for that recipe; the final `.app` is missing `Frameworks/<dotted-name>.framework/`, and the app crashes at `import` with `dlopen ... (no such file)`.

**Symptoms:**
- `file <wheel>/.../*.so` reports the wrong arch (e.g., `Mach-O ... arm64` for an x86_64-tagged wheel)
- App bundle is missing the expected `Frameworks/<package>.framework/` dir
- Device error: `dlopen(... Frameworks/<dotted-name>.framework/<dotted-name>, ...) ... no such file`

**Fix:** add explicit iOS cross-compile CMake args. Mirrors the Android toolchain-file pattern.

```yaml
build:
  script_env:
# {% if sdk == 'android' %}
    CMAKE_ARGS: ... (Android-specific, see other entries)
# {% else %}
    # iOS: tell CMake the target SDK + arch + deployment target explicitly.
    # CMAKE_SYSTEM_NAME=iOS triggers cross-compile mode (CMAKE_CROSSCOMPILING=TRUE).
    # CMAKE_OSX_SYSROOT={{ sdk }} → 'iphoneos' or 'iphonesimulator' (Jinja).
    # CMAKE_OSX_ARCHITECTURES={{ arch }} → 'arm64' or 'x86_64' (Jinja).
    # CMAKE_CROSSCOMPILING_EMULATOR=env satisfies CMP0190 (CMake 3.30+).
    # CMAKE_FIND_ROOT_PATH_MODE_{LIBRARY,INCLUDE}=BOTH lets find_library look
    # outside the SDK sysroot (needed for ZMQ_PREFIX, OPENSSL_DIR, etc.).
    CMAKE_ARGS: -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT={{ sdk }} -DCMAKE_OSX_ARCHITECTURES={{ arch }} -DCMAKE_OSX_DEPLOYMENT_TARGET={{ sdk_version }} -DCMAKE_CROSSCOMPILING_EMULATOR=env -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=BOTH -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH
# {% endif %}
```

**Verification before retesting:**
```bash
for whl in dist/<pkg>-*-ios_*.whl; do
    tmp=$(mktemp -d); unzip -q "$whl" -d "$tmp"
    so=$(find "$tmp" -name "*.so" | head -1)
    echo "$(basename "$whl"): $(file "$so" | grep -oE 'arm64|x86_64' | tail -1)"
    rm -rf "$tmp"
done
```

The reported arch must match the tag — `*-ios_13_0_x86_64_iphonesimulator.whl` must contain x86_64, not arm64.

**See also:** `references/recipe-patterns.md` § Pattern F (CMake/Meson) for the full scikit-build-core cross-compile template.

---

### iOS `flet build ios-simulator`: `Error (Xcode): Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be linked) in <pkg>.framework/<pkg>` (a CMake/scikit-build extension is an MH_BUNDLE)

**Cause:** serious_python's darwin packaging wraps **every** site-packages native
`.so` into a `.framework` binary that SwiftPM **links** (a `Package.swift`
`binaryTarget` the plugin target depends on). `ld` links only `MH_OBJECT`/
`MH_DYLIB`, so an extension that is an **`MH_BUNDLE`** aborts the app build. iOS
CPython's sysconfig sets `LDSHARED='...-dynamiclib -F . -framework Python'`, which
**setuptools / Cython / meson / maturin honor** (→ `MH_DYLIB`, pass); but
**CMake / scikit-build** link a Python `MODULE` with Apple's default `-bundle`
(→ `MH_BUNDLE`), *ignoring* `LDSHARED`. So the failing set is exactly the CMake
ones — **opencv (`cv2`), ncnn, coolprop, faiss (`_swigfaiss`)**, plus latent
sherpa_onnx/onnx. The flet-lib dependency is a **red herring** (cv2/ncnn link only
system `Accelerate`/`libc++`). Discriminate with `otool -hv <so>` (`BUNDLE` vs
`DYLIB`). (Note: **llama-cpp-python / pyarrow** iOS failure is a *different* bug —
interdependent SHARED dylibs, sp #223, which crashes at **launch** not build; see
the dedicated entry just below. Their libs are already dylibs, so this MH_BUNDLE
conversion is a no-op there.)

**Fix:** none per-recipe — **forge `fix_wheel` (build.py, iOS branch) converts each
`MH_BUNDLE` `.so` to `MH_DYLIB`** in place: inject an `LC_ID_DYLIB` load command
into the Mach-O header's free padding (bounded by the lowest `__TEXT` section file
offset — the `section_64.offset` field is at +48), flip the header `filetype`
`0x8`→`0x6` (and `ncmds`/`sizeofcmds`), then **ad-hoc re-sign** (`codesign --force
--sign -` — the header edit invalidates the linker signature). `dlopen` (the import
path) works on both filetypes so nothing regresses; serious_python's own
`install_name_tool -id` overwrites the placeholder `@rpath/<basename>` id. Generic
— rebuild and it catches every CMake extension with zero per-recipe CMake knowledge.
Per-recipe fallback (what onnxruntime/tflite/lightgbm did): force `-dynamiclib`
+ `-undefined dynamic_lookup` in the CMake link flags. **Validate** by `otool -hv`
= `DYLIB` + `otool -l | grep LC_ID_DYLIB` on the built wheel's `.so`, and that
`ld ... <so>` links (exit 0) where the original bundle gave the exact error above.
Verified: ncnn (real forge build → `MH_BUNDLE -> MH_DYLIB`, codesign ok) + cv2
(link test + iOS-sim app build past the `cv2.cv2.framework` link).

---

### iOS: app builds fine but **crashes at launch**, 0-byte `console.log` — `dyld: Library not loaded: @rpath/lib<X>.dylib, Referenced from: <app>.debug.dylib` (interdependent bundled dylibs, serious_python #223)

**Symptom:** the `.app` builds and installs, but on launch `console.log` is **0
bytes** (Flet rebinds stdout→console.log only after Python starts; pytest prints
"test session starts" *before* importing the recipe — so 0 bytes = crash BEFORE
Python). `simctl launch --console-pty` shows `dyld[…]: Library not loaded:
@rpath/lib<X>.dylib … Referenced from: …/recipe-tester.debug.dylib … tried
'…/Frameworks/lib<X>.dylib' (no such file)`. Recipes with a **chain of
interdependent native libs**: pyarrow (`libarrow`←`libarrow_compute`←
`libarrow_python`, plus every `pyarrow.*` C-ext), llama-cpp-python
(`libggml-base`←`libggml-cpu`←`libggml`←`libllama`).

**Cause:** serious_python framework-izes each site-package `.so`/`.dylib` into a
framework named by its **dotted relative path** (`opt/lib/libarrow.dylib` →
`opt.lib.libarrow.framework/opt.lib.libarrow`) and makes each a `Package.swift`
`binaryTarget` the plugin **links at launch**. But `create_xcframework_from_dylibs`
left every Mach-O **install-id** and interdependent **`@rpath` ref** at the
ORIGINAL bare name (`@rpath/libarrow.dylib`) — it ran `install_name_tool -id` only
for `ext=so`, never for `.dylib`, and never rewrote deps. So a bare
`@rpath/libarrow.dylib` resolves to `Frameworks/libarrow.dylib` (doesn't exist; the
file is inside `…framework/…`) → dyld can't link at launch. The recipe's ctypes
`.fwork` shim is **moot** here — it runs IN Python, after the crash. (Distinct from
the MH_BUNDLE build error above, and from the forge MH_BUNDLE→MH_DYLIB fix which is
necessary-but-not-sufficient.)

**Fix (serious_python, not per-recipe):** `reconcile_framework_install_names()` in
`serious_python_darwin/darwin/xcframework_utils.sh`, called from
`sync_site_packages.sh` after the `for _sp_ext in so dylib` conversion loop — sets
every framework binary's own install-id to `@rpath/<fw>.framework/<fw>` and rewrites
every dep matching a sibling's old-id to that framework path, then ad-hoc re-signs;
excludes the python/stdlib xcframeworks. Local sp branch `fix/soref-package-init`
commit **cc28d13** (UNPUSHED). **CI stays red for these recipes' iOS jobs until sp
is released** (published sp lacks it — same release-gating as apsw's SP `_SorefFinder`
fix). **Verified locally:** pyarrow 24.0.0 iOS-sim now launches, `4 passed`, `EXIT 0`
(was this exact dyld crash). Two bash gotchas bit while implementing it — the
`otool -D | head -1` SIGPIPE race (buffer to a var first) and zsh-vs-bash array
indexing in the *test harness* (real sp runs under bash). To verify an unreleased sp
change locally without a release: pubspec `dependency_overrides` path-dep the local
sp packages, build with the **local flet-cli** (`uv run --project .../flet/sdk/python
flet build ios-simulator --python-version 3.12`) not `uvx` (else
`SERIOUS_PYTHON_APP … must be set`), stage the recipe's CI wheels as `-9999` via
`PIP_FIND_LINKS`. Full recipe in the [[serious-python-223-framework-relocation]] memory.

---

### iOS: a flet-lib*'s native lib is silently absent from the app bundle

**Symptom:** `flet build ios-simulator` succeeds, but at runtime the consumer
can't find the native lib (e.g. ctypes "Unable to find … shared library"), and
the `.app` has no `Frameworks/*.framework` for it and no `opt/lib/*.fwork`.

**Cause:** serious-python's iOS xcframework merge uses **`iphoneos.arm64` as the
reference slice to *discover* `.so` files** to convert. If you built the flet-lib*
for only one slice (e.g. `iphonesimulator.arm64`), it's missing from
`iphoneos.arm64`, never discovered, never converted → absent from the bundle.

**Fix:** build the flet-lib* (and any per-slice-tagged Python wrapper) for **all
three iOS slices**: `forge iOS <flet-lib>` covers iphoneos.arm64 +
iphonesimulator.arm64 + iphonesimulator.x86_64. Confirm with
`ls dist/<lib>-*ios*` (expect 3 wheels) before `flet build`.

---

### Build succeeds but wheel can't be installed on device — `PT_LOAD alignment is X, expected >= 16384`

**Cause:** Android 15+ enforces 16 KB page alignment for native libs (Google Play requirement). `fix_wheel()` validates this and fails the build if any `.so` is misaligned.

**Fix:** forge sets `-Wl,-z,max-page-size=16384` in LDFLAGS automatically (`build.py:358`). If your recipe's `script_env.LDFLAGS` overrides without re-adding it, you've stripped the alignment flag.

Solution: append, don't replace.

```yaml
# WRONG — overwrites forge's default
build:
  script_env:
    LDFLAGS: '-lfoo -lbar'

# RIGHT — forge appends recipe LDFLAGS to base; alignment flag preserved
# (See build.py:444-449 — LDFLAGS/CFLAGS/CPPFLAGS get +=, other keys get =.)
build:
  script_env:
# {% if sdk == 'android' %}
    LDFLAGS: '-lfoo -lbar -Wl,-z,max-page-size=16384'
# {% endif %}
```

For CMake-driven builds, the `-Wl,-z,max-page-size=16384` won't reach the linker unless you forward it. Use `-DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384"` in `CMAKE_ARGS`. See `recipes/opencv-python/meta.yaml`.

---

### `ERROR: Dangerous symbolic link path was ignored` (during NDK install)

**Cause:** the `.dmg` Google ships for r27d contains lldb python bindings with relative symlinks that point upward out of the extract root. 7-zip flags them as dangerous and aborts the extract — `.ci/install_ndk.sh` then proceeds to `mv ... $NDK_HOME` against a non-existent dir, silently failing.

**Fix:** use the bundled installer instead — `bash .claude/skills/new-mobile-recipe/scripts/install_ndk_r27d.sh`. It passes `-snld` to 7-zip to skip those symlinks silently rather than abort. The lldb bindings aren't needed for cross-compile anyway.

If you already ran the broken installer and have a half-installed state at `~/ndk/r27d/`, the bundled installer detects the broken state and starts over.

---

### `ModuleNotFoundError: No module named 'setuptools_scm'` (or similar build dep)

**Cause:** upstream's `pyproject.toml::build-system.requires` lists a tool, but the package isn't on PyPI under the same name, or has an unusual version pin that pip can't resolve in the crossenv's build environment.

**Fix:** Add it explicitly to `requirements.build` in meta.yaml:

```yaml
requirements:
  build:
    - setuptools_scm[toml] >=3.4
    - setuptools >=77
```

This forces forge to pip-install them before invoking `python -m build`.

---

### Rust: `error[E0463]: can't find crate for 'core'`

**Cause:** the package pins a specific toolchain via `rust-toolchain.toml` (often
a nightly, e.g. polars). rustup auto-installs that *toolchain* but not the cross
*targets* for it; your `rustup target add …` only added them to stable.

**Fix:** add the mobile targets to the pinned toolchain:

```bash
rustup target add --toolchain <pinned-nightly> \
  aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios \
  aarch64-linux-android arm-linux-androideabi x86_64-linux-android i686-linux-android
```

(`rustup show` in the unpacked build dir prints the active toolchain.) Related:
Rust crates that vendor an autotools C lib (polars→tikv-jemalloc-sys) can hit the
config.sub iOS-triplet error from inside cargo — prefer a pure-Rust/alternative
allocator via a Cargo.toml patch (polars: route iOS/Android to mimalloc).

---

### `KeyError: '<version>'` while downloading a Python package's source

**Cause:** `PythonPackageBuilder` tried the PyPI sdist lookup and the version
isn't there — the package publishes **wheels only, no sdist** (e.g. pyzbar).

**Fix:** add a `source.url` pointing at a GitHub release/tag archive. forge's
PythonPackageBuilder honors it (downloads + unpacks + patches like normal):

```yaml
source:
  url: https://github.com/<org>/<repo>/archive/refs/tags/v{version}.tar.gz
```

See `references/recipe-patterns.md` § "Source layout".

---

### autotools: the GitHub release has no dist tarball (only a source archive)

**Cause:** GitHub's auto-generated `/archive/refs/tags/<v>.tar.gz` contains the
raw git tree — **no pre-generated `configure`** (only `configure.ac`). autotools
(`autoreconf`/`automake`) is **not on the forge build PATH**, so you can't
`autogen.sh`.

**Fix:** use the project's official **dist tarball** (which ships a built
`configure` + `Makefile.in`), not the GitHub archive. These live on the
project's release page or distro mirror — e.g. zbar's are on
`https://linuxtv.org/downloads/zbar/zbar-<v>.tar.bz2`. Verify before committing:
`tar tjf <tarball> | grep -E '/configure$'`.

---

### Build hangs or takes >10 minutes for a single small package

**Cause:** usually meson/cmake doing autoconfig probes, or a dependency rebuilding from sdist. Less commonly: the crossenv's pip is hitting `pypi.flet.dev` and getting redirected through Cloudflare cold-cache.

**Fix:** check the log live with `tail -f logs/<name>-<ver>-cp312-<slice>.log` (the build is in `logs/` while running, then moved to `errors/` on failure). If you see "Downloading X.tar.gz" lines, that's normal. If you see meson's "Checking for X..." lines for minutes, that's also normal for large packages (matplotlib, scipy).

If a build truly hangs (no log output for >2 minutes), Ctrl-C, then `forge --clean <slice> <name>` to retry from scratch.

---

### `relocation R_AARCH64_ADR_PREL_PG_HI21 cannot be used against symbol '…'; recompile with -fPIC`

**Symptom:** a C-extension links a **static** `flet-lib*.a` and the final
`-shared` link of the extension `.so` fails. Variants:
`R_AARCH64_ADD_ABS_LO12_NC`, `R_X86_64_PC32`, or plainly
`requires dynamic R_… relocation … against symbol; recompile with -fPIC`. The
error names a symbol `>>> defined in …/opt/lib/lib<X>.a(<obj>.o)`.

**Cause:** the native library compiled its **static** archive *without* `-fPIC`.
Many projects (PostgreSQL, etc.) build position-independent objects only for
their *own* shared lib (separate `*_shlib.o`) and leave the `.a` non-PIC. But
when that `.a` is folded into a Python extension — itself a **shared object** —
every archived object must be PIC.

**Fix:** in the flet-lib*'s `build.sh`, append `-fPIC` to the cross `CFLAGS`
*before* `configure`/`make` so the static archive is position-independent:

```bash
export CFLAGS="${CFLAGS:-} -fPIC"   # append; don't clobber the cross sysroot/16KB flags
```

Then `forge --clean <slice> flet-lib<X>` and rebuild the consumer. This is part
of Pattern I (recipe-patterns.md) — `recipes/flet-libpq/build.sh` is the worked
example.

---

### iOS: autotools lib fails with `use of undeclared identifier '<path-component>'`

**Symptom:** an autotools native lib compiles fine on Android but on an **iOS**
slice a C file errors with a burst of `use of undeclared identifier 'Users'`,
`'flet'`, `'playground'`, … — i.e. the *components of a filesystem path* parsed
as bare C tokens. (For PostgreSQL it's `src/common/config_info.c` compiling the
generated `CONFIGURE_ARGS` from `pg_config.h`.)

**Cause:** the build embeds raw `CFLAGS`/`LDFLAGS` into a **C string literal**
(so a tool like `pg_config` can report them). forge's **iOS** `LDFLAGS` contains
`-F "<framework path>"` with *literal double quotes* (the `-F` points at
`Python.xcframework/...`). The inner `"` terminates the string literal early, and
the path tail becomes naked identifiers. Android's `LDFLAGS` has no `-F "..."`,
so it never triggers.

**Fix:** the framework path has no spaces, so strip the quotes before
`./configure` (iOS branch only):

```bash
export LDFLAGS=$(printf '%s' "${LDFLAGS:-}" | tr -d '"')
```

Generalises to any autotools package that bakes flags into source (`*-config`
data, `--version` banners). See Pattern I and `recipes/flet-libpq/build.sh`.

---

### Rust: `error[E0432]: unresolved import std::sync::atomic::AtomicU64` (armeabi-v7a)

**Cause:** 32-bit ARM (`arm-linux-androideabi` / armeabi-v7a) has no native 64-bit
atomics, so std doesn't expose `AtomicU64` there. 32-bit x86 is fine (cmpxchg8b);
only armeabi-v7a hits it. Same whether the offending `AtomicU64` is in the
package's own code or a dependency.

**Two fixes:**
- **`excluded_arches: [armeabi-v7a]`** (package-level meta key) — when the crate
  needs `AtomicU64` pervasively / can't be patched / ships no 32-bit-ARM wheels
  upstream. Drops the arch. polars 1.33.0.
- **portable-atomic patch (keeps the arch)** — when usage is contained: add
  `portable-atomic = "1"` as a direct dep of the offending crate's `Cargo.toml`,
  and change `use std::sync::atomic::AtomicU64` → `use portable_atomic::AtomicU64`
  (`Ordering` stays std). portable-atomic ships a const-constructible 32-bit
  fallback, so `static X: AtomicU64 = AtomicU64::new(0)` still compiles; on 64-bit
  it uses native atomics. tokenizers 0.23.1 (`NEXT_CACHE_ID` in
  `src/models/bpe/model.rs`). **Tell:** you'll already see `Compiling
  portable-atomic` in the build — well-behaved deps route 64-bit atomics through
  it, so only the package's *own* raw `AtomicU64` is the offender.

---

### CMake `Could NOT find Python (missing: Interpreter Development.Module Development.Embed)` (cross-compile)

**Cause:** the recipe's CMakeLists does `find_package(Python COMPONENTS Interpreter
…)`, and `-DPython_EXECUTABLE` is pointed at `{prefix}/bin/python` — the
cross-compiled **target** binary (an Android ELF / iOS Mach-O), which can't run on
the build host. FindPython tries to exec it (even via the emulator) and drops
*all* components. Bit Python 3.12/3.13; 3.14 only passed by accidentally falling
back to the cross python on `PATH`.

**Fix:** point it at the host-runnable crossenv interpreter:
`-DPython_EXECUTABLE={CROSS_VENV_PYTHON}` (forge `script_env` var =
`<venv>/cross/bin/pythonX.Y`, a wrapper that runs the build python but reports the
*target* sysconfig), plus `-DCMAKE_CROSSCOMPILING_EMULATOR=/usr/bin/env`. (coolprop
sidesteps it — it only needs Development, not Interpreter.) pyzmq.

---

### `autoreconf: error: autopoint failed with exit status: 2`

**Cause:** the recipe `autoreconf`s an upstream that ships only `configure.ac`
(e.g. flet-libzbar from the zbar git archive — no release tarball), and its
`configure.ac` uses `AM_GNU_GETTEXT`, so `autoreconf` invokes `autopoint`, which
needs gettext installed. The build env didn't have it.

**Fix:** install the autotools + gettext in the build step —
`autoconf automake libtool gettext autopoint` (apt on Android; `brew install
autoconf automake libtool gettext` + put gettext's keg-only bin on `PATH` on the
macOS/iOS runner). Locally on macOS: `brew install autoconf automake libtool`.

---

### iOS: `ninja` pip package crashes importing (`sysconfig.get_preferred_scheme("user") → 'posix_user' … not valid`)

**Cause:** scikit-build-core imports the `ninja` pip package to locate ninja; its
`__init__` calls `sysconfig.get_preferred_scheme("user")`, which raises on the iOS
crossenv python (iOS has no user-site scheme). Android's ninja imports fine.

**Fix:** use the Makefiles generator on iOS so scikit-build-core never imports
ninja — `CMAKE_GENERATOR: Unix Makefiles` (iOS-gated; keep the Ninja generator on
Android). pyzmq. Same on plain-setup.py CMake drivers: pywhispercpp sets the same
iOS-gated `CMAKE_GENERATOR: Unix Makefiles` env var (faiss-cpu/duckdb precedent)
so setup.py never imports the ninja package; onnxruntime's iOS lane simply omits
`-GNinja` from its `FORGE_CMAKE_ARGS` (Makefiles is the default there).

---

### bundled autotools lib in a CMake recipe: `configure: error: cannot run C compiled programs / If you meant to cross compile, use '--host'`

**Cause:** a CMake recipe builds a bundled autotools sub-library whose `./configure`
tries to run a target binary on the host because no `--host` was passed. pyzmq's
libzmq bundles libsodium this way.

**Fix:** give configure a cross `--host` triple. pyzmq reads `CIBW_HOST_TRIPLET`:
`{HOST_TRIPLET}` on Android (forge env var, android-only) and `{{ arch }}-apple-ios`
on iOS. libsodium's `config.sub` accepts `aarch64`/`x86_64-apple-ios` but
**rejects** the `-simulator` suffix; `*-apple-ios` is always `!=` the macOS
`*-apple-darwin` build triple, so it always registers as cross. The real
simulator/device targeting is done by the iOS CC/`-isysroot`, not the triple.

---

### `call to undeclared library function 'cpow'` / `'clog'` (Android, Cython-generated `.c`)

**Cause:** bionic gates the C99 complex functions `cpow`/`clog` behind **API 26**
(`__INTRODUCED_IN(26)` in `<complex.h>`; `cexp`/`csqrt` are API 23 and fine), and
forge targets API 24 — only Android slices break, iOS/macOS declare them. Do NOT
"fix" by declaring the function or force-including `<complex.h>`: the symbol is
also absent from the API-24 libm link stub, so it just fails at LINK instead.
Two variants:

- **Variant A — accidental complex promotion:** a `.pyx` uses `**` with a
  float exponent; Cython 3's default `cpow=False` follows Python semantics
  (negative base to a fractional power → complex) and lowers `**` to C `cpow()`.
  **Fix:** the Cython directive **`cpow=True`** on the offending `.pyx` (append
  to its `# cython:` line via a patch) → `**` uses real `pow()`, no cpow emitted.
  Find offenders without a forge build:
  `uvx --from Cython cython -3 file.pyx -o out.c && grep 'define __Pyx_c_pow' out.c`.
  astropy (`recipes/astropy/patches/android-cython-cpow.patch`, android-gated —
  iOS builds clean).
- **Variant B — genuine fused-complex math:** the tell is that upstream's
  setup.py **already passes `cpow=True`** globally yet the regenerated `.c`
  still calls cpow (the `.pyx` is fused-typed over float/double AND complex, so
  `x ** phi` on complex operands is a real complex pow), and/or the package's
  own C source calls `clog`. **Fix:** a patch that **creates** a self-contained
  compat header defining static `cpow/cpowf/clog/clogf` from API-24-safe libm
  only (`clog = log(hypot) + i*atan2`; `cpow = e^(b·clog a)`), plus android-only
  `CPPFLAGS: -include <pkg>/src/bionic_complex_compat.h` in `script_env`
  (setuptools appends env CPPFLAGS to every compile; the path is relative to the
  build cwd). Verify the wheels: `llvm-readelf --dyn-syms *.so | grep cpow` must
  be EMPTY (the statics inline). statsmodels 0.14.6.

Debug trap: identical error line-offsets across rebuilds mean the stale
sdist-shipped `.c` was recompiled without regeneration from the `.pyx`.

---

### `fatal error: 'tensorflow/lite/delegates/xnnpack/macros.h' file not found` — superbuild self-clones its parent project

**Cause:** `-DTENSORFLOW_SOURCE_DIR` was left unset, so tensorflow/lite's CMake
**git-clones its own TensorFlow pinned at `GIT_TAG v2.19.0`** into the build dir
and compiles your 2.21 tree's sources against those stale headers (that macros.h
is new in 2.21). A missing-header error at a high build % with
version-suspicious paths is the signature.

**Tells:** `Downloading TensorFlow repository...` in the configure output;
`-I…/tensorflow-src` include paths (upstream overrides the FetchContent SOURCE_DIR — no `_deps/` component) in the target's `flags.make`.

**Fix:** pin `-DTENSORFLOW_SOURCE_DIR=<unpacked source root>` (the shim passes
`Path.cwd()`) at configure. Generalizes to any superbuild that FetchContents its
**parent project** when a source-dir cache var is unset. tflite-runtime
(`_forge/forge_tflite_backend.py`).

---

### setuptools: `could not create 'build/lib...': Not a directory` (macOS local build)

**Cause:** the source root carries a Bazel **`BUILD`** file, which collides with
setuptools' default `build/` directory on **case-insensitive** filesystems —
i.e. macOS local builds; Linux CI is unaffected, so this bites exactly when you
try to reproduce locally.

**Fix:** build somewhere else:
`setup(..., options={"build": {"build_base": ".forge_pybuild"}})`. tflite-runtime
(patch-added setup.py).

---

### `undefined symbol: TfLiteXNNPackDelegateCreate` (ld.lld, after setting `TFLITE_ENABLE_XNNPACK=OFF`)

**Cause:** tflite's `interpreter_wrapper.cc` calls
`TfLiteXNNPackDelegateOptionsDefault()` / `TfLiteXNNPackDelegateCreate()`
unconditionally — runtime-gated but **link-unconditional** — so the *python*
wheel cannot be built with XNNPACK off on ANY ABI. Upstream's own 32-bit-arm
`XNNPACK=OFF` convention predates that code and only works for the C++ library.

**Fix:** leave XNNPACK at its default (ON) everywhere, **including
armeabi-v7a** — it builds fine with NDK r27 (p4a shipped XNNPACK-on-v7a back at
TF 2.8). tflite-runtime.

---

### Build green but the wheel is KB-sized / missing its pybind `.so`

**Cause:** upstream `setup.py` keys its native-lib list on `platform.system()`,
and the crossenv reports `"Android"` / `"iOS"` — matching **no** upstream branch,
so the list stays unset and the extension module never enters the wheel. The
build "succeeds". (Termux hit the same on onnxruntime and hand-installs the .so
post-hoc; we fix the predicate instead.)

**Tell:** the wheel is KB not MB; `unzip -l dist/<pkg>-*.whl | grep '\.so'`
comes back empty.

**Fix:** patch the predicate to include the mobile values, keeping the Darwin
branch intact for real macOS builds:
`if platform.system() in ("Linux", "AIX", "Android", "iOS"):`. onnxruntime
`mobile.patch`.

---

### Wrong-arch code inside a wheel — `llvm-readelf` Machine/`e_machine` mismatch (e.g. AArch64/`e_machine 183` `.so` in an x86_64 wheel)

**Cause:** forge **reuses the unpacked source tree across arch slices** within
one invocation (only the first slice unpacks clean). Any build dir keyed
globally — a single `build/`, a done-marker at the source root — leaks slice 1's
arch state into slice 2: first slice fine, later slices ship the wrong
architecture's binaries.

**Fix:** key build dirs per slice — `ANDROID_ABI` on android,
`CMAKE_OSX_SYSROOT` + `CMAKE_OSX_ARCHITECTURES` on iOS (device/sim ×
arm64/x86_64) — and re-stage the python package **fresh on every PEP 517 hook**
so the current ABI always wins. onnxruntime's shim (`.forge_build/<key>`; caught
by CI round 1 poisoning the x86_64 wheel with arm64 code), inherited by
tflite-runtime. Same root-cause class as a recipe caching a per-arch artifact
under a global guard (ckzg's vendored libblst).

---

### Android wheel ships a dead `lib<pkg>-jni.so` (force-enabled component that can never work under flet)

**Cause:** upstream CMake **force-enables** a component on Android — sherpa-onnx
flips JNI ON whenever JNI and C_API are both OFF — yielding a 4 MB
`libsherpa-onnx-jni.so` in the wheel that can never work in a flet app (its Java
classes aren't dexed into the APK; the jpype1 reasoning).

**Fix:** patch out the force block, **after confirming nothing else depends on
it** — in sherpa's case the onnxruntime `install(FILES …)` rule is unconditional,
so dropping the block was safe.
`recipes/sherpa-onnx/patches/android-no-jni.patch`.

---

### CI android leg OOMs / thrashes to death — unbounded `make -j` from the recipe

**Cause:** a bare `-j` is **unlimited parallel jobs**. sherpa-onnx's
`SHERPA_ONNX_MAKE_ARGS=-j` would have had ~228 C++ TUs ready at once on the
4-vCPU/16GB ubuntu runner — whose free-disk-space step **deletes swap**.

**Fix:** bound it (`-j4`) or drop the var entirely and let upstream's default
run (sherpa's setup.py falls back to a bounded `make -j4`). **Related trap:**
`{CPU_COUNT}` is injected only for **build.sh** recipes
(`SimplePackageBuilder.compile`, build.py:997); in a PythonPackageBuilder
`script_env` it raises `KeyError: 'CPU_COUNT'` when forge `.format()`s the value
(build.py:576-580). sherpa-onnx (adversarial-review catch).

---

### CMake-driving setup.py keys its build tool on a literal `"-G Ninja"` substring

**Cause:** sherpa-onnx's `cmake/cmake_extension.py` decides make-vs-ninja with
`if "-G Ninja" in cmake_args:`. Pass `-GNinja` (no space) and CMake generates a
Ninja tree but setup.py then runs `make` in it; other spellings misfire the same
way.

**Fix:** for env-driven builds of this class, pass **no generator flag at all**
and let the upstream default run (Unix Makefiles + its bounded `make -j4`); put
everything else in the `SHERPA_ONNX_CMAKE_ARGS`-class env var, which setup.py
appends AFTER its own defaults so overrides win. sherpa-onnx.

---

### pybind11 v3 configure picks the HOST (Homebrew) python — crossenv ignored

**Cause:** pybind11 v3 (pip package or FetchContent'd at configure) uses CMake's
**new FindPython**; the legacy `-DPYTHON_EXECUTABLE` hint is **IGNORED**, so it
discovers the host/Homebrew interpreter instead of the crossenv. Symptom:
configure log prints a host python path; wrong headers/libs follow.

**Fix:** pass the full triple —
`-DPython_EXECUTABLE={CROSS_VENV_PYTHON}
-DPython_INCLUDE_DIR={HOST_PYTHON_HOME}/include/python{py_version_short}
-DPython_LIBRARY={HOST_PYTHON_HOME}/lib/libpython{py_version_short}.so`
(`.dylib` on iOS). For FetchContent'd pybind11, add
`-DPYBIND11_USE_CROSSCOMPILING=TRUE` (onnxruntime). pywhispercpp (first hit),
sherpa-onnx, onnxruntime. Complements the FindPython/`CROSS_VENV_PYTHON` entry
above (that one is about a target binary being exec'd; this one is about the
hint variable being silently dropped).

---

### forge CLI: `KeyError: 'iOS'` immediately at invocation

**Cause:** wrong slice syntax — e.g. `forge iOS:arm64`. The per-slice form takes
**SDK names**, not OS names: the CLI resolves `<sdk>:<arch>` through an SDK→OS
map that has no `iOS` key (`src/forge/__main__.py` OS_MAP).

**Fix:** valid hosts are the whole-OS forms `android` / `iOS`, or per-slice
`android:arm64-v8a`, `iphonesimulator:arm64`, `iphonesimulator:x86_64`,
`iphoneos:arm64` (optionally `sdk:version:arch`). onnxruntime-iOS spike.

---

### build.sh prebuilt-repackage: the archive's documented paths don't exist (`jni/<abi>/…` gone after unpack)

**Cause:** forge unpacks `source.url` archives with the **leading path component
of every member stripped** (`--strip-components=1` equivalent, build.py
`unpack_source`). An archive whose top level is several directories loses those
directories themselves — flet-libonnxruntime's zip (`jni/<abi>/libonnxruntime.so`
+ `headers/*.h`) lands as `<abi>/libonnxruntime.so` + `*.h` at the unpack root.

**Fix:** either address the stripped layout in build.sh
(`cp "$ANDROID_ABI/libonnxruntime.so" …; cp ./*.h …`, with a loud guard like
`"no libonnxruntime.so for ABI '$ANDROID_ABI' in the zip"`), or set
`source: strip: 0` in meta.yaml to keep the archive layout verbatim.
`recipes/flet-libonnxruntime/build.sh`.

---

### Host tool fetched for the wrong OS — `Exec format error` / `cannot execute binary file` (protoc, flatc, …)

**Cause:** under the crossenv, `platform.system()` returns the TARGET OS (`"Android"`
/ `"iOS"`), and `sys.platform`-style checks lie the same way. A PEP 517 shim that
picks a host-tool download by `platform.system()` fetches the linux binary onto a
macOS host (onnx's protoc shim, first run).

**Fix:** detect the build host by shelling out to the real `uname -s` (and `uname -m`
for arch), never via Python's platform module inside the cross build.
`machine/onnx-insightface:recipes/onnx/` `_forge` shim.

---

### CMake: `protobuf::libprotobuf` target never created / half-found host protobuf (onnx)

**Cause:** without `-DONNX_BUILD_CUSTOM_PROTOBUF=ON`, onnx's caffe2-style
`find_program`/`find_package` locates ANY host protoc (Homebrew) and enters a
half-found state — the imported protobuf targets are never created and configure
or link fails in confusing ways.

**Fix:** `-DONNX_BUILD_CUSTOM_PROTOBUF=ON` is MANDATORY when cross-compiling onnx —
it vendors protobuf as target-only libs, while codegen goes through the host protoc
you supply via `-DONNX_CUSTOM_PROTOC_EXECUTABLE`. `machine/onnx-insightface:recipes/onnx/`.

---

### CMake finds Python but a LATER `find_package(Python3 …)` (or `Python …`) still fails — dual FindPython families

**Cause:** CMake's FindPython has THREE independent hint families — `Python_*`,
`Python3_*`, and per-component SABI vars — and every `find_package` call in the tree
only reads its own family. onnx itself uses `Python3` (incl. `Development.SABIModule`,
which wants `Python3_SABI_LIBRARY`), while its vendored nanobind calls
`find_package(Python …)`.

**Fix:** pass BOTH full families: `Python_EXECUTABLE/INCLUDE_DIR/LIBRARY/SABI_LIBRARY`
AND `Python3_EXECUTABLE/INCLUDE_DIR/LIBRARY/SABI_LIBRARY`, all pointing at
`{CROSS_VENV_PYTHON}` / `{HOST_PYTHON_HOME}` paths (`.so` android, `.dylib` iOS).
Complements the pybind11-v3 entry above — same disease, more families.
`machine/onnx-insightface:recipes/onnx/meta.yaml`.

---

### nanobind: `fatal error: 'Python.h' file not found` (nanobind-static compile)

**Cause:** nanobind's static-lib target doesn't inherit the include dirs FindPython
resolved for the module target, so the cross Python headers never reach its compile
line.

**Fix:** inject globally:
`-DCMAKE_CXX_FLAGS=-I{HOST_PYTHON_HOME}/include/python{py_version_short}`. onnx.

---

### Android link: `undefined symbol: PyExc_…` with `--no-undefined` (CMake MODULE libs)

**Cause:** upstream links extension modules with `-Wl,--no-undefined` (onnx does),
so the usual leave-python-symbols-unresolved convention fails — the module must link
libpython explicitly. But the libpython flags are multi-token and forge's
`CMAKE_ARGS` is shlex-split, so `-DCMAKE_MODULE_LINKER_FLAGS=… -L… -lpython…` can't
be passed as separate tokens.

**Fix:** fold everything into ONE comma-joined `-Wl` token:
`-DCMAKE_MODULE_LINKER_FLAGS=-Wl,-z,max-page-size=16384,-L{HOST_PYTHON_HOME}/lib,-lpython{py_version_short}`.
The linker splits `-Wl` args on commas, dodging the single-token constraint. onnx.
iOS mirror-image: a wrapper with NO FindPython at all wants
`-Wl,-undefined,dynamic_lookup` instead (tflite-runtime iOS lane) — apple's two-level
namespace otherwise fails on the unresolved python symbols.

---

### meta.yaml schema: `None is not of type 'array'` on one platform only

**Cause:** a platform-gated dep was jinja-guarded at the ENTRY level under an
otherwise-empty key — on the other platform the key renders with no items and YAML
parses `host:` (or `patches:`, etc.) as `None`, failing schema validation on every
leg of that platform.

**Fix:** guard the whole KEY, not just the entry:

```yaml
# {% if sdk == 'android' %}
  host:
    - flet-libcpp-shared >=27.2.12479018
# {% endif %}
```

Entry-level guards are fine only when other entries keep the list non-empty.
onnx (3 iOS legs failed at render).

---

### meson: `ERROR: Tried to form an absolute path to a dir in the source tree` (numpy include)

**Cause:** forge unpacks the sdist with the cross venv INSIDE the source root, and
meson's `include_directories()` refuses absolute paths into the source tree. Any
project using the legacy numpy detection (`run_command(… numpy.get_include())` →
`include_directories(...)`) dies at configure — and upstream's
numpy-include-dir property hatch can't help, because the path itself is the problem.

**Fix:** patch to `dependency('numpy')` (meson ≥ 1.4 resolves it via `numpy-config`
on the cross venv PATH — this is why modern scipy never hits it). Extra include dirs
that must stay path-based (pythran) ride as plain `'-I' + path` compile args instead.
scikit-image `mobile.patch`.

---

### meson: `py3.install_sources` can't rename a file / pure-python file must land in platlib

**Cause:** two meson API gaps hit together when installing a `.py` file AS a
different module (e.g. a pythran source standing in for its compiled extension on
Android): `py3.install_sources()` has NO `rename:` kwarg, and installing into
purelib while the rest of the package is in platlib makes meson-python die on the
purelib/platlib split.

**Fix:** use `install_data(sources, rename: ['newname.py'], install_dir:
py3.get_install_dir(subdir: '<pkg>/<sub>', pure: false))` — `install_data` has
`rename:`, and `pure: false` keeps it in platlib. scikit-image (pythran modules as
pure-python drop-ins on Android).

---

### meson: `Compiler cannot compile programs` right after adding a `-include` CPPFLAG

**Cause:** the env-CPPFLAGS `-include <relative-path>` mechanism (fine for
setuptools — statsmodels precedent) breaks meson: its compiler SANITY checks run
from their own scratch dirs, where the relative path doesn't resolve, so meson
concludes the compiler itself is broken.

**Fix:** inject via the build files instead, with an absolute project path:
`add_project_arguments('-include', meson.project_source_root() / 'path/to/compat.h',
language: ['c'])` — android-gated, **C only** (`double complex` isn't C++; C++ TUs
use `std::complex`, and the header carries a `!__cplusplus` guard). scikit-image's
cpow compat header; see the cpow/clog entry above for the underlying bionic gap.

---

### build.sh recipe: `cmake: command not found` (exit 127)

**Cause:** `build.sh` recipes get only what `requirements.build` seeds into the
build env — unlike PEP 517 recipes there's no pyproject `build-system.requires` to
pull tools in, and the pip cmake shim is not present by default.

**Fix:** declare it explicitly in the flet-lib recipe:
`requirements.build: [cmake]` (add `ninja` if the script uses it). flet-libhdf5.

---

### `patch` fails mid-hunk / a file ends up with DUPLICATED content after patching

**Cause:** the patch file was regenerated by CONCATENATING a new `diff -ruN` onto an
existing one while the diff trees still held earlier edits — the same hunk appears
twice. `patch --dry-run` does NOT catch this (each duplicate validates independently
against the pristine tree); the second application then corrupts the file or fails
with fuzz.

**Fix:** always regenerate the WHOLE patch from clean `a/` vs edited `b/` trees, then
verify by REALLY applying it to a scratch unpack of the sdist and content-grepping
for one marker per hunk. keras `mobile.patch` (bit twice in one session).

---

### iOS CMake: `install TARGETS given no BUNDLE DESTINATION for MacOS bundle target "flatc"`

**Cause:** a FetchContent'd flatbuffers builds its `flatc` TOOL as part of the
target configure; on iOS CMake forces executables to be MACOSX_BUNDLEs, and
flatbuffers' install rule has no BUNDLE destination → configure/install fails. A
target-built flatc would be useless anyway (wrong arch to run).

**Fix:** `-DFLATBUFFERS_BUILD_FLATC=OFF -DFLATBUFFERS_INSTALL=OFF` on the iOS lane;
codegen runs through the separately-built host flatc (see the host-tools escalation
ladder in `new-mobile-recipe` § 3.6). tflite-runtime iOS.

---

### iOS/apple CMake: the built extension is a `.dylib` but the wheel needs a `.so`

**Cause:** on apple platforms `add_library(… SHARED)` emits `lib<name>.dylib`;
Python extension modules (and the wheel layout downstream tooling expects) want the
`.so` name. serious_python's iOS loader also keys on the `.so` name for its
`.fwork` framework-ization.

**Fix:** either set the target's `SUFFIX ".so"` in CMake (lightgbm precedent) or
have the PEP 517 shim stage the `.dylib` under the `.so` name when copying into the
package (tflite-runtime). Verify with `otool -h` that it's a real MH_DYLIB either way.

---

### iOS: `reference to 'Ptr' is ambiguous` (Apple `MacTypes.h` vs a `using namespace`'d C++ lib)

**Cause:** Apple's `<MacTypes.h>` (pulled in transitively on iOS/macOS) defines a
global `typedef char* Ptr;`. Any C++ TU that does `using namespace cv;` (or another
namespace exporting a `Ptr`) and then writes a bare `Ptr<T>` is ambiguous between
`::Ptr` and `cv::Ptr`. **iOS/macOS only** — Android has no `MacTypes.h`, so bare
`Ptr` binds to the lib's cleanly. opencv 5's python bindings hit this in hand-written
helper headers AND in gen2.py-**generated** code (e.g. `std::vector<Ptr<CChecker>>`).

**Fix:** qualify the offending names with `cv::`. Patch hand-written sources directly;
for generated code, patch the **generator** to emit qualified names — including `Ptr<`
**nested** inside other templates (a leading-only check misses `std::vector<Ptr<…>>`).
Same class covers bare `Size`/`Point`/`Rect`. opencv-python 5.0.0.93 `mobile.patch`
(`pyopencv_*`, `pycompat.hpp`, gen2.py `prefix_ambiguous_ios`).

---

### iOS/x86_64: `error: unknown target CPU 'armv8-a'` (an ARM NEON HAL built on the x86_64 simulator)

**Cause:** opencv 5 bundles **KleidiCV** (Arm's NEON HAL, `WITH_KLEIDICV` default ON).
Its NEON kernels pass `-mcpu=armv8-a`, which x86_64 clang rejects — the x86_64
iOS-sim (and android x86_64) slice tries to build ARM-only code.

**Fix:** `-DWITH_KLEIDICV=OFF` (perf-only HAL; opencv's own NEON still applies, and the
4.12 wheels never shipped it). opencv-python 5.0.0.93.

---

### iOS/x86_64: `invalid instruction mnemonic 'b'` (ARM asm compiled on the x86_64 simulator)

**Cause:** the recipe hardcoded `-DCMAKE_SYSTEM_PROCESSOR=aarch64` for **all** iOS
slices (fine for arm64 device/sim), so on the x86_64 simulator opencv still enabled
its ARM asm/NEON code paths and the assembler chokes on ARM mnemonics. Tolerated in
opencv 4.12; opencv 5's stricter arch-gated asm exposes it.

**Fix:** set `CMAKE_SYSTEM_PROCESSOR` **per-arch** on the iOS lane —
`{{ 'x86_64' if arch == 'x86_64' else 'aarch64' }}` (arm64 unchanged). Android gets the
right arch from the NDK toolchain, so it never needs this. opencv-python 5.0.0.93.

---

### iOS: Rust `error[E0432]: unresolved import 'internal'` / `cannot find module 'os'` (a crate with no `target_os="ios"` backend)

**Cause:** a platform-specific Rust crate (here `mac_address` 1.x, pulled in for v1/v6
UUID MAC nodes) selects a per-OS backend module but has **no `ios` one**, so its
`internal`/`os` module is empty → won't compile for any Apple-iOS target. Android /
linux / macos backends exist, so only the iOS slices break.

**Fix:** cfg-gate the dep OUT on iOS in `Cargo.toml`
(`[target.'cfg(all(…, not(target_os = "ios")))'.dependencies]`) AND gate its use-sites,
routing iOS to whatever fallback the code already has (uuid-utils' `_getnode()` already
falls back to a random node). Only viable when the dep is optional / has a fallback.
uuid-utils 0.17.0 `mobile.patch`.

---

## Runtime failures (on device/emulator/simulator)

### Flet 0.86 changed Android packaging — `sitepackages.zip` + jniLibs relocation (the umbrella behind a whole class of "worked under 0.85, fails now" on-device failures)

**Cause:** the recipe-tester migration to Flet 0.86 (flet-dev/flet#104) stopped
extracting site-packages to disk. Now, on **Android**:
- pure Python ships in a stored **`sitepackages.zip`** imported via `zipimport`;
- native extensions are **relocated into the APK's `jniLibs/<abi>/lib<mangled>.so`**
  and resolved by a `sys.meta_path` finder (`_sp_bootstrap._SorefFinder`) through a
  per-module **`.soref`** marker left in the zip — written **only** for filenames
  matching `\.(cpython-[^/]+|abi3)\.so$`;
- `opt/` trees from `flet-lib*` wheels are copied to `jniLibs` by `copyOpt`, which
  takes **only `**/*.so`** (non-`.so` data is dropped);
- packages are compiled to `.pyc` and the `.py` source is stripped (except the app,
  which sets `[tool.flet.compile] app = false`).

Under 0.85 site-packages was a real directory (the `useLegacyPackaging` extract), so
any loader/data-access that built a filesystem path from `__file__` worked; under
0.86 `dirname(__file__)` is *inside* the zip and every such path misses — that's the
"why only now." **iOS is unaffected** (its site-packages stay a real dir in the app
bundle; iOS has its own `.fwork`/framework story). Match the specific symptom below;
after a build, `unzip -l` the APK and check `assets/sitepackages.zip` /
`assets/extract.zip` / `lib/<abi>/`.

---

### `NotADirectoryError: [Errno 20] Not a directory: '.../sitepackages.zip/<pkg>/<datafile>'` (Android, at import)

**Cause:** the package reads a bundled **data file** (not a `.py`) via a real
`__file__`-relative path — matplotlib `mpl-data/matplotlibrc`, astropy `CITATION`,
scikit-learn `estimator.css`, thinc `backends/_custom_kernels.cu` (spacy pulls
thinc). Under 0.86 the parent is `sitepackages.zip` (a file), so `open()`/
`read_text()` on the child path raises NotADirectoryError.

**Fix:** ship the package **extracted to disk** via serious_python's Android hatch.
Declare it in the recipe's meta.yaml as a top-level list:
```yaml
extract_packages:
  - matplotlib      # the IMPORT name (sklearn not scikit-learn; cv2 not opencv-python)
```
`stage_recipe.sh` reads it (via `read_meta_list.py`) into
`[tool.flet.android].extract_packages`; serious_python unpacks those packages to
disk (on `sys.path` before the zip) so `__file__` resolves to a real dir. Field is
in `src/forge/schema/meta-schema.yaml`. Verified: matplotlib, astropy. **opencv-python**
also needs `extract_packages: [cv2]` — but that alone is NOT enough for it; its
loader has a separate config.py/native-name break (see the dedicated cv2 entry
below). And it does NOT help when the missing data file lives in a *flet-lib\**
`opt/` tree rather than the python package itself: **python-magic**
(`could not find any valid magic files!` — `magic.mgc` is dropped by `copyOpt`
because `copyOpt` copies only `**/*.so`); the fix there is to ship the data file
**inside the python package's own wheel** + load it from memory — see the dedicated
python-magic entry below.

---

### `RuntimeError: Failed to load shared library '.../<pkg>/lib/lib<X>.so'` / `dlopen failed: library "..." not found` (Android, at import — a **ctypes** loader that raises before its own jniLibs fallback)

**Cause — NOT what the path suggests.** The failing path (`…/sitepackages.zip/<pkg>/lib/
lib<X>.so` or `…/extract/<pkg>/lib/lib<X>.so`) is the path the loader *tried*, NOT where
the `.so` is. Flet 0.86 **does relocate these ctypes libs into `jniLibs/<abi>/`** (verified:
`unzip -l APK` shows `lib/arm64-v8a/libllama.so`, `libggml*.so`), so they ARE loadable —
but only by **bare soname**. The bug is in the recipe's own ctypes loader: its main-load
loop does `for lib_path in _candidate_paths(...): try: CDLL(str(lib_path)) except Exception:
raise RuntimeError(...)` — it **raises on the FIRST (disk/zip) candidate's miss and never
reaches the bare-soname jniLibs fallback that sits right below it**. (Regression: build-1
guarded with `if lib_path.exists()` so it fell through; the iOS `.fwork` rework dropped the
guard and added the raise.) llama-cpp-python (`libggml*`←`libllama`, `-DCMAKE_INSTALL_LIBDIR=
llama_cpp/lib`) hit exactly this.

**Fix — the loader, not packaging.** Change the main-load `except` to fall through (`pass`)
instead of raising, so the loop ends and the existing `for _n in (f"lib{name}.so", …):
CDLL(_n)` bare-soname fallback runs and the platform linker resolves it from jniLibs. Bump
the recipe build number (it's a wheel change). iOS is unaffected (the `.fwork` candidate is
tried first and succeeds). **`extract_packages` is a RED HERRING here** — I tried it first
and it FAILED: it moved the package's `.pyc` to disk but the `.so` still went to jniLibs, so
the raise-on-first-candidate still fired (path just changed from `sitepackages.zip/…` to
`extract/…`). Verified on-device (Android arm64, `test_native_lib_callable` PASS) after the
loader fall-through. Only reach for `extract_packages` when the missing thing is a **data
file** read by `__file__` (the entry above), not a native lib.

---

### `ModuleNotFoundError: No module named '<pkg>.<ext>'` / `cannot import name '<_ext>' … (most likely due to a circular import)` for a NATIVE submodule (Android)

**Cause:** the extension `.so` ships **untagged** — `ncnn/ncnn.so`,
`faiss/_swigfaiss.so`, `CoolProp/{CoolProp,_constants}.so` — rather than
`*.cpython-*.so`/`*.abi3.so`. serious_python only relocates + writes a `.soref` for
ABI-tagged names; a bare `NAME.so` is treated as a plain dependency lib, gets no
`.soref`, and the import finder can't resolve it. CMake / SWIG / Cython / nanobind
builds routinely emit untagged extensions (they can't derive the target SOABI when
cross-compiling; setuptools/maturin tag theirs, which is why numpy/pandas/pyarrow are
fine). The x86_64 leg can break while arm64 is fine if the build tags
nondeterministically per arch (onnxruntime). The misleading "circular import"
message is just Python's wording when a `from . import _ext` can't find the `.so`.

**Fix:** none per-recipe — **forge `fix_wheel` (build.py, Android branch) ABI-tags
any bare `.so` exporting `PyInit_<basename>`** (a genuine extension; `llvm-nm -D`
discriminates it from a dependency lib, which is left untouched) to
`<basename>.cpython-3X.so`, so serious_python writes its `.soref`. Just rebuild; the
fix is generic and covers future CMake/SWIG/Cython recipes. If you hit this, confirm
via `unzip -l` that the wheel ships a bare `.so` exporting `PyInit_*`. Verified:
ncnn, faiss-cpu, coolprop; onnxruntime x86_64.

---

### `OSError: Cannot load native module '<Pkg>.<mod>': Not found <mod>.cpython-3X.so, .abi3.so, .so, .fwork` (pycryptodome/pycryptodomex, Android)

**Cause:** the `.abi3.so` extensions ARE relocated + `.soref`'d (a plain `import`
would work), but pycryptodome's `Crypto/Util/_raw_api.py:load_pycryptodome_raw_lib`
**ctypes-loads by a `__file__`-relative path** (`os.path.isfile` next to the module,
inside the zip), never consulting the import system. General shape: any package with
a custom dlopen-by-`__file__` loader for extensions that *are* correctly tagged.

**Fix:** after the on-disk probes miss, ask the import system for the resolved
on-device origin and dlopen that — no hardcoded soname mangling:
```python
import importlib.util
spec = importlib.util.find_spec(name)      # name = "Crypto.Util._cpuid_c"
if spec is not None and spec.origin:
    return load_lib(spec.origin, cdecl)    # _SorefFinder set origin to the jniLibs/apk path
```
Extend the recipe's `mobile.patch` loader; keep the existing iOS `.fwork` branch (it
wins first on iOS, where the path is real). Verified: pycryptodome, pycryptodomex.

---

### `cannot import name '<subdir>' from partially initialized module '<pkg>'` for an include-only namespace dir (Android)

**Cause:** `<pkg>/__init__.py` does `from . import <subdir>`, but `<pkg>/<subdir>/`
has **no importable member** — only Cython `.pxi` includes / `.h`/`.c` / data
(compiled into a sibling `.so` at build time). Under normal CPython it's an empty
PEP 420 namespace package; under 0.86 serious_python's `synthesizePackageInits()`
only injects a synthetic `__init__` for dirs containing a `.py`/`.pyc`/`.soref`, so
the include-only dir is invisible to `zipimport`. selectolax:
`from . import lexbor, modest, parser` — `modest/` holds only `.pxi` (`include`d by
`parser.pyx`); `lexbor`/`parser` are real `.so` and load fine.

**Fix:** if the import is **vestigial** (no runtime API — the real modules are the
sibling `.so`), drop it from `__init__` via `mobile.patch` (selectolax:
`from . import lexbor, parser`). If the dir genuinely must be importable, ship an
empty `<pkg>/<subdir>/__init__.py` — but verify the build's `find_packages` /
`package_data` actually lands it in the wheel (selectolax's
`find_packages(include=["selectolax"])` would NOT, which is why the drop was cleaner
there). Verified: selectolax (drop).

---

### `ImportError: OpenCV loader: missing configuration file: ['config.py']` / `Bindings generation error. Submodule name should always start with a parent module name. Parent name: cv2.cv2. Submodule name: cv2` (opencv-python, Android)

**Cause:** a *two-part* 0.86 break in cv2's stock loader
(`cv2/__init__.py::bootstrap`). Stock OpenCV: (1) `exec()`s a `config.py` /
`config-3.py` to discover a directory of `.so` files, then (2) pops the `cv2`
package from `sys.modules` and **re-imports it as the top-level module `cv2`** so the
native binary's `__name__` is exactly `cv2` — its compiled-in bindings register
submodules (`cv2.dnn`, `cv2.gapi`, …) and assert each *starts with the parent name*.
Under 0.86 Android both halves break: `config.py` is compiled to `config.pyc`, so
`os.path.exists('config.py')` is False → **"missing configuration file"**; and the
native `cv2.cv2` extension is relocated to `jniLibs` (importable **only** as the
submodule `cv2.cv2` via a `cv2/cv2.soref` marker, never as top-level `cv2`). If you
naively `import cv2.cv2`, OpenCV's C init sees parent name `cv2.cv2`, the compiled
submodule `cv2` no longer starts with it, and it aborts with **"Submodule name
should always start with a parent module name."** (The native `.so`'s DT_NEEDED are
all system libs — `libcamera2ndk`/`libmediandk`/`liblog`/… — so this is **not** a
dlopen failure; don't chase a missing lib.)

**Fix:** patch `cv2/__init__.py` to insert a fast-path right after the
`sys.OpenCV_LOADER = True` recursion guard that bypasses the config machinery and
loads the native under the **required top-level name `cv2`**:
```python
import importlib.util as _ilu, importlib.machinery as _ilm
_sub = _ilu.find_spec(__name__ + ".cv2")          # soref finder → real jniLibs .so path
if _sub is not None and getattr(_sub, "origin", None):
    _loader = _ilm.ExtensionFileLoader("cv2", _sub.origin)   # name MUST be "cv2", not "cv2.cv2"
    _native = _ilu.module_from_spec(_ilu.spec_from_loader("cv2", _loader))
    _loader.exec_module(_native)                  # runtime __name__ == "cv2" → C init happy
    # relink _native.__dict__ into globals(), del sys.OpenCV_LOADER,
    # then run __collect_extra_submodules()/__load_extra_py_code_for_module()
    return
# else fall through to the stock loader (desktop / non-0.86)
```
Pair with **`extract_packages: [cv2]`** in meta.yaml (the extra-submodule scan does
`os.listdir()` on the package dir, so cv2 must ship extracted, not zipped). On
desktop `find_spec('cv2.cv2')` is None → stock loader runs unchanged. General tell:
any package whose loader **re-imports its own native under a specific top-level
name** — reproduce the exact name via a fresh `ExtensionFileLoader(name, origin)`,
never via `import pkg.pkg`. Verified on-device (arm64) 4/4 against the byte-identical
4.10 loader; ported to the 5.0.0.93 recipe.

**iOS has the SAME break, different relocation → the fast-path must handle both.**
On iOS the native is framework-ized, not soref'd: serious_python leaves a
`cv2/cv2.fwork` marker whose text is the **app-relative path to the framework
binary** (e.g. `Frameworks/cv2.cv2.framework/cv2.cv2`). So `find_spec('cv2.cv2')`
returns an origin ending in **`.fwork`** (not `.so`) — an Android-only fast-path
that assumes a `.so` origin falls through and the stock loader recurses
(`ERROR: recursion is detected during loading of "cv2" binary extensions`). Resolve
it exactly as CPython's `AppleFrameworkLoader.create_module` does — read the
`.fwork` text and `os.path.join(os.path.dirname(sys.executable), <that text>)` — to
get the framework binary, then `ExtensionFileLoader("cv2", <framework binary>)`.
(This is separate from, and downstream of, the forge `fix_wheel` MH_BUNDLE→MH_DYLIB
conversion that makes cv2 *linkable* in the first place.) One local-repro gotcha:
serious_python's per-arch native staging pulls the iphoneos-slice wheel from the
index (NOT honoring `--find-links`/dist-test locally), so a hand-patched dist-test
wheel won't take on a local `flet build ios-simulator` — verify opencv iOS in CI
(where the freshly-built slice wheels are used), as coolprop iOS did.

---

### `AttributeError: module 'apsw' has no attribute 'Connection'` / a package whose `__init__` IS the native extension imports empty (Android) — a serious_python `_SorefFinder` gap

**Cause:** the package's `__init__` is *itself* a C extension — apsw's setup builds
`Extension("apsw.__init__", …)` → `apsw/__init__.cpython-*.so` (dotted import name
`apsw`). Under 0.86 that `.so` is relocated to jniLibs and its marker is written at
**`apsw/__init__.soref`**, but `_sp_bootstrap._SorefFinder.find_spec("apsw")` only
probed `"<dotted>.soref"` (= `apsw.soref`) → miss → `None`. Meanwhile
`synthesizePackageInits()` injects an **empty `apsw/__init__.py`**, which then wins,
so `import apsw` yields an empty module and any `apsw.Connection` / `apsw.apswversion()`
raises AttributeError. **This is a serious_python bug, not a recipe/forge bug** — the
recipe's mobile.patch (SQLite amalgamation cross-compile) is unrelated; the `.so`
exports `PyInit_apsw` (not `PyInit___init__`) on non-Windows, so it *can* be loaded
under the top-level name.

**Fix (in serious_python, `serious_python_android/python/_sp_bootstrap.py`):** when
`"<dotted>.soref"` misses, fall back to **`"<dotted>/__init__.soref"`**; load via
`ExtensionFileLoader(fullname, origin)` (its `PyInit_<name>` matches) and mark the
result a **package** — set `spec.submodule_search_locations = [<winning sys.path
entry>/<dotted>]` so pure-Python submodules (`apsw.ext`, `apsw._unicode`, …) resolve
via the normal zipimport/FileFinder machinery (`_read_marker` must also return which
entry it hit). The `_SorefFinder` sits at `meta_path[0]`, so once it resolves `apsw`
it beats the synthesized empty `__init__`. Validated on-device (Android arm64) with a
local serious_python override: apsw 3.53.2.0 imports + runs an in-memory SQLite
round-trip 2/2. **Caveat:** the fix must land in a *released* serious_python before
CI / real consumers get it — until then apsw stays red in CI (do not include it in a
recipe CI dispatch). To test an unreleased serious_python locally, point the app at
your checkout via `[tool.flet.flutter.pubspec.dependency_overrides]` (path deps for
`serious_python` + `serious_python_android` + `serious_python_platform_interface`) in
the generated pyproject.

---

### `magic.MagicException: could not find any valid magic files!` (python-magic, Android) — a data file that lives in a `flet-lib*` `opt/` tree

**Cause:** the runtime data file a package needs ships in a **separate `flet-lib*`
wheel's `opt/` tree**, not in the package itself, and 0.86's `copyOpt` copies **only
`.so`** out of an `opt/` tree (and `splitSitePackages` skips `opt/` entirely), so the
data file reaches **neither** jniLibs **nor** `sitepackages.zip`. python-magic:
libmagic's compiled DB `magic.mgc` ships in `flet-libmagic`'s
`opt/share/misc/magic.mgc`; the `.so` (`libmagic.so`) is relocated to jniLibs fine,
but `magic.mgc` is dropped, so `magic_load(cookie, <missing path>)` /
`magic_load(cookie, None)` (falls back to libmagic's compiled-in default, absent on
device) fails. **`extract_packages` does NOT help** — extracting the *python* package
to disk doesn't bring back a file that was never in it. iOS is unaffected (real dir).

**Fix (two parts):** ship the data file **inside the consuming package's own wheel**
(which rides 0.86's all-files `sitepackages.zip`, unlike an `opt/` tree), then load it
in a way that survives the stored zip.
- *Delivery:* forge's `PythonPackageBuilder` has no copy hook and `patch -p1` can't
  carry a multi-MB binary, so copy it in from `setup.py` at build time, fed the path
  via a meta `build.script_env` that templates the `flet-lib*` host dep's cross-env
  path — `FLET_MAGIC_MGC: "{platlib}/opt/share/misc/magic.mgc"` (the `{platlib}/opt/…`
  idiom; the `flet-lib*` host dep installs there). Add the file to `package_data`.
- *Load:* real path when one exists (iOS/desktop/`extract_packages`), else read the
  file's **bytes** via `importlib.resources.files(__package__).joinpath(...).read_bytes()`
  (routes through `zipimport.get_data`, so it works from a stored zip) and hand them to
  a **from-memory** API — for libmagic, bind `magic_load_buffers` (public in file
  ≥ 5.32) and keep the ctypes buffer alive past the cookie (libmagic references it in
  place; stash it on the object the module caches). Guard the binding
  (`except AttributeError`) so import survives an older lib.
Zero consumer config (no `extract_packages`). General tell: a package's runtime data
lives in a sibling `flet-lib*` `opt/` and you see a "can't find <data>" at import →
relocate the data into the consumer's wheel + load from memory. Verify with
`nm -D lib<x>.so | grep <load_buffers_symbol>` (must be exported) and `unzip -l` the
APK's `sitepackages.zip` for the data file. Verified on-device (arm64) 2/2:
python-magic (`magic_load_buffers`, `magic.mgc` 10.3 MB in `sitepackages.zip`).

---

### `FileNotFoundError: Shared library with base name '<X>' not found` (ctypes-by-`__file__` loader, Android)

**Cause:** the loader gates each candidate on `Path.exists()` for a
`dirname(__file__)/lib` path — inside `sitepackages.zip` under 0.86, so every probe
misses. The bundled libs (llama-cpp-python's libllama/libggml*) were relocated to
`jniLibs` and are loadable by bare soname. Same 0.86 class as the `find_library()
→ None` case (pysodium/opaque) below, different loader shape.

**Fix:** after the on-disk probes miss, fall back to `ctypes.CDLL("lib<name>.so")`
(bare soname → the Android linker resolves it from jniLibs), for both the dependency
preload and the main lib; load `RTLD_GLOBAL` so preloaded deps satisfy the main
lib's DT_NEEDED. Verified: llama-cpp-python (android). See also "Unable to find
… shared library" (the `find_library`-returns-None sibling).

---

### `ImportError: dlopen failed: cannot locate symbol "<sym>" referenced by ".../lib/<abi>/lib<pkg>.so"` where `lib<pkg>.so` is the wheel's OWN extension (Android)

**Cause:** a **jniLibs name collision**. A *top-level* Python extension module named
`<pkg>` (e.g. `jq`) mangles to `lib<pkg>.so`; a bundled `flet-lib*` C library with
the same base name (`libjq.so`) *also* lands at `lib/<abi>/lib<pkg>.so`. One clobbers
the other — the extension (which references the C lib's symbols) overwrites the C
lib, so its symbols vanish (`cannot locate symbol jq_teardown`). NOT a missing
export — `llvm-nm -D` shows the C lib exports it fine; check `lib/<abi>/lib<pkg>.so`'s
size to see which one won.

**Fix:** make the extension **self-contained** so no colliding `lib<pkg>.so` ships.
Static-link the flet-lib* into the extension: build the flet-lib* `--with-pic` and
keep its `.a` (drop the `.so`); in the consumer switch `requirements.host` →
**`host_build`** (build-time only, not a runtime dep) and patch the link
`-l<name>` → `-l:lib<name>.a` (static). The extension's DT_NEEDED then lists no
`lib<pkg>.so`. Verified: jq (static-links flet-libjq's libjq.a/libonig.a; flet-libjq
build 11, jq build 3).

**iOS caveat — `-l:NAME.a` is a GNU ld extension; Apple's ld64 does NOT support it**
→ the iOS build dies `ld: library ':libjq.a' not found` on every Python. The jniLibs
name collision that motivates `-l:` is **Android-only**, and since the `flet-lib*`
ships *only* static `.a` (no `.so`/`.dylib`), a plain `-l<name>` resolves to the
static archive just the same on iOS. So gate the flag by target platform in the
consumer's `setup.py`: `-l:libX.a` on Android, `-lX` on iOS. Detect with
`"ios" in sysconfig.get_platform()` (the crossenv reports the *target* platform, e.g.
`ios-13.0-arm64-iphonesimulator`). Verify the iOS extension is self-contained with
`otool -L` (no `libX` dylib dep) + `nm` (the `libX` symbols are `T`, defined). Any
recipe that borrows this static-link pattern must apply the same per-platform gate.

---

### iOS: `import <pkg>` → `symbol not found in flat namespace '…<Sym>…'` at dlopen (a CMake OBJECT library never made it into the `.framework`)

**Cause:** the build is GREEN but a CMake `OBJECT` library's objects — meant to link
straight into the consuming target — do **not** propagate into an iOS static-framework
link. The consuming code keeps its references (iOS links with `-undefined
dynamic_lookup`, so undefined symbols are allowed at *link* time), and the symbol has no
provider at *runtime* → dlopen fails on first `import`. opencv 5's vendored **MLAS**
(`3rdparty/mlas` OBJECT lib → `opencv_dnn`) does exactly this: `import cv2` dies on
`MlasGemmBatch`. **Key lesson: a green iOS wheel ≠ a loadable one — you cannot `import`
an iOS wheel on the macOS build host, so only the sim/emulator (or CI mobile test)
catches this class.**

**Fix:** fix the propagation, or (pragmatic) disable the OBJECT-lib feature on the iOS
framework build. For MLAS: gate `add_subdirectory(3rdparty/mlas)` on `NOT
APPLE_FRAMEWORK` — its call sites are wholly `#ifdef HAVE_MLAS`, so they compile out and
opencv_dnn falls back to its built-in SGEMM. Android static-links it fine (its on-device
test passes), so keep it there. **Cheap host-side check without a device:**
`nm -u <ext>.so | grep -i <sym>` must be empty, and every remaining undefined symbol
should have a provider in `otool -L` (linked frameworks), libSystem, libc++, or the
app's Python. opencv-python 5.0.0.93 `mobile.patch`.

---

### `ImportError: dlopen failed: library "libc++_shared.so" not found` (Android, at first import)

**Cause:** ujson, grpcio, opencv-python, pandas, etc. all link C++ code against NDK's libc++_shared. The `.so` they ship has a runtime DT_NEEDED entry for `libc++_shared.so`, which has to be packaged into the APK's `lib/<abi>/`. Without `flet-libcpp-shared` as a host dep, it isn't.

**Fix:** add to recipe meta.yaml, Android-only via Jinja:

```yaml
# {% if sdk == 'android' %}
requirements:
  host:
    - flet-libcpp-shared >=27.2.12479018
# {% endif %}
```

Then `forge --clean android <pkg>` to rebuild Android slices with the new METADATA. `fix_wheel()` (build.py:582-600) will add `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` to the wheel METADATA. When the recipe-tester app installs, pip will auto-pull `flet-libcpp-shared`, and serious-python-android's `copyOpt_<abi>` gradle task will copy `libc++_shared.so` from `site-packages/<abi>/opt/lib/` into `jniLibs/<abi>/`. Android packages it into the APK's `lib/<abi>/`, which is in dlopen's default search path.

iOS doesn't need this — Apple's clang resolves the C++ runtime to system libc++ which is always present.

---

### `ImportError: Unable to find <name> shared library` (ctypes wrapper, at import)

**Cause:** a pure-Python `ctypes` wrapper called `ctypes.util.find_library()`,
which returns `None` on mobile (no ldconfig/compiler), so it gave up before
trying to load the lib. This is the Pattern H case (pyzbar, python-magic,
pysodium, opaque, …); under Flet 0.86 it is the `find_library`-returns-None
member of the `sitepackages.zip` class (umbrella entry at the top of this
section).

**Fix:** this needs the full Pattern H treatment, not a one-liner:
1. the `flet-lib*` must be built **shared** (`lib<name>.so`), not static;
2. the wrapper's loader must be **patched** to try
   `<site-packages>/opt/lib/lib<name>.fwork` (iOS), `…/opt/lib/lib<name>.so`,
   and bare `lib<name>.so` (Android);
3. the wrapper must declare the flet-lib* in `requirements.host`;
4. on iOS, build the flet-lib* for **all three slices** (see the iOS-absent
   entry above).

iOS detail: iOS CPython's `ctypes.CDLL` *is* `.fwork`-aware — pass it the
`.fwork` path and it dereferences to the embedded framework. See
`references/recipe-patterns.md` § "Pattern H" for the full recipe and the
canonical loader patch.

---

### `ImportError: dlopen failed: library "libssl.so.3" not found` (or libcrypto, libsqlite, etc.)

**Cause:** the .so links to OpenSSL/SQLite/etc. dynamically. On Android, those libraries are provided by the Python Android support tarball under different names (e.g., `libcrypto_python.so` rather than `libssl.so.3`).

**Fix:** depends. Sometimes the upstream `setup.py` accepts an env var to point at the right library. Sometimes a patch is needed. Check existing recipes for the same C dep:

```bash
grep -rln 'libssl\|libcrypto\|OPENSSL' recipes/*/meta.yaml | head -5
```

`recipes/cryptography/`, `recipes/grpcio/`, and `recipes/pymongo/` are the canonical references for OpenSSL-linked recipes.

---

### `ImportError: cannot import name '<X>' from '<pkg>'`

**Cause:** the wheel was built but Python found a *different* (likely pure-Python fallback) version of the package at import time, missing the C accelerator. Usually a site-packages clash.

**Fix:** rare in well-formed test apps. Check `import <pkg>; print(<pkg>.__file__)` to see which copy is being loaded. If the path is `<app>/python_site_packages/`, you're loading our wheel. If it's somewhere else, there's a stale install in `build/<proj>/site-packages/<arch>/`.

```bash
rm -rf build/   # nuke flet-cli's site-packages cache
uv run flet build apk  # rebuild
```

---

### App launches but `import X` shows old version

**Cause:** flet-cli has a hash-based cache (`build/.hash/`) that decides whether to re-run the pip install step. If you only updated wheels in `dist/` but pyproject deps didn't change, the cache thinks nothing has changed.

**Fix:**

```bash
rm -rf tests/recipe-tester/build/.hash
flet build <target>
```

Or for full freshness:

```bash
rm -rf tests/recipe-tester/build
flet build <target>
```

---

### `Cannot load imports from non-existent stub` (lazy_loader, on device only)

**Cause:** serious_python STRIPS `*.pyi` files when bundling site-packages into the
app. Packages using lazy_loader's `attach_stub()` (which parses the `.pyi` at import
time to learn the lazy API surface) crash on every import even though the wheel
carried all the stubs. First hit: scikit-image (15 stubs, all 16 imports dead).

**Fix:** patch inside the wheel — convert every `attach_stub(__name__, __file__)`
call to plain `lazy_loader.attach(__name__, submodules=[...], submod_attrs={...})`
(sklearn-style), with the tables precomputed mechanically from each `.pyi` (mirror
lazy_loader's own `_StubVisitor` rules). Validate on desktop by deleting all `.pyi`
from the installed package and re-running the tests. WATCH FOR any package using
`attach_stub` — the pattern is spreading in scientific python (networkx does not).
scikit-image `mobile.patch`.

---

### `ModuleNotFoundError: No module named '_posixshmem'` (iOS, at import of a multiprocessing user)

**Cause:** a python-build gap, not a recipe bug. iOS CPython (flet's python-build)
re-enables `_multiprocessing` (`build_ios.py` flips `py_cv_module__multiprocessing=n/a`
→ `yes` — SemLock/sockets build fine on Darwin) but left **`_posixshmem` n/a**.
`multiprocessing/resource_tracker.py` does an **unconditional `import _posixshmem`
on posix**, so with `_multiprocessing` present but `_posixshmem` absent, *any*
transitive `import multiprocessing` takes the consumer down on iOS. scikit-learn:
`sklearn.utils.validation` → joblib → multiprocessing → `resource_tracker` →
`ModuleNotFoundError: _posixshmem`. Affects **any** package that reaches
multiprocessing (not sklearn-specific).

**Fix (in python-build, not the recipe):** flip `py_cv_module__posixshmem=n/a` →
`yes` in `darwin/build_ios.py`, right beside the existing `_multiprocessing` flip.
`shm_open`/`shm_unlink` build fine on Darwin/iOS (the sandbox restricts *use*, not
the build; nothing here uses shared memory), and upstream 3.13's official iOS
support ships `_posixshmem`. Leave `_posixsubprocess` n/a (genuinely needs
fork/exec). **Needs an iOS python-build rebuild + a new support run-id for CI to
pick it up.** Tell: any iOS import traceback whose deepest frame is
`multiprocessing/resource_tracker.py` importing a missing `_posix*` → it's this
python-build gap, fix it there, don't patch the consuming recipe.

---

### `ModuleNotFoundError` on device for a dep the package never declared (hidden dependency)

**Cause:** upstream's `Requires-Dist` is incomplete for the code path mobile
actually exercises — e.g. keras's numpy backend eagerly imports scipy
(`backend/numpy/linalg.py`) but upstream omits scipy because the other backends
don't need it. Desktop dev machines mask this (scipy is always around).

**Fix:** patch the dep into the package's `pyproject.toml` dependencies (keras
`mobile.patch`). **Detection method that catches these before the device does:**
build a device-emulating desktop venv containing ONLY the wheel's declared deps
(no jax, no dev leftovers) and run the recipe tests there.

---

### insightface: `PermissionError: [Errno 13] … '/data/.insightface'` (FaceAnalysis init, Android)

**Cause:** `FaceAnalysis()` defaults its model root to `~/.insightface`, and in
1.0.1 the `INSIGHTFACE_HOME` env var is IGNORED — on Android `~` resolves to an
unwritable location.

**Fix:** always pass `root=` explicitly to a writable app dir (e.g.
`os.path.join(os.environ["FLET_APP_STORAGE_DATA"], "insightface")`). The mobile
model pack is `buffalo_sc` (det_500m + w600k_mbf, 15MB download).

---

## Recipe-tester app failures

### `ResolutionImpossible` — a package's `numpy` upper-cap can't be satisfied on a newer CPython

**Symptom:** `flet build` (or a mobile test) dies with pip
`ResolutionImpossible` / `Cannot install X, numpy and Y … conflicting
dependencies`, naming a `numpy<A.B.C` cap. Real case: `opencv-python 4.12.0.88`
requires `numpy<2.3.0`, but the **lowest numpy that supports cp314 is 2.3.2**, so
NO `<2.3.0` numpy exists for Python 3.14 — and flet 0.86 defaults `flet build` to
**cp314**. Any app pulling such a package (opencv, or ncnn which depends on it)
becomes unresolvable on the default. cp312 is fine (numpy 2.2.2 is published), cp313
often too.

**Cause:** a native dep's `Requires-Dist` upper-caps numpy below the *lowest* numpy
that supports the target CPython. Publishing an older numpy to the index CANNOT fix
it — the version you'd need doesn't build for that CPython at all.

**Fix:** bump the capping package to a release that lifts the cap (opencv-python
5.0.0.93 → `numpy>=2`, unbounded). Watch sdist availability — opencv `4.13.x` dropped
the cap but are **wheel-only** (no sdist for forge to build); `5.0.0.93` was the first
cap-free release WITH an sdist. Interim user workaround: `flet build --python-version
3.12`. (Trimming the *consumer's* forced deps — e.g. ncnn's `install_requires` on
opencv-python — is a separate lever but doesn't help an app that uses opencv directly.)

---

### `uv run flet build` fails building the package *from source on the host* (e.g. `Error: pg_config executable not found`)

**Symptom:** `uv run flet build apk` (or `ios-simulator`) dies almost immediately
— before flet prints "Creating app shell" — with a build error for *your*
package compiled for **macOS**: `× Failed to build psycopg2==2.9.12 … Error:
pg_config executable not found`, or any host-toolchain error. The Android/iOS
wheel you built is fine and irrelevant here.

**Cause:** the recipe-tester is a uv project (`pyproject.toml` + `uv.lock` +
`.venv`), so `uv run` does an **implicit `uv sync` of the host venv** before
running flet. When the package you added has **no host (macOS) wheel on PyPI** —
psycopg2 is sdist-only; the binary is the separate `psycopg2-binary` — uv falls
back to building it for the host and hits the missing host library/tool. The
host venv never actually needs your package (flet *cross*-compiles it for the
device), so the sync is pure collateral damage.

**Fix:** skip the implicit sync — `flet` is already in `.venv` from earlier runs:

```bash
PIP_FIND_LINKS="$(realpath ../../dist)" uv run --no-sync flet build apk --arch arm64-v8a
```

`flet build` then cross-installs your package from `dist/` via `PIP_FIND_LINKS`
with the target platform tag (it uses `--only-binary`, so it never tries to
compile for the host). Confirm the package landed in the bundle — on flet ≥0.85
it's inside `lib/<abi>/libpythonsitepackages.so`, not `app.zip`:

```bash
unzip -p build/apk/*.apk lib/arm64-v8a/libpythonsitepackages.so > /tmp/sp.zip
unzip -l /tmp/sp.zip | grep <pkg>
```

(If `.venv` somehow lacks flet, run `uv sync --dev` once *without* your package in
`[project].dependencies`, then add it back and use `--no-sync`.)

---

### `Extra PyPi indexes: [https://pypi.flet.dev]` — and pip uses pypi.flet.dev's version, not your local dist

**Cause:** `PIP_FIND_LINKS` is not set in the shell where you ran `flet build`. The Dart `Process.start` inherits the parent env by default, but only what's set at invocation time.

**Fix:** in the same terminal session where you run `flet build`:

```bash
export PIP_FIND_LINKS="$(realpath /path/to/mobile-forge/dist)"
flet build <target>
```

Or inline:

```bash
PIP_FIND_LINKS="$(realpath /path/to/mobile-forge/dist)" flet build <target>
```

Verify pip is seeing it by looking for the line `Looking in links: /path/to/mobile-forge/dist` in the pip output during the build.

---

### `Installing requirements with pip command` produces "no matching distribution" for your package

**Cause:** the wheels in `dist/` don't have the platform tag pip is asking for. Common when:
- You built only iOS wheels and ran `flet build apk` (no Android wheel exists)
- The Python ABI tag is wrong (cp312 vs cp313 — recipe-tester might be on a different Python)
- You built only the `iphonesimulator` slices and ran `flet build ios-simulator` —
  it **also resolves the iphoneos (device) wheel**, so the full iOS slice set
  (iphoneos.arm64 + both simulators) must be in `dist/`. onnxruntime-iOS.

**Fix:** confirm `dist/<pkg>-*-<expected-tag>.whl` exists:

```bash
ls dist/<pkg>-*  | sort
```

Each `flet build <target>` resolves the target tag from `serious_python/bin/package_command.dart::platforms`. For `ios-simulator` on Apple Silicon: `ios-13.0-arm64-iphonesimulator`. For `apk`: one tag per configured arch (default: `android-24-arm64-v8a`, `android-24-armeabi-v7a`, `android-24-x86_64`).

If the wheel for the right tag isn't there, build it: `forge <slice> <pkg>`.

---

### `flet build` pip-backtracks a pure-python dep to an ancient version → runtime crash (omegaconf 2.0.0 `UnsupportedValueType: PosixPath`)

**Cause:** flet's mobile resolution requires **wheels**, and a pure-python dep in
the chain is **sdist-only on PyPI** (antlr4-python3-runtime, omegaconf's dep).
pip quietly backtracks the parent to an ancient version that predates the dep
(omegaconf → 2.0.0), and the app crashes at runtime far from the real cause.

**Tell:** scan the pip resolution output during `flet build` for a suspiciously
old version of a mid-chain dep. General tell for any sdist-only pure-python
package in a dependency chain — no recipe is needed.

**Fix:** `pip wheel antlr4-python3-runtime==4.9.3` once and re-host the
resulting `py3-none-any` wheel (pypi.flet.dev, or `PIP_FIND_LINKS` locally), and
pin the parent in the app (`omegaconf>=2.3`). rapidocr validation.

---

### Build succeeds but the APK is missing `lib/<abi>/libc++_shared.so` (or other native lib)

**Cause:** the `flet-libcpp-shared` host dep wasn't picked up. Either (a) it's not declared in the recipe's `requirements.host`, (b) `fix_wheel()` didn't write the Requires-Dist entry to METADATA, or (c) the Android wheel for `flet-libcpp-shared` doesn't exist on pypi.flet.dev for the target ABI.

**Fix:** check each layer:

```bash
# (a) — did the recipe declare it?
grep -A3 'requirements' recipes/<pkg>/meta.yaml

# (b) — did the wheel METADATA get the Requires-Dist line?
unzip -p dist/<pkg>-*-android_24_arm64_v8a.whl '*/METADATA' | grep Requires-Dist

# (c) — is flet-libcpp-shared available?
pip index versions flet-libcpp-shared --index-url https://pypi.flet.dev
# (or just check by browsing pypi.flet.dev)
```

If (b) is missing, rebuild with `forge --clean android <pkg>` (the recipe change requires a wheel rebuild).

---

### `adb: failed to install … java.io.IOException: Requested internal only, but not enough space`

**Cause:** the emulator's `/data` is full (Flet APKs are ~150–200 MB, and each
install also extracts a `python_site_packages` copy). Stale `recipe_tester`
installs from previous sessions pile up.

**Fix:** reclaim space — `adb uninstall com.flet.recipe_tester` (frees its data),
or `adb shell df /data` to check, or use an AVD with a larger internal-storage
setting. Then reinstall.

---

### Device shows the *old* app behavior after reinstalling

Two layers of stale state to clear when iterating on a recipe:
- **Host (flet build cache):** `rm -rf <proj>/build/.hash` (see the
  "App launches but `import X` shows old version" entry).
- **Device (extracted site-packages):** `adb install -r` keeps the app's data
  dir, where Flet caches the extracted `python_site_packages`. A `-r` reinstall
  can keep serving the old extraction. Do a **full** `adb uninstall
  com.flet.recipe_tester` before installing, or `adb shell pm clear
  com.flet.recipe_tester`. On iOS Simulator, `xcrun simctl uninstall booted
  <bundle-id>` similarly.

---

### `flet build` fails resolving a PURE-python dep that has no wheel on PyPI (sdist-only)

**Cause:** the target-platform pip resolve refuses sdists by default, so a
pure-python-but-sdist-only dependency (insightface 1.0.1, antlr4 pins) fails with
"no matching distribution" — even though nothing needs compiling.

**Fix:** NOT a recipe. The app opts in via pyproject:

```toml
[tool.flet]
source_packages = ["insightface"]
```

which makes `flet build` set `SERIOUS_PYTHON_ALLOW_SOURCE_DISTRIBUTIONS` and pip
builds that sdist for the target at package time. Decision tree: sdist-only + pure
python → `source_packages`; sdist-only + native code → recipe. (Check the sdist
really is pure — an opt-in C extension gated behind an env var, like insightface's
face3d, still counts as pure.)

---

## Diagnostic snippets

### Inspect a wheel's contents

```bash
python -m zipfile -l dist/<pkg>-*-<tag>.whl
unzip -p dist/<pkg>-*-<tag>.whl '*/WHEEL'      # tag, build, generator
unzip -p dist/<pkg>-*-<tag>.whl '*/METADATA'   # name, version, requires-dist
file <(unzip -p dist/<pkg>-*-<tag>.whl '*.so')  # confirm Mach-O / ELF target
```

### Inspect what `flet build` actually packaged

```bash
# After flet build, in the project dir
ls tests/recipe-tester/build/site-packages/<arch>/
unzip -l tests/recipe-tester/build/apk/app-<arch>-release.apk | grep -E 'lib/<arch>/'
```

### Get the full env that forge used during a failing build

The error log includes all environment variables passed to subprocesses, lines starting with `>>>` followed by `    KEY=value`:

```bash
grep -E "^    [A-Z_]+=|^>>>" errors/<pkg>-*-<slice>.log | head -50
```

This is gold for "but I thought CFLAGS was set!" debugging.

### Render meta.yaml manually for both SDK contexts

```bash
python .claude/skills/new-mobile-recipe/scripts/verify_render.py recipes/<name>/meta.yaml
```

Shows the rendered dict for iphoneos, iphonesimulator, android. Catches Jinja syntax issues and SDK-conditional logic bugs cheaply.
