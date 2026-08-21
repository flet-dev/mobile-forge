# soxr

[`soxr`](https://github.com/dofuuz/python-soxr) is the SoX Resampler bound to Python — one
job, done well: change the sample rate of audio. It wraps
[libsoxr](https://sourceforge.net/projects/soxr/), the resampler behind SoX, and compiles it
into the wheel.

Sample-rate conversion is the step almost every on-device audio pipeline needs and almost no
model provides. A recorder hands you 44.1 or 48 kHz; speech models want 16 kHz. soxr does
that conversion in a few hundred KB of compiled code, with no FFT library, no BLAS and no
model runtime behind it.

## Install

```toml
dependencies = [
    "flet",
    "soxr",
]
```

The API takes and returns [numpy](https://numpy.org/doc/stable/) arrays, so what you pass in
decides what you get back: pass `float32` and the result is `float32`, pass `int16` and it
stays `int16`. `float64` and `int32` work too, and anything else raises.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`resample-tone`](examples/resample-tone) — converts a generated tone between rates on a
  worker thread and reports the rate, the timing and the engine in use.

## Usage in a Flet app

Two entry points cover everything.
[`soxr.resample`](https://python-soxr.readthedocs.io/en/stable/soxr.html#soxr.resample)
converts an array you already hold:

```python
import numpy as np
import soxr

y = soxr.resample(x, 48000, 16000)          # x: float32 array at 48 kHz
```

[`soxr.ResampleStream`](https://python-soxr.readthedocs.io/en/stable/soxr.html#soxr.ResampleStream)
keeps filter state across calls, which is what a microphone feed or a file too large to hold
at once needs:

```python
stream = soxr.ResampleStream(48000, 16000, 1, dtype="float32", quality="HQ")
out = stream.resample_chunk(chunk, last=is_final_chunk)
```

Set `last=True` exactly once, on the final chunk, to flush the filter tail — otherwise the
last few milliseconds never come out. Chunked output then concatenates to the same result as
one `resample` call over the whole signal.

Quality defaults to `HQ`, which is also the best choice on a phone: it is the highest
setting that still runs on libsoxr's SIMD engine. `VHQ` is a worse trade than it looks —
see **Things to know**.

In an app, run the conversion off the UI thread and put the result into a control:

```python
status = ft.Text()

def work():
    y = soxr.resample(x, 48000, 16000)
    status.value = f"{len(x):,} frames @48k → {len(y):,} @16k"
    page.update()          # a background thread needs this explicitly

page.add(status, ft.Button("Resample", on_click=lambda _: page.run_thread(work)))
```

### Storage

soxr reads and writes nothing: an array goes in, an array comes out, with no config
directory, no cache and no network. Audio files you keep belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
but that is your file handling, not soxr's.

soxr does not decode or encode audio files. Getting samples out of a `.wav` is the standard
library's [`wave`](https://docs.python.org/3/library/wave.html) module; any other container
or codec needs its own package.

### Threading

The compiled resampler releases the GIL around every conversion, so
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) above
buys real concurrency rather than only a responsive UI — two conversions on two threads
genuinely overlap.

Catch exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update): a background
thread does not get the automatic one. A `ResampleStream` carries filter state, so calling
`resample_chunk` on one stream from two threads at once corrupts it — give each thread its
own stream, or serialise the calls behind a lock. `run_thread` uses a pool, so two quick
taps can overlap.

### App size

Roughly 155–225 KB compressed and 300–530 KB unpacked per slice, almost all of it the one
compiled extension; `armeabi_v7a` is the smallest and `x86_64` the largest. There are no
data files. That is small enough that the decision worth making is about numpy, which the
package needs and which is many times its size — most apps reaching for a resampler already
carry it for other reasons.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the app does not need every ABI.

### Other considerations

A desktop `flet run` uses PyPI's own wheel rather than this one. The API is identical, but
the compiled engine is not always: PyPI's macOS and Linux x86_64 builds carry libsoxr's AVX
engine, which no ARM build has, so a `VHQ` timing measured at your desk does not transfer to
a phone. Time the quality setting you actually ship on a device or emulator/simulator.

## Things to know

- **`VHQ` is slower on a phone than its name suggests.** `QQ`, `LQ`, `MQ` and `HQ` all run
  on libsoxr's 32-bit SIMD engine. `VHQ` raises precision to 28 bits, which crosses into the
  double-precision engine — and that engine's SIMD variant is AVX, so on every ARM device it
  falls back to a scalar core. Prefer `HQ` unless you have measured that you need more.

- **`resample_chunk` type-checks exactly.** It tests `type(x) != np.ndarray`, so a numpy
  *subclass* is rejected with a `TypeError` naming the dtype even when the dtype is right.
  Pass `np.asarray(x)`. The dtype must also match the one given to the constructor; it is not
  converted for you.

- **Multi-channel work runs on one core.** libsoxr can split channels across threads, but
  that path is compiled out here, as it is in upstream's own wheels. The GIL is released
  during conversion, so arrange parallelism yourself with `run_thread` if you need it.

- **soxr is LGPL-2.1-or-later, and this wheel links libsoxr statically.** The licence texts
  ship inside the wheel under `dist-info/licenses/`. For an open-source app that is the end
  of it. If you are shipping a closed-source app, LGPL section 6 asks that a user be able to
  relink your app against a modified libsoxr, which a statically linked store binary does not
  offer on its own; section 6a (shipping your object files) is the usual answer where it
  matters. This is a flag, not legal advice.

## Build notes (maintainers)

### Recipe shape

scikit-build-core + CMake over a self-contained sdist that vendors libsoxr — the
[`duckdb`](../duckdb) / [`rapidfuzz`](../rapidfuzz) archetype, with no patches. Upstream
already does the things a cross build usually has to be patched into: the nanobind stub step
is guarded behind `NOT CMAKE_CROSSCOMPILING`, `vr-coefs.h` ships pre-generated so no host
code generator runs, nothing anywhere uses `try_run`, and OpenMP, the LSR bindings and shared
libraries are all turned off before `add_subdirectory(libsoxr)`.

A separate `flet-libsoxr` was considered and rejected: upstream supports
`USE_SYSTEM_LIBSOXR=ON`, but a shared libsoxr bundled inside a signed APK or IPA is no more
relinkable by the user than a static one, so it would add a recipe and a load-time dependency
without changing the licensing position that motivates it.

This is the repo's first **nanobind** recipe, which is the reason for both `meta.yaml`
settings that are not boilerplate; each is explained in a comment beside it.

### Upgrade hazards

- **A lost SIMD engine does not fail the build.** libsoxr compiles its `cr32s` core only when
  CMake can identify the target CPU, and the wheel is perfectly functional without it — just
  measurably slower. `test_simd_engine_compiled_in` is the guard; if a bump moves libsoxr's
  CMake modules, check that test before anything else.
- **`cmake/versioning.cmake` runs `git describe` against `VCS_REPO_DIR`.** Inside forge's
  build tree that walks up into mobile-forge's own repository and stamps *its* commit into
  `soxr.__libsoxr_version__`, overwriting the value the sdist ships. Cosmetic, and the inner
  `cmake -P` is a fresh cacheless invocation so `-DGIT_EXECUTABLE=` cannot reach it. **Do not
  write a test asserting `__libsoxr_version__`.**
- **`CMAKE_INSTALL_PREFIX ../install`** is set before `add_subdirectory(libsoxr)`, so
  libsoxr's own install rules resolve beside the wheel staging directory. They land outside
  the wheel today, but a layout change upstream could start leaking `lib/libsoxr.a` and the
  docs into the payload.
- **`STABLE_ABI` resolves on Apple but not under the NDK**, so the platforms ship
  structurally different modules — `soxr_ext.abi3.so` against `soxr_ext.cpython-3XX-*.so`.
  forge's `fix_wheel` rewrites the tag and accepts both, so this needs no handling; it is
  listed because it looks like a defect when diffing two wheels.

### Re-verification checklist

- **SIMD engine per slice:** `strings <so> | grep -x cr32s` on every wheel, plus the
  on-device test. `cr64s` is expected on the x86_64 slices only.
- **Wheel hygiene:** correct `Machine` per ABI, every Android `LOAD` segment aligned
  `0x4000`, `DT_NEEDED` limited to bionic plus `libc++_shared` and `libpython`, iOS
  `LC_BUILD_VERSION` platform 2 on device and 7 on the simulators.
- **METADATA:** `Requires-Dist: numpy` present, `flet-libcpp-shared` promoted on Android only.
- **Sizes:** re-measure from the wheels rather than scaling the figures above.

### Coverage gaps

The device tests cover a float32 round trip, all four dtypes in two channels, streaming
against one-shot, and the SIMD engine. They do not cover variable-rate mode (`vr=True`, which
upstream marks experimental), `num_clips()` on integer overflow, `delay()`, `clear()`,
`set_io_ratio()`, or any real audio file. `test_simd_engine_compiled_in` skips on 32-bit ARM,
where NEON is a runtime property rather than a build one, so that slice's engine is only ever
checked by inspecting the binary.
