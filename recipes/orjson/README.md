# orjson

[`orjson`](https://github.com/ijl/orjson) is a JSON serialiser written in Rust. It is faster
than the standard library's, but that is rarely the reason to put it on a phone: for the
payload sizes a screen actually handles, the saving is *microseconds*. The two things that do
earn their place on mobile are:

- **Compact, always-UTF-8 output.** orjson emits no spaces and never escapes non-ASCII, so
  the bytes it produces are about **12% smaller** than `json.dumps` defaults on the same
  document. That is a real number on a metered connection, and it is free.
- **Types the stdlib refuses.** [`datetime`](https://github.com/ijl/orjson#datetime), `date`,
  `time`, [`UUID`](https://github.com/ijl/orjson#uuid),
  [dataclass instances](https://github.com/ijl/orjson#dataclass), `IntEnum` and — with one
  flag — [numpy arrays](https://github.com/ijl/orjson#numpy) all serialise natively, so the
  hand-written [`default=`](https://github.com/ijl/orjson#default) layer that every stdlib
  JSON app grows can go away.

It is *nearly* a drop-in, and the ways it is not are mostly silent. Two of them corrupt data
rather than raise: [`dumps`](https://github.com/ijl/orjson#serialize) returns `bytes` where
`json.dumps` returns `str`, and [`loads`](https://github.com/ijl/orjson#deserialize) **quietly
turns an integer outside the 64-bit range into a float**. Read
[Things to know](#things-to-know) before swapping an import in an app that already works.

## Install

Add orjson to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "orjson",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`json-swap`](examples/json-swap) — times orjson against the stdlib `json` on the device
  and walks eight cases where the swap is not transparent.

## Usage in a Flet app

```python
import orjson

encoded = orjson.dumps(report, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
report = orjson.loads(encoded)
preview = ft.Text(encoded.decode())
```

Two things in those three lines are not the standard library. `dumps` returns `bytes`, so
anything bound for a Flet control, a text file or a `str`-typed API needs `.decode()` — the
change most likely to break code that already works. And formatting is a bitwise integer
built from the
[`OPT_*` names](https://github.com/ijl/orjson#option) with `|`, not keyword arguments:
`indent=`, `sort_keys=`, `ensure_ascii=` and `separators=` do not exist and raise `TypeError`
if you pass them.

### Storage

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
sprinkled in until it stops complaining. Reading is the forgiving direction — `orjson.loads`
takes `bytes`, `bytearray`, `memoryview` and `str` alike, with no consistent speed difference
between them, so there is no reason to convert either way.

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. There is no atomic-write or temp-sibling machinery in
the library — one `write()` of one `bytes` object is the whole operation — so if a truncated
file on a killed app would hurt, write beside the target and `os.replace` it yourself.

### Threading

**orjson holds the GIL for the whole call, so threads buy no parallelism.** Measured on
desktop against a control that *does* release it: four threads each doing 30 `loads` of a
293 KB blob took four times or more the wall time of one thread doing the same 30 — a
parallel speedup of **0.66–0.97×** over three runs — where the same harness gave
`hashlib.sha256` **2.97–3.12×**. Nothing in the wheel starts a thread of its own either, so
serialisation scales with clock speed, never with core count, and there is no pool to size.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
does buy you is an event handler that returns immediately. That is worth having for a large
document and worth nothing for a small one, so measure before adding the thread — the
[`json-swap`](examples/json-swap) example prints the per-call cost on your device.

There is no shared handle to serialise — `dumps` and `loads` are functions with no state you
hold — but the Flet-side rules still apply. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads, and its body must be wrapped in `try/except`, because
`run_thread` discards whatever it raises — a serialisation error in a worker looks like a
screen that stopped updating, not like an error. If one document is big enough to stutter
even at orjson speed, there is no chunking API for a single document: split it into several
and serialise them in turn, so the worker has somewhere to yield.

### App size

Roughly 0.31–0.35 MB compressed per architecture and 0.77–0.88 MB unpacked, of which the
extension alone is 87–89% — iOS carries about 13% more native code than Android arm64 for the
same version. Almost all of the remainder is `dist-info` metadata, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing; it does drop `__init__.pyi` and `py.typed`, which is harmless here because
nothing reads either at runtime. The Android levers of an app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
worth reaching for because of what else is in the app, not because of this.

### Other considerations

A desktop `flet run` uses PyPI's wheel, which is the same Rust code at the same version. Every
absolute number on this page was measured on desktop; the ratios are the transferable part, so
re-measure on a device before designing around one.

Nothing in the package reads its own source or a data file, so Flet's default
compile-to-`.pyc` and Android's zipped site-packages are both safe. What is *not* safe is
reading the native module's location: Flet relocates every tagged extension out of
site-packages, so **`orjson.orjson.__file__` is not a path inside your app** on either
platform, and whether the attribute exists at all varies by package as well as by platform —
[`pydantic-core`](../pydantic-core) reports none on Android where [`pyyaml`](../pyyaml)
reports a bare `jniLibs` filename, and on iOS that same package reports `_pydantic_core.fwork`,
the pointer file serious_python leaves behind when it turns a `.so` into a framework. Code
that locates anything relative to a native module's `__file__` breaks here. The
[`json-swap`](examples/json-swap) example prints whatever this device resolved, through
`__spec__.origin` when `__file__` is missing, so you can read the answer instead of predicting
it.

## Things to know

- **`dumps` returns `bytes`. This is the change that breaks working code.** Every call site
  that wrote the result to a text file, put it in a Flet control, or handed it to an API
  expecting `str` needs `.decode()` — and some of those only fail on device, in a handler,
  where an unhandled exception makes Flet crash the session. Decoding costs 13–16% of the
  `dumps` time, so it does not erase the win. The shipped `orjson/__init__.pyi` declares
  `-> bytes`, so a type checker will tell you before a device does.

- **`loads` silently downgrades an integer outside the 64-bit range to a float.** No
  exception, no warning; the value is simply wrong from then on.
  `orjson.loads("12345678901234567890123")` is `1.2345678901234568e+22` where `json.loads`
  returns the exact integer. Measured boundaries: `2**63` and `2**64 - 1` come back as exact
  `int`, while `2**64`, `2**100` and `-2**63 - 1` all come back as `float`. There is **no**
  `parse_int` hook to fix it with — `orjson.loads()` takes no keyword arguments at all. So if
  a payload can carry bare integers past 64 bits (128-bit identifiers, token amounts,
  arbitrary-precision counters), either have the producer emit them as strings or keep the
  stdlib for that endpoint. The write direction at least fails loudly: `orjson.dumps(2**64)`
  and `orjson.dumps(-2**63 - 1)` both raise `TypeError: Integer exceeds 64-bit range`, and
  [`OPT_STRICT_INTEGER`](https://github.com/ijl/orjson#opt_strict_integer) tightens that to 53
  bits (`Integer exceeds 53-bit range`) for JavaScript-safe output. Note that the two ranges
  are the *same* — `dumps` accepts exactly `[-2**63, 2**64 - 1]`, which is exactly what
  `loads` returns as an `int` — so anything orjson wrote, orjson reads back exactly. The
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
  (`orjson.dumps([MyStr("a")])` is `b'["a"]'`).
  [`OPT_NON_STR_KEYS`](https://github.com/ijl/orjson#opt_non_str_keys) restores the stdlib
  behaviour and then some: `int`, `float`, `bool`, `None`, `str` subclasses, `datetime`,
  `date` and `UUID` keys all coerce (`b'{"1":"a"}'`, `b'{"true":"a"}'`, `b'{"null":"a"}'`,
  `b'{"1.5":"a"}'`). It still refuses a tuple key (`Dict key must a type serializable with
  OPT_NON_STR_KEYS`) and an integer key outside 64 bits (`Dict integer key must be within
  64-bit range`). The cleanest fix is to `str()` your keys at the boundary.

- **The stdlib keyword API does not exist.** `dumps()` takes only `default` and `option`,
  `loads()` takes no keywords at all, and there is no `dump()`, `load()`, `JSONEncoder` or
  `JSONDecoder`. Of the two `OPT_*` names that replace formatting keywords,
  [`OPT_INDENT_2`](https://github.com/ijl/orjson#opt_indent_2) is the *only* indent there is —
  no arbitrary width — and [`OPT_SORT_KEYS`](https://github.com/ijl/orjson#opt_sort_keys)
  sorts recursively and by code point, identically to the stdlib's `sort_keys`.
  `parse_float`, `parse_int`, `object_hook` and `object_pairs_hook` have no equivalent at all,
  so code that used them cannot be swapped: money and precision code built on
  `json.loads(text, parse_float=Decimal)` should stay on the stdlib for that one call, and
  everything else can be post-processed after parsing.

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
  **254 containers deep, dicts and lists alike** — 254 nested dicts or 254 nested lists around
  a scalar serialise, 255 of either raise `TypeError: Recursion limit reached`, a compiled-in
  cap that `sys.setrecursionlimit` does not move. Meanwhile `loads` happily parses 1024 levels
  of array nesting (1025 raises `JSONDecodeError`), and `json.dumps` handles 1500-deep dicts.
  Flatten deeply recursive structures, or keep the stdlib for that one call site.

- **An unknown bit in `option` is sometimes ignored rather than rejected.**
  `option=1 << 30` is accepted and silently does nothing, and `option=None` is accepted too;
  but `option=4096`, `option=1 << 16`, `option=(1 << 30) | 1` and `option=True` all raise
  `TypeError: Invalid opts`. It is not a clean "reject anything unknown", so a mistyped flag
  constant can quietly have no effect. Only ever build the argument from the `OPT_*` names
  with `|`.

- **[`orjson.Fragment`](https://github.com/ijl/orjson#fragment) does not validate what it
  splices.** It drops already-serialised JSON into an output document without re-parsing it —
  `orjson.dumps({"raw": orjson.Fragment(b'{"a":1}')})` is `b'{"raw":{"a":1}}'` — and
  `orjson.Fragment(b"not json")` emits `b'{"raw":not json}'` with no complaint, producing a
  document that is not JSON. Only pass content orjson itself produced, or validate it once
  with `orjson.loads` before caching it. The shipped `.pyi` also declares
  `class Fragment(tuple)` where the real class inherits straight from `object`, so a type
  checker will allow tuple operations that fail at runtime; treat it as an opaque wrapper.

- **What you actually gain, measured.** On a nested API-shaped document (accented strings,
  floats, bools, nulls, a nested object, a list), desktop CPython 3.12 on an arm64 Mac, best
  of many runs at nine sizes from 260 B to 906 KB: `dumps` **6.0–6.8×** faster, `loads`
  **2.1–3.0×** faster with the ratio drifting down as the document grows, and output
  **12% smaller** than `json.dumps` defaults. The output is byte-for-byte identical to
  `json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()` at every one of those
  sizes, and 0 of 20,000 random floats serialised differently between the two libraries — so
  the size win is spacing and `\uXXXX` escaping, not a different encoding. **In absolute
  terms it is microseconds.** At one record (260 B) `dumps` saves 1.3 µs and `loads` 0.9 µs;
  at fifty (9 KB), 47 µs and 25 µs. Against a 16.7 ms frame, none of that is visible. Reach
  for orjson for the compact output and the type coverage, and only for the speed once you
  have measured a payload big enough for it to matter — the
  [`json-swap`](examples/json-swap) example is built to do exactly that on your device.

- **The types the stdlib refuses, and the ones orjson refuses too.** `datetime`, `date`,
  `time`, `UUID`, a dataclass instance and an `IntEnum` member all serialise, and a `zoneinfo`
  tzinfo is respected (`b'"2026-08-17T00:00:00+02:00"'`). `OPT_UTC_Z` writes `Z` instead of
  `+00:00`, `OPT_NAIVE_UTC` stamps a naive value as UTC, `OPT_OMIT_MICROSECONDS` drops the
  fraction, and `OPT_PASSTHROUGH_DATETIME` routes datetimes to your `default` so you can
  choose the format. `json.dumps` raises `TypeError: Object of type
  datetime|date|time|UUID|<dataclass> is not JSON serializable` for the first five. Still
  refused by orjson: `set`, `bytes` and `complex` (`Type is not JSON serializable: set`) —
  those need `default=`. And subclasses of `str`, `int`, `dict` and `list` serialise as their
  base type unless you pass
  [`OPT_PASSTHROUGH_SUBCLASS`](https://github.com/ijl/orjson#opt_passthrough_subclass), which
  routes them to `default` instead and raises if there is none.

- **numpy works, and orjson does not depend on it.** With
  [`OPT_SERIALIZE_NUMPY`](https://github.com/ijl/orjson#opt_serialize_numpy), arrays of
  `int8`–`int64`, `uint8`–`uint64`, `float16`/`32`/`64`, `bool` and `datetime64` serialise
  natively, as do numpy scalars, with `nan` becoming `null` and an empty array `[]`; refused
  are a non-C-contiguous slice (`numpy array is not C contiguous; use ndarray.tolist() in
  default`), big-endian dtypes (`not native-endianness`), and complex, string and 0-d arrays
  (`unsupported datatype in numpy array`). The flag is safe without numpy installed: `orjson`
  never imports it — `numpy` is absent from `sys.modules` after `import orjson` and after an
  `OPT_SERIALIZE_NUMPY` call on a plain list.

- **`import orjson` is three times the cost of `import json` standalone, and almost free
  inside a Flet app.** It pulls 39 modules, including the stdlib `json` (which
  `JSONDecodeError` subclasses), plus `dataclasses`, `inspect`, `ast`, `dis`, `tokenize`,
  `uuid` and `datetime` — 7.8 ms against `import json`'s 2.6 ms on desktop, `dataclasses`
  alone accounting for 6.1 ms of it. But `import flet` has already loaded all of those except
  `datetime` and `uuid`, so the marginal cost in a real app measured **0.75 ms**. Desktop
  figures; a phone will be slower on both sides of the comparison.

## Build notes (maintainers)

### Recipe shape

A `meta.yaml` naming the version and one environment variable, no patches, no `build.sh`, no
`requirements` — the same shape as [`pydantic-core`](../pydantic-core) and [`jiter`](../jiter).
That is the fact worth recording: a Rust extension with no C dependencies cross-compiles to
every slice of all three Python minors on forge's stock support alone, so the day this recipe
needs a patch, suspect the toolchain or an upstream restructuring before reaching for one.

The build covers all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and iOS
device plus both simulator slices, on Python 3.12, 3.13 and 3.14, with one legacy 32-bit
`android_24_x86` slice on 3.12. Nothing below 3.12 goes on the index, which matches what
Flet's mobile runtimes support; `Requires-Python` in the wheel is upstream's `>=3.10`, so the
floor a consumer actually hits is Flet's.

What the wheels look like, since the consumer sections rest on it:

- **Eleven files** — `orjson/__init__.py` (a one-line `from .orjson import *`),
  `orjson/__init__.pyi`, an empty `orjson/py.typed`, the extension, and a `dist-info` that is
  nearly 100 KB of the unpacked size. `METADATA` and the three licence files are
  byte-identical on every slice; the CycloneDX SBOM names the same 23 Rust crates everywhere
  but differs per slice in serial number, timestamp and build path.
- **Nothing transitive** — no `Requires-Dist` and no `Provides-Extra` in `METADATA`. No
  `extract_packages` entry either: no data file, and no occurrence of `__file__`,
  `importlib.resources`, `pkgutil`, `pkg_resources` or `getsource` anywhere in the package.
- **An ordinary submodule** — the extension is `orjson.orjson`, not the package `__init__`, so
  this wheel does not touch the class of Android failures [`apsw`](../apsw) documents.
- **Android** — `DT_NEEDED` is `libpython3.<minor>.so`, `libdl.so`, `libc.so` on every slice;
  no `libc++_shared`, so no `flet-libcpp-shared` follows it in. Every undefined symbol outside
  CPython's API is bionic libc or libdl. All `PT_LOAD` segments carry 16 KB alignment, and
  armeabi-v7a and the legacy `x86` slice are genuine `ELF32` builds rather than stubs.
- **iOS** — every slice is already `MH_DYLIB` marked `NOUNDEFS`, so forge's `MH_BUNDLE`
  conversion never applies. `otool -L` names only `@rpath/Python.framework/Python`,
  `/usr/lib/libiconv.2.dylib` and `/usr/lib/libSystem.B.dylib`; the libiconv line is not
  orjson's (`nm -u` finds no `iconv` symbol on any slice) but comes from Rust's own Apple
  linkage, and the same three lines appear verbatim in `pydantic-core`'s and `jiter`'s iOS
  device wheels on this index.
- **No threading machinery** — `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState_*` and
  `pthread_create` are absent from every slice. That is the evidence behind
  [Threading](#threading): no GIL-release path to reach, and nothing that starts a thread.

### Upgrade hazards

- Almost everything the sections above tell an app author is Rust behaviour, not structure:
  the numeric boundaries, the nesting caps, the option validation, `Fragment`, the exact
  wording of every diagnostic. All of it can change in a point release without the build so
  much as blinking, so a green CI run is not evidence that those claims survived.
- **The extension filename spelling differs per Python.** The 3.12 wheels ship a bare
  `orjson/orjson.cpython-312.so` where 3.13 and 3.14 ship the full platform triple
  (`orjson.cpython-314-aarch64-linux-android.so`). Both carry the `cpython-<minor>` ABI tag,
  which is what Android's packaging keys on; an *untagged* `.so` would be a silent
  `ModuleNotFoundError` on device.
- **The build on the index was not produced in one pass.** Every 3.12 slice is dated
  2026-06-04 and the 3.13 and 3.14 slices 2026-06-11, except *both* armeabi-v7a slices — 3.13
  and 3.14 alike — dated 2026-06-29, which are also the only two of the nineteen built with
  maturin 1.14.1 where the rest say 1.13.3 (`dist-info/WHEEL` `Generator` lines). Rebuild the
  set together rather than assuming uniformity.
- **The day upstream ships a mobile-tagged or `py3-none-any` wheel, this recipe may stop being
  needed.** It is needed today only because PyPI has nothing pip can select for an Android or
  iOS target.
- **The size gap against the desktop wheel is unexplained.** The mobile `__text` is about 2.9×
  the PyPI macOS wheel's for the same version, and the mobile builds carry unwind machinery
  the desktop one does not — `__eh_frame` and `__gcc_except_tab` on iOS, `.eh_frame` on
  Android arm64, against a desktop wheel with a 144-byte `__unwind_info` stub and not one
  `_Unwind_*` import. That narrows it to build configuration rather than code, but which
  upstream flag accounts for it was **not** established. Worth settling if wheel size ever
  becomes the complaint.
- The iOS `LC_ID_DYLIB` still carries the CI build path and the extension has no `LC_RPATH` of
  its own. Whether either matters under serious_python's framework relocation has not been
  established.

### Re-verification checklist

- **The numeric boundaries.** That `2**63` and `2**64 - 1` still round-trip as exact `int` and
  that `2**64` and `-2**63 - 1` still come back as `float`; that `dumps(2**64)` still raises,
  and that `OPT_STRICT_INTEGER` still moves the line to 53 bits. These are the claims that
  corrupt data if they move.
- **The nesting caps** — 254 containers on `dumps` (dicts and lists alike), 1024 array levels
  on `loads`. Compiled in, so a release can change them without any signal.
- **The byte-equality with `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)`**, at
  several sizes and over a few thousand random floats. The whole "12% smaller" claim and the
  example's cross-check hang off it, and a float-formatting change upstream (`zmij` and
  `itoa`/`itoap` are in the SBOM) would break it without breaking anything else.
- **`Requires-Dist` still empty and the file count still eleven.** A new dependency or a new
  data file would put both the [Install](#install) snippet and the no-`extract_packages`
  claim back in question.
- **The linkage lists and the filetype**, exactly as listed under Recipe shape. Anything new in
  either list is a runtime dependency [Install](#install) does not mention, and an iOS slice
  that came back `MH_BUNDLE` would need forge's conversion.
- **That a bare `orjson` still resolves from this index.** Re-run one
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev
  orjson` per target and read the filename that comes back, rather than comparing version
  numbers. The last pass covered fifteen of the eighteen slice/Python combinations — the iOS
  arm64 simulator was not among them.
- **The measurements**, all of them: the speed ratios, the 12%, the 13–16% decode overhead,
  the import timings, the GIL speedups with their `hashlib` control, and the sizes. Re-measure
  rather than scaling; every absolute number above is a desktop number a phone will not
  reproduce.

### Coverage gaps

**No on-device run backs anything above Build notes.** Every claim came off the wheels or off
a desktop install of the same version, and the bridge that licenses the second kind is narrow
but real: `__init__.py`, `__init__.pyi` and `METADATA` are byte-identical between the Android
wheel, the iOS wheel and the PyPI desktop wheel, and every diagnostic string quoted above —
`Dict key must be str`, `Integer exceeds 64-bit range`, `Recursion limit reached`, `str is not
valid UTF-8: surrogates not allowed`, the three numpy refusals and the rest — is present
verbatim in the Android arm64, Android armeabi-v7a **and** iOS device binaries. What that does
not establish is that `import orjson` succeeds on a phone at all. The
[`json-swap`](examples/json-swap) example is the missing evidence, and its header line is
built to be the thing you read off the screen.

`tests/test_orjson.py` asserts the `bytes` return type and a float round trip, and nothing
else. It covers none of what this page warns app authors about; three additions are worth more
than any of the timings — the past-64-bit `loads` downgrade (the most consumer-visible claim
here and the least protected), one `OPT_*` behaviour, and one native type (`datetime` or
`UUID`), so a build that lost the datetime path could not go green.
