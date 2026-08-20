# ujson

[`ujson`](https://github.com/ultrajson/ultrajson) is a JSON encoder and decoder written in
C, and it keeps the standard library's `json` *shapes* where the faster alternatives drop
them: `dumps` returns `str`, `loads` takes `str` or `bytes`, `dump`/`load` exist, and the
familiar `indent`, `sort_keys`, `ensure_ascii` and `separators` keywords all work.
([`orjson`](../orjson), the other fast JSON wheel on this index, returns `bytes` from
`dumps` and has no `dump`/`load` at all.)

The honest question on a phone is whether that buys anything, because the stdlib
[`json`](https://docs.python.org/3/library/json.html) is **already C**. Measured **on device**
on 2026-08-20 by the [example](examples/shape-bench) itself — 1,000 items per shape, `json` at
its own compact setting, best of 150/40/10 calls — on an arm64-v8a Android 14 emulator and an
iPhone 16 simulator, both CPython 3.14.6. Speedups are `json` time over `ujson` time, so above
1 is a win:

| shape, 1,000 items | `dumps` Android | `dumps` iOS | `loads` Android | `loads` iOS | output size |
| --- | --- | --- | --- | --- | --- |
| `records` — API-shaped objects | **2.83×** | **1.98×** | 1.29× | 1.49× | +0.0% |
| `floats` | **4.52×** | **3.56×** | 2.50× | 2.37× | +0.0% |
| `flags` — booleans | **0.74× — slower** | **0.84× — slower** | 1.69× | 1.63× | +0.0% |
| `URLs` | 1.73× | 1.69× | 1.29× | 1.19× | **+12.1% — bigger** |
| `text` — accented strings | 1.12× | 1.10× | **3.90×** | **3.15×** | +0.0% |

So: a large win on numbers, a wash on writing strings (though a 3–4× win parsing them), a
**loss on booleans on both platforms**, and on URL-heavy documents *more* bytes, because ujson
escapes `/` by default. The two platforms disagree on magnitude and agree on every sign, and
the byte counts are identical because they are deterministic.

Keep the absolute scale in view: encoding all five shapes with `ujson` instead of `json` saves
**2,111 µs on Android and 968 µs on iOS**, against the 16,700 µs a frame gets at 60 Hz. That is
real if you serialise on the UI thread, and irrelevant if you do it once behind a spinner.

Reach for ujson when you want the stdlib's API and semantics with a modest speedup on your
shape of data; reach for [`orjson`](../orjson) when you want the speed and can live with
`bytes` output. Measured in one round-robin harness on the `records` document from the table
above — the example's, at 1,000 items, 177,828 bytes at `json` compact — against `orjson`
3.11.9, the version this index ships: `json.dumps` 1.06 ms, `ujson.dumps` 0.74 ms (1.43×),
`orjson.dumps` 0.19 ms (5.7×); parsing back, 0.82 ms, 0.61 ms (1.34×) and 0.37 ms (2.23×).

The compatibility is genuinely good where it counts: 5,000 randomly generated documents —
nested dicts and lists, accented strings, slashes, integers up to `2**80`, floats across
eighteen orders of magnitude — round-tripped through both libraries with **0 mismatched
objects in either direction**. The places it does break are listed in
[Things to know](#things-to-know); the one that will bite silently is
`except json.JSONDecodeError`, which does not catch ujson's decode error.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "ujson",
]
```

Nothing to configure, but **on Android something does follow it in**: the Android wheels
declare `Requires-Dist: flet-libcpp-shared (>=27.2.12479018)`, because the extension links
the NDK's C++ runtime (see [Android notes](#android-notes)). Resolving the way `flet build`
does — `pip download --only-binary :all: --platform … --extra-index-url
https://pypi.flet.dev` — over all three Android ABIs and iOS device plus both simulator
slices, on 3.12, 3.13 and 3.14, all eighteen came back with this index's wheel, and each of
the three Android ones additionally fetched `flet_libcpp_shared` 27.3.13750724. That is
worth checking against, because a wheel that *needs* `libc++_shared.so` and does not declare
it fails at import on device with `dlopen failed: library "libc++_shared.so" not found`. The
iOS wheels declare no `Requires-Dist` at all; iOS links the OS's own libc++.

A bare `ujson` really does resolve from this index on every slice, and it has to: upstream
publishes 76 files at 5.12.1 and not one is Android, iOS or `py3-none-any`, so PyPI has
nothing pip can select for a mobile target.

The entry nevertheless belongs in top-level `[project] dependencies` and not in a
`[tool.flet.android]` / `[tool.flet.ios]` table, because `flet build` also resolves for the
build host, and PyPI does have a desktop wheel for every host you would build from: those 76
files are one sdist and 75 wheels, covering CPython 3.10 through 3.14 on macOS (`x86_64` and
`arm64`), `manylinux`/`musllinux` (`x86_64`, `aarch64`, `i686`) and Windows (`win32`,
`win_amd64`, `win_arm64`). Keeping it top-level is also what makes `flet run` on your laptop exercise the
same API you will ship — which matters here, since the whole point of the package is that
the API is the stdlib's.

Builds cover all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and iOS
device plus both simulator slices, on 3.12, 3.13 and 3.14 — nineteen wheels at the same build
number, those eighteen combinations plus a legacy 32-bit `android_24_x86` slice on 3.12. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed, and no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry either: **the wheel ships no Python module at all**. Its entries are the extension, a
`ujson-stubs/__init__.pyi` type stub, five `dist-info` files, and — on seventeen of the
nineteen slices, all but `armeabi_v7a` on 3.13 and 3.14 — a stray upstream
`src/ujson/python/version.h`. So there is no shipped code that could read a data file, and
after Flet's default package cleanup (`cleanup.packages`, on by default) even those non-code
files are gone, since serious_python's junk-file list carries `**.pyi` and `**.h`
(checked in 4.3.6 and 4.5.1). What reaches the device is one extension.

`Requires-Python` in the wheel is upstream's `>=3.10`, so the floor you will actually hit is
Flet's.

## Storage

Unlike some faster codecs, ujson **has** a file API — `ujson.dump(obj, fp)` and
`ujson.load(fp)` — and `dumps` returns `str`, so the stdlib idiom transfers unchanged. A JSON
file the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.json")
with open(path, "w", encoding="utf-8") as handle:
    ujson.dump(settings, handle)
with open(path, encoding="utf-8") as handle:
    settings = ujson.load(handle)
```

The two handle types are not symmetric, which is the one thing to get right:
`ujson.dump` needs a **text** handle and raises `TypeError: a bytes-like object is required,
not 'str'` on a binary one, while `ujson.load` accepts text and binary handles alike
(measured on desktop with the same file). The shipped stub says as much —
`dump(obj, fp: SupportsWrite[str])`, `load(fp: SupportsRead[str | bytes | bytearray])` — so a
type checker catches it before a device does.

ujson itself opens nothing and reaches nothing. Of the ~96 undefined symbols on the Android
arm64 slice, none is `open`, `fopen`, `stat`, `getenv`, `socket` or `connect`; the only
stdio names present (`fprintf`, `fwrite`, `fflush`, `__sF`) sit on the C++ runtime's abort
path. So there is no cache or config directory to point anywhere before importing it, and
nothing here needs the network — every byte it touches is one you passed in.

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. There is no atomic-write machinery here — one `dump()`
is one write — so if a truncated file on a killed app would hurt, write beside the target and
`os.replace` it yourself.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`shape-bench`](examples/shape-bench) — times ujson against the stdlib `json` on five payload shapes at
  three sizes, and answers eight drop-in questions with calls made on the device.

## Threading

**ujson holds the GIL for the whole call, so threads buy no parallelism.** Measured on
desktop against a control that does release it, on the example's 1,000-record document
(177,832 bytes of ujson output, four more than `json` compact's 177,828 because of the
escaped slashes): four threads each doing 60 `loads` never beat one thread doing the same 60,
for a parallel speedup of **0.64–0.83×** across three processes, where the same harness gave
`hashlib.sha256` on a buffer sized to cost the same per call **2.4–3.7×**. Four threads are
in fact *slower* than serial here, because each builds its own 1,000-record object graph and
they contend for the allocator as well as for the GIL. The symbols agree:
`PyEval_SaveThread`, `PyEval_RestoreThread` and `PyGILState_*` appear in the undefined
symbols of **none** of the nineteen slices, so there is no GIL-release path in the extension
to reach. `pthread_create` is absent from all nineteen too, so nothing in the wheel starts a
thread of its own.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
buy is an event handler that returns immediately, which matters at megabyte payloads and not
at all at kilobyte ones — a 100-record document serialises in 71 µs on desktop. The Flet-side
rules apply as everywhere: a worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and its body must be wrapped in `try/except`, because
`run_thread` discards whatever it raises — a serialisation error in a worker looks like a
screen that stopped updating rather than like an error.

There is no shared handle to serialise: `dumps` and `loads` are functions with no state you
hold, and since the GIL is held for the whole call there is nothing for two threads to
interleave inside one.

## Android notes

The extension links the NDK C++ runtime, which is the one thing that makes this package's
Android story different from a pure-C codec's. `DT_NEEDED` on all ten Android slices is
`libm.so`, `libpython3.<minor>.so`, **`libc++_shared.so`**, `libdl.so` and `libc.so`, and the
reason is visible in the symbol table: of the 88–96 named undefined dynamic symbols per slice
(`readelf --dyn-syms` prints one more, the unnamed index-0 entry every ELF carries), five
are C++ — `std::__ndk1::locale::classic`, `use_facet`, `ctype<char>::id`, `operator new` and
`operator delete` — coming from the bundled double-conversion code that formats and parses
the numbers. Everything else is CPython's API or bionic (`malloc`, `memcpy`, `__cxa_atexit`,
`dl_iterate_phdr`, the pthread rwlock family, `syscall`).

That runtime is not free, and it really does arrive. An APK built from the
[example](examples/shape-bench) — whose only added dependency is ujson — carries
`lib/arm64-v8a/libc++_shared.so` at **1,292,904 bytes**, `lib/armeabi-v7a/` at 872,872 and
`lib/x86_64/` at 1,252,080, beside `libujson.so` at 121,552 / 70,960 / 127,064 and an
11-byte `ujson.soref` in `sitepackages.zip`. So the C++ runtime is about ten times ujson's
own arm64 extension. If your app already pulls a C++ package the cost is shared; if ujson is
the only one, that is what the drop-in costs on Android. A wheel that needed that `.so` and
failed to declare it would instead fail at import with `dlopen failed: library
"libc++_shared.so" not found` — this one declares it, and the APK is the proof.

All `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires. arm64-v8a and
x86_64 are `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
`ELF32`/`i386` builds rather than stubs.

**The extension's filename is not the same on every Python**, which matters if you go looking
for it in an app payload: 3.13 and 3.14 ship
`ujson.cpython-3<minor>-aarch64-linux-android.so` (and `…-arm-linux-androideabi.so`,
`…-x86_64-linux-android.so`), while the 3.12 wheels from the same build ship a bare
`ujson.cpython-312.so`. Both spellings carry the `cpython-<minor>` ABI tag, which is what
Android's packaging keys on.

**ujson is a top-level module, not a package** — there is no `ujson/` directory and no
`__init__.py`, just `ujson.<tag>.so` at the root of site-packages. Flet relocates every
tagged extension out of site-packages, so `ujson.__file__` is not a path inside your app, and
whether the attribute exists at all varies by platform: for the same Flet version
[`pydantic-core`](../pydantic-core) reports none on Android where [`pyyaml`](../pyyaml)
reports a bare `jniLibs` filename. Code that locates anything relative to a module's
`__file__` breaks here. The [example](examples/shape-bench) prints whatever this device resolved,
through `__spec__.origin` when `__file__` is missing, so you can read the answer instead of
predicting it.

## iOS notes

**The extension needs no fixing up.** All nine iOS slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging links — so the
`MH_BUNDLE` link failure that has bitten other recipes on this index does not apply here.

`otool -L` names three libraries besides the install name:
`@rpath/Python.framework/Python`, `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib`.
The middle one is the same C++ dependency Android pays 1.3 MB for, except that on iOS it is
an OS library — **so there is nothing extra to ship, and the iOS wheels declare no
`Requires-Dist` at all.** The undefined symbols are the mirror image of Android's: 88–89 per
slice, five C++ (`std::__1::locale` and the two `operator new`/`delete`), the rest CPython's
API, libc, the Itanium unwinder and `dyld_stub_binder`.

iOS carries about **34% more native code than Android arm64** for the same version —
162,888 bytes against 121,552 on 3.14 — and yet the iOS wheel is the *smaller* download,
53,849 bytes against 62,085, with a `METADATA` that is 8 KB larger. The Mach-O simply
compresses better than the ELF; nothing about the code differs. As on Android, relocation
means `ujson.__file__` is not the path in the wheel: serious_python turns each site-packages
`.so` into a framework and leaves a `<name>.fwork` pointer file behind.

## Things to know

- **`except json.JSONDecodeError:` does not catch ujson's decode error.**
  `ujson.JSONDecodeError` subclasses `ValueError` directly — `issubclass(ujson.JSONDecodeError,
  json.JSONDecodeError)` is `False` — so an existing handler stops firing the moment you swap
  the import, and a malformed payload becomes an unhandled exception, which in a Flet handler
  crashes the session. Catch `ValueError`, which covers both. The error object is also barer
  than the stdlib's: **no `.pos`, `.lineno`, `.colno`, `.msg` or `.doc`**, and the messages
  carry no position — `ujson.loads("")` says `Expected object or value` where
  `json.loads("")` says `Expecting value: line 1 column 1 (char 0)`, and `'{"a":1} junk'`
  gives `Trailing data` against json's `Extra data: line 1 column 9 (char 8)`. Anything that
  reported *where* a document went wrong loses that ability.
- **`loads()` takes no keyword arguments at all**, so `object_hook`, `object_pairs_hook`,
  `parse_float`, `parse_int` and the old `precise_float` are gone: every one raises
  `TypeError: function takes at most 1 argument (2 given)`. Money code built on
  `json.loads(text, parse_float=Decimal)` cannot be swapped — keep the stdlib for that call
  and post-process elsewhere.
- **Output is not byte-identical to the stdlib's, because `/` is escaped by default.**
  `ujson.dumps({"u": "a/b"})` is `{"u":"a\/b"}` where `json.dumps` compact gives
  `{"u":"a/b"}`. It is still valid JSON and `json.loads` reads it back correctly, but it is
  bigger: 65,001 bytes against 58,001 on a list of 1,000 CDN URLs, **+12.07%**. Pass
  `escape_forward_slashes=False` to turn it off — it costs nothing measurable (0.054 ms
  either way on that list, against `json.dumps` compact's 0.081 ms) and gives back
  byte-identical output on that list. Across arbitrary documents it is *nearly* identical:
  of 5,000 randomly generated ones, 109 still differed with escaping off, all of them
  single-digit negative exponents, where ujson writes `1e-5` and the stdlib writes `1e-05`.
  The values are equal; only the text differs. If you sign or hash serialised JSON, those two
  details are what will break you.
- **The data itself survives the swap.** The 5,000-document corpus above produced **0**
  object mismatches: `ujson.loads(ujson.dumps(d))` equalled
  `json.loads(json.dumps(d))` every time, and each library parsed the other's output to the
  same object. Floats are exact too — 0 of 20,000 random doubles failed to round-trip, and
  `5e-324`, `1.7976931348623157e+308` and `0.1` all come back identical.
- **Big integers are exact in both directions**, which is not true of every fast JSON
  library: `2**64`, `2**100` and a bare 23-digit literal all serialise and parse as exact
  `int`, matching the stdlib.
- **`NaN` and `Infinity` behave exactly like the stdlib** — both emit the non-standard
  `NaN`/`Infinity` and both read them back — so a ujson producer and a stdlib consumer agree.
  The strict switch differs only in its exception: `ujson.dumps(nan, allow_nan=False)` raises
  `OverflowError: Invalid value when encoding double` where the stdlib raises `ValueError`.
- **`Decimal` is accepted and silently rounded to a double.** `json.dumps` refuses a
  `Decimal` with `TypeError`; ujson emits it as a float, so
  `Decimal("1.234567890123456789012345")` becomes `1.2345678901234567` and
  `Decimal("1E-400")` becomes `0.0`. Nothing raises. If you moved to `Decimal` for precision,
  ujson gives it back to the double you were avoiding — dump `str(value)` instead.
- **A non-string dict key is stringified further than the stdlib will go.** Both libraries
  coerce `int`, `float`, `bool` and `None` keys the same way (`"1"`, `"1.5"`, `"true"`,
  `"null"`), but a **tuple key** raises `TypeError: keys must be str, int, float, bool or
  None, not tuple` under the stdlib and quietly becomes `{"(1, 2)":"a"}` under ujson — its
  `repr`, as a key, with no error. `str()` your keys at the boundary.
- **`bytes` are rejected on the way out and accepted on the way in.**
  `ujson.dumps(b"abc")` raises `TypeError: reject_bytes is on and 'abc' is bytes`
  (`reject_bytes` defaults to `True`; passing `False` emits `"abc"` and will produce mojibake
  for non-UTF-8 input), while `ujson.loads(b'{"a":1}')` works.
- **The encoder gives up at 1,024 nested containers**, where the stdlib does not.
  1,024 nested dicts or lists serialise; 1,025 raises `OverflowError: Maximum recursion level
  reached`, and `json.dumps` handles the same structure fine. The decoder has the matching cap
  — 1,024 levels of array nesting parse, 1,025 raises `JSONDecodeError: Reached object
  decoding depth limit`. A **circular reference** falls into the same trap: the stdlib
  detects it immediately with `ValueError: Circular reference detected`, while ujson walks
  1,024 levels first and then raises `OverflowError`.
- **The formatting keywords are there, with one edge that differs.** `sort_keys=True`,
  `indent=2`, `ensure_ascii=False`, `separators=(",", ": ")`, `encode_html_chars=True` and
  `escape_forward_slashes=False` all work and match the stdlib where they overlap — nested
  `indent=2` output is byte-identical, and `sort_keys` sorts by code point exactly as the
  stdlib does. `cls=` and `skipkeys=` do not exist (`TypeError: 'cls' is an invalid keyword
  argument for this function`). And `indent=0` means opposite things: ujson emits compact
  output, the stdlib emits one item per line.
- **Speed is shape-dependent, and one shape is a loss.** Desktop CPython 3.12 on an arm64 Mac,
  1,000 items per shape, `json` at its compact setting: `dumps` 2.93× on floats, 1.52× on
  URLs, 1.47× on API records, 1.05× on accented text and **0.62× on booleans** — i.e.
  1.6× *slower* than the stdlib on the cheapest possible values, and it gets worse with size
  rather than better: 1.20× at 100 items, 0.62× at 1,000, 0.53× at 5,000. `loads` came out
  1.10×–2.73× and never lost in these runs. CPython 3.14 shifts the numbers without changing
  the picture (booleans 0.72×, floats 2.92×). Two things follow: measure
  *your* payload rather than a benchmark's, and remember all of this is microseconds unless
  your documents are megabytes — the [example](examples/shape-bench) does exactly that measurement
  on the device in your hand.
- **The ratios were re-checked on device, and the desktop harness predicted their signs but
  not their sizes.** On 2026-08-20 the example ran on an arm64-v8a Android 14 emulator and an
  iPhone 16 simulator, both CPython 3.14.6. Every sign held — floats the biggest win, booleans
  a loss, URLs the only size change — while the magnitudes moved a long way: floats 2.93× on
  desktop against **4.52×** on Android and **3.56×** on iOS, booleans 0.62× against **0.74×**
  and **0.84×**. So the desktop numbers are usable as a *shape*, and the device numbers in the
  table at the top of this page are the ones to quote. Everything else here is still a fact
  read from a published wheel or a built APK; see [Build notes](#build-notes-maintainers).
- **`import ujson` is cheaper than `import json` in a bare interpreter and strictly dearer
  inside a Flet app**, because `import flet` has already imported `json` for you. In a fresh
  interpreter ujson wins: `python -X importtime`, best of nine on desktop CPython 3.14.6,
  gives **0.72 ms against `json`'s 1.97 ms**. But `import flet` puts `json`, `json.decoder`,
  `json.encoder` and `_json` into `sys.modules`, so after it `import json` is a dictionary
  hit too small to time — 0.000 ms — while `import ujson` still costs **0.73 ms**, best of
  fifteen fresh interpreters. **Just over half of that is `decimal`**, which ujson pulls in —
  along with `numbers` and `collections.abc` — for its `Decimal` support, and which `flet`
  does not import (checked by diffing `sys.modules` across `import flet`): `import decimal`
  alone costs 0.38 ms there, and with `decimal` already loaded `import ujson` drops to
  0.33 ms. Startup is the one budget where the stdlib wins outright.
- **Size: 46–70 KB to download, 81–183 KB unpacked, and 86–92% of it is the extension.**
  Per slice, on Python 3.14 (3.12 and 3.13 are within 1.1 KB on Android arm64):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 62,085 | 133,194 | 121,552 |
  | Android armeabi-v7a | 45,881 | 80,521 | 70,960 |
  | Android x86_64 | 65,706 | 138,702 | 127,064 |
  | iOS arm64 (device) | 53,849 | 182,819 | 162,888 |
  | iOS arm64 (simulator) | 56,083 | 167,761 | 147,816 |
  | iOS x86_64 (simulator) | 56,946 | 138,170 | 118,224 |

  On Android add `flet-libcpp-shared`'s 1,292,904-byte arm64 runtime to that, which dwarfs
  it. Everything besides the extension is a 5,975-byte licence, the 1,606-byte stub, a
  1,999-byte stray header and the `dist-info` — 11.6 KB on Android arm64 and x86_64,
  9.6 KB on armeabi-v7a, which ships no stray header, and 19.9 KB on every iOS slice,
  where the `METADATA` alone is 9,561 bytes against Android's 1,262. Android's is shorter
  because it carries the extra `Requires-Dist` line and none of upstream's long description,
  which forge's requirement injection drops (see
  [Build notes](#build-notes-maintainers)). Same code, different metadata; do not read the
  gap as a different build.
- **Most of these wheels put a namespace package called `src` in site-packages.** That stray
  `src/ujson/python/version.h` is upstream's own packaging accident — the PyPI desktop wheel
  installs it too, byte-identical — and it makes `import src` succeed against a namespace
  package whose `__path__` points into site-packages. Seventeen of the nineteen slices carry
  it; `armeabi_v7a` on 3.13 and 3.14 does not, for no reason visible in the recipe. Harmless
  either way, and on device it is removed by Flet's package cleanup along with the `.pyi`
  stub, but it is worth knowing if you ever wonder why `src` is importable in a venv where
  you never installed anything called `src`.

## Build notes (maintainers)

A `meta.yaml` naming the version and, under an `{% if sdk == 'android' %}` guard, one
`requirements.host` entry on `flet-libcpp-shared` — no patches, no `build.sh`. That guard is
the whole recipe, and the reason it exists is in the symbol table rather than in the build
log: five C++ symbols out of ~93 undefined ones, all from the bundled double-conversion
sources. If a future ujson drops that dependency, the guard and the resulting
`Requires-Dist` should go with it, and the check is one `readelf -d` for `libc++_shared.so`.

That injection has a side effect worth knowing before someone reports it as a bad build:
`Builder.write_message_file` rebuilds `METADATA` from its headers alone, so adding the
requirement drops the payload — upstream's long description — leaving the Android
`METADATA` at 1,262 bytes against the iOS slices' 9,561. Only the Android wheels are
affected, and only because only they have a requirement to add.

**No on-device run backs anything above this section.** Every claim came off the wheels, off
a built APK of the example, or off a desktop install of the same version. The APK settles
the packaging half — `libc++_shared.so` and `libujson.so` in `jniLibs`, the `.pyi` stub and
the stray `version.h` gone — but says nothing about what happens when the app starts. The
bridge that licenses the desktop kind is
narrow but real: `ujson-stubs/__init__.pyi`, `src/ujson/python/version.h` and `LICENSE.txt`
are byte-identical between the Android wheel, the iOS wheel and the PyPI 5.12.1 desktop
wheel, and every diagnostic string quoted above — `Trailing data`, `Expected object or
value`, `reject_bytes is on`, `Maximum recursion level reached`, `Reached object decoding
depth limit`, `is not JSON serializable` — is present verbatim in the Android arm64, Android
armeabi-v7a **and** iOS device binaries. What that does not establish is that `import ujson`
succeeds on a phone at all, or that the speed ratios hold on a phone core. The
[example](examples/shape-bench) is the missing evidence, and its header line and table are built to
be read off the screen.

The wheels on the index are build 10 from a repo-wide pass that ran in three parts: every 3.12
slice is dated 2026-06-04 and the 3.13 and 3.14 slices 2026-06-11, except the 3.13 and 3.14
armeabi-v7a pair, dated 2026-06-29 — a later rebuild at the same build number, and the two
that came out without the stray `version.h`. All nineteen are from setuptools 82.0.1.

`tests/test_ujson.py` is two functions — a `str`-returning round trip and a float round trip
— and neither carries the docstring this repo's test convention asks for. More usefully,
neither covers anything this page warns app authors about. In rough order of value, the
additions worth making are the `\/` escaping default (the claim a consumer meets first), the
`JSONDecodeError` base class (the one that breaks working code silently), `loads()` refusing
keywords, and `Decimal` rounding to a double.

On a bump, in rough order of what a green build fails to tell you:

- **`escape_forward_slashes` still defaulting to `True`**, and `separators`, `sort_keys`,
  `indent` and `ensure_ascii` still being accepted. These are the drop-in claims; upstream has
  added and removed keywords before (`precise_float` is gone).
- **`ujson.JSONDecodeError`'s base class**, and whether the error object grew `.pos`. If it
  ever becomes a `json.JSONDecodeError` subclass, the loudest bullet on this page becomes
  wrong in the consumer's favour and should be deleted rather than left standing.
- **The 1,024 nesting caps** on both directions. Compiled in, so a release can move them with
  no signal.
- **`Decimal` still being accepted** rather than raising, and still going through a double.
- **`DT_NEEDED` on the Android slices**, per the first paragraph — the recipe's only moving
  part.
- **The speed ratios**, which are the reason a reader would install this rather than use the
  stdlib. The example is the cheapest way to re-measure them: build it, change nothing, read
  the table.
