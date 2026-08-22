# msgpack

[`msgpack`](https://github.com/msgpack/msgpack-python) is the reference Python binding for
[MessagePack](https://msgpack.org/), a binary serialisation format shaped like JSON — maps,
arrays, strings, integers, floats, booleans, null — plus the two things JSON does not have: a
**binary** type that carries raw bytes without base64, and an **extension** type that lets you
put your own tagged values on the wire. The import surface is small:
[`packb`/`unpackb`](https://msgpack-python.readthedocs.io/en/latest/api.html#msgpack.packb),
`pack`/`unpack` for file objects, `Packer`/`Unpacker` for streams, `ExtType`/`Timestamp` for
the two tagged types, `load`/`loads`/`dump`/`dumps` aliases and the exception classes.
Underneath them is a Cython extension, `msgpack._cmsgpack`, and a pure-Python implementation,
`msgpack.fallback`, that `__init__.py` silently substitutes when the extension will not
import — see [Things to know](#things-to-know), because that substitution is the one failure
this package never reports.

**You almost certainly already have it.** Flet encodes every control message with MessagePack,
so `flet` 0.86.5 declares `msgpack>=1.1.0` in its metadata with no environment marker and the
wheel is in your build whether or not you name it. Importing msgpack in your own code therefore
costs **zero additional bytes of app payload**: the extension is already `dlopen`ed, and by the
time `main(page)` runs the module object is already in `sys.modules`.

[`ormsgpack`](../ormsgpack) writes the same wire format from Rust and packs faster. It also
packs a dataclass, a `datetime`, a `UUID` or an `Enum` with no `default=` hook — but those extra
types are *converted* rather than preserved, so a dataclass comes back a `dict` and a `UUID`
comes back a `str`. Reach for this package when a round trip has to hand back the types it was
given, and for the per-call keyword options the sections below turn on and off.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "msgpack",
]
```

Name it if you import it, so your app keeps a dependency it actually uses even if Flet's
protocol ever stops needing one.

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.android]` /
`[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has a desktop
wheel for every host you would build from.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`pack-compare`](examples/pack-compare) — msgpack against json on the same objects: bytes,
  milliseconds, a type-fidelity table, and what a flipped bit does to each.

## Usage in a Flet app

```python
import flet as ft
import msgpack

blob = msgpack.packb({"id": 7, "value": 1.5, "thumb": b"\x89PNG"})
doc = msgpack.unpackb(blob)
assert msgpack.Packer.__module__ == "msgpack._cmsgpack"  # not the slow fallback

label = ft.Text(f"{doc['id']} · {len(doc['thumb'])} bytes")  # thumb is still bytes
```

That assertion is the line to keep in real code. `msgpack/__init__.py` is
`try: from ._cmsgpack import … except ImportError: from .fallback import …`, the two
implementations produce byte-identical output, and nothing downstream can tell them apart —
only the clock can, and the difference is roughly fifteenfold.

### Storage

**msgpack opens nothing by itself.** No file, no socket, no environment lookup, on any published
slice; the Python layer imports only `os`, `sys`, `struct`, `datetime`, `collections` and `io`.
So the file is yours to place, and the choice is the usual Flet one:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for something derived, and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch.

**`packb` is for one document; a log of many needs `Packer` and `Unpacker`.** Concatenated
documents are a first-class use of the format, and both halves stream:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "records.msgpack")
packer = msgpack.Packer()
with open(path, "wb") as handle:
    for record in records:
        handle.write(packer.pack(record))

with open(path, "rb") as handle:
    for record in msgpack.Unpacker(handle, max_buffer_size=64 * 1024):
        consume(record)
```

Measured on desktop over 5,000 copies of the record the [example](examples/pack-compare)
flips bits in — `{"id": f"rec-{i:05d}", "value": 1.5 + i / 8.0, "tags": [f"tag-{i % 7}"]}` —
the stream is 205,000 bytes, written in 0.9 ms and read back in 1.1 ms, equal to the originals.
One-shot `packb` of the same list is 205,003 bytes — three bytes more, because that is one array
rather than 5,000 documents, and it must be held whole in memory at both ends. `max_buffer_size`
bounds what the reader holds; 64 KiB streamed all 5,000 records fine.

**A truncated record stream ends silently.** Cutting that file at 102,517 bytes, part-way
through a record, and feeding the front to `Unpacker` yielded 2,500 complete records and then
the iterator simply stopped — no exception, no partial record, nothing to catch, and the 17
bytes of record 2,501 were swallowed. (`unpackb` on the same bytes raises `ExtraData`, but only
because it decodes the first document and objects to the other 2,499.) A phone's filesystem is
exactly where a half-written file happens, so write a count or a digest beside the data and
check it on read; nothing in the format will do it for you.

### Threading

**The extension never releases the GIL.** There is no `Py_BEGIN_ALLOW_THREADS` anywhere in the
binding, on any published slice. Confirmed by measurement on desktop, with a pure-Python counter
thread running beside the work and its rate given as a percentage of an idle window, work
repeated to fill a 0.6 s window in every case. Controls first: `time.sleep` (releases) 90–100%,
`zlib.decompress` of a 48 MB blob — a C extension that does release it — 95–125%, and
`math.factorial(60000)` (holds) 16–19%. Then, over a 120,000-record list, `msgpack.packb`
**23–30%** and `msgpack.unpackb` **17–24%**; `json.dumps` and `json.loads` were 10–15% on the
same harness. Squarely in the holds camp, and the zlib control is what shows the measurement
could have said otherwise.

That does not make msgpack a bad candidate for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — it makes
the thread useful for the *rest* of the job. Encoding is fast enough that it is rarely what
blocks you: 1.6 MB of byte blobs packed in 0.08 ms and 259 KB of records in 0.71 ms on desktop.
The work worth moving off the UI thread is the file read, the HTTP round trip or the transform
around the encode, and the encode simply rides along.

**One call on a shared object is safe today, because the GIL makes it atomic.** Measured on
desktop: eight threads pushing 200 documents each through one shared `Packer` completed 1,600 of
1,600, all decodable and correct, on 5 of 5 runs with zero exceptions; six threads feeding one
shared `Unpacker` produced 1,200 of 1,200 correct objects on 3 of 3. Read that as a property of
the interpreter rather than a guarantee from the library — upstream's 1.2.0 added
`@cython.critical_section` to the packer's methods, which is what preparing for a free-threaded
build looks like, and every Python Flet ships on mobile has the GIL. A *sequence* of calls
against one `Packer(autoreset=False)`, which accumulates into a shared buffer, is a different
matter and needs a `threading.Lock` around the whole sequence.

The Flet-side rules apply as everywhere else, and the [example](examples/pack-compare) shows
both. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try`/`except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no log,
no dialog and no crash.

### Size and speed against json

Measured on a desktop (Apple M4, macOS 26.6, CPython 3.14.6), best of seven, against
`json.dumps(…, separators=(",", ":")).encode()` on the same objects:

| payload | msgpack | json | pack ms | dump ms | unpack ms | load ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2,000 API records | 259,089 | 338,487 | 0.71 | 1.95 | 1.30 | 1.61 |
| 400 × 25 float grid | 91,203 | 182,388 | 0.10 | 2.30 | 0.14 | 1.29 |
| 4,000 short strings | 44,003 | 52,001 | 0.05 | 0.13 | 0.05 | 0.10 |
| 200 × 8 KiB byte blobs | 1,639,034 | 2,185,439 | 0.08 | 4.08 | 0.04 | 2.98 |

Numbers, not text, is where the format earns its place — halving a float grid — and bytes are
where it stops being a size argument and becomes a correctness one: json cannot hold `bytes` at
all, so that last row is msgpack against base64-then-json, and msgpack's encoding of 1,638,400
bytes of payload is 1,639,034 bytes total, an overhead of 634. Size is not the finding worth
acting on, though: **type fidelity is**, and both formats will hand you back an object that is
not what you gave them, in opposite directions. The first two bullets of
[Things to know](#things-to-know) are that story.

**An emulator and a simulator answered on 2026-08-20, and only half of what they said is
portable.** Both at CPython 3.14.6, on the example's `api records` document: an arm64-v8a
Android 14 emulator and an iPhone 16 simulator produced *identical* byte counts, identical to
the desktop figures above — msgpack 259,089 against json's 338,487, **23% smaller** — because
the encoding is deterministic, and both formats decoded back to an equal object. That half
carries to a real phone unchanged. The clock does not. Packing took 0.76 ms against json's 2.52
on the simulator, and 2.52 ms against json's 19.20 on the emulator, so the same comparison reads
as 3× on one and 7.6× on the other; do not quote either ratio, because an emulator's CPU is not
the phone's. What is portable is the direction: msgpack is ahead on both halves, and further
ahead packing than unpacking (1.67 ms against 2.12 on the simulator, 14.41 against 24.03 on the
emulator) — worth knowing if your app decodes far more often than it encodes.

### App size

Approximately 68–86 KB compressed and 156–294 KB unpacked per architecture, most of it the
single `_cmsgpack` extension and `fallback.py` the next largest entry. An app bundle, split APKs
or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
levers worth pulling for other packages rather than for this one; every ABI `flet build` asks
for is published. The one lever that does apply here is dropping the pure-Python fallback, which
is roughly a quarter of the unpacked payload — see the `compile.packages` bullet in
[Things to know](#things-to-know), including why it is a trade rather than a free win.

### Other considerations

**Desktop and device can be on different versions unless you pin.** PyPI publishes releases this
index has not built yet, so a bare `msgpack` requirement can resolve one version for `flet run`
on your laptop and an older one for `flet build`. The differences are not always cosmetic: 1.2.0
raised the packer's recursion limit from 511 to 1024 and annotated the packer's methods with
`@cython.critical_section`. Pin both sides — as the [`pack-compare`](examples/pack-compare)
example does — if either matters to you.

**Identify the implementation by `msgpack.Packer.__module__`, never by a file path.** With
Flet's package compilation on, the mobile default on Android and iOS alike, the four Python
modules ship as bytecode with no source beside them, and a native extension may report no
`__file__` at all on Android. `__module__` answers on both platforms and answers the question
that matters, which is whether the C extension or the fallback is running.

## Things to know

- **Two options silently swap `bytes` and `str`, and they are one keyword away from symmetric
  code.** `use_bin_type` (pack) and `raw` (unpack) both predate msgpack's 2013 split of the old
  `raw` type into `str` and `bin`, and both still exist for talking to implementations that
  never made the split. Measured on 1.1.2:

  | you write | you get back |
  | --- | --- |
  | `unpackb(packb(b"id"))` | `b'id'` — exact |
  | `unpackb(packb(b"id", use_bin_type=False))` | `'id'` — a **str** |
  | `unpackb(packb("id"))` | `'id'` — exact |
  | `unpackb(packb("id"), raw=True)` | `b'id'` — **bytes**, and so is every key and value |
  | `unpackb(packb(b"\xff\xfe", use_bin_type=False))` | `UnicodeDecodeError` |

  The defaults are the modern pair (`use_bin_type=True`, `raw=False`) and are the ones to leave
  alone. The last row is the merciful case: invalid UTF-8 raises rather than mutating. Valid
  UTF-8 does not.

- **Non-string dict keys are where msgpack and json fail in opposite directions.** json coerces
  them to strings and says nothing: `{1: "a"}` comes back `{'1': 'a'}`, `{1.5: "a"}` comes back
  `{'1.5': 'a'}`, `{True: "a"}` comes back `{'true': 'a'}`, and
  `{1: "int key", "1": "str key"}` — two distinct Python keys — round-trips as a **dict of
  length one**. msgpack preserves the key exactly but refuses to hand it back by default:
  `unpackb` raises `ValueError: int is not allowed for map key when strict_map_key=True`. The
  asymmetry is deliberate — packing is allowed, only decoding refuses — and upstream's README
  gives the reason: the default changed to `True` in 1.0 *to avoid hash DoS*, since a decoder
  that will hash arbitrary key types is attackable by whoever sends the bytes. Pass
  `strict_map_key=False` and `{1: "a"}` round-trips exactly, floats included. Neither format can
  carry a tuple key: json raises `TypeError`, and msgpack packs the tuple as an array and then
  refuses the array as a key — `ValueError: list is not allowed for map key when
  strict_map_key=True` by default, and `TypeError: cannot use 'list' as a dict key` once you
  relax that.

- **Integers are 64-bit, and outside that range it raises rather than truncating.** `2**64 - 1`
  and `-2**63` round-trip exactly; `2**64` and `-2**63 - 1` both raise
  `OverflowError: Integer value out of range`. Python's `json` has no such limit — `10**40`
  round-trips fine — so an ID or a hash that fits in json can fail to encode here. It fails
  loudly, which is the right trade, but it fails.

- **Tuples become lists**, in both formats. `use_list=False` gets tuples back from msgpack, but
  it applies to *every* array in the document, not to the ones that started as tuples, so it
  changes the type of your lists instead. There is no round trip that distinguishes the two.

- **`set` needs a `default=` hook**, and so does anything else the format has no type for.
  `packb({1, 2})` raises `TypeError: can not serialize 'set' object` — the same error Flet's own
  serializer produces if you put a set in a control property. A one-liner fixes it:
  `packb(obj, default=lambda o: sorted(o) if isinstance(o, set) else o)`, at the cost of the set
  coming back a list.

- **`datetime` needs a flag on *both* sides, and the naive case raises.** `packb(dt)` alone
  raises `TypeError`. `packb(dt, datetime=True)` writes the standard timestamp extension —
  10 bytes for a microsecond-precision aware datetime — but `unpackb` then returns a
  `msgpack.Timestamp`, not a `datetime`, unless you also pass `timestamp=3`. With both, the
  value comes back identical, microseconds included. A naive datetime raises
  `ValueError: can not serialize 'datetime.datetime' object where tzinfo=None`, so attach a
  timezone before packing. json cannot express a datetime at all.

- **`NaN` and `Infinity` survive msgpack and produce invalid JSON.** msgpack packs them as
  ordinary float64 and gives them back unchanged; `json.dumps` emits the bare tokens `NaN` and
  `Infinity`, which Python's own parser accepts and
  [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) does not — pass `allow_nan=False` and json
  raises instead. If your data can contain them and anything other than Python reads it, this is
  a real difference.

- **Lone surrogates go the other way.** `json.dumps("a\udc80b")` round-trips through
  `json.loads` unchanged; msgpack raises `UnicodeEncodeError: surrogates not allowed` unless you
  pass `unicode_errors="replace"`, which then substitutes `?`. Strings arriving from
  `surrogateescape` decoding are the realistic source.

- **Nesting has a hard ceiling, and it moved in 1.2.0.** On 1.1.2, packing a structure nested
  more than 511 deep raises `ValueError: recursion limit exceeded.` (`DEFAULT_RECURSE_LIMIT` in
  `_packer.pyx`), and unpacking one nested more than 1024 deep raises `msgpack.StackError` —
  **with an empty message**, so print the type, not the text. 1.2.0 raises the packing limit to
  1024. Python's `json` handled 20,000 levels on the same machine and hit `RecursionError` at
  100,000.

- **The exception classes are not what they look like.** `msgpack.PackException` **is**
  `Exception`, `msgpack.PackValueError` **is** `ValueError` and `msgpack.PackOverflowError`
  **is** `OverflowError` — plain aliases, kept for compatibility, so `except PackException:`
  catches everything in the program. Only the unpack side has a real hierarchy
  (`UnpackException` → `BufferFull`, `OutOfData`, and `FormatError`/`StackError`, which also
  derive from `ValueError`). Catch `Exception` around a decode and inspect the type — and catch
  it, because an unhandled exception in a Flet event handler ends the session with a crash
  screen.

- **A damaged frame lies more often than a damaged JSON document.** A length-prefixed binary
  frame carries no checksum, and neither does JSON. 400 single-bit flips per seed, three seeds,
  into the 8,203-byte msgpack frame and the 9,983-byte json encoding of the 200-record document
  the [example](examples/pack-compare) uses: msgpack raised 88/122/111 times and **returned
  wrong data silently 312/278/289 times**; json raised 211/236/216 times and returned wrong data
  189/164/184 times. Neither ever returned the original object — this is a difference of degree,
  not of kind, because a binary encoding has more bits that mean something and text has more
  bits whose corruption produces a syntax error. What a silently wrong decode looks like: a key
  renamed (`'tags'` → `'tagq'`, `'id'` → `'ie'`), or `'rec-00152'` decoding as `'rec-08152'`.
  Store a `hashlib.sha256` beside anything you persist, and check it on read.

- **msgpack is not smaller than json on every value.** A lone float costs 9 bytes against json's
  3 (`1.5`); `2**32` costs 9 against 10, so the crossover is nearby. Where it wins on scalars is
  the small stuff — `None`, `True` and any int from −32 to 127 are one byte each, against 4, 4
  and up to 3 — and the empty list and empty dict are one byte each against two. Strings cost
  one framing byte up to 31 characters and two up to 255, against json's two quotes. On the
  mixed record payload above that came out at 23% smaller overall; on numbers, 50%.

- **`compile.packages` ships a 42,760-byte pure-Python packer you will never run.**
  `fallback.py` is 32,390 bytes of source and 42,760 as `.pyc` compiled by CPython 3.14 (the
  exact figure moves a little with the path `compileall` bakes into `co_filename`), and the four
  modules together come to 54,740 bytes of bytecode beside the extension. That is the price of
  the silent fallback in the next bullet. You can drop it with
  `[tool.flet.cleanup] package_files = ["**msgpack/fallback.pyc"]` — `.pyc`, not `.py`, because
  serious_python's `bin/package_command.dart` runs `compileall` and deletes the `.py` files
  *before* it applies these globs (checked in 4.2.1 and 4.5.1), and the no-slash `**` form is
  the one serious_python uses for its own junk list (`"**.py"`, `"**.pyi"`) — but then a failed
  extension load turns into an `ImportError` at startup instead of a slow app. **That glob has
  not been verified against a build here**; check the result with
  `unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep msgpack`
  before relying on it. The same compilation happens for iOS; the APK is simply the easier
  bundle to open.

- **If the extension fails to load, msgpack keeps working and gets much slower — without telling
  you.** `__init__.py` is `try: from ._cmsgpack import … except ImportError: from .fallback
  import …`, and the environment variable `MSGPACK_PUREPYTHON` selects the fallback outright.
  The two produce byte-identical output (same SHA-256 on a mixed document), so nothing
  downstream can tell them apart; only the clock can. Measured on desktop over 2,000 API
  records: packing 0.71 ms with the extension against 11.60 ms without, unpacking 1.30 ms
  against 19.78 ms — 16× and 15× — which also puts the fallback **behind** `json` on both halves
  (1.95 ms and 1.61 ms). The check is one line, and the [example](examples/pack-compare) prints
  it on screen:

  ```python
  assert msgpack.Packer.__module__ == "msgpack._cmsgpack"
  ```

## Build notes (maintainers)

### Recipe shape

The recipe is `meta.yaml` and nothing else — no patches, no `requirements`, no `script_env`, no
`build.sh`, no `platforms` key, no `excluded_arches`. That shape is earned rather than lucky:
upstream's `setup.py` declares one `Extension` built from a **pre-generated**
`msgpack/_cmsgpack.c` (so Cython is not a build requirement — `build-system.requires` is
`setuptools >= 80.9.0` alone), with no `libraries` outside a `win32` branch, no dependencies,
and `include_dirs=["."]`. There is nothing for a cross build to get wrong. Confirmed against the
wheels: `__init__.py`, `exceptions.py`, `ext.py` and `fallback.py` in the mobile wheel are
byte-identical to the sdist, so the recipe changes nothing about the package.

**This recipe is load-bearing for every Flet mobile app**, not only for apps that import msgpack
themselves: Flet's control protocol depends on it, so a red build here blocks everyone. Treat it
that way when triaging.

One observation from the published wheels that has no other home: **the iOS extensions keep
their build-tree install name**, e.g.
`build/lib.ios-13.0-arm64-iphoneos-cpython-314/msgpack/_cmsgpack.cpython-314-iphoneos.so`, on
every iOS slice. Flet relocates and re-signs these into framework binaries, so this is recorded
as an observation rather than a defect — but it is the first thing to look at if an iOS load
ever fails with a path error.

### Upgrade hazards

- **The 3.12 Android slices name the extension `_cmsgpack.cpython-312.so`, without the platform
  triplet, while 3.13 and 3.14 use the full `_cmsgpack.cpython-31X-<triplet>.so`.** Both carry
  the `.cpython-*` tag serious_python's `jniLibs` relocation keys on, so both work, but the
  untriplet-ed form means forge's foreign-arch drop (the `\.cpython-\d+-<triplet>\.so$` filter
  in `src/forge/build.py`) cannot tell the four 3.12 Android slices apart by filename. Currently
  harmless — the `e_machine` of every slice was checked and each is the right architecture — but
  it is the failure mode to look for first if a 3.12 Android wheel ever imports on one ABI and
  not another.
- **Upstream is preparing for free threading.** 1.2.0 added `@cython.critical_section` to the
  packer's methods. The first `Py_BEGIN_ALLOW_THREADS` to land would invert
  [Threading](#threading) and the shared-object measurements under it.
- **1.2.0 moved `DEFAULT_RECURSE_LIMIT` from 511 to 1024** in `_packer.pyx` and `fallback.py`,
  and both limits are quoted with a version attached above.
- **Upstream publishing its own mobile wheels** would remove this recipe's reason to exist. The
  releases inspected here carry no Android tag, no iOS tag and no `py3-none-any` tag, which is
  what makes a bare `msgpack` resolve from this index.

### Re-verification checklist

- **That each wheel actually contains a `_cmsgpack*.so`.** This is the one that matters most and
  the one nothing else catches. `setup.py` skips the `Extension` entirely when
  `MSGPACK_PUREPYTHON` is set in the *build* environment, and `__init__.py` then imports the
  pure-Python packer without complaint — so a wheel with no extension at all installs, imports,
  produces byte-identical output and passes every test in `tests/`. It would simply be 15×
  slower on device, which is exactly the kind of regression that ships. `unzip -l` each wheel.
- **That `METADATA` still has zero `Requires-Dist` lines.** Nothing on this page anticipates a
  transitive dependency arriving with the wheel, and upstream declaring one would change every
  consumer's payload without failing anything here.
- **The recursion limits and the `strict_map_key` default**, both quoted in
  [Things to know](#things-to-know) with a version attached because both have moved. Re-read
  `_packer.pyx` and `fallback.py` rather than assuming.
- **The version skew** that [Other considerations](#other-considerations) states. Compare this
  index's newest wheel with PyPI's newest release; if they meet, that paragraph should say so
  instead.
- **The GIL claim behind [Threading](#threading).** Grep the new slices' undefined symbols for
  `PyEval_SaveThread` and `PyEval_RestoreThread`; both must stay absent.
- **The "opens nothing" claim behind [Storage](#storage).** Dump the undefined symbols and
  confirm no `open`, `fopen`, `stat`, `socket`, `connect`, `dlopen` or `getenv` at any binding.
  Everything outside CPython's own API was eight libc symbols on Android (`mem*`, `strrchr`, the
  `__cxa_*` pair and `__register_atfork`) out of 188–191, and the Mach-O equivalents on iOS; the
  only export besides a Cython marker is `PyInit__cmsgpack`.
- **Linkage and extension filename, per slice.** Android `DT_NEEDED` is exactly `libm.so`,
  `libpython3.<minor>.so`, `libdl.so` and `libc.so`, with no `SONAME`, `RPATH`, `RUNPATH` or
  `libc++_shared` — the sources are C, so none of the usual Android C++ staging applies. Every
  `PT_LOAD` segment must keep 16 KB alignment (`0x4000`) for Android 15, and armeabi-v7a and the
  legacy `x86` slice must stay genuine `ELF32` builds. On iOS, `otool -hv` must report `DYLIB`
  and not `BUNDLE`, or the app fails at link time with *Unsupported mach-o filetype*, and
  `otool -L` should add only `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
  The extension name must keep a CPython ABI tag on every slice — an untagged `.so` is a silent
  `ModuleNotFoundError` on Android.
- **Size.** Re-measure compressed and unpacked from the built wheels; the figures in
  [App size](#app-size) are decimal KB. The extension itself was 105,928–159,512 bytes on
  Android against 244,088 on the iOS arm64 device slice, so the same code being markedly bigger
  on iOS is expected rather than a regression.
- **Coverage of the ABIs `flet build` asks for** — Android arm64-v8a, armeabi-v7a and x86_64
  plus all three iOS slices, on every Python built. The legacy `android_24_x86` slice is not one
  of them, which is why the gap there costs a consumer nothing; a gap moving into the other six
  would.

### Coverage gaps

`tests/test_msgpack.py` is two functions — a mixed-type round trip through `packb`/`unpackb`,
and a streaming `Unpacker` over three concatenated documents. **Both pass unchanged on the
pure-Python fallback**, so nothing on device currently proves the extension is the code that
ran. Note that "every Flet app on a phone works, and Flet encodes its controls with msgpack" is
not evidence either — it proves the *module* imports, and the fallback imports too. One line
closes it (`assert msgpack.Packer.__module__ == "msgpack._cmsgpack"`), and it is the
highest-value test this recipe could gain.

After that, in rough order: a `bytes` round trip asserting the result is still `bytes`, which
pins the `use_bin_type` default that [Things to know](#things-to-know) tells people to leave
alone; a `strict_map_key` assertion, which pins the other default; and a `datetime=True` /
`timestamp=3` round trip, since the extension has its own C path for the timestamp type that the
fallback implements separately. Nothing on device exercises the recursion limits, the exception
hierarchy, `Packer(autoreset=False)` or the streaming truncation behaviour described under
[Storage](#storage) — all of that came from desktop inspection.
