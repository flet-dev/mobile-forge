# bitarray

[`bitarray`](https://github.com/ilanschnell/bitarray) is a sequence type that stores one bit
per bit. It behaves like a list of booleans — indexing, slicing, `append`, `extend`, `count`,
comparison — but eight elements share a byte in one contiguous buffer, and the whole-array
operations (`&`, `|`, `^`, `~`, `count`, `search`) run over that buffer in C rather than
element by element. The importable surface is two C extensions behind two modules: `bitarray`
itself, and
[`bitarray.util`](https://github.com/ilanschnell/bitarray#functions-defined-in-bitarrayutil-module),
which adds the things you actually build with — `zeros`, `ones`, `count_and`/`count_or`/
`count_xor`, `subset`, Huffman coding, integer and hex conversion, and a sparse compression
codec.

On a phone the reason to reach for it is memory. Over a universe of 1,000,000 ids, measured
with `sys.getsizeof` on a desktop (macOS arm64, CPython 3.12.13): the bitarray is 125,080
bytes, the same 1,000,000 booleans as a Python list are 8,000,056, and a `set` holding 100,000
of those ids as ints is 4,194,520 bytes of table plus 2,800,000 bytes of int objects. That is
the difference between a membership structure you can hold in a background-refreshed app and
one you cannot. The buffer is also a real buffer: it exports the buffer protocol, `tobytes()`
hands you the bytes, and a format that packs bits the same way — PNG's bit-depth-1 greyscale,
for one — consumes it with no conversion at all.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "bitarray",
]
```

The entry belongs in top-level `[project] dependencies` rather than in a `[tool.flet.android]`
or `[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has
desktop wheels for every host you would build from.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bloom-filter`](examples/bloom-filter) — a Bloom filter drawn one pixel per bit, its measured
  false-positive rate checked against what its own density predicts.

## Usage in a Flet app

Allocate with [`util.zeros`](https://github.com/ilanschnell/bitarray#functions-defined-in-bitarrayutil-module),
set bits through ordinary indexing, and let `count()` produce a value for a
[`ft.Text`](https://flet.dev/docs/controls/text/):

```python
import flet as ft
from bitarray.util import zeros

seen = zeros(65_536)                    # one 8,192-byte buffer, every bit clear
for position in hash_positions(key):    # your own hash function
    seen[position] = 1

present = all(seen[position] for position in hash_positions(other_key))
status = ft.Text(f"{seen.count():,} of {len(seen):,} bits set")
```

Note the `from bitarray.util import …` form: a plain `import bitarray` does not reach `util`,
which is the first bullet under [Things to know](#things-to-know).

### Storage

bitarray opens no files of its own, and
[`fromfile`/`tofile`](https://github.com/ilanschnell/bitarray#bitarray-methods) take a *file
object*, not a path — `tofile("x.bin")` is `AttributeError: 'str' object has no attribute
'write'`. So you choose the location: something that should survive a restart goes under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
a scratch copy under
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).

```python
from bitarray.util import serialize

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "seen.bits")
with open(path, "wb") as handle:
    handle.write(serialize(seen))
```

**Use `util.serialize`, not `tofile`, unless the bit length is a multiple of eight.** A buffer
is whole bytes, so `tofile` writes the padding and `frombytes` reads it back as data: a 9-bit
array round-tripped that way comes back **16 bits long and unequal to the original**.
[`serialize`](https://github.com/ilanschnell/bitarray/blob/master/doc/represent.rst) prepends
one header byte carrying the endianness and the pad count — the same 9 bits become 3 bytes —
and `deserialize` restores the length *and* the endianness exactly.

**`util.sc_encode` is for sparse arrays and quietly gives up on dense ones — which is the right
behaviour, not a failure.** Measured on 65,536-bit arrays, raw buffer 8,192 bytes, against
`zlib.compress(level=9)` on the same bytes:

| bits set | fill | `sc_encode` | `zlib` level 9 |
| --- | --- | --- | --- |
| 80 | 0.12% | 167 B | 199 B |
| 399 | 0.61% | 660 B | 648 B |
| 1,573 | 2.4% | 1,834 B | 1,857 B |
| 3,873 | 5.9% | 4,134 B | 3,437 B |
| 7,539 | 11.5% | 7,512 B | 5,017 B |
| 14,244 | 21.7% | 8,199 B | 6,552 B |
| 29,947 | 45.7% | 8,199 B | 8,203 B |

Genuinely sparse is where it earns its place: 16% smaller than zlib at 0.12% fill, 36% smaller
at 0.06%. Between roughly 0.3% and 2.5% the two are within about 2% of each other and swap
places row to row; from about 3.5% zlib is ahead and the gap only widens. The ceiling is the
sharp part — `sc_encode` caps at 8,199 bytes, the raw buffer plus seven, however dense the
array gets. It never blows up, it round-trips exactly, and it preserves endianness; it just
stops helping.
[Upstream documents the format](https://github.com/ilanschnell/bitarray/blob/master/doc/sparse_compression.rst).

### Threading

**Neither extension ever releases the GIL** — there is no `Py_BEGIN_ALLOW_THREADS` anywhere in
the package. Measured on a desktop with a counter thread running beside the work, its rate given
as a percentage of an idle window: `count()` over a 1.07 GB array left the counter at 2.2–3.3%
and `c & d` over two 537 MB arrays at 1.4–1.8%, the same camp as `math.factorial(150000)` at
2.7–3.5%, against 85% for `zlib.decompress` — a C extension that does release it.

What that means for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is narrower
than it sounds. Most bitarray work in an app is a Python loop making many *short* C calls, and
the interpreter switches threads between bytecodes, so a worker doing that shares the
interpreter and the UI stays live: on the same harness a loop of 400,000 `filt[i] = 1`
assignments left the counter thread at full baseline rate, against 1.1% for one `count()` of
comparable duration. What does not interleave is one *long* call — a `count()`, an `&` or a
`search` over a very large array holds the GIL for its whole duration no matter which thread
issues it. Size the arrays rather than the thread pool.

```python
def rebuild():
    try:
        filt = build(keys)              # many short C calls: the UI stays live
        status.value = f"{filt.count():,} bits set"
    except Exception as error:          # run_thread discards what a worker raises
        status.value = f"{type(error).__name__}: {error}"
    page.update()                       # auto-update does not reach this thread

page.run_thread(rebuild)
```

Without the explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) the screen never
redraws, and without the `try/except` a failure disappears with no log, no dialog and no crash,
because `run_thread` never retrieves the worker's future.

**One call on a shared array is safe; a *sequence* of calls is yours to guard.** Nothing can
interleave with a call that never releases the GIL, and an array whose buffer is exported
refuses to resize rather than moving memory under a reader (`BufferError: cannot resize bitarray
that is exporting buffers`). A read-modify-write spanning several bytecodes — `if not a[i]:
a[i] = 1` — is different: the interpreter may switch threads mid-sequence, and `run_thread`
submits to a shared pool, so two quick taps do overlap. Hold a `threading.Lock` across the whole
sequence, or give each worker its own array.

### App size

Each wheel is approximately 0.14–0.15 MB compressed, and 0.57 MB unpacked on Android arm64-v8a
against 0.67 MB on the iOS device slice — the same C compiles larger on iOS. Roughly half of
that is upstream's own test suite (`test_bitarray.py`, `test_util.py`, `test_281.pickle`), which
ships inside the package, and Flet's defaults make that half *bigger* rather than smaller:
[`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) is on, and
compiling those two modules to `.pyc` grows them. In a built cp314 APK of the
[example](examples/bloom-filter) they are about 340,000 and 180,000 bytes, plus the 442-byte
pickle — approximately 520 KB of payload for a test suite the app never calls, against
approximately 150 KB of code that can run. Re-measure per leg: the `.pyc` sizes move with the
interpreter and with the length of the path `compileall` bakes into `co_filename`.

Drop it with [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
`package_files`, matching the *compiled* names, since cleanup runs after compilation:

```toml
[tool.flet.cleanup]
package_files = ["**bitarray/test_*.pyc", "**bitarray/*.pickle"]
```

**There is no slash after the leading wildcard, and that is not a typo.** serious_python matches
each glob with Dart's `Glob` against the absolute entry path, where a wildcard followed by `/`
insists on a literal separator, so `**/bitarray/test_*.pyc` misses a top-level `bitarray/` and
only ever fires on a nested one. These globs are verified against that matcher rather than
against a build, so confirm the result in the built APK's `assets/sitepackages.zip` before
relying on it — and drop the entry if the app calls `bitarray.test()`.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These figures describe the package payload, not the exact
amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel. It is built from the same source and the Python
API is identical, but three things behave differently there.

**`bitarray.test()` passes on a desktop and cannot on a device.** The package ships upstream's
own test suite and `bitarray.test()` runs both modules. Two cases reach the filesystem through
`__file__` — `test_bitarray.check_file`, which reads `test_281.pickle` beside its own module,
and `test_util.test_canonical_decode_large`, which reads its own source with
`open(__file__, 'rb')` — and what goes wrong depends on the platform:

- **Android.** Site-packages lives inside `sitepackages.zip` under Flet 0.86, so neither
  `open()` can resolve its path at all and both raise. This is what
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) exists for. The
  pickle really does ship — confirmed at 442 bytes in a built APK of the
  [example](examples/bloom-filter) — so extracting the package is enough for the first case.
- **iOS.** Site-packages is a directory, so both paths open. The pickle read then works, and the
  source read does not: with `compile.packages` on by default what ships is `test_util.pyc` with
  no `.py` beside it, `__file__` on a sourceless module is the `.pyc`, and the test gets
  bytecode where it expected source. Only `compile.packages = false` helps there; extracting
  changes nothing.

Neither case was run on a device — both are reasoned from the built payload and Flet's
packaging model, which is why `### Coverage gaps` lists the suite as unexercised.

**`util.random_p` needs Python 3.12**, raising `NotImplementedError` below it because it depends
on `random.binomialvariate`. Every Python Flet ships on mobile is 3.12 or later, so this only
bites a desktop `flet run` on an older interpreter.

**The threading guidance above assumes the GIL**, and every Python Flet ships on mobile has it.
None of it holds on a free-threaded desktop build, where upstream's own classifier still reads
*Free Threading :: 1 - Unstable*; validate that configuration separately if you run one.

## Things to know

- **`import bitarray` does not give you `bitarray.util`.** `__init__.py` never imports it, so
  `bitarray.util.zeros(8)` after a plain `import bitarray` is `AttributeError: module 'bitarray'
  has no attribute 'util'`, which inside a Flet event handler is a crash screen rather than a
  message. Write `from bitarray.util import zeros`, as the [example](examples/bloom-filter) does.
- **`a[i]` returns an `int`, not a `bool`.** `zeros(3)[0]` is `0` of type `int`, so
  `a[i] is True` is always false and `a[i] is 1` is a CPython interning accident. Use
  `if a[i]:`. Comparison of whole arrays is by value and does the right thing.
- **Bit-endianness changes the bytes but not the equality.** The default is `big`, and
  `bitarray('11010000', 'big').tobytes()` is `d0` while the same bits as `little` are `0b` — yet
  the two arrays compare **equal**, and a `frozenbitarray`'s hash is deliberately
  endianness-independent. So an array that round-trips correctly through `serialize` can still
  hand a different byte string to something outside Python. Anything that consumes `tobytes()` —
  a wire format, a file header, the PNG trick in the [example](examples/bloom-filter) — needs
  `endian='big'` stated explicitly rather than assumed.
  [Upstream's note on endianness](https://github.com/ilanschnell/bitarray/blob/master/doc/endianness.rst)
  is worth the five minutes.
- **`bitarray(n)` is zero-filled**, per its own docstring and observed over 50 fresh 4,096-bit
  arrays. `util.zeros(n)` is the same thing said out loud, and the one to write.
- **The object header is 80 bytes.** `sys.getsizeof` on a freshly built array is exactly
  `buffer_info().nbytes + 80`, and on a grown one it tracks `buffer_info().alloc` instead, which
  over-allocates only slightly: appending 100,000 bits gave `nbytes` 12,500 and `getsizeof`
  12,884 (desktop, CPython 3.12.13). Below a few thousand bits the header dominates and the
  memory argument does not apply.
- **A big Python `int` is the obvious alternative and it is slower.** Building the same
  65,536-bit membership structure from 10,000 keys × 5 positions took 10.7 ms with bitarray and
  34.6 ms with `n |= 1 << j` on an int, because ints are immutable and every set bit copies the
  whole value. Combining is where the gap widens, since bitarray has an operation that never
  materialises the intermediate: on 1,048,576 bits `util.count_and(a, b)` is 2.8 µs against
  17.9 µs for `(ia & ib).bit_count()`, while plain `a.count()` and `int.bit_count()` tie at
  2.4 µs. Desktop figures.
- **`__file__` is read only by the shipped test modules.** `bitarray/__init__.py` and
  `bitarray/util.py` never touch it, so ordinary use works straight out of Flet 0.86's zipped
  Android site-packages; `bitarray.test()` is the exception, and
  [Other considerations](#other-considerations) has it.
- **The `.pyi` stubs and `py.typed` do not reach the device.** serious_python's package step
  deletes `**.h`, `**.pyi` and `**.typed`. That is harmless for bitarray — nothing in the package
  reads them at runtime — but type checking has to happen on your development machine.

## Build notes (maintainers)

### Recipe shape

The recipe is `meta.yaml` and nothing else — no patches, no `requirements`, no `script_env`, no
`build.sh`, no `platforms` key, no `excluded_arches`. That shape is worth recording because it is
*earned*, not lucky: upstream's `setup.py` declares two `Extension`s with no `define_macros`
outside a PyPy branch, no `include_dirs`, no `libraries` and no dependencies, reads its version
out of `bitarray/bitarray.h` with a regex, and vendors `pythoncapi_compat.h` so it compiles
against every CPython from 3.6 without conditionals. There is nothing for a cross build to get
wrong. Confirmed against the wheels: every `.py`, `.h` and `.pickle` in the mobile wheel is
byte-identical to the sdist, so the recipe changes nothing about the package.

The matrix is nineteen wheels at one build number: Python 3.12 across all four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`), 3.13 and 3.14 across
three each, plus all three iOS slices (device, arm64 simulator, x86_64 simulator) per Python.

### Upgrade hazards

- **Free-threading support landing upstream inverts the whole Threading section.** The 3.8.1
  classifiers already carry *Free Threading :: 1 - Unstable*; the first `Py_BEGIN_ALLOW_THREADS`
  to appear turns "never releases the GIL" into a false consumer claim.
- **Upstream moving the test suite out of the package removes a consumer section.** It is
  currently about half the wheel, and the `[tool.flet.cleanup]` guidance under
  [App size](#app-size) exists only because of it.
- **Upstream publishing its own mobile wheels retires this recipe.** The 3.8.1 release is 104
  files — CPython 3.8 through 3.14 on macOS, Linux and Windows, thirteen free-threaded `cp314t`
  wheels, and an sdist — with `requires_python` and `requires_dist` both null, and no Android or
  iOS tag among them. That absence is the only reason the recipe exists.

### Re-verification checklist

- **The GIL claim.** Grep the new slices' undefined symbols for `PyEval_SaveThread` and
  `PyEval_RestoreThread`; both are absent from `_bitarray` and `_util` on every slice today.
- **The wheel composition**, which [App size](#app-size) states in bytes. Re-derive from
  `unzip -l` rather than assuming, and re-measure the compiled `.pyc` sizes from a built APK.
- **That `__file__` is still confined to the test modules.** `grep -n '__file__'` across the
  wheel's `.py` files hits `test_bitarray.py` twice and `test_util.py` once on 3.8.1, and should
  hit nothing else. The moment `util.py` or `__init__.py` reads a path relative to itself, this
  recipe acquires an `extract_packages` requirement and [Install](#install) is wrong.
- **The extension filenames.** They must keep a CPython ABI tag; an untagged `NAME.so` gets no
  `.soref`, is not relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError` on
  device. The spellings already vary — `_bitarray.cpython-312.so` on the 3.12 Android wheels,
  `_bitarray.cpython-314-aarch64-linux-android.so` on the 3.13 and 3.14 Android ones, and
  `_bitarray.cpython-312-iphoneos.so` / `…-iphonesimulator.so` on iOS — so a check must match the
  prefix, not the exact suffix. Forge's tag regex is in `src/forge/build.py`.
- **`otool -hv` reporting `DYLIB` on every iOS slice.** Forge's `MH_BUNDLE` → `MH_DYLIB`
  conversion landed in 2026-07; wheels published before it are the class of breakage that only
  appears at app link time, never in the recipe's own tests.
- **The no-I/O claim behind [Storage](#storage).** The extensions' symbol tables contain no
  `open`, `fopen`, `stat`, `socket`, `dlopen` or `getenv` at any binding on any of the 38
  extension files today.
- **Android ELF shape.** `DT_NEEDED` is `libm.so`, `libpython3.<minor>.so`, `libdl.so` and
  `libc.so` on all ten Android slices, with no `SONAME`, no `RPATH`/`RUNPATH` and no
  `libc++_shared` — the sources are C, not C++. Every `PT_LOAD` segment must keep 16 KB
  alignment, which Android 15 requires.
- **The `sc_encode` density table in [Storage](#storage)**, which is measured, and the
  `tofile`-loses-the-length claim, which is a property of the format rather than of a version but
  is cheap to re-run.

### Coverage gaps

`tests/test_bitarray.py` is a single `test_basic` covering construction, `append`, `extend`,
equality, `&`/`|`/`^` and slice assignment. It never imports `bitarray.util`, so **`_util.so` is
never loaded by the test suite on any device**; the only thing exercising the second extension
today is the [example](examples/bloom-filter). A one-line
`from bitarray.util import zeros; assert zeros(9).count() == 0` would close that, and asserting
that `serialize`/`deserialize` round-trips a non-byte-aligned array would close it while also
backing the claim in [Storage](#storage).

Nothing in `tests/` covers `bitarray.test()` on device, either failure mode described in
[Other considerations](#other-considerations), or the `[tool.flet.cleanup]` globs — those are
verified against serious_python's matcher, not against a build. The device evidence behind the
example is one pass per platform, on an Android emulator and an iPhone simulator.
