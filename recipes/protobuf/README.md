# protobuf

[Protocol Buffers](https://protobuf.dev/) is Google's schema-first binary wire format, and
this is its Python runtime. You describe your records once, and every language that speaks
protobuf reads and writes the same bytes — so on a phone, the bytes your backend already
produces are the bytes your app reads, smaller and faster than the same records as JSON
([Speed and wire size](#speed-and-wire-size) has the figures).

The reason this recipe exists is `google/_upb/_message`, the C extension that does the actual
encoding and decoding. **protobuf works without it**, by silently substituting a pure-Python
implementation, and that is the trap: nothing warns you, every message still round-trips
correctly, and the app is roughly a hundred times slower. Upstream publishes a
`py3-none-any` wheel that pip is happy to install on Android and iOS, and it contains no
extension at all. The wheels here do.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "protobuf",
]
```

**Write the version from [`meta.yaml`](meta.yaml) into that `protobuf` line.** A bare
requirement resolves to whatever PyPI's latest is, and upstream's
`protobuf-<latest>-py3-none-any.whl` is tagged compatible with every platform, so pip prefers
it over anything on this index the moment PyPI is one release ahead. Resolving the way
`flet build` does, a bare `protobuf` came back as upstream's `py3-none-any` wheel on **all
eighteen** mobile slices — three Android ABIs and three iOS slices on each of 3.12, 3.13 and
3.14 — where the pinned spelling came back with this index's wheel on all eighteen. That
wheel then installs cleanly and produces no error of any kind: the only sign is
`api_implementation.Type()` reporting `python` instead of `upb`, which is why the first
bullet of [Things to know](#things-to-know) is an assertion at startup.

If you need the well-known Google API messages (`google.type`, `google.rpc` and the rest), add
`googleapis-common-protos`: it is pure Python on PyPI and resolves for a mobile target
alongside the pinned wheel here.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`runtime-schema`](examples/runtime-schema) — a schema built from a `FileDescriptorProto` at
  startup with no protoc anywhere, timed against `json` and stressed with corrupt bytes.

## Usage in a Flet app

```python
import flet as ft
from google.protobuf.internal import api_implementation

from reading_pb2 import Reading  # protoc output, committed into src/

assert api_implementation.Type() == "upb"  # anything else is the slow fallback

blob = Reading(id=7, sensor="kitchen", celsius=21.5).SerializeToString()
back = Reading.FromString(blob)
page.add(ft.Text(f"{back.sensor}: {back.celsius} °C in {len(blob)} bytes"))
```

`SerializeToString()` hands you `bytes` and `FromString` takes them back; `ParseFromString` is
the in-place spelling for a message object you already hold. The rest of this section is about
where `Reading` comes from, where the bytes go, and what happens when they are wrong.

### Storage

protobuf hands you `bytes`, so the file handling is yours and the mode is binary. Put files in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted and is included in backups;
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose.

**A file of concatenated messages is not a file of records.** protobuf's wire format has no
message boundary, so two `SerializeToString()` outputs written back to back parse as one
*merged* message with the second record's scalars silently overwriting the first's — appending
`Reading(id=1, sensor="aa")` and `Reading(id=2, sensor="bb")` and parsing the result gives
`{'id': 2, 'sensor': 'bb'}` and no error. `google.protobuf.proto` ships the framing:

```python
from google.protobuf import proto

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "readings.pb")
with open(path, "wb") as handle:
    for reading in readings:
        proto.serialize_length_prefixed(reading, handle)
with open(path, "rb") as handle:
    while (reading := proto.parse_length_prefixed(Reading, handle)) is not None:
        ...
```

Both take a real file object despite being annotated `io.BytesIO`, and `parse_length_prefixed`
returns `None` at EOF. The framing is one varint per record — a single byte while a record
stays under 128 bytes — which is cheaper than wrapping the lot in a `repeated` field, where
each element also carries a tag: on the example's 2,000 readings the log is 63,034 bytes
against 65,034 for the same records inside one `Batch` message.

There is no atomic-write machinery — one `write()` is the whole operation — so if a truncated
file after a kill would hurt, write beside the target and `os.replace` it yourself. And a
parse succeeding is not evidence the file is yours; see the third bullet of
[Things to know](#things-to-know).

### Threading

**protobuf holds the GIL for the whole of a call, so threads buy no parallelism.** There is no
GIL-release path in the extension to reach, and the Python layer imports `threading` in exactly
two modules and uses it only for `threading.Lock`, never to start one. Measured on desktop
against a control that does release the GIL: four threads each parsing a 5,000-record message
40 times took 21.9 ms against one thread's 5.5 ms — a parallel speedup of **1.00x** — where the
same harness gave `hashlib.sha256` **3.41x**. Encoding and decoding scale with clock speed,
never with core count, and there is no pool to size.

What [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does
buy you is an event handler that returns immediately, which is worth having for a large
document and worth nothing for a small one. The Flet-side rules then apply: a worker must end
with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update),
because auto-update does not reach background threads, and its body must be wrapped in
`try/except`, because `run_thread` discards whatever it raises — a `DecodeError` in a worker
looks like a screen that stopped updating, not like an error.

Give each thread its own message *instances*. Reading a field of a parsed message is not the
passive lookup it looks like on the upb path: the parse leaves the bytes largely untouched and
attribute access is where the work happens, which is exactly the gap between the parse and
parse-plus-read rows below. Nothing here measured a race, so this is a recommendation rather
than a finding — but "two threads only reading" is not what it sounds like here. The message
*classes* are a different matter: build them once at import and share them freely, for the
reasons in [Things to know](#things-to-know).

### Getting a schema onto the device

There is no `protoc` on a phone and none in this wheel —
`google/protobuf/compiler/plugin_pb2.py` is the plugin *protocol*, not a compiler — so a
message class has to arrive some other way. Three routes, all verified against these wheels:

1. **Run protoc on your build machine and commit the generated
   [`_pb2.py`](https://protobuf.dev/reference/python/python-generated/) into `src/`.** It is
   plain Python and imports unchanged here. This is the ordinary route.
2. **Run `protoc --descriptor_set_out` and ship the result as an
   [asset](https://flet.dev/docs/cookbook/assets).** Load it with `FileDescriptorSet.FromString`
   plus `pool.Add` (or `pool.AddSerializedFile`) — 187 bytes for a two-message schema.
3. **Build the `FileDescriptorProto` in Python at runtime.** This needs no protoc on any
   machine, not even the one you build on, and is the only one of the three that makes a
   self-contained app possible. The [`runtime-schema`](examples/runtime-schema) example is this
   route end to end, and `tests/test_protobuf.py` exercises the same API.

`proto_builder.MakeSimpleProtoClass` is route 3 in one call: it turns a plain
`{"id": TYPE_INT32, "sensor": TYPE_STRING}` dict into a message class without touching
`descriptor_pb2` at all. It has no way to express a repeated or nested message field, so
anything with a list of records still needs `descriptor_pool` plus `message_factory`.

Routes 1 and 3 cost about the same at import. On a desktop interpreter, `descriptor_pb2` plus
`descriptor_pool` plus `message_factory` was 11.4 ms and 69 modules, against a generated `_pb2`
module's 10.7 ms and 69, where `import json` is 2.5 ms and 13. A generated module registers its
schema through `AddSerializedFile` and never loads `descriptor_pb2` at all — 32 `google.*`
modules end up in `sys.modules` and that is not one of them — so the two routes separate only
on a cold `__pycache__`, where compiling `descriptor_pb2`'s 372 KB of Python costs route 3
about 40 ms more. Your build machine pays that once, not the phone. `import google.protobuf` on
its own is free: the package `__init__` is a version string.

Whichever route you take, build the message classes **once**, at import — the fifth bullet of
[Things to know](#things-to-know) is what happens otherwise.

### Speed and wire size

Desktop CPython 3.14 on an arm64 Mac, a 2,000-record document of five-field sensor readings,
best of 20. The absolute numbers are desktop numbers; the ratios are the part that transfers to
a phone.

| | protobuf | `json` | ratio |
| --- | ---: | ---: | ---: |
| wire bytes | 65,034 | 149,475 | 44% |
| serialise, ms | 0.044 | 0.652 | 15x |
| parse, ms | 0.055 | 0.648 | 12x |
| parse + read every field, ms | 0.507 | 0.805 | 1.6x |

The JSON side is `json.dumps(rows, separators=(",", ":"))`, and the byte ratio holds from 500 to
20,000 records. The last row is what keeps the other two honest: upb's parse does not build
Python objects, so parse alone measures almost nothing and the work moves to attribute access.
The two speedups bracket your case — pull a few fields out of a large message and you land near
12x, walk the whole thing and you land on 1.6x.

Without the extension the comparison inverts outright. The same job on the pure-Python
implementation takes 3.927 ms to serialise and 9.251 ms to parse, losing to the standard
library's `json` on both. That is what the assertion in [Things to know](#things-to-know) is
protecting.

### App size

Approximately 300–340 KB compressed and 1.2–1.4 MB unpacked per architecture. Two thirds to
four fifths of the unpacked size is the Python layer rather than the extension — about 920 KB
across 55 modules, byte-identical on every slice — so narrowing architectures moves less here
than it does for a package that is mostly native code. Flet's default
[compile-to-`.pyc`](https://flet.dev/docs/publish/#compilation-and-cleanup) does not shrink it
either: the same modules compile to about 1.0 MB of bytecode, and there is no test suite or data
directory worth removing.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the amount
added to the final APK or IPA; packaging and compression decide that.

### Other considerations

**A desktop `flet run` will not show you the fallback.** On macOS, Linux and Windows pip
installs upstream's own binary wheel, which carries the extension, so `api_implementation.Type()`
reports `upb` there whether or not the mobile pin is right. The wheel that goes into an APK or
IPA is resolved separately, at build time. Take the device reading as the answer, and put the
assertion where you will see it on a phone.

**The Python layer is the same code you develop against.** All 55 `.py` files are byte-identical
(`shasum -a 256`) between the Android wheel, the iOS wheel and upstream's desktop wheels of the
same version, so the API on the phone is the API on your laptop. What differs is the one native
file and the wheel metadata.

**Every absolute figure on this page is a desktop figure.** No phone will reproduce them; the
ratios are the transferable part. The [`runtime-schema`](examples/runtime-schema) example exists
to put your device's own numbers on screen.

**Do not locate the extension by path.** Flet relocates every tagged extension out of
site-packages: on Android the `.so` moves into `jniLibs` and a `_message.soref` marker file is
left behind, and on iOS serious_python turns it into a framework and leaves a `_message.fwork`
pointer file. The filename is not stable either — 3.13 and 3.14 ship
`_message.cpython-3<minor>-<triple>.so` where the 3.12 wheels from the same build ship a bare
`_message.cpython-312.so`. Nothing inside protobuf reads either, so this only bites code of
yours that goes looking; match on `_message.cpython-*` rather than on a full filename.

## Things to know

- **Assert the implementation at startup; nothing else will tell you.** With the extension
  gone, `api_implementation.Type()` returns `python`, `descriptor._USE_C_DESCRIPTORS` becomes
  `False` and message classes are built by
  `google.protobuf.internal.python_message.GeneratedProtocolMessageType` instead of
  `google._upb._message.MessageMeta` — and **no warning is printed at all**, even under
  `python -W always`. Verified by renaming `site-packages/google/_upb` away: every message
  still round-tripped, and the cost on a 2,000-record job went from 0.055 ms to 9.251 ms to
  parse and 0.044 ms to 3.927 ms to serialise. So:

  ```python
  from google.protobuf.internal import api_implementation
  assert api_implementation.Type() == "upb"
  ```

  Do **not** check that `google._upb._message` imports instead. That proves nothing: under
  `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` the module still imports and still reports a
  real `.so` origin while every message is built by the pure-Python metaclass. All three
  signals above flip; the import check does not.
- **Leave `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION` unset.** It is read at import and accepts
  only `python`, `cpp` or `upb`. `cpp` is not a third option on these wheels — it makes
  `import google.protobuf.descriptor` fail outright with `ImportError: cannot import name
  '_message' from 'google.protobuf.pyext'`, because the wheel ships `google/_upb` and no
  `pyext` extension — and any other value raises
  `ValueError: PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION <x> is not supported` before your app
  draws anything. The only other legitimate value is `python`, and only as a deliberate A/B.
- **A successful parse is not authentication, and `except DecodeError` is not enough.**
  protobuf's wire format is not self-describing enough to reject every blob: fed batches of
  2,000 random 64-byte payloads, a three-field message rejected almost all of them with
  `DecodeError` but **accepted between none and five per batch** as a valid-looking message
  (ten batches: 1, 2, 1, 0, 1, 3, 1, 5, 2, 1), so the rate is small, non-zero and not
  something to plan around. Truncation is the same story — of the 21 truncations of a
  22-byte message, 17 raised and four (the ones landing on a field boundary) parsed. And two
  unrelated schemas whose field numbers and wire types line up decode each other's payloads
  without complaint: a `{qty: 1 int32, label: 2 string}` message read `{id: 9, name: "hi"}`
  back as `{'qty': 9, 'label': 'hi'}`. On top of that, `DecodeError` is **not** a `ValueError`
  subclass, and an invalid-UTF-8 string field raises `DecodeError` under upb but plain
  `UnicodeDecodeError` on the pure-Python path — so a handler written against one crashes the
  app on the other. Catch broad `Exception` around any parse of bytes your app did not produce
  (an unhandled exception in a Flet handler sends `SESSION_CRASHED`), carry the message type
  out of band rather than inferring it from a successful parse, and put a version or magic
  field in the schema if the bytes came from outside.
- **Map fields serialise to different bytes in every process.** Five separate interpreters
  encoding the same 30-entry `map<string, int32>` gave five different SHA-256 digests, while
  `SerializeToString(deterministic=True)` gave one digest every time. `PYTHONHASHSEED=0` does
  not pin it — the order is upb's, not Python's — and within a single process the plain calls
  *are* stable, which is exactly what hides the bug in testing. Never hash, sign, byte-compare
  or content-address a serialised message without `deterministic=True`; upstream is explicit
  that [serialization is not canonical](https://protobuf.dev/programming-guides/serialization-not-canonical/)
  even then. Messages with no map fields did re-serialise byte-identically after a parse in
  every check here, but that is an observation, not a guarantee.
- **Build your message classes once, at import.** Messages from two different
  `DescriptorPool`s never compare equal even when their content and their bytes are identical
  — `==` compares descriptor identity — so rebuilding the schema per call gives an app whose
  equality checks silently always fail. Verified identical under both implementations.
  `descriptor_pool.Default()` is the other half of the same problem: it rejects a second file
  registered under a name it already holds unless the content is byte-identical, and the
  error type differs by implementation (`TypeError: … duplicate file name` under upb,
  `DescriptorDatabaseConflictingDefinitionError` on the fallback). Give runtime-built schemas a
  namespaced `FileDescriptorProto.name`, or keep them in a private `DescriptorPool()`.
- **A pool does not know a well-known type until something registers it.** Referencing
  `.google.protobuf.Timestamp` from a runtime-built schema fails with `TypeError: … Depends on
  file 'google/protobuf/timestamp.proto', but it has not been loaded` under upb — and that is
  true of `descriptor_pool.Default()` as well, not only of a private pool, because a `_pb2`
  module registers itself with `Default()` when it is *imported*. Two fixes: `import
  google.protobuf.timestamp_pb2` and add to `Default()`, or copy the descriptor into your own
  pool first — `timestamp_pb2.DESCRIPTOR.CopyToProto(fdp); pool.Add(fdp)`. Both verified. (The
  pure-Python fallback resolves the dependency on its own, so this is one more thing that only
  breaks once the extension is doing its job.)
- **Generated code from a newer protoc than the runtime refuses to import.** protoc's major
  version maps to the runtime's minor — `google/protobuf/runtime_version.py` in the wheel
  declares the `OSS_MAJOR` and `OSS_MINOR` it will accept — and every `_pb2.py` calls
  `runtime_version.ValidateProtobufRuntimeVersion` at import. Gencode one minor ahead of the
  runtime raises `VersionError: Detected incompatible Protobuf Gencode/Runtime versions …
  Runtime version cannot be older than the linked gencode version` — on device, at startup,
  before any of your code runs. Gencode behind the runtime is fine:
  [older gencode is supported, newer is not](https://protobuf.dev/support/cross-version-runtime-guarantee/).
  Generate with a protoc whose major matches this runtime's minor, and regenerate when the
  recipe is bumped.
- **`MessageFactory().GetPrototype(descriptor)` is gone.** Every tutorial that calls it raises
  `AttributeError: 'MessageFactory' object has no attribute 'GetPrototype'` on both
  implementations, and `symbol_database.Default()` has no `GetPrototype` either. Use
  `message_factory.GetMessageClass(pool.FindMessageTypeByName("pkg.Msg"))`.
- **proto3 presence is not what a Python programmer expects.** A plain scalar has no presence:
  `HasField("a")` raises `ValueError: Field … does not have presence`, and a field set to its
  zero value **is not written to the wire at all** — `M(a=0).SerializeToString()` is `b''`, so
  a deliberate zero is indistinguishable from an omission on the far side. Declaring the field
  [`optional`](https://protobuf.dev/programming-guides/proto3/#field-presence) gives it
  presence: `HasField` then answers, and `m.b = 0` serialises to `b'\x10\x00'`. There is also
  no `required` in proto3 — a `LABEL_REQUIRED` field is rejected by upb with
  `TypeError: proto3 fields cannot be required`, while the pure-Python path accepts it
  silently, which is one more reason to keep the extension live.
- **Unknown fields survive a round trip**, on both implementations. A record serialised by a
  schema carrying a field number the reader has never heard of parses fine, keeps the bytes,
  and hands them back when the older class re-serialises — which is what makes adding a field
  to a backend safe for app versions already in the store. Inspect them with
  `google.protobuf.unknown_fields.UnknownFieldSet(msg)`;
  `msg.UnknownFields()` raises `NotImplementedError: unknown field accessor` on upb.
- **proto3 JSON encodes 64-bit integers as strings.** `json_format.MessageToJson` on a message
  with an `int64` field gives `{"ts": "99"}`, and `MessageToDict` gives `'ts': '99'` likewise,
  which surprises anyone diffing protobuf's JSON against a hand-written one.
  `json_format.Parse` accepts both forms and the round trip compares equal. Unknown JSON keys
  are rejected by default (`ParseError: Message type "…" has no field named "nope"`); pass
  `ignore_unknown_fields=True` if the backend adds fields. `Struct` is JSON-shaped in the other
  direction too — integers put into a `Struct` come back as floats.
- **protobuf is the serialisation layer and nothing else — it gives you no transport.** For a
  protobuf-over-HTTP backend, this wheel plus `httpx` or `requests` is the whole story. Real
  gRPC means adding `grpcio`, which is on this index for exactly the slices protobuf has —
  seven on 3.12, six on 3.13 and 3.14 — but is a very different proposition: its Android arm64
  wheel is roughly twenty times this one's download, and it does pull further dependencies of
  its own. And `grpcio-tools` — the protoc plugin that generates `_pb2_grpc.py` stubs — is
  **not** on the index at all (404), so those stubs have to be generated on your build machine,
  which is the same constraint as the schema itself.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is six lines — a name, a version, a build number — with no patches directory, no
`requirements`, no `build.sh` and no `script_env`. That is worth recording as the fact it is.
The sdist has **no `pyproject.toml`**: a legacy `setup.py` globs the 75 vendored C files
(`google/protobuf/*.c`, `python/*.c`, `upb/**/*.c`, `utf8_range/*.c`) into a single
`Extension`, and that cross-compiles to all nineteen slices on forge's stock support with
nothing added. So the day this recipe needs a patch or a build requirement, suspect the
toolchain or an upstream restructuring — an added `[build-system]` table especially — before
reaching for one.

Why [Install](#install) carries no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry: the wheel
is 61 entries — 55 `.py`, one `.so` and five `dist-info` files — with no data file, no `.pyi`
and no `py.typed`. Grepped across all 55 modules, `__file__`, `ctypes`, `importlib.resources`,
`pkg_resources`, `subprocess` and `platform.system()` have **zero** occurrences between them;
the one line of that family anywhere in the wheel is `pkgutil.extend_path` in
`google/__init__.py`, which declares `google` a namespace package and is harmless under
`zipimport` — the mechanism Android's site-packages uses — as checked by importing the package
out of a zip on `sys.path`.

`google/_upb/` contains **only** the extension; there is no `__init__.py` in it. Flet 0.86
relocates every ABI-tagged extension into `jniLibs`, leaves a `.soref` marker behind, and
synthesises an `__init__` for any directory holding a `.py`, `.pyc` or `.soref`, so the package
still resolves. Read off the APK the [`runtime-schema`](examples/runtime-schema) example
produces, that is exactly what happens: `lib/<abi>/libgoogle-_upb-_message.so` for all three
ABIs, a 26-byte `google/_upb/_message.soref` naming it inside `assets/sitepackages.zip`, and
the empty `google/_upb/__init__.py` synthesised beside it. On iOS the extension needs no fixing
up at all — every slice is already `MH_DYLIB`, so forge's `MH_BUNDLE` conversion never engages
— and serious_python moves it whole into
`Frameworks/google._upb._message.framework` with a `_message.fwork` shim left in its place.

The build matrix is nineteen wheels at the same build number: ten Android — arm64-v8a,
armeabi-v7a and x86_64 on each of 3.12, 3.13 and 3.14, plus a legacy 32-bit `android_24_x86` on
3.12 only — and nine iOS (device, arm64 simulator and x86_64 simulator on each of the three).
`Requires-Python` in the wheel is upstream's `>=3.10`, so the floor a consumer actually hits is
Flet's.

### Upgrade hazards

- **The gencode/runtime pairing.** protoc major ↔ runtime minor, and the exact `VersionError`
  text, which app authors hit at import on device. Bumping the recipe invalidates every
  `_pb2.py` a consumer generated against the old one, so the bump note has to say so.
- **The bare-versus-pinned resolve.** The [Install](#install) warning depends on which version
  PyPI is on relative to this index; its wording should be re-checked rather than assumed.
- **Upstream publishing a mobile-tagged wheel** would remove this recipe's reason to exist.
  Today it publishes `cp310-abi3` wheels for macOS, manylinux and Windows and a `py3-none-any`
  wheel for everything else — and that universal wheel is precisely what makes an unpinned
  `protobuf` resolve wrong for mobile.
- **The behavioural quotes**, because this page reproduces them and app code will match on
  them: the `VersionError` and `ValueError` texts, `Field … does not have presence`,
  `proto3 fields cannot be required`, `duplicate file name`, and the `pyext` `ImportError`.
  That `DecodeError` is still not a `ValueError` subclass belongs with them.
- **The map non-determinism and the two-pools-never-equal behaviour.** Both would corrupt data
  quietly if they moved, and both underpin a [Things to know](#things-to-know) bullet.

### Re-verification checklist

- **That the extension is still in the wheel and still the live implementation.** One `.so` per
  wheel, `google/_upb/_message.*`, and `api_implementation.Type() == "upb"` on an install of
  the built wheel. Everything above [Things to know](#things-to-know) is a claim about that one
  file.
- **That a pinned `protobuf` still resolves from this index, on every slice.** Re-run one
  `pip download --only-binary :all: --platform <tag> --python-version <ver> --extra-index-url
  https://pypi.flet.dev protobuf==<version>` per target and read the filename that comes back.
  All eighteen combinations — Android arm64-v8a, armeabi-v7a and x86_64 plus iOS device and
  both simulator slices, on 3.12, 3.13 and 3.14 — must come back with this index's wheel.
  Re-run the **bare** `protobuf` resolve at the same time.
- **`Requires-Dist` still empty and the file count still 61.** Either a new dependency or a new
  data file would put both the [Install](#install) snippet and the no-`extract_packages`
  reasoning back in question.
- **The linkage lists and the filetype.** Android `DT_NEEDED` is `libm.so`,
  `libpython3.<minor>.so`, `libdl.so` and `libc.so` with no `libc++_shared`, and every
  `PT_LOAD` segment must keep 16 KB alignment for Android 15; armeabi-v7a and the legacy `x86`
  slice must stay genuine `ELF32`/`ARM` and `ELF32`/`i386` builds rather than stubs. iOS must
  stay `MH_DYLIB`/`NOUNDEFS` (`otool -hv`) with only `@rpath/Python.framework/Python` and
  `/usr/lib/libSystem.B.dylib` in `otool -L`. Anything new in either list is a runtime
  dependency [Install](#install) does not mention, and an `MH_BUNDLE` slice would need forge's
  conversion. Open all nine iOS slices, not one: their `LC_BUILD_VERSION` `minos` already
  disagrees with the `ios_13_0` in their filenames — 13.0 on the device and x86_64-simulator
  slices, 14.0 on all three arm64-simulator ones.
- **The GIL claim behind [Threading](#threading).** `PyEval_SaveThread`,
  `PyEval_RestoreThread`, `PyGILState_*` and `pthread_create` must all stay absent from the
  undefined symbols of the extension. Of the arm64-v8a slice's 161 undefined dynamic symbols
  only 33 are outside CPython's own API today, and every one is bionic libc or libm (`malloc`,
  `memcpy`, `qsort`, `strtod`, `snprintf`, `getauxval`, `__system_property_get`,
  `memfd_create` and similar); none is C++-mangled.
- **The extension filename spelling per Python.** The 3.12 Android wheels carry a bare
  `cpython-312` tag where 3.13 and 3.14 carry the full platform triple. Both work today; the
  reason to check is that Android's packaging keys on that tag, so an *untagged* `.so` would be
  a silent `ModuleNotFoundError` on device, and [Other considerations](#other-considerations)
  tells consumers to match on the prefix.
- **Size.** Re-measure compressed and unpacked from the built wheels; the figures in
  [App size](#app-size) are decimal, so a `du -h` re-measurement will disagree with them by
  about 2%. The extension was 427,392 bytes on the Android arm64-v8a slice against 469,736 on
  the iOS device slice at 3.14, so iOS carrying roughly 10% more native code for the same
  Python is expected rather than a regression.
- **The measurements**, all of them: the timing table, the byte ratio, the GIL speedup with its
  `hashlib` control, the import cost and the size range. Every absolute number above is a
  desktop number that a phone will not reproduce — the *ratios* are the transferable part, and
  the example exists to produce the device figures.

### Coverage gaps

**No on-device run backs anything above the Build notes.** protobuf is not in the workflow's
`SMOKE_TEST_PACKAGES` (`lru-dict`, `pydantic-core`, `numpy`) and `git log -- recipes/protobuf`
shows no recipe-specific work since the repo-wide normalisation commits. Every behavioural
claim came off a desktop install of the exact recipe version, and the bridge that licenses that
is narrow but real: all 55 `.py` files are byte-identical (`shasum -a 256`) between the Android
wheel and the iOS wheel, and the 54 of them under `google/protobuf/` are byte-identical to
upstream's PyPI `py3-none-any` and `cp310-abi3` macOS wheels of the same version — the mobile
wheels add only `google/__init__.py`, which upstream's wheels omit. It is the code that carries
across and not the metadata: `METADATA` matches between the two mobile wheels and differs from
upstream's, which forge regenerates (`Metadata-Version` 2.4 against upstream's 2.1). What none
of that establishes is that the *extension* loads on a phone, which is the entire point of the
recipe. The [`runtime-schema`](examples/runtime-schema) example is the missing evidence, and
its header line is built to be the thing you read off the screen.

`tests/test_protobuf.py` is two docstringed functions with no version assertion, so it already
matches the repo's test conventions — but **neither test would fail if the extension never
loaded**. Both pass unchanged under `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`, which was
checked; `test_well_known_timestamp`'s docstring claims it depends "on the C++ extension being
correctly loaded", and it does not. (The docstring also calls upb a C++ implementation. It
links no C++ runtime: no `libc++_shared` in `DT_NEEDED` and no mangled C++ symbols among the
undefined ones.) One line — `assert api_implementation.Type() == "upb"` — would turn the
on-device run into the proof this page needs, and is the single highest-value change to this
recipe.

The nineteen wheels were not produced in one pass: every 3.12 slice is dated 2026-06-08 and
the 3.13 and 3.14 slices 2026-06-11, except **both** armeabi-v7a slices — 3.13 and 3.14 alike
— dated 2026-06-29. Other recipes in this repo built in the same window carry the same three
dates, so it is a property of this repo's build history rather than of protobuf.
