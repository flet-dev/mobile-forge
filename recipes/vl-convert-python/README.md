# vl-convert-python

[`vl-convert-python`](https://github.com/vega/vl-convert) converts
[Vega-Lite](https://vega.github.io/vega-lite/) and [Vega](https://vega.github.io/vega/)
chart specifications to SVG, PNG, JPEG and PDF. It is the engine behind
[Altair](https://altair-viz.github.io/)'s `chart.save("chart.png")`. In a Flet app, the chart
is compiled and rendered on the device, so a spec turns into an image without a WebView, a
server or a network connection.

The mobile wheel runs Vega's JavaScript on [QuickJS-ng](https://github.com/quickjs-ng/quickjs)
instead of the V8 the desktop wheel embeds, which vl-convert cannot ship for iOS or Android
(see Build notes). The Python API is the same as on the desktop.

## Install

Give `vl-convert-python` a 2.0 lower bound in your `pyproject.toml`, and leave `armeabi-v7a`
out of the Android targets:

```toml
dependencies = [
    "flet",
    "vl-convert-python>=2.0.0rc7",
]

[tool.flet.android]
target_arch = ["arm64-v8a", "x86_64"]
```

**The bound keeps desktop and mobile on the same API.** The mobile wheel exists only for the
2.0 series. A mobile build picks it without the bound, since it is the only mobile wheel, but
`flet run` on a desktop then installs PyPI's 1.x, which has no `vl_convert.asyncio` or
`configure`: code that works on the phone fails with `AttributeError` at your desk. Naming a
pre-release in the bound is also what lets the resolver choose one.

**There is no 32-bit ARM wheel.** `flet build apk` targets every ABI by default, so without the
`target_arch` line the `armeabi-v7a` resolve fails and takes the whole build with it. `x86_64`
is the emulator; use `["arm64-v8a"]` alone for a device-only release.

Altair is pure Python: add it to the same list and `chart.save(...)` finds the mobile
`vl-convert-python`. Altair tells vl-convert which Vega-Lite version to compile with, and
vl-convert accepts only the versions it bundles (`vlc.get_vegalite_versions()`), so a newer
Altair can outrun the wheel; 6.3.0 is the version tested.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`chart-gallery`](examples/chart-gallery) — converts three Vega-Lite specs to PNG and shows
  how long each conversion took.

## Usage in a Flet app

A spec is a dict (or a JSON string). Convert it and hand the bytes to
[`ft.Image`](https://flet.dev/docs/controls/image/):

```python
import vl_convert as vlc

png = vlc.vegalite_to_png(spec, scale=2)
chart = ft.Image(src=png)
```

`vegalite_to_svg` returns the SVG as a string and `vegalite_to_pdf` returns PDF bytes. With
Altair, call `chart.save(path)` or pass `chart.to_dict()` to the same functions.

### Storage

vl-convert keeps two caches, and each resolves its directory once, on the first conversion.
Point them at [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
before importing it:

```python
import os
import tempfile

# Absolute either way: vl-convert rejects a relative font cache directory.
cache = os.path.join(os.getenv("FLET_APP_STORAGE_CACHE") or tempfile.gettempdir(), "vl-convert")
os.environ.setdefault("V82JSC_BC_CACHE_DIR", os.path.join(cache, "bytecode"))
os.environ.setdefault("VLC_GOOGLE_FONTS_CACHE_DIR", os.path.join(cache, "google-fonts"))

import vl_convert as vlc
```

- `V82JSC_BC_CACHE_DIR` holds compiled JavaScript, about 3.3 MB. It is what makes the next
  launch fast (see below); set it to an unwritable path, or `V82JSC_NO_BC_CACHE=1`, and every
  launch recompiles Vega.
- `VLC_GOOGLE_FONTS_CACHE_DIR` holds fonts downloaded for `google_fonts=` requests. Set it to
  `none` to keep them in memory only.

Specs that read files need an absolute path and an explicit allowance: by default vl-convert
loads data over HTTP and HTTPS but not from the filesystem. See
[`configure(allowed_base_urls=...)`](https://github.com/vega/vl-convert/tree/main/vl-convert-python#readme).

### Startup and speed

The first conversion in a process starts the JavaScript runtime, and that is where the time
goes: the desktop wheel restores V8 from a snapshot in well under a second, while the mobile
build has no snapshot and evaluates Deno's runtime and Vega from scratch. Conversions after
that are quick. Measured with the example app:

| first chart | arm64 Android emulator | iOS simulator |
| --- | ---: | ---: |
| first launch, empty bytecode cache | ~10 s | ~4.4 s |
| later launches, bytecode cache in place | ~3 s | ~0.6 s |
| every conversion after the first | ~0.5 s | |

Both columns were measured on an Apple Silicon Mac, whose CPU the emulator and the simulator
both use; measure on a phone before relying on them.

Do a throwaway conversion while the user is still looking at something else, so the first real
chart is not the one that waits. `warm_up_workers()` is not enough: it starts the runtime but
leaves Vega and Vega-Lite to load on the first conversion.

```python
page.run_thread(vlc.vegalite_to_svg, {"mark": "point"})
```

Do not judge startup from `flet run` on a desktop, which uses the V8 wheel and its snapshot.

### Threading

Conversions block the calling thread. Run them in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), or
use the `vl_convert.asyncio` variants from an async handler:

```python
async def show(e):
    chart.src = await vlc.asyncio.vegalite_to_png(spec, scale=2)
    page.update()
```

Conversions run on one worker by default, which keeps memory to a single JavaScript runtime.
Leave [`configure(num_workers=...)`](https://github.com/vega/vl-convert/tree/main/vl-convert-python#readme) at 1 unless you
convert in parallel and can afford one runtime per worker.

### App size

Expect about 29 MB of compressed wheel and 70 MB unpacked per Android architecture (arm64-v8a
measured), and 26 MB and 57–66 MB per iOS slice. Almost all of it is the one native module
that carries the Deno runtime, QuickJS and the bundled Vega and Vega-Lite. Use an app bundle, split APKs or a narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
that matters.

### Other considerations

A desktop `flet run` installs PyPI's V8-based wheel. Besides startup, text can differ: the
desktop wheel sees the computer's fonts, while the device has only the bundled Liberation Sans,
so a font named in a spec renders at your desk and not on the phone (see below). Check timing,
memory and typography on a device.

## Things to know

- **The device's own fonts are not found; Liberation Sans is the only one there.** The wheel
  bundles it and `sans-serif` maps to it. What happens to a family it cannot find depends on
  the output: PNG falls back to Liberation Sans, while JPEG, PDF and `svg_to_png` leave that
  text out. Name `sans-serif` or a family you registered: ship font files as
  [assets](https://flet.dev/docs/cookbook/assets) and call `vlc.register_font_directory(...)`
  with their absolute path, or request `google_fonts=[...]` with network access.
- **Remote data needs the network; inline data does not.** A spec whose `data.url` points at
  the web is fetched during conversion. On Android the HTTPS check uses the Mozilla root
  certificates bundled in the wheel, so a server signed by a certificate installed only on the
  device is rejected.
- **The first conversion is slow and the rest are not.** See [Startup and speed](#startup-and-speed);
  a spinner on the first chart is worth it even with the cache in place.

## Build notes (maintainers)

### Recipe shape

vl-convert executes Vega inside Deno, and Deno's engine is V8. V8 was the first route and was
rejected: rusty_v8 publishes no Android build at all (building it from source means hours of
GN/ninja per ABI), its iOS builds are arm64-only and jitless, and vl-convert's build-time V8
snapshot, made by a host V8 with a different configuration, cannot load on either. deno_core
0.411 can instead run on QuickJS-ng through its `deno_v8` facade, which turns the engine into
an ordinary C dependency.

Running without a snapshot exposed that Deno embeds none of its own JavaScript: extension
sources are recorded as build-machine paths and read only while a snapshot is made. The wheel
therefore embeds them (`deno_core.patch`, `deno_runtime.patch`). A QuickJS snapshot made on the
build host was the alternative and was rejected: v8x replays snapshot callbacks by op index,
Deno registers some ops per OS, and CI builds Android on Linux and iOS on macOS.

Two problems surfaced on an arm64 emulator:

- `__clear_cache` was left undefined, because rustc links with `-nodefaultlibs` and only
  aarch64 code calls it; forge now passes the NDK's compiler-rt builtins to every Android Rust
  link. CI's emulator is x86_64, so only an arm64 run catches this one.
- Rust has no native TLS on any Android ABI, so every `thread_local!` costs a pthread key, and
  one worker took about 80 of bionic's 128. The next native module to load (rpds-py, under
  Altair) aborted with `fatal runtime error: out of TLS keys`. `forge_tls.c` multiplexes all of
  the extension's keys onto one; `test_leaves_tls_keys_for_other_modules` guards it on every
  Android leg.

The Deno crates that do not compile for Android or iOS are patched through forge's
`crate_patches`, one file per crate; each preamble says why.

### Upgrade hazards

- **2.0 final, or any later release, means re-diffing every patch.** The crate patches pin
  exact versions through `Cargo.lock`, and forge refuses a crate that no longer matches.
- **deno_core's source macros.** If a new deno_core changes `include_js_files!`, the embed
  patch may still apply while sources go back to being paths. The check below catches it.
- **Six crates are not locked.** QuickJS pulls in `icu_collator`, `icu_locale`, their data
  crates, `utf16_iter` and `write16`, which upstream's V8 lockfile never needed, so cargo picks
  their newest compatible versions at build time. A build that breaks with no recipe change
  should be checked against them first.
- **v8x is a release candidate**, pulled in by `deno_v8` with an exact pin. A new deno_core
  brings a new v8x, whose 64-bit-only bindings are why `armeabi-v7a` is excluded.

### Re-verification checklist

- **No build paths in the binary:** `grep -a -o -E '/(home|Users)/[^"[:space:]]*\.(js|ts)' <so>`
  should find only vl-convert's two module specifiers (`vl-convert-index.js`,
  `vl-plugin-entry.js`). Hundreds of hits mean sources are paths again, and the worker panics
  on device with "Failed to initialize a JsRuntime: No such file or directory".
- **An arm64 device or emulator run,** not only CI, whose x86_64 emulator cannot see an
  arm64-only failure such as `__clear_cache`.
- **The TLS key test** (`test_leaves_tls_keys_for_other_modules`) and the Altair test.
- **Timings and sizes,** re-measured from the example and the wheels.

### Coverage gaps

The device tests run on CI's x86_64 Android emulator and iOS simulator, and were run on an
arm64 Android emulator by hand. They cover SVG and PNG conversion, the asyncio variants, text
rendering, the bytecode cache location, the TLS key budget (Android only) and Altair's
`chart.save`. They are network-free, so remote `data.url` loading and Google Fonts downloads
are not exercised; remote data was verified by hand on the arm64 Android emulator only. PDF
and JPEG output, Vega plugins and locales are untested on device.
