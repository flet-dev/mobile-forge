# python-magic

[`python-magic`](https://github.com/ahupp/python-magic) tells you what a file **is** by reading
its bytes, not its name. It is a small ctypes wrapper — pure Python, no compiled extension of its
own — around [libmagic](https://www.darwinsys.com/file/), the library behind the Unix `file`
command, and what this recipe adds is that libmagic **and its compiled rule database** both travel
with it, on every Android ABI and every iOS slice Flet targets.
[Upstream's documentation](https://github.com/ahupp/python-magic#usage) applies unchanged.

On a phone that is worth more than on a server. Everything a user hands your app — a share sheet,
a document picker, a download, a file synced from somewhere else — arrives with a name somebody
else chose, and an extension is a claim rather than a fact. The alternatives are to believe the
claim or to send the bytes somewhere that knows; python-magic answers in-process, offline, fast
enough that a picker callback does not need a background thread, and never touches the network.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "python-magic",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`identify-by-content`](examples/identify-by-content) — ten generated files, two of them lying
  about what they are, identified by content with a head-size slider.

## Usage in a Flet app

Two calls do the whole job, and their results are strings that go straight into a
[`ft.Text`](https://flet.dev/docs/controls/text/):

```python
import magic

mime = magic.from_file(path, mime=True)  # 'application/pdf'
detail = magic.from_file(path)           # 'PDF document, version 1.4, 3 page(s)'
label = ft.Text(f"{mime} — {detail}", selectable=True)
```

For bytes that never reach the filesystem, `magic.from_buffer(data, mime=True)` answers the same
question. Stay on these **module-level** functions rather than constructing `Magic()` yourself:
they cache at most two instances for the whole process, and each live instance costs about 10 MB.

### Storage

python-magic writes nothing of its own; the database is read-only and ships inside the package.
What it does need is a **real path** for its best API. `from_file()` identifies things
`from_buffer()` cannot — a plain ZIP is the clearest case — so anything you can put on disk, put
on disk and identify from there.

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

### Threading

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
only if each thread has its own `Magic` — and each one costs about 10 MB of resident memory, so
twelve workers is 120 MB. Measured on a development machine over five runs of 12 threads × 300
detections, per-thread instances were 2–3× faster than the shared module-level one in every run,
while the shared instance never beat a plain single-threaded loop by anything worth having.
Correctness held throughout: 36,000 threaded detections, zero errors and zero wrong answers.

The two standing Flet caveats apply as everywhere else: `run_thread` never retrieves the worker's
future, so an exception raised inside one surfaces nowhere at all — wrap the body — and
auto-update does not reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Memory and the rule database

**Every live `Magic` holds its own copy of the ~10 MB rule database, on both platforms.** The
reason differs — on Android the package ships inside a stored zip with no filesystem path, so the
database is read into memory; on iOS it is a real file, but the shipped libmagic was built without
`mmap`, so reading it still means a full `malloc` — and the price does not. Measured on a host
reproduction of each platform's load path, peak resident memory rises by about 10 MB per extra
live instance, and construction costs single-digit to tens of milliseconds instead of a fraction
of one. Detection speed is unaffected.

The module-level `magic.from_file` / `magic.from_buffer` cache at most **two** instances for the
whole process — one for `mime=False`, one for `mime=True` — so the default usage pattern caps the
cost at about 20 MB. Stay on them and you never think about this.

On Android there is a lever if you want the memory back:

```toml
[tool.flet.android]
extract_packages = ["magic"]
```

That moves `magic/` out of the stored `sitepackages.zip` and onto disk on first launch, so the
database becomes a real file and the Android build of libmagic — which does have `mmap` — maps one
shared copy instead of allocating one per cookie. It is a **memory** lever, not a correctness one:
the recipe works without it, and it does not shrink the app, because the database ships either
way. The disk-versus-RAM trade has not been measured on a device.

### App size

**Budget about 10 MB on Android, and possibly twice that on iOS — a second copy of the database may ride along in `flet-libmagic`'s `opt/`, unconfirmed against a built IPA. Budget about 10 MB.** The wheel is about 0.5 MB compressed and 10.4 MB unpacked, and the rule
database is all but a fraction of that. It compresses well inside the wheel but **not** on the way
into an APK, because serious_python ships site-packages as a stored zip — so on Android the full
10 MB is what lands.
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing useful
to remove; the database is the payload.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA; packaging and compression determine that result.

### Other considerations

**`flet run` on your desktop does not use this wheel.** These wheels are Android/iOS
platform-tagged, so a desktop resolve takes PyPI's `py2.py3-none-any` build — the unpatched
loader, no bundled library, no bundled database. Install a system libmagic for desktop runs
(`brew install libmagic`, `sudo apt install libmagic1`) and guard the import so a machine without
one shows a message rather than failing to launch. The system copy brings its own, usually older,
database — macOS's own `file` here is 5.41 against this build's 5.46 — so desktop wording can
differ from device wording, and the `detect_from_*` compatibility API works there while failing on
device. Validate detection on a device or emulator/simulator, not from a desktop run.

## Things to know

- **`from_buffer` cannot name a plain ZIP — at any length, including the whole file.** It returns
  `data` / `application/octet-stream` where `from_file` on the same bytes says
  `Zip archive data, made by v2.0 UNIX, …` / `application/zip`. Whatever the generic-ZIP rule
  needs, a flat buffer does not provide it, and this is neither a mobile nor a wrapper artefact:
  upstream `file 5.46` on a non-seekable pipe says the same. **ZIP-based document formats are
  fine**, because those are matched near the start rather than from the end — measured against
  this database, `from_buffer` correctly returned `application/epub+zip`,
  `application/vnd.oasis.opendocument.text`, the OOXML types for `.docx` and `.xlsx`, and
  `application/vnd.android.package-archive`. It is the *unbranded* archive that goes dark.
- **A head sample is enough for most formats, and how much is format-specific.** Measured on the
  example's own generated files, the smallest prefix `from_buffer` needs to agree with `from_file`:
  UTF-8 and ASCII text 2 bytes, GIF 4, gzip 4, PDF 5, WAVE 12, PNG 16, SQLite 18 — and **POSIX tar
  512**, because tar's identity lives in a 512-byte header block. libmagic reads at most 7.3 MB
  from a file anyway (`Magic().getparam(magic.MAGIC_PARAM_BYTES_MAX)`), so a huge file is never
  read whole.
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
  device.** These names (`magic.open` too) are the libmagic-project compatibility API, and they are
  served by two cookies that `magic/compat.py` creates and loads **at import time** with no
  filename — so libmagic falls back to its compiled-in default database path, which is a CI-runner
  path baked into the shipped binary and cannot exist on a phone. The load fails silently and the
  first call dies with `AttributeError: 'NoneType' object has no attribute 'split'`. It works on a
  desktop, where a system magic directory exists, so this is exactly the kind of thing `flet run`
  will not catch. Use `from_file` / `from_buffer` / `from_descriptor`; only those go through the
  patched loading path.
- **`import magic` proves the shared library loaded, not that the database is there.** The
  database is read in `Magic.__init__`, i.e. on the first detection. With `magic.mgc` deleted,
  `import magic` still succeeds and `magic.libmagic is not None` is still `True`; the first
  `from_buffer` then raises `FileNotFoundError` naming `magic/magic.mgc`. Guard the first
  detection, not only the import. (`$MAGIC` cannot break the patched path: the loader passes the
  bundled database explicitly, so an environment variable pointing anywhere else is ignored.)
- **`Magic(uncompress=True)` cannot look inside a compressed file here, and does not tell you so
  by raising.** The recipe builds libmagic without zlib, bzlib, xzlib, zstd and lzlib, so it tries
  to fork an external `gzip` instead; with no such binary reachable the *description* comes back as
  `'ERROR:[gzip: Wait failed, No child processes] (gzip compressed data, max compression)'` and the
  MIME as `application/x-decompression-error-gzip-…`. An app bundle carries no such binary. Leave
  the flag off — the outer container is identified correctly and usefully (`gzip compressed data` /
  `application/gzip`) — and decompress with the stdlib `gzip` / `bz2` / `lzma` / `zipfile` modules,
  then identify the inner bytes yourself.
- **An empty buffer and an empty file are different MIME types.** `from_buffer(b'')` gives
  `application/x-empty`, `from_file(<0-byte file>)` gives `inode/x-empty`. Both describe as
  `empty`. Worth knowing before you write `== "inode/x-empty"` against the wrong one.
- **The description and the MIME are two different cookies with different flags, and the
  description carries structure the MIME cannot.** A PNG is
  `PNG image data, 16 x 16, 8-bit/color RGB, non-interlaced` / `image/png`; a SQLite file names
  the engine version, page count and schema cookie. `from_file` also sees things `from_buffer`
  cannot — on a gzip it adds the uncompressed length. `Magic(extension=True)` works against this
  build and returns a slash-separated extension list, or `'???'` when libmagic has no extension
  for the type: `'png'`, `'gif'`, `'pdf'`, but `'???'` for plain text and for a generic ZIP.

## Build notes (maintainers)

`patches/mobile.patch` carries a full preamble on both halves of what it changes, and `meta.yaml`
explains its `script_env` and its host requirement next to them. What is left here is what a bump
can silently invalidate. Note that most of the claims above are about **libmagic and its
database** rather than about python-magic — upstream python-magic has not moved since 0.4.27
(2022), so a `flet-libmagic` or a Flet bump invalidates far more of this page than a python-magic
one would.

### Recipe shape

Two Python files in the wheel differ from upstream's own release: `magic/__init__.py` and
`magic/loader.py`. `magic/compat.py` and `magic/__init__.pyi` are byte-identical, nothing public
was removed or renamed, and the Android and iOS wheels carry the same `magic/` tree byte for byte
apart from the database — which is why the page can point at upstream's docs unchanged.

`flet-libmagic` is a `Requires-Dist` of the wheel and supplies the per-platform `.so`. Its own
`opt/share/misc/magic.mgc` is a **build-time transport only**: `meta.yaml`'s `FLET_MAGIC_MGC`
points `setup.py` at it so the database is copied into python-magic's own wheel, which is what
reaches the device. That database is compiled by a host `file` binary built inside the same job,
so it always matches the shipped library version; if that arrangement is ever lost the symptom is
not a build failure but a version-skewed database that loads fine and answers differently.

The delivery chain lives outside this recipe and is the fragile part; [`pyzbar`](../pyzbar) rides
the same one for `libzbar`, and what is specific here is the 10 MB database that has to travel
beside the library. Android depends on
`copyOpt_<abi>` flattening `opt/**/*.so` into `jniLibs/<abi>/` under the basename (which is why
the loader asks `dlopen` for a bare soname), on `splitSitePackages_<abi>` skipping `opt/`, and on
`sitepackages.zip` staying *stored* so `zipimport.get_data` can read `magic.mgc` out of it without
zlib. iOS depends on the darwin sync framework-izing every `*.so` under site-packages and leaving
a `.fwork` pointer, which the loader tries first. The candidate order is load-bearing in opposite
directions on the two platforms.

The `compat` cookies are deliberately **not** patched. Fixing them would mean two more cookies
holding two more 10 MB buffers on Android, which is worse than the four functions they serve are
worth. If that calculus changes, the `detect_from_*` bullet above goes with it.

### Upgrade hazards

- **A serious_python bump can break delivery from a wheel that built green.** Every mechanism in
  the paragraph above is read out of `serious_python_android` 4.5.1's `build.gradle.kts` and
  `serious_python_darwin` 4.5.1's `sync_site_packages.sh`, and a wrong answer there is a
  device-only failure.
- **The same `build.sh` gives the two platforms different libmagic internals, and nothing warns
  you.** `configure`'s `AC_FUNC_MMAP` cannot run its probe under cross-compilation and guesses by
  host: yes for `linux*` (Android's `aarch64-linux-android`), no for anything else (the iOS legs'
  `*-apple-darwin23`). That one guess decides whether `apprentice_map`'s `mmap` is compiled in,
  which is the whole per-instance memory story above. Forcing
  `ac_cv_func_mmap_fixed_mapped=yes` on the iOS leg would close the gap — the guess is a
  cross-compilation artefact, not a statement about the platform — but it has not been tried and
  would need an on-device run.
- **Build-1 wheels are still on the index** and are the only ones for `android_24_x86` cp312.
  Build 2 wins every resolve `flet build` can ask for, because the build tag breaks the tie at
  equal version, and that ABI is unreachable anyway — flet-cli 0.86.5 accepts only `armeabi-v7a`,
  `arm64-v8a` and `x86_64`. Do not delete build 1 expecting nothing to change. The two failure
  modes are distinguishable on device: build 1 gives
  `MagicException: could not find any valid magic files!`, while a build-2 wheel that lost its
  data file gives `FileNotFoundError` naming `magic/magic.mgc`.

### Re-verification checklist

- **Everything the consumer sections claim about the Flet side was read off Flet 0.86.5, which
  pins serious_python 4.5.1.** Re-read it on a serious_python bump.
- **Resolve, one per slice, the way `flet build` does it:** `pip download --only-binary :all:
  --extra-index-url https://pypi.flet.dev --platform <tag> --python-version <ver>` across the three
  Android ABIs, the three iOS slices (device arm64, simulator arm64, simulator x86_64) and Python
  3.12/3.13/3.14. Last measured eighteen for eighteen, each pulling this wheel plus a matching
  `flet_libmagic` 5.46.
- **Read `mmap` off the binaries, not off a desktop build**, whose native configure always says
  yes: `mmap`/`mmap64` and `munmap` must appear among each Android `.so`'s undefined symbols, and
  their absence from the iOS dylibs is what makes a `Magic` cost 10 MB there.
- **Re-measure the rule count and the sizes rather than adjusting them by eye.** The count comes
  from the database's own 16-byte header (`struct.unpack('<IIII', head)` → magic number, format
  version, and the two set counts; `(first + second + 1) * 432` should equal the file size). The
  example prints the count it finds on device.
- **Check `PT_LOAD` alignment** — every segment 16 KB (`0x4000`) aligned on all three Android
  ABIs, which is what Android's 16 KB page-size devices need.
- **Confirm whether `flet-libmagic`'s `opt/share/misc/magic.mgc` ships in a built IPA.** The
  darwin sync stages the whole site-packages tree, `opt/` included, so it probably lands there
  beside python-magic's own copy — another 10 MB. If it holds, strip `share/` from the runtime
  wheel while keeping it available to the cross-env, and that is 10 MB off every iOS build.
- **Do not treat the database hash as a platform or version identity.** The Android and iOS
  copies have different SHA-256 hashes — about a hundred records sit in a different order, which
  is what two build hosts walking the magic sources differently looks like — but they are the same
  database: same size, same header, identical record multiset, and 40 compared answers came back
  identical.

### Coverage gaps

`tests/test_python_magic.py` asserts two things: that the loader found a library, and that a
minimal PNG comes back as `PNG` / `image/png`. That second one exercises the database end-to-end,
which is what turns a delivery regression red on device — but nothing checks the format-specific
behaviour this page promises, the head-size thresholds, the ZIP hole, the `compat` breakage or the
memory story. The [`identify-by-content`](examples/identify-by-content) example is what exercises
the first four; rebuild and run it on a bump.

The memory and throughput figures above are host measurements — several taken against a native
libmagic deliberately configured the way the iOS leg is — not device ones. The `extract_packages`
disk-versus-RAM trade and whether a device can reach an external `gzip` for `uncompress=True` are
both unmeasured.
