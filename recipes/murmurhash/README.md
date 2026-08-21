# murmurhash

[`murmurhash`](https://github.com/explosion/murmurhash) is a Cython binding for
[MurmurHash](https://en.wikipedia.org/wiki/MurmurHash), Austin Appleby's non-cryptographic
hash. It is a building block rather than a library you would sit down and write an app
against: one call turns a string into a 32-bit integer, quickly and identically on every run
and every architecture. That combination is what makes it the standard tool for the
*hashing trick* — mapping an unbounded set of text features onto a fixed number of columns
with no vocabulary to build, store or keep in step with a model.

The speed comes from defending against nothing. See **Things to know** before using it
anywhere an attacker chooses the input.

## Install

Add murmurhash to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "murmurhash",
]
```

`hash(value, seed=0)` takes a `str` or a `bytes` and returns a **signed** 32-bit `int`;
`hash_unicode` and `hash_bytes` are the same function with the type fixed, and `hash` simply
dispatches to one of them. Anything else — `bytearray`, `memoryview`, `int` — raises
`TypeError: Expected bytes, got bytearray`, so convert first with `bytes(view)`. The seed is
a `uint32`: a negative one raises `OverflowError: can't convert negative value to uint32_t`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`feature-hash`](examples/feature-hash) — hashes a corpus into a fixed-width vector and
  measures the collisions that width buys.

## Usage in a Flet app

The whole API, and the four lines that turn it into a feature vector:

```python
import flet as ft
from murmurhash import hash as mmh

WIDTH = 1 << 18  # a power of two, so the bucket is a mask rather than a modulo


def column(feature):
    """Return the column this feature belongs in, and the sign to add there."""
    value = mmh(feature)
    return value & (WIDTH - 1), 1 if value >= 0 else -1


index, sign = column("orange|juice")
caption = ft.Text(f"column {index}, {sign:+d}")
```

The sign is not decoration. Taking it from the sign bit gives a second, independent hash for
free, and adding `+1` or `−1` instead of always `+1` stops colliding features from
accumulating in one direction — the same reasoning behind `alternate_sign` in scikit-learn's
[`FeatureHasher`](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.FeatureHasher.html).
Masking is only correct for a power-of-two width; use `%` for any other. Python's `&` reads
the two's-complement bits of a negative `int`, so the result is non-negative without `abs()`.

### Storage

The number is worth persisting, which is the point of using this rather than Python's own
`hash`: CPython salts
[`str.__hash__`](https://docs.python.org/3/reference/datamodel.html#object.__hash__) per
process, so an index built from the builtin is meaningless after a restart, while
`murmurhash.hash("apple")` is `1880549520` in every process, on every architecture in this
wheel. A model's weights, a bloom filter or a deduplication set can therefore be written once
and read back next launch.

Put anything the user expects to keep in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
regenerable derivatives in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
and scratch in
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).
Store the table width beside the data: a bucket index means nothing without the width it was
taken modulo, and widening a table renumbers every column.

### Threading

Each call is a pure function of its arguments and keeps no state between calls, so calls from
several threads are independent; `mrmr.pyx` declares `freethreading_compatible=True`. The GIL
is held for the duration of a call, because the Python-visible wrappers are `cpdef` rather
than `nogil`, so hashing does not overlap with other Python work in the same process.

One hash is a function call and belongs wherever you need it, UI thread included. A pass over
a corpus is a Python loop around that call, and the loop is the expensive part: move it into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### What the wheel exposes

Read from the built wheel rather than from documentation, because the Python surface is much
narrower than MurmurHash's:

| Reachable from | What you get |
| --- | --- |
| Python | `hash`, `hash_unicode`, `hash_bytes` — all three are `MurmurHash3_x86_32`, returning a signed 32-bit `int` |
| Cython (`cimport`) | `hash32`, `hash64` (MurmurHash2's `MurmurHash64A`), `real_hash64`, `hash128_x86`, `hash128_x64`, all `nogil` |

The 64- and 128-bit entry points are `cdef` declarations in `murmurhash/mrmr.pxd`, which
means they are reachable only by compiling a Cython extension against them — something that
happens on a build machine, not on a phone. `murmurhash.get_include()` exists to point a
compiler at the bundled headers and is a build-time helper for exactly that. **From a Flet
app, the 32-bit signed function is the API.**

`MurmurHash3_x86_32` is 32-bit arithmetic throughout, and the vendored source loads each
block through an endian-normalising accessor, so `armeabi-v7a` produces the same number as
`arm64-v8a`, and an iOS device the same number as the simulator.

### App size

Expect approximately 23–29 KB of compressed wheel and 41–118 KB unpacked per architecture —
the extension is nearly all of it, at 32–48 KB on Android and 65–108 KB on iOS. This is
one of the smaller payloads on the index, and
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
here worth the configuration.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not the
amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's wheel of the same version, compiled from the same vendored
`MurmurHash2.cpp` and `MurmurHash3.cpp`. If your app depends on desktop and device agreeing —
and a persisted index does — assert a known value rather than assuming it: on desktop
`hash("hello world")` is `1586663183` and `hash("anxiety")` is `-1859125401`. The recipe's
device test asserts only that two calls agree with each other, so it is not evidence of the
constant.

## Things to know

- **`from murmurhash import hash` shadows the builtin `hash` in that module.** The symptom
  arrives later and somewhere else: `hash(3.5)` in the same file now raises
  `TypeError: Expected bytes, got float`. Import it as `mmh` or use `murmurhash.hash(...)`.

- **This is not a cryptographic hash, and the speed is the reason.** Hashing 54,500 short
  strings took 2.1 ms through `murmurhash.hash` against 10.6 ms through
  [`hashlib.blake2b`](https://docs.python.org/3/library/hashlib.html) on desktop — four to
  five times, bought by resisting nothing an adversary does. MurmurHash is a published
  target for hash-flooding: an attacker who can name your keys can drive every
  one of them into the same bucket. For integrity, authentication or anything a user supplies
  and an adversary might, use [`hashlib`](https://docs.python.org/3/library/hashlib.html) or
  [`hmac`](https://docs.python.org/3/library/hmac.html), and
  [`hmac.compare_digest`](https://docs.python.org/3/library/hmac.html#hmac.compare_digest) to
  compare the result. Never a password: that needs a deliberately slow KDF such as the
  one in [`argon2-cffi-bindings`](../argon2-cffi-bindings).

- **Thirty-two bits is a bucket index, not an identity.** Roughly half of all values are
  negative, the empty string hashes to `0`, and the birthday bound puts even money on a
  collision at about 77,000 distinct inputs — well inside the feature count of a modest text
  corpus. Colliding into a table you sized on purpose is the technique working; colliding
  into a set of "unique" ids is a bug that appears once the data grows.

- **A collision costs what the colliding features were worth.** In the example's corpus,
  19,582 features into 262,144 buckets leaves 7.0% of them sharing, and into 4,096 buckets
  99.1% — yet none of the hundred most frequent features collide with each other until 4,096,
  where 6% do. Size the table against the features that carry weight, and let the long tail
  collide.

- **The version is not on the package.** `murmurhash.__version__` raises `AttributeError`,
  because `about.py` exports through `import *` and every name in it starts with an
  underscore. Read `murmurhash.about.__version__`.

## Build notes (maintainers)

### Recipe shape

A plain Python package recipe with no patches. The sdist cythonizes one `.pyx` and compiles
the two vendored MurmurHash `.cpp` files into a single extension, `murmurhash.mrmr`, with
`language="c++"`. That C++ setting is the whole reason for the Android host requirement in
`meta.yaml`: the built `.so` carries `libc++_shared.so` in `DT_NEEDED`, which the device
runtime does not provide unless the wheel brings it. On iOS the same extension resolves
against `/usr/lib/libc++.1.dylib` and is `MH_DYLIB`.

### Upgrade hazards

- The consumer page above rests on the Python surface being exactly three functions returning
  a signed 32-bit int, with everything wider confined to `mrmr.pxd`. Upstream promoting a
  64-bit variant to `cpdef` would not break anything, but it would make **What the wheel
  exposes** wrong on the next bump.
- The MurmurHash sources are upstream's vendored copies. Re-vendoring is the one change that
  could alter the constants this page quotes, and nothing in the build would flag it.
- `Requires-Python: >=3.6,<3.15` caps the interpreter; a newer one needs an upstream release
  first.

### Re-verification checklist

- **Known values, on both platforms:** `hash("hello world") == 1586663183` and
  `hash("anxiety") == -1859125401`. Nothing in `tests/` asserts a constant today, so this is
  the check that would actually catch a re-vendor or an endianness regression.
- **Extension per slice:** one `mrmr` `.so` with the right ABI tag; `MH_DYLIB` on iOS, and
  `libc++_shared.so` still in `DT_NEEDED` on Android.
- **The `.pxd` surface:** `mrmr.pxd` is the contract every Cython consumer compiles against.
  A changed `cdef` signature breaks them at build time, not here.
- **Sizes:** re-measure compressed and unpacked from the wheels rather than scaling these.

### Coverage gaps

The device test calls `murmurhash.hash` twice and asserts the two agree. That reaches
`mrmr`, the only extension in the wheel, so import and the 32-bit path are genuinely covered
on device — but a platform returning different numbers from desktop would pass it, which is
why the checklist above adds a constant.

Nothing exercises the Cython-only entry points, and they cannot be reached from a test
written in Python. Worth knowing before a consumer recipe starts using them:
`MurmurHash64A` dereferences the key as a `uint64_t *`, so a caller passing an unaligned
pointer is doing an unaligned 64-bit load — benign on the 64-bit targets, untested on
`armeabi-v7a`. The `int` length parameter is likewise untested at sizes where it would
overflow.
