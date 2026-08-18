# python-magic

[`python-magic`](https://github.com/ahupp/python-magic) tells you what a file **is** by reading
its bytes, not its name. It is a small ctypes wrapper — pure Python, no compiled extension of its
own — around [libmagic](https://www.darwinsys.com/file/), the library behind the Unix `file`
command, and what this recipe adds is that libmagic **and its compiled rule database** both travel
with it. The database in these wheels holds 23,970 rules: it names a GIF from 4 bytes, a PNG from
16 and a SQLite file from 18, and knows EPUB, OOXML, tar and WAVE besides.

On a phone that is worth more than on a server. Everything a user hands your app — a share sheet,
a document picker, a download, a file synced from somewhere else — arrives with a name somebody
else chose, and an extension is a claim rather than a fact. The alternatives are to believe the
claim or to send the bytes somewhere that knows; python-magic answers in-process, offline, in a
fraction of a millisecond per call on a development machine (31–445 µs across the ten files the
example generates, text being the slowest), and never touches the network.

It is published for **both platforms** — every Android ABI and every iOS slice Flet targets. What
is worth knowing is how the database reaches the device (the two platforms take different routes
and both end up paying ~10 MB per live `Magic`), and a set of API shapes that fail quietly or in
the wrong exception class.

Two Python files in the wheel differ from upstream's own release: `magic/__init__.py` and
`magic/loader.py`. `magic/compat.py` and `magic/__init__.pyi` are byte-identical, nothing public
was removed or renamed, and the Android and iOS wheels carry the same `magic/` tree byte for byte
apart from the database — so
[upstream's documentation](https://github.com/ahupp/python-magic#usage) applies unchanged.
Everything below about the Flet side was read off Flet 0.86.5, which pins serious_python 4.5.1.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "python-magic",
]
```

Nothing else to configure. `flet-libmagic` — the libmagic build the wrapper dlopens — is a
`Requires-Dist` of the wheel and comes along on its own.

A bare `python-magic` resolves from this index on **every slice a `flet build` can produce**.
Measured one resolve per slice, the way `flet build` does it (`pip download --only-binary :all:
--extra-index-url https://pypi.flet.dev --platform <tag> --python-version <ver>`): the three
Android ABIs Flet 0.86.5 targets (`arm64-v8a`, `x86_64`, `armeabi-v7a`) and all three iOS slices
(device arm64, simulator arm64, simulator x86_64), on Python 3.12, 3.13 and 3.14 — eighteen for
eighteen, each pulling the same forge wheel plus a matching `flet_libmagic` 5.46.

**Budget about 10 MB of app size for it.** The rule database, `magic/magic.mgc`, is 10,355,472
bytes and is most of the wheel: 512,005 bytes to download, 10,391,167 unpacked. It compresses well
in the wheel (498,782 bytes deflated) but not on the way into an APK — serious_python writes
site-packages into a *stored* `sitepackages.zip` and its Gradle config sets
`noCompress.add("zip")`, so on Android the full 10,355,472 bytes ship uncompressed. That figure is
read from `serious_python_android` 4.5.1's `build.gradle.kts`, not off a built APK.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is required — the recipe exists precisely so that none is — but there is a reason you might
still want one, and it is a memory trade rather than a correctness one. See
[Android notes](#android-notes).

## Storage

python-magic writes nothing of its own; the database is read-only and ships inside the package.
What it does need is a **real path** for its best API. `from_file()` can identify things
`from_buffer()` cannot — a plain ZIP is the clearest case (see
[Things to know](#things-to-know)) — so anything you can put on disk, put on disk and identify
from there.

The app-private directories are the place for that. Use
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for files you keep,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a downloaded blob you are about to identify and throw away:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_TEMP", "."), "incoming.bin")
```

Bytes that genuinely never touch the filesystem — a chunk pulled off a socket, a clipboard
payload — are what `from_buffer()` is for. An already-open file object goes to
`from_descriptor(f.fileno())`, which behaves like `from_file()` rather than like `from_buffer()`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`identify-by-content`](examples/identify-by-content) — ten generated files, two of them lying
  about what they are, identified by content with a head-size slider.

## Threading

`from_file()` and `from_buffer()` are safe to call from any thread, and they are safe because
upstream takes a `threading.Lock` around **every** call into libmagic. That lock is not a
formality: a libmagic cookie has one internal result buffer, so two threads inside it at once is
not a race you get away with. Driving a single cookie from two threads with the lock bypassed
(`magic.magic_buffer(m.cookie, data)` directly, one thread asking about a PNG and the other about
a PDF) failed on all six runs of a 400-iteration batch: four `SIGABRT`, one `SIGTRAP`, one hang.
A surviving low-iteration run had the PDF thread return `'image/pngapplication/pdf'`, an answer
spliced out of the other thread's question. Those are native crashes with no Python traceback and
nothing to `except`. **Never reach for `m.cookie` or the `magic_*` functions yourself** — stay on
`from_file` / `from_buffer` / `from_descriptor` and the lock is already there.

What the lock costs you is parallelism: it serialises detection, so handing magic work to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys throughput
only if each thread has its own `Magic`. Measured on a development machine over five runs of 12
threads × 300 detections of six different formats: the module-level shared instance took
0.28–0.46 s and one `Magic` per thread 0.12–0.17 s — per-thread was 2.3–3.4× faster in every run,
while the shared instance never beat a plain single-threaded loop by anything worth having.
Correctness held throughout: 36,000 threaded detections, zero errors and zero wrong answers.

Before you reach for per-thread instances, read what one costs: on **both** platforms each live
`Magic` holds its own ~10 MB copy of the database — on Android because the in-memory branch is the
one that runs, on iOS because the shipped libmagic was built without `mmap`. See
[Android notes](#android-notes) and [iOS notes](#ios-notes); twelve worker threads is 120 MB.

The two standing Flet caveats apply as everywhere else: `run_thread` never retrieves the worker's
future, so an exception raised inside one surfaces nowhere at all — wrap the body — and
auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**The library is found by bare soname.** `flet-libmagic` ships a single unversioned
`opt/lib/libmagic.so` whose `SONAME` is `libmagic.so` and whose only `DT_NEEDED` entries are
`libm`, `libdl` and `libc`; serious_python's `copyOpt_<abi>` Gradle task copies `opt/**/*.so` into
`jniLibs/<abi>/` under the basename alone (`eachFile { path = name }`), which is exactly what the
patched loader asks `dlopen` for. The `<site-packages>/opt/lib/libmagic.so` path the wheel
nominally unpacks to is *not* where it ends up: `splitSitePackages_<abi>` skips `opt/` outright
and leaves it to `copyOpt`. Both halves read out of `serious_python_android` 4.5.1's
`build.gradle.kts`. This is the same delivery chain [`pyzbar`](../pyzbar#android-notes) uses for
`libzbar.so`, and it behaves identically here — what is specific to this recipe is not the
library but the 10 MB database that has to travel beside it.

**The database is loaded into memory, and that is per-instance.** The `magic` package itself lands
in a *stored* `sitepackages.zip` with no real filesystem path, so `magic.mgc` cannot be `fopen`ed;
the patched `Magic.__init__` reads its bytes through `zipimport` and hands them to
`magic_load_buffers`, which both platform builds export (`nm -D` lists `magic_load_buffers` on
Android, `nm -gU` lists `_magic_load_buffers` on iOS). libmagic then references that buffer **in
place**, so every live `Magic` keeps its own 9.9 MiB copy resident. Measured by importing `magic`
out of a *stored* zip on `sys.path` — the real Android arrangement, in which
`_bundled_magic_db_path()` returns `None` and `_magic_db_buffer` comes back 10,355,472 bytes long
— peak RSS for 1 / 2 / 4 / 8 / 16 live instances runs 22.0 / 32.0 / 51.6 / 91.9 / 172.0 MiB, a
slope of ~10 MiB per extra instance, against a flat 0.0–0.3 MiB on the real-file branch of a
libmagic that has `mmap`. Construction costs 6–40 ms per instance instead of 0.04–0.3 ms, since
each one re-reads the database out of the zip. Detection speed is unaffected.

The module-level `magic.from_file` / `magic.from_buffer` cache at most **two** instances for the
whole process — one for `mime=False`, one for `mime=True` — so the default usage pattern caps the
cost at about 20 MB. Stay on them and you never think about this.

**If you want the memory back, extract the package:**

```toml
[tool.flet.android]
extract_packages = ["magic"]
```

That moves `magic/` out of `sitepackages.zip` into `extract.zip`, which serious_python unpacks to
disk on first launch, so `magic.mgc` becomes a real file, the loader takes the by-path branch, and
every cookie shares one mmapped copy — the Android build of libmagic has `mmap` compiled in, which
is exactly what the iOS one lacks (see [iOS notes](#ios-notes)). The mechanism is
`build.gradle.kts`'s `isAllowlisted(rel)` plus the patched loader's `os.path.exists` probe; the
disk-versus-RAM trade has not been measured on a device, and it does not shrink the APK — the
database ships either way.

**`flet-libmagic`'s own copy of the database never reaches the device.** The wheel carries
`opt/share/misc/magic.mgc` alongside the `.so` — a second 10,355,472 bytes, byte-identical to the
one inside python-magic for the same platform — but `copyOpt` copies only `**/*.so` and
`splitSitePackages` skips `opt/`, so nothing under `opt/share/` is packaged. That gap is exactly
what this recipe exists to work around.

Sizes, per ABI, stripped: `libmagic.so` is 146,624 bytes on arm64-v8a, 154,112 on x86_64 and
103,844 on armeabi-v7a, with every `PT_LOAD` segment 16 KB (`0x4000`) aligned on all three — what
Android's 16 KB page-size devices need.

## iOS notes

**The library is a real framework, and the database is a real file.** `flet-libmagic` ships a
Mach-O `MH_DYLIB` on all three slices (never an `MH_BUNDLE`, so forge's `fix_wheel` conversion has
nothing to do), each with `install_name @rpath/libmagic.so` and linking nothing but
`/usr/lib/libSystem.B.dylib`. The `LC_BUILD_VERSION` differs per slice, as it should: device arm64
is platform 2 `minos 13.0`, the arm64 simulator platform 7 `minos 14.0`, the x86_64 simulator
platform 7 `minos 13.0`. serious_python's darwin sync walks site-packages,
repackages each `*.so`/`*.dylib` into a framework and writes a `.fwork` text pointer where the
file was, so `<site-packages>/opt/lib/libmagic.fwork` is what exists on device and iOS CPython's
`.fwork`-aware `ctypes.CDLL` dereferences it — the patched loader's *first* bundled candidate,
ahead of the bare soname Android needs. [`pyzbar`](../pyzbar#ios-notes) documents the same
`.fwork` mechanism; what differs here is everything below.

**The database is a real file — and a live `Magic` still costs ~10 MB here.** Because site-packages
stays a real directory, `magic/magic.mgc` is a real file and the loader takes its by-path branch.
That branch is the cheap one only where libmagic was compiled with `mmap`, and the iOS build was
not: `apprentice_map`'s `mmap` sits behind `QUICK`, which `file.h` defines only when `HAVE_MMAP` is
set, and `configure`'s `AC_FUNC_MMAP` cannot run its probe under cross-compilation — it guesses yes
for a `linux*` host and no for everything else. Android's triplets are `aarch64-linux-android` and
friends; the iOS legs configure as `*-apple-darwin23`. The shipped binaries agree: all four Android
`libmagic.so` import `mmap`/`mmap64` **and** `munmap`, none of the three iOS dylibs imports either.
What is left is `malloc` plus a full read, per cookie.

Measured against a native file 5.46 configured the way the iOS leg is
(`ac_cv_func_mmap_fixed_mapped=no`, giving the same missing-`mmap` symbol profile as the shipped
dylib), peak RSS for 1 / 2 / 4 / 8 / 16 live instances on the by-path branch: 9.9 / 19.9 / 39.6 /
79.3 / 158.6 MiB, construction 1.7–6.6 ms. The same measurement against a build that *does* have
`mmap` — what Android gets under `extract_packages` — stays flat at 0.0–0.3 MiB and 0.04–0.3 ms. So
the per-instance arithmetic in [Android notes](#android-notes) applies here too, for a different
reason, and the same mitigation applies: stay on the module-level `magic.from_file` /
`magic.from_buffer`, which cache at most two instances for the whole process. A `Magic` per worker
thread is *not* free on either platform.

**The database probably ships twice.** `serious_python_darwin` 4.5.1's `sync_site_packages.sh`
stages the whole site-packages tree into the bundle (`cp -R $tmp_dir/${archs[0]}/* $dist/site-packages`),
`opt/` included, so `flet-libmagic`'s redundant `opt/share/misc/magic.mgc` very likely lands in
the IPA alongside python-magic's own copy — another 10,355,472 bytes. This is read from the sync
script, **not** confirmed against a built IPA; there is nothing a consumer can do about it either
way, and it is on the maintainer checklist below.

Sizes: `libmagic.so` is 213,480 bytes on device arm64 and 198,984 on the arm64 simulator. The
Android and iOS copies of `magic.mgc` have different SHA-256 hashes — 97 of its 23,971 records sit
in a different order, which is what two build hosts walking the magic sources differently looks
like — but they are the same database: same size, same header, identical record multiset, and 40
answers compared (ten sample files × description/MIME × `from_file`/`from_buffer`) came back
identical. Do not treat the hash as a platform or version identity.

## Things to know

- **`from_buffer` cannot name a plain ZIP — at any length, including the whole file.** It returns
  `data` / `application/octet-stream` where `from_file` on the same bytes says
  `Zip archive data, made by v2.0 UNIX, …` / `application/zip`. Whatever the generic-ZIP rule
  needs, a flat buffer does not provide it, and this is neither a mobile nor a wrapper artefact:
  upstream `file 5.46` on a non-seekable pipe says the same (`cat x.zip | file -m magic.mgc -` →
  `data`, while the same binary on the same file by path identifies it). **ZIP-based document
  formats are fine**, because those are matched near the start rather than from the end — measured
  against this database, `from_buffer` correctly returned `application/epub+zip`,
  `application/vnd.oasis.opendocument.text`, the OOXML types for `.docx` and `.xlsx`, and
  `application/vnd.android.package-archive`. It is the *unbranded* archive that goes dark.
- **A head sample is enough for most formats, and how much is format-specific.** Measured on the
  example's own generated files, the smallest prefix `from_buffer` needs to agree with `from_file`:
  UTF-8 and ASCII text 2 bytes, GIF 4, gzip 4, PDF 5, WAVE 12, PNG 16, SQLite 18 — and **POSIX tar
  512**, because tar's identity lives in a 512-byte header block. libmagic reads at most 7,340,032
  bytes from a file anyway (`Magic().getparam(magic.MAGIC_PARAM_BYTES_MAX)`), so a huge file is
  never read whole.
- **Text-versus-binary is decided over what was read, so a head sample can confidently call a
  binary file text.** A 7,795-byte file of 3,699 ASCII bytes followed by 4,096 binary ones reads as
  `ASCII text` / `text/plain` at head sizes of 64, 512, 2048 and 3699, and as `data` /
  `application/octet-stream` when libmagic reads the whole file. If "is this really text?" is the
  question you are asking, ask it of the file, not of a prefix. (Trailing NUL bytes alone do not
  flip it: the same file with 4,096 NULs instead of binary still reads as `ASCII text` in full.)
- **`from_buffer` rejects `bytearray` and `memoryview` with a `ctypes.ArgumentError`** —
  `argument 2: TypeError: 'bytearray' object cannot be interpreted as ctypes.c_void_p` — because
  `magic_buffer`'s argtypes are `[magic_t, c_void_p, c_size_t]`. Reading a picked file into a
  `bytearray` is the natural thing to do, and `except MagicException` will not catch this. Call
  `bytes(buf)` first. A `str` *is* accepted and encoded for you.
- **`from_file` raises the ordinary filesystem exceptions, before libmagic is consulted at all.**
  The wrapper opens the path itself first, so a missing path is `FileNotFoundError` and a
  directory is `IsADirectoryError: [Errno 21] Is a directory`. Neither is a `MagicException`, so an
  app that guards only that one ends the Flet session with a crash screen. Catch broad `Exception`
  around any detection driven by a picker or a share sheet.
- **`magic.detect_from_filename` / `detect_from_content` / `detect_from_fobj` do not work on
  device.** These four names (`open` too) are the libmagic-project compatibility API, copied into
  the `magic` namespace at import by `_add_compat`, and they are served by two cookies that
  `magic/compat.py` creates and loads **at import time** with no filename — so libmagic falls back
  to `$MAGIC` or its compiled-in default database path. That default is a CI runner path baked
  into the shipped binary (`strings` shows
  `/home/runner/work/mobile-forge/…/opt/share/misc/magic` on Android and the `/Users/runner/…`
  equivalent on iOS), which cannot exist on a phone. The load fails silently — `compat.Magic.load`
  has no error check and just returns `-1` — and the first call dies with
  `AttributeError: 'NoneType' object has no attribute 'split'`. Reproduced by pointing `$MAGIC` at
  a nonexistent path, which is what the device's dead default amounts to. It works on a desktop,
  where a system magic directory exists, so this is exactly the kind of thing `flet run` will not
  catch. Use `from_file` / `from_buffer` / `from_descriptor`; only those go through the patched
  loading path.
- **`import magic` proves the shared library loaded, not that the database is there.** The
  database is read in `Magic.__init__`, i.e. on the first detection. With `magic.mgc` deleted,
  `import magic` still succeeds and `magic.libmagic is not None` is still `True`; the first
  `from_buffer` then raises `FileNotFoundError` naming `magic/magic.mgc`. Guard the first
  detection, not only the import. (For what it is worth, `$MAGIC` cannot break the patched path:
  the loader passes the bundled database explicitly, so an environment variable pointing anywhere
  else is ignored by `Magic`.)
- **`Magic(uncompress=True)` cannot look inside a compressed file here, and does not tell you so
  by raising.** The recipe builds libmagic with `--disable-zlib --disable-bzlib --disable-xzlib
  --disable-zstdlib --disable-lzlib`, so it tries to fork an external `gzip` instead; with no such
  binary reachable the *description* comes back as
  `'ERROR:[gzip: Wait failed, No child processes] (gzip compressed data, max compression)'` and
  the MIME as `application/x-decompression-error-gzip-…`. What is established here is that the
  library itself cannot decompress and that the fallback is an external process; whether a device
  can reach one was not measured, and an app bundle carries no such binary. Leave the flag off —
  the outer container is identified correctly and usefully (`gzip compressed data` /
  `application/gzip`) — and decompress with the stdlib `gzip` / `bz2` / `lzma` / `zipfile`
  modules, then identify the inner bytes yourself.
- **An empty buffer and an empty file are different MIME types.** `from_buffer(b'')` gives
  `application/x-empty`, `from_file(<0-byte file>)` gives `inode/x-empty`. Both describe as
  `empty`. Worth knowing before you write `== "inode/x-empty"` against the wrong one.
- **The description and the MIME are two different cookies with different flags, and the
  description carries structure the MIME cannot.** A PNG is
  `PNG image data, 16 x 16, 8-bit/color RGB, non-interlaced` / `image/png`; a SQLite file names
  the engine version, page count and schema cookie. `from_file` also sees things `from_buffer`
  cannot — on a gzip it adds the uncompressed length (`original size modulo 2^32 …`).
  `Magic(extension=True)` works against this build (`version()` is 546, past the wrapper's own 524
  guard) and returns a slash-separated extension list, or `'???'` when libmagic has no extension
  for the type: `'png'`, `'gif'`, `'pdf'`, but `'???'` for plain text and for a generic ZIP.
- **`flet run` on your desktop does not use this wheel.** These wheels are Android/iOS
  platform-tagged, so a desktop resolve takes PyPI's `py2.py3-none-any` build — the unpatched
  loader, no bundled library, no bundled database. Verified: `pip download python-magic
  --only-binary :all: --extra-index-url https://pypi.flet.dev` with no `--platform` fetches
  upstream's 13,840-byte wheel. Install a system libmagic for desktop runs (`brew install
  libmagic`, `sudo apt install libmagic1`) and guard the import so a machine without one shows a
  message rather than failing to launch. The system copy brings its own, usually older, database —
  macOS's own `file` here is 5.41 against this build's 5.46 — so desktop wording can differ from
  device wording.

## Build notes (maintainers)

`patches/mobile.patch` carries a full preamble on both halves of what it changes, and `meta.yaml`
explains its `script_env` and its host requirement next to them, so what is left here is what a
bump can silently invalidate. Note that most of the claims above are about **libmagic and its
database** rather than about python-magic — upstream python-magic has not moved since 0.4.27
(2022), so a `flet-libmagic` or a Flet bump invalidates far more of this page than a python-magic
one would.

- **`tests/test_python_magic.py` asserts two things: that the loader found a library, and that a
  minimal PNG comes back as `PNG` / `image/png`.** That second one exercises the database
  end-to-end, which is what turns a build-1-shaped regression red on device — but nothing checks
  any of the format-specific behaviour this README promises. The
  [`identify-by-content`](examples/identify-by-content) example is what exercises `from_file`
  versus `from_buffer`, the head-size thresholds and the ZIP hole; rebuild and run it on a bump.
- **The database is compiled by a host `file` binary built inside the same job** (`build.sh` builds
  `_hostbuild` natively and passes `FILE_COMPILE="$HOST_FILE"` to both `make` and `make install`),
  so it always matches the shipped library version. If that arrangement is ever lost, the symptom
  is not a build failure — it is a version-skewed database that loads fine and answers differently.
- **Re-measure the rule count and the sizes rather than adjusting them by eye.** 23,970 rules comes
  from the database's own 16-byte header (`struct.unpack('<IIII', head)` → magic number, format
  version 20, and the two set counts 16,771 and 7,199; `(16771 + 7199 + 1) * 432` is exactly the
  file's 10,355,472 bytes). The example prints the count it finds on device.
- **The same `build.sh` gives the two platforms different libmagic internals, and nothing warns
  you.** `configure`'s `AC_FUNC_MMAP` cannot run its probe under cross-compilation and guesses by
  host: yes for `linux*` (Android's `aarch64-linux-android`), no for anything else (the iOS legs'
  `*-apple-darwin23`). That one guess decides whether `QUICK` — and with it `apprentice_map`'s
  `mmap` — is compiled in, which is the whole per-instance memory story above. Read it off the
  binaries after a bump rather than trusting a desktop build, whose native configure always says
  yes: `mmap`/`mmap64` and `munmap` must appear among the Android `.so`'s undefined symbols, and
  their absence from the iOS dylib is what makes a `Magic` cost 10 MB there. Forcing
  `ac_cv_func_mmap_fixed_mapped=yes` on the iOS leg would close the gap — the guess is a
  cross-compilation artefact, not a statement about the platform — but it has not been tried and
  would need an on-device run.
- **The delivery mechanism lives outside this recipe and is the fragile part.** Android depends on
  `copyOpt_<abi>` flattening `opt/**/*.so` into `jniLibs/<abi>/` under the basename, on
  `splitSitePackages_<abi>` skipping `opt/`, and on `sitepackages.zip` staying *stored* so
  `zipimport.get_data` can read `magic.mgc` out of it without zlib; iOS depends on the darwin sync
  continuing to framework-ize every `*.so` under site-packages and leave a `.fwork` pointer. The
  loader's candidate order is load-bearing in opposite directions on the two platforms. Re-check
  after a serious_python bump — a wrong answer here is a device-only failure from a wheel that
  built green.
- **`flet-libmagic`'s `opt/share/misc/magic.mgc` is now only a build-time transport.** Since build
  2 it exists to feed `FLET_MAGIC_MGC`; on Android it is dropped by `copyOpt`, but on iOS the
  darwin sync copies the whole site-packages tree, so it is probably shipping a second 10 MB copy
  in every IPA. Confirm that against a built IPA, and if it holds, strip `share/` from the runtime
  wheel (keeping it available to the cross-env for the copy) — that is 10 MB off every iOS build.
- **Build-1 wheels are still on the index and are the only ones for `android_24_x86` cp312.** Build
  2 wins every resolve `flet build` can ask for (18/18 measured), because the build tag breaks the
  tie at equal version — and that ABI is unreachable anyway: flet-cli 0.86.5's
  `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM` holds only `armeabi-v7a`, `arm64-v8a` and `x86_64`, so
  `--arch x86` exits with *Invalid Android architecture(s): x86*. Do not delete build 1
  expecting nothing to change; do check the actual resolve after any republish. The two failure
  modes are distinguishable on device: build 1 gives
  `MagicException: could not find any valid magic files!`, while a build-2 wheel that lost its data
  file gives `FileNotFoundError` naming `magic/magic.mgc`.
- **The `compat` cookies are still broken on device and are deliberately not patched.** They are
  created and loaded at import in `magic/compat.py` with no filename, so they get the compiled-in
  CI-runner default and fail silently. Patching them would mean two more cookies holding two more
  10 MB buffers on Android, which is worse than the four functions they serve are worth. If that
  calculus changes, the README bullet about `detect_from_*` goes with it.
