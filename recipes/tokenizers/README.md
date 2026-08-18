# tokenizers

[`tokenizers`](https://huggingface.co/docs/tokenizers/index) is Hugging Face's tokenizer
library: a Rust core behind a PyO3 binding, shipped here as **one** extension module that
links nothing but the interpreter, the platform's C and C++ runtimes and — on iOS —
`libiconv`. It turns text into token ids and back, and it does the whole job locally:
training, encoding, decoding, serialising a tokenizer to a file and loading it again, with
no model download anywhere in that list.

On a phone that is worth having for three reasons. Token counting is the only honest answer
to *"will this prompt fit in the model's context?"*, and doing it on device means you can
answer it before you spend a request. Splitting a long document into windows needs the same
count. And a tokenizer you train yourself, on text your app already has, is one JSON file
you write at runtime rather than a model you have to ship or fetch.

It is published for **both platforms** — every Android ABI Flet builds for (arm64-v8a,
armeabi-v7a, x86_64) plus iOS device and both simulator slices — on Python 3.12, 3.13 and
3.14. What is worth reading before you use it is which parts stay offline (nearly all of
them), what comes along in the dependency tree (more than you expect), and a set of API
shapes that fail quietly rather than loudly.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "tokenizers",
]
```

**It does not come alone.** `huggingface-hub` is an unconditional `Requires-Dist` of the
wheel on both platforms — it is installed whether or not your app ever calls
`from_pretrained`. Resolving the way `flet build` does (`pip install --dry-run
--only-binary=:all: --platform … --extra-index-url https://pypi.flet.dev/`) pulls **15
wheels** for Android arm64-v8a — 4.72 MB on 3.12, 4.86 MB on 3.13 and 3.14 — of which
tokenizers is 2.61 MB either way: PyYAML (and the `flet-libyaml` it needs), certifi,
charset-normalizer, filelock,
`flet-libcpp-shared`, fsspec, huggingface-hub, idna, packaging, requests, tqdm,
typing-extensions and urllib3. iOS resolves the identical set minus `flet-libcpp-shared`.
Nothing removes them — they are metadata, not a choice — but `import tokenizers` never
imports `huggingface_hub`, so they cost bytes rather than startup time.

**Consider pinning `huggingface-hub` anyway.** The version that resolves for mobile is
**0.31.4**, not the current 1.x: `huggingface-hub >= 1.0` requires `hf-xet`, which publishes
no Android or iOS wheel at all, so pip backtracks through 88 versions of `huggingface_hub`
before it finds one that resolves. Adding `"huggingface-hub==0.31.4"` to your own
dependencies drops those 88 metadata fetches to 1 and produces a byte-identical install set.
Ask for 1.x explicitly — `huggingface-hub==1.27.0` — and the resolve fails outright with
`Could not find a version that satisfies the requirement hf-xet<2.0.0,>=1.5.2 … (from
versions: none)`.

**No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed for `import tokenizers`** — but there is one submodule it does not cover.
The package ships exactly one data file, `tokenizers/tools/visualizer-styles.css`, and
`tokenizers/tools/visualizer.py` opens it relative to `__file__` *at module import*.
Nothing else in the package touches `__file__`, `importlib.resources`, `pkgutil` or
`pkg_resources`, and the top-level `__init__` imports only `enum`, `typing`,
`.tokenizers` and `.implementations` — so plain `import tokenizers` never goes near it. The
one import that does, `tokenizers.tools`, is the shape Android's zipped site-packages cannot
serve, and would need `extract_packages = ["tokenizers"]`. What it offers is
`EncodingVisualizer`, which returns an HTML string — a notebook tool rather than anything a
Flet screen consumes — so the practical advice is not to import it. (Untested on device: the
reasoning is from the wheel's own source, not from a run.)

**Every slice a Flet build asks for exists**, on each of the three interpreters, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The index also carries a 32-bit `android_24_x86` wheel on 3.12 that
3.13 and 3.14 do not have, and that asymmetry costs nothing: `flet build` resolves Android
wheels for `arm64-v8a`, `armeabi-v7a` and `x86_64` only — there is no 32-bit x86 Android
target — so nothing ever asks for it. `Requires-Python` in the wheel is upstream's `>=3.10`.

## Storage

A tokenizer is one JSON file, and
[`Tokenizer.save`](https://huggingface.co/docs/tokenizers/api/tokenizer) /
`Tokenizer.from_file` are the whole API for it:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "models", "trained.json")
os.makedirs(os.path.dirname(path), exist_ok=True)   # save() will not create it
tokenizer.save(path)
tokenizer = Tokenizer.from_file(path)
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the app-private directory that is never auto-deleted and is included in backups — the
right home for a tokenizer you trained, since retraining it is the only way to get it back.
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
suits one you can re-derive cheaply.

Two things about `save()` that bite once each:

- **It does not create the parent directory.** Saving into a subdirectory that does not exist
  raises a bare `Exception: No such file or directory (os error 2)` — not an `OSError`, so
  `except OSError` does not catch it. `os.makedirs(..., exist_ok=True)` first.
- **`pretty` defaults to `True`.** `save(path, pretty=False)` roughly halves the file: 5,874
  bytes against 2,982 for the same small trained tokenizer, and 17,842 bytes for the one the
  example trains. Both reload identically; the only cost of `False` is that the file stops
  being readable by eye.

`Tokenizer.to_str()` / `Tokenizer.from_str()` are the same round trip in memory if you would
rather keep it in a database column or a preferences blob — verified to give identical ids
back.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`train-and-count`](examples/train-and-count) — trains a byte-level BPE on device, then
  checks round trips, token budgets, offsets and a save/reload cycle.

## Threading

**The batch calls release the GIL; one `encode` or `decode` holds it for nearly the whole
call.** Measured by the longest stall a canary thread suffers while the call runs — a
canary that never gets a turn is a UI thread that never gets a frame — with
`RAYON_NUM_THREADS=1` so CPU contention could not be mistaken for the GIL. The first two
rows are the harness checking itself: a call known to release must sit near 0 and one known
to hold must sit near 1, or nothing below them means anything. Median of five runs, desktop
CPython 3.14 on a 10-core host:

| call | duration | longest canary stall | stall ÷ call |
| --- | --- | --- | --- |
| `hashlib.sha256` of 30 MB (releases) | 18 ms | 0.1 ms | 0.00 |
| `sum(range(60_000_000))` (holds) | 289 ms | 283 ms | 0.98 |
| `encode_batch`, 30k strings | 386 ms | 14 ms | 0.04 |
| `encode_batch_fast`, 30k strings | 270 ms | 2 ms | 0.01 |
| `decode_batch`, 8k id lists | 23 ms | 1 ms | 0.06 |
| `train_from_iterator`, 20k lines | 1085 ms | 10 ms | 0.01 |
| `encode` of one 47 KB document | 13 ms | 7 ms | 0.52 |
| `encode` of one 483 KB document | 97 ms | 90 ms | 0.93 |
| `encode` of one 1085 KB document | 225 ms | 217 ms | 0.96 |
| `decode` of one 95k-id list | 14 ms | 8 ms | 0.55 |

So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) buys
real concurrency for `encode_batch`, `decode_batch` and training, and buys you **nothing**
for one big `encode` — the ratio climbs towards 1 as the document grows, so moving a 200 ms
encode onto a worker freezes the UI for about 200 ms anyway. **Do not read the 0.52 and 0.55
rows as "half speed in general."** Both are 13–14 ms calls, and below about 50 ms this ratio
is dominated by the canary's own scheduling jitter rather than by the GIL: independent
re-runs of those two rows on a comparable host came back at 1.0 and 1.0, not at a half. The
rows worth quoting are the long ones. Batch the work instead — hand `encode_batch` a list
rather than looping `encode` over it, which also costs almost nothing on the UI thread: the
same 3000 strings
encoded one at a time in a Python loop stall the canary 6 ms, because the GIL is dropped
*between* calls, not inside them.

**Batch calls also spin up rayon worker threads sized to the core count** — verified: the
process holds one thread until the first tokenizers call, then ten on a 10-core host, and
two under `RAYON_NUM_THREADS=2`. That is a separate effect from the GIL and looks the same
from the outside. With rayon left at its default `encode_batch` runs 2.3× faster in wall
time but the canary drops from 89% to **51%** of its idle rate — the GIL behaviour did not
change, the cores did. If a batch job must not starve the Flutter UI thread, set
`RAYON_NUM_THREADS` or `TOKENIZERS_PARALLELISM=false` in the environment before importing
tokenizers; leave them alone when throughput matters more.

The two standing Flet caveats apply either way: `run_thread` never retrieves the worker's
future, so an exception raised inside one surfaces nowhere at all — wrap the body in
`try/except Exception` — and auto-update does not reach background threads, so end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

`Tokenizer` also carries a native async surface — `async_encode`, `async_encode_batch`,
`async_encode_batch_fast` and `async_decode_batch` — which agree with the synchronous
results. They must be awaited from inside a running loop; calling one outside a loop raises
`RuntimeError: no running event loop` before it does any work.

## Android notes

The extension links five libraries, and the list is identical on all ten published Android
slices — four ABIs on 3.12, three on 3.13 and 3.14: `libpython3.<minor>.so`,
**`libc++_shared.so`**, `libdl.so`, `libm.so` and `libc.so`. Nothing is vendored into the
wheel and the `.so` carries no `SONAME`.

`libc++_shared.so` is the reason the Android wheels carry an extra
`Requires-Dist: flet-libcpp-shared (>=27.2.12479018)` that the iOS wheels do not. It comes
along on its own — a resolve picks up `flet-libcpp-shared 27.3.13750724`, whose entire
payload is a single 1,292,904-byte `opt/lib/libc++_shared.so` — so there is nothing to
configure. There is no jniLibs name collision to worry about either: the extension is a
*submodule* (`tokenizers/tokenizers.abi3.so`), not a top-level module named after the
package, and `libc++_shared.so` is the only library tokenizers brings with it.

All four `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires.

armeabi-v7a exists only because of `patches/mobile.patch`, and it is the smallest slice by a
clear margin — 6.24 MB of extension against arm64-v8a's 7.20 MB.

## iOS notes

**The extension needs no fixing up.** All three iOS slices are already `MH_DYLIB` marked
`NOUNDEFS` (`otool -hv`), which is the filetype Flet's iOS packaging needs, so the
`MH_BUNDLE` conversion other recipes on this index depend on never engages here. Its
linkage is three OS libraries plus Flet's Python framework:
`@rpath/Python.framework/Python`, `/usr/lib/libc++.1.dylib`, `/usr/lib/libiconv.2.dylib` and
`/usr/lib/libSystem.B.dylib`. There is no companion wheel — iOS uses the system's own C++
runtime where Android needs `flet-libcpp-shared`.

**`otool -L` prints a build-machine path first and it is not a missing dependency.** The
`LC_ID_DYLIB` install name is
`/Users/runner/work/mobile-forge/…/target/aarch64-apple-ios/release/deps/libtokenizers.dylib`
— an artefact of how maturin links the Rust cdylib. Python loads the extension by file path
and nothing resolves that install name, so it is harmless; it is just the first line you see
and the easiest one to misread.

**The deployment-target load command is not the same on all three slices**, and none of them
says 13.0 despite the `ios_13_0` in every filename: the device and x86_64-simulator slices
carry the older `LC_VERSION_MIN_IPHONEOS version 10.0`, while the arm64 simulator carries
`LC_BUILD_VERSION platform 7, minos 14.0` — below the tag on two slices and above it on the
third. It bites nothing on a phone Flet supports, and it is recorded here because a slice
comparison that opens one binary and generalises will get this wrong. Same discrepancy as
[`protobuf`](../protobuf) documents.

**iOS carries about 17% more native code than Android arm64** for the same source: 8,448,044
bytes against 7,201,688 on 3.14. Every `.py` file is identical between the two. The other
platform difference in the metadata is cosmetic but worth knowing on a bump — forge rewrites
`Requires-Dist` on the Android wheels and drops the long description with it, leaving a
1,818-byte `METADATA` where iOS keeps the full 9,830-byte one, so the two files are not
comparable byte-for-byte.

## Things to know

- **Every error it raises is a bare `Exception`, including file I/O.** `Tokenizer.from_file`
  on a missing path gives `Exception: No such file or directory (os error 2)`, on malformed
  JSON `Exception: EOF while parsing a value at line 1 column 0`, on well-formed JSON that is
  not a tokenizer `Exception: invalid type: sequence, expected struct Tokenizer at line 1
  column 1`; `from_str("garbage")` gives `Exception: expected value at line 1 column 1`; and
  `save()` into a missing directory gives the `os error 2` message again. Their MRO is
  `Exception < BaseException < object` and nothing else — so `except OSError`,
  `except FileNotFoundError` and `except ValueError` all miss them. Catch broad `Exception`
  around every `from_file` / `from_str` / `save` / `train` call, and show `str(error)`: the
  Rust messages are specific and worth surfacing. This matters more in Flet than elsewhere,
  because an unhandled exception in an event handler makes Flet send `SESSION_CRASHED`.
- **A byte-level BPE trained without `initial_alphabet=ByteLevel.alphabet()` silently drops
  characters.** It does not raise and it emits no `[UNK]` — the text simply comes back
  shorter. Trained on the example's 2,000-line ASCII corpus with no initial alphabet
  (vocabulary reaches 232), `decode(encode("Zürich — 42 €"))` returns `'rich   '`,
  `"a\tb\nc"` returns `'abc'`, `"hello,  world!"` returns `'hello  world'` and the emoji
  simply disappears. Pass the full alphabet — it costs about 256 vocabulary slots and makes
  the round trip lossless for arbitrary input, including tabs, newlines, accents, currency
  symbols and emoji, none of which the corpus ever contained.
- **`Whitespace` with the default decoder is lossy by construction**, so
  `decode(encode(s)) == s` fails for anything but single-spaced plain words. Punctuation
  becomes `[UNK]` — and `decode` skips special tokens by default, so it does not even leave
  a marker behind: on the same corpus `'hello,  world!'` tokenises to
  `['he', 'l', 'l', 'o', '[UNK]', 'w', 'o', 'r', 'ld', '[UNK]']` and decodes to
  `'he l l o w o r ld'`, and `"a\tb\nc"` comes back as `'a b c'`. An in-corpus sentence
  round-trips perfectly, which is what makes this easy to build by accident; it is the shape
  of this recipe's own test, which asserts substring containment for exactly that reason. For
  an exact round trip use
  [`pre_tokenizers.ByteLevel(add_prefix_space=False)`](https://huggingface.co/docs/tokenizers/api/pre-tokenizers)
  with [`decoders.ByteLevel()`](https://huggingface.co/docs/tokenizers/api/decoders) and the
  full initial alphabet. Reserve `Whitespace` for word-level analysis where losing
  punctuation is the intent.
- **An untrained tokenizer encodes to an empty list instead of failing.**
  `Tokenizer(BPE()).encode("hello").ids` is `[]`, no exception. If training silently produced
  nothing, every token count on screen reads 0 and nothing says why. Assert
  `tokenizer.get_vocab_size() > 0` after training and treat an empty encode as an error
  state.
- **Byte-level offsets are not a partition of the string.** Each `(start, end)` in
  [`Encoding.offsets`](https://huggingface.co/docs/tokenizers/api/encoding) indexes the
  *original* text and is individually correct, so `source[start:end]` is that token's source
  substring and `char_to_token` / `token_to_chars` round-trip. But a multi-byte character
  produces several tokens that all carry the **same** range: on `'Zürich €'` the tokens `'Ã'`
  and `'¼'` both carry `(1,2)`, and `'â'`, `'Ĥ'` and `'¬'` all carry `(7,8)`, so
  `"".join(s[a:b] for a, b in e.offsets)` gives `'Züürich €€€'` where `decode(e.ids)` gives
  `'Zürich €'`. Use offsets to highlight or locate; use `decode` to rebuild.
- **`Encoding.overflowing` stays empty under `enable_truncation` — truncation just drops the
  tail.** `max_length=8` on a 320-token input gives `kept=8, overflowing=0`, and adding
  `stride`, `strategy="longest_first"` or `direction="left"` changes nothing about that;
  `encode_batch` under the same setting returns `[8, 2]` for a long and a short input. A
  reader expecting the chunks for a context window gets one truncated encoding and loses the
  rest of the document silently. Chunk by slicing the id list yourself —
  `[ids[i:i + n] for i in range(0, len(ids), n)]` — which is exact in ids, trivially: flattening
  a slicing of a list always reproduces the list. **Rebuilding the text is where it stops being
  exact.** `"".join(tok.decode(w) for w in windows)` matches the original only while no window
  boundary lands inside a multi-byte character, and a boundary that does costs you the character:
  on `'the harbour crane measures Zürich twice before dawn.'` at `n=1` the join comes back with
  `'Z��rich'` in it, and a paragraph of `'Zürich — 42 € café naïve'` still fails at
  `n=64`. ASCII never trips it, which is what makes it easy to ship. Decode the rejoined id list,
  not the windows one at a time.
- **Token count is `len(tokenizer.encode(s).ids)`, and it depends on the training corpus far
  more than on the string.** Against a tokenizer trained on 2,000 lines of generated English,
  an in-domain sentence of 36 characters costs 7 tokens while `'hello world'` — 11 characters
  the corpus never contained — costs 8, and `'Zürich — 42 €'` costs 17 for 13 characters.
  Non-ASCII is expensive under a byte-level model because each character becomes several byte
  symbols.
- **`vocab_size` is a ceiling, not a target.** Corpus variety is the real cap: on 2,000 lines
  drawing on 56 distinct words, `BpeTrainer(vocab_size=2000)` produced a vocabulary of 459,
  and quadrupling the corpus moved it only to 488. If you need a larger vocabulary, feed
  more varied text, not a larger number.
- **`from_pretrained` is the one thing that needs the network, and it fails in two different
  ways.** It is implemented in Rust and imports `huggingface_hub` at call time — no shipped
  Python file mentions it, and nothing imports it at module import. With the package missing
  it raises a plain `ModuleNotFoundError`; with the package present and no network it raises
  `huggingface_hub.errors.LocalEntryNotFoundError` after about 0.7 s. Both are ordinary
  catchable exceptions — `LocalEntryNotFoundError`'s MRO passes through `FileNotFoundError`,
  `OSError` and `ValueError` on its way to `Exception` — so `except Exception` covers them.
  Everything else in the library is fully offline: the four trainers (`BpeTrainer`,
  `WordPieceTrainer`, `UnigramTrainer`, `WordLevelTrainer`) train from an in-memory iterator,
  and `save` / `from_file` need nothing but the filesystem.
- **`encode_batch_fast` shaves 15–25% on short sequences.** All it skips is computing
  offsets, so the saving is whatever share of the work that was: 10,000 short sequences took
  96.8 ms against 82.6 ms on one corpus and 98.1 ms against 74.3 ms on another. Reach for it
  when you are counting tokens and will never look at `Encoding.offsets`. Throughput on one
  large document is around 5 M characters per second — 130,001 tokens out of 585,000
  characters in 115 ms. All desktop figures; measure on the device before deciding what fits
  in a frame.
- **No free-threaded slices.** The published set is cp312, cp313 and cp314 only; there is no
  `cp313t`/`cp314t` wheel, so the free-threading notes in upstream's own `__init__` docstring
  do not describe anything you can build for a phone today.
- **Size: 2.57–3.06 MB to download, 6.60–9.13 MB unpacked, and 95% of it is the extension.**
  Per slice, on Python 3.14 (3.12 is within 352 bytes of it on Android arm64-v8a):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 2.61 MB | 7.56 MB | 7.20 MB |
  | Android armeabi-v7a | 2.57 MB | 6.60 MB | 6.24 MB |
  | Android x86_64 | 2.79 MB | 8.10 MB | 7.74 MB |
  | iOS arm64 (device) | 2.87 MB | 8.81 MB | 8.45 MB |
  | iOS arm64 (simulator) | 2.93 MB | 8.86 MB | 8.50 MB |
  | iOS x86_64 (simulator) | 3.06 MB | 9.13 MB | 8.77 MB |

  Of the 358,384 bytes that are not the extension on Android arm64-v8a, **143,882 are a
  CycloneDX SBOM** under `dist-info/sboms/` and 140,281 are `.pyi` stubs; the Python layer
  itself is only 64,595 bytes plus the 4,850-byte visualiser stylesheet. serious_python's
  mobile cleanup list carries `**.pyi` and `**.typed`, so the stubs and `py.typed` are
  dropped on the way into the app and nothing misses them; the SBOM is not on that list.

## Build notes (maintainers)

`patches/mobile.patch` explains what it changes and why it was preferred to
`excluded_arches`, and `meta.yaml`'s one uncommented setting
(`_PYTHON_SYSCONFIGDATA_NAME`) is the shared Rust/maturin idiom that appears verbatim in 16
other recipes here, so neither needs re-explaining. What is left is the bump checklist — and
a green build verifies almost none of what this page promises.

- **The patch is the armeabi-v7a slice.** The published index is the check that it still
  works: if a bump drops `android_24_armeabi_v7a` from the wheel list while the other ABIs
  survive, the `AtomicU64` import came back somewhere the patch does not reach. Note this
  recipe made the opposite choice from [`polars`](../polars), which carries
  `excluded_arches: [armeabi-v7a]` for the same error — so a future maintainer weighing that
  option should know it was considered and rejected here.
- **Re-check the dependency tree, not just the build.** `huggingface-hub` is an upstream
  `Requires-Dist`, and both its 0.31.4 resolution and the 15-wheel download figures in
  [Install](#install) are properties of *its* dependency graph, which moves without anyone
  touching this recipe. The `hf-xet` blocker in particular could disappear the day `hf-xet`
  publishes a mobile wheel. Re-run the pip dry-run for one Android and one iOS slice on a
  bump.
- **Check the slice list against what `flet build` actually asks for**, not against the
  index. serious_python resolves Android wheels for `arm64-v8a`, `armeabi-v7a` and `x86_64`
  only (its `platforms["Android"]` map), so an index gap outside those three — the 32-bit
  `android_24_x86` slice that exists on 3.12 and not on 3.13/3.14 — is invisible to a
  consumer, and a gap *inside* them is a hard build failure. [Install](#install) states the
  first; a bump must re-check the second.
- **`tests/test_tokenizers.py` covers the train/encode/decode path only, and deliberately
  asserts substring containment** because it uses the lossy `Whitespace` shape. It does not
  check the byte-level round trip, the offsets behaviour, `save`/`from_file`, or that the
  errors are still bare `Exception`s — all of which [Things to know](#things-to-know)
  asserts. The [`train-and-count`](examples/train-and-count) example checks every one of them
  on screen, which is why it is the thing to run after a bump.
- **No on-device run backs the numbers on this page.** Every behavioural figure above came
  off a desktop install of exactly `tokenizers==0.23.1` plus `huggingface-hub==0.31.4`. The
  only on-device evidence that exists is `tests/test_tokenizers.py`, which the workflow runs
  on an emulator/simulator whenever this recipe is in a run's package set — note that
  `SMOKE_TEST_PACKAGES` is only the *fallback* recipe list, so absence from it says nothing
  about whether the test ran. The bridge from desktop is narrow but real — the shipped `.py`
  files are byte-identical on both platforms and the behaviour lives in the Rust core, one
  source tree for every slice — but a phone's timings are its own. The example's header
  lines are built to be the thing you read off the screen.
- **The timing and size numbers are measured, not estimated.** Re-measure them on a bump
  rather than adjusting them by eye. The GIL table has two traps, and both produce a
  plausible middle number instead of an obvious failure: leaving rayon at its default turns
  a GIL-released call into something that looks GIL-bound, and sizing the single-`encode`
  row too small makes a call that holds the GIL throughout look like it only holds it half
  the time. Keep the two control rows — they are what tells a real result from either.
