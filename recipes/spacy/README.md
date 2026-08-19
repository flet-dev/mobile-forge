# spacy

[`spaCy`](https://spacy.io/) is the industrial NLP library: a fast Cython tokenizer, a
`Doc`/`Span`/`Token` object model with exact character offsets, rule engines
([`Matcher`](https://spacy.io/api/matcher), [`PhraseMatcher`](https://spacy.io/api/phrasematcher),
[`EntityRuler`](https://spacy.io/api/entityruler)) and a slot for a statistical pipeline on top.

**The wheel contains no model, and nothing in it opens a connection.** That is the first thing to
know, and it cuts both ways. Everything the tokenizer needs is ordinary Python source —
[`spacy.blank("en")`](https://spacy.io/api/top-level#spacy.blank) gives you a working tokenizer,
`Vocab`, `StringStore`, all the lexical attributes and every rule component, offline, on an
aeroplane, with nothing but the wheel installed. What it does *not* give you is a tagger, parser,
lemmatizer, named-entity recogniser or word vectors: those live in a separate 12.8 MB–457 MB model
that you have to get onto the device yourself. See [Storage](#storage) for exactly what that
means.

Reaching for it on a phone makes sense when the answer is rules over text you can describe —
splitting a receipt into sentences, pulling known product names out of a note, finding amounts and
dates, normalising a share-sheet payload — and you want offsets that slice the original string
back exactly. It is a heavy dependency for that: 44–45 wheels and 21.6–24.8 MB of downloads (see
[Install](#install)), against a `re` module that is already there. Weigh it before you commit.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "spacy",
]

[tool.flet.android]
extract_packages = ["spacy", "thinc"]
```

**The [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is not
optional on Android**, and it is the one thing you cannot discover by running the app on your Mac.
`import spacy` reads three files through `Path(__file__).parent` while the package is still
importing — `spacy/default_config.cfg` (`spacy/language.py:78`),
`spacy/cli/templates/quickstart_training_recommendations.yml` (`spacy/cli/init_config.py:25`) and
`thinc/backends/_custom_kernels.cu` (`thinc/backends/_custom_kernels.py:12`). Under Flet 0.86
Android site-packages is a *stored* zip, where such a path is not a directory: importing a package
of that shape out of a stored zip raises
`NotADirectoryError: [Errno 20] Not a directory: '…/sitepackages.zip/<pkg>/default_config.cfg'`,
before a line of your code runs. The recipe's own `meta.yaml` declares the same two packages, but
that value reaches only this repository's on-device test app — it does not travel to `pip install`
consumers, and `flet_cli`'s `ANDROID_DEFAULT_EXTRACT_PACKAGES` is empty, so your `pyproject.toml`
has to say it. iOS keeps a real site-packages directory and needs nothing, which also means a
green iOS-simulator run proves nothing about this.

Eleven more platform-tagged wheels come along, and none of them needs configuring. `thinc`,
`blis`, `cymem`, `preshed`, `murmurhash` and `srsly` are spaCy's own Cython stack; `numpy`,
`pydantic-core`, `charset-normalizer` and `markupsafe` arrive through `Requires-Dist`; and on
Android only, `flet-libcpp-shared` comes with them (see [Android notes](#android-notes)).

A bare `spacy` resolves on **every slice a `flet build` can produce**. Measured one resolve per
slice the way `flet build` does it (`pip download --only-binary :all: --extra-index-url
https://pypi.flet.dev --platform <tag> --python-version <ver>`): the three Android ABIs Flet
0.86.5 targets and all three iOS slices, on Python 3.12, 3.13 and 3.14 — eighteen for eighteen.
There is nothing below 3.12: a cp311 resolve reports *no matching distribution* for `spacy`
itself.

Budget for the size before anything else. Each of those resolves is **45 wheels on Android and 44
on iOS** (the difference is `flet-libcpp-shared`), and the download totals run 21,611,446 –
24,846,742 bytes depending on slice. On Android arm64 / cp314, 17,850,099 of that is the 12
platform-tagged wheels and 4,736,948 is 33 pure-Python ones; the single largest are `numpy`
(6,849,496), `spacy` (5,723,650), `pydantic_core` (1,873,194) and `blis` (1,178,323).

**This wheel fixes an upstream packaging bug, so it imports where the PyPI one does not.**
spaCy 3.8.13 calls `from click import NoSuchOption` in `spacy/cli/_util.py:18` but never declares
`click` — it relied on `typer` pulling it transitively, and typer dropped that dependency. A fresh
`uv pip install spacy==3.8.13` today resolves 43 distributions with typer 0.27.1 and no click, and
`import spacy` then dies with `ModuleNotFoundError: No module named 'click'` — on the desktop too.
The mobile wheels carry `Requires-Dist: click>=8.0.0`, which upstream's do not.

## Storage

spaCy writes nothing of its own: no cache directory, no download on first use, no lock file. The
only files it reads are the three package-internal ones named above, plus every installed
distribution's `entry_points.txt` (44 of them in a plain spaCy environment) during
[`catalogue`](https://github.com/explosion/catalogue)'s registry scan. So there is nothing to put
in app storage until you decide you want a model.

**What works with no network at all.** Traced under a `sys.addaudithook`, which sees the events
CPython raises inside `_socket` itself, so a module that grabbed the symbol early cannot slip past
it. One socket *is* created at import — `urllib3/util/connection.py:137` runs
`HAS_IPV6 = _has_ipv6("::1")`, which opens an `AF_INET6` socket and `bind()`s it to loopback inside
a bare `except Exception: pass`. Nothing resolves a name and nothing connects:

| | network attempts |
| --- | --- |
| `import spacy` | 0 |
| `spacy.blank("en")` + sentencizer + EntityRuler over a document | 0 |
| `spacy.load("en_core_web_sm")` with no model present | 0 — raises `OSError [E050] Can't find model …` |
| `spacy.load("<a directory>")` | 0 |
| `spacy.cli.download("en_core_web_sm")` | 1 before the block bit — `raw.githubusercontent.com`, then a second host below |

Only the last one goes out, and nothing calls it for you — and a missing model is a loud `OSError`,
not a silent fetch, which is the behaviour you want on a phone. Note that a real download needs
**two** hosts, not the one the trace records: `spacy/about.py` points `__compatibility__` at
`raw.githubusercontent.com` and `__download_url__` at
`github.com/explosion/spacy-models/releases/download`, and the blocked socket raises on the first,
so the second never reaches the table. Allow-list both, if you allow-list anything.

**Getting a model onto the device.** The pipelines are
[not on PyPI](https://spacy.io/usage/models#download): `https://pypi.org/simple/en-core-web-sm/`
returns HTTP 200 and a valid 286-byte index listing zero files — the project exists and publishes
nothing — and `pypi.flet.dev` has no entry either. They are published only as GitHub release
assets, at these compressed sizes (`curl -sIL` on the 3.8.0 release URLs):

| pipeline | wheel |
| --- | --- |
| `en_core_web_sm` | 12,806,118 B |
| `xx_ent_wiki_sm` | 11,099,251 B |
| `en_core_web_md` | 33,480,380 B |
| `en_core_web_lg` | 400,658,291 B |
| `en_core_web_trf` | 457,421,864 B |

Those wheels are `py3-none-any` with **no `Requires-Dist` and no `Requires-Python` line at all**,
and they are ordinary zips. That matters because **`spacy.load()` accepts a bare unpacked
directory** — no installed package, no entry point. Unzipping `en_core_web_sm-3.8.0` and calling
`spacy.load("…/en_core_web_sm/en_core_web_sm-3.8.0")` loaded a full
`['tok2vec', 'tagger', 'parser', 'attribute_ruler', 'lemmatizer', 'ner']` pipeline in 0.18 s with
the network blocked, from a directory of 26 files totalling 15,231,350 bytes — on a development
machine. **Nothing here has run a statistical model on a device**: neither `tests/` nor the example
loads one, so treat the load time, the memory and the tagger/parser/NER output on a phone as
untested, and measure them before you ship one.

So the two routes are: **ship the unpacked directory with the app** — put it under your app's
`src/assets/` and read it back through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir), which
is read-only and replaced on every app update, the same route
[`tflite-runtime`](../tflite-runtime#storage) and [`ncnn`](../ncnn#storage) use for a model file —
or download it once on first run
into [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups — and
`spacy.load()` that path forever after. Do not put it in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
which the OS may purge, or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp),
which may vanish between launches. If instead you install a model as a *package*, add its name to
the same Android `extract_packages` list: its `__init__.py` calls
`get_model_meta(Path(__file__).parent)` at import, which is the identical zip failure.

**A rule-only pipeline is the cheap alternative, and it persists.**
`nlp.to_disk()` of `blank("en")` + sentencizer + EntityRuler wrote **95,394 bytes** across
`config.cfg`, `entity_ruler`, `meta.json`, `sentencizer.json`, `tokenizer` and `vocab`, and
`spacy.load()` of that directory restored the pipeline and its entities. 77,066 of that is the
tokenizer's exception table and 13,038 the `StringStore`, so the size barely moves with your
patterns — it goes to 95,705 once any document has been processed and then stays there. Processed
documents serialise far smaller: a [`DocBin`](https://spacy.io/api/docbin) of 200 copies of a
46-character sentence is 2,158 bytes, and of 200 *distinct* short sentences 6,001 — it stores token
indices against the shared `Vocab`, so the count that matters is how many strings are new.

The offline lemmatizer tables — what `[E1004]` asks for when you add a `lookup`-mode
lemmatizer — are a separate 98,458,367-byte `spacy-lookups-data` wheel on PyPI, and it is not on
`pypi.flet.dev`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`no-model-pipeline`](examples/no-model-pipeline) — a rule-based pipeline with no model at all,
  auditing its own tokenisation against a regex reconstruction.

## Threading

**A pipeline call holds the GIL for essentially all of its duration.** Measured on desktop with a
counting thread spinning beside one long call over 218,889 characters, against three controls —
a GIL-holding floor (`math.factorial`), an ordinary Python loop, and a GIL-releasing ceiling
(`hashlib.sha256`, over a pre-allocated buffer so the allocation is not in the timed region):

| main thread is running | counter, as a share of its undisturbed rate |
| --- | --- |
| `math.factorial` — floor, GIL never released | 2% |
| `nlp.make_doc(text)` — the tokenizer alone | 3% |
| `nlp(text)`, `blank("en")` with no components | 4% |
| `nlp(text)` + sentencizer | 6% |
| `nlp(text)` + sentencizer + `EntityRuler` | 11% |
| a pure-Python loop — ordinary bytecode, GIL shared fairly | 51% |
| `hashlib.sha256` — ceiling, GIL released | 101% |

Figures are CPython 3.12; 3.14 lands within two points of every row. spaCy is Cython, and Cython
that touches Python objects keeps the GIL, so the fullest rule pipeline sits nearer the floor than
the pure-Python control — about a fifth of what an ordinary Python loop leaves behind.
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is still where
the work belongs, because the handler returns immediately — but for the length of the call the rest
of your Python gets about a tenth of the interpreter: a second slider release, a button tap and any
other worker all effectively queue behind it. Size the document so the call is short, and expect a
device to be slower than these figures.

**Sharing one pipeline across threads held up, and bought nothing.** Three runs of 12 threads ×
500 documents against a single `blank("en")` + sentencizer + EntityRuler, with every document
carrying tokens no other thread used so the shared `StringStore` grew concurrently (to 19,864
entries), every result checked (exact reconstruction, expected entity, `vocab.strings[token.orth]`
round trip), and `sys.setswitchinterval(1e-6)` to give an unsafe mutation the best chance an
in-process test can give it: 0 errors and 0 wrong answers in all three. But eight threads doing
eight times the work took 8.3× as long as one, which is what the table above predicts — there is no
throughput to win.

**And `nlp.pipe` will not win it back either.** Over an *identical* 200-document corpus
[`nlp.pipe`](https://spacy.io/api/language#pipe) measured 0.96–1.03× a plain
`[nlp(t) for t in texts]` — at the default `n_process=1` it is that loop, with a tidier signature.
Per-document cost is set by document length (≈4 µs/token either way), not by how you iterate.
**Leave `n_process` at 1** regardless: `spacy/language.py:1612` hands off to
`_multiprocessing_pipe` for any other value, which forks worker processes via `multiprocessing`.
That is not something to try in an app runtime.

Two standing Flet rules apply on top: `run_thread` never retrieves the worker's future, so an
exception inside one surfaces nowhere at all — wrap the body, and catch broad `Exception`, because
spaCy raises its own error-coded `ValueError`s alongside plain ones. And auto-update does not
reach background threads, so end the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

## Android notes

**`extract_packages = ["spacy", "thinc"]` is required.** See [Install](#install); the symptom is
`NotADirectoryError` at import.

**`libc++_shared.so` comes with the wheel.** The Android `METADATA` carries
`Requires-Dist: flet-libcpp-shared (>=27.2.12479018)`, which the iOS one does not. It is
load-bearing: 45 of spaCy's 46 extensions name `libc++_shared.so` in `DT_NEEDED` (alongside
`libpython3.<minor>.so`, `libm`, `libdl` and `libc`), the exception being
`spacy/matcher/levenshtein`. Every `.so` in `cymem`, `preshed`, `murmurhash`, `srsly` and `thinc`
names it as well, and those five wheels carry the same `Requires-Dist` line; `blis` is the one
that does not, being pure C.

**Two extensions share a basename.** `spacy/pipeline/ner` and
`spacy/pipeline/_parser_internals/ner` are the only colliding `.so` basenames across the seven
wheels, and a plain `import spacy` loads both. Flet 0.86 relocates each extension into
`jniLibs/<abi>/` under a mangled name and leaves a per-module `.soref` marker at the original zip
path, which are distinct here — but a change to that naming is exactly the kind of serious_python
bump that would break this one package and nothing else, so it is worth re-checking.

**Python coverage differs by ABI.** cp312 ships four Android slices (`arm64-v8a`, `armeabi-v7a`,
`x86`, `x86_64`); cp313 and cp314 ship three, without `x86`. The rest of the chain — `blis`,
`thinc`, `cymem`, `preshed`, `murmurhash`, `srsly` — has the same tag set. `x86` is unreachable
from `flet build` anyway: flet-cli 0.86.5's `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM`
(`flet_cli/utils/android.py:3`) holds only the other three.

## iOS notes

**Nothing to configure, and no `flet-libcpp-shared`.** iOS site-packages stays a real directory,
so the three `__file__`-relative reads work and no `extract_packages` equivalent exists or is
needed. The C++ runtime comes from the OS: every one of the 46 extensions is a Mach-O ARM64
`MH_DYLIB` (`otool -hv`: `DYLIB … NOUNDEFS`), and `otool -L` across all 46 lists nothing but
`@rpath/Python.framework/Python`, `/usr/lib/libSystem.B.dylib` and — on 45 of them —
`/usr/lib/libc++.1.dylib`. None depends on a sibling extension, so there is no install-name
relocation problem of the kind [`pyarrow`](../pyarrow) needed.

**The iOS wheels are bigger.** 19,852,998 bytes unpacked against 15,814,431 on Android arm64-v8a,
with the 46 extensions accounting for 14,486,768 against 10,471,352. All three iOS slices are
published on cp312, cp313 and cp314.

**`require_gpu()` fails with a different message here.** `thinc/util.py:226` branches on
`platform.system() == "Darwin"`, and Flet's iOS runtime reports `"iOS"` (PEP 730), so iOS takes
the non-Darwin branch and raises *Cannot use GPU, CuPy is not installed* where a Mac says
*Cannot use GPU, PyTorch is not installed*. Same outcome, different text. Those two lines are the
**only** `platform.system()` gates in `spacy`, `thinc`, `srsly` and `blis` combined, so this is the
one place the iOS/Darwin difference can bite.

**There is no Accelerate path.** `thinc-apple-ops`, the Apple backend spaCy declares under
`extra == "apple"`, returns HTTP 404 on `pypi.flet.dev`. iOS gets the same generic BLAS Android
does — see [Things to know](#things-to-know).

## Things to know

- **`spacy.blank("<lang>")` is a complete tokenizer, and it is exact.** Over a 121-character test
  string it produced 30 tokens whose `text_with_ws` rejoined to the source character for character,
  with `Dr.` and `Corp.` kept whole (English tokenizer exceptions), `$4,500.00` split into `$` and
  `4,500.00` with `like_num=True` and `shape_='d,ddd.dd'`, and `acme.com` flagged `like_url=True`.
  Every `Span` sliced back out of the source by its own `start_char`/`end_char`. That, plus
  `Vocab`/`StringStore`, `Matcher`, `PhraseMatcher`, `EntityRuler`, `sentencizer`, `DocBin` and
  `to_disk`/`load`, is what you get for free.
- **Model-dependent *attributes* degrade silently; model-dependent *components* fail loudly.**
  This is the split worth memorising. On a blank pipeline `pos_`, `tag_`, `lemma_`, `dep_` and
  `str(token.morph)` all return `''` and `doc.ents` returns `()`, with no warning of any kind —
  a wrong empty answer that looks like a right one. Only `doc.sents` and `doc.noun_chunks` raise
  (`ValueError [E030]`, naming the sentencizer fix, and `[E029]`). Add a component that needs a
  model and it raises the moment it runs: `tagger`, `parser`, `ner`, `morphologizer`, `senter`,
  `tok2vec`, `spancat` and `trainable_lemmatizer` all give
  `ValueError [E109] Component '<name>' could not be run. Did you forget to call initialize()?`,
  `lemmatizer` gives `[E1004] Missing lemmatizer table(s)`, `entity_linker` gives `[E139]` and
  `textcat` gives *Cannot get dimension 'nO' for model 'sparse_linear': value unset*. In a Flet
  app an unhandled exception in a handler is a crash screen, so guard the call.
- **75 of the 79 bundled languages give a working blank pipeline with nothing extra installed.**
  Iterating every directory under `spacy/lang`: 75 tokenised successfully, including `zh` (whose
  default segmenter is per-character — `我喜欢北京天安门` → 8 tokens) and the multi-language `xx`.
  The four failures are `ja` (wants SudachiPy), `ko` (mecab-ko), `th` (PyThaiNLP) and `vi` (Pyvi),
  and each of those four returns HTTP 404 on `pypi.flet.dev`. Vietnamese has a way out that needs
  no extra dependency: `spacy.blank("vi", config={"nlp": {"tokenizer": {"use_pyvi": False}}})` tokenises
  fine.
- **`PhraseMatcher` matches nothing when the pattern tokenises differently from the text, and says
  nothing about it.** The classic case is case itself: `nlp.make_doc("ACME Corp. on")` gives
  `['ACME', 'Corp.', 'on']` but `nlp.make_doc("acme corp.")` gives `['acme', 'corp', '.']`, so
  `PhraseMatcher(attr="LOWER")` with pattern `acme corp.` returns `[]` against a text where
  `attr="ORTH"` with `ACME Corp.` returns the span — and against a text where `re.finditer` finds
  it too. Print `[t.text for t in nlp.make_doc(pattern)]` when a pattern mysteriously never fires,
  or use an `EntityRuler` string pattern, which tokenises pattern and text the same way (verified
  agreeing with `re.finditer` span for span). The
  [`no-model-pipeline`](examples/no-model-pipeline) example puts this on screen as a number.
- **Registering the same component name twice raises `OSError: could not get source code` where
  sources are stripped.** `spacy/language.py:518` and `:608` compare the old and new functions with
  `util.is_same_func`, which is `inspect.getsourcelines(func1) == inspect.getsourcelines(func2)`
  (`spacy/util.py:1205`). With the `.py` present that comparison succeeds and a duplicate
  registration is harmless; with only a `.pyc` — which is what
  [`cleanup.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup), on by default in
  flet-cli 0.86.5, leaves of every dependency — the second registration raises. Reproduced by
  importing a `.pyc`-only module twice. Register each custom name once at module scope, or guard
  with `if name not in Language.factories`. (`catalogue/__init__.py:161` makes the same call
  guarded only against `TypeError`/`ValueError`, so `OSError` escapes there too.)
- **`en_core_web_sm` buys you no word vectors, and `has_vector` lies about it.** Its `meta.json`
  declares `{'width': 0, 'vectors': 0, 'keys': 0}`, `nlp.vocab.vectors.shape` is `(0, 0)`, and yet
  `doc.has_vector` is `True` and `doc.similarity(other)` returns a plausible `0.6178` computed
  from tok2vec tensors — the only signal being a `[W007]` warning nothing surfaces on a phone.
  Check `nlp.vocab.vectors.shape != (0, 0)` before trusting a similarity, and reach for
  `en_core_web_md` (33 MB) if you need real vectors.
- **`import spacy` drags in the whole command-line interface.** `spacy/__init__.py:18` is
  `from .cli.info import info`, and `spacy/cli/__init__.py` has 30 eager imports covering
  `download` (requests), `init_config` (jinja2) and the project commands (weasel). After the import
  finishes, `sys.modules` holds `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`,
  `httpx`, `ssl`, `typer`, `click`, `rich`, `pygments`, `shellingham`, `weasel`, `jinja2`,
  `markupsafe` and `tqdm` — 320 of the 1,062 modules loaded. It is not optional and cannot be
  trimmed from the app side. It costs 0.59 s and loads 74 native extension modules (43 of them
  spaCy's own) on a development machine; a device will be slower, so do the import before the
  first frame rather than inside a handler. The HTTP stack being resident does **not** mean spaCy
  calls out — the same trace records zero connection attempts.
- **`nlp.max_length` is 1,000,000 characters and exceeding it raises.** `ValueError [E088]`,
  which is a good default on a phone: a 960,000-character document produced 210,000 tokens with a
  `doc.mem` pool of 39,322,800 bytes and a 75 MiB peak-RSS delta on desktop. `doc.mem.size` is
  readable and grows with the document (6,000 → 39,600 → 308,400 bytes across the example's 1, 8
  and 64-copy documents), which makes it a usable budget meter.
- **The linear algebra is portable reference C on both platforms.** `blis` compiled the *generic*
  BLIS configuration for Android arm64 and iOS arm64 alike: the only context initialisers present
  are `bli_cntx_init_generic{,_ind,_ref}` and the only gemm microkernels are
  `bli_{s,d,c,z}gemm_generic_ref` — no ARM assembly kernel anywhere. The `cortexa*` names that do
  appear *are* real symbols (`bli_cpuid_is_cortexa53` and its three siblings, defined in both
  binaries), but they are CPU-detection predicates, not kernels; `haswell` and `zen2` appear only
  in BLIS's architecture name table. Checked the same way on both platforms — `llvm-nm -D` on the
  ELF (stripped, so `.dynsym` is all there is) and `nm -a` on the Mach-O. `thinc`
  calls straight into it (`thinc/backends/cblas.pyx` cimports `blis.cy`), so every matmul in a
  loaded model runs on that. It has no effect on a rule-only pipeline, which does no matrix maths.
- **GPU calls fail cleanly.** `spacy.prefer_gpu()` returns `False`; `spacy.require_gpu()` raises
  `ValueError`. Neither misbehaves — see [iOS notes](#ios-notes) for the message difference.
- **About 2.6 MB of the wheel is something your app will never run.** Upstream's own
  `spacy/tests` package is 1,433,806 bytes (9% of the unpacked Android wheel) and the Cython
  sources shipped beside the extensions — `.pyx` 733,352, `.c` 377,753, `.pxd` 57,769, `.pyi`
  31,830 — are another 1,200,704. `srsly` has the same shape, with 1,727,412 bytes of `.cpp`. The
  14 `.pyi` files are type-checker stubs; nothing imports them, and spaCy uses no
  `lazy_loader`-style stub attachment, so their fate in packaging is irrelevant.
- **The Python half of the wheel is upstream's, byte for byte.** All 870 `.py` files in the
  Android wheel hash identically to a `spacy==3.8.13` install from PyPI — the recipe's patch
  touches only `setup.py` and `setup.cfg`, neither of which ships. Upstream's documentation
  applies here without a translation step. The native half does not carry that guarantee.

## Build notes (maintainers)

`patches/mobile.patch` explains both of its hunks in its own preamble and `meta.yaml` comments
its two settings, so what is left here is shape and the bump checklist.

**A bump is not a version bump.** spaCy 3.8.14 and 3.8.15 publish 30 files each and **no sdist**,
which forge cannot consume — 3.8.13 is the newest release that has one. So moving forward means
changing where the source comes from, not editing a version string. `thinc` also has to stay in
8.3.x: spaCy 3.8.13 pins `thinc<8.4.0,>=8.3.12`, thinc 8.3.13 pins `blis<1.4.0,>=1.3.0` (which the
index's blis 1.3.3 satisfies) and thinc 9.x pins `blis<1.1.0`, which it does not.

What to re-verify, in rough order of how quietly it breaks:

- **The `click` hunk.** It exists because upstream forgot a dependency. If a future spaCy declares
  `click` itself, the `setup.cfg` half of the patch stops applying and the build goes red for a
  good reason — at which point delete the hunk and the paragraph in [Install](#install). Check
  `Requires-Dist: click` is still in the built wheel's `METADATA` either way; without it a
  consumer's app fails at `import spacy` on device with `ModuleNotFoundError`.
- **The three `__file__`-relative reads.** The whole `extract_packages` requirement rests on them:
  `spacy/language.py`'s `DEFAULT_CONFIG_PATH`, `spacy/cli/init_config.py`'s `ROOT` and
  `thinc/backends/_custom_kernels.py`'s `PWD`. Re-derive them with a `sys.addaudithook` on the
  `open` event around a fresh `import spacy`, filtering out `.py`/`.pyc`/`.so` — not by patching
  `pathlib`/`builtins`, which a read done in C or through a symbol bound before the patch walks
  straight past. The set is small enough to enumerate, and if it ever empties, Android changes. Note
  that `tests/` cannot catch a regression here: the recipe-tester reads `extract_packages` out of
  `meta.yaml`, so on-device CI is always in the extracted arrangement a consumer only reaches by
  editing their own `pyproject.toml`.
- **The 18-slice resolve and the size table.** Both are measured with `pip download` per slice, not
  inferred, and both move when any of the eleven native dependencies is republished — `numpy` alone
  is 6.8 MB of the 22 MB. Re-run rather than adjusting by eye. The cp312-only `android_24_x86`
  slice is unreachable from `flet build`, so do not treat its absence on cp313/cp314 as a gap.
- **The behavioural claims, none of which `tests/` protects.** `tests/test_spacy.py` asserts the
  tokenizer and a `StringStore` round trip — presence, essentially. Everything in
  [Things to know](#things-to-know) is a property of spaCy's Python layer that a bump can move
  without the build noticing: the silent `''` attributes, the `[E109]`/`[E1004]`/`[E139]` messages,
  the 75-of-79 language count, the `PhraseMatcher` tokenisation trap, `has_vector` lying on a
  vector-less model. The [Threading](#threading) table is the same kind of claim: re-run it with all
  three controls, and compare `nlp.pipe` against a plain loop over the *same* corpus — against a
  different corpus it measures document length, not batching. Worth adding to `tests/`, in order of
  value: that `token.pos_` is `''`
  rather than raising on a blank pipeline (the most consumer-visible claim on this page), an
  `EntityRuler` match with its character offsets re-sliced from the source, and a `to_disk`/`load`
  round trip — which together would also make the [`no-model-pipeline`](examples/no-model-pipeline) example's
  premise a CI-enforced one. Per this repo's test convention, assert relationships rather than
  version numbers.
- **`blis`'s configuration.** The generic-C finding is a property of how `blis` was cross-compiled,
  not of spaCy, so a `blis` bump can change it in either direction without touching this recipe.
  Grep `bli_cntx_init_*` and `bli_*gemm_*_ref` in `blis/cy...so` on both platforms — but with
  `llvm-nm -D` on the Android ELF (it ships stripped, so `.dynsym` is the only symbol table) and
  `nm -a` on the iOS Mach-O. `strings` finds these names in the ELF's `.dynstr` and finds *none* of
  them in the Mach-O, so a `strings`-on-both check reads as a platform difference that is not
  there.
- **The model story.** That `en_core_web_sm` publishes nothing on PyPI, that its wheel has no
  `Requires-Dist`, and that `spacy.load()` takes a bare directory are the load-bearing facts under
  [Storage](#storage). They are upstream's decisions, re-checkable in a minute with `curl -sIL`
  and one `spacy.load()`, and a change to any of them rewrites that section.
