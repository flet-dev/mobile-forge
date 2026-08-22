# ujson

[`ujson`](https://github.com/ultrajson/ultrajson) is a JSON encoder and decoder written in C
that keeps the standard library's [`json`](https://docs.python.org/3/library/json.html)
*shapes* where the faster alternatives drop them: `dumps` returns `str`, `loads` takes `str` or
`bytes`, `dump`/`load` exist, and the familiar `indent`, `sort_keys`, `ensure_ascii` and
`separators` keywords all work. ([`orjson`](../orjson), also on this index, returns `bytes`
from `dumps` and has no `dump`/`load` at all.)

Whether that buys anything on a phone depends on the shape of your data, because the stdlib
`json` is **already C**: encoding a document of floats comes out 3.5–4.5× faster, encoding a
list of booleans is *slower*, and URL-heavy output is about 12% bigger.
[Speed](#speed) has the per-shape table, measured by the [example](examples/shape-bench) on the
device it was installed on.

It is nearly a drop-in, and the ways it is not are in [Things to know](#things-to-know). The
one that bites silently is `except json.JSONDecodeError`, which does not catch ujson's decode
error.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "ujson",
]
```

Keep that entry in top-level `[project] dependencies` rather than in a `[tool.flet.android]` or
`[tool.flet.ios]` table. `flet build` resolves for the build host as well as for the device, so
a mobile-only entry leaves `flet run` on your laptop without the package — which matters more
here than for most, since the whole point of ujson is that its API is the stdlib's, and the
desktop run is where you find the places it is not.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`shape-bench`](examples/shape-bench) — times ujson against the stdlib `json` on five payload
  shapes at three sizes, and answers eight drop-in questions with calls made on the device.

## Usage in a Flet app

```python
import ujson

encoded = ujson.dumps(report, indent=2, sort_keys=True)
report = ujson.loads(encoded)
preview = ft.Text(encoded)
```

Those are the stdlib's signatures, and that is the reason to choose this package over a faster
one: `dumps` hands back a `str` that goes straight into a Flet control, a text file or a
`str`-typed API, and formatting is keyword arguments rather than flags. Two things inside the
same API do not transfer. `loads()` accepts **no keyword arguments at all**, so `object_hook`
and `parse_float` are gone; and its decode error is not a `json.JSONDecodeError`, so an
`except` clause that works today stops firing the moment you swap the import. Both are in
[Things to know](#things-to-know).

### Storage

ujson **has** a file API — `ujson.dump(obj, fp)` and `ujson.load(fp)` — so the stdlib idiom
transfers unchanged. A JSON file the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.json")
with open(path, "w", encoding="utf-8") as handle:
    ujson.dump(settings, handle)
with open(path, encoding="utf-8") as handle:
    settings = ujson.load(handle)
```

The two handle types are not symmetric, which is the one thing to get right: `ujson.dump` needs
a **text** handle and raises `TypeError: a bytes-like object is required, not 'str'` on a
binary one, while `ujson.load` accepts text and binary handles alike (measured on desktop with
the same file). The shipped stub says as much — `dump(obj, fp: SupportsWrite[str])`,
`load(fp: SupportsRead[str | bytes | bytearray])` — so a type checker catches it before a
device does.

ujson opens nothing and reaches nothing on its own: there is no cache or config directory to
point anywhere before importing it, and nothing here touches the network. Every byte it handles
is one you passed in.

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. There is no atomic-write machinery here — one `dump()` is
one write — so if a truncated file on a killed app would hurt, write beside the target and
`os.replace` it yourself.

### Threading

**ujson holds the GIL for the whole call, so threads buy no parallelism.** Measured on desktop
against a control that does release it, on the example's 1,000-record document (177,832 bytes
of ujson output, four more than `json` compact's 177,828 because of the escaped slashes): four
threads each doing 60 `loads` never beat one thread doing the same 60, for a parallel speedup
of **0.64–0.83×** across three processes, where the same harness gave `hashlib.sha256` on a
buffer sized to cost the same per call **2.4–3.7×**. Four threads are in fact *slower* than
serial here, because each builds its own 1,000-record object graph and they contend for the
allocator as well as for the GIL. Nothing in the wheel starts a thread of its own either.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
buy is an event handler that returns immediately, which matters at megabyte payloads and not at
all at kilobyte ones — a 100-record document serialises in 71 µs on desktop. The Flet-side
rules apply as everywhere: a worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and its body must be wrapped in `try/except`, because
`run_thread` discards whatever it raises — a serialisation error in a worker looks like a
screen that stopped updating rather than like an error.

There is no shared handle to serialise: `dumps` and `loads` are functions with no state you
hold, and since the GIL is held for the whole call there is nothing for two threads to
interleave inside one.

### Speed

The win is a distribution, not a number, because the stdlib is already C. Measured by the
[example](examples/shape-bench) on 2026-08-20 — 1,000 items per shape, `json` called at its own
compact setting, best of 150/40/10 calls — on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. Speedups are `json` time over `ujson` time, so above 1 is a win:

| shape, 1,000 items | `dumps` Android | `dumps` iOS | `loads` Android | `loads` iOS | output size |
| --- | --- | --- | --- | --- | --- |
| `records` — API-shaped objects | **2.83×** | **1.98×** | 1.29× | 1.49× | +0.0% |
| `floats` | **4.52×** | **3.56×** | 2.50× | 2.37× | +0.0% |
| `flags` — booleans | **0.74× — slower** | **0.84× — slower** | 1.69× | 1.63× | +0.0% |
| `URLs` | 1.73× | 1.69× | 1.29× | 1.19× | **+12.1% — bigger** |
| `text` — accented strings | 1.12× | 1.10× | **3.90×** | **3.15×** | +0.0% |

A large win on numbers, a wash on writing strings (though a 3–4× win parsing them), a **loss on
booleans on both platforms**, and on URL-heavy documents *more* bytes, because ujson escapes `/`
by default. The two platforms disagree on magnitude and agree on every sign; the byte counts are
identical because they are deterministic.

Keep the absolute scale in view: encoding all five shapes with ujson instead of `json` saves
**2,111 µs on Android and 968 µs on iOS**, against the 16,700 µs a frame gets at 60 Hz. That is
real if you serialise on the UI thread, and irrelevant if you do it once behind a spinner.

A desktop harness — CPython 3.12 on an arm64 Mac, the same shapes at 1,000 items — predicted
every sign and none of the magnitudes: floats 2.93× against the run above at 4.52× and 3.56×,
booleans 0.62× against 0.74× and 0.84×, and records 1.47×, URLs 1.52×, text 1.05×. The boolean
loss also gets *worse* with size rather than better — 1.20× at 100 items, 0.62× at 1,000, 0.53×
at 5,000. So measure your payload at your size; an emulator and a simulator are not a handset
either, and the example re-runs the whole table on whatever it is installed on.

Reach for ujson when you want the stdlib's API and semantics with a modest speedup on your
shape of data; reach for [`orjson`](../orjson) when you want the speed and can live with `bytes`
output. One desktop round-robin on the `records` document above at 1,000 items (177,828 bytes at
`json` compact), against orjson 3.11.9: `json.dumps` 1.06 ms, `ujson.dumps` 0.74 ms (1.43×),
`orjson.dumps` 0.19 ms (5.7×); parsing back, 0.82 ms, 0.61 ms (1.34×) and 0.37 ms (2.23×).

### App size

Per architecture the wheel is roughly **45–70 KB compressed and 80–185 KB unpacked**, of which
86–92% is the extension. On Android that is not the whole cost. The extension links a shared C++
runtime that Android does not carry in the OS, so the APK gains that too: in a build of the
[example](examples/shape-bench), whose only added dependency is ujson, the runtime lands at
about **0.87 MB on armeabi-v7a, 1.25 MB on x86_64 and 1.29 MB on arm64-v8a** — roughly ten
times ujson's own extension. If your app already ships a C++ package the cost is shared; if
ujson is the only one, that is what the drop-in costs. iOS pays nothing extra, because there the
C++ runtime is an OS library.

The Android levers are the usual ones — an app bundle, split APKs, or narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) — and
they are worth reaching for because of that runtime rather than because of ujson.
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing left
to remove here: it already drops the type stub on device, and what reaches the phone is one
extension.

### Other considerations

A desktop `flet run` installs PyPI's wheel, which is the same C code at the same version behind
the same API — that is the point of the package. Three things still differ once it is on a
device.

**`ujson.__file__` is not a path inside your app, on either platform.** ujson is a top-level
module rather than a package — no `ujson/` directory and no `__init__.py`, just `ujson.<tag>.so`
at the root of site-packages — and Flet relocates every tagged extension out of site-packages.
Whether the attribute survives at all varies: for the same Flet version
[`pydantic-core`](../pydantic-core) reports none on Android where [`pyyaml`](../pyyaml) reports
a bare `jniLibs` filename, and on iOS serious_python turns each site-packages `.so` into a
framework and leaves a `<name>.fwork` pointer file behind. Code that locates anything relative
to a module's `__file__` breaks here. The [example](examples/shape-bench) prints whatever this
device resolved, through `__spec__.origin` when `__file__` is missing, so you can read the
answer instead of predicting it.

**Desktop ratios predict signs, not magnitudes.** Re-measure before designing around one — see
[Speed](#speed).

**A namespace package called `src` shows up in a desktop site-packages.** Most of these wheels
carry a stray upstream `src/ujson/python/version.h` — the PyPI desktop wheel installs it too,
byte-identical — and it makes `import src` succeed against a namespace package whose `__path__`
points into site-packages. Harmless, and Flet's package cleanup removes it on device; worth
knowing if you ever wonder why `src` is importable in a venv where you never installed anything
called `src`.

## Things to know

- **`except json.JSONDecodeError:` does not catch ujson's decode error.**
  `ujson.JSONDecodeError` subclasses `ValueError` directly — `issubclass(ujson.JSONDecodeError,
  json.JSONDecodeError)` is `False` — so an existing handler stops firing the moment you swap
  the import, and a malformed payload becomes an unhandled exception, which in a Flet handler
  crashes the session. Catch `ValueError`, which covers both. The error object is also barer
  than the stdlib's: **no `.pos`, `.lineno`, `.colno`, `.msg` or `.doc`**, and the messages
  carry no position — `ujson.loads("")` says `Expected object or value` where `json.loads("")`
  says `Expecting value: line 1 column 1 (char 0)`, and `'{"a":1} junk'` gives `Trailing data`
  against json's `Extra data: line 1 column 9 (char 8)`. Anything that reported *where* a
  document went wrong loses that ability.

- **`loads()` takes no keyword arguments at all**, so `object_hook`, `object_pairs_hook`,
  `parse_float`, `parse_int` and the old `precise_float` are gone: every one raises
  `TypeError: function takes at most 1 argument (2 given)`. Money code built on
  `json.loads(text, parse_float=Decimal)` cannot be swapped — keep the stdlib for that call and
  post-process elsewhere.

- **Output is not byte-identical to the stdlib's, because `/` is escaped by default.**
  `ujson.dumps({"u": "a/b"})` is `{"u":"a\/b"}` where `json.dumps` compact gives `{"u":"a/b"}`.
  It is still valid JSON and `json.loads` reads it back correctly, but it is bigger: 65,001
  bytes against 58,001 on a list of 1,000 CDN URLs, **+12.07%**. Pass
  `escape_forward_slashes=False` to turn it off — it costs nothing measurable (0.054 ms either
  way on that list, against `json.dumps` compact's 0.081 ms) and gives back byte-identical
  output there. Across arbitrary documents it is *nearly* identical: of 5,000 randomly generated
  ones, 109 still differed with escaping off, all of them single-digit negative exponents, where
  ujson writes `1e-5` and the stdlib writes `1e-05`. The values are equal; only the text
  differs. If you sign or hash serialised JSON, those two details are what will break you.

- **The data itself survives the swap.** Those 5,000 documents — nested dicts and lists,
  accented strings, slashes, integers up to `2**80`, floats across eighteen orders of magnitude
  — produced **0 object mismatches** in either direction: `ujson.loads(ujson.dumps(d))` equalled
  `json.loads(json.dumps(d))` every time, and each library parsed the other's output to the same
  object. Floats are exact too — 0 of 20,000 random doubles failed to round-trip, and `5e-324`,
  `1.7976931348623157e+308` and `0.1` all come back identical.

- **Big integers are exact in both directions**, which is not true of every fast JSON library:
  `2**64`, `2**100` and a bare 23-digit literal all serialise and parse as exact `int`, matching
  the stdlib.

- **`NaN` and `Infinity` behave exactly like the stdlib** — both emit the non-standard
  `NaN`/`Infinity` and both read them back — so a ujson producer and a stdlib consumer agree.
  The strict switch differs only in its exception: `ujson.dumps(nan, allow_nan=False)` raises
  `OverflowError: Invalid value when encoding double` where the stdlib raises `ValueError`.

- **[`Decimal`](https://docs.python.org/3/library/decimal.html#decimal.Decimal) is accepted and
  silently rounded to a double.** `json.dumps` refuses a `Decimal` with `TypeError`; ujson emits
  it as a float, so `Decimal("1.234567890123456789012345")` becomes `1.2345678901234567` and
  `Decimal("1E-400")` becomes `0.0`. Nothing raises. If you moved to `Decimal` for precision,
  ujson gives it back to the double you were avoiding — dump `str(value)` instead.

- **A non-string dict key is stringified further than the stdlib will go.** Both libraries
  coerce `int`, `float`, `bool` and `None` keys the same way (`"1"`, `"1.5"`, `"true"`,
  `"null"`), but a **tuple key** raises `TypeError: keys must be str, int, float, bool or None,
  not tuple` under the stdlib and quietly becomes `{"(1, 2)":"a"}` under ujson — its `repr`, as
  a key, with no error. `str()` your keys at the boundary.

- **`bytes` are rejected on the way out and accepted on the way in.** `ujson.dumps(b"abc")`
  raises `TypeError: reject_bytes is on and 'abc' is bytes` (`reject_bytes` defaults to `True`;
  passing `False` emits `"abc"` and will produce mojibake for non-UTF-8 input), while
  `ujson.loads(b'{"a":1}')` works.

- **The encoder gives up at 1,024 nested containers**, where the stdlib does not. 1,024 nested
  dicts or lists serialise; 1,025 raises `OverflowError: Maximum recursion level reached`, and
  `json.dumps` handles the same structure fine. The decoder has the matching cap — 1,024 levels
  of array nesting parse, 1,025 raises `JSONDecodeError: Reached object decoding depth limit`. A
  **circular reference** falls into the same trap: the stdlib detects it immediately with
  `ValueError: Circular reference detected`, while ujson walks 1,024 levels first and then
  raises `OverflowError`.

- **The formatting keywords are there, with one edge that differs.** `sort_keys=True`,
  `indent=2`, `ensure_ascii=False`, `separators=(",", ": ")`, `encode_html_chars=True` and
  `escape_forward_slashes=False` all work and match the stdlib where they overlap — nested
  `indent=2` output is byte-identical, and `sort_keys` sorts by code point exactly as the stdlib
  does. `cls=` and `skipkeys=` do not exist (`TypeError: 'cls' is an invalid keyword argument
  for this function`). And `indent=0` means opposite things: ujson emits compact output, the
  stdlib emits one item per line.

- **`import ujson` is cheaper than `import json` in a bare interpreter and strictly dearer
  inside a Flet app**, because `import flet` has already imported `json` for you. In a fresh
  interpreter ujson wins: `python -X importtime`, best of nine on desktop CPython 3.14.6, gives
  **0.72 ms against `json`'s 1.97 ms**. But `import flet` puts `json`, `json.decoder`,
  `json.encoder` and `_json` into `sys.modules`, so after it `import json` is a dictionary hit
  too small to time — 0.000 ms — while `import ujson` still costs **0.73 ms**, best of fifteen
  fresh interpreters. **Just over half of that is `decimal`**, which ujson pulls in — along with
  `numbers` and `collections.abc` — for its `Decimal` support, and which `flet` does not import
  (checked by diffing `sys.modules` across `import flet`): `import decimal` alone costs 0.38 ms
  there, and with `decimal` already loaded `import ujson` drops to 0.33 ms. Startup is the one
  budget where the stdlib wins outright.

## Build notes (maintainers)

### Recipe shape

A `meta.yaml` naming the version and, under an `{% if sdk == 'android' %}` guard, one
`requirements.host` entry — no patches, no `build.sh`. The recipe exists at all only because
PyPI has nothing pip can select for a mobile target: upstream publishes 76 files at this
version, and not one is Android, iOS or `py3-none-any`.

That guard is the whole recipe, and its reason is in the symbol table rather than in the build
log: of the 88–96 named undefined dynamic symbols per Android slice (`readelf --dyn-syms` prints
one more, the unnamed index-0 entry every ELF carries), five are C++ —
`std::__ndk1::locale::classic`, `use_facet`, `ctype<char>::id`, `operator new` and
`operator delete` — from the bundled double-conversion sources that format and parse the
numbers. Everything else is CPython's API or bionic. `meta.yaml`'s comment owns the mechanism;
what it does not carry is how to test the guard and how to know the declaration works:

- **Removal test.** `readelf -d` the Android slices for `libc++_shared.so`. If a future ujson
  stops linking it, the guard and the resulting `Requires-Dist` go with it. A wheel that needs
  that `.so` and fails to declare it fails at import on device with `dlopen failed: library
  "libc++_shared.so" not found`, so this is worth checking rather than assuming.
- **The declaration resolves.** Resolving the way `flet build` does —
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev` — over
  all three Android ABIs and iOS device plus both simulator slices, on 3.12, 3.13 and 3.14, all
  eighteen came back with this index's wheel, and each of the three Android ones additionally
  fetched `flet_libcpp_shared` 27.3.13750724. The iOS wheels declare no `Requires-Dist` at all;
  iOS links the OS's own libc++.

What the wheels look like, since the consumer sections rest on it:

- **Nineteen slices at one build number** — three Android ABIs plus iOS device and both
  simulator slices, on 3.12, 3.13 and 3.14, plus a legacy 32-bit `android_24_x86` slice on 3.12.
  `Requires-Python` is upstream's `>=3.10`, so the floor a consumer actually hits is Flet's.
- **No Python module at all.** The entries are the extension, a `ujson-stubs/__init__.pyi` type
  stub, five `dist-info` files, and — on seventeen of the nineteen, all but `armeabi_v7a` on
  3.13 and 3.14 — a stray upstream `src/ujson/python/version.h`. So nothing shipped could read a
  data file, and after Flet's default package cleanup even those non-code files are gone, since
  serious_python's junk-file list carries `**.pyi` and `**.h` (checked in 4.3.6 and 4.5.1).
- **Byte-exact sizes on Python 3.14**, which the rounded ranges under [App size](#app-size) come
  from (3.12 and 3.13 are within 1.1 KB on Android arm64):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 62,085 | 133,194 | 121,552 |
  | Android armeabi-v7a | 45,881 | 80,521 | 70,960 |
  | Android x86_64 | 65,706 | 138,702 | 127,064 |
  | iOS arm64 (device) | 53,849 | 182,819 | 162,888 |
  | iOS arm64 (simulator) | 56,083 | 167,761 | 147,816 |
  | iOS x86_64 (simulator) | 56,946 | 138,170 | 118,224 |

  The remainder per slice is a 5,975-byte licence, the 1,606-byte stub, the 1,999-byte stray
  header and the `dist-info` — 11.6 KB on Android arm64 and x86_64, 9.6 KB on armeabi-v7a (which
  ships no stray header) and 19.9 KB on every iOS slice. iOS carries about 34% more native code
  than Android arm64 and is still the smaller download; the Mach-O simply compresses better than
  the ELF.
- **Android linkage.** `DT_NEEDED` on all ten Android slices is `libm.so`,
  `libpython3.<minor>.so`, **`libc++_shared.so`**, `libdl.so` and `libc.so`. All `PT_LOAD`
  segments carry 16 KB alignment, which Android 15 requires; armeabi-v7a and the legacy `x86`
  slice are genuine `ELF32`/`ARM` and `ELF32`/`i386` builds rather than stubs. In an APK built
  from the example, `lib/arm64-v8a/libc++_shared.so` is 1,292,904 bytes beside `libujson.so` at
  121,552 (armeabi-v7a 872,872 / 70,960, x86_64 1,252,080 / 127,064), plus an 11-byte
  `ujson.soref` in `sitepackages.zip`.
- **iOS linkage.** Every slice is already `MH_DYLIB` marked `NOUNDEFS` (`otool -hv`), so forge's
  `MH_BUNDLE` conversion never applies here. `otool -L` names `@rpath/Python.framework/Python`,
  `/usr/lib/libc++.1.dylib` and `/usr/lib/libSystem.B.dylib` — the middle one being the same C++
  dependency Android pays 1.3 MB for, except that on iOS it is an OS library. Undefined symbols
  are the mirror image of Android's: 88–89 per slice, five C++ (`std::__1::locale` and the two
  `operator new`/`delete`), the rest CPython's API, libc, the Itanium unwinder and
  `dyld_stub_binder`.
- **No threading machinery** — `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState_*` and
  `pthread_create` are absent from all nineteen slices. That is the evidence behind
  [Threading](#threading): no GIL-release path to reach, and nothing that starts a thread.
- **No I/O of its own** — of the ~96 undefined symbols on the Android arm64 slice, none is
  `open`, `fopen`, `stat`, `getenv`, `socket` or `connect`; the only stdio names present
  (`fprintf`, `fwrite`, `fflush`, `__sF`) sit on the C++ runtime's abort path. That is the
  evidence behind [Storage](#storage).

One side effect of the requirement injection is worth knowing before someone reports it as a bad
build: `Builder.write_message_file` rebuilds `METADATA` from its headers alone, so adding the
requirement drops the payload — upstream's long description — leaving the Android `METADATA` at
1,262 bytes against the iOS slices' 9,561. Only the Android wheels are affected, and only
because only they have a requirement to add. Same code, different metadata.

### Upgrade hazards

- **Almost everything the sections above tell an app author is C behaviour, not structure**: the
  escaping default, the nesting caps, the `JSONDecodeError` base class, the `Decimal` rounding,
  the wording of every diagnostic. All of it can move in a point release without the build so
  much as blinking, so a green CI run is not evidence that any of it survived.
- **The extension's filename spelling differs per Python.** 3.13 and 3.14 ship
  `ujson.cpython-3<minor>-aarch64-linux-android.so` (and `…-arm-linux-androideabi.so`,
  `…-x86_64-linux-android.so`) where the 3.12 wheels from the same build ship a bare
  `ujson.cpython-312.so`. Both carry the `cpython-<minor>` ABI tag, which is what Android's
  packaging keys on; an *untagged* `.so` would be a silent `ModuleNotFoundError` on device.
- **ujson is a top-level module, not a package.** Any upstream move to a `ujson/` directory
  would put the Android zipped-site-packages story, and the `__file__` note under
  [Other considerations](#other-considerations), back in question.
- **The build on the index was not produced in one pass.** Build 10: every 3.12 slice is dated
  2026-06-04 and the 3.13 and 3.14 slices 2026-06-11, except the 3.13 and 3.14 armeabi-v7a pair,
  dated 2026-06-29 — a later rebuild at the same build number, and the two that came out without
  the stray `version.h`. All nineteen are from setuptools 82.0.1. Rebuild the set together
  rather than assuming uniformity.
- **The day upstream ships a mobile-tagged or `py3-none-any` wheel, this recipe may stop being
  needed.** It is needed today only because PyPI has nothing pip can select for an Android or
  iOS target.
- **The example's pin.** `examples/shape-bench/pyproject.toml` pins ujson with `==`; bump it in
  the same commit and rebuild, which is what makes the example a live regression test of the
  bump.

### Re-verification checklist

- **`escape_forward_slashes` still defaulting to `True`**, and `separators`, `sort_keys`,
  `indent` and `ensure_ascii` still being accepted. These are the drop-in claims; upstream has
  added and removed keywords before (`precise_float` is gone).
- **`ujson.JSONDecodeError`'s base class**, and whether the error object grew `.pos`. If it ever
  becomes a `json.JSONDecodeError` subclass, the loudest bullet on this page becomes wrong in
  the consumer's favour and should be deleted rather than left standing.
- **The 1,024 nesting caps** in both directions. Compiled in, so a release can move them with no
  signal at all.
- **`Decimal` still being accepted** rather than raising, and still going through a double.
- **`DT_NEEDED` on the Android slices**, per the removal test above — the recipe's only moving
  part.
- **That a bare `ujson` still resolves from this index.** Re-run one `pip download` per target
  and read the filename that comes back, rather than comparing version numbers.
- **The speed table**, which is the reason a reader would install this rather than use the
  stdlib. The example is the cheapest way to re-measure: build it, change nothing, and read
  the table off the screen.
- **The sizes**, re-measured from the wheels rather than scaled. Quote them decimal — `du` is
  binary, so a 133 KB payload re-measured with `du -h` reads as 130 K and looks like a
  regression.

### Coverage gaps

`tests/test_ujson.py` is two functions — a `str`-returning round trip and a float round trip —
and neither carries the docstring this repo's test convention asks for. More usefully, neither
covers anything this page warns app authors about. In rough order of value, the additions worth
making are the `\/` escaping default (the claim a consumer meets first), the `JSONDecodeError`
base class (the one that breaks working code silently), `loads()` refusing keywords, and
`Decimal` rounding to a double.

The 2026-08-20 run of the [example](examples/shape-bench) covered an arm64-v8a Android 14
emulator and an iPhone 16 simulator, both CPython 3.14.6 — **not physical hardware**, and not
3.12 or 3.13. What it does establish is that `import ujson` succeeds on both platforms, the
per-shape ratios under [Speed](#speed), and the eight answers the example's audit table computes
on the spot: what `dumps` returns, `/` escaping, `NaN`, a 23-digit integer, a tuple dict key, a
25-digit `Decimal`, a `loads` keyword, and what an existing `except json.JSONDecodeError` clause
does with ujson's error.

Everything else came off the wheels, off a built APK of the example, or off a desktop install of
the same version — the threading measurements, the import timings, the 5,000-document corpus,
the nesting caps, the `bytes` handling and the file-handle asymmetry. The bridge that licenses
the desktop kind is narrow but real: `ujson-stubs/__init__.pyi`,
`src/ujson/python/version.h` and `LICENSE.txt` are byte-identical between the Android wheel, the iOS wheel and the PyPI desktop
wheel of the same version, and every diagnostic string quoted above — `Trailing data`, `Expected
object or value`, `reject_bytes is on`, `Maximum recursion level reached`, `Reached object
decoding depth limit` — is present verbatim in the Android arm64, Android armeabi-v7a **and**
iOS device binaries.
