# rapidfuzz

[`rapidfuzz`](https://rapidfuzz.github.io/RapidFuzz/) is fuzzy string matching: how alike are two
strings, and which of these ten thousand is closest to what the user typed. It gives you the
[`fuzz`](https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html) scorers (`ratio`, `partial_ratio`,
`token_sort_ratio`, `token_set_ratio`, `WRatio`, …), the
[`distance`](https://rapidfuzz.github.io/RapidFuzz/Usage/distance/index.html) metrics (Levenshtein,
Damerau-Levenshtein, Jaro, Jaro-Winkler, Hamming, Indel, LCSseq, OSA, Prefix, Postfix) and
[`process`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html), which runs one query against
a whole list in C++ instead of in a Python loop. It is MIT-licensed and needs no network and no
model file. On a phone that last part is the point: the alternative to `process` is a Python loop
over your data, and the loop is what stalls the frame.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "rapidfuzz",
]
```

**Add `"numpy"` as well if you call
[`process.cdist`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#rapidfuzz.process.cdist)
or `cpdist`.** Those two `import numpy` inside their own function bodies, so an app without it
installs, imports and searches — and then raises `ModuleNotFoundError: No module named 'numpy'`
from a handler the first time someone touches that code path. Every other API works without it.
If you pin numpy with `==`, raise your `requires-python` to `>=3.11` to match numpy's own
floor: uv resolves every version in the range, so an `==` pin against a `>=3.10` floor makes the
lowest split unsatisfiable and `flet build` stops with *No solution found when resolving
dependencies for split*. A bare `numpy`, as above, resolves per split and needs no change. The
[example](examples/fuzzy-search) pins, and raises its floor accordingly.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`fuzzy-search`](examples/fuzzy-search) — searches 4,000 in-app strings and shows the six
  scorers disagreeing about the answer, with `process.extract` checked against both a Python loop
  and `process.cdist`.

## Usage in a Flet app

```python
import flet as ft
from rapidfuzz import fuzz, process, utils

matches = process.extract(
    query,
    CHOICES,
    scorer=fuzz.WRatio,
    processor=utils.default_process,
    limit=8,
)
results.controls = [ft.Text(f"{name} — {score:.0f}") for name, score, _ in matches]
page.update()
```

[`process.extract`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#rapidfuzz.process.extract)
returns `(choice, score, index)` triples, best first. `processor=` and `limit=` are the two whose
defaults will surprise you: without a processor every scorer is case-sensitive, so a lowercase
query scores `0.0` against Title Cased data, and without `limit=` you get five results rather than
all of them. `scorer=` is the choice that decides whether the answers are any good — see
[Choosing a scorer](#choosing-a-scorer). Pass a `dict` of `{key: text}` as the choices and the
third element of each triple comes back as your key instead of a list index.

One more line belongs on a debug screen, because a native module that will not load costs you
nothing but speed and says nothing about it:

```python
compiled = not fuzz.ratio.__module__.endswith("_py")
```

### Choosing a scorer

**The scorers disagree, and picking the wrong one produces bad results rather than an error.**
Against the example's 4,000 place names, the query `junctn havn nrth` — a misspelling with the
words reordered — has `token_sort_ratio` and `token_set_ratio` finding `North Haven Junction` at
88.9, `WRatio` finding it at 84.4, and `ratio` (60.6, `Stone Haven Point`), `partial_ratio` (69.2,
`New Haven Point`) and `Levenshtein.normalized_similarity` (44.4, `Queens Haven Green`) each
confidently returning something else. It cuts the other way too: for `stone brige`, `ratio` and
`Levenshtein` correctly pick `Stone Bridge Bay` while `WRatio` — the default for `process.extract`
— returns `Stone Thorpe Springs`, its whole top 8 tied at 85.5 on the strength of `stone` alone.

| scorer | reach for it when |
| --- | --- |
| `WRatio` | a general search box; it is `process.extract`'s default |
| `token_sort_ratio` | the words may be reordered (names, addresses) |
| `token_set_ratio` | one side is a subset of the other |
| `ratio` / `QRatio` | the strings are short and nearly identical |
| `distance.*` | you want an edit count rather than a percentage |

That is rough guidance; measure it on your own data. `token_set_ratio` in particular saturates and
then ranks nothing — `token_set_ratio('cat', 'cat dog bird fish')` and
`token_set_ratio('a b', 'a b c d e f g')` are both `100.0`.

### Speed

Desktop CPython against a 4,000-choice corpus, best of 5, each call computing the identical top 8.
The absolute numbers are desktop numbers; the ratios are the part that transfers to a phone.

`process.extract` against a hand-written Python loop doing the same work — process the query once,
each choice once:

| scorer | `extract` vs the loop |
| --- | ---: |
| `ratio` | 4.9× |
| `Levenshtein.normalized_similarity` | 3.9× |
| `token_sort_ratio` | 2.7× |
| `WRatio`, `partial_ratio`, `token_set_ratio` | 1.6–1.7× |

The win tracks how cheap the scorer is, because what `extract` removes is Python call overhead, not
scoring work. The bigger number is what you get from having the compiled wheel at all. Forced onto
the pure-Python fallback, the same calls picked the same top match and cost:

| scorer | compiled | fallback |
| --- | ---: | ---: |
| `ratio` | 0.28 ms | 12.8 ms |
| `Levenshtein.normalized_similarity` | 0.42 ms | 26.4 ms |
| `WRatio` | 3.10 ms | 44.6 ms |

Same answers, 14× to 63× the time, and nothing in the API tells you which one you are running —
hence the `__module__` check above.

[`extract_iter`](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#rapidfuzz.process.extract_iter)
is the lazy form and is cheaper, especially with a cutoff. Same corpus, `fuzz.ratio`:
`extract(limit=None)` 0.76 ms, `list(extract_iter(...))` 0.49 ms, and
`extract_iter(..., score_cutoff=60)` 0.30 ms. How much the cutoff saves is entirely
query-dependent — see [Things to know](#things-to-know).

### Threading

**Threading a search buys nothing, because every scoring call holds the GIL for its whole
duration.** Measured on desktop, four threads over four disjoint 30,000-choice slices against one
thread doing all four: `process.extract` with `fuzz.ratio` 0.91×, with `WRatio` 1.01×, and a Python
loop over `fuzz.ratio` 1.01× — indistinguishable from a GIL-bound `sum(range(...))` control at
1.00×, while a GIL-releasing `hashlib.sha256` control on the same harness reached 1.82×.

**A background thread therefore does not make a long call safe — only a short one.** Measured with
a canary thread counting in a tight Python loop, calibrated against `sum(range(...))` (GIL-holding,
canary keeps 0.01 of its idle rate) and `hashlib.sha256` over 64 MB (GIL-releasing, 0.89): one
`process.extract` with `WRatio` over 200,000 choices scores 0.11, and one `fuzz.partial_ratio` on
two 4,000-character strings scores 0.01, the GIL-holding floor. Concretely, a 60 fps tick driven
from another thread arrives 712 ms late on the median and 1,419 ms late at worst while that one
`partial_ratio` runs.

**`cdist(..., workers=N)` is the exception, and the only one.** It scores 0.97 on that canary
**even at `workers=1`**, so it is the single call in this package that really does run alongside a
live UI — and the only one that uses more than one core. It needs a big enough matrix to be worth
the workers, though. 32 queries × 120,000 choices with `fuzz.ratio`, best of 5 after two warm-up
runs: 85.7 ms at `workers=1`, 46.4 at 2, 30.2 at 4, 22.1 at 8 and 21.5 at `-1` — 4.0× on a 10-core
machine, with `numpy.array_equal` true against the single-worker result at every setting. At
6 × 4,000 the win collapses to 0.645 → 0.409 ms and `-1` (0.500 ms) is worse than `workers=4`; at
1 × 4,000, the shape a search box actually produces, `workers=1` is 0.259 ms against 0.288 at 2 and
0.370 at `-1`, so extra workers are a straight loss. Use it above a threshold you measured, not by
default.

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is still the
right home for a search, for two narrower reasons: the handler returns immediately, and a search
over a corpus an app actually ships is milliseconds — the example's 4,000 names cost about 4 ms,
which no user can see. Size the corpus, not the thread.

The usual Flet rules then apply. `run_thread` never retrieves the worker's future, so an exception
in it vanishes without a log — wrap the body in `try/except`. Auto-update does not reach background
threads, so end the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). And `run_thread` submits
to a *shared* pool, so disabling the control that started the run is not by itself a guard against
two workers landing on the same rows; read the flag back before dispatching.

### App size

Approximately 1.2–2.0 MB compressed and 4.5–4.9 MB unpacked per ARM slice, about 94% of it the
five compiled extensions — so [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup)
has nothing here worth removing. Android carries one more thing, the C++ runtime those extensions
link, which is another 0.8–1.3 MB depending on ABI. The x86_64 emulator slice is more than twice
the size of an ARM one (see [Android](#android)), but it never ships to a user.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. Every ABI `flet build` asks for is published, armeabi-v7a
included as a genuine 32-bit build, so narrowing is a choice about your users rather than a
workaround. These figures describe the package payload, not the amount added to the final APK or
IPA; packaging and compression decide that.

### Android

**The x86_64 emulator is not the same build as a phone.** That slice ships three modules the ARM
slices do not — `_feature_detector_cpp`, `fuzz_cpp_avx2` and `distance/metrics_cpp_avx2` — and
unpacks to about 11.3 MB against 4.9 MB on arm64-v8a. rapidfuzz's dispatch asks
`_feature_detector_cpp` what the CPU supports and imports the AVX2 module when it says AVX2, so on
an emulator whose CPU reports AVX2 expect `fuzz.ratio.__module__` to read `rapidfuzz.fuzz_cpp_avx2`
and `Levenshtein.distance.__module__` to read `rapidfuzz.distance.metrics_cpp_avx2`, where a real
phone reads `…fuzz_cpp` and `…distance.metrics_cpp`. `process.extract` and `utils.default_process`
are unaffected either way: `process.py` and `utils.py` do have AVX2 branches, but no
`process_cpp_avx2` or `utils_cpp_avx2` is built on any platform, upstream included, so those
branches always fall through. Benchmark numbers taken on an x86_64 emulator therefore describe a
different binary from the one your users run. The `.endswith("_py")` check stays correct on both.

**Android costs one extra shared library**, the C++ runtime all five extensions link against. It
arrives with the wheel, and serious_python's Gradle build places it in `jniLibs/<abi>/`, which is
where the extensions look for it.

**Flet relocates the extensions, so `rapidfuzz.fuzz_cpp.__spec__.origin` is not a path inside your
app.** Extension filenames carry a `cpython-3<minor>` ABI tag on Android and that relocation keys
on the tag. The [`fuzzy-search`](examples/fuzzy-search) example prints the origin so you can read
the real value off the device rather than off this page.

### iOS

**Nothing extra ships.** C++ comes from the OS copy at `/usr/lib/libc++.1.dylib`, so the iOS wheel
is the five extensions and the Python layer.

**The iOS extension filenames carry no ABI tag** — `rapidfuzz/fuzz_cpp.so`,
`rapidfuzz/distance/metrics_cpp.so` — where the iOS device wheels of [`shapely`](../shapely),
[`orjson`](../orjson), [`pydantic-core`](../pydantic-core), [`lxml`](../lxml),
[`duckdb`](../duckdb) and [`pyzmq`](../pyzmq) on this index all ship
`<name>.cpython-3<minor>-iphoneos.so`. There is nothing for a consumer to do about it — the
recipe's on-device iOS-simulator tests run green — but the `.so` basenames serious_python stages
into frameworks are generic ones like `metrics_cpp`, which matters if you go looking for them in a
bundle.

**The x86_64 simulator reads the same module names as a device.** It ships a
`_feature_detector_cpp` with nothing to dispatch to: no `fuzz_cpp_avx2` or `metrics_cpp_avx2` is
built for iOS, so every AVX2 and SSE2 import in the dispatch ladder falls through to the generic
module. Unlike the Android x86_64 emulator (see [Android](#android)), a simulator reading of
`fuzz.ratio.__module__` is the reading you would get on a phone.

### Other considerations

**A desktop `flet run` uses PyPI's desktop wheel, and on an x86_64 machine that is a different
binary.** Upstream builds the feature detector and the SIMD kernels only for x86, so a desktop
x86_64 wheel dispatches `fuzz.ratio` to `rapidfuzz.fuzz_cpp_avx2` on any CPU that reports AVX2, and
runs at a speed no phone reproduces; a desktop arm64 wheel ships exactly the five modules the
mobile ARM slices do. Take the device reading for both the module names and the timings.

**`RAPIDFUZZ_IMPLEMENTATION=cpp` turns a failed native load from silent into loud**, which is the
most useful thing to set while validating a build. It has to be set before the first
`import rapidfuzz`:

```python
import os

os.environ["RAPIDFUZZ_IMPLEMENTATION"] = "cpp"

import rapidfuzz
```

The `_impl == "cpp"` branch's final import is not wrapped in `contextlib.suppress`, so a broken
extension raises — on a deliberately sabotaged install,
`ImportError: dlopen(…metrics_cpp…so …): slice is not valid mach-o file` — instead of quietly
answering from Python. `=python` forces the fallback, which is a convenient way to see what it
would cost you (see [Speed](#speed)).

## Things to know

- **A native module that will not load costs you nothing but speed, silently.** Every dispatch
  module (`fuzz.py`, `process.py`, `utils.py`, `distance/*.py`) wraps its `_cpp` import in
  `with contextlib.suppress(ImportError):` and then falls through to a pure-Python twin. Verified
  by overwriting all five `.so` in a venv with garbage: `from rapidfuzz import fuzz` still
  succeeded, `fuzz.ratio('appel', 'apple')` was still `80.0` and
  `Levenshtein.distance('kitten', 'sitting')` was still `3` — only `__module__` changed, to
  `rapidfuzz.fuzz_py`, `rapidfuzz.process_py`, `rapidfuzz.utils_py` and
  `rapidfuzz.distance.Levenshtein_py`. Nothing is logged. **The check that works is
  `not fuzz.ratio.__module__.endswith("_py")`** — it also stays correct on an Android x86_64
  emulator, where the answer can be `rapidfuzz.fuzz_cpp_avx2`. The obvious alternative,
  `'rapidfuzz.fuzz_py' in sys.modules`, is always `True` and proves nothing: the compiled modules
  load the fallback modules themselves, and `import rapidfuzz` leaves 40 rapidfuzz modules in
  `sys.modules` including all 16 `*_py` fallbacks.
- **Every scorer is case-sensitive, and a pure case difference scores zero.**
  `fuzz.ratio('CAFE', 'cafe')` is `0.0`, and so are `partial_ratio`, `token_sort_ratio`,
  `token_set_ratio`, `token_ratio`, `partial_token_sort_ratio`, `WRatio` and `QRatio`;
  `Levenshtein.normalized_similarity` and `JaroWinkler.similarity` are `0.0` too. A search box
  built the obvious way over Title Cased data finds nothing when the user types lowercase. Pass
  [`processor=rapidfuzz.utils.default_process`](https://rapidfuzz.github.io/RapidFuzz/Usage/utils.html#rapidfuzz.utils.default_process)
  to every `fuzz.*` call and to `process.extract`/`extractOne`/`cdist` — all eight scorers then
  give `100.0` on that pair. Know what it actually does before relying on it: lowercase,
  non-alphanumeric → space, strip, and nothing else. `'  Hello, WORLD!  '` becomes
  `'hello  world'` (the double space survives), `"Don't"` becomes `'don t'`, `'Ärger-Straße'`
  becomes `'ärger straße'` — no Unicode folding. It costs about 0.19 ms over 4,000 choices
  (0.32 ms with the processor against 0.13 ms on a pre-processed corpus, with `fuzz.ratio`), and
  pre-processing the corpus once takes 0.24 ms, so either way it is not what makes a search slow.
- **`fuzz.partial_ratio` explodes when *both* strings are long.** On two dissimilar random
  strings it took 1.4 ms at 500 characters, 19 ms at 1,000, 173 ms at 2,000 and 1,560 ms at
  4,000, while `ratio`, `token_sort_ratio`, `token_set_ratio` and `WRatio` stayed at 0.2–0.6 ms
  on the same 4,000-character pair. A short query against a long document is fine — the same
  `partial_ratio` over a 16-character query and a 7,326-character document was 0.017 ms — so the
  trap is specifically comparing two paragraphs. Keep it off *every* thread, not just the UI one:
  the call holds the GIL for its whole duration, so moving it into `page.run_thread` freezes the
  UI just the same (see [Threading](#threading)). **`WRatio` is not the way out**, even though it
  is `process.extract`'s default — it skips the partial path only while the two lengths are within
  a factor of 1.5, and falls into it the moment they are not. The cliff is at exactly
  `len_ratio >= 1.5` and it is about 1,500× wide: 4,000 characters against 5,990 took 0.9 ms,
  4,000 against 6,000 took 1,389 ms — slower than `partial_ratio` alone on that pair, because
  `WRatio` runs the other scorers first. The 0.2–0.6 ms figures above are the equal-length case
  only.
- **`process.extract`'s default `limit` is 5, not "all".** `len(process.extract('item', <50
  strings>))` is 5; `limit=None` gives 50. Code that scores everything and filters afterwards
  silently drops results. Pass `limit=` explicitly. A `score_cutoff` is the other way to shorten
  the work, but how much it saves is entirely query-dependent: on the example's corpus
  `score_cutoff=60` yields 86 of the 4,000 for `stone brige` and only 3 for `junctn havn nrth`, so
  it is not a selectivity you can assume.
- **`score_cutoff` is scaled to the scorer, and mixing the scales raises `TypeError` from inside
  Cython.** 0–100 for `fuzz.*`, 0.0–1.0 for the normalized `distance.*` metrics, an integer edit
  count for the raw distances. `process.extract(q, choices,
  scorer=Levenshtein.normalized_similarity, score_cutoff=60)` raises
  `TypeError: score_cutoff has to be in the range of 0.0 - 1.0`. The miss behaviour differs
  between layers as well: `fuzz.ratio('appel', 'apple', score_cutoff=90)` returns `0.0`, not
  `None`, while `process.extractOne('x', ['a'], score_cutoff=99)` returns `None`.
- **Bad input mostly returns a plausible wrong number instead of raising.**
  `fuzz.ratio(None, 'x')` is `0` (an `int`, not a `float`); `fuzz.ratio('abc', ['a','b','c'])` is
  `100.0`; `fuzz.ratio(b'abc', 'abc')` is `100.0`; `fuzz.ratio((1,2,3), (1,2,4))` is `66.67`; and
  `process.extract('x', ['a', None, 'b'])` returns `[('a', 0.0, 0), ('b', 0.0, 2)]` — index 1
  dropped, no warning. It is not consistent, either: `fuzz.ratio(123, 'x')` raises
  `TypeError: object of type 'int' has no len()`, `Levenshtein.distance(None, 'a')` raises
  `TypeError: object of type 'NoneType' has no len()`, and `utils.default_process(None)` raises
  `TypeError: sentence must be a String`. Coerce to `str` at the app boundary, and guard the
  handler with `except Exception` — these are plain builtin `TypeError`s, not a rapidfuzz
  exception class, and an unhandled exception in a Flet handler produces a crash screen.
- **`processor=` is applied to the query as well as to every choice, so it cannot pull a field
  out of a record.** `process.extract('nrth havn', [{'id': …, 'name': …}, …],
  processor=lambda r: default_process(r['name']))` raises
  `TypeError: string indices must be integers, not 'str'` — the lambda got handed the query
  string. Pass a `dict` of `{key: text}` as `choices` instead: `extract` then returns
  `(matched_string, score, your_key)` rather than `(matched_string, score, index)`.
- **`process.extract` sorts distance scorers the right way round.** With
  `scorer=Levenshtein.distance` the results come back ascending (lower is better) and with
  `scorer=fuzz.ratio` descending, because `process` reads the scorer's `_RF_ScorerPy` flags
  (`rapidfuzz/_utils.py`). You do not have to reverse anything yourself.
- **`cdist` returns `float32` for similarity scorers and `uint32` for integer distances**, and
  `dtype=` overrides with rounding to nearest. A `(1, 4000)` similarity matrix is 16,000 bytes;
  `cpdist` returns a 1-D array of the pairwise scores instead. Both need numpy — see
  [Install](#install).
- **Upstream's documentation applies here with no translation step.** The recipe carries no
  patches, and the Python half of the wheel is upstream's byte for byte — every `.py`, `.pyi` and
  `py.typed` entry hashes identically against PyPI's own wheels at the same version. Anything
  [upstream's docs](https://rapidfuzz.github.io/RapidFuzz/) say about the Python layer is true of
  this wheel.
- **Nothing is missing on ARM relative to a desktop ARM machine.** The five compiled modules the
  mobile ARM slices ship are exactly the five in PyPI's own `macosx_11_0_arm64` wheel. The extra
  modules are an x86 story on every platform, mobile and desktop alike, which is why an x86_64
  emulator and a desktop x86_64 laptop both carry eight.

## Build notes (maintainers)

### Recipe shape

**A plain scikit-build-core/CMake consumer with one host dep, and that is the whole design.**
rapidfuzz vendors its only native dependencies — the header-only `rapidfuzz-cpp` and Taskflow
submodules — inside the sdist, so there is no companion `flet-lib*` recipe to build and nothing to
resolve at load time by soname. Android needs `flet-libcpp-shared` because the C++ extensions link
`libc++_shared.so`; iOS binds the OS `/usr/lib/libc++.1.dylib` and needs nothing, which is why the
host dep sits behind an `sdk == 'android'` guard rather than being declared for both.

**Wheel shape, which is what licenses the absence of any `[tool.flet.*]` guidance in
[Install](#install).** All 64 entries in the Android wheel are 37 `.py` files, 16 `.pyi` stubs, an
empty `py.typed`, five extensions and five `dist-info` files — no data file to read. Across the
shipped `.py` source there is no `sys.platform` / `platform.system()` / `os.name` gate at all, the
only environment variable read is `RAPIDFUZZ_IMPLEMENTATION` (14 times, once per dispatch module),
and the only `__file__` uses are `get_include()` — a build-time helper for compiling *against*
rapidfuzz — and the PyInstaller hook package, which nothing imports. No `ctypes`, no `dlopen`, no
`find_library`, no `importlib.resources`, no `pkgutil`; so no
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry and no loader
shim. Flet's default [compilation and cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup)
is safe too: `getsource` and `inspect` appear nowhere, and the 53,740 bytes of `.pyi` that
serious_python strips are plain type stubs — rapidfuzz does not use `lazy_loader`, so nothing
parses them at runtime.

**Requires-Dist.** The Android wheel's only unconditional entry is
`flet-libcpp-shared (>=27.2.12479018)`; the iOS wheel has none. `numpy` is `numpy; extra == "all"`
on both — verified in a fresh venv where `pip install rapidfuzz` left `pip` and `RapidFuzz` as the
only packages and `'numpy' in sys.modules` was `False` after `import rapidfuzz`.

**Matrix and resolution.** Eighteen wheels at the same build number: Python 3.12, 3.13 and 3.14 ×
three Android ABIs (arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator,
x86_64 simulator). No arch is excluded; armeabi-v7a is a genuine ELF32/ARM build, not a stub. A
bare `rapidfuzz` resolves to this index on every mobile target, because PyPI's own release at the
recipe version is 82 wheels and one sdist with not one `android`, `ios_` or `none-any` filename
among them; `pip download` for cp312 and cp314 × arm64-v8a, armeabi-v7a, x86_64, iOS device and iOS
x86_64 simulator returned this index's wheel 10 times out of 10.

**Android linkage.** `DT_NEEDED` on each of `fuzz_cpp`, `process_cpp_impl`, `utils_cpp`,
`distance/_initialize_cpp` and `distance/metrics_cpp` is exactly `libpython3.<minor>.so`,
`libm.so`, `libc++_shared.so`, `libdl.so`, `libc.so`, with no `SONAME`, `RPATH` or `RUNPATH` —
identical on all three ABIs. **No `libatomic`, on any ABI including armeabi-v7a**: nothing names it
in `DT_NEEDED`, and no `__atomic_*` or `__sync_*` symbol is undefined in `fuzz_cpp` or
`process_cpp_impl` on the 32-bit slice. Every `PT_LOAD` segment is `0x4000`-aligned on all three
ABIs, for all five extensions and, on x86_64, the three extra ones. `flet-libcpp-shared` ships one
file, `opt/lib/libc++_shared.so`, whose size is per-ABI — 1,292,904 bytes on arm64-v8a, 872,872 on
armeabi-v7a and 1,252,080 on x86_64, the same in the pinned floor and in the current build — and
serious_python's Gradle `copyOpt_<abi>` task puts it in `jniLibs/<abi>/` under that basename, which
is what makes the bare `DT_NEEDED` entry resolve.

**iOS linkage.** `otool -hv` on all five reports `MH_MAGIC_64 ARM64 DYLIB … NOUNDEFS DYLDLINK
TWOLEVEL`, so none needs the `MH_BUNDLE` → `MH_DYLIB` conversion some CMake-built recipes do at
packaging time, and none depends on a sibling: `otool -L` lists only `/usr/lib/libc++.1.dylib`,
`/usr/lib/libSystem.B.dylib` and the module's own `@rpath/<name>.so`. `nm -m` marks 140 symbols
"dynamically looked up" in `fuzz_cpp`, 176 in `process_cpp_impl`, 101 in `utils_cpp`, 166 in
`_initialize_cpp` and 147 in `metrics_cpp`, and **every one of them is a `_Py*` entry point** — the
libc++ and libSystem symbols are all two-level bound. There is no `@rpath/Python.framework/Python`
load command, unlike [`shapely`](../shapely) and [`orjson`](../orjson) on this same index.

**GIL and thread symbols, which is the evidence behind [Threading](#threading).**
`process_cpp_impl` is the only module importing `PyEval_SaveThread`/`PyEval_RestoreThread`, and the
only one importing `pthread_create` and carrying Taskflow (the mangled name `tf8Executor` appears
12 times in its strings on Android arm64-v8a). `fuzz_cpp` and `distance/metrics_cpp` import only
`PyGILState_Ensure`/`PyGILState_Release`; `utils_cpp` and `distance/_initialize_cpp` import
neither. Same picture on iOS via `nm -m`. The release is not on the `extract` path, which is why
the measured speedups are flat.

**The x86 extras.** Upstream's `src/rapidfuzz/CMakeLists.txt` gates `_feature_detector_cpp` and the
SIMD targets on `RAPIDFUZZ_ARCH_X64 OR RAPIDFUZZ_ARCH_X86`, so PyPI's `manylinux_2_27_x86_64` wheel
and this index's Android x86_64 slice both carry eight modules while every ARM slice carries five.
The iOS x86_64 simulator slice carries six: the detector is built, the SIMD kernels are not.

**Sizes**, the table behind [App size](#app-size). Bytes, so decimal MB divides by 10⁶ and a `du -h`
re-measurement will read about 5% lower.

| slice | wheel | unpacked | the extensions |
| --- | ---: | ---: | ---: |
| Android arm64-v8a | 1,376,169 | 4,875,335 | 4,579,080 |
| Android armeabi-v7a | 1,954,947 | 4,508,833 | 4,212,576 |
| Android x86_64 | 3,565,912 | 11,324,284 | 11,027,720 |
| iOS arm64 (device) | 1,241,148 | 4,863,741 | 4,556,240 |
| iOS arm64 (simulator) | 1,289,267 | 4,896,484 | 4,588,976 |
| iOS x86_64 (simulator) | 2,007,331 | 6,718,001 | 6,410,400 |

The non-extension payload is constant everywhere: 234,700 bytes of `.py` (174,569 of it the 16
pure-Python fallback modules that only ever run if the extensions fail), 53,740 bytes of `.pyi` and
1,246 bytes of the PyInstaller hook package.

### Upgrade hazards

- **`tests/test_rapidfuzz.py`'s docstring for `test_process_extract_one` claims
  `process_cpp_impl` links "libatomic for 64-bit atomics" on armeabi-v7a, and the shipped v7a wheel
  has no such dependency.** (The NDK's libatomic is a static `.a`, so if it were linked it would
  leave no runtime trace either way; there is nothing for a consumer to bundle.) Do not cite the
  tests for the dependency list; read `meta.yaml` and the wheel `METADATA`. Same class of drift as
  [`shapely`](../shapely)'s `flet-libcpp-shared` docstrings, and fixing it is a separate change.
- **The PR that added this recipe states, in its consumer notes, that the x86 SSE2/AVX2 kernels
  "aren't part of the ARM build".** True of ARM, but it reads as though they are absent from the
  mobile build entirely, and the x86_64 emulator slice does ship them.
- **The iOS ABI tag.** `rf_add_library` in `src/rapidfuzz/CMakeLists.txt` stamps the tag by passing
  `WITH_SOABI` to `python_add_library`, and it comes out empty on iOS and correct on Android; the
  cause was not chased further than that. If a bump changes it, the [iOS](#ios) paragraph about
  untagged basenames goes away — and if it changes in the other direction on Android, imports
  break, because Flet's `jniLibs` relocation keys on the tag.
- **Upstream publishing its own mobile wheels** would remove this recipe's reason to exist, and
  upstream making `numpy` an unconditional dependency would change both [Install](#install) and the
  example's dependency list.

### Re-verification checklist

A green build establishes almost none of what this page claims.

- **That the extensions are actually there.** The single most important property of this recipe is
  that `RAPIDFUZZ_BUILD_EXTENSION=1` is still honoured: without it scikit-build-core produces a
  *working* pure-Python wheel, and every test that only checks answers would still pass. `unzip -l`
  the wheel and count five `.so` on an ARM slice, eight on Android x86_64, six on the iOS x86_64
  simulator. `tests/test_cpp_extension_loaded` is the on-device half of this and is worth keeping
  first in the file.
- **The module names in the fallback check.** [Things to know](#things-to-know) tells app authors to
  test `not fuzz.ratio.__module__.endswith("_py")`. That depends on upstream's generated dispatch
  modules keeping the `_py` / `_cpp` / `_cpp_avx2` naming — re-run
  `grep -rn 'RAPIDFUZZ_IMPLEMENTATION' rapidfuzz` and check `fuzz.py`'s import ladder after a bump.
- **`Requires-Dist`, on both platforms.** Android must still carry `flet-libcpp-shared` and iOS must
  still carry no unconditional dependency; `numpy` must still be behind `extra == "all"` on both.
- **The linkage split.** Android: `DT_NEEDED` unchanged on all three ABIs, no `libatomic`, and 16 KB
  `PT_LOAD` alignment everywhere. iOS: still five `MH_DYLIB … NOUNDEFS TWOLEVEL` objects, `otool -L`
  still naming only libc++, libSystem and the module itself, and every "dynamically looked up"
  symbol still a `_Py*`.
- **Byte-identity with the desktop wheels.** Hash the `.py`/`.pyi` entries against the same-version
  PyPI macOS and manylinux wheels. A new data file or a diverging module would put both the
  no-`extract_packages` reasoning and "upstream's documentation applies" back in question.
- **Every measured number.** The extract-versus-loop ratios, the fallback costs, the threading
  figures, the `partial_ratio` scaling curve and the size table are all measured, most on desktop.
  Re-measure rather than scaling; the ratios transfer, the absolute times do not.
- **The two claims a wall-clock benchmark cannot check.** [Threading](#threading) says the scorers
  hold the GIL and only `cdist` releases it — that needs a canary thread run against *both* a
  GIL-holding and a GIL-releasing control, because a speedup ratio alone cannot tell the two apart.
  [Things to know](#things-to-know) says `WRatio` enters the `partial_ratio` blow-up at
  `len_ratio >= 1.5`; that constant lives in upstream's `WRatio`, so bisect it again (4,000
  characters against 5,990 versus 6,000 separates the two sides by ~1,500×) rather than assuming it
  held.
- **The behavioural gotchas.** Case sensitivity, the default `limit=5`, `score_cutoff`'s per-scorer
  scale, `processor=` being applied to the query, and the silent handling of `None` choices are all
  properties of upstream's Python layer, so a bump can move any of them without the build noticing.
  They are the most consumer-visible claims on this page and `tests/` asserts none of them.

### Coverage gaps

`tests/test_rapidfuzz.py` covers import, the `fuzz_cpp` canary, `Levenshtein.distance` and
`process.extractOne` — presence, essentially. Nothing on device exercises the scorer-choice
guidance, the case-sensitivity trap, `score_cutoff`, `cdist` or the numpy boundary, and every
timing on this page is a desktop timing; the [`fuzzy-search`](examples/fuzzy-search) example is
what puts device numbers on a screen.

Worth adding, in rough order of value: an assertion that `fuzz.ratio.__module__` does not end in
`_py`, which is the one failure mode that otherwise turns a broken build into a slow app rather
than a red test; a `processor=default_process` case proving the case-sensitivity fix works on
device; and one `process.cdist` call under a `pytest.importorskip("numpy")`. Per the repo's test
convention, assert relationships rather than version numbers — the version belongs on the example's
header line, not in an assertion a bump has to chase.
