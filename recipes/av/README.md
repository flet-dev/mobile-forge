# av

[`av`](https://pyav.basswood.io) (PyAV) is a Cython binding to FFmpeg's libraries — containers,
streams, packets, codecs and frames as Python objects, with the pixel and sample data reachable
in place. On mobile that is the only way to get at them: you cannot ship an `ffmpeg` binary in
an app bundle, and neither iOS nor Android will let you spawn one. The wheel carries its own
FFmpeg, so what your app can decode is fixed by the wheel and not by the OS underneath it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "av",
]
```

**iOS needs Flet 0.86.0 or newer.** The FFmpeg libraries ship as dylibs that flet relocates
into the app's frameworks, and reconciling the `@rpath` references between them landed in
serious_python 4.3.2 — the version Flet 0.86.0 is the first to pin (0.85.2 pins 1.0.0, which
has no such pass). Below that the app dies at launch, before Python starts, with
`dyld: Library not loaded: @rpath/libavutil.dylib`. A bare `flet` resolves to the latest
release, so this only bites if something in your project holds Flet back.

This is one of the larger wheels on the index — see [App size](#app-size) before adding it to
an app that has a download-size budget.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`clip-roundtrip`](examples/clip-roundtrip) — writes an MP4, reopens it, and puts the frames
  it reads back on screen.

## Usage in a Flet app

Open a file, decode a frame, and re-encode it as a JPEG for
[`ft.Image`](https://flet.dev/docs/controls/image/), which takes encoded bytes rather than raw
pixels:

```python
import io
import os

import av
import flet as ft


def first_frame(path: str, width: int = 320) -> bytes:
    """Decode the first video frame of `path` and return it as JPEG bytes."""
    with av.open(path) as container:
        frame = next(container.decode(video=0))

    height = width * frame.height // frame.width
    scaled = frame.reformat(width=width, height=height, format="yuvj420p")

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mjpeg") as out:
        stream = out.add_stream("mjpeg", rate=1)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuvj420p"
        out.mux(stream.encode(scaled))
        out.mux(stream.encode(None))
    return buffer.getvalue()


clip = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "clip.mp4")
page.add(ft.Image(src=first_frame(clip), width=320))
```

### Storage

Media files are large and slow to produce, so where you put them matters more than usual.
Anything the user would be upset to lose — a recording, an import, a rendered export — belongs
in [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private, never auto-deleted and included in backups. Put transcodes and thumbnails
you can regenerate in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
instead — the OS may purge it under storage pressure, which for derived files is the behaviour
you want. Never write anything you intend to reopen to
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp);
it can vanish between launches.

`av.open()` also takes any file-like object, so a clip you are only going to process once never
has to touch the filesystem at all.

### Media over the network

**There is no `https` protocol in this build**, and no `tls`, `rtmps` or encrypted HLS with it.
`av.open("https://…")` raises
[`av.error.ProtocolNotFoundError`](https://pyav.basswood.io/docs/stable/api/error.html). FFmpeg needs a TLS
backend for those, which would mean a second copy of OpenSSL inside the app.

Fetch the bytes with a Python HTTP client and hand PyAV a file-like object instead — the same
`av.open` call, and it goes through your app's own TLS stack and certificate store. `httpx` is
already there, as one of Flet's own dependencies:

```python
import io

import httpx

with av.open(io.BytesIO(httpx.get(url).content)) as container:
    ...
```

A `BytesIO` is seekable, so `container.seek(...)` and formats that need to read a trailing
index (MP4 with the `moov` atom at the end) work normally. Wrapping a streaming response
directly gives you a non-seekable file object, which FFmpeg accepts but can only read
forwards — fine for a progressive download, not for a seek bar.

Plain `http://`, `tcp`, `udp`, `rtp` and `rtmp` are compiled in, so an RTSP camera or an
`http://` stream on a local network opens directly.

### Showing and playing what you decode

PyAV decodes; it does not display. A decoded `VideoFrame` reaches the screen the way the
snippet above does it — re-encoded as JPEG or PNG bytes and handed to
[`ft.Image`](https://flet.dev/docs/controls/image/). That is fine for thumbnails, stills and
frame-by-frame inspection, and it is not a video player: every frame costs an encode, a
control update and a decode by the Flutter side.

For actual playback, leave the file to Flet's own player controls — `Video` from
[`flet-video`](https://pypi.org/project/flet-video/) and `Audio` from
[`flet-audio`](https://pypi.org/project/flet-audio/), separate packages you add to
`dependencies` alongside `flet`. They wrap the platform's player, which is hardware-accelerated
where this build is not. The natural division of labour is PyAV for anything that reads or
rewrites the media — probing, trimming, remuxing, extracting frames or audio — and a Flet
control for playing the result.

### Threading

PyAV releases the GIL around demuxing, decoding and encoding, so this work genuinely runs in
parallel with the UI. Hand it to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — a
half-second decode on the event-handler thread is a visibly frozen app. `run_thread` swallows
exceptions and does not carry an automatic update with it, so catch your own failures and
finish the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

A single container is not safe to use from two threads at once. Give each thread its own
`av.open(...)`, or serialise access with a `threading.Lock`.

### What this build can encode

Decoding is broad: H.264, HEVC, AV1, VP8, VP9, ProRes, MJPEG, PNG, GIF, WebP, AAC, MP3, Opus,
Vorbis and FLAC are all present, in MP4/MOV, Matroska/WebM, MPEG-TS, HLS, WAV, OGG and the rest
of FFmpeg's demuxers.

Encoding is narrower, and that is a licence consequence rather than a build oversight. The
video encoders for H.264, HEVC, VP8, VP9 and AV1 all come from external libraries — x264 and
x265 are GPL, and the BSD-licensed ones (libvpx, libaom, SVT-AV1) are not built here — so what
you get is FFmpeg's own: **`mpeg4`, `mjpeg`, `png`, `gif`, `prores` and `ffv1`** for video, and
**`aac`, `opus`, `vorbis`, `flac`, `alac` and PCM** for audio. There is no MP3 encoder either;
that one is LAME.

In practice: remuxing an H.264 clip into another container is free (the packets are copied, not
re-encoded), extracting stills and audio works, and re-encoding video to H.264 does not. If you
need an H.264 file out of a Flet app, encode it on a server, or capture with the platform's own
recorder.

No hardware acceleration is compiled in on either platform — no VideoToolbox, no MediaCodec —
so everything decodes on the CPU. A 1080p H.264 decode is comfortable on a modern phone; 4K is
not, and neither is real-time software encoding of anything large.

`libavdevice` is linked and `av.device` works, but no capture devices are registered:
`av.enumerate_input_devices("avfoundation")` raises `ValueError`. Capture with
[`flet-camera`](https://pypi.org/project/flet-camera/) or
[`flet-audio-recorder`](https://pypi.org/project/flet-audio-recorder/) and hand the file they
produce to PyAV.

### App size

The wheels add approximately **12 MB compressed and 27 MB unpacked per architecture** —
roughly 21 MB of that is the FFmpeg libraries and 4 MB PyAV's own extension modules. On
Android that is per ABI, so ship an app bundle or split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) to the
ABIs you actually support, rather than putting three copies in one universal APK. These are
package figures; what reaches a user's download depends on packaging and compression.

### Other considerations

A desktop `flet run` resolves PyPI's own `av` wheel, which is built against a **different**
FFmpeg: it has x264, x265, libvpx, SVT-AV1, dav1d, LAME, WebP and both Apple hardware
frameworks, plus TLS and capture devices. So `add_stream("libx264")`, `av.open("https://…")`,
`format="lavfi"` and camera enumeration all succeed on your Mac and fail on device. Anything
that names a codec, a protocol or a device has to be validated on a device or
emulator/simulator.

## Things to know

- **A decoded frame is much bigger than the file it came from.** One 1080p `yuv420p` frame is
  about 3 MB; hold a few dozen and a phone will kill the app. Decode in a loop and let each
  frame go, and if you need to keep frames, keep them re-encoded (JPEG/PNG bytes) rather than
  as `VideoFrame` objects.
- **`seek` lands on a keyframe, not on your timestamp.** `container.seek(t)` positions to the
  nearest preceding keyframe, so the first frame you decode after it can be a second or more
  early. Decode forward to the frame you actually wanted, comparing `frame.time`.
- **`av.datasets` has nowhere to write.** Its fixture helpers cache downloads under
  `/usr/local/share/pyav/datasets` and similar system paths, none of them writable from an app
  sandbox, so they raise rather than download. Point `PYAV_TESTDATA_DIR` at app storage if you
  want them, or bundle sample media in your app's `src/assets/` — which is what an app that
  ships fixtures should do anyway.
- **`format="lavfi"` is unavailable.** The `lavfi` virtual input device is part of
  `libavdevice`, which registers nothing here. Build the graph directly with
  [`av.filter.Graph`](https://pyav.basswood.io/docs/stable/api/filter.html) instead; all 400-odd
  filters are compiled in.
- **Subtitle character-set conversion is off.** `iconv` is unavailable on Android before API 28,
  so it is disabled on both platforms for symmetry; the `sub_charenc` option has no effect.
  UTF-8 subtitles are unaffected.
- **Licensing:** `av` itself is
  [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html), but the wheel is useless without
  the FFmpeg libraries behind it, and those come from the separate
  [`flet-libffmpeg`](../flet-libffmpeg) wheel, which declares
  [LGPL-2.1-or-later](https://spdx.org/licenses/LGPL-2.1-or-later.html) `AND`
  [IJG](https://spdx.org/licenses/IJG.html). Two things follow, and only the second asks
  anything of you:

  - **The LGPL part.** No `--enable-gpl` and no `--enable-nonfree`, which is why the GPL-only
    encoders above are missing. The libraries ship **shared** and are loaded dynamically, so
    the LGPL's relinking condition is satisfied by the shape of the build; a closed-source app
    carries the notice and says it uses FFmpeg under the LGPL.
  - **The IJG part is an action.** libavcodec's JPEG DCT routines come from the Independent
    JPEG Group, and that grant's condition (2) says that if you distribute **only executable
    code** — which every published app does — the accompanying documentation must state that
    the software is *"based in part on the work of the Independent JPEG Group"*. Put that
    sentence wherever your app credits its third-party code: an about screen, a licences page,
    the store listing. It applies whether or not you touch MJPEG, because the code is compiled
    in either way.

  Both wheels ship their licence text; read it off the artifact rather than from a summary
  elsewhere:

  ```bash
  unzip -p <wheel> '*.dist-info/METADATA' | grep -i license
  unzip -l <wheel> | grep licenses/
  ```

  This is a flag, not legal advice.

## Build notes (maintainers)

### Recipe shape

Two recipes: [`flet-libffmpeg`](../flet-libffmpeg) builds the seven `libav*` libraries shared,
and this one compiles PyAV's 49 Cython extension modules against them. It is the
`flet-libarrow` → `pyarrow` chain, with the same per-platform delivery — jniLibs on Android,
per-slice `*.fwork` frameworks on iOS plus an `__init__` preload shim.

Shared is not a preference. PyAV's `setup.py` refuses a static FFmpeg outright ("Building PyAV
against static FFmpeg libraries is not supported"), and 49 extension modules each statically
linking a 13 MB `libavcodec` is not a wheel anyone would ship. It also means `setup.py` finds
FFmpeg *only* through `pkg-config`, which is why `flet-libffmpeg` ships relocatable `.pc` files
— forge puts `<site-packages>/opt/lib/pkgconfig` on `PKG_CONFIG_LIBDIR` and nothing else is
needed.

The wheel is `abi3` (PyAV asks for `Py_LIMITED_API` on 3.12 and 3.13), so the modules are named
`*.abi3.so`. forge and serious_python both recognise that spelling; forge still re-tags the
wheel per Python version.

**`-Wl,-headerpad_max_install_names` on iOS is load-bearing, and its absence fails silently.**
An iOS build creates 56 frameworks for this app — 49 extension modules and the 7 dylibs — and
serious_python then rewrites every `@rpath/libavformat.dylib` reference to
`@rpath/opt.lib.libavformat.framework/opt.lib.libavformat`, which is 30 bytes longer. With no
header padding `install_name_tool` refuses ("larger updated load commands do not fit"),
`reconcile_framework_install_names` aborts the sync, and `flet build` **still reports success**
— having produced an app whose site-packages are whatever the plugin's shared `dist_ios`
happened to hold from a previous build. Observed as an app carrying another recipe's packages
and no `av` at all. Both recipes therefore pass the flag: this one through `script_env`
`LDFLAGS`, `flet-libffmpeg` through `--extra-ldflags`. Any change that lengthens those
framework names needs it re-checked.

### Upgrade hazards

- **PyAV and FFmpeg move as a pair.** Each PyAV release supports one FFmpeg major line
  (18.x is 8.x) and its `.pxd` headers track that ABI. Bumping one means bumping the other and
  re-pinning `requirements.host` in `meta.yaml`; a floating `>=` there would let a future ABI
  break resolve silently.
- **The encoder list is a licence boundary, not a snapshot.** If a future bump appears to add
  H.264 encoding, something turned on `--enable-gpl` — check before believing it, because the
  wheel's declared LGPL metadata would then be wrong.
- **The Flet floor in Install is about serious_python, not about PyAV.** It moves only if the
  iOS framework-reconciliation contract changes.

### Re-verification checklist

- `tests/test_av.py::test_build_is_lgpl_only` asserts every library reports LGPL and that no
  GPL/nonfree codec is linked; `test_no_capture_devices_registered` pins `--disable-devices`.
  Both turn red on their own if the build configuration drifts, which is what they are for.
- The decoder/encoder names this page promises are asserted by
  `test_expected_codecs_available`. Add to that list whenever the page starts promising more.
- `test_no_tls_protocols` pins the absence of `https`. The rest of the protocol list is not
  asserted; read it off a device if the configure flags change, with
  `av._core.library_meta["libavformat"]["configuration"]`.
- Re-measure the size figures rather than adjusting them by eye, and quote decimal MB. They
  move with FFmpeg's codec tables on every bump.
- `flet-libffmpeg`'s `build.sh` extracts the IJG notice out of `libavcodec/jrevdct.c` at build
  time and fails the build if it is not there, so an upstream move cannot silently drop it.
  What that guard cannot see is the notice **spreading** — re-check on a bump that
  `LICENSE.md` still carves out only those three files, since a new one would make the
  `AND IJG` expression incomplete rather than wrong.

### Coverage gaps

The device tests exercise muxing, encoding, decoding, seeking through a `BytesIO`, swscale,
swresample, avfilter and the bitstream-filter registry — all on synthetic media generated in
the test. Nothing decodes a real-world H.264 or HEVC file, so a codec that is *present* but
broken on a given architecture would not be caught. Nothing touches the network protocols.
Nothing measures decode throughput, so the performance claims in **What this build can encode**
are judgement, not measurement.
