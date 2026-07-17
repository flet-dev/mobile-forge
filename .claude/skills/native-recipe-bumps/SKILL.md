---
name: native-recipe-bumps
description: Playbook for bumping native-library recipes in mobile-forge (libxml2, libxslt, openssl-class C deps and their consumers). Covers the Jinja-templated meta.yaml pattern for version-conditional URLs / patches / host pins, the build.sh quirks for cross-compiling autotools projects to iOS and Android (NDK r27d, API 24, Python 3.12), and the recurring pitfalls (iconv on Android, iOS static-only builds, bash 3.2 + set -u, etc). USE THIS SKILL when bumping the version of an EXISTING recipe — especially `flet-lib*` ones. Sibling skills — `new-mobile-recipe`: creating a recipe from scratch (use that instead for new packages); `forge-error-catalogue`: error → fix mappings when the bumped build fails; `local-recipe-testing`: on-device verification; `forge-ci`: pushing/dispatching the bump.
---

# Bumping native-library recipes in mobile-forge

This skill captures conventions for editing recipes in `recipes/<pkg>/` so that:
- the new version builds on iPhoneOS, iPhoneSimulator, and Android API 24, and
- the recipe stays back-compatible — flipping one Jinja `version` line at the top reverts to the previously-pinned version (URL, patches, host deps follow automatically).

## File layout per recipe

```
recipes/<pkg>/
  meta.yaml                        # rendered through Jinja before YAML parsing
  build.sh                         # optional; for autotools / make-based deps
  patches/
    mobile-<X.Y.x>.patch           # one per supported version line
    mobile-<X.Z.x>.patch
```

## meta.yaml: the Jinja idiom

`src/forge/package.py` runs the file through `jinja2.Template(...).render(sdk=..., sdk_version=..., arch=..., version=..., py_version=...)` *before* `yaml.safe_load`. Two patterns matter:

**1. Comment-prefixed Jinja (`# {% ... %}`)** — the only form that keeps the YAML linter happy. `{% set %}` / `{% if %}` lines that don't produce YAML output should always be `# {% ... %}`. The `#` plus blank rendered output is a no-op for YAML. This is the same idiom `recipes/numpy/meta.yaml` uses.

**2. Single conditional block sets every dependent variable** — version, host-dep versions, patch filename, anything else that branches by version. Then the body of the file just interpolates `{{ var }}`. Avoid scattering multiple `{% if %}` blocks throughout the file.

Canonical shape (from `recipes/flet-libxslt/meta.yaml`):

```yaml
# {% set version = "1.1.45" %}
# {% if version == "1.1.32" %}
# {%   set libxml2_version = "2.9.8" %}
# {%   set patch = "mobile-1.1.32.patch" %}
# {% else %}
# {%   set libxml2_version = "2.15.3" %}
# {%   set patch = "mobile-1.1.45.patch" %}
# {% endif %}

package:
  name: flet-libxslt
  version: '{{ version }}'

source:
  url: https://download.gnome.org/sources/libxslt/{{ version.rsplit('.', 1)[0] }}/libxslt-{{ version }}.tar.xz

requirements:
  host:
    - flet-libxml2 {{ libxml2_version }}

patches:
  - {{ patch }}
```

To go back to 1.1.32: change one line at the top — URL, host requirement, and patch all flip in lockstep.

### URL templating for GNOME tarballs

`https://download.gnome.org/sources/<pkg>/<X.Y>/<pkg>-<X.Y.Z>.tar.xz` — directory is major.minor, file is full version:

```
url: https://download.gnome.org/sources/libxml2/{{ version.rsplit('.', 1)[0] }}/libxml2-{{ version }}.tar.xz
```

`version.rsplit('.', 1)[0]` turns `2.15.3` → `2.15`, `2.9.8` → `2.9`.

### SDK-conditional script_env

The Jinja `sdk` variable holds `'iphoneos'`, `'iphonesimulator'`, or `'android'`. The framework formats `script_env.LDFLAGS / CFLAGS / CPPFLAGS` by *appending* to the compiler-derived value (other keys are set verbatim). Use this for platform-specific link flags:

```yaml
build:
  script_env:
    WITH_XML2_CONFIG: '{platlib}/opt/bin/xml2-config'
# {% if sdk != 'android' %}
    LDFLAGS: -liconv
# {% endif %}
```

`numpy/meta.yaml` writes `sdk == 'iOS'` — that branch never matches the values that are actually passed (the per-slice SDK names). Don't copy that comparison; use `sdk == 'iphoneos'` / `sdk == 'iphonesimulator'` / `sdk == 'android'`.

When a bump adds a platform-gated dep to a list that would otherwise be EMPTY on the other platform, guard the whole KEY (`host:`), not just the entry — an empty rendered list is `None` and fails schema validation. See the `forge-error-catalogue` entry "`None is not of type 'array'`".

## Patches

Patches in `meta.yaml`'s `patches:` list are simple filenames in `patches/`. The framework has *no* conditional-patch support — don't extend the schema for it. Put the conditional in Jinja:

- one patch file per supported version line, named `mobile-<X.Y.x>.patch`
- `# {%   set patch = "mobile-X.Y.x.patch" %}` inside the version block
- `patches: [{{ patch }}]` in the body

When a patch needs to apply across both old and new versions (e.g. lxml's `setupinfo.py` macOS-SDK filter), keep it as a single `mobile.patch` and don't introduce conditional naming. Verify with `patch --dry-run -p1 --ignore-whitespace < patches/mobile.patch` against both extracted tarballs before committing.

### Renaming with `git mv`

When splitting `mobile.patch` into `mobile-X.Y.x.patch` + `mobile-A.B.x.patch`, do `git mv` for the original then add the new file — git detects the rename and history is preserved.

## build.sh patterns

### Bash 3.2 + `set -u` compatibility

macOS still ships bash 3.2. Two gotchas:

- **No bash arrays for optional flags** — `"${arr[@]}"` on an empty array under `set -u` errors with `unbound variable`. Use a plain string:
  ```bash
  if [ "$CROSS_VENV_SDK" = "android" ]; then
      iconv_arg=--without-iconv
  else
      iconv_arg=--with-iconv
  fi
  ./configure ... $iconv_arg
  ```
- **`shopt -s nullglob` for cleanup globs** — without it, `rm -r $PREFIX/lib/*.la` passes literal `*.la` when nothing matches and fails. Combined with `rm -rf` it makes cleanup tolerant of layout changes between versions.

### Cleanup recipe

```bash
shopt -s nullglob
rm -rf $PREFIX/share
rm -rf $PREFIX/lib/cmake $PREFIX/lib/pkgconfig $PREFIX/lib/*.la $PREFIX/lib/*.sh
```

**Do *not* delete `*.a`.** iOS only builds static archives. Removing them leaves `lib/` empty, and downstream consumers (lxml, libxslt) that want to link statically have nothing to find. Android only produces `*.so` so the `.a` line would be a no-op there anyway.

### Available env vars in build.sh

The framework exposes (see `compile()` in `src/forge/build.py`):

- `HOST_TRIPLET`, `HOST_ARCH`, `BUILD_TRIPLET`
- `SDK`, `SDK_VERSION`, `SDK_ROOT` (empty for Android)
- `CROSS_VENV_SDK` — same as `SDK`, the canonical "is this Android?" check
- `PREFIX` — install root (`<build>/wheel/opt`)
- `PYTHON_PREFIX`, `PLATLIB`
- `CPU_COUNT`, plus `CC` / `CXX` / `AR` / `STRIP` / `RANLIB` / `CFLAGS` / `CPPFLAGS` / `LDFLAGS`

There is **no** `RECIPE_DIR` env var. Don't try to apply patches from build.sh — let the framework's `patch_source()` do it.

### Skipping CLI binary subdirs

When a project's autotools build links a CLI tool against the library and that tool can't be linked on iOS (e.g. xsltproc using libxml2 symbols not in the iOS SDK's `libxml2.tbd`), restrict recursion:

```bash
make -j $CPU_COUNT V=1 SUBDIRS='lib1 lib2'
make install SUBDIRS='lib1 lib2'
```

This is cleaner than fighting the linker — wheels don't ship CLI tools anyway.

## Cross-compile pitfalls (catalogue)

- **Android NDK r27d API 24 has no `iconv`** in bionic (added in API 28). For libxml2 ≥ 2.10 configure makes iconv mandatory by default (silent soft-fail in 2.9.x). Pass `--without-iconv` for Android only; iOS has system iconv.
- **iOS builds static-only**, Android builds shared-only with this toolchain. Don't assume both produce both.
- **iOS SDK ships `libxml2.tbd` with an *old* libxml2 API.** When statically linking our newer libxml2 into a CLI binary, the linker pulls the SDK stub for unresolved transitive symbols and fails. For a wheel target this only matters if you build a binary; for shared-object Python extensions, dyld resolves at load time so it's fine.
- **iOS linker doesn't auto-add `-liconv`.** When libxml2 is built with iconv and linked statically into something else, the consumer must add `-liconv` explicitly. lxml's `setupinfo.libraries()` lists `xslt exslt xml2 z m` only, so push `-liconv` via `script_env.LDFLAGS` for non-Android.
- **macOS SDK include leaks into cross-build.** lxml's `xml2-config --cflags` parsing picks up `-I…/MacOSX.sdk/usr/include`. The recipe ships a `mobile.patch` to filter that out — apply or carry forward when bumping lxml.
- **Header reshuffles.** libxml2 < 2.15 installs to `$includedir/libxml2/libxml`; the build.sh `mv $PREFIX/include/libxml2/libxml $PREFIX/include` flatten still applies in 2.15.x — re-check on future bumps.
- **`libxml2.syms` was removed upstream around 2.10.** Old `mobile.patch`es that comment out `docb*` / `xmlDllMain` symbols don't apply to ≥ 2.10 and are unnecessary there (modern config.sub already handles `*-apple-ios`).
- **`config.sub` in modern releases handles `*-apple-ios` natively** but still rejects `*-apple-ios-simulator` (kernel=ios, os=simulator combo not whitelisted). The minimal patch is to add an `ios-simulator*)` case in the `case $basic_os in` block that sets `kernel=` and `os=$basic_os`.

## Verification before re-running `forge build`

Cheap checks worth doing in-shell, without spinning up the cross-venv:

```bash
# Render meta.yaml with both target versions and inspect the parsed result
source venv3.12/bin/activate && python -c "
import jinja2, yaml
with open('recipes/<pkg>/meta.yaml') as f:
    tpl = f.read()
for v in ['<new>', '<old>']:
    src = tpl.replace('<new>', v, 1) if v != '<new>' else tpl
    rendered = jinja2.Template(src).render(sdk='iphoneos', sdk_version='13.0', arch='arm64', version=None, py_version=None)
    print(yaml.safe_load(rendered))
"

# Confirm patches still apply against fresh tarballs
cd /tmp && tar xf <pkg>-<ver>.tar.xz && cd <pkg>-<ver>
patch --dry-run -p1 --ignore-whitespace < /path/to/recipes/<pkg>/patches/mobile-<X.Y.x>.patch

# Quick triplet sanity check on a config.sub patch
./config.sub aarch64-apple-ios-simulator
./config.sub x86_64-apple-ios-simulator
./config.sub aarch64-linux-android
```

Render with both `sdk='iphoneos'` and `sdk='android'` whenever the file has SDK conditionals.

## Build / debug loop

`forge` takes a *host* (top-level platform name like `iOS`/`android`, or a `platform:arch` / `platform:version:arch` triple) followed by one or more recipe names. There is no `build` subcommand.

```bash
# Single arch — fastest iteration, good for quick tests
forge iphoneos:arm64 flet-libxslt
forge iphonesimulator:arm64 flet-libxslt
forge iphonesimulator:x86_64 flet-libxslt
forge android:arm64-v8a flet-libxslt
forge android:armeabi-v7a flet-libxslt
forge android:x86_64 flet-libxslt
forge android:x86 flet-libxslt

# All arches for one platform
forge iOS flet-libxslt
forge android flet-libxslt

# Override the version without editing meta.yaml ('<pkg>:<ver>')
forge android flet-libxslt:1.1.32
forge iphoneos:arm64 lxml:5.3.0

# Override version + build number ('<pkg>:<ver>::<build>' or ':<ver>:<build>')
forge android flet-libxslt:1.1.45::1

# Useful flags
forge --clean iphoneos:arm64 flet-libxml2     # wipe build dir first
forge -v iOS lxml                             # verbose log
forge --all-versions iOS lxml                 # build every supported version
```

Recipes can also be addressed by path (anything containing a slash): `forge iOS ./recipes/lxml`.

After a failure, the latest log lives at `errors/<pkg>-<ver>-<sdk_tag>.log` (or `errors/<pkg>-<ver>-cp312-<sdk_tag>.log` for Python packages). It includes the full stderr+stdout *plus* the recipe's environment dumped near the bottom — useful for confirming `CROSS_VENV_SDK`, `PREFIX`, etc. were what you expected.

When a build mostly succeeds and dies in cleanup, look at the last `<<< Return code: N` line and the immediately preceding shell error — most "failed" libxml2/libxslt builds are post-install `rm` errors, not real build failures.

## Recipes that already follow these conventions

- `recipes/flet-libxml2/` — Jinja version + iconv conditional in build.sh, two version-suffixed patches.
- `recipes/flet-libxslt/` — single Jinja block sets version + libxml2 dep + patch; SUBDIRS override to skip xsltproc.
- `recipes/lxml/` — version-conditional libxml2/libxslt host pins; SDK-conditional `LDFLAGS=-liconv`; carries `mobile.patch` for the macOS SDK include filter.
- `recipes/flet-libopaque/` — minimal `{% set version %}` + URL template, no version branching needed.
- `recipes/numpy/` — selective patch via Jinja + override-version (`{% if version and version < (2, 0) %}`); shows the override-driven pattern when versions need to be flippable from the CLI rather than the meta.yaml itself.

Newer `flet-lib*` shapes worth knowing when bumping (fork branches; read via `git show <branch>:<path>`):

- `machine/audioflux:recipes/flet-libfftw/` — classic autotools build.sh, both platforms.
- `machine/h5py:recipes/flet-libhdf5/` — **CMake** build.sh. Two bump-relevant tells: build.sh recipes must declare their tools in `requirements.build` (`[cmake]` — the pip shim isn't seeded otherwise), and hdf5 1.14.3 is the cross-compile floor (older versions run target codegen binaries on the host).
- `machine/sherpa-onnx:recipes/flet-libonnxruntime/` — **prebuilt-repackage**: no compile at all; `source.url` points at upstream's official mobile archive and build.sh restages it. Bumping = new archive URL + re-verifying 16KB `LOAD` alignment of the prebuilt `.so` (`llvm-readelf -l`). Note forge strips the archive's leading path component on unpack.
- `machine/onnxruntime:recipes/onnxruntime/` — the `{% set version = "X.Y.Z" %}`-as-first-line idiom reused in `package.version` AND `source.url`, making a bump a one-line edit. Prefer this shape for any new recipe you touch.
