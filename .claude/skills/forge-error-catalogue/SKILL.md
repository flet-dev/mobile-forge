---
name: forge-error-catalogue
description: >-
  Diagnose a mobile-forge recipe BUILD or runtime FAILURE via a catalogue of
  error -> cause -> fix mappings for cross-compiling Python wheels for iOS +
  Android. USE THIS when a `forge` build errors, a recipe wheel won't build or
  install, a CI recipe job goes red, or an on-device import crashes — e.g.
  Rust AtomicU64/E0432 on armeabi-v7a, autoreconf/autopoint, CMake FindPython
  "Could NOT find Python" (incl. the dual Python_*/Python3_*/SABI families),
  iconv on Android, undeclared cpow/clog, a green build whose wheel ships
  empty (platform.system() == "Android"), a host tool fetched for the wrong
  OS ("Exec format error"), wrong-arch .so in a wheel (e_machine mismatch),
  TENSORFLOW_SOURCE_DIR header skew, "None is not of type 'array'" meta
  schema errors, meson source-tree include / sanity-check breakage,
  duplicated patch hunks, iOS flatc MACOSX_BUNDLE, .dylib-vs-.so staging,
  libc++_shared, config.sub apple-ios, ctypes "Unable to find ... shared
  library", PT_LOAD 16KB alignment, lazy_loader "non-existent stub" crashes
  (stripped *.pyi), the Flet 0.86 Android sitepackages.zip class (NotADirectoryError
  on a bundled data file -> extract_packages, untagged native .so
  ModuleNotFoundError -> forge ABI-tag, ctypes-by-__file__ loaders -> find_spec /
  bare soname, jniLibs lib<pkg>.so name collision -> static-link, a package whose
  loader re-imports its own native under a fixed top-level name -> opencv cv2
  "missing configuration file: ['config.py']" / "Submodule name should always start
  with a parent module name"), hidden runtime deps, or a stale on-device cache. Sibling
  of `new-mobile-recipe` (authoring), `native-recipe-bumps` (version bumps),
  `local-recipe-testing` (on-device testing), and `forge-ci` (CI triage);
  this one is the dedicated error -> fix reference.
---

# mobile-forge error catalogue

The single source of error → cause → fix mappings for `flet-dev/mobile-forge`
recipe builds (cross-compiling Python wheels for iOS + Android). When a build or
on-device run fails, **match the error message here and apply the documented fix**
instead of re-deriving it.

## How to use

1. Grab the **first hard error** from the build log (not a warning). For a forge
   build, the failing log moves to `errors/<pkg>-*.log`; read the last ~100 lines.
2. Search [`references/failure-catalogue.md`](references/failure-catalogue.md) for
   the error string (or its symptom). Entries are grouped by phase.
3. Apply the fix. Rebuild the single failing slice first
   (`forge --clean <slice> <pkg>`) before fanning out.

## What's in the catalogue (`references/failure-catalogue.md`)

- **Build-time failures** — the big one. Cross-compiler/sysconfigdata paths,
  `config.sub` apple-ios, `--disable-pthread`, **iconv → flet-libiconv**, libtool
  versioned dylib (iOS), missing headers / `-lXXX`, libpython SONAME, libstdc++,
  iOS fat-lib / silently-absent flet-lib, **PT_LOAD 16KB alignment**, NDK install,
  missing build deps, **Rust `E0463` (mobile targets)** and **Rust `E0432`
  AtomicU64 on armeabi-v7a** (excluded_arches vs portable-atomic patch),
  no-dist-tarball → `source.url`, `-fPIC` relocations, iOS quoted-LDFLAGS,
  **CMake FindPython "Could NOT find Python" → `CROSS_VENV_PYTHON`**,
  **`autoreconf: autopoint failed` → install gettext/autotools**, **iOS ninja
  `posix_user` → Makefiles generator**, **bundled libsodium `--host` →
  `CIBW_HOST_TRIPLET`**, **Cython `cpow`/`clog` undeclared on bionic** (directive
  vs compat header), **superbuild self-clones its parent → stale headers
  (`TENSORFLOW_SOURCE_DIR`)**, Bazel `BUILD` vs setuptools `build/` on macOS,
  XNNPACK link-mandatory (`TfLiteXNNPackDelegateCreate`), **empty wheel via the
  `platform.system()` predicate**, **wrong-arch wheel (`e_machine` mismatch) →
  per-slice build dirs**, unbounded `make -j` CI OOM (+ `{CPU_COUNT}` KeyError in
  script_env), literal `"-G Ninja"` build-tool check, **pybind11 v3 → full
  `Python_*` triple** and **dual `Python_*`/`Python3_*`/SABI families**, forge CLI
  `KeyError: 'iOS'` slice syntax, dead force-enabled JNI lib, **prebuilt-zip
  leading-path strip**, **host tool for the wrong OS (`Exec format error` →
  real `uname`)**, `ONNX_BUILD_CUSTOM_PROTOBUF`, nanobind `Python.h`,
  **`--no-undefined` → comma-joined `-Wl` libpython token**, **empty jinja'd key →
  `None is not of type 'array'`**, meson source-tree includes /
  `install_data rename:` / `-include` sanity-check breakage, **build.sh
  `cmake: command not found` → `requirements.build`**, **duplicated patch hunks
  from concatenated diffs**, iOS `flatc` MACOSX_BUNDLE, **`.dylib` staged under
  the `.so` name**, **iOS `Unsupported mach-o filetype (only MH_OBJECT and
  MH_DYLIB can be linked)` → forge `fix_wheel` converts a CMake extension's
  `MH_BUNDLE` `.so` to `MH_DYLIB`** (inject `LC_ID_DYLIB` + flip filetype + ad-hoc
  re-sign; setuptools/Cython/meson already ship dylib), **Apple `MacTypes.h` `Ptr` vs `cv::Ptr` ambiguity** (iOS-only;
  hand-written + gen2.py-generated code), **opencv-5 KleidiCV `armv8-a` on x86_64**
  and **hardcoded `CMAKE_SYSTEM_PROCESSOR` → ARM asm on the x86_64 sim** (per-arch
  fix), **Rust crate with no `target_os="ios"` backend** (`mac_address`, cfg-gate it).
- **Runtime failures** (device/emulator/simulator) — **the Flet 0.86 Android
  `sitepackages.zip` class** (its umbrella entry explains "why only now"):
  `NotADirectoryError` on a bundled data file → **`extract_packages`** meta field;
  untagged native `.so` `ModuleNotFoundError`/"circular import" → **forge `fix_wheel`
  ABI-tags `PyInit_*` `.so`**; pycryptodome `Cannot load native module …` →
  **`importlib.find_spec().origin`**; llama `FileNotFoundError` / ctypes
  `find_library`-None → **bare-soname load from jniLibs**; a top-level extension
  colliding with a `flet-lib*` at `lib<pkg>.so` → **static-link (`host_build` +
  `-l:lib.a`)**; opencv-python cv2 `missing configuration file: ['config.py']` /
  `Submodule name should always start with a parent module name. Parent name:
  cv2.cv2` → **load the native under top-level name `cv2` via
  `ExtensionFileLoader("cv2", find_spec('cv2.cv2').origin)` + `extract_packages`**;
  a runtime DATA file that lives in a sibling `flet-lib*` `opt/` tree (dropped by
  `copyOpt`, which copies only `.so`) → python-magic `could not find any valid magic
  files!` → **ship the data file in the consumer's own wheel (`script_env`
  `{platlib}/opt/…` copy in setup.py + `package_data`) + load from memory
  (`importlib.resources` bytes → `magic_load_buffers`)**. Plus: `libc++_shared.so` not found,
  **CMake OBJECT-lib not linked into the iOS `.framework` → undefined symbol at
  dlopen** (opencv-5 MLAS; green build ≠ loadable — verify with `nm -u`/`otool -L`),
  ctypes **"Unable to find … shared library"** (Pattern H loader / lib delivery),
  `libssl.so.3`/`libcrypto`/`libsqlite` not found, import-name errors, old version
  loaded, **lazy_loader "non-existent stub" (serious_python strips `*.pyi`)**,
  **hidden runtime deps** (keras→scipy; device-emulating venv method),
  **insightface `root=` PermissionError**, and **iOS app crashes at launch with a
  0-byte `console.log` → `dyld: Library not loaded: @rpath/lib<X>.dylib` for a chain
  of interdependent bundled dylibs (pyarrow, llama)** → **serious_python #223**:
  reconcile framework install-ids + `@rpath` deps to the dotted-framework paths
  (`reconcile_framework_install_names` in darwin scripts; needs an sp release for CI;
  local sp fix cc28d13 verified pyarrow 4/4 on-sim).
- **Recipe-tester app failures** — host-build (`pg_config` etc.), pypi.flet.dev
  index precedence, "no matching distribution" (incl. **ios-simulator also
  resolving the iphoneos wheel**), **sdist-only pure-python dep → pip backtrack**
  (omegaconf `UnsupportedValueType: PosixPath`), **sdist-only pure-python dep →
  `[tool.flet] source_packages`, not a recipe**, missing `lib/<abi>/*.so`, install
  storage, the **stale device cache (uninstall before reinstall)**, and a **numpy
  upper-cap unsatisfiable on a newer CPython → `ResolutionImpossible`** (opencv
  `numpy<2.3.0` vs cp314; publishing an older numpy can't fix it — bump the capper).
- **Diagnostic snippets** — inspect a wheel, see what `flet build` packaged, dump
  the env forge used, render meta.yaml per SDK context.

## Adding entries

Append to `references/failure-catalogue.md` in the matching section, in the house
style: a `###` heading naming the exact error string, then **Cause:** and
**Fix:** (cite the recipe it came from). Keep one `---` between entries.

## Related

- `new-mobile-recipe` — authoring a brand-new recipe (it points here for failures).
- `native-recipe-bumps` — bumping existing `flet-lib*` versions.
- `local-recipe-testing` — fast on-device validation loop.
- `forge-ci` — CI triggering, chains, and run triage (infra flakes vs real failures
  live THERE, not here — this catalogue is for errors that reproduce).
