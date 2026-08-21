# preshed

[`preshed`](https://github.com/explosion/preshed) is a pair of Cython hash tables keyed by a
64-bit unsigned integer:
[`PreshMap`](https://github.com/explosion/preshed/blob/master/preshed/maps.pyx), which maps
that key to a pointer-sized value, and
[`PreshCounter`](https://github.com/explosion/preshed/blob/master/preshed/counter.pyx), which
counts how often it has seen one; a
[Bloom filter](https://github.com/explosion/preshed/blob/master/preshed/bloom.pyx) comes in the
same package. This is a low-level building block — the layer a vocabulary or a tokenizer is
built on, rather than something you would normally add to an app by hand — and what it buys is
memory: a Python `dict` allocates an `int` object for every key and every value it holds, where
preshed keeps the raw integers in one flat array of cells.

## Install

Add preshed to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "preshed",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`int-map`](examples/int-map) — indexes hashed tokens in a `PreshMap` and prices it against a
  plain `dict`.

## Usage in a Flet app

```python
from preshed.maps import PreshMap

index = PreshMap(initial_size=1 << 16)
index[0x9f2b1c4d5e6f7a80] = 42     # key and value are both unsigned integers
index[0x9f2b1c4d5e6f7a80]          # 42 — and None for a key that was never stored
```

Counting is a second table, whose `inc` reads and writes a cell in one call:

```python
from preshed.counter import PreshCounter

counts = PreshCounter()
counts.inc(0x9f2b1c4d5e6f7a80, 1)
counts[0x9f2b1c4d5e6f7a80]         # 1 — and 0 for a key it has never seen
```

### Storage

Neither table can be pickled or copied: `pickle.dumps(PreshMap())` and `copy.copy(...)` both
raise `TypeError: self.c_map cannot be converted to a Python object for pickling`. Persist the
contents instead — `items()` yields `(key, value)` pairs, and a flat `array("Q")` of them is a
file you can read straight back. Put it in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
import os
from array import array

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "index.bin")
with open(path, "wb") as handle:
    array("Q", [n for pair in index.items() for n in pair]).tofile(handle)
```

Refilling is cheap enough that the file is often not worth keeping: 200,000 inserts took around
20 ms on desktop, and rebuilding from whatever produced the keys avoids a format to migrate.
When you do cache the table, [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
is the right directory, since the app can always regenerate it.

### Threading

**`PreshMap` is the one class that is meant to be shared.** `maps.pyx` takes Cython critical
sections around the table, and upstream's own test suite runs eight threads against a single
`PreshMap`, exercising `__getitem__`, `__setitem__`, `items()`, `pop` and `__delitem__` with the
interpreter switch interval driven down to force overlap. The thread-unsafety warning at the top
of `maps.pxd` is about the C struct API that Cython code cimports, not about that object. The
`BloomFilter` gets the same treatment and the same eight-thread test.

`PreshCounter` has neither: no critical section anywhere in `counter.pyx`, and no threaded test.
`PreshMapArray` carries its own `thread-unsafe without external synchronization` note in the same
`.pxd`. Build either of those on one thread, or put your own lock around it.

What does need care is the UI thread. Turning text into keys is the expensive half of building
an index — the inserts themselves are fast — so build it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), keep the
worker body wrapped so a failure cannot leave the controls disabled, and finish with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Keys

**A key is a `uint64` and nothing else.** A string raises `TypeError: an integer is required`,
a negative number raises `OverflowError: can't convert negative value to uint64_t`, and
anything at or above 2⁶⁴ raises `OverflowError: Python int too large to convert to C unsigned
long`. Values go through the same door, as `size_t`, so a negative value raises
`OverflowError: can't convert negative value to size_t`. Store an index, an offset or a packed
integer, and see below for the one wrong type that does not raise.

Text therefore has to be hashed on the way in, and the hash has to be **stable across
launches**. Python's builtin `hash()` is salted per process unless `PYTHONHASHSEED` is set, so
a table keyed with it stops matching the moment the app restarts. A truncated digest from
[`hashlib`](https://docs.python.org/3/library/hashlib.html) is the portable answer:

```python
import hashlib

def key(text):
    return int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
    )
```

`murmurhash` is preshed's usual partner — `bloom.pyx` cimports `hash128_x86` from it — but that
pairing lives at the Cython level: the `murmurhash` package's Python API returns a *signed
32-bit* int, which is neither wide enough nor the right sign for a key. From application
Python, produce the 64 bits yourself.

**A collision is silent.** The table stores your integer and never sees the original string, so
two texts that fold to the same key share one cell and nothing reports it. With a well-mixed
64-bit digest that is remote — around one chance in a billion that *any* pair collides across
200,000 keys — but not zero, and it is why a preshed-keyed index is a lookup structure rather
than a system of record.

### Memory and speed

Measured on desktop (macOS on Apple silicon, CPython 3.12), for 200,000 integer keys mapped to
integer values:

| | `PreshMap` | `dict` |
| --- | ---: | ---: |
| Held | 8.4 MB | 23.2 MB |
| Per entry | 42 bytes | 116 bytes |
| One lookup from Python | 32.2 ns | 19.4 ns |
| 400,000 increments | 30.8 ms | 51.2 ms |

The dict's 23.2 MB is 10.5 MB of hash table — the part `sys.getsizeof` reports — plus 12.7 MB
of `int` objects hanging off it, counting each key and value object once. That second number is
what preshed removes, and it is why the ratio is stable rather than a benchmark artefact: a cell
is a `uint64` next to a pointer-sized value, 16 bytes on every ABI a Flet app can target,
whatever the keys happen to be. The 8.4 MB is that arithmetic — 524,288 cells — and it matched
the process's resident-set growth to within 33 KB. The lookup figures are the best of nine
passes over all 200,000 keys.

The lookup row is the one to read twice. **For most app code a `dict` is the right answer**: it
is faster to read from Python, it takes any hashable key, and you hand it the object itself
rather than a digest of it. preshed earns its place when the table is big enough for 2.8×
memory to matter, or when the code touching it is Cython that can drop into the `nogil` C API —
which a Flet app written in Python cannot. The increment row, `PreshCounter` against
`collections.Counter`, is the exception at the Python level: `inc(key, 1)` is one call where
`tally[key] += 1` is two dict operations and a fresh `int`.

Size the table up front. It doubles as soon as it is three-fifths full, allocating a fresh array
each time — 8, 16, 32 … 524,288 cells in turn, 16.8 MB of allocation to arrive at a table that
needs 8.4 MB. Filling those 200,000 keys from the default size left the process 16.7 MB heavier
and it stayed there; constructed with `initial_size=1 << 19` the same fill cost 8.4 MB.

### App size

The wheel is approximately 0.11–0.14 MB compressed, and unpacked 0.22–0.34 MB per Android ABI
and 0.38–0.52 MB per iOS slice, across three small extension modules. Nothing here is a size
lever; if an application needs one, it is an app bundle, split APKs or a narrower
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures), and it
is about the rest of the payload.

### Other considerations

A desktop `flet run` uses PyPI's wheel of the same version, built by a different toolchain. The
API and the semantics are the same, and the memory figures follow from the cell layout rather
than from the machine — but the timings do not transfer, so measure any latency budget on the
device.

## Things to know

- **`len()` on a `PreshCounter` is the size of the table, not the number of keys.** A counter
  holding three keys reports `8`, because that is its cell count; it is the same number as
  `counter.length`. Iterating yields `(key, count)` pairs, so `sum(1 for _ in counter)` is the
  figure you probably wanted.

- **Keys 0 and 1 are the empty and deleted markers.** They store, read back and appear in
  `items()`, but `len()` does not count them: a `PreshMap` holding 5,000 keys of which two are
  0 and 1 reports `4998` while `items()` yields 5,000 pairs. If your keys come from a hash,
  fold those two values somewhere else.

- **A `float` is truncated, not rejected.** `index[2.9] = 7.9` stores the value `7` under the
  key `2`, and `counter.inc(5.7, 2.9)` adds `2` to the key `5`. Every other wrong type raises
  `TypeError: an integer is required`, so a stray float is the one that slips through — and any
  value between `-1` and `0` truncates to key `0`, preshed's empty marker. Cast with `int()`
  where the number arrives.

- **A miss reads differently in each table.** `PreshMap` returns `None` for a key it has never
  stored, and supports `in`. `PreshCounter` returns `0`, and cannot distinguish "never seen"
  from "seen zero times". A stored value of `0` is not a miss in either: `PreshMap` returns
  `0` and `in` still answers `True`.

- **`PreshCounter.smooth()` fits a Good–Turing smoother and refuses unnatural data.** It needs
  keys seen exactly once *and* keys seen exactly twice, which a Zipf-shaped table has and a
  flat one does not; without them it raises `AssertionError: Cannot smooth your weird data`.
  Call it inside a `try` if the distribution is not under your control.

## Build notes (maintainers)

### Recipe shape

A plain Python sdist build with one patch. The structural point is that preshed resolves `.pxd`
files out of *installed sibling packages* rather than out of its own tree, so anything that
changes how the cross environment exposes site-packages breaks the build inside `cythonize`,
before a compiler runs. The patch preamble owns that mechanism and `meta.yaml`'s comments own
the Android C++ runtime requirement; neither is restated here.

The wheel is not self-contained at runtime either. `preshed.maps` and `preshed.counter` import
`cymem`, and `preshed.bloom` additionally imports `murmurhash`, so a CI run that builds preshed
has to make both sibling recipes' wheels resolvable to the on-device test app.

### Upgrade hazards

- Upstream's `install_requires` holds `cymem>=2.0.2,<2.1.0` and `murmurhash>=0.28.0,<1.1.0`.
  The sibling recipes must build versions inside those ranges, or the wheel installs nowhere.
- The patch is anchored to the shape of upstream's `setup.py`; a rewrite of the `cythonize`
  call moves it.
- Upstream's `python_requires` is `>=3.9,<3.15`, so a new interpreter leg needs an upstream
  release before this recipe can follow.

### Re-verification checklist

- **All three extensions import.** `maps`, `counter` and `bloom` are separate binaries and a
  test that touches one proves nothing about the others.
- **The consumer semantics above.** `len()` versus `items()` with keys 0 and 1, `len()` on a
  `PreshCounter` being the cell count, `None` versus `0` on a miss, and the `uint64`-only key
  and value conversions with their exact error text.
- **Cell size.** The memory figures assume `struct Cell { uint64_t key; void* value; }`.
  Compiled with NDK r27 clang that is 16 bytes on `arm64-v8a`, `x86_64` *and* `armeabi-v7a` —
  the 64-bit key's alignment pads out the 4-byte pointer on the 32-bit ABI — so the arithmetic
  holds everywhere Flet can build. It is 12 bytes for 32-bit x86, which Flet has refused to
  target since 0.86.0; if that ever returns, the figures need a second column.
- **Growth policy.** `map_set` resizes when `(filled + 1) * 5 >= length * 3`. If upstream
  changes that, both the 8.4 MB figure and the pre-sizing advice move with it.
- **Which classes are locked.** `maps.pyx` and `bloom.pyx` carry `cython.critical_section`
  blocks and `counter.pyx` carries none, which is the whole basis of the Threading section.
  Grep for it, and check whether `tests/test_multithreaded.py` has grown a `PreshCounter` case:
  a bump that levels those up would make that section needlessly restrictive.
- **Size.** Re-measure compressed and unpacked from the built wheels rather than scaling these.

### Coverage gaps

The device test imports `preshed.maps` and exercises set, get, `len` and `in` on it. It never
touches `preshed.counter` or `preshed.bloom`, so a green run is not evidence that those two
extensions load — and because `bloom` is the only module that pulls `murmurhash` in at runtime,
it is not evidence that dependency resolves either. Bloom filters, `PreshMapArray`, `pop` and
`__delitem__`, and smoothing are all outside what is currently checked, and no test has ever
run on a device or emulator using the 32-bit `armeabi-v7a` wheel.
