# soundfile

[`soundfile`](https://github.com/bastibe/python-soundfile) reads and writes audio files as
numpy arrays. It is a thin cffi wrapper over
[libsndfile](https://libsndfile.github.io/libsndfile/), the C library that most of the
scientific-Python audio stack sits on — librosa, wfdb and pywavelets pipelines all expect a
`sf.read()` at the front.

The wheel here is pure Python; the audio work happens in
[`flet-libsndfile`](../flet-libsndfile), which pip pulls in automatically. That library is
built with FLAC, Ogg Vorbis, Opus and MP3 compiled in, so the container list on a phone is
the same one you get on a desktop.

## Install

```toml
dependencies = [
    "flet",
    "soundfile",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`codec-roundtrip`](examples/codec-roundtrip) — encodes a generated chord into every
  container and reports the size, time and error of each round trip.

## Usage in a Flet app

`read` and `write` cover most of it — a path or any binary file object, in and out:

```python
import soundfile as sf

data, samplerate = sf.read("clip.wav")          # float64 (frames,) or (frames, channels)
sf.write("out.flac", data, samplerate)          # format inferred from the extension
```

`dtype` decides what you get back, and it matters more on a phone than on a desktop:
`float64` is the default and doubles your memory for no accuracy you can hear.

```python
data, sr = sf.read("clip.wav", dtype="float32")     # half the RAM
data, sr = sf.read("clip.wav", dtype="int16")       # what the file already holds
```

For anything longer than a few seconds, read it in blocks rather than whole:

```python
with sf.SoundFile("long.wav") as f:
    print(f.samplerate, f.channels, len(f))         # header only, nothing decoded yet
    for block in f.blocks(blocksize=16000, dtype="float32"):
        process(block)
```

`sf.info(path)` is the cheapest call in the library — it opens the header and closes the
file, so it is how you check a samplerate or duration before deciding to decode.

### Reading audio the user picked

[`FilePicker`](https://flet.dev/docs/controls/filepicker/) hands back a path on both
platforms, and `sf.read()` takes it directly. **A real path is the only form that works
everywhere** — see the iOS note below.

Where you hold bytes instead (a download, a file read out of `assets/`), `soundfile` does
accept any file object, and on Android that works:

```python
import io

data, sr = sf.read(io.BytesIO(raw_bytes))     # Android and desktop only
```

**On iOS this raises `MemoryError`,** and no version of the package will fix it. That path
uses libsndfile's virtual I/O, which means handing the C library a `ffi.callback()`; cffi
writes that trampoline into memory at runtime, and iOS refuses write+execute pages to an
app without the JIT entitlement. The message names the cause:

    MemoryError: Cannot allocate write+execute memory for ffi.callback().

Write the bytes to a file and read that instead — it costs one write, needs no
per-platform branch, and is the recommended form on both platforms:

```python
import os

path = os.path.join(os.getenv("FLET_APP_STORAGE_TEMP"), "clip.wav")
with open(path, "wb") as f:
    f.write(raw_bytes)
data, sr = sf.read(path)
```

Only the *file-object* form is affected. Paths, and integer file descriptors (which go
through `sf_open_fd`), use no callbacks and work normally on iOS.

### Storage

`soundfile` reads and writes nothing of its own — no config, no cache, no env vars. Files you
write need a real writable directory, which on both platforms means
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables#flet_app_storage_data)
for anything the user should keep, or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables#flet_app_storage_temp)
for scratch. The app's working directory is not writable.

```python
import os

out = os.path.join(os.getenv("FLET_APP_STORAGE_DATA"), "recording.flac")
sf.write(out, data, 44100)
```

### Threading

Decoding is CPU-bound and libsndfile releases the GIL, so put it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — a background
thread does not get the automatic one. A `SoundFile` object carries a file position; do not
share one across threads, open one per thread.

### App size

`flet-libsndfile` is about 2.4 MB per Android ABI and 3.0 MB per iOS slice, all of it the
one shared library, and the `soundfile` wheel itself is around 27 KB. That figure is the
price of the codecs: an MP3 decoder, an MP3 encoder, FLAC, Vorbis and Opus account for most
of it, and there is no build flag here to drop them per app.

`numpy` is the bigger line item for an app that does not already carry it.

### Other considerations

A desktop `flet run` uses PyPI's own `soundfile` wheel, which bundles its own copy of
libsndfile 1.2.2 built with the same codec set — so the format list matches what you get on
device, which is not something you can assume for every package.

## Things to know

- **`sf.read()` defaults to `float64`.** A three-minute stereo 44.1 kHz track is 127 MB as
  `float64` and 63 MB as `float32`. On a phone that is the difference between working and
  being killed by the OS. Pass `dtype="float32"` unless you specifically need the precision,
  and prefer `blocks()` over reading whole files.

- **iOS cannot read audio from a file object.** Repeating it here because it is the one
  thing that behaves differently between the two platforms, and it fails at the point of
  use rather than at import. `io.BytesIO` in, `MemoryError` out; write a file first.

- **Opus only encodes at 48 kHz.** libsndfile will not resample for you; `sf.write(...,
  format="OGG", subtype="OPUS")` at any other rate raises. Resample first — [`soxr`](../soxr)
  is on pypi.flet.dev for exactly this.

- **Writing MP3 works, and is usually the wrong choice.** The encoder (LAME) is compiled in,
  so `sf.write("x.mp3", ...)` succeeds. For storing audio your app will read back, FLAC is
  lossless, decodes faster and is only a few times larger. MP3 is for handing a file to
  something else.

- **`sf.available_formats()` is the honest answer to "is X supported?"** It asks libsndfile's
  own registry rather than a table in Python, so it reflects this build and not upstream's
  documentation. Worth calling once in development if you are unsure about a container.

- **Lossy round trips do not line up sample-for-sample.** Vorbis, Opus and MP3 all add
  codec delay and pad the tail, so a decoded file is longer than what you encoded and
  shifted. Anything comparing audio before and after a lossy hop needs to align first — this
  surprises people writing tests far more often than it affects playback.

- **This is a `.so` the app loads at runtime, not a compiled extension.** If `import
  soundfile` fails on device with an `OSError` about finding the library, the cause is
  `flet-libsndfile` not being bundled — check it is in the build's resolved dependencies
  rather than looking for a Python-side problem.

- **libsndfile is LGPL-2.1-or-later and ships here as a replaceable shared library**, which
  is the arrangement that licence is written for; the notices ride in the wheel under
  `dist-info/licenses/`. LAME additionally asks that apps using it acknowledge LAME and link
  to its site. This is a flag, not legal advice.

## Build notes (maintainers)

### Recipe shape

Pattern H — a pure-Python wrapper plus a shared `flet-lib*` — the
[`pyzbar`](../pyzbar)/[`python-magic`](../python-magic) archetype, with one twist: the
wrapper uses **cffi**, not ctypes.

That twist is the whole reason for `patches/mobile.patch`. `ffi.dlopen()` is a raw
`dlopen(3)`, so unlike `ctypes.CDLL` it cannot dereference the `.fwork` text pointer
serious-python leaves behind when it relocates a library into an iOS framework (that
dereference lives in iOS CPython's patched `ctypes/__init__.py`, nowhere lower). The patch
therefore wraps `ctypes.util.find_library`, lets **ctypes** resolve the name, and hands cffi
the absolute path ctypes settled on (`CDLL(candidate)._name`). Candidates, in order: the bare
soname `libsndfile.so` (Android jniLibs), `opt/lib/libsndfile.fwork` (iOS framework),
`opt/lib/libsndfile.so` (not relocated). Everything downstream of `find_library` is
upstream's, untouched.

The patch is mandatory, not an optimisation: upstream's loader branches on `sys.platform`
over `darwin`/`win32`/`linux` only, and both fallbacks end in a bare `raise`. On
`android`/`ios` `import soundfile` fails outright without it.

The codec chain is six `flet-lib*` recipes — `flet-libogg`, `flet-libvorbis`,
`flet-libflac`, `flet-libopus`, `flet-libmpg123`, `flet-libmp3lame` — built as **static PIC
archives** and declared `requirements.host_build` of `flet-libsndfile`, which absorbs them
into its one shared library. They are deliberately not `requirements.host`: nothing of them
is loaded at runtime, so promoting them to `Requires-Dist` would make every consuming app
download six wheels whose contents already live inside `libsndfile.so`.

### Upgrade hazards

- **There has been no libsndfile release since 1.2.2 (August 2023).** `flet-libsndfile`
  carries `patches/security-backports.patch`, five upstream memory-safety fixes cherry-picked
  from master. When upstream finally tags a release, drop that patch and re-check
  `git log 1.2.2..<tag>` rather than assuming the list was complete.
- **soundfile's loader has no anchor comments.** The patch keys on the
  `from ctypes.util import find_library` import and on the `try:  # packaged lib` line. A
  bump that reworks the loader will need the patch rewritten, not rebased — read
  `soundfile.py`'s platform dispatch before assuming a clean apply.
- **`numpy` became a hard dependency in soundfile 0.13.0.** There is no numpy-free build.
- **soundfile's own `bdist_wheel` mis-tags under cross-compilation** — it emits
  `py2.py3-none-any` for an unknown `sys.platform`. forge's `fix_wheel` overwrites the tag,
  which is what makes our wheel outrank PyPI's `any` wheel at the same version. Do not
  "fix" the tag in a patch.
- **FLAC 1.5.0 needs `-DCMAKE_SYSTEM_VERSION` on Android** and `-DENABLE_MULTITHREADING=OFF`;
  both have comments in `recipes/flet-libflac/build.sh` saying what breaks without them.

### Re-verification checklist

- **Codecs actually linked:** `sf.available_formats()` on device must list `FLAC`, `OGG` and
  `MP3`, and `available_subtypes("OGG")` must be exactly `{VORBIS, OPUS}`. The CMake configure
  summary is not sufficient — `ENABLE_EXTERNAL_LIBS`/`ENABLE_MPEG` silently downgrade to OFF.
- **Nothing leaked from the build host:** `flet-libsndfile` passes
  `-DCMAKE_FIND_USE_CMAKE_SYSTEM_PATH=NO` so a Homebrew `flac`/`opus` cannot be found instead
  of ours. If that is ever removed, a developer machine and CI will produce different wheels.
- **Exported symbols are `sf_*` only** — `nm -gU` on iOS (41 symbols, all `_sf_`), `llvm-nm
  -D --defined-only` on Android (version-scripted `@@libsndfile.so.1.0`). The absorbed codec
  symbols must stay hidden; jniLibs is a flat namespace shared with every other native wheel.
- **Wheel hygiene:** one unversioned `opt/lib/libsndfile.so` per slice; Android `DT_NEEDED`
  limited to `libc`/`libm`/`libdl`, `SONAME` exactly `libsndfile.so`, every `LOAD` aligned
  `0x4000`; iOS `otool -L` showing only `libSystem`, filetype `DYLIB`.
- **METADATA:** `soundfile` promotes `flet-libsndfile (==1.2.2)`; the six codec libraries
  must NOT appear.

### Coverage gaps

The device tests cover loading the library, WAV round trips in three subtypes, every
container and codec, virtual I/O from `BytesIO` (Android) and its `MemoryError` on iOS,
the write-a-file workaround, block reads with seeking, and the format registry. They do not
cover: writing to `FLET_APP_STORAGE_*` (a path question, not a
libsndfile one), any real recorded audio file, `sf.info()`, the `RAW` format's manual
`samplerate`/`channels`/`subtype` arguments, or multi-threaded decoding. The security
backports are compile-verified only — there are no regression tests for the five fixes, since
reproducing them needs the malformed inputs from upstream's fuzz corpus.
