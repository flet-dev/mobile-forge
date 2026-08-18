# msgspec

[`msgspec`](https://github.com/msgspec/msgspec) serialises **and validates** in one C
extension. You declare the shape of a document as a
[`Struct`](https://msgspec.dev/api.html#msgspec.Struct) and hand that type to
[`decode`](https://msgspec.dev/api.html#msgspec.json.decode); what comes back is either typed
objects or a
[`ValidationError`](https://msgspec.dev/api.html#msgspec.ValidationError) naming the field that
was wrong. Four codecs ship in every wheel — JSON, MessagePack, TOML and YAML — and the first
two are compiled in.

Three things make that worth having on a phone rather than a server:

- **The check is the same pass as the parse.** A parse-only library builds the whole dict tree
  first and then you write the `isinstance` loop; msgspec never builds the tree. Measured on a
  5,000-record, 323,757-byte document (desktop CPython 3.12, arm64 Mac, best of 12×20):
  `json.loads` 1.494 ms, `orjson.loads` 0.659 ms, `msgspec.json.decode(blob, type=list[Order])`
  **0.573 ms**, and `orjson.loads` plus a hand-written type loop 0.968 ms. The fastest of the
  four is also the only one that checks the document without a second pass over it.
- **Bad data stops the decode where it goes bad.** Same document, one wrong field: at record 1
  it fails in **0.001 ms**, at the last record it costs a full pass — 0.573 ms, against 0.579 ms
  for the fully valid document, in the same run. A parse-only library pays the full pass either
  way and then hands you the wrong-typed value with no complaint.
- **It is small.** 187 KB to download and 456 KB unpacked on Android arm64 — **58%** of
  [`orjson`](../orjson)'s wheel and **10%** of [`pydantic-core`](../pydantic-core)'s, while
  doing more than either.

Both platforms are fully published, and nothing else comes along with it. The trade against
pydantic is narrower than it looks — constraints, JSON Schema generation and custom validation
are all here — but msgspec reports **only the first error** and gives you no structured way to
locate it. Read [Things to know](#things-to-know) before you build a form on it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "msgspec",
]
```

Nothing else to configure, and nothing else follows it in. `METADATA` carries three
`Requires-Dist` lines and every one is gated behind `extra == "toml"` or `extra == "yaml"`, so
a bare `msgspec` resolves to exactly one wheel: no `flet-lib*`, no transitive dependency.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either. The whole wheel is 23 entries — sixteen `.py`/`.pyi` files, an empty
`py.typed`, the extension and five `dist-info` files — with no data file anywhere, and no
occurrence of `__file__`, `importlib.resources`, `pkgutil`, `pkg_resources` or `getsource` in
any shipped module. The native module is `msgspec._core`, a **submodule** rather than the
package `__init__`, which is the ordinary shape Android's zipped site-packages handles as-is;
this wheel does not touch the class of failures [`apsw`](../apsw) exists to document.

**A bare `msgspec` really does resolve from this index, on every slice.** Upstream publishes
no mobile-tagged wheel and no `py3-none-any` wheel — 49 files at 0.21.1, none of them Android,
iOS or universal — so PyPI has nothing pip can select for a mobile target. Resolving the way
`flet build` does (`pip download --only-binary :all: --platform … --extra-index-url
https://pypi.flet.dev`) over Android arm64-v8a, armeabi-v7a and x86_64 and iOS device plus both
simulator slices, on 3.12, 3.13 and 3.14, all eighteen came back with this index's wheel.

Nineteen wheels at the same build number: ten Android (arm64-v8a, armeabi-v7a and x86_64 on
each of 3.12, 3.13 and 3.14, plus a legacy 32-bit `android_24_x86` on 3.12) and nine iOS
(device, arm64 simulator and x86_64 simulator on each of the three). No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. `Requires-Python` in the wheel is upstream's `>=3.10`, so the floor you
will actually hit is Flet's.

**The two extras resolve for mobile as well, at different prices.** `msgspec[toml]` adds one
pure-Python `tomli_w-1.2.0-py3-none-any.whl` and nothing more — its `tomli` line is gated on
`python_version < "3.11"`, which no Flet mobile runtime is. `msgspec[yaml]` adds
[`pyyaml`](../pyyaml) *and* the `flet-libyaml` wheel it depends on. Both verified on Android
arm64-v8a and iOS device, on 3.12 and 3.14. You may need neither: see the TOML note in
[Things to know](#things-to-know).

## Storage

msgspec has **no file API** — there is no `dump()` and no `load()`, only
[`encode`](https://msgspec.dev/api.html#msgspec.json.encode) and
[`decode`](https://msgspec.dev/api.html#msgspec.json.decode) — so the file handling stays
yours. `encode` hands you `bytes`, so the mode is binary:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.json")
with open(path, "wb") as handle:
    handle.write(msgspec.json.encode(settings))
with open(path, "rb") as handle:
    settings = msgspec.json.decode(handle.read(), type=Settings)
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the app-private directory that is never auto-deleted and is included in backups. Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. There is no atomic-write machinery in the library — one
`write()` of one `bytes` object is the whole operation — so if a truncated file on a killed app
would hurt, write beside the target and `os.replace` it yourself.

For a file only your app reads,
[`msgspec.msgpack`](https://msgspec.dev/api.html#msgspec.msgpack.decode) is the same API
against a binary encoding and the same validation: on the example's 5,000-record document it is
**251,619 bytes against JSON's 323,757**, 22% smaller, with `type=` behaving identically.
Reach for it for caches and for anything you send over a metered connection; keep JSON where a
human or another language has to read the file.

The `type=` argument is what makes reading a file back safe. A settings file the user edited,
a cache written by an older version of your app and a truncated download are all *plausible*
JSON, and a typed decode is the difference between an `AttributeError` three screens later and
one `ValidationError` at the point of reading.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`three-ways`](examples/three-ways) — decodes one document with `json`, `orjson` and typed
  `msgspec` on the device and shows what each does with a malformed record.

## Threading

**msgspec holds the GIL for the whole call, so threads buy no parallelism.** The symbols say
so: `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState_*` and `pthread_create` are all
absent from the undefined symbols of **all nineteen slices**, so there is no GIL-release path
in the extension to reach and nothing in the wheel starts a thread of its own. Measured on
desktop against a control that does release it: four threads each doing 20 typed decodes of a
323,757-byte document took 47.9 ms against one thread's 12.1 ms — a parallel speedup of
**1.01×** — where the same harness gave `hashlib.sha256` **3.56×**. Decoding scales with clock
speed, never with core count, and there is no pool to size.

There is no shared handle to serialise either. `encode` and `decode` are functions with no
state you hold, a reused
[`Decoder`](https://msgspec.dev/api.html#msgspec.json.Decoder) or `Encoder` is the only object
you would hold at all, and because the GIL is held for the whole of a call there is nothing for
two threads to interleave inside one.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
buy you is an event handler that returns immediately — worth having for a large document and
worth nothing for a small one. The Flet-side rules then apply: a worker must end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads, and its body must be wrapped in `try/except`,
because `run_thread` discards whatever it raises — a `ValidationError` in a worker looks like a
screen that stopped updating, not like an error.

## Android notes

The extension links nothing beyond the interpreter, the maths library and libc. `DT_NEEDED` on
the 3.14 arm64-v8a slice is `libm.so`, `libpython3.14.so`, `libdl.so` and `libc.so` — no
`libc++_shared`, so none of the usual Android C++ staging applies and msgspec brings no
`flet-libcpp-shared` with it. Of its 186 undefined dynamic symbols only ten are outside
CPython's own API, and every one is bionic libc (`__cxa_atexit`, `__cxa_finalize`,
`__register_atfork`, `fmod`, `memcmp`, `memcpy`, `memmove`, `memset`, `nextafter`, `strlen`).
All three `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires. arm64-v8a and
x86_64 are `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and
`ELF32`/`i386` builds rather than stubs — armeabi-v7a is markedly smaller than the rest, 264 KB
of extension against arm64's 362 KB, which makes it the smallest of the nineteen wheels.

**The extension's filename is not the same on every Python**, which matters if you go looking
for it in an app payload: 3.13 and 3.14 ship
`msgspec/_core.cpython-3<minor>-aarch64-linux-android.so` (and `…-arm-linux-androideabi.so`,
`…-x86_64-linux-android.so`), while the 3.12 wheels from the same build ship a bare
`msgspec/_core.cpython-312.so` with no platform triple. Both spellings carry the
`cpython-<minor>` ABI tag, which is what Android's packaging keys on, so match on
`_core.cpython-*` rather than a full filename. Exactly the quirk [`orjson`](../orjson) documents.

Flet relocates every tagged extension out of site-packages, so **`msgspec._core.__file__` is
not a path inside your app** — and whether the attribute exists at all varies by package as
well as by platform: [`pydantic-core`](../pydantic-core) reports none on Android where
[`pyyaml`](../pyyaml) reports a bare `jniLibs` filename. Nothing in msgspec reads it, so this
only bites code of yours that locates something relative to a native module. The
[`three-ways`](examples/three-ways) example prints whatever this device resolved, through
`__spec__.origin` when `__file__` is missing, so you can read the answer instead of predicting it.

## iOS notes

**The extension needs no fixing up.** All nine iOS slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging needs, so the
`MH_BUNDLE` conversion that other recipes on this index depend on never engages here.

Its linkage is shorter than Android's and shorter than either Rust neighbour's. Besides its own
install name, `otool -L` names exactly two libraries: `@rpath/Python.framework/Python` and
`/usr/lib/libSystem.B.dylib`. There is **no** `/usr/lib/libiconv.2.dylib` line, which
[`orjson`](../orjson) and [`pydantic-core`](../pydantic-core) both carry from Rust's Apple
linkage — a C extension does not pick it up. Of 187 undefined symbols, eleven are outside
CPython's API and all eleven are libSystem or the linker (`___stack_chk_fail`,
`___stack_chk_guard`, `_bzero`, `_fmod`, `_memcmp`, `_memcpy`, `_memmove`, `_memset`,
`_nextafter`, `_strlen`, `dyld_stub_binder`). There is nothing to preload and nothing to stage.

**iOS carries about 7% more native code than Android arm64** for the same Python — 395,648
bytes against 370,552 on 3.14 — and that 25,096-byte gap is the whole 25,086-byte difference in
unpacked size between the two platforms plus the ten bytes iOS's `dist-info` is smaller by:
every `.py` file is byte-identical. As on Android, the relocation
means `msgspec._core.__file__` is not the path in the wheel: serious_python turns each
site-packages `.so` into a framework and leaves a `<name>.fwork` pointer file behind. In a built
simulator bundle of the [`three-ways`](examples/three-ways) example that is
`Frameworks/msgspec._core.framework` plus a `site-packages/msgspec/_core.fwork` reading
`Frameworks/msgspec._core.framework/msgspec._core`, which is the shape
[`pydantic-core`](../pydantic-core) reports as `_pydantic_core.fwork` on an iOS device.

## Things to know

- **Unknown fields are ignored by default, and the damage is the field that keeps its default.**
  A server sending `fontSize` where your `Struct` declares `font_size` gives you
  `Settings(theme='dark', font_size=14, notifications=False)` — no error, no warning, and the
  value the user actually set is gone. This is the trap for anyone arriving from pydantic
  expecting validation to mean rejection. Two fixes, and which one you want depends on whether
  the wire format is wrong or merely different: `class Settings(msgspec.Struct,
  forbid_unknown_fields=True)` turns it into ``ValidationError: Object contains unknown field
  `fontSize` ``, and
  [`rename="camel"`](https://msgspec.dev/structs.html) decodes `fontSize` into `font_size`
  correctly and encodes it back. Note it only bites fields that *have* a default — a required
  field missing from the payload does raise ``Object missing required field `qty` ``.
- **Only the first error is reported, and it carries no structured location.** A record with
  three bad fields raises once, naming ``$.a`` and nothing else. The path is embedded in the
  message text — ``Expected `int`, got `str` - at `$.qty` ``, ``… - at `$[1].qty` `` inside a
  list, ``… - at `$.lines[1].qty` `` nested two deep — and there is no `.errors()`, no `loc`
  tuple and no `.path`: `sorted(set(dir(e)) - set(dir(BaseException)))` is just
  `['__module__', '__weakref__']` and `e.args` is a one-element tuple holding the whole
  sentence. So a per-field rejection table like the one
  [`pydantic-core`](../pydantic-core)'s `ValidationError.errors()` gives you cannot be built
  the same way. Decode record-by-record instead — or as `list[msgspec.Raw]` and then per item —
  so the index is yours rather than the message's, and show `str(e)` as the reason. On the
  happy path the same property is a feature: it is exactly why the early abort is 0.001 ms on
  the 5,000-record document above.
- **`except msgspec.MsgspecError` does not catch everything a decode can raise.** Invalid UTF-8
  in the input raises a plain `UnicodeDecodeError`, encoding a lone surrogate raises a plain
  `UnicodeEncodeError`, and exceeding the nesting cap raises a plain `RecursionError` — none of
  which inherit from `MsgspecError`. The reverse mistake is worse: `DecodeError.__bases__` is
  `(MsgspecError, ValueError)`, so a bare `except ValueError` silently swallows the validation
  failures you meant to surface. Catch broad `Exception` around anything parsing input your app
  did not produce, which is also the Flet rule — an unhandled exception in an event handler
  sends `SESSION_CRASHED`. Surrogates matter specifically on a phone because `os.listdir()` and
  `os.environ` hand them to you under `surrogateescape`.
- **No 64-bit integer limit.** msgspec does not have orjson's most dangerous trap:
  `msgspec.json.decode(b"12345678901234567890123")` returns the exact `int` both untyped and
  with `type=int`, and `2**63`, `2**64 - 1`, `2**64`, `2**100` and `-2**63 - 1` all round-trip
  exactly, where `orjson.loads` silently returns `1.2345678901234568e+22` and `orjson.dumps`
  raises `TypeError: Integer exceeds 64-bit range`. A non-`str` dict key is coerced like the
  stdlib does (`{1: "a"}` → `b'{"1":"a"}'`) rather than refused. If you moved to orjson to
  escape the stdlib and hit either of those, msgspec is the way back.
- **Rich types decode and re-encode natively, and `Decimal` is exact.** One `Struct` carrying
  `datetime` (RFC 3339, offset preserved as a `datetime.timezone`), `date`, `time`,
  `uuid.UUID`, `decimal.Decimal`, `Enum` (by value), `IntEnum`, `timedelta` (ISO-8601
  duration), `set` and `bytes` (base64) decodes from one payload and re-encodes — the last two
  being types orjson refuses outright. Bad values give typed messages:
  `Invalid enum value 'green'`, `Invalid UUID`, `Invalid RFC3339 encoded datetime`. Two
  asymmetries to know about. `Decimal` **encodes to a JSON string** (`b'"1.10"'`) while it
  decodes from either a string or a bare number, so msgspec round-trips its own output exactly
  but a JavaScript or Go consumer sees `"1.10"` where it expected `1.10` — agree the wire
  representation explicitly, and prefer changing the other side, because the exactness is the
  whole reason to use `Decimal`. And `timedelta` **does not round-trip byte-stably**:
  `"P1DT2H"` decodes to `timedelta(days=1, seconds=7200)` and re-encodes as `"P1DT7200S"`,
  identical in meaning and different in text, so never diff, hash, sign or cache on encoded
  bytes across a decode/encode cycle.
- **`strict=False` is per call, not per field.** The default refuses string-to-int
  (``Expected `int`, got `str` ``) and float-to-int (``Expected `int`, got `float` ``) but does
  widen int to float, so `"price": 3` into a `float` field gives `3.0`.
  [`strict=False`](https://msgspec.dev/usage.html#strict-vs-lax-mode) enables string coercion
  everywhere in that one call — `"1"` → `1`, `"true"` → `True` — while still rejecting genuine
  garbage (`"abc"` into an `int` still raises). There is no way to relax it for one field only.
- **`__post_init__` runs on the decode path, and launders exceptions inconsistently.** It is
  the [custom-validation hook](https://msgspec.dev/structs.html#post-init-processing) and it
  fires on decoding as well as on construction — but a `ValueError` or `TypeError` raised there
  comes back as a `msgspec.ValidationError` with the message preserved, while a `KeyError`
  propagates untouched as a `KeyError`, and on plain construction (`PI(-1)`, no decoding) the
  same `ValueError` stays a `ValueError`. Raise `ValueError` and catch broad `Exception` at the
  call site rather than keying on the type.
- **`msgspec.Raw` defers a decode; it does not validate what it defers.** A `Raw` field accepts
  any well-formed JSON value and hands back the bytes, so
  `msgspec.json.decode(b'{"body":{"x":1}}', type=…)` succeeds when the intended shape of `body`
  was something else entirely. Decode it with a type as an explicit second step, and treat the
  field as untrusted until you have.
- **The nesting cap is 9,998 in both directions and it raises `RecursionError`.** One level
  past raises `RecursionError: maximum recursion depth exceeded while deserializing an object`
  (`… serializing …` on the way out), and `sys.setrecursionlimit` moves it in neither
  direction. That is far roomier than [`orjson`](../orjson)'s 254 encode / 1,024 decode, so it
  is unlikely to bite — the exception *type* is the surprise, not the limit, and it is the same
  reason not to catch only `MsgspecError`.
- **What you gain over pydantic, and the three things you give up.** Three of the four gaps you
  might expect are not gaps. JSON Schema generation exists —
  [`msgspec.json.schema(C)`](https://msgspec.dev/api.html#msgspec.json.schema) returns real
  JSON Schema with constraints folded in (`minimum`, `maximum`, `minLength`, `pattern`,
  `required`, `$defs`/`$ref`), from the 17 KB `msgspec/_json_schema.py` that ships in every
  wheel. [Constraints](https://msgspec.dev/constraints.html) exist via
  `typing.Annotated[..., msgspec.Meta(...)]` — `ge`/`gt`/`le`/`lt`/`min_length`/`max_length`/
  `pattern`/`multiple_of`/`tz`, plus `title`/`description`/`examples`/`extra_json_schema` —
  with messages like ``Expected `int` >= 1 - at `$.qty` `` and
  ``Expected `str` matching regex '^[A-Z]+$' - at `$.sku` ``. Coercion exists via `strict=False`,
  custom validation via `__post_init__`, and runtime introspection via
  [`msgspec.inspect.type_info`](https://msgspec.dev/api.html#msgspec.inspect.type_info). What
  you actually give up is the three bullets above: one error at a time, no structured error
  location, and no per-field `field_validator`/`model_validator` — only whole-struct
  `__post_init__`.
- **A `Struct` is a slots-like dataclass with encoding options, and your existing dataclasses
  still work.** Instances carry no `__dict__` (setting an undeclared attribute raises
  `AttributeError`), and the [class options](https://msgspec.dev/structs.html) have no
  dataclass equivalent: `frozen=True` (hashable; mutating raises
  `AttributeError: immutable type`), `kw_only=True`, `rename="camel"`, `tag=True` / `tag="cat"`
  for [tagged unions](https://msgspec.dev/structs.html#tagged-unions) (a bad tag reads
  ``Invalid value 'fish' - at `$.type` ``), `array_like=True` (encodes as `[1,"z"]` instead of
  an object) and `forbid_unknown_fields=True`. A mutable default is allowed and each instance
  gets its own — `tags: list[str] = []` is fine here where `dataclasses` raises
  `ValueError: mutable default`. And plain `@dataclass` types decode and encode through msgspec
  unchanged, so adopting it forces no rewrite; `Struct` is the opt-in upgrade.
- **The memory win is the same single-pass property, and it is the one that matters on a
  phone.** Decoding the 5,000-record document into `Struct`s cost 1.13 MB retained and 1.13 MB
  peak; `orjson.loads` into dicts cost 1.68 MB retained and **5.57 MB peak** — a 4.9× peak
  ratio, because msgspec never materialises the intermediate tree. For one object: a five-field
  `Struct` instance is 72 bytes and has no `__dict__` at all, against a dataclass instance's 48
  bytes plus a 296-byte `__dict__`.
- **Reusing a `Decoder` buys almost nothing at app scale.** 0.573 ms one-shot against 0.572 ms
  through a reused `msgspec.json.Decoder(list[Order])` on the 5,000-record document — inside
  the noise. Upstream's [performance tips](https://msgspec.dev/perf-tips.html) emphasise it in
  a way that reads as a bigger win than it is; use whichever spelling is clearer and reach for
  a `Decoder` only in a hot loop over many small messages.
- **TOML decoding costs you nothing extra; the other three directions cost an extra.**
  `msgspec.toml.decode` tries the stdlib `tomllib` first and only falls back to `tomli`, and
  `tomllib` is stdlib on 3.11+ — every Python Flet's mobile runtimes ship. `msgspec.toml.encode`
  needs `tomli_w`, and both `msgspec.yaml` directions need `PyYAML`; each raises an `ImportError`
  naming what to install. The [`three-ways`](examples/three-ways) example calls all four on
  screen, which is how to confirm the `tomllib` half on a device rather than infer it.
- **`msgspec.msgpack` is not the [`msgpack`](../msgpack) package.** They are unrelated, and
  adding `msgpack` to your dependencies because you used `msgspec.msgpack` is a wasted wheel:
  msgspec's `top_level.txt` is just `msgspec`, and importing `msgspec.msgpack` leaves the
  top-level name `msgpack` untouched in `sys.modules`. Flet itself depends on `msgpack>=1.1.0`,
  so it is already in your app either way — and the
  `TypeError: can not serialize 'set' object` you may see from a Flet control comes from *that*
  msgpack, not from this one.
- **`import msgspec` pulls 35 modules and no stdlib `json`, unless `typing_extensions` is
  installed.** In a virtualenv holding nothing but msgspec and orjson, best of twelve fresh
  desktop interpreters: `import json` 1.99 ms, `import msgspec` **5.85 ms**, `import orjson`
  6.50 ms. msgspec eagerly imports `decimal` (with the `_decimal` C accelerator), `uuid`,
  `datetime`, `enum`, `re` and `typing`, plus all eleven of its own submodules including the
  29 KB `msgspec.inspect` — but **not** `tomllib`, `yaml`, `tomli` or `tomli_w`, which neither
  library touches, and **not** `dataclasses`, the stdlib `json` or `inspect`, all three of which
  orjson's 39 do include. `msgspec/_utils.py` then reaches for `typing_extensions` inside a
  `try/except`, so if anything in your app installs it the import grows to 53 modules and
  9.15 ms — Flet declares it only for `python_version < "3.11"`, which no mobile runtime is, so
  by default it will not be there. Inside a Flet app both costs fall and the gap widens, because
  `import flet` has already pulled `json`, `dataclasses`, `inspect`, `re`, `enum` and `typing`:
  after it, msgspec adds 20 modules and 3.0 ms where orjson adds 6 and 0.8 ms. The `_decimal`
  dependency is the same Flet-runtime property
  [`pydantic-core`](../pydantic-core)'s README documents, and it is what makes exact `Decimal`
  decoding cheap.
- **Size: 178–192 KB to download, 358–480 KB unpacked, and 74–81% of it is the extension.**
  Per slice, on Python 3.14 (3.12 and 3.13 are within 2 KB on Android arm64):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 187 KB | 456 KB | 362 KB |
  | Android armeabi-v7a | 178 KB | 358 KB | 264 KB |
  | Android x86_64 | 192 KB | 447 KB | 353 KB |
  | iOS arm64 (device) | 181 KB | 480 KB | 386 KB |
  | iOS arm64 (simulator) | 185 KB | 467 KB | 373 KB |
  | iOS x86_64 (simulator) | 192 KB | 448 KB | 354 KB |

  The remaining 94 KB is the Python layer (86,906 bytes, of which `inspect.py` is 28,928 and
  `_json_schema.py` 17,351) plus a 9,204-byte `dist-info` — a 5,790-byte `METADATA` and a
  1,498-byte licence, both byte-identical on every slice. There is no CycloneDX SBOM, which
  [`orjson`](../orjson) spends 27 KB on. Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes the five
  `.pyi` files and `py.typed` — its glob list carries `**.pyi` and `**.typed` — which strips
  14,194 bytes and is harmless, since nothing in the package reads either at runtime. Unlike
  orjson, the mobile extension is **not** bloated against desktop: the PyPI
  `macosx_11_0_arm64` 3.14 wheel's `_core` is 379,256 bytes, within ±5% of both mobile figures.
- **Upstream's documentation moved and the wheel's metadata still points at the old address.**
  `METADATA` gives `Homepage: https://jcristharif.com/msgspec/`, which is a 404 today; the docs
  are at [msgspec.dev](https://msgspec.dev/) and the repository at
  [github.com/msgspec/msgspec](https://github.com/msgspec/msgspec) (the `jcrist/msgspec` URL
  redirects). Every link on this page points at the working host.

## Build notes (maintainers)

`meta.yaml` is a name, a version, a build number and one line — `requirements.build:
setuptools ^69.5.1` — with no patches directory and no `build.sh`. That one line is unique in
this repo (`grep -rl 'setuptools \^69.5.1' recipes/*/meta.yaml` matches exactly one file), and
forge translates `^X` into `>=X` (`src/forge/build.py`), so it is a floor seeding setuptools
into the build environment rather than a cap. It is not what decides the version, either:
upstream's own `[build-system] requires` is `setuptools>=80` and `setuptools-scm>=8`, well
above that floor, which is why the wheels report `Generator: setuptools (82.0.1)`. The fact
worth recording is that a 718 KB hand-written `src/msgspec/_core.c` with no Cython and no C
dependencies cross-compiles to all nineteen slices on forge's stock support plus that one seed,
so the day this recipe needs a patch, suspect the toolchain or an upstream restructuring before
reaching for one. Note the version is `setuptools-scm`-derived: the wheel's `_version.py` is
generated, so a build from anything but the sdist (which carries `PKG-INFO`) would have to find
the version somewhere.

**No on-device run backs anything above this section.** msgspec is not in the workflow's
`SMOKE_TEST_PACKAGES` (`lru-dict`, `pydantic-core`, `numpy`) and `git log -- recipes/msgspec`
shows no recipe-specific work since the repo-wide normalisation commits. Every behavioural
claim came off a desktop install of the exact recipe version, and the bridge that licenses that
is narrow but real: all sixteen `.py`/`.pyi` files and `METADATA` are byte-identical
(`shasum -a 256`) between the Android wheel, the iOS wheel **and** the PyPI macOS desktop wheel
of the same version, and every diagnostic string quoted above — the `` - at %U`` path template,
``Expected `%s`, got``, `Object missing required field`, `Object contains unknown field`,
`Invalid enum value`, `Invalid UUID`, `Invalid RFC3339 encoded datetime`, `JSON is malformed`,
`matching regex`, `of length <=`, `multiple of`, `immutable type` and
`while deserializing an object` — is present verbatim in the Android arm64-v8a, Android
armeabi-v7a and iOS device binaries. What that does not establish is that `import msgspec`
succeeds on a phone at all. The [`three-ways`](examples/three-ways) example is the missing
evidence, and its two header lines are built to be the thing you read off the screen.

The nineteen wheels were not produced in one pass, which weakens "they were built together" as
an argument: every 3.12 slice is dated 2026-06-08 and the 3.13 and 3.14 slices 2026-06-11,
except **both** armeabi-v7a slices — 3.13 and 3.14 alike — dated 2026-06-29. Identical skew
pattern to [`orjson`](../orjson)'s. Spot-checked that the 06-29 slice carries the same
diagnostic strings as the others, so the skew has no observed consequence.

`tests/test_msgspec.py` is two docstringed functions with no version assertion, so it already
matches the repo's test conventions — but one docstring calls msgspec "a Cython/C-backed schema
validator" and **there is no Cython here**: the extension is hand-written C built by
setuptools, with no Cython in the build requirements. The tests cover JSON encode/decode and one
`ValidationError` and nothing else, which leaves most of what this page promises unprotected.
The four additions worth more than any timing are the msgpack codec, one `Meta` constraint, one
rich type (`Decimal` or `datetime`) and `forbid_unknown_fields`, so a build that lost any of
those paths could not go green.

On a bump, in rough order of what a green build fails to tell you:

- **The error-message wording**, because this page quotes it and app code will match on it.
  ``Expected `int`, got `str` - at `$[1].qty` `` for the path form, ``Object missing required
  field `qty` ``, ``Object contains unknown field `fontSize` ``, and the constraint phrasings.
  Re-run the strings check against the mobile binaries as well as a desktop install.
- **That unknown fields are still ignored by default**, and that `forbid_unknown_fields` and
  `rename="camel"` still behave as described. This is the top consumer-facing warning here and
  the least protected by anything in `tests/`.
- **The exception hierarchy** — `ValidationError → DecodeError → MsgspecError → ValueError`,
  and that invalid UTF-8, lone surrogates and over-deep nesting still escape it as
  `UnicodeDecodeError`, `UnicodeEncodeError` and `RecursionError`. The advice to catch broad
  `Exception` hangs off this.
- **The integer and `Decimal` behaviour.** Exact ints past 64 bits in both directions, and
  `Decimal` still encoding to a JSON string while decoding from either. Both would corrupt data
  silently if they moved.
- **`Requires-Dist` still fully extra-gated** and the file count still 23. Either an
  unconditional dependency or a new data file would put both the [Install](#install) snippet
  and the no-`extract_packages` claim back in question, and it is worth re-resolving
  `msgspec[toml]` and `msgspec[yaml]` for mobile at the same time — `tomli_w` being pure-Python
  and `pyyaml` having a recipe here is what makes those extras usable.
- **The linkage lists and the filetype.** Android `DT_NEEDED` is `libm`/`libpython3.<minor>`/
  `libdl`/`libc` with 16 KB `PT_LOAD` alignment; iOS is `MH_DYLIB`/`NOUNDEFS` with only
  `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`. Anything new in either
  list is a runtime dependency [Install](#install) does not mention, and an iOS slice that came
  back `MH_BUNDLE` would need forge's conversion. The iOS `LC_ID_DYLIB` still carries the CI
  build path and the extension has no `LC_RPATH` of its own; whether either matters under
  serious_python's framework relocation has not been established.
- **The extension filename spelling per Python.** The 3.12 Android wheels carry a bare
  `cpython-312` tag where 3.13 and 3.14 carry the full platform triple. Both work today; the
  reason to check is that Android's packaging keys on that tag, so an *untagged* `.so` would be
  a silent `ModuleNotFoundError` on device.
- **Whether a bare `msgspec` still resolves from this index.** Today it must, because upstream
  publishes no mobile and no universal wheel — which also means the day it does, this recipe
  may stop being needed. Re-run one `pip download --only-binary :all: --platform … --extra-index-url
  https://pypi.flet.dev msgspec` per target and read the filename that comes back, rather than
  comparing version numbers.
- **The measurements**, all of them: the decode table, the memory figures, the 22% msgpack
  saving, the import timings, the GIL speedup with its `hashlib` control, the nesting caps and
  the size table. Every absolute number above is a desktop number that a phone will not
  reproduce — the *ratios* are the transferable part, and the example exists to produce the
  device figures.
- **The upstream documentation host.** Every `msgspec.dev` link here was checked to resolve
  while `METADATA`'s own `Homepage` did not. If the metadata is ever corrected upstream, drop
  the bullet that says so.
