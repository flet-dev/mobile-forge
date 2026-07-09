# Recipe patterns — deep dive

Each subsection covers one recipe shape: when it applies, the canonical `meta.yaml`, what each field does, and a known-good real-world example from the recipes/ directory.

## Pattern A: Minimal C-extension (well-behaved upstream)

**When:** upstream package has C/C++ source, builds with plain `setuptools` / `pyproject.toml`, no system library deps beyond what mobile-forge provides (BZip2, OpenSSL, libffi, mpdecimal, XZ), no patches needed.

**meta.yaml:**

```yaml
package:
  name: <pypi-name-case-sensitive>
  version: <version>
```

That's it. Two real lines. The PyPI sdist lookup is automatic (forge calls PyPI's JSON API), `python -m build` runs the upstream's `setup.py` inside the crossenv, and the result wheel gets re-tagged for the mobile platform.

**Real examples:**
- `recipes/regex/` — has `_regex.c` C extension; 2-line recipe
- `recipes/lru-dict/` — pure C
- `recipes/bitarray/` — pure C
- `recipes/markupsafe/` — has `_speedups.c`

**When upstream needs a specific setuptools version:**

```yaml
package:
  name: msgspec
  version: 0.18.6
requirements:
  build:
    - setuptools ^69.5.1
```

`requirements.build` puts things in the build environment (your laptop runs them). Pip will install `setuptools>=69.5.1` before invoking `python -m build`.

**See:** `recipes/msgspec/meta.yaml`.

---

## Pattern B: Minimal C-extension + Android libc++_shared

**When:** package compiles C++ source (its own, or a bundled C++ library like `double-conversion`, `re2`, `protobuf`'s runtime, etc.) and on Android the resulting `.so` will dlopen `libc++_shared.so` at runtime. Pure-C packages don't need this.

**How to tell ahead of time:** look at upstream's `setup.py` for `extra_link_args` containing `-lstdc++`, `-lc++`, or `language='c++'` on `Extension(...)`. Look for `.cpp` / `.cc` files in `sources=`. If you see any of these, plan for this pattern.

**meta.yaml:**

```yaml
package:
  name: <pypi-name>
  version: <version>

# {% if sdk == 'android' %}
requirements:
  host:
    # iOS uses Apple's system libc++ — no extra dep needed. Android NDK r27d
    # links our C++ code against libc++_shared.so, which has to be present
    # at runtime in the app bundle. flet-libcpp-shared packages it and
    # serious_python_android's copyOpt_<abi> gradle task surfaces it into
    # jniLibs/<abi>/ at app build time.
    - flet-libcpp-shared >=27.2.12479018
# {% endif %}
```

**Real examples:**
- `recipes/ujson/` — uses bundled `double-conversion` C++ library
- `recipes/grpcio/` — much more involved but also uses this pattern (see `recipes/grpcio/meta.yaml`)

**Failure mode you're avoiding:** `ImportError: dlopen failed: library "libc++_shared.so" not found` at first `import <pkg>` on Android device.

---

## Pattern C: Rust via PyO3 / maturin

**When:** upstream `pyproject.toml::build-system.requires` contains `maturin` or `setuptools-rust`. The package compiles Rust code and exposes it via PyO3 bindings.

**meta.yaml:**

```yaml
package:
  name: <pypi-name>
  version: <version>
build:
  script_env:
    # PyO3 reads this env var to find the right sysconfig for the target
    # Python ABI. Without it, the Rust build can't link against the host
    # Python lib correctly.
    _PYTHON_SYSCONFIGDATA_NAME: '{sysconfigdata_name}'
```

The `{sysconfigdata_name}` placeholder gets filled by Python's `str.format` at compile-env time. Forge sets it to e.g. `_sysconfigdata__iphoneos_arm64-iphoneos`.

Cargo cross-compile plumbing (`CARGO_BUILD_TARGET`, `CARGO_TARGET_<...>_LINKER`, etc.) is handled by forge's `compile_env()` in `build.py:382-410`. The recipe doesn't touch `Cargo.toml`.

**Real examples:**
- `recipes/pydantic-core/` — canonical PyO3 example
- `recipes/jiter/` — same pattern, smaller package
- `recipes/rpds-py/` — same
- `recipes/tokenizers/` — same, larger Rust crate graph
- `recipes/pyxirr/` — adds a tiny patch (`mobile.patch`) to inject `version = ` into `pyproject.toml` because pyxirr's version is dynamic and cross-build needs it static

**Setup requirement:** Rust targets for the platform need to be installed on the host. The build env script (`setup.sh` / CI) does:

```bash
rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
rustup target add aarch64-linux-android arm-linux-androideabi x86_64-linux-android i686-linux-android
```

If you see a Rust build fail with "target not installed", run the relevant `rustup target add`.

**Upstream "no mobile support" disclaimer:** Some Rust packages (orjson) explicitly state they won't support mobile. This is about *upstream merging patches*, not about whether the code cross-compiles. The recipe lives in mobile-forge, not upstream — try the build and iterate. Most Rust+PyO3 packages cross-compile cleanly to mobile without patches.

---

## Pattern D: C-extension needing patches

**When:** the minimal recipe build fails because the upstream `setup.py` does something hostile to cross-compile — reaches for `/usr/include`, uses `pkg-config`, hardcodes macOS framework paths, conditionally branches on `sys.platform`, etc.

**meta.yaml:**

```yaml
package:
  name: <pypi-name>
  version: <version>
patches:
  - mobile.patch
```

**patches/mobile.patch:**

```diff
--- a/setup.py
+++ b/setup.py
@@ -100,5 +100,3 @@
-include_dirs = ['/usr/include/libsomething']
+include_dirs = []
@@ -200,3 +200,3 @@
-USE_PKG_CONFIG = True
+USE_PKG_CONFIG = False
```

The patch is applied with `patch -p1 --ignore-whitespace --quiet` after source unpack and before the build. Naming convention:

- `mobile.patch` — single patch covering all platforms and versions
- `mobile-<X.Y.x>.patch` — version-stream-specific (select via Jinja); use only when patches need to differ between upstream major/minor lines

**Authoring a patch:**

```bash
# Unpack the same source forge will use
cd /tmp
tar xf ~/PycharmProjects/.../mobile-forge/downloads/<pkg>-<ver>.tar.gz
cd <pkg>-<ver>

# Make your edits to setup.py / etc.
$EDITOR setup.py

# Generate the patch (forge expects -p1 style relative paths)
diff -u setup.py.orig setup.py > /path/to/recipes/<pkg>/patches/mobile.patch

# Confirm it applies cleanly to a fresh unpack
mkdir -p /tmp/verify && cd /tmp/verify
tar xf ~/PycharmProjects/.../mobile-forge/downloads/<pkg>-<ver>.tar.gz
cd <pkg>-<ver>
patch --dry-run -p1 --ignore-whitespace < /path/to/recipes/<pkg>/patches/mobile.patch
```

**Real examples:**
- `recipes/cffi/patches/mobile.patch` — drops host /usr/include and disables pkg-config probing
- `recipes/lxml/patches/mobile.patch` — filters macOS SDK include paths from `xml2-config --cflags` parsing
- `recipes/pyjnius/patches/mobile.patch` — replaces autodetection of `libjvm` with our peer-dep approach
- `recipes/pillow/patches/setup-11.x.patch` — version-stream-specific patch for Pillow's `setup.py`

---

## Pattern E: C-ext + script_env tweaks for native deps

**When:** upstream's build accepts environment variables to point at its native deps, AND you have a `flet-lib*` recipe providing that dep already (or you can use one of the dep wheels in `dist/` like openssl).

**meta.yaml:**

```yaml
package:
  name: <pypi-name>
  version: <version>
build:
  script_env:
    # These placeholders get filled by str.format at build time:
    # {platlib} → the crossenv's site-packages root, where flet-lib* wheels unpack
    OPENSSL_DIR: '{platlib}/opt'                    # cryptography expects this
    LIBSODIUM_LIB_DIR: '{platlib}/opt/lib'          # pynacl expects this
    GDAL_LIBRARY_PATH: '{platlib}/opt/lib'          # pyogrio expects this
    WITH_XML2_CONFIG: '{platlib}/opt/bin/xml2-config'   # lxml expects this
    _PYTHON_SYSCONFIGDATA_NAME: '{sysconfigdata_name}'  # PyO3 / sysconfig-aware C builds

# {% if sdk == 'android' %}
    # Android-specific CFLAGS/LDFLAGS additions — note CFLAGS/LDFLAGS get
    # APPENDED to the base sysconfig values, not overwritten (per build.py
    # script_env handling, line 444). Use this to add flags, not replace.
    CFLAGS: '-U__ANDROID_API__ -D__ANDROID_API__={{ sdk_version }}'
    LDFLAGS: '-llog -L{platlib}/opt/lib'
# {% endif %}

requirements:
  host:
    - openssl >=3.0.15
    # Add other flet-lib* deps as needed
# {% if sdk == 'android' %}
    - flet-libcpp-shared >=27.2.12479018
# {% endif %}
```

**Real examples:**
- `recipes/cryptography/meta.yaml` — uses `OPENSSL_DIR` + `_PYTHON_SYSCONFIGDATA_NAME`
- `recipes/lxml/meta.yaml` — uses `WITH_XML2_CONFIG` + `WITH_XSLT_CONFIG`, gates `-liconv` LDFLAGS by SDK
- `recipes/grpcio/meta.yaml` — heavy Jinja-gated `script_env`

**Available placeholders:** Two layers — **Jinja** (rendered when meta.yaml is loaded) and **str.format** (rendered when script_env values are passed to the build).

| Placeholder | Layer | Available on | What it gives |
| --- | --- | --- | --- |
| `{{ sdk }}` | Jinja | both | SDK name: `iphoneos` / `iphonesimulator` / `android` |
| `{{ arch }}` | Jinja | both | `arm64`, `x86_64`, `arm64-v8a`, `armeabi-v7a`, `x86` |
| `{{ sdk_version }}` | Jinja | both | `13.0` (iOS) / `24` (Android) |
| `{{ version }}` | Jinja | both | The recipe's `package.version` |
| `{platlib}` | str.format | both | Cross-env's site-packages — where `flet-lib*` opt/ lands |
| `{prefix}` | str.format | both | Sysconfig prefix (`/usr/local` on Android — anonymized) |
| `{include}`, `{stdlib}`, `{scripts}`, `{purelib}` | str.format | both | Other sysconfig paths |
| `{sysconfigdata_name}` | str.format | both | e.g. `_sysconfigdata__iphoneos_arm64-iphoneos` |
| `{py_version_short}` | str.format | both | `3.12` |
| `{NDK_ROOT}` | str.format | Android | NDK install root |
| `{NDK_SYSROOT}` | str.format | Android | NDK sysroot dir |
| `{ANDROID_ABI}` | str.format | Android | Same as `{{ arch }}` on Android, but in str.format scope |
| `{ANDROID_API_LEVEL}` | str.format | Android | Same as `{{ sdk_version }}` on Android |
| `{HOST_TRIPLET}` | str.format | Android | e.g. `aarch64-linux-android` |
| `{MESON_CROSS_FILE}` | str.format | both | Only set during meson builds |
| `{CC}`, `{CXX}`, `{AR}`, etc. | str.format | both | Compiler toolchain paths |
| `{CFLAGS}`, `{LDFLAGS}`, etc. | str.format | both | Compiler/linker flags as composed by forge |
| `{PYO3_CROSS_LIB_DIR}` | str.format | both | For Android: `<install>/lib/python3.12`; for iOS: platform-config dir |

> **Important gotcha:** `{{ arch }}` and `{{ sdk }}` are **Jinja-only** — they get rendered when the recipe is loaded. They're NOT str.format placeholders, so writing `arch={arch}` in a `script_env` value will raise `KeyError: 'arch'` at build time. For Android-equivalents in str.format scope use `{ANDROID_ABI}` and `{ANDROID_API_LEVEL}`. For iOS, use Jinja `{{ arch }}` / `{{ sdk }}` which get rendered before forge invokes the build.
>
> Source: `compile_env()` in `src/forge/build.py:394-462` (env keys, str.format scope) plus `cross_venv.scheme_paths` + `cross_venv.sysconfig_data` (sysconfig keys, str.format scope) plus `package.py:81` (Jinja context).

---

## Pattern F: Meson / CMake builds

**When:** upstream uses meson-python or scikit-build-core (CMake). Common in numerical/scientific packages.

**meta.yaml for meson:**

```yaml
package:
  name: <pypi-name>
  version: <version>
requirements:
  build:
    - meson
    - ninja
build:
  backend-args:
    # Forge auto-generates a meson cross-file (see _create_meson_cross
    # in build.py:832). We just need to tell meson to use it.
    - -Csetup-args=--cross-file
    - -Csetup-args={MESON_CROSS_FILE}
  meson:
    # Optional: override entries in the auto-generated meson cross-file.
    properties:
      longdouble_format: IEEE_QUAD_LE
```

**meta.yaml for CMake:**

```yaml
package:
  name: <pypi-name>
  version: <version>
build:
  script_env:
# {% if sdk == 'android' %}
    CMAKE_ARGS: >-
      -DANDROID=ON
      -DCMAKE_TOOLCHAIN_FILE={NDK_ROOT}/build/cmake/android.toolchain.cmake
      -DANDROID_ABI={arch}
      -DANDROID_PLATFORM=android-{{ sdk_version }}
      -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-z,max-page-size=16384"
# {% else %}
    CMAKE_ARGS: >-
      -DCMAKE_SYSTEM_NAME=iOS
      -DCMAKE_OSX_SYSROOT={{ sdk }}
      -DCMAKE_OSX_ARCHITECTURES={{ arch }}
      -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0
# {% endif %}
```

Two Jinja styles coexist in CMake recipes: `{{ var }}` rendered by the meta.yaml loader, and `{var}` rendered later by Python `str.format`. Don't worry about it — both work. See the placeholder table in "Cross-cutting conventions" for which placeholder lives in which layer.

**Real examples:**
- `recipes/numpy/meta.yaml` — meson + `properties.longdouble_format` override
- `recipes/matplotlib/meta.yaml` — meson + Android CPPFLAGS override
- `recipes/grpcio/meta.yaml` — partial CMake via the upstream's `setup.py` shim
- `recipes/opencv-python/meta.yaml` — full CMake recipe with both Android and iOS branches

### Sub-pattern: scikit-build-core packages (Cython + CMake)

When upstream's `pyproject.toml::build-system.requires` includes `scikit-build-core`, the build is CMake-driven *and* compile-time Cython generation may happen inside CMake. This is a different pain surface than plain CMake — scikit-build-core's FindPython runs cross-compile-aware logic that needs careful handling on both platforms.

**Things scikit-build-core hits that plain CMake doesn't:**

- CMake 3.30+'s policy CMP0190 refuses to search Python's Interpreter/Compiler components during cross-compile without `CMAKE_CROSSCOMPILING_EMULATOR` set
- The Android toolchain file sets `CMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY` which restricts library searches to the NDK sysroot, breaking `find_library(... PATHS $YOUR_PREFIX NO_DEFAULT_PATH)`
- CMake on iOS silently ignores forge's CC/CXX env vars and produces native-arch binaries unless the recipe sets `CMAKE_SYSTEM_NAME=iOS` + `CMAKE_OSX_SYSROOT` + `CMAKE_OSX_ARCHITECTURES` explicitly
- Forge's `LDFLAGS` (including the Android 16KB-page-alignment flag) doesn't propagate through CMake's linker invocations — needs `CMAKE_SHARED_LINKER_FLAGS` + `CMAKE_MODULE_LINKER_FLAGS`
- If upstream's CMakeLists requires the `Development.Embed` component on Android (i.e. uses `target_link_libraries(... Python::Python)`), `Python_LIBRARY` needs to be pre-supplied and **the Android libpython must have a SONAME** (see the `forge-error-catalogue` skill). Most recipes don't need this.

**Template** (the form pyzmq needs):

```yaml
package:
  name: <pypi-name>
  version: <version>

build:
  script_env:
    # Recipe-specific env vars (e.g. ZMQ_PREFIX, OPENSSL_DIR)
    YOUR_PREFIX: '{platlib}/opt'

# {% if sdk == 'android' %}
    # Android: NDK toolchain file is non-negotiable, plus the FIND_ROOT_PATH_MODE
    # overrides, plus the 16KB linker flags, plus (if upstream uses
    # target_link_libraries(... Python::Python)) Python_LIBRARY/INCLUDE_DIR.
    CMAKE_ARGS: -DCMAKE_TOOLCHAIN_FILE={NDK_ROOT}/build/cmake/android.toolchain.cmake -DANDROID_ABI={ANDROID_ABI} -DANDROID_PLATFORM=android-{ANDROID_API_LEVEL} -DCMAKE_CROSSCOMPILING_EMULATOR=env -DPython_LIBRARY={PYO3_CROSS_LIB_DIR}/../libpython{py_version_short}.so -DPython_INCLUDE_DIR={PYO3_CROSS_LIB_DIR}/../../include/python{py_version_short} -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=BOTH -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH -DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384 -DCMAKE_MODULE_LINKER_FLAGS=-Wl,-z,max-page-size=16384
# {% else %}
    # iOS: explicit SYSROOT + ARCHITECTURES (CMake otherwise builds native arch
    # silently); CMP0190 emulator workaround; FIND_ROOT_PATH_MODE override.
    CMAKE_ARGS: -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT={{ sdk }} -DCMAKE_OSX_ARCHITECTURES={{ arch }} -DCMAKE_OSX_DEPLOYMENT_TARGET={{ sdk_version }} -DCMAKE_CROSSCOMPILING_EMULATOR=env -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=BOTH -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH
# {% endif %}

requirements:
  build:
    # scikit-build-core needs cmake — PyPI's `cmake` package bundles the binary.
    - cmake >=3.15
  host:
    - <flet-lib-dep>
# {% if sdk == 'android' %}
    - flet-libcpp-shared >=27.2.12479018   # if upstream is C++ or links a C++ dep
# {% endif %}
```

**Real example:** `recipes/pyzmq/meta.yaml`. Read the comments — every line in CMAKE_ARGS is there because something silently broke without it.

---

## Pattern G: Native library (flet-lib*)

**When:** you need a C/C++ library that isn't on PyPI and isn't already in `recipes/`. The library will be packaged as a fake "wheel" containing only `opt/lib/` and `opt/include/` — other recipes can then depend on it via `requirements.host`.

**Directory layout:**

```
recipes/flet-libZZZ/
├── meta.yaml          # describes how to fetch the source
├── build.sh           # autotools/cmake script that installs into $PREFIX
└── patches/           # optional, for config.sub fixes and similar
    └── config.patch
```

**meta.yaml** — Jinja idiom with a single conditional block at the top so future bumps are one-line edits:

```yaml
# {% set version = "X.Y.Z" %}
# {% if version.startswith('X.Y.') %}
# {%   set patch = "config-X.Y.x.patch" %}
# {% else %}
# {%   set patch = "config.patch" %}
# {% endif %}

package:
  name: flet-libZZZ
  version: '{{ version }}'

source:
  url: https://upstream.example.com/sources/libZZZ-{{ version }}.tar.gz

build:
  number: 1    # bump this when only the recipe changes, not the upstream version

patches:
  - {{ patch }}
```

**build.sh** — see `templates/build-flet-lib.sh` for the canonical autotools-with-iOS-and-Android template. The recurring patterns it encodes:

- `set -eu` (bash 3.2 compatible — no arrays)
- `if [ "$CROSS_VENV_SDK" = "android" ]; then ... else ... fi` for platform branches
- `./configure --host=$HOST_TRIPLET --prefix=$PREFIX ...`
- `make -j $CPU_COUNT && make install`
- `shopt -s nullglob` before cleanup globs to avoid "no match" failures
- Don't delete `*.a` (iOS static-only consumers need them)
- Do delete `*.la`, `*.cmake`, `pkgconfig/`, `share/` (artifacts not consumed downstream)

**Real examples:**
- `recipes/flet-libxml2/` — autotools, version-conditional patch
- `recipes/flet-libsodium/` — autotools, no patches, build.sh has iOS triplet rewrite
- `recipes/flet-libcurl/` — autotools, host dep on flet-libpsl + openssl
- `recipes/flet-libgeos/` — CMake-based (different build.sh shape)

**See the `forge-error-catalogue` skill § "autotools cross-compile pitfalls"** for the recurring config.sub, iconv, and iOS static-library issues.

---

## Pattern H: ctypes-loaded shared library (flet-lib* shared + pure-Python wrapper)

**When:** the Python package is a thin **pure-Python `ctypes` wrapper** that
`dlopen`s a C library at *runtime* (not a compiled extension that links it at
build time). Tell-tale: the package's loader calls
`ctypes.util.find_library(...)` / `ctypes.CDLL(...)`. Examples: `pyzbar`→libzbar,
`python-magic`→libmagic, many `*-ctypes` bindings.

This is fundamentally different from Patterns E/G (where a C-extension links a
**static** `flet-lib*.a` at build time). Here there is **no extension to link
into**, so the native lib must be **shared** and present, loadable, at runtime.

### The three things that make it work

1. **Build the flet-lib* as a SHARED library named `lib<name>.so`** (not the
   usual static `.a`). On iOS the "shared object" is a Mach-O dylib; still name
   it `.so` so serious-python's `*.so`→framework conversion picks it up. See
   `templates/build-flet-lib-shared.sh` — it builds shared on Android and, on
   iOS, builds **static then hand-links a shared dylib** (libtool can't emit a
   versioned darwin dylib under cross-compile — see the `forge-error-catalogue` skill).

2. **Patch the wrapper's loader** — `find_library()` returns `None` on both
   mobile platforms (no ldconfig/compiler). Patch it to try the shipped
   locations directly. The flet-lib* wheel installs to `<site-packages>/opt/lib`,
   so relative to the wrapper package (`<site-packages>/<pkg>/`) that's
   `../opt/lib`. On **iOS** the `.so` is replaced by a `lib<name>.fwork` text
   pointer — and **iOS CPython's `ctypes.CDLL` is `.fwork`-aware** (it reads the
   pointer and `dlopen`s the embedded framework binary), so loading the `.fwork`
   path Just Works. On **Android** the real `.so` sits in the app's native lib
   dir, loadable by bare name. Canonical patch (from `recipes/pyzbar/`):

   ```python
   path = find_library('zbar')
   if not path:
       import os
       _optlib = os.path.join(
           os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'opt', 'lib')
       libzbar = None
       for _cand in (os.path.join(_optlib, 'libzbar.fwork'),   # iOS
                     os.path.join(_optlib, 'libzbar.so'),       # generic
                     'libzbar.so', 'libzbar.dylib'):            # Android jniLibs / desktop
           try:
               libzbar = cdll.LoadLibrary(_cand); break
           except OSError:
               libzbar = None
       if libzbar is None:
           raise ImportError('Unable to find zbar shared library')
   else:
       libzbar = cdll.LoadLibrary(path)
   ```

3. **The wrapper's `requirements.host` lists the flet-lib*** (unconditional —
   needed on *both* platforms now). `fix_wheel` adds it as a `Requires-Dist` so
   pip pulls it automatically.

### Per-platform delivery (how the .so reaches the device)

- **Android:** `serious_python_android`'s `copyOpt_<abi>` gradle task copies
  `opt/**/*.so` into `jniLibs/<abi>/`, which lands in the APK's `lib/<abi>/`
  (in the default `dlopen` search path). Bare `CDLL("lib<name>.so")` resolves.
- **iOS:** `serious_python_darwin` converts each `opt/lib/*.so` into an embedded
  `<dotted.path>.framework` and replaces the file with a `lib<name>.fwork` text
  pointer at `<site-packages>/opt/lib/lib<name>.fwork`. The `.fwork`-aware ctypes
  loads it from there.

### iOS gotcha: build the flet-lib* for ALL THREE iOS slices

serious-python's iOS xcframework merge uses **`iphoneos.arm64` as the reference
slice to *discover* `.so` files**. If the flet-lib* exists only for
`iphonesimulator.arm64` (e.g. you only built that one), the lib is never found
during conversion and is **silently absent** from the bundle (the wrapper then
fails with "Unable to find … shared library"). Always `forge iOS <flet-lib>`
(all of iphoneos.arm64 + iphonesimulator.arm64 + iphonesimulator.x86_64) — and
likewise build the pure-Python wrapper for all three (its wheel is per-slice
tagged even though pure-Python).

**Real example:** `recipes/flet-libzbar/` (shared, Android+iOS) + `recipes/pyzbar/`
(loader patch, `source.url` for a sdist-less package). On Android, zbar also
needs `flet-libiconv` (see the `forge-error-catalogue` skill § iconv).

---

## Pattern I: C-extension that links a native lib via a `*-config` tool (flet-lib* static + config-shim)

**When:** the package is a **compiled C-extension** (not a ctypes wrapper) that
links a big external C library at *build time*, and its `setup.py` locates that
library by shelling out to a `*-config` helper (`pg_config`, `mysql_config`,
`pcre-config`, `xml2-config`, `curl-config`, …) rather than `pkg-config`.
Examples: `psycopg2`→libpq (`pg_config`), `mysqlclient`→libmysqlclient
(`mysql_config`). This is Pattern E/G specialised for the "upstream runs a
config binary" case.

Three things make it work:

### 1. The flet-lib* ships a **static, PIC, self-contained** archive

- **Static + folded in:** build the native lib `--static`, link it into the
  extension `.so` at build time. No runtime native lib to ship (unlike Pattern H).
- **PIC is mandatory.** Many libraries compile their *static* `.a` **without**
  `-fPIC` (the PIC objects go into a separate `*_shlib.o` used only for their own
  `.so`). But the extension you link it into (`_psycopg.so`) is a **shared**
  object, so every archived object must be position-independent or AArch64's
  linker rejects it: `relocation R_AARCH64_ADR_PREL_PG_HI21 cannot be used
  against symbol '…'; recompile with -fPIC`. Force it in build.sh:
  ```bash
  export CFLAGS="${CFLAGS:-} -fPIC"   # append — keep the cross sysroot/16KB flags
  ```
- **Merge dependent archives.** A lib's public `.a` often depends on sibling
  static archives (libpq.a needs libpgcommon.a + libpgport.a). The consumer's
  "static link" only pulls the one named `.a`, so merge them into one with `ar`:
  ```bash
  "$AR" -M <<EOF
  create libpq_merged.a
  addlib libpq.a
  addlib $BUILD_DIR/src/common/libpgcommon.a
  addlib $BUILD_DIR/src/port/libpgport.a
  save
  end
  EOF
  mv libpq_merged.a libpq.a && "$RANLIB" libpq.a
  ```
  **On iOS the `ar -M` MRI script doesn't work** — Apple's `ar` has no MRI mode.
  Use the native combiner instead: `xcrun libtool -static -o libpq_merged.a a.a
  b.a c.a` (it ranlibs the result too). Branch on `$CROSS_VENV_SDK`.

**Extra iOS gotchas for autotools native libs** (learned building flet-libpq):

- **Rewrite the Apple triplet** so PostgreSQL's `config.sub` accepts it — it
  knows `*-apple-darwin*` but not `*-apple-ios*`. Map `arm64-apple-ios`→
  `arm-apple-darwin23`, `arm64-apple-ios-simulator`→`aarch64-apple-darwin23`,
  `x86_64-apple-ios-simulator`→`x86_64-apple-darwin23` (mirrors flet-libsodium).
- **Pin the sysroot.** PostgreSQL's `src/template/darwin` runs `xcrun
  --show-sdk-path` when `PG_SYSROOT` is unset — that returns the *macOS* SDK on
  the build host, the wrong headers for an iOS target. Force it:
  `export PG_SYSROOT=$(xcrun --sdk "$SDK" --show-sdk-path)`.
- **Strip literal quotes from `LDFLAGS`.** forge's iOS `LDFLAGS` contains
  `-F "<framework path>"` with *literal* double quotes. Autotools libs that bake
  raw flags into a C string (PostgreSQL's `config_info.c` embeds `CONFIGURE_ARGS`
  into `pg_config.h`) get a broken string literal → `use of undeclared identifier
  '<path-component>'`. The path has no spaces, so
  `export LDFLAGS=$(printf '%s' "${LDFLAGS:-}" | tr -d '"')`.

### 2. The flet-lib* ships a **portable `*-config` shim**

The real `*-config` is often a target-arch binary that can't run on the build
host, or hard-codes the build prefix. Replace it with a tiny `/bin/sh` script
that derives its prefix from **its own location** and echoes what the consumer
queries (`--includedir`, `--libdir`, `--version`, …). Install it at
`$PREFIX/bin/<tool>` and `chmod 755` it. See `recipes/flet-libpq/build.sh` for a
complete `pg_config` shim. (The wheel preserves the +x bit; the shim runs on the
build host during the consumer's `setup.py`.)

### 3. The consumer recipe points the build at the shim via `script_env`

```yaml
package:
  name: psycopg2
  version: 2.9.12
patches:
  - mobile.patch          # teach setup.py to read the env vars below
build:
  script_env:
    PG_CONFIG: '{platlib}/opt/bin/pg_config'   # {platlib} → the host-dep's install root
    PSYCOPG2_STATIC_LIBPQ: '1'                  # force static link of the merged .a
requirements:
  host:
    - flet-libpq 16.9     # the flet-lib* above
```

`{platlib}` expands to the crossenv site-packages where `flet-libpq`'s `opt/` was
installed, so `{platlib}/opt/bin/pg_config` is the shim's runtime path. If
upstream's `setup.py` doesn't already honor an env var for the config-tool path
(psycopg2 doesn't — it only reads `--pg-config`/setup.cfg/PATH), a tiny patch
makes it read `os.environ`:

```python
self.pg_config_exe = self.build_ext.pg_config
if not self.pg_config_exe:
    self.pg_config_exe = os.environ.get('PG_CONFIG')   # <-- added
if not self.pg_config_exe:
    self.pg_config_exe = self.autodetect_pg_config_path()
```

**Real example:** `recipes/flet-libpq/` (PostgreSQL libpq — static, PIC, merged
`.a` + `pg_config` shim) + `recipes/psycopg2/` (env-var patch + `script_env` +
host dep). Verified on Android + iOS Simulator: `import psycopg2`,
`__libpq_version__` (a live `PQlibVersion()` call), `parse_dsn`, and
value-quoting all work with no runtime native lib. flet-libpq builds for Android
and all three iOS slices from one `build.sh` (branch on `$CROSS_VENV_SDK`).

> **Host-build caveat for the recipe-tester:** psycopg2 has **no macOS wheel** on
> PyPI (only an sdist; the binary is the separate `psycopg2-binary`). `uv run flet
> build` will try to compile it for the host and fail with `pg_config executable
> not found`. The committed `tests/recipe-tester` sidesteps this entirely —
> `uvx --with flet-cli flet build …` never installs the recipe on the host
> (it's bundled straight from `dist/` via `PIP_FIND_LINKS`).

---

## Pattern J: PEP 517 shim for no-sdist CMake giants

**When:** no sdist AND no usable `setup.py`/`pyproject.toml` at the source root —
upstream's only wheel path is a host==target build script (onnxruntime, tflite-runtime).

The recipe's `mobile.patch` **adds** a PEP 517 entry point: a `pyproject.toml` with
`build-backend = "forge_<pkg>_backend"` + `backend-path = ["_forge"]`, and a
`_forge/forge_<pkg>_backend.py` that wraps `setuptools.build_meta` and runs the cmake
configure+build before every hook (marker-file guarded, per-slice build dirs).

The full rules (each bought with a failed build) live in the `new-mobile-recipe`
SKILL.md § "Shape deep-dive: PEP 517 shim". **Real examples:**
`machine/onnxruntime:recipes/onnxruntime/` and
`machine/tflite-runtime:recipes/tflite-runtime/` (read via `git show <branch>:<path>`).

---

## Pattern K: Prebuilt-repackage + host_build chain

**When:** upstream publishes official prebuilt mobile archives of a big native lib AND
the consumer's own build system knows how to link + re-ship the `.so`
(flet-libonnxruntime → sherpa-onnx).

A `build.sh` flet-lib recipe repackages the prebuilt archive into `$PREFIX/{lib,include}`;
the consumer declares it in `requirements.host_build` (link-time only, NOT promoted to
`Requires-Dist`) and re-ships the `.so` in its own wheel with an RTLD_GLOBAL ctypes
preload patch.

Full rules in the `new-mobile-recipe` SKILL.md § "Shape deep-dive: prebuilt-repackage".
**Real example:** `machine/sherpa-onnx:recipes/flet-libonnxruntime/` +
`machine/sherpa-onnx:recipes/sherpa-onnx/`. CI consequence: this is a chain recipe —
see the `forge-ci` skill.

---

## Cross-cutting conventions

### Version specifiers in requirements

Forge parses `requirements.host` / `requirements.build` strings per `build.py:67-78`:

| Recipe writes | Pip sees |
| --- | --- |
| `openssl 3.0.15` | `openssl==3.0.15` |
| `openssl >=3.0.15` | `openssl>=3.0.15` |
| `openssl ^3.0.12` | `openssl>=3.0.12` |
| `numpy ~2.0` | `numpy~=2.0` |
| `cython <3.1` | `cython<3.1` |

Use `>=` for cross-recipe flet-lib* deps (forward-compat) and `==` only when you've validated a specific peer-build pair.

### Jinja `sdk` values

The Jinja `sdk` variable is the **SDK string**, not the OS name. Values:

- iOS: `'iphoneos'`, `'iphonesimulator'`
- Android: `'android'`
- tvOS: `'appletvos'`, `'appletvsimulator'`
- watchOS: `'watchos'`, `'watchsimulator'`

So:

```yaml
# CORRECT — matches all 3 iOS slices via a single negative branch
# {% if sdk == 'android' %}
# CORRECT — explicit two-arm
# {% if sdk in ['iphoneos', 'iphonesimulator'] %}

# WRONG — sdk is never 'iOS', this branch never matches
# {% if sdk == 'iOS' %}
```

`recipes/numpy/meta.yaml` accidentally uses the wrong form (`sdk == 'iOS'`); don't copy that pattern.

### `build.number`

Integer in `build:`, schema default **1** (`src/forge/schema/meta-schema.yaml`) — and `1` is the repo convention (start every new recipe there). Bump when the recipe itself changes but the upstream version doesn't — pip prefers higher build numbers for the same version, and the new build gets a distinct filename (`<pkg>-<ver>-N-<tag>.whl`). Important for forcing redeploys when patching.

Don't write `number: 0`: forge only passes `--build-number` when the value is truthy (`build.py`), so `0` produces a wheel with NO build tag — losing the ability to supersede it later without a version bump.

### Source layout

`source:` is optional. Defaults:

- Omit / `pypi` — resolve sdist URL via PyPI JSON API
- `url: https://...` — fetch any tarball/zip from a URL
- `git_url + git_rev` — clone a git repo at a ref *(schema-defined but NOT
  implemented in either builder — don't use yet)*
- `path: <local-dir>` — copy from a local directory *(also unimplemented)*
- `null` — the build.sh script will get its own source (rare)

For `flet-lib*` recipes, always use an explicit `url:` (the libraries aren't on PyPI).

**`source.url` works for Python packages too** (not just `flet-lib*`). This is
the fix for packages that publish **wheels but no sdist** on PyPI (e.g. pyzbar):
point `source.url` at a GitHub release/tag archive and forge's
`PythonPackageBuilder` downloads + unpacks + patches + builds from it. `{version}`
is a str.format placeholder filled at download time:

```yaml
package: {name: pyzbar, version: 0.1.9}
source:
  url: https://github.com/NaturalHistoryMuseum/pyzbar/archive/refs/tags/v{version}.tar.gz
```

The download is named `<name>-<version><ext>` in `downloads/` (collision-free).
When `source` is omitted the PyPI sdist path is used exactly as before.

### Rust packages that pin a toolchain (rust-toolchain.toml)

Some Rust packages pin a specific (often nightly) toolchain via
`rust-toolchain.toml` (polars pins `nightly-YYYY-MM-DD`). rustup auto-installs
the *toolchain* on first build, but **not the cross targets for it** — you'll
hit `error[E0463]: can't find crate for 'core'`. Add the mobile targets to that
exact toolchain:

```bash
rustup target add --toolchain <pinned-nightly> \
  aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios \
  aarch64-linux-android arm-linux-androideabi x86_64-linux-android i686-linux-android
```

(The plain `rustup target add …` only covers the default/stable toolchain.)

### `--strip` for unusual archive layouts

Default behavior: `tarfile.extractall(strip=1)` — strips one top-level directory. If your source archive has a different layout, set:

```yaml
source:
  url: ...
  strip: 0    # don't strip; archive contents go directly into build dir
  # or strip: 2 for double-nested archives
```

Rare. Most archives follow the `name-version/...` convention.
