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
you have to get onto the device yourself. See [Model files](#model-files).

Reaching for it on a phone makes sense when the answer is rules over text you can describe —
splitting a receipt into sentences, pulling known product names out of a note, finding amounts and
dates — and you want offsets that slice the original string back exactly. It is a heavy dependency
for that: roughly 22–25 MB of downloads (see [App size](#app-size)), against a `re` module that is
already there. Weigh it before you commit.

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
Android site-packages is a *stored* zip, where such a path is not a directory, so the import dies
with `NotADirectoryError: [Errno 20] Not a directory` on a path containing `sitepackages.zip`,
before a line of your code runs.

The value is the **import** name, and it has to be in *your* `pyproject.toml`: the copy in this
recipe's `meta.yaml` reaches only mobile-forge's own test app, and `flet_cli`'s
`ANDROID_DEFAULT_EXTRACT_PACKAGES` is empty. iOS keeps a real site-packages directory and needs
nothing, which also means a green iOS-simulator run proves nothing about this.

**spaCy needs Python 3.12 or newer**, so raise `requires-python` to `>=3.12` if it is lower. A
cp311 resolve reports *no matching distribution* for `spacy` itself, not for a dependency.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`no-model-pipeline`](examples/no-model-pipeline) — a rule-based pipeline with no model at all,
  auditing its own tokenisation against a regex reconstruction.

## Usage in a Flet app

Build a pipeline once, run it over text, and put the spans in a control:

```python
import flet as ft
import spacy

nlp = spacy.blank("en")  # tokenizer + Vocab, from Python source: no model, no download
nlp.add_pipe("sentencizer")
nlp.add_pipe("entity_ruler").add_patterns([{"label": "ORG", "pattern": "ACME Corp."}])

doc = nlp("Dr. Smith invoiced ACME Corp. $4,500.00 on 2026-01-15.")
found = ft.Text(", ".join(f"{e.label_}: {e.text}" for e in doc.ents))
```

Every [`Span`](https://spacy.io/api/span) carries `start_char` and `end_char` back into the string
you passed in, so `text[e.start_char:e.end_char]` is the original substring — which is what makes
spaCy worth the weight over a regex when you need to highlight, replace or redact in place. Build
the pipeline at module scope, not in a handler: `import spacy` is expensive, and adding a custom
component twice has a failure mode of its own. Both are in
[Things to know](#things-to-know).

### Storage

spaCy writes nothing of its own: no cache directory, no download on first use, no lock file. So
nothing needs a home in app storage until you decide to keep something. Two things are worth
keeping, and both belong in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
which is app-private, included in backups and never auto-deleted:

```python
import os

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "pipeline")
nlp.to_disk(path)          # later, on a cold start: nlp = spacy.load(path)
```

A **rule-only pipeline** persists cheaply. [`to_disk`](https://spacy.io/api/language#to_disk) of
`blank("en")` + sentencizer + EntityRuler wrote about 95 KB, most of it the tokenizer's exception
table and the `StringStore`, so the size barely moves with how many patterns you add. A **model
directory** is the other case, at 12.8 MB to 457 MB — see [Model files](#model-files).

Neither belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
which the OS may purge, or
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp),
which may vanish between launches: rebuilding either is a download or a re-training, not a
recomputation. Anything shipped with the app is an asset instead — put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and resolve it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir), which
is read-only and replaced wholesale on every app update.

Processed documents serialise far smaller than the pipeline that produced them: a
[`DocBin`](https://spacy.io/api/docbin) of 200 copies of a 46-character sentence is 2.2 KB, and of
200 *distinct* short sentences 6.0 KB. It stores token indices against the shared `Vocab`, so what
costs is how many strings are new, not how many documents there are.

### Threading

**A pipeline call holds the GIL for essentially all of its duration.** Measured on desktop with a
counting thread spinning beside one long call over 218,889 characters, reported as a share of the
counter's undisturbed rate, against a GIL-holding floor and a GIL-releasing ceiling:

| main thread is running | counter keeps |
| --- | --- |
| `math.factorial` — floor, GIL never released | 2% |
| `nlp(text)` + sentencizer + `EntityRuler` — the fullest rule pipeline | 11% |
| a pure-Python loop — ordinary bytecode, GIL shared fairly | 51% |
| `hashlib.sha256` — ceiling, GIL released | 101% |

The tokenizer alone is 3% and a component-less `nlp(text)` 4%, so every arrangement sits nearer
the floor than the pure-Python control: spaCy is Cython, and Cython that touches Python objects
keeps the GIL. [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
is still where the work belongs, because the handler returns immediately — but for the length of
the call the rest of your Python gets about a tenth of the interpreter, and a second slider
release, a button tap and any other worker all queue behind it. You are buying responsiveness, not
throughput. Size the document so the call is short, and expect a device to be slower than this.

`run_thread` never retrieves the worker's future, so an exception inside one surfaces nowhere at
all — wrap the body, and catch broad `Exception`, because spaCy raises its own error-coded
`ValueError`s alongside plain ones. Auto-update does not reach background threads either, so end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

**Concurrency is safe here and buys nothing.** Sharing one pipeline held up under three runs of 12
threads × 500 documents, every document carrying tokens no other thread used so the shared
`StringStore` grew concurrently, and `sys.setswitchinterval(1e-6)` to give an unsafe mutation its
best chance: 0 errors and 0 wrong answers. But eight threads doing eight times the work took 8.3×
as long as one, exactly as the table predicts, and
[`nlp.pipe`](https://spacy.io/api/language#pipe) measured 0.96–1.03× a plain
`[nlp(t) for t in texts]` over an *identical* 200-document corpus — at the default `n_process=1`
it is that loop with a tidier signature. **Leave `n_process` at 1**: any other value forks workers
via [`multiprocessing`](https://flet.dev/docs/cookbook/multiprocessing/), which is not something
to try in a Flet app runtime.

### Model files

The pipelines are [not on PyPI](https://spacy.io/usage/models#download):
`https://pypi.org/simple/en-core-web-sm/` returns a valid index listing zero files — the project
exists and publishes nothing — and `pypi.flet.dev` has no entry either. They are published only as
GitHub release assets, at these compressed sizes:

| pipeline | download |
| --- | ---: |
| `en_core_web_sm` | 12.8 MB |
| `xx_ent_wiki_sm` | 11.1 MB |
| `en_core_web_md` | 33.5 MB |
| `en_core_web_lg` | 401 MB |
| `en_core_web_trf` | 457 MB |

Those wheels are `py3-none-any` with **no `Requires-Dist` and no `Requires-Python` line at all**,
and they are ordinary zips. That matters, because **`spacy.load()` accepts a bare unpacked
directory** — no installed package, no entry point — which gives you two routes onto a device:

- **Ship the unpacked directory with the app**, under `src/assets/`, and load it through
  `FLET_ASSETS_DIR`. `en_core_web_sm-3.8.0` unpacks to 15.2 MB across 26 files, and that goes into
  every build for every architecture.
- **Download it once on first run** into `FLET_APP_STORAGE_DATA`, and `spacy.load()` that path
  forever after.

Nothing fetches a model for you: a missing one is a loud `OSError [E050] Can't find model …`, not
a silent download, which is the behaviour you want on a phone.
[`spacy.cli.download()`](https://spacy.io/api/cli#download) is the only call in the package that
goes out, and it needs **two** hosts — `raw.githubusercontent.com` for the compatibility table and
`github.com/explosion/spacy-models/releases/download` for the asset. Allow-list both, if you
allow-list anything. Everything else is offline: traced under a `sys.addaudithook`, `import spacy`,
a blank pipeline over a document and a failing `spacy.load()` all record zero name resolutions and
zero connection attempts.

If you install a model as a *package* rather than a directory, add its import name to the Android
`extract_packages` list beside `spacy` and `thinc`: its `__init__.py` calls
`get_model_meta(Path(__file__).parent)` at import, which is the identical zip failure.

**Nothing here has run a statistical model on a device.** Neither `tests/` nor the example loads
one. On a development machine, network blocked, `spacy.load()` of an unpacked `en_core_web_sm`
restored the full `['tok2vec', 'tagger', 'parser', 'attribute_ruler', 'lemmatizer', 'ner']`
pipeline in 0.18 s — but treat load time, memory and tagger/parser/NER output on a phone as
untested, and measure them before you ship one. The offline lemmatizer tables that `[E1004]` asks
for are a separate 98 MB `spacy-lookups-data` wheel, not on `pypi.flet.dev` either.

### App size

The whole dependency set downloads approximately 22–25 MB depending on slice, of which the `spacy`
wheel itself is about 5.7 MB on Android arm64. Unpacked, spaCy alone is roughly 16 MB on Android
arm64 and 20 MB on iOS; the difference is its 46 compiled extensions.

About 2.6 MB of that is something your app will never run: upstream's own `spacy/tests` package
(1.4 MB) and the Cython sources shipped beside the extensions — `.pyx`, `.c`, `.pxd` and `.pyi`,
1.2 MB together. The test package is the part worth naming yourself:

```toml
[tool.flet.cleanup]
package_files = ["spacy/tests"]
```

Read those figures as near what lands on the device rather than exactly it:
[`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) is on by default and
replaces the remaining `.py` files with `.pyc`, which has a consequence of its own in
[Things to know](#things-to-know). On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. A bundled model lands on top of all of this and is usually
the larger number by far.

### Other considerations

A desktop `flet run` uses PyPI's wheel, and for spaCy 3.8.13 the first difference you meet is that
**the mobile wheel imports where PyPI's does not.** Upstream calls `from click import NoSuchOption`
in `spacy/cli/_util.py` but never declares `click` — it relied on `typer` pulling it transitively,
and typer dropped that dependency. A fresh `uv pip install spacy==3.8.13` today resolves with typer
and no click, and `import spacy` then dies with `ModuleNotFoundError: No module named 'click'`.
These wheels carry `Requires-Dist: click>=8.0.0`, which upstream's do not. If a desktop run fails
at import while the device is fine, that is why — add `click` to your dev dependencies.

`require_gpu()` also says something different on your Mac than on either phone.
`spacy.prefer_gpu()` returns `False` everywhere and is safe to leave in shared code.
`spacy.require_gpu()` raises `ValueError: Cannot use GPU, PyTorch is not installed` on macOS and
`ValueError: Cannot use GPU, CuPy is not installed` on **both** Android and iOS, because `thinc`
branches on `platform.system() == "Darwin"` and Flet's iOS runtime reports `"iOS"` (PEP 730). Same
outcome, different text — do not match on the message.

The linear algebra underneath is not your laptop's either. [`blis`](../blis) is compiled with
BLIS's portable C reference kernels on Android arm64 and iOS arm64 alike — the only gemm
microkernels present are `bli_{s,d,c,z}gemm_generic_ref`, no ARM assembly kernel anywhere — and
[`thinc`](../thinc) calls straight into it, so every matmul in a loaded model runs on that. There
is no Accelerate path on iOS either: `thinc-apple-ops`, the Apple backend spaCy declares under
`extra == "apple"`, is not on `pypi.flet.dev`. A rule-only pipeline does no matrix maths and is
unaffected; a model is the case to measure.

So: validate the Android `extract_packages` requirement on Android, which an iOS simulator cannot
exercise; measure the import cost before your first frame; and treat anything involving a model as
unmeasured until you have run it on hardware.

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
  `str(token.morph)` all return `''` and `doc.ents` returns `()`, with no warning of any kind — a
  wrong empty answer that looks like a right one. Only `doc.sents` and `doc.noun_chunks` raise
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
  and each of those four returns HTTP 404 on `pypi.flet.dev`. Vietnamese has a way out needing no
  extra dependency: `spacy.blank("vi", config={"nlp": {"tokenizer": {"use_pyvi": False}}})`.

- **`PhraseMatcher` matches nothing when the pattern tokenises differently from the text, and says
  nothing about it.** The classic case is case itself: `nlp.make_doc("ACME Corp. on")` gives
  `['ACME', 'Corp.', 'on']` but `nlp.make_doc("acme corp.")` gives `['acme', 'corp', '.']`, so
  `PhraseMatcher(attr="LOWER")` with pattern `acme corp.` returns `[]` against a text where
  `attr="ORTH"` with `ACME Corp.` returns the span — and where `re.finditer` finds it too. Print
  `[t.text for t in nlp.make_doc(pattern)]` when a pattern mysteriously never fires, or use an
  `EntityRuler` string pattern, which tokenises pattern and text the same way. The
  [`no-model-pipeline`](examples/no-model-pipeline) example puts this on screen as a number.

- **Registering the same component name twice raises `OSError: could not get source code` where
  sources are stripped.** `spacy/language.py:518` and `:608` compare old and new functions with
  `util.is_same_func`, which is `inspect.getsourcelines(func1) == inspect.getsourcelines(func2)`.
  With the `.py` present that comparison succeeds and a duplicate registration is harmless; with
  only a `.pyc` — which is what
  [`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup), on by default in
  flet-cli 0.86.5, leaves of every dependency — the second registration raises. Register each
  custom name once at module scope, or guard with `if name not in Language.factories`.
  `catalogue`'s own call is guarded only against `TypeError`/`ValueError`, so `OSError` escapes
  there too.

- **`en_core_web_sm` buys you no word vectors, and `has_vector` lies about it.** Its `meta.json`
  declares `{'width': 0, 'vectors': 0, 'keys': 0}`, `nlp.vocab.vectors.shape` is `(0, 0)`, and yet
  `doc.has_vector` is `True` and `doc.similarity(other)` returns a plausible `0.6178` computed from
  tok2vec tensors — the only signal being a `[W007]` warning nothing surfaces on a phone. Check
  `nlp.vocab.vectors.shape != (0, 0)` before trusting a similarity, and reach for `en_core_web_md`
  (33.5 MB) if you need real vectors.

- **`import spacy` drags in the whole command-line interface.** `spacy/__init__.py` imports
  `.cli.info`, and `spacy/cli/__init__.py` has 30 eager imports covering `download` (requests),
  `init_config` (jinja2) and the project commands (weasel) — so `requests`, `urllib3`, `httpx`,
  `ssl`, `typer`, `click`, `rich` and `tqdm` all end up resident, 320 of the 1,062 modules loaded.
  It is not optional and cannot be trimmed from the app side. It costs 0.59 s and loads 74 native
  extension modules on a development machine, so do the import before the first frame rather than
  inside a handler. A resident HTTP stack does **not** mean spaCy calls out — the same trace
  records zero connection attempts.

- **`nlp.max_length` is 1,000,000 characters and exceeding it raises `ValueError [E088]`.** That
  is a good default on a phone: a 960,000-character document produced 210,000 tokens with a
  `doc.mem` pool of 39 MB and about 79 MB of peak resident-set growth on desktop — the same
  measurement a binary-unit tool reports as 75 M. `doc.mem.size` is readable and grows with the
  document (6,000 → 39,600 → 308,400 bytes across the example's 1, 8 and 64-copy documents),
  which makes it a usable budget meter.

- **The Python half of the wheel is upstream's, byte for byte.** All 870 `.py` files in the
  Android wheel hash identically to a `spacy==3.8.13` install from PyPI — the recipe's patch
  touches only `setup.py` and `setup.cfg`, neither of which ships. Upstream's documentation
  applies here without a translation step. The native half does not carry that guarantee.

## Build notes (maintainers)

### Recipe shape

An ordinary Python-package recipe over spaCy's sdist, with one patch. The Cython stack it compiles
against — [`thinc`](../thinc), [`blis`](../blis), [`cymem`](../cymem), [`preshed`](../preshed),
[`murmurhash`](../murmurhash) and [`srsly`](../srsly) — is six sibling recipes resolved from the
index as plain build requirements, not vendored. The extensions compile as C++, so the Android
slices and only those carry `Requires-Dist: flet-libcpp-shared`; on iOS the C++ runtime comes from
the OS. The patch preamble owns both of its hunks and `meta.yaml` comments its two settings.

`meta.yaml`'s `extract_packages` list reaches this repository's on-device test app only. That is
why the consumer instruction has to be repeated in every consuming `pyproject.toml`, and why a
green recipe test proves nothing about an app that omits it.

Two Android facts are recorded here because no other file records them. 45 of the 46 extensions
name `libc++_shared.so` in `DT_NEEDED` (the exception is `spacy/matcher/levenshtein`), as does
every `.so` in `cymem`, `preshed`, `murmurhash`, `srsly` and `thinc`; `blis` is the one that does
not, being pure C. And `spacy/pipeline/ner` and `spacy/pipeline/_parser_internals/ner` are the only
colliding `.so` basenames across the seven wheels, both loaded by a plain `import spacy` — Flet
0.86 gives each a distinct mangled name in `jniLibs/<abi>/` plus a per-module `.soref` marker, but
a change to that naming would break this one package and nothing else.

iOS needs nothing equivalent: all 46 extensions are Mach-O ARM64 `MH_DYLIB` depending only on
`@rpath/Python.framework/Python`, `libSystem` and — on 45 — `/usr/lib/libc++.1.dylib`. None
depends on a sibling extension, so there is no install-name relocation problem of the kind
[`pyarrow`](../pyarrow) needed.

### Upgrade hazards

- **A bump is not a version bump.** spaCy 3.8.14 and 3.8.15 publish 30 files each and **no sdist**,
  which forge cannot consume — 3.8.13 is the newest release that has one. Moving forward means
  changing where the source comes from, not editing a version string.
- **`thinc` has to stay in 8.3.x.** spaCy 3.8.13 pins `thinc<8.4.0,>=8.3.12`, thinc 8.3.13 pins
  `blis<1.4.0,>=1.3.0` (which the index's blis 1.3.3 satisfies), and thinc 9.x pins `blis<1.1.0`,
  which it does not.
- **The `click` hunk exists because upstream forgot a dependency.** If a future spaCy declares
  `click` itself, the `setup.cfg` half of the patch stops applying and the build goes red for a
  good reason — delete the hunk and the paragraph in
  [Other considerations](#other-considerations). Check `Requires-Dist: click` is in the built
  wheel's `METADATA` either way; without it a consumer's app fails at `import spacy` on device.
- **Python coverage differs by ABI.** cp312 ships four Android slices (`arm64-v8a`, `armeabi-v7a`,
  `x86`, `x86_64`); cp313 and cp314 ship three, without `x86`, and the rest of the chain has the
  same tag set. `x86` is unreachable from `flet build` anyway — flet-cli 0.86.5's
  `ANDROID_ARCH_TO_FLUTTER_TARGET_PLATFORM` holds only the other three — so its absence on
  cp313/cp314 is not a gap.

### Re-verification checklist

- **The three `__file__`-relative reads.** The whole `extract_packages` requirement rests on them:
  `spacy/language.py`'s `DEFAULT_CONFIG_PATH`, `spacy/cli/init_config.py`'s `ROOT` and
  `thinc/backends/_custom_kernels.py`'s `PWD`. Re-derive them with a `sys.addaudithook` on the
  `open` event around a fresh `import spacy`, filtering out `.py`/`.pyc`/`.so` — not by patching
  `pathlib`/`builtins`, which a read done in C or through a symbol bound before the patch walks
  straight past. If the set ever empties, Android changes.
- **The resolve and the sizes.** Measured one `pip download --only-binary :all: --extra-index-url
  https://pypi.flet.dev --platform <tag> --python-version <ver>` per slice, the way `flet build`
  resolves: three Android ABIs and three iOS slices on 3.12, 3.13 and 3.14, eighteen for eighteen.
  Each resolve is 45 wheels on Android and 44 on iOS (the difference is `flet-libcpp-shared`),
  totalling 21,611,446–24,846,742 bytes; unpacked, spaCy is 15,814,431 bytes on Android arm64-v8a
  against 19,852,998 on iOS. `numpy` alone is 6.8 MB of the download, so any of the eleven native
  dependencies being republished moves the whole table — re-run it rather than adjusting by eye.
- **The behavioural claims, none of which `tests/` protects.** Everything in
  [Things to know](#things-to-know) is a property of spaCy's Python layer that a bump can move
  without the build noticing: the silent `''` attributes, the `[E109]`/`[E1004]`/`[E139]` messages,
  the 75-of-79 language count, the `PhraseMatcher` trap, `has_vector` lying on a vector-less model.
  The [Threading](#threading) table is the same kind of claim — re-run it with all three controls,
  and compare `nlp.pipe` against a plain loop over the *same* corpus, since a different corpus
  measures document length rather than batching. Worth adding to `tests/`, in order of value: that
  `token.pos_` is `''` rather than raising on a blank pipeline, an `EntityRuler` match with its
  offsets re-sliced from the source, and a `to_disk`/`load` round trip — which together would make
  the [`no-model-pipeline`](examples/no-model-pipeline) example's premise CI-enforced.
- **`blis`'s configuration.** The generic-C finding is a property of how `blis` was
  cross-compiled, not of spaCy, so a `blis` bump can change it without touching this recipe. Grep
  `bli_cntx_init_*` and `bli_*gemm_*_ref` in `blis/cy...so` on both platforms — with `llvm-nm -D`
  on the Android ELF (it ships stripped, so `.dynsym` is the only symbol table) and `nm -a` on the
  iOS Mach-O. `strings` finds these names in the ELF's `.dynstr` and *none* of them in the Mach-O,
  so a `strings`-on-both check reads as a platform difference that is not there.
- **The model story.** That `en_core_web_sm` publishes nothing on PyPI, that its wheel has no
  `Requires-Dist`, and that `spacy.load()` takes a bare directory are the load-bearing facts under
  [Model files](#model-files). They are upstream's decisions, re-checkable in a minute with
  `curl -sIL` and one `spacy.load()`, and a change to any of them rewrites that section.

### Coverage gaps

The device tests cover a blank English pipeline tokenising a four-word string and a `StringStore`
hash round trip. That does reach the Cython tokenizer and the cymem / preshed / murmurhash / thinc
stack under it, and little else: nothing on device loads a statistical model, serialises with
`to_disk`, runs an `EntityRuler` or a `PhraseMatcher`, touches a language other than English, or
measures the import cost. The recipe-tester also reads `extract_packages` out of `meta.yaml`, so
on-device CI is always in the extracted arrangement — the failing arrangement is one a consumer
reaches by omitting the entry from their own `pyproject.toml`, which no test here can catch.
Everything in the consumer sections above rests on desktop measurement and on the example app.
