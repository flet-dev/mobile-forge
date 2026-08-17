# orjson

[`orjson`](https://github.com/ijl/orjson) is a JSON serialiser written in Rust. It is
faster than the standard library's — about **6× on the way out and 2–3× on the way back
in** — but that is rarely the reason to put it on a phone, because for the payload sizes a
screen actually handles the saving is *microseconds*. The two things that do earn their
place on mobile are:

- **Compact, always-UTF-8 output.** orjson emits no spaces and never escapes non-ASCII, so
  the bytes it produces are about **12% smaller** than `json.dumps` defaults on the same
  document. That is a real number on a metered connection, and it is free.
- **Types the stdlib refuses.** `datetime`, `date`, `time`, `UUID`, dataclass instances,
  `IntEnum` and — with one flag — numpy arrays all serialise natively, so the hand-written
  `default=` layer that every stdlib JSON app grows can go away.

It is *nearly* a drop-in, and the ways it is not are mostly silent. Two of them will
corrupt data rather than raise: `dumps` returns `bytes` where `json.dumps` returns `str`,
and `loads` **quietly turns an integer outside the 64-bit range into a float**. Read
[Things to know](#things-to-know) before swapping an import in an app that already works.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "orjson",
]
```

Nothing else to configure, and nothing else comes along: the wheel's `METADATA` carries no
`Requires-Dist` line at all and no `Provides-Extra`, so no `flet-lib*` wheel and no
transitive dependency follows it in.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either. The whole payload is four files — `orjson/__init__.py` (693 bytes of
`from .orjson import *`), `orjson/__init__.pyi`, an empty `orjson/py.typed`, and the
extension — with no data file to read and no occurrence of `__file__`,
`importlib.resources`, `pkgutil`, `pkg_resources` or `getsource` anywhere in it. The
extension carries a CPython ABI tag on every slice, so it runs as-is out of Android's zipped
site-packages.

**A bare `orjson` really does resolve from this index, on every slice.** That is worth saying
because it is not true of every recipe here: upstream publishes no mobile-tagged wheel and no
`py3-none-any` wheel, so PyPI has nothing pip can select for an Android or iOS target no
matter how far ahead its version is. Measured with PyPI at 3.12.0 and this index at 3.11.9,
resolving the way `flet build` does (`pip --only-binary :all: --platform … --extra-index-url
https://pypi.flet.dev`): Android arm64-v8a, armeabi-v7a and x86_64 and iOS device and the
x86_64 simulator, on 3.12, 3.13 and 3.14, all came back with this index's wheel.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
device plus both simulator slices, on Python 3.12, 3.13 and 3.14 — nineteen wheels at the
same build number, those eighteen combinations plus a legacy 32-bit `android_24_x86` slice on
3.12. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. There is nothing below 3.12 on the index, which matches what Flet's
mobile runtimes support; `Requires-Python` in the wheel is the upstream `>=3.10`, so the
floor you will actually hit is Flet's.

## Storage

orjson has **no file API**: there is no `dump()` and no `load()`, only `dumps()` and
`loads()`, so the file handling stays yours. A JSON file the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups — and the
one thing that changes versus the stdlib is the mode, because `dumps` hands you bytes:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.json")
with open(path, "wb") as handle:
    handle.write(orjson.dumps(settings))
with open(path, "rb") as handle:
    settings = orjson.loads(handle.read())
```

`open(path, "w")` plus `orjson.dumps(...)` raises `TypeError: write() argument must be str,
not bytes`, which is the loud version of this mistake; the quiet version is `.decode()`
sprinkled in until it stops complaining. Reading is the forgiving direction —
`orjson.loads` takes `bytes`, `bytearray`, `memoryview` and `str` alike, with no consistent
speed difference between bytes and str — a few per cent at 9 KB, 90 KB and 360 KB, and in
both directions across runs — so there is no reason to convert either way.

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. There is no atomic-write or temp-sibling machinery in
the library — one `write()` of one `bytes` object is the whole operation, so if a truncated
file on a killed app would hurt, write beside the target and `os.replace` it yourself.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`json-swap`](examples/json-swap) — times orjson against the stdlib `json` on the device
  and walks eight cases where the swap is not transparent.

## Threading

**orjson holds the GIL for the whole call, so threads buy no parallelism.** Measured on
desktop against a control that *does* release it: four threads each doing 30 `loads` of a
293 KB blob took four times or more the wall time of one thread doing the same 30 — a
parallel speedup of **0.66–0.97×** over three runs — where the same harness gave
`hashlib.sha256` **2.97–3.12×**. The symbols agree: `PyEval_SaveThread`,
`PyEval_RestoreThread` and `PyGILState_*` are absent from the undefined symbols of all nineteen
slices, so there is no GIL-release path in the extension to reach.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
does buy you is an event handler that returns immediately. That is worth having for a large
document and worth nothing for a small one, so measure before adding the thread — the
[`json-swap`](examples/json-swap) example prints the per-call cost on your device.

`pthread_create` is absent from every slice too, so nothing in the wheel starts a thread of
its own: serialisation scales with clock speed, never with core count, and there is no pool
to size. There is no shared handle to serialise either: `dumps` and `loads` are functions
with no state you hold, and because the GIL is held for the whole of a call there is nothing
for two threads to interleave inside one.

The Flet-side rules still apply. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and its body must be wrapped in `try/except`, because
`run_thread` discards whatever it raises — a serialisation error in a worker looks like a
screen that stopped updating, not like an error. If one document is big enough to stutter
even at orjson speed, there is no chunking API for a single document: split it into several
documents and serialise them in turn so the worker has somewhere to yield.

## Android notes

The extension links nothing beyond the interpreter and libc. `DT_NEEDED` is
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices — no `libc++_shared`,
so none of the usual Android C++ staging applies and orjson brings no `flet-libcpp-shared`
with it. Of the 110 undefined symbols on the 3.14 arm64-v8a slice (108 on 3.12 and 3.13), every
one outside CPython's own API is bionic libc (`malloc`, `memcpy`, `mmap`, `getauxval`,
`__system_property_get`, `dl_iterate_phdr`, the pthread TLS and rwlock family) or libdl
(`dlsym`). All `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires. arm64-v8a and
x86_64 are `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
`ELF32`/`i386` builds rather than stubs.

**The extension's filename is not the same on every Python**, which matters if you go
looking for it in an app payload: 3.13 and 3.14 ship
`orjson/orjson.cpython-3<minor>-aarch64-linux-android.so` (and
`…-arm-linux-androideabi.so`, `…-x86_64-linux-android.so`), while the 3.12 wheels from the
same build ship a bare `orjson/orjson.cpython-312.so` with no platform triple. Both spellings
carry the `cpython-<minor>` ABI tag, which is what Android's packaging keys on.

**The native module is `orjson.orjson`, a submodule — not the package `__init__`.** That is
the ordinary shape, so this wheel does not touch the class of Android failures that
[`apsw`](../apsw) exists to document, where a package whose `__init__` *is* the extension
needs special handling.

Flet relocates every tagged extension out of site-packages, so **`orjson.orjson.__file__` is
not a path inside your app** — and whether the attribute exists at all varies by package as
well as by platform: [`pydantic-core`](../pydantic-core) reports none on Android where
[`pyyaml`](../pyyaml) reports a bare `jniLibs` filename. Code that locates anything relative
to a native module's `__file__` breaks here. The
[`json-swap`](examples/json-swap) example prints whatever this device resolved, through
`__spec__.origin` when `__file__` is missing, so you can read the answer instead of
predicting it.

## iOS notes

**The extension needs no fixing up.** All nine iOS slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging needs — so the
`MH_BUNDLE` link failure that has bitten other recipes on this index does not apply, and
there is no third-party dylib to ship beside it.

Besides its own install name, `otool -L` names three libraries: `@rpath/Python.framework/Python`,
`/usr/lib/libiconv.2.dylib` and `/usr/lib/libSystem.B.dylib`. The middle one is **not
orjson's** — `nm -u` finds no `iconv` symbol among the undefined names of any iOS slice, 115 to
117 of them per slice and 117 on all three device slices, so the load command comes from Rust's
own Apple linkage rather than from any code in the package. Both
`/usr/lib` entries are OS libraries rather than anything the wheel carries, and the same
three lines appear verbatim in [`pydantic-core`](../pydantic-core)'s and
[`jiter`](../jiter)'s iOS device wheels on this index — pydantic-core being one of the three
packages this repo's CI builds and runs **on a device** on every non-recipe change, which is
the closest thing to evidence that the reference resolves there. It has not been observed
from an orjson import on a device; see [Build notes](#build-notes-maintainers).

Everything outside CPython's API in that undefined list is libc, libSystem, the Itanium
unwinder (`_Unwind_*`), `dyld` image introspection and four `dispatch_*` entry points —
nothing in that list comes from outside the OS or CPython, so there is nothing to preload.

**iOS carries about 13% more native code than Android arm64** for the same version —
776,488 bytes against 688,696 — and that 87,792-byte gap is the whole 87,785-byte difference
in unpacked size between the two platforms plus the seven bytes iOS's `dist-info` is smaller
by. As on Android, the relocation means `orjson.orjson.__file__` is not the path in the
wheel: serious_python turns each
site-packages `.so` into a framework and leaves a `<name>.fwork` pointer file behind, which
is why [`pydantic-core`](../pydantic-core) reports `_pydantic_core.fwork` on an iOS device.

## Things to know

- **`dumps` returns `bytes`. This is the change that breaks working code.** Every call site
  that wrote the result to a text file, put it in a Flet control, or handed it to an API
  expecting `str` needs `.decode()` — and some of those only fail on device, in a handler,
  where an unhandled exception makes Flet crash the session rather than log something.
  Decoding costs 13–16% of the `dumps` time (measured at 9 KB, 90 KB and 360 KB), so it does
  not erase the win: on a 2,000-record, 369,060-byte document, `orjson.dumps` 0.386 ms,
  `orjson.dumps().decode()` 0.439 ms, `json.dumps` 2.278 ms. The shipped
  `orjson/__init__.pyi` declares `-> bytes`, so a type checker will tell you before a device
  does.
- **`loads` silently downgrades an integer outside the 64-bit range to a float.** No
  exception, no warning; the value is simply wrong from then on.
  `orjson.loads("12345678901234567890123")` is `1.2345678901234568e+22` where `json.loads`
  returns the exact integer. Measured boundaries: `2**63` and `2**64 - 1` come back as exact
  `int`, while `2**64`, `2**100` and `-2**63 - 1` all come back as `float`. There is **no**
  `parse_int` hook to fix it with — `orjson.loads()` takes no keyword arguments at all. So if
  a payload can carry bare integers past 64 bits (128-bit identifiers, token amounts,
  arbitrary-precision counters), either have the producer emit them as strings or keep the
  stdlib for that endpoint. The write direction at least fails loudly:
  `orjson.dumps(2**64)` and `orjson.dumps(-2**63 - 1)` both raise
  `TypeError: Integer exceeds 64-bit range`, and `option=orjson.OPT_STRICT_INTEGER` tightens
  that to 53 bits (`Integer exceeds 53-bit range`) for JavaScript-safe output. Note that the
  two ranges are the *same* — `dumps` accepts exactly `[-2**63, 2**64 - 1]`, which is exactly
  what `loads` returns as an `int` — so anything orjson wrote, orjson reads back exactly. The
  hazard is only ever a document that came from somewhere else.
- **`NaN` and `Infinity` break in both directions, so a stdlib producer and an orjson
  consumer can fail to talk to each other.** `json.dumps({"x": float("nan")})` emits the
  non-standard `{"x": NaN}` while orjson emits `{"x":null}`; `json.dumps([inf, -inf])` emits
  `[Infinity, -Infinity]` against orjson's `[null,null]`. Reading back, `json.loads("NaN")`
  returns `nan` and `orjson.loads("NaN")` raises `JSONDecodeError: unexpected character`
  (`[Infinity]` fails at column 2). Sanitise floats with `math.isfinite` before serialising
  so the `null` is yours and deliberate, and make the producer pass
  `json.dumps(..., allow_nan=False)` — which raises `ValueError` instead of emitting invalid
  JSON — so the mismatch surfaces on the server rather than in the app.
- **A non-string dict key raises where `json.dumps` quietly coerces it.** `{1: "a"}` is
  `'{"1": "a"}'` under the stdlib and `TypeError: Dict key must be str` under orjson — and a
  **`str` subclass** key raises too, even though a `str` subclass *value* serialises fine
  (`orjson.dumps([MyStr("a")])` is `b'["a"]'`). `option=orjson.OPT_NON_STR_KEYS` restores the
  stdlib behaviour and then some: `int`, `float`, `bool`, `None`, `str` subclasses, `datetime`,
  `date` and `UUID` keys all coerce (`b'{"1":"a"}'`, `b'{"true":"a"}'`, `b'{"null":"a"}'`,
  `b'{"1.5":"a"}'`). It still refuses a tuple key (`Dict key must a type serializable with
  OPT_NON_STR_KEYS`) and an integer key outside 64 bits (`Dict integer key must be within
  64-bit range`). The cleanest fix is to `str()` your keys at the boundary.
- **The stdlib keyword API does not exist.** `dumps()` takes only `default` and `option`;
  `loads()` takes no keywords at all; and there is no `dump()`, `load()`, `JSONEncoder` or
  `JSONDecoder`. `sort_keys=True`, `indent=2`, `ensure_ascii=True` and
  `separators=(",", ":")` each raise `TypeError: dumps() got an unexpected keyword argument`,
  and `object_hook=` raises `TypeError: orjson.loads() takes no keyword arguments`.
  Formatting is a bitwise integer built from the `OPT_*` names instead —
  `option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS` gives
  `b'{\n  "a": 2,\n  "b": 1\n}'`. Two things about that: `OPT_INDENT_2` is the *only* indent
  there is, no arbitrary width; and `OPT_SORT_KEYS` sorts recursively and by code point,
  identically to the stdlib's `sort_keys` — `{"é": 1, "z": 2, "A": 3}` gives the same
  `{"A":3,"z":2,"é":1}` from orjson and from
  `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`.
- **`parse_float`, `parse_int`, `object_hook` and `object_pairs_hook` have no orjson
  equivalent at all**, so code that used them cannot be swapped. Money and precision code
  built on `json.loads(text, parse_float=Decimal)` is the common case, and it should stay on
  the stdlib for that one call; everything else can be post-processed after parsing.
- **An exception raised inside your `default` comes back as a `TypeError` with orjson's
  wording, not yours.** A `default` that raises `ValueError("my own message")` surfaces as
  `TypeError: Type is not JSON serializable: set` — your exception is preserved on
  `__cause__` but not in the message, where the stdlib would have propagated it unchanged.
  A `default` that *returns* something unserialisable gives
  `TypeError: default serializer exceeds recursion limit` rather than naming the type.
- **`except orjson.JSONEncodeError:` swallows every unrelated `TypeError` in the block**,
  because `orjson.JSONEncodeError is TypeError` — the same object, not a subclass. Keep the
  `try` down to the single `dumps()` call and do not read the name as specific. The decode
  side is well behaved: `orjson.JSONDecodeError` is a genuine subclass of
  `json.JSONDecodeError`, so existing `except json.JSONDecodeError` handlers keep working and
  `.pos`, `.lineno` and `.msg` are populated.
- **A string containing a lone surrogate raises where `json.dumps` succeeds.**
  `orjson.dumps("\ud800")` is `TypeError: str is not valid UTF-8: surrogates not allowed`
  against the stdlib's `'"\\ud800"'`. That matters on a phone because surrogates are exactly
  what `os.listdir()` and `os.environ` hand you under `surrogateescape`, so a filename or an
  environment value can carry one. Normalise before serialising —
  `s.encode("utf-8", "replace").decode("utf-8")`. The read side is symmetric:
  `orjson.loads(b'"\xff"')` raises `JSONDecodeError` with the same wording.
- **orjson can read documents it cannot write.** `dumps` refuses a structure nested more than
  **254 containers deep, dicts and lists alike** — 254 nested dicts or 254 nested lists around a
  scalar serialise, 255 of either raise `TypeError: Recursion limit reached`, a compiled-in cap
  that `sys.setrecursionlimit` does not move. Meanwhile `loads` happily parses 1024 levels of
  array nesting (1025 raises `JSONDecodeError`), and `json.dumps` handles 1500-deep dicts.
  Flatten deeply recursive structures, or keep the stdlib for that one call site.
- **An unknown bit in `option` is sometimes ignored rather than rejected.**
  `option=1 << 30` is accepted and silently does nothing, and `option=None` is accepted too;
  but `option=4096`, `option=1 << 16`, `option=(1 << 30) | 1` and `option=True` all raise
  `TypeError: Invalid opts`. It is not a clean "reject anything unknown", so a mistyped flag
  constant can quietly have no effect. Only ever build the argument from the `OPT_*` names
  with `|`.
- **`orjson.Fragment` does not validate what it splices.** It exists to drop
  already-serialised JSON into an output document without re-parsing it —
  `orjson.dumps({"raw": orjson.Fragment(b'{"a":1}')})` is `b'{"raw":{"a":1}}'` — and
  `orjson.Fragment(b"not json")` emits `b'{"raw":not json}'` with no complaint, producing a
  document that is not JSON. Only pass content orjson itself produced, or validate it once
  with `orjson.loads` before caching it. Note also that the shipped `.pyi` declares
  `class Fragment(tuple)` while the real class inherits straight from `object`, so a type
  checker will allow tuple operations that fail at runtime; treat it as an opaque wrapper.
- **What you actually gain, measured.** On a nested API-shaped document (accented strings,
  floats, bools, nulls, a nested object, a list), desktop CPython 3.12 on an arm64 Mac, best
  of many runs at nine sizes from 260 B to 906 KB: `dumps` **6.0–6.8×** faster, `loads`
  **2.1–3.0×** faster with the ratio drifting down as the document grows, and output
  **12% smaller** than `json.dumps` defaults. The output is byte-for-byte identical to
  `json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()` at every one of those
  sizes, and 0 of 20,000 random floats serialised differently between the two libraries — so
  the size win is spacing and `\uXXXX` escaping, not a different encoding. **In absolute
  terms it is microseconds.** At 1 record (260 B) `dumps` saves 1.3 µs and `loads` 0.9 µs; at
  50 records (9 KB), 47 µs and 25 µs; a 52-byte settings dict is 76 ns against 704 ns, a
  9× ratio that saves 0.6 µs. Against a 16.7 ms frame, none of that is visible.
  Reach for orjson for the compact output and the type coverage, and only for the speed once
  you have measured a payload big enough for it to matter — the
  [`json-swap`](examples/json-swap) example is built to do exactly that on your device.
- **The types the stdlib refuses, and the ones orjson refuses too.** `datetime` →
  `b'"2026-08-17T12:30:05.123456"'`, `date` → `b'"2026-08-17"'`, `time` →
  `b'"12:30:05.123456"'`, `UUID` → its canonical form, a dataclass instance → its fields, an
  `IntEnum` member → its value, and a `zoneinfo` tzinfo is respected
  (`b'"2026-08-17T00:00:00+02:00"'`). `OPT_UTC_Z` writes `Z` instead of `+00:00`,
  `OPT_NAIVE_UTC` stamps a naive value as UTC, `OPT_OMIT_MICROSECONDS` drops the fraction,
  and `OPT_PASSTHROUGH_DATETIME` routes datetimes to your `default` so you can choose the
  format. `json.dumps` raises `TypeError: Object of type datetime|date|time|UUID|<dataclass>
  is not JSON serializable` for the first five; an `IntEnum` member it handles by itself,
  since it is an `int`. Still refused by orjson: `set`, `bytes` and
  `complex` (`Type is not JSON serializable: set`) — those need `default=`. And subclasses of
  `str`, `int`, `dict` and `list` serialise as their base type unless you pass
  `OPT_PASSTHROUGH_SUBCLASS`, which routes them to `default` instead and raises if there is
  none.
- **numpy works, and orjson does not depend on it.** With
  `option=orjson.OPT_SERIALIZE_NUMPY`, arrays of `int8`–`int64`, `uint8`–`uint64`,
  `float16`/`32`/`64`, `bool` and `datetime64` serialise natively, as do numpy scalars, with
  `nan` becoming `null` and an empty array `[]`; refused are a non-C-contiguous slice
  (`numpy array is not C contiguous; use ndarray.tolist() in default`), big-endian dtypes
  (`not native-endianness`), and complex, string and 0-d arrays (`unsupported datatype in
  numpy array`). Verified against numpy 2.4.6, which is what this index publishes for 3.12,
  3.13 and 3.14 on both platforms. The flag is safe without numpy installed: `orjson` never
  imports it — `numpy` is absent from `sys.modules` after `import orjson` and after a
  `OPT_SERIALIZE_NUMPY` call on a plain list.
- **`import orjson` is three times the cost of `import json` standalone, and almost free
  inside a Flet app.** It pulls 39 modules, including the stdlib `json` (which
  `JSONDecodeError` subclasses), plus `dataclasses`, `inspect`, `ast`, `dis`, `tokenize`,
  `uuid` and `datetime`: 7.8 ms against `import json`'s 2.6 ms on desktop, best of seven
  fresh interpreters, with `dataclasses` alone accounting for 6.1 ms of it. But `import flet`
  has already loaded all of those except `datetime` and `uuid`, so the marginal cost in a
  real app measured **0.75 ms** — 0.31 ms of stdlib and 0.46 ms of loading the extension.
  Desktop figures; a phone will be slower on both sides of the comparison.
- **Size: about 320 KB to download, 770–880 KB unpacked, and 87–89% of it is the extension.**
  Eleven files per wheel, of which the code is one `.so` and a 693-byte `__init__.py`. Per
  slice, on Python 3.14 (3.12 and 3.13 are within 200 bytes on Android arm64):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 321 KB | 771 KB | 673 KB |
  | Android armeabi-v7a | 339 KB | 772 KB | 674 KB |
  | Android x86_64 | 339 KB | 831 KB | 733 KB |
  | iOS arm64 (device) | 314 KB | 856 KB | 758 KB |
  | iOS arm64 (simulator) | 317 KB | 846 KB | 748 KB |
  | iOS x86_64 (simulator) | 345 KB | 879 KB | 781 KB |

  The remaining 97 KB is all metadata: a 41 KB `METADATA` (upstream's README) and 28 KB of
  three licence files, both byte-identical on every slice, plus a 27 KB CycloneDX SBOM that
  names the same 23 Rust crates everywhere but differs per slice in its serial number,
  timestamp and build path — so the `dist-info` total is not one fixed number but 98,947 to
  98,983 bytes. Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes
  `__init__.pyi` and `py.typed` — its glob list carries `**.pyi` and `**.typed` — which is
  harmless here, since nothing in the package reads either at runtime. For scale, the
  extension is roughly 2.9× the `__text` of the same version's PyPI macOS wheel (474,568 B
  against 165,060 B, both on 3.14); the stdlib `json` costs nothing at all.

## Build notes (maintainers)

A `meta.yaml` naming the version and one environment variable, no patches, no `build.sh`, no
`requirements` — the same shape as [`pydantic-core`](../pydantic-core) and [`jiter`](../jiter),
and one of 17 recipes in this repo carrying that one variable. That is the fact worth recording: a
Rust extension with no C dependencies cross-compiles to every slice of all three Python minors on
forge's stock support alone, so the day this recipe needs a patch, suspect the toolchain or an
upstream restructuring before reaching for one.

**No on-device run backs anything above this section.** Every claim came off the wheels or
off a desktop install of the same version, and the bridge that licenses the second kind is
narrow but real: `__init__.py`, `__init__.pyi` and `METADATA` are byte-identical between the
Android wheel, the iOS wheel and the PyPI 3.11.9 desktop wheel, and every diagnostic string
quoted above — `Dict key must be str`, `Integer exceeds 64-bit range`, `Recursion limit
reached`, `str is not valid UTF-8: surrogates not allowed`, the three numpy refusals and the
rest — is present verbatim in the Android arm64, Android armeabi-v7a **and** iOS device
binaries. What that does not establish is that `import orjson` succeeds on a phone at all.
There is no CI run for this recipe in recent history, and the wheels on the index come from a
repo-wide build 10 that was not even produced in one pass: every 3.12 slice is dated
2026-06-04 and the 3.13 and 3.14 slices 2026-06-11, except **both** armeabi-v7a slices — 3.13
and 3.14 alike — which are dated 2026-06-29 and are the only two of the nineteen built with
maturin 1.14.1 where the other seventeen say 1.13.3 (`dist-info/WHEEL` `Generator` lines).
The [`json-swap`](examples/json-swap) example is the missing evidence, and its header line is
built to be the thing you read off the screen.

`tests/test_orjson.py` is two docstringed functions asserting the `bytes` return type and a
float round trip, with no version assertion — it already matches the repo's test
conventions. What it does not cover is anything this page warns app authors about, and three
additions are worth more than any of the timings: the past-64-bit `loads` downgrade (the
single most consumer-visible claim here and the least protected), one `OPT_*` behaviour, and
one native type (`datetime` or `UUID`), so a build that lost the datetime path could not go
green.

On a bump, in rough order of what a green build fails to tell you:

- **The numeric boundaries.** That `2**63` and `2**64 - 1` still round-trip as exact `int`
  and that `2**64` and `-2**63 - 1` still come back as `float`; that `dumps(2**64)` still
  raises, and that `OPT_STRICT_INTEGER` still moves the line to 53 bits. These are the
  claims that corrupt data if they move.
- **The nesting caps** — 254 containers on `dumps` (dicts and lists alike), 1024 array levels
  on `loads`. Compiled in, so a release can change them without any signal.
- **The byte-equality with `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)`**, at
  several sizes and over a few thousand random floats. The whole "12% smaller" bullet and the
  example's cross-check hang off it, and a float-formatting change upstream (`zmij` and
  `itoa`/`itoap` are in the SBOM) would break it without breaking anything else.
- **`Requires-Dist` still empty** and the file count still eleven. A new dependency or a new
  data file would put both the [Install](#install) snippet and the no-`extract_packages`
  claim back in question.
- **The linkage lists and the filetype.** Android `DT_NEEDED` is
  `libpython3.<minor>`/`libdl`/`libc` with 16 KB `PT_LOAD` alignment; iOS is
  `MH_DYLIB`/`NOUNDEFS` with `@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib`
  and `/usr/lib/libSystem.B.dylib`. Anything new in either list is a runtime dependency
  [Install](#install) does not mention, and an iOS slice that came back `MH_BUNDLE` would
  need forge's conversion. Note the iOS `LC_ID_DYLIB` still carries the CI build path
  (`/Users/runner/work/mobile-forge/…/liborjson.dylib`) and the extension has no `LC_RPATH`
  of its own; whether either matters under serious_python's framework relocation has not
  been established.
- **The extension filename spelling per Python.** The 3.12 wheels carry a bare
  `cpython-312` tag where 3.13 and 3.14 carry the full platform triple. Both work today; the
  reason to check is that Android's packaging keys on that tag, so an *untagged* `.so` would
  be a silent `ModuleNotFoundError` on device.
- **Whether a bare `orjson` still resolves from this index.** Today it must, because upstream
  publishes no mobile and no universal wheel — which also means the day it does, this recipe
  may stop being needed. Re-run one
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  orjson` per target and read the filename that comes back, rather than comparing version
  numbers.
- **The measurements**, all of them: the 6× / 2–3× ratios, the 12%, the 13–16% decode
  overhead, the import timings, the GIL speedups with their `hashlib` control, and the size
  table. Re-measure rather than scaling — the ratios are the transferable part, and every
  absolute number above is a desktop number that a phone will not reproduce.
- **The size gap against the desktop wheel is unexplained.** The mobile `__text` is ~2.9× the
  PyPI macOS wheel's for the same version, and the mobile builds carry unwind machinery the
  desktop one does not: `__eh_frame` 21,128 B and `__gcc_except_tab` 3,296 B on iOS,
  `.eh_frame` 57,860 B on Android arm64, against a desktop wheel with no `__eh_frame`, no
  `__gcc_except_tab`, a 144-byte `__unwind_info` stub and not one `_Unwind_*` import. That
  narrows it to build configuration rather than code, but which upstream flag accounts for it
  was **not** established; only the measurements are solid. Worth settling if wheel size ever
  becomes the complaint.
