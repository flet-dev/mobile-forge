# bitarray

[`bitarray`](https://github.com/ilanschnell/bitarray) is a sequence type that stores one
bit per bit. It behaves like a list of booleans — indexing, slicing, `append`, `extend`,
`count`, comparison — but eight elements share a byte in one contiguous buffer, and the
whole-array operations (`&`, `|`, `^`, `~`, `count`, `search`) run over that buffer in C
rather than element by element. The importable surface is two C extensions behind two
modules: `bitarray` itself, and
[`bitarray.util`](https://github.com/ilanschnell/bitarray#functions-defined-in-bitarrayutil-module),
which adds the things you actually build with — `zeros`, `ones`, `count_and`/`count_or`/
`count_xor`, `subset`, Huffman coding, integer and hex conversion, and a sparse
compression codec. **`import bitarray` does not give you `bitarray.util`** — `__init__.py`
never imports it, so `bitarray.util.zeros(8)` after a plain `import bitarray` is
`AttributeError: module 'bitarray' has no attribute 'util'`, which inside a Flet event
handler is a crash screen rather than a message. Write `from bitarray.util import zeros`,
as the [example](examples/bloom-filter) does. Two further Python modules ship in the same
directory, upstream's own test suite; they are half the wheel, and
[Things to know](#things-to-know) prices them.

On a phone the reason to reach for it is memory. Measured on a desktop (macOS arm64,
CPython 3.12.13, bitarray 3.8.1) over a universe of 1,000,000 ids: the bitarray is 125,080
bytes, the same 1,000,000 booleans as a Python list are 8,000,056, and a `set` holding
100,000 of those ids as ints is 4,194,520 bytes of table plus its int objects, 6,994,520
in total. That is the difference between a membership structure you can hold in a
background-refreshed app and one you cannot. The second reason is that the buffer is a
real buffer: it exports the buffer protocol, `tobytes()` hands you the bytes, and formats
that pack bits the same way — PNG's bit-depth-1 greyscale, for one — can consume it with
no conversion at all, which is what the [example](examples/bloom-filter) does.

**Measured on device, 2026-08-20.** The [`bloom-filter`](examples/bloom-filter) example ran on
an arm64-v8a Android 14 emulator and an iPhone 16 simulator, both CPython 3.14.6, and the two
platforms produced *identical* structural results: 5,000 members in a 65,536-bit filter set
29,947 bits (45.7% full), and 50,000 non-member probes produced **98 false positives, a rate of
0.00196 against the 0.00190 the fill level predicts** — 95.1 ± 19.1 expected, so inside the 95%
band on both. The memory claim holds at the same scale: an 8,192-byte filter against 749,504
bytes for a `set` of the same keys, 91×. Only the timings differ — 50,000 probes took 490 ms on
Android and 196 ms on iOS.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "bitarray",
]
```

Nothing else to configure, and the entry belongs in top-level `[project] dependencies`
rather than in a `[tool.flet.android]` / `[tool.flet.ios]` table: `flet build` resolves for
the build host first, and PyPI has desktop wheels for every host you would build from. The
3.8.1 release is 104 files — CPython 3.8 through 3.14 on macOS (`x86_64` and `arm64`),
Linux (`manylinux` and `musllinux` × x86_64, aarch64, ppc64le, s390x) and Windows
(`win32`, `win_amd64`, `win_arm64`), thirteen free-threaded `cp314t` wheels, and an sdist
— with `requires_python` and `requires_dist` both null. None of those 104 files carries an
Android or iOS tag, which is why this recipe exists.

The wheel pulls nothing in with it: all nineteen mobile wheels have **zero** `Requires-Dist`
lines, so no `flet-lib*` wheel and no transitive dependency follows.

No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. `bitarray/__init__.py` and `bitarray/util.py` never touch `__file__`; the
only reads through `__file__` are the two in the shipped *test* modules (see
[Android notes](#android-notes)). Both extensions carry a CPython ABI tag in their filename
on every slice, though the suffix after it varies — `_bitarray.cpython-312.so` on the 3.12
Android wheels, `_bitarray.cpython-314-aarch64-linux-android.so` on the 3.13 and 3.14
Android ones, `_bitarray.cpython-312-iphoneos.so` and `…-iphonesimulator.so` on iOS — and
the tag is what Flet's relocation of native modules into `jniLibs` keys on
(`src/forge/build.py`), so neither needs a shim.

Nineteen wheels at the same build number: Python 3.12 across all four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`) and 3.13 and 3.14
across three each, plus all three iOS slices (device, arm64 simulator, x86_64 simulator)
for each of the three Pythons. No architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The wheels themselves are 138,794 to 150,268 bytes.

## Storage

bitarray opens no files of its own — the extensions' symbol tables contain no `open`,
`fopen`, `stat`, `socket`, `dlopen` or `getenv` at any binding on any of the 38 extension
files, and [`fromfile`/`tofile`](https://github.com/ilanschnell/bitarray#bitarray-methods)
take a *file object*, not a path (`tofile("x.bin")` is `AttributeError: 'str' object has
no attribute 'write'`). So you choose the location, and the choice is the usual one: a
filter or index you want to survive a restart goes under
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
a scratch one under
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp).

**Use `util.serialize`, not `tofile`, unless the bit length is a multiple of eight.** A
buffer is whole bytes, so `tofile` writes the padding and `frombytes` reads it back as
data: a 9-bit array round-tripped through `tofile`/`frombytes` comes back **16 bits long
and unequal to the original**.
[`serialize`](https://github.com/ilanschnell/bitarray/blob/master/doc/represent.rst)
prepends one header byte carrying the endianness and the number of pad bits — the same
9 bits become 3 bytes, and `deserialize` restores the length *and* the endianness exactly.

**`util.sc_encode` is for sparse arrays and quietly gives up on dense ones — which is the
right behaviour, not a failure.** Measured on 65,536-bit arrays, raw buffer 8,192 bytes,
against `zlib.compress(level=9)` on the same bytes:

| bits set | fill | `sc_encode` | `zlib` level 9 |
| --- | --- | --- | --- |
| 80 | 0.12% | 167 B | 199 B |
| 399 | 0.61% | 660 B | 648 B |
| 1,573 | 2.4% | 1,834 B | 1,857 B |
| 3,873 | 5.9% | 4,134 B | 3,437 B |
| 7,539 | 11.5% | 7,512 B | 5,017 B |
| 14,244 | 21.7% | 8,199 B | 6,552 B |
| 29,947 | 45.7% | 8,199 B | 8,203 B |

There is no clean crossover. Genuinely sparse is where `sc_encode` earns its place —
16% smaller than zlib at 0.12% fill, and 36% smaller at 0.06% on a finer sweep. From
roughly 0.3% to 2.5% the two are within about 2% of each other and swap places row to
row (zlib ahead at 0.61%, `sc_encode` ahead again at 0.97% and 2.4%), so neither is worth
choosing on size there. From about 3.5% zlib is ahead and the gap only widens. What is
sharp is the ceiling: by 16% density `sc_encode` is already at 8,195 bytes and it caps at
8,199, the raw buffer plus seven, however dense the array gets. It never blows up, it
round-trips exactly, and it preserves endianness; it just stops helping.
[Upstream documents the format](https://github.com/ilanschnell/bitarray/blob/master/doc/sparse_compression.rst).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`bloom-filter`](examples/bloom-filter) — a Bloom filter drawn one pixel per bit, its measured
  false-positive rate checked against what its own density predicts.

## Threading

**Neither extension ever releases the GIL.** `PyEval_SaveThread` and
`PyEval_RestoreThread` are absent from the undefined-symbol table of `_bitarray` and
`_util` on every one of the nineteen slices — there is no `Py_BEGIN_ALLOW_THREADS`
anywhere in the package. Confirmed by measurement on a desktop, with a counter thread
running beside the work and its rate given as a percentage of an idle window: controls
first, `time.sleep(0.3)` (GIL released) 94–101%, `zlib.decompress` of a 64 MB blob — a C
extension that *does* release it — 85%, and `math.factorial(150000)` (GIL held) 2.7–3.5%.
Then `a.count()` over a 1,073,741,824-byte array, **2.2–3.3%**; and `c & d` over two
536,870,912-byte arrays, **1.4–1.8%**. Squarely in the held camp, and the zlib control is
what shows the measurement could have said otherwise.

What that means for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is
narrower than it sounds. Most bitarray work in an app is a Python loop making many *short*
C calls — setting bits, testing bits — and the interpreter switches threads between
bytecodes, so a worker doing that does share the interpreter and the UI stays live: on the
same harness, a Python loop of 400,000 `filt[i] = 1` assignments left the counter thread
running at full baseline rate, against 1.1% for one `count()` of comparable duration. What
does not interleave is one *long* call: a `count()`, an `&` or a `search` over a very large
array holds the GIL for its whole duration no matter which thread issues it, and no
amount of threading changes that. Size the arrays rather than the thread pool.

The Flet-side rules apply as everywhere else, and the example shows both. A `run_thread`
worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads; and its body must be wrapped in
`try/except`, because `run_thread` never retrieves the worker's future and discards
whatever it raised — with no log, no dialog and no crash.

**One call on a shared array is safe; a *sequence* of calls is yours to guard.** There is
no lock in either extension, but the GIL finding above does that job for one call at a
time — nothing can interleave with a call that never releases it. Measured on a desktop:
four threads each appending 100,000 bits to one array gave exactly 400,000 bits on 5 of 5
runs; one thread appending while another looped on `count()` raised nothing on 5 of 5;
and an array whose buffer is exported refuses to resize rather than moving memory under a
reader (`BufferError: cannot resize bitarray that is exporting buffers`). What that does
not cover is a read-modify-write spanning several bytecodes — `if not a[i]: a[i] = 1` —
where the interpreter may switch threads mid-sequence; `run_thread` submits to a shared
pool, so two quick taps do overlap. Hold a `threading.Lock` across that whole sequence, or
give each worker its own array. A lost update there was not reproduced here, but neither
was one in the textbook pure-Python control (`x[0] = x[0] + 1`, 4 threads × 200,000, no
loss on 3 of 3), so read that absence as a blunt instrument and not a guarantee. None of
this holds on a free-threaded build — upstream's own classifier reads *Free Threading ::
1 - Unstable* — and every Python Flet ships on mobile has the GIL.

## Android notes

**The extensions link nothing but the interpreter and bionic.** `DT_NEEDED` is `libm.so`,
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices, with no
`SONAME`, no `RPATH`/`RUNPATH` and no `libc++_shared` — the sources are C, not C++, so
none of the usual Android C++ staging applies. Every `PT_LOAD` segment carries 16 KB
alignment, which Android 15 requires. arm64-v8a and x86_64 are `ELF64`; armeabi-v7a and
the legacy `x86` slice are genuine `ELF32`/`ARM` and `ELF32`/`i386` builds rather than
stubs. Each extension exports exactly one symbol — `PyInit__bitarray` and `PyInit__util` —
and outside CPython's own API the only symbols either imports are `memcpy`, `memmove`,
`memset`, `memcmp`, `strcmp`, `strlen`, `__cxa_atexit`, `__cxa_finalize` and
`__register_atfork`. No file, network or environment call of any kind.

**Do not expect `bitarray.test()` to pass on a device.** The package ships upstream's own
test suite (`test_bitarray.py`, `test_util.py`) and `bitarray.test()` runs both —
`test_bitarray.run()` loads `bitarray.test_util` into the same suite. Two cases open a file
through `__file__`: `test_bitarray.check_file` reads `test_281.pickle` at
`os.path.join(os.path.dirname(__file__), fn)` (`test_bitarray.py:1787`), and
`test_util.test_canonical_decode_large` reads its own source with `open(__file__, 'rb')`
(`test_util.py:2766`). Each fails differently, and the two platforms differ:

- **Android**, the pickle read: site-packages lives inside `sitepackages.zip` under Flet
  0.86, and an `open()` on a path through the archive raises. `test_281.pickle` is in that
  zip — confirmed at 442 bytes in a built APK of the [example](examples/bloom-filter) — it is
  simply not openable by path. This one is what
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) exists for;
  reasoned from Flet's documented model, not run on a device.
- **Both platforms**, the source read: `compile.packages` is on by default, so what ships is
  `test_util.pyc` with no `.py` beside it. `__file__` on a sourceless module is the `.pyc`,
  so that `open()` hands the test bytecode where it expected its own source. Confirmed
  against the built payload: the iOS `site-packages/…/bitarray/` directory holds
  `test_bitarray.pyc`, `test_util.pyc`, `util.pyc`, `__init__.pyc`, the two `.so` files and
  the pickle — and no `.py` at all. `extract_packages` does not help here; only
  `compile.packages = false` would.

Nothing in `tests/` covers either case. Note this affects `bitarray.test()` only; nothing on
the normal import path reads `__file__`.

## iOS notes

**The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices — the failure mode that produces
*Unsupported mach-o filetype (only MH_OBJECT and MH_DYLIB can be linked)* at link time
does not arise here. Besides each extension's own install name, `otool -L` lists exactly
two dependencies, the same two on all eighteen files: `@rpath/Python.framework/Python`
and `/usr/lib/libSystem.B.dylib`.

**The same code is bigger on iOS.** For cp314 arm64: `_bitarray` is 134,728 bytes on the
iOS device slice against 80,584 on Android arm64-v8a, and `_util` 91,200 against 45,112 —
so an unpacked wheel of 668,157 bytes against 567,947. The x86_64 simulator slice is the
smallest of the three iOS builds at 89,984 / 54,720.

## Things to know

- **`a[i]` returns an `int`, not a `bool`.** `zeros(3)[0]` is `0` of type `int`, so
  `a[i] is True` is always false and `a[i] is 1` is a CPython interning accident. Use
  `if a[i]:`. Comparison of whole arrays is by value and does the right thing.
- **Bit-endianness changes the bytes but not the equality.** The default is `big`, and
  `bitarray('11010000', 'big').tobytes()` is `d0` while the same bits as `little` are
  `0b` — yet the two arrays compare **equal**, and a `frozenbitarray`'s hash is
  deliberately endianness-independent. So an array that round-trips correctly through
  `serialize` can still hand a different byte string to something outside Python.
  Anything that consumes `tobytes()` — a wire format, a file header, the PNG trick in the
  [example](examples/bloom-filter) — needs `endian='big'` stated explicitly rather than
  assumed.
  [Upstream's note on endianness](https://github.com/ilanschnell/bitarray/blob/master/doc/endianness.rst)
  is worth the five minutes.
- **The object header is 80 bytes and the over-allocation is small.** `sys.getsizeof` on a
  freshly built array is exactly `buffer_info().nbytes + 80`, and on a grown one it tracks
  `buffer_info().alloc` instead: appending 100,000 bits gave `nbytes` 12,500, `alloc`
  12,804 and `getsizeof` 12,884. All desktop measurements, CPython 3.12.13. Below a few
  thousand bits the header dominates and the memory argument does not apply.
- **A big Python `int` is the obvious alternative and it is slower on both sides.**
  Building the same 65,536-bit membership structure from 10,000 keys × 5 positions took
  10.7 ms with bitarray, 34.6 ms with `n |= 1 << j` on an int (3.2×) and 12.2 ms with a
  `bytearray` and hand-written masks — all three producing the same 34,932 set bits, and
  the bytearray's bytes identical to `filter.tobytes()`. Testing 20,000 keys × 5 positions
  took 23.3 ms against the bitarray and 52.1 ms against the int. Ints are immutable, so
  every set bit copies the whole value; that is the whole story. Where bitarray pulls
  further ahead is the combining operations, because it has one that never materialises
  the intermediate: on 1,048,576 bits, `a.count()` 2.4 µs and `int.bit_count()` 2.4 µs are
  a tie, but `util.count_and(a, b)` is 2.8 µs against 17.9 µs for `(ia & ib).bit_count()`.
  Desktop figures throughout.
- **Half the wheel is upstream's test suite, and Flet's default packaging makes that half
  bigger.** Of the 567,947 unpacked bytes of the cp314 Android arm64-v8a wheel, 149,160
  (26.3%) is code that can run, 290,559 (51.2%) is `test_bitarray.py`, `test_util.py` and
  `test_281.pickle`, 81,468 (14.3%) is two C headers — `bitarray.h`, which upstream ships
  so other C extensions can use bitarray's C API, and the vendored `pythoncapi_compat.h`
  it builds against — 38,212 is `dist-info`, and the remaining 8,548 is the two `.pyi`
  stubs and an empty `py.typed`. `flet build`
  then removes some of that and inflates the rest: serious_python's package step deletes
  `**.h`, `**.pyi` and `**.typed` (three of the sixteen globs in its `junkFilesMobile`
  list, identical in 4.3.0 and 4.5.1) and
  `flet build` passes `--cleanup-packages` by default (`cleanup.packages` defaults to
  `True` in flet_cli 0.86.5), which takes out 90,016 bytes of headers and stubs — but
  `compile.packages` also defaults to `True`, and compiling to `.pyc` makes the test
  modules *larger*. **A built cp314 APK of the [example](examples/bloom-filter) is the figure
  to plan against: `test_bitarray.pyc` 343,907 bytes, `test_util.pyc` 178,602, plus the
  442-byte `test_281.pickle` — 522,951 bytes of payload for a test suite the app never
  calls**, against 149,160 bytes of code that can. The exact number moves with the
  interpreter and with the length of the path the file was compiled from, which
  `compileall` bakes into `co_filename`: on desktop CPython 3.12.13 the same two files came
  to 337,986 and 174,007, and an 18-character path gave 337,986 where a 64-character one
  gave 338,032. So read them as *about* 340,000 and 180,000, and re-measure per leg.
  The mechanism to drop it is `[tool.flet.cleanup] package_files` (read by flet_cli
  0.86.5's `build_base.py`), matching the *compiled* names since cleanup runs after
  compilation:

  ```toml
  [tool.flet.cleanup]
  package_files = ["**bitarray/test_*.pyc", "**bitarray/*.pickle"]
  ```

  **There is no slash after the leading wildcard, and that is not a typo.**
  serious_python matches each glob with Dart's
  `Glob(pattern, context: site-packages)` against the absolute entry path, where a
  wildcard followed by `/` insists on a literal separator — so `**/bitarray/test_*.pyc`
  misses a top-level `bitarray/` and only ever fires on a nested one. Checked by running
  both patterns through the same `glob` package serious_python uses: the slashed form
  matched nothing under a site-packages root, the unslashed form matched both test
  modules. Upstream's own junk list carries `__pycache__` *and* `**/__pycache__` for the
  same reason. **The globs are verified against the matcher, not against a build** — check
  the result with
  `unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep bitarray`
  before relying on it, and drop the entry if the app calls `bitarray.test()`.
- **The native code is small, and small because it is stripped.** The two extensions
  together are 125,696 bytes on Android arm64-v8a (cp314) and 225,928 on the iOS device
  slice. Upstream's own `manylinux2014_aarch64` cp314 wheel — same source, same
  architecture family — ships a 623,128-byte `_bitarray.so` carrying `.symtab` and
  `.debug_*` sections; the forge build of the same file is 80,584 bytes with neither.
- **The `.pyi` stubs and `py.typed` do not reach the device**, per the cleanup list above.
  That is harmless for bitarray — nothing in the package reads them at runtime — but it
  means type checking has to happen on your development machine, and it is the same
  mechanism that breaks packages using `lazy_loader`'s `attach_stub`.
- **`util.random_p` needs Python 3.12**, raising `NotImplementedError` below it because it
  depends on `random.binomialvariate`. Every Python Flet ships on mobile is 3.12 or later,
  so this only bites a desktop `flet run` on an older interpreter.
- **`bitarray(n)` is zero-filled**, per its own docstring and observed over 50 fresh
  4,096-bit arrays. `util.zeros(n)` is the same thing said out loud, and the one to write.

## Build notes (maintainers)

The recipe is `meta.yaml` and nothing else — no patches, no `requirements`, no
`script_env`, no `build.sh`, no `platforms` key, no `excluded_arches`. That shape is worth
recording because it is *earned*, not lucky: upstream's `setup.py` declares two
`Extension`s with no `define_macros` outside a PyPy branch, no `include_dirs`, no
`libraries` and no dependencies, reads its version out of `bitarray/bitarray.h` with a
regex, and vendors `pythoncapi_compat.h` so it compiles against every CPython from 3.6
without conditionals. There is nothing for a cross build to get wrong. Confirmed against
the wheels: every `.py`, `.h` and `.pickle` in the mobile wheel is byte-identical to
`bitarray-3.8.1.tar.gz`, so the recipe changes nothing about the package.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That the GIL claim still holds**, since [Threading](#threading) is built on it. Grep
  the new slices' undefined symbols for `PyEval_SaveThread`; upstream has been adding
  free-threading support (the 3.8.1 classifiers already carry
  *Free Threading :: 1 - Unstable*), and the first `Py_BEGIN_ALLOW_THREADS` to land would
  invert that whole section.
- **The wheel composition**, which [Things to know](#things-to-know) states in bytes.
  Upstream keeps the test suite inside the package, so a release that grows it moves a
  consumer-facing number; a release that finally moves it out would remove a whole bullet.
  Re-derive from `unzip -l` rather than assuming.
- **That `__file__` is still confined to the test modules.** `grep -n '__file__'` across
  the wheel's `.py` files hits `test_bitarray.py` twice and `test_util.py` once on 3.8.1,
  and should hit nothing else. The moment
  `util.py` or `__init__.py` reads a path relative to itself, this recipe acquires an
  `extract_packages` requirement and [Install](#install) is wrong.
- **The extension filenames.** They must keep a CPython ABI tag; an untagged `NAME.so`
  gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Note the spellings already in play here —
  `_bitarray.cpython-312.so` on the 3.12 Android wheels,
  `_bitarray.cpython-314-aarch64-linux-android.so` on the 3.13 and 3.14 Android ones, and
  `_bitarray.cpython-312-iphoneos.so` / `…-iphonesimulator.so` on iOS — so a check must
  match the prefix, not the exact suffix.
- **`otool -hv` reporting `DYLIB` on every iOS slice.** Forge's `MH_BUNDLE` →
  `MH_DYLIB` conversion landed in 2026-07; wheels published before it are the class of
  breakage that only appears at app link time, never in the recipe's own tests.
- **The `sc_encode` density table in [Storage](#storage)**, which is measured, and the
  `tofile`-loses-the-length claim, which is a property of the format rather than of a
  version but is cheap to re-run.
- **Whether upstream has started publishing mobile wheels.** Today's 3.8.1 release is 104
  files with no Android or iOS tag among them; the day that changes, this recipe may stop
  being needed.

`tests/test_bitarray.py` is a single `test_basic` covering construction, `append`,
`extend`, equality, `&`/`|`/`^` and slice assignment. Two things about it are worth fixing
at the next touch. It has no docstring, which the repo's test convention requires. And it
never imports `bitarray.util`, so **`_util.so` — 45,112 bytes of the wheel on Android
arm64-v8a, 91,200 on iOS device — is never loaded by the test suite on any device**; the
only thing exercising the second extension today is the [example](examples/bloom-filter). A
one-line `from bitarray.util import zeros; assert zeros(9).count() == 0` would close that,
and asserting `serialize`/`deserialize` round-trips a non-byte-aligned array would close
it while also backing the claim in [Storage](#storage). No version assertion, in line with
the repo's conventions.
