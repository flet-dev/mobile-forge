# msgspec

[`msgspec`](https://github.com/msgspec/msgspec) serialises **and validates** in one C
extension. You declare the shape of a document as a
[`Struct`](https://msgspec.dev/api#msgspec.Struct) and hand that type to
[`decode`](https://msgspec.dev/api#msgspec.json.decode); what comes back is either typed
objects or a [`ValidationError`](https://msgspec.dev/api#msgspec.ValidationError) naming the
field that was wrong. Four codecs ship in every wheel — JSON, MessagePack, TOML and YAML — and
the first two are compiled in.

Two properties earn it a place on a phone. The check is the same pass as the parse, so a typed
decode costs less than parsing into dicts and writing the `isinstance` loop afterwards; and a
bad field stops the decode where the document goes bad instead of after a full pass over it.
Both are measured under [Speed and memory](#speed-and-memory).

The trade against pydantic is narrower than it looks — constraints, JSON Schema generation and
custom validation are all here — but msgspec reports **only the first error** and gives you no
structured way to locate it. Read [Things to know](#things-to-know) before you build a form on
it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "msgspec",
]
```

**The two extras resolve for mobile as well, at different prices.** `msgspec[toml]` adds one
pure-Python `tomli_w` wheel — its `tomli` line is gated on `python_version < "3.11"`, which no
Flet mobile runtime is — while `msgspec[yaml]` adds [`pyyaml`](../pyyaml). Both were verified
on Android arm64-v8a and iOS device, on 3.12 and 3.14. You may well need neither:
`msgspec.toml.decode` reads TOML through the stdlib `tomllib` with nothing installed beyond
msgspec itself, and only the other three directions need an extra. See the TOML bullet in
[Things to know](#things-to-know).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`three-ways`](examples/three-ways) — decodes one document with `json`, `orjson` and typed
  `msgspec` on the device and shows what each does with a malformed record.

## Usage in a Flet app

```python
import flet as ft
import msgspec


class Settings(msgspec.Struct, forbid_unknown_fields=True):
    theme: str = "light"
    font_size: int = 14


def load(blob: bytes) -> tuple[Settings, str]:
    try:
        return msgspec.json.decode(blob, type=Settings), ""
    except Exception as error:  # not only MsgspecError — see Things to know
        return Settings(), str(error)


settings, problem = load(blob)
page.add(ft.Text(settings.theme, size=settings.font_size), ft.Text(problem))
```

[`encode`](https://msgspec.dev/api#msgspec.json.encode) is the other half and hands back
`bytes`. `forbid_unknown_fields=True` is not the default and is the single most useful thing to
put on a `Struct` you decode untrusted input into — the first bullet of
[Things to know](#things-to-know) is what happens without it.

### Storage

msgspec has **no file API** — there is no `dump()` and no `load()`, only `encode` and `decode`
— so the file handling stays yours. `encode` hands you `bytes`, so the mode is binary:

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
[`msgspec.msgpack`](https://msgspec.dev/api#msgspec.msgpack.decode) is the same API against a
binary encoding, with the same validation: on the example's 5,000-record document it is
**251,619 bytes against JSON's 323,757**, 22% smaller, with `type=` behaving identically. Reach
for it for caches and for anything you send over a metered connection; keep JSON where a human
or another language has to read the file.

The `type=` argument is what makes reading a file back safe. A settings file the user edited, a
cache written by an older version of your app and a truncated download are all *plausible*
JSON, and a typed decode is the difference between an `AttributeError` three screens later and
one `ValidationError` at the point of reading.

### Threading

**msgspec holds the GIL for the whole call, so threads buy no parallelism.** There is no
GIL-release path in the extension to reach and nothing in the wheel starts a thread of its own.
Measured on desktop against a control that does release it: four threads each doing 20 typed
decodes of a 323,757-byte document took 47.9 ms against one thread's 12.1 ms — a parallel
speedup of **1.01×** — where the same harness gave `hashlib.sha256` **3.56×**. Decoding scales
with clock speed, never with core count, and there is no pool to size.

There is no shared handle to serialise either. `encode` and `decode` are functions with no state
you hold, a reused [`Decoder`](https://msgspec.dev/api#msgspec.json.Decoder) or `Encoder` is the
only object you would hold at all, and because the GIL is held for the whole of a call there is
nothing for two threads to interleave inside one.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
buy you is an event handler that returns immediately — worth having for a large document and
worth nothing for a small one. The Flet-side rules then apply: a worker must end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads, and its body must be wrapped in `try/except`,
because `run_thread` discards whatever it raises — a `ValidationError` in a worker looks like a
screen that stopped updating, not like an error.

### Speed and memory

Desktop CPython 3.12 on an arm64 Mac, a 5,000-record 323,757-byte document, best of 12×20. The
absolute numbers are desktop numbers; the ratios are the part that transfers to a phone.

| decoder | ms | checks the document |
| --- | ---: | --- |
| `json.loads` | 1.494 | no |
| `orjson.loads` | 0.659 | no |
| `orjson.loads` plus a hand-written type loop | 0.968 | yes |
| `msgspec.json.decode(blob, type=list[Order])` | **0.573** | yes |

The fastest of the four is also the only one that checks the document without a second pass over
it. Corrupt one field of that same document and the second property shows up: at record 1 the
decode fails in **0.001 ms**, at the last record it costs a full pass — 0.573 ms, against
0.579 ms for the fully valid document in the same run. A parse-only library pays the full pass
either way and then hands you the wrong-typed value with no complaint.

Peak memory is what decides whether a large document fits on a phone at all. Decoding those
5,000 records into `Struct`s cost 1.13 MB retained and 1.13 MB peak; `orjson.loads` into dicts
cost 1.68 MB retained and **5.57 MB peak** — a 4.9× peak ratio, because msgspec never
materialises the intermediate tree. Per object, a five-field `Struct` instance is 72 bytes and
has no `__dict__` at all, against a dataclass instance's 48 bytes plus a 296-byte `__dict__`.

Reusing a `Decoder` buys almost nothing at app scale: 0.573 ms one-shot against 0.572 ms through
a reused `msgspec.json.Decoder(list[Order])`, inside the noise. Upstream's
[performance tips](https://msgspec.dev/perf-tips) emphasise it in a way that reads as a bigger
win than it is — use whichever spelling is clearer, and reach for a `Decoder` only in a hot loop
over many small messages.

### App size

Approximately 180–200 KB compressed and 365–495 KB unpacked per architecture. Three quarters to
four fifths of that is the single `msgspec._core` extension; the rest is the Python layer, whose
two largest files are `inspect.py` at 29 KB and `_json_schema.py` at 17 KB. Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes the five
`.pyi` files and `py.typed`, stripping about 14 KB, and is harmless here because nothing in the
package reads either at runtime.

An app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
levers worth pulling for other packages rather than for this one; every ABI `flet build` asks
for is published. These figures describe the package payload, not the amount added to the final
APK or IPA; packaging and compression decide that.

### Other considerations

**Every absolute figure on this page is a desktop figure.** They came off a desktop install of
the same version, and no phone will reproduce them — the ratios are the transferable part. The
[`three-ways`](examples/three-ways) example exists to put your device's own numbers on screen.

**Do not locate the native module by path.** Flet relocates every tagged extension out of
site-packages, so `msgspec._core.__file__` is not a path inside your app on either platform: on
iOS serious_python turns the `.so` into a framework and leaves a `_core.fwork` pointer file
behind, and whether the attribute exists at all varies by package as well as by platform —
[`pydantic-core`](../pydantic-core) reports none on Android where [`pyyaml`](../pyyaml) reports a
bare `jniLibs` filename. The filename is not stable either: 3.13 and 3.14 ship
`_core.cpython-3<minor>-<triple>.so` where the 3.12 wheels from the same build ship a bare
`_core.cpython-312.so`. Nothing inside msgspec reads either, so this only bites code of yours
that locates something relative to a native module — match on `_core.cpython-*` rather than a
full filename, and fall back to `__spec__.origin` when `__file__` is missing.

**The YAML codec can work under `flet run` and fail on the device.** `flet-cli` in a project's
`dev` dependency group drags PyYAML in through `cookiecutter`, and the `dev` group is not
packaged into the app — so a desktop run can report `msgspec.yaml` working where a build without
`msgspec[yaml]` cannot. Take the device reading as the answer.

## Things to know

- **Unknown fields are ignored by default, and the damage is the field that keeps its default.**
  A server sending `fontSize` where your `Struct` declares `font_size` gives you
  `Settings(theme='dark', font_size=14, notifications=False)` — no error, no warning, and the
  value the user actually set is gone. This is the trap for anyone arriving from pydantic
  expecting validation to mean rejection. Two fixes, and which one you want depends on whether
  the wire format is wrong or merely different: `class Settings(msgspec.Struct,
  forbid_unknown_fields=True)` turns it into ``ValidationError: Object contains unknown field
  `fontSize` ``, and [`rename="camel"`](https://msgspec.dev/structs) decodes `fontSize` into
  `font_size` correctly and encodes it back. Note it only bites fields that *have* a default — a
  required field missing from the payload does raise ``Object missing required field `qty` ``.
- **Only the first error is reported, and it carries no structured location.** A record with
  three bad fields raises once, naming ``$.a`` and nothing else. The path is embedded in the
  message text — ``Expected `int`, got `str` - at `$.qty` ``, ``… - at `$[1].qty` `` inside a
  list, ``… - at `$.lines[1].qty` `` nested two deep — and the exception adds no attributes at
  all over `BaseException`: no `.errors()`, no `loc` tuple, no `.path`, and `e.args` is a
  one-element tuple holding the whole sentence. Pydantic's `ValidationError.errors()` returns a
  per-field list; msgspec has no equivalent, so a rejection table cannot be built the same way.
  Decode record-by-record instead — or as
  `list[msgspec.Raw]` and then per item — so the index is yours rather than the message's, and
  show `str(e)` as the reason. On the happy path the same property is a feature: it is exactly
  why the early abort is 0.001 ms on the 5,000-record document above.
- **`except msgspec.MsgspecError` does not catch everything a decode can raise.** Invalid UTF-8
  in the input raises a plain `UnicodeDecodeError`, encoding a lone surrogate raises a plain
  `UnicodeEncodeError`, and exceeding the nesting cap raises a plain `RecursionError` — none of
  which inherit from `MsgspecError`. The reverse mistake is worse: `DecodeError.__bases__` is
  `(MsgspecError, ValueError)`, so a bare `except ValueError` silently swallows the validation
  failures you meant to surface. Catch broad `Exception` around anything parsing input your app
  did not produce, which is also the Flet rule — an unhandled exception in an event handler sends
  `SESSION_CRASHED`. Surrogates matter specifically on a phone because `os.listdir()` and
  `os.environ` hand them to you under `surrogateescape`.
- **No 64-bit integer limit.** msgspec does not have orjson's most dangerous trap:
  `msgspec.json.decode(b"12345678901234567890123")` returns the exact `int` both untyped and with
  `type=int`, and `2**63`, `2**64 - 1`, `2**64`, `2**100` and `-2**63 - 1` all round-trip exactly,
  where `orjson.loads` silently returns `1.2345678901234568e+22` and `orjson.dumps` raises
  `TypeError: Integer exceeds 64-bit range`. A non-`str` dict key is coerced like the stdlib does
  (`{1: "a"}` → `b'{"1":"a"}'`) rather than refused. If you moved to orjson to escape the stdlib
  and hit either of those, msgspec is the way back.
- **Rich types decode and re-encode natively, and `Decimal` is exact.** One `Struct` carrying
  `datetime` (RFC 3339, offset preserved as a `datetime.timezone`), `date`, `time`, `uuid.UUID`,
  `decimal.Decimal`, `Enum` (by value), `IntEnum`, `timedelta` (ISO-8601 duration), `set` and
  `bytes` (base64) decodes from one payload and re-encodes — the last two being types orjson
  refuses outright. Bad values give typed messages: `Invalid enum value 'green'`, `Invalid UUID`,
  `Invalid RFC3339 encoded datetime`. Two asymmetries to know about. `Decimal` **encodes to a
  JSON string** (`b'"1.10"'`) while it decodes from either a string or a bare number, so msgspec
  round-trips its own output exactly but a JavaScript or Go consumer sees `"1.10"` where it
  expected `1.10` — agree the wire representation explicitly, and prefer changing the other side,
  because the exactness is the whole reason to use `Decimal`. And `timedelta` **does not
  round-trip byte-stably**: `"P1DT2H"` decodes to `timedelta(days=1, seconds=7200)` and
  re-encodes as `"P1DT7200S"`, identical in meaning and different in text, so never diff, hash,
  sign or cache on encoded bytes across a decode/encode cycle.
- **`strict=False` is per call, not per field.** The default refuses string-to-int
  (``Expected `int`, got `str` ``) and float-to-int (``Expected `int`, got `float` ``) but does
  widen int to float, so `"price": 3` into a `float` field gives `3.0`.
  [`strict=False`](https://msgspec.dev/usage#strict-vs-lax-mode) enables string coercion
  everywhere in that one call — `"1"` → `1`, `"true"` → `True` — while still rejecting genuine
  garbage (`"abc"` into an `int` still raises). There is no way to relax it for one field only.
- **`__post_init__` runs on the decode path, and launders exceptions inconsistently.** It is the
  [custom-validation hook](https://msgspec.dev/structs#post-init-processing) and it fires on
  decoding as well as on construction — but a `ValueError` or `TypeError` raised there comes back
  as a `msgspec.ValidationError` with the message preserved, while a `KeyError` propagates
  untouched as a `KeyError`, and on plain construction (`PI(-1)`, no decoding) the same
  `ValueError` stays a `ValueError`. Raise `ValueError` and catch broad `Exception` at the call
  site rather than keying on the type.
- **`msgspec.Raw` defers a decode; it does not validate what it defers.** A `Raw` field accepts
  any well-formed JSON value and hands back the bytes, so
  `msgspec.json.decode(b'{"body":{"x":1}}', type=…)` succeeds when the intended shape of `body`
  was something else entirely. Decode it with a type as an explicit second step, and treat the
  field as untrusted until you have.
- **The nesting cap is 9,998 in both directions and it raises `RecursionError`.** One level past
  raises `RecursionError: maximum recursion depth exceeded while deserializing an object`
  (`… serializing …` on the way out), and `sys.setrecursionlimit` moves it in neither direction.
  That is far roomier than [`orjson`](../orjson)'s 254 encode / 1,024 decode, so it is unlikely to
  bite — the exception *type* is the surprise, not the limit, and it is the same reason not to
  catch only `MsgspecError`.
- **What you gain over pydantic, and the three things you give up.** Three of the four gaps you
  might expect are not gaps. JSON Schema generation exists —
  [`msgspec.json.schema(C)`](https://msgspec.dev/api#msgspec.json.schema) returns real JSON Schema
  with constraints folded in (`minimum`, `maximum`, `minLength`, `pattern`, `required`,
  `$defs`/`$ref`), from the 17 KB `msgspec/_json_schema.py` that ships in every wheel.
  [Constraints](https://msgspec.dev/constraints) exist via
  `typing.Annotated[..., msgspec.Meta(...)]` — `ge`/`gt`/`le`/`lt`/`min_length`/`max_length`/
  `pattern`/`multiple_of`/`tz`, plus `title`/`description`/`examples`/`extra_json_schema` — with
  messages like ``Expected `int` >= 1 - at `$.qty` `` and
  ``Expected `str` matching regex '^[A-Z]+$' - at `$.sku` ``. Coercion exists via `strict=False`,
  custom validation via `__post_init__`, and runtime introspection via
  [`msgspec.inspect.type_info`](https://msgspec.dev/api#msgspec.inspect.type_info). What you
  actually give up is the three bullets above: one error at a time, no structured error location,
  and no per-field `field_validator`/`model_validator` — only whole-struct `__post_init__`.
- **A `Struct` is a slots-like dataclass with encoding options, and your existing dataclasses
  still work.** Instances carry no `__dict__` (setting an undeclared attribute raises
  `AttributeError`), and the [class options](https://msgspec.dev/structs) have no dataclass
  equivalent: `frozen=True` (hashable; mutating raises `AttributeError: immutable type`),
  `kw_only=True`, `rename="camel"`, `tag=True` / `tag="cat"` for
  [tagged unions](https://msgspec.dev/structs#tagged-unions) (a bad tag reads
  ``Invalid value 'fish' - at `$.type` ``), `array_like=True` (encodes as `[1,"z"]` instead of an
  object) and `forbid_unknown_fields=True`. A mutable default is allowed and each instance gets
  its own — `tags: list[str] = []` is fine here where `dataclasses` raises
  `ValueError: mutable default`. And plain `@dataclass` types decode and encode through msgspec
  unchanged, so adopting it forces no rewrite; `Struct` is the opt-in upgrade.
- **TOML decoding costs you nothing extra; the other three directions cost an extra.**
  `msgspec.toml.decode` tries the stdlib `tomllib` first and only falls back to `tomli`, and
  `tomllib` is stdlib on 3.11+ — every Python Flet's mobile runtimes ship. `msgspec.toml.encode`
  needs `tomli_w`, and both `msgspec.yaml` directions need `PyYAML`; each raises an `ImportError`
  naming what to install. The [`three-ways`](examples/three-ways) example calls all four on
  screen, which is how to confirm the `tomllib` half on a device rather than infer it.
- **`msgspec.msgpack` is not the [`msgpack`](../msgpack) package.** They are unrelated, and adding
  `msgpack` to your dependencies because you used `msgspec.msgpack` is a wasted wheel: msgspec's
  `top_level.txt` is just `msgspec`, and importing `msgspec.msgpack` leaves the top-level name
  `msgpack` untouched in `sys.modules`. Flet itself depends on `msgpack>=1.1.0`, so it is already
  in your app either way — and the `TypeError: can not serialize 'set' object` you may see from a
  Flet control comes from *that* msgpack, not from this one.
- **`import msgspec` is an eager import, and something else installing `typing_extensions` makes
  it cost nearly twice as much.** It pulls 35 modules on its own — `decimal` (with the `_decimal`
  C accelerator, which is present in Flet's mobile Python builds and is what makes exact
  `Decimal` decoding cheap), `uuid`, `datetime`, `enum`, `re`, `typing` and all eleven of its own
  submodules, though not `tomllib`, `yaml`, `tomli` or `tomli_w`. `msgspec/_utils.py` then
  reaches for `typing_extensions` inside a `try/except`, and where that package is present the
  import grows to 53 modules and from 5.85 ms to 9.15 ms on a desktop interpreter. Flet declares
  it only for `python_version < "3.11"`, which no mobile runtime is, so by default it will not be
  there — check before adding a dependency that drags it in. Inside a Flet app the cost is much
  lower anyway, because `import flet` has already pulled `json`, `dataclasses`, `inspect`, `re`,
  `enum` and `typing`: after it, msgspec adds 20 modules and 3.0 ms.
- **The `Homepage` in the wheel's metadata is dead.** `METADATA` gives
  `https://jcristharif.com/msgspec/`, which 404s today; the documentation is at
  [msgspec.dev](https://msgspec.dev/) and the repository at
  [github.com/msgspec/msgspec](https://github.com/msgspec/msgspec) (the `jcrist/msgspec` URL
  redirects). Every link on this page points at the working host.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version, a build number and one line — `requirements.build:
setuptools ^69.5.1` — with no patches directory and no `build.sh`. That line is unique in this
repo (`grep -rl 'setuptools \^69.5.1' recipes/*/meta.yaml` matches exactly one file), and forge
translates `^X` into `>=X` (`install_requirements` in `src/forge/build.py`), so it is a floor
seeding setuptools into the build environment rather than a cap. It is not what decides the
version either: upstream's own `[build-system] requires` is `setuptools>=80` and
`setuptools-scm>=8`, well above that floor, which is why the wheels report
`Generator: setuptools (82.0.1)`.

The fact worth recording is that a 718 KB hand-written `src/msgspec/_core.c` with no Cython and
no C dependencies cross-compiles to all nineteen slices on forge's stock support plus that one
seed — so the day this recipe needs a patch, suspect the toolchain or an upstream restructuring
before reaching for one. The version is `setuptools-scm`-derived: the wheel's `_version.py` is
generated, so a build from anything but the sdist (which carries `PKG-INFO`) would have to find
the version somewhere.

Why [Install](#install) carries no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry: the wheel
is 23 entries with no data file anywhere, no occurrence of `__file__`, `importlib.resources`,
`pkgutil`, `pkg_resources` or `getsource` in any shipped module, and the native module is
`msgspec._core`, a submodule rather than the package `__init__` — the ordinary shape Android's
zipped site-packages handles as-is.

The build matrix is nineteen wheels at the same build number: ten Android (arm64-v8a,
armeabi-v7a and x86_64 on each of 3.12, 3.13 and 3.14, plus a legacy `android_24_x86` on 3.12)
and nine iOS (device, arm64 simulator and x86_64 simulator on each of the three).
`Requires-Python` in the wheel is upstream's `>=3.10`, so the floor a consumer actually hits is
Flet's.

### Upgrade hazards

- **The error-message wording**, because this page quotes it and app code will match on it:
  ``Expected `int`, got `str` - at `$[1].qty` `` for the path form, ``Object missing required
  field `qty` ``, ``Object contains unknown field `fontSize` ``, and the constraint phrasings.
  Re-run the strings check against the mobile binaries as well as a desktop install.
- **That unknown fields are still ignored by default**, and that `forbid_unknown_fields` and
  `rename="camel"` still behave as described. This is the top consumer-facing warning on the page
  and the least protected by anything in `tests/`.
- **The exception hierarchy** — `ValidationError → DecodeError → MsgspecError → ValueError`, and
  that invalid UTF-8, lone surrogates and over-deep nesting still escape it as
  `UnicodeDecodeError`, `UnicodeEncodeError` and `RecursionError`. The advice to catch broad
  `Exception` hangs off this.
- **The integer and `Decimal` behaviour.** Exact ints past 64 bits in both directions, and
  `Decimal` still encoding to a JSON string while decoding from either. Both would corrupt data
  silently if they moved.
- **Upstream publishing its own mobile wheels** would remove this recipe's reason to exist. Today
  it publishes neither a mobile-tagged nor a `py3-none-any` wheel — 49 files at the current
  version, none of them Android, iOS or universal — which is what makes a bare `msgspec` resolve
  from this index.

### Re-verification checklist

- **That a bare `msgspec` still resolves from this index, on every slice.** Re-run one
  `pip download --only-binary :all: --platform … --extra-index-url https://pypi.flet.dev msgspec`
  per target and read the filename that comes back, rather than comparing version numbers. All
  eighteen combinations — Android arm64-v8a, armeabi-v7a and x86_64 plus iOS device and both
  simulator slices, on 3.12, 3.13 and 3.14 — must come back with this index's wheel.
- **`Requires-Dist` still fully extra-gated** and the file count still 23. Either an unconditional
  dependency or a new data file would put both the [Install](#install) snippet and the
  no-`extract_packages` reasoning back in question. Re-resolve `msgspec[toml]` and `msgspec[yaml]`
  for mobile at the same time — `tomli_w` being pure-Python and `pyyaml` having a recipe here is
  what makes those extras usable.
- **The linkage lists and the filetype.** Android `DT_NEEDED` is `libm.so`/`libpython3.<minor>.so`
  /`libdl.so`/`libc.so` with no `libc++_shared`, and every `PT_LOAD` segment must keep 16 KB
  alignment for Android 15; armeabi-v7a and the legacy `x86` slice must stay genuine `ELF32`
  builds. iOS must stay `MH_DYLIB`/`NOUNDEFS` (`otool -hv`) with only
  `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib` in `otool -L` — an
  `MH_BUNDLE` slice would need forge's conversion, and anything new in either list is a runtime
  dependency [Install](#install) does not mention. The iOS `LC_ID_DYLIB` still carries the CI
  build path and the extension has no `LC_RPATH` of its own; whether either matters under
  serious_python's framework relocation has not been established.
- **The GIL claim behind [Threading](#threading).** `PyEval_SaveThread`, `PyEval_RestoreThread`,
  `PyGILState_*` and `pthread_create` must all stay absent from the undefined symbols of every
  slice.
- **The extension filename spelling per Python.** The 3.12 Android wheels carry a bare
  `cpython-312` tag where 3.13 and 3.14 carry the full platform triple. Both work today; the
  reason to check is that Android's packaging keys on that tag, so an *untagged* `.so` would be a
  silent `ModuleNotFoundError` on device.
- **Size.** Re-measure compressed and unpacked from the built wheels; the figures in
  [App size](#app-size) are decimal KB, so a `du -h` re-measurement will disagree with them by
  about 2%. The extension was 370,552 bytes on the Android arm64-v8a slice against 395,648 on the
  iOS device slice at 3.14, so iOS carrying roughly 7% more native code for the same Python is
  expected rather than a regression. It is also not bloated against desktop: PyPI's
  `macosx_11_0_arm64` wheel's `_core` is 379,256 bytes, within ±5% of both.
- **The measurements**, all of them: the decode table, the memory figures, the 22% msgpack saving,
  the import timings, the GIL speedup with its `hashlib` control and the nesting caps. Every
  absolute number on the page is a desktop number, the ratios are the transferable part, and the
  example exists to produce the device figures.
- **The upstream documentation host.** Every `msgspec.dev` link here was checked to resolve while
  `METADATA`'s own `Homepage` did not. If the metadata is ever corrected upstream, drop the bullet
  that says so.

### Coverage gaps

**No on-device run backs anything above the Build notes.** msgspec is not in the workflow's
`SMOKE_TEST_PACKAGES` (`lru-dict`, `pydantic-core`, `numpy`), and every behavioural claim came off
a desktop install of the recipe version. The bridge that licenses that is narrow but real: all
sixteen `.py`/`.pyi` files and `METADATA` are byte-identical (`shasum -a 256`) between the Android
wheel, the iOS wheel and the PyPI macOS desktop wheel of the same version, and every diagnostic
string quoted on this page is present verbatim in the Android arm64-v8a, Android armeabi-v7a and
iOS device binaries. What that does not establish is that `import msgspec` succeeds on a phone at
all. The [`three-ways`](examples/three-ways) example is the missing evidence, and its two header
lines are built to be the thing you read off the screen.

`tests/test_msgspec.py` is two functions covering JSON encode/decode and one `ValidationError`,
which leaves most of what this page promises unprotected. One docstring there calls msgspec "a
Cython/C-backed schema validator" and **there is no Cython here** — the extension is hand-written
C built by setuptools. The four additions worth more than any timing are the msgpack codec, one
`Meta` constraint, one rich type (`Decimal` or `datetime`) and `forbid_unknown_fields`, so a
build that lost any of those paths could not go green.

The nineteen wheels were not produced in one pass, which weakens "they were built together" as an
argument: every 3.12 slice is dated 2026-06-08 and the 3.13 and 3.14 slices 2026-06-11, except
**both** armeabi-v7a slices — 3.13 and 3.14 alike — dated 2026-06-29. Spot-checked that the 06-29
slice carries the same diagnostic strings as the others, so the skew has no observed consequence.
