# pymongo

[`pymongo`](https://pymongo.readthedocs.io/) is the official MongoDB driver. Installing it
gives three importable packages: `pymongo` itself, `gridfs`, and
[`bson`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html) — the encoder for
[BSON](https://bsonspec.org/spec.html), MongoDB's binary document format, with a C accelerator
compiled into this wheel.

On a phone, `bson` is the half that needs nothing else present. BSON is a *typed* format: a
document is a `dict` whose values keep their types across a write and a read — object ids,
exact decimals, 64-bit integers, timestamps, raw binary — so a file of encoded documents is a
usable local store with no database process, no schema and no server anywhere.

## Install

Add pymongo to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pymongo",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bson-store`](examples/bson-store) — keeps typed documents in a file in app storage and
  reports, field by field, what survives the round trip.

## Usage in a Flet app

Encode a document, append it to a file in the app's own storage, and read the file back:

```python
import bson, os
from bson import Decimal128, ObjectId

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "readings.bson")

with open(path, "ab") as handle:
    handle.write(bson.encode({"_id": ObjectId(), "celsius": Decimal128("21.50")}))

with open(path, "rb") as handle:
    docs = list(bson.decode_file_iter(handle))
```

Every encoded document carries its own length, so a file of them needs no header, separator or
index and appending is one `write` — the layout
[`mongodump`](https://www.mongodb.com/docs/database-tools/mongodump/) produces.
[`decode_file_iter`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.decode_file_iter)
walks such a file one document at a time, so memory tracks the largest document rather than the
store;
[`decode_all`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.decode_all)
does the same for `bytes` already in memory, and
[`decode`](https://pymongo.readthedocs.io/en/stable/api/bson/index.html#bson.decode) takes one.

### Storage

Put a store the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
as above. From Flet 0.86.0 that durable directory is also the process working directory, so a
relative write lands there; naming the variable still makes the intent clear. Use
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for an index you can rebuild and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch; a document file shipped with the app belongs in the
[assets directory](https://flet.dev/docs/cookbook/assets).

Append whole documents: build the `bytes` first and hand them to one `write`. A file whose last
document was cut short raises `bson.errors.InvalidBSON` when the reader reaches it — `objsize
too large` at nearly every offset, `cut off in middle of objsize` or `not enough data for a BSON
document` when the write stopped inside a length prefix. `decode_file_iter` raises it mid-walk,
so everything before the tear has already been handed over and only the torn document is lost,
while `decode_all` on the same bytes returns nothing at all. That is the whole of the recovery
story, so a store that has to survive being killed mid-write wants a database instead;
[`apsw`](../apsw) and [`duckdb`](../duckdb) have recipes here.

### Threading

Encoding and decoding are thread-safe and keep no shared state, but they hold the GIL: four
threads each decoding the same document took 4.03x the wall clock one thread needed for a
quarter of that work, and a 4 MB document gave 4.09x, so the C decoder does not hand the GIL
back for a large copy either (desktop, CPython 3.12). Moving a large scan into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) therefore
buys a responsive handler loop rather than throughput. Catch exceptions inside the worker and
finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

`run_thread` uses a thread pool, so two quick taps can overlap. Serialise appends to one file
behind a module-level `threading.Lock`, or two half-written documents interleave and the next
read hits the error above.

### Documents and types

A document is a `dict` with `str` keys. What comes back is not always what went in:

| In | Back out |
| --- | --- |
| `ObjectId` | `ObjectId` |
| `datetime` | `datetime`, truncated to whole milliseconds, and naive unless you ask otherwise |
| `Decimal128` | `Decimal128` |
| `int` | `int` inside the signed 32-bit range, `Int64` outside it — `-2³¹` returns `int`, `-2³¹ - 1` returns `Int64`, a subclass of `int`, so it compares equal |
| `Binary(data, subtype)` | `bytes` for subtype 0, otherwise `Binary` with the subtype kept |
| `tuple` | `list` |

[`Decimal128`](https://pymongo.readthedocs.io/en/stable/api/bson/decimal128.html) is the reason
to reach for BSON over JSON for money or measurements: an exact decimal, so `0.1` stays `0.1`
instead of becoming a binary float, up to 34 significant digits — past that its constructor
raises `decimal.Inexact`. A datetime, by contrast, is a count of UTC milliseconds and nothing
else, so microseconds are gone and the value decodes *naive*, which `astimezone()` then
misreads as local. Ask for the zone back:

```python
options = CodecOptions(tz_aware=True, tzinfo=datetime.timezone.utc)
doc = bson.decode(blob, codec_options=options)
```

The same
[`CodecOptions`](https://pymongo.readthedocs.io/en/stable/api/bson/codec_options.html) carries
`document_class` and `uuid_representation`, and every encode and decode entry point accepts one.

### Talking to a server

A [`MongoClient`](https://pymongo.readthedocs.io/en/stable/api/pymongo/mongo_client.html)
against a remote deployment does work from a phone — Flet's Android build sets
`android.permission.INTERNET` by default — but it is usually the wrong shape for an app. The
connection string is a database credential sitting in a payload that anyone holding the device
can read, and a pooled connection is a poor match for a process the OS suspends whenever the
user switches away. Put an HTTPS API in front of the database and keep the driver behind it. If
you do connect directly, a short `serverSelectionTimeoutMS` and an explicit `tlsCAFile` (below)
are the two options that most change what you see.

### App size

A wheel is about 0.76 MB compressed and 3.0 MB unpacked — 2.95 MB on `armeabi_v7a`, and 0.82 MB
compressed for the x86_64 simulator wheel, 3.24 MB unpacked, which carries a device build beside
the simulator one. Compiled code is a small slice: 91 KB on `armeabi_v7a`, 123–125 KB on the
other Android ABIs, 229 KB on iOS. The rest is Python, and 2.36 MB of the 2.99 MB is the driver,
which ships near-identical synchronous and asynchronous copies of itself at 0.81 and 0.82 MB.

Leave the 191 KB of C source in the wheel alone: serious_python's package step deletes `**.c`
and `**.h` from site-packages already, and `flet build` runs that step by default
(`cleanup.packages` defaults to `True` in flet_cli 0.86.5). The lever worth pulling is the
driver, for an app that only ever reaches for `bson` — `import bson` loads nothing out of
`pymongo` or `gridfs`:

```toml
[tool.flet.cleanup]
package_files = ["pymongo", "gridfs"]
```

Bare directory names, the shape serious_python's own `bin` entry uses, matched against
site-packages entries after compilation — `**/pymongo` matches nothing there, so keep the name
bare. Running that matcher over a staged tree took both directories and left a `bson` that
still encodes and decodes every type above; no APK here was built from it, so check the real
one with `unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l
/tmp/sp.zip | grep -c pymongo/`.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. These figures describe the package payload, not the exact amount
added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's own wheel. The API is identical and the C accelerator is
present in both, so BSON behaviour carries over — the surrounding platform does not. Validate
anything that opens a socket on a device or emulator/simulator, not only at your desk.

## Things to know

- **Do not `pip install bson`.** A different, unrelated project of that name publishes its own
  top-level `bson` package, and the two overwrite each other file by file, so installation
  order decides which one you get. With that distribution installed last, `bson.encode` is gone
  and `import pymongo` fails at `ImportError: cannot import name 'SON' from 'bson'`; install it
  first and pymongo works while the other package is quietly broken instead. Everything here
  comes from `pymongo` alone.

- **A native `uuid.UUID` will not encode.** `bson.encode({"u": uuid.uuid4()})` raises
  `ValueError: cannot encode native uuid.UUID with UuidRepresentation.UNSPECIFIED`. Wrap it with
  [`Binary.from_uuid(value)`](https://pymongo.readthedocs.io/en/stable/api/bson/binary.html),
  which gives subtype 4 and decodes back with `.as_uuid()`, or configure
  `uuid_representation` and pass those options when reading as well as writing.

- **What `encode` refuses, it refuses loudly.** An integer past the *signed* 64-bit range raises
  `OverflowError: MongoDB can only handle up to 8-byte ints`, so `2 ** 63 - 1` encodes and
  `2 ** 63` does not; a non-string key, a key containing a NUL byte and a `set` each raise
  `InvalidDocument`. Store an out-of-range integer as a `Decimal128` or a string, and convert a
  `set` to a list yourself so you choose the ordering.

- **The 16 MB limit is the server's, not the file's.** `bson.encode` produced a 17.8 MB document
  here without complaint and a file of such documents read back normally; it is `MongoClient`
  that refuses to put one on the wire. A local store is bounded by the BSON length prefix
  instead, a signed 32-bit count.

- **TLS to a public server needs the CA bundle handed over.** Given no `tlsCAFile`, pymongo
  builds its context and calls `ctx.load_default_certs()`, which on a desktop finds the system
  trust store. Nothing in a Flet mobile runtime provides one, and the failure lands at handshake
  as a verification error that reads like a server problem. A bundle is already in your payload,
  since `certifi` arrives with Flet, so pass `MongoClient(uri, tlsCAFile=certifi.where())`. This
  has **not** been settled by a handshake on a device here — it is read out of pymongo's context
  construction — so treat that argument as the cheap way to make the question moot.

- **`bson.json_util` is the bridge to anything that only speaks JSON.**
  [`json_util.dumps`](https://pymongo.readthedocs.io/en/stable/api/bson/json_util.html) writes
  MongoDB Extended JSON — `{"$oid": …}`, `{"$date": …}` — and `json_util.loads` reads it back
  into the same BSON types, with `Int64` the one that returns as a plain `int`, so a document
  survives a log line or an HTTP body intact.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version and a build number, and there are no patches. Both extensions
(`bson._cbson`, `pymongo._cmessage`) are plain C in the sdist — no external library, no
configure step, no code generation — so the default Python-package path builds them as they
are. Upstream's hatchling hook shells out to `_setup.py build_ext -i` and force-includes the
results, invisibly to forge.

### Upgrade hazards

**A failed extension build is a warning upstream, not an error.** `_setup.py` wraps `build_ext`
in a `custom_build_ext` that catches every exception and downgrades it to a `UserWarning` unless
`PYMONGO_C_EXT_MUST_BUILD` is set in the environment, and the hatch hook marks the wheel
platform-specific regardless. A cross-compile that stops working therefore produces a green
forge run and a correctly tagged wheel with no `_cbson` in it, silently dropping every consumer
onto the pure-Python encoder. Blocking the `bson._cbson` import on a desktop (CPython 3.12) put
that fallback at 17–26% of the compiled encode rate and 11–22% of the compiled decode rate for
documents of a hundred to a few hundred bytes — four to nine times slower, closing to about 65%
only for a document that is one 64 KB binary. Set that variable in `build.script_env`, or
assert `bson.has_c()` on device, before believing a bump.

### Re-verification checklist

- **C accelerator present:** confirm `bson/_cbson*.so` and `pymongo/_cmessage*.so` are in each
  wheel *and* that `bson.has_c()` is true on device. This is the one regression that does not
  announce itself.
- **Type round trips:** re-check the datetime truncation, the subtype-0 `Binary` to `bytes`
  demotion, the `int`/`Int64` boundary and the `Decimal128` digit limit. The table above states
  each of them exactly, and a minor release can move any of them.
- **Android package layout:** test from zipped site-packages. Both `topology.py` modules read
  `Path(__file__).parent` at import and `pymongo/daemon.py` calls `os.path.realpath(__file__)`,
  so a change in how `__file__` behaves there surfaces as an import failure, not a build one.
- **Runtime dependencies:** `dnspython` is the only required one, and it is pure Python. A
  release that adds a compiled dependency needs that second recipe before this one is usable.
- **Size:** re-measure from the resulting wheels rather than scaling these figures.

### Coverage gaps

The device tests cover a plain-dict round trip, `ObjectId`, and constructing a `MongoClient`
with `connect=False`. They do not check `bson.has_c()`, the typed values the sections above make
claims about (`datetime`, `Decimal128`, `Binary`, `Int64`), any file-backed store or
`decode_file_iter`, `gridfs`, TLS setup, or a connection to a real server. The `bson-store`
example exercises several of those, but only when somebody builds it.
