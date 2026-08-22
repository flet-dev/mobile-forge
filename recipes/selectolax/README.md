# selectolax

[`selectolax`](https://github.com/rushter/selectolax) is a Cython binding for two C HTML5
parsers. It takes a string or a byte string of markup, builds a real DOM out of it the way a
browser would, and lets you query that DOM with CSS selectors. The reason to want it on a
phone is not raw speed so much as **not hand-rolling a tokenizer**: real-world HTML leaves
elements unclosed, nests formatting tags in the wrong order, omits `<tbody>`, and puts
markup-shaped text inside `<script>`, and the standard library's
[`html.parser`](https://docs.python.org/3/library/html.parser.html) hands you the tags the
source happened to contain and leaves the repairs to you.

The wheel ships **both** engines, as two independent extension modules:
[`selectolax.lexbor`](https://selectolax.readthedocs.io/en/latest/lexbor.html) wrapping
[Lexbor](https://lexbor.com/), and
[`selectolax.parser`](https://selectolax.readthedocs.io/en/latest/parser.html) wrapping
[Modest](https://github.com/lexborisov/Modest). Every `import selectolax` loads both, so both
are in your app whichever one you call.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "selectolax",
]
```

One top-level entry covers `flet run` and `flet build` alike: `flet build` resolves for the
build host first, and upstream publishes desktop wheels for every host you would build from,
so the same requirement line serves the laptop and the device.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`page-scrape`](examples/page-scrape) — a deliberately broken feed page turned into records,
  with the parser's repairs listed, a live CSS selector box, and a timing comparison against
  `html.parser`.

## Usage in a Flet app

```python
import flet as ft
from selectolax.lexbor import LexborHTMLParser

tree = LexborHTMLParser(html)                       # html is a str; see Storage for bytes
titles = tree.css("li.post:not(.draft) > a.title")  # a list of nodes

page.add(
    ft.ListView(
        controls=[
            ft.Text(node.text(separator=" ", strip=True))
            for node in titles
        ],
        expand=True,
    )
)
```

[`ft.ListView`](https://flet.dev/docs/controls/listview/) rather than a plain column because a
selector can match more rows than fit on a phone. `css_first(...)` is the same query for a
single node, `node.attributes` is a dict of that element's attributes, and `node.html` is its
serialised subtree.

**Reach for `LexborHTMLParser` and treat `HTMLParser` as the fallback.** Upstream's own
docstring for the Modest class, shipped in the wheel, reads "This backend is deprecated.
Please use lexbor backend instead." Everything measured for this page pointed the same way,
with two exceptions that are the reason Modest is still worth knowing about — both are the
first bullet of [Things to know](#things-to-know), along with the selectors the two engines
disagree about.

### Storage

**selectolax opens nothing on your behalf**, so there is no cache directory to relocate and no
environment variable to set before importing. Neither parser class takes a path: the first
argument of `LexborHTMLParser` and of `HTMLParser` is a `str` or a `bytes` of markup, and every
argument after it is a parsing option — `is_fragment`, `detect_encoding` and the like. Reading
the file is your job:

```python
import os
from selectolax.lexbor import LexborHTMLParser

path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "page.html")
with open(path, "rb") as handle:
    raw = handle.read()
tree = LexborHTMLParser(raw.decode("utf-8", "replace"))
```

Decode it yourself, as above, rather than handing Lexbor the bytes. That is not stylistic:
Lexbor does **not** honour a `<meta charset>`, so `LexborHTMLParser(raw)` on a windows-1251
document that declares its own charset gives you replacement characters where Modest gives you
the right text.

Where the file goes is the usual Flet split:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a page you fetched and will fetch again.

### Threading

**Parsing releases the GIL; querying does not.** Both engines drop the interpreter around
document creation and the parse call, and around nothing in the selector path. Measured on a
10-core desktop, four threads each parsing its own 276 KB document, serial wall time over
parallel wall time, median of nine runs: **2.6–3.0× for Lexbor** and **2.8× for Modest**,
against a `time.sleep` control at 3.9× and `html.parser` at 1.0×. The same harness pointed at
`tree.css("li.post > a.title")` on a shared tree gives **0.9×** — no parallelism at all,
because the query never drops the interpreter.

So put the parse in a
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker,
where it genuinely competes with an idle event loop rather than blocking it, and do not expect
a pool of threads running `css()` to go any faster than one.

**Reading one tree from several threads did not misbehave, but do not mutate one.** Eight
threads running 200 `css()` calls each against a single shared tree finished with zero
exceptions and exactly one distinct match count. That is a read-only result and it is the only
thing measured: `decompose()`, `unwrap()`, `strip_tags()` and node insertion all mutate the C
tree, and nothing guards it. Give each thread its own tree, or hold a `threading.Lock` across
the mutation.

The Flet-side rules apply as everywhere else. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try/except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no
log, no dialog and no crash.

### Speed and memory

Desktop (Apple M4, macOS 26.6, CPython 3.14.6), best of seven timed batches over the same
bytes, parsing only:

| MB/s | 1.2 KB | 28 KB | 276 KB |
| --- | ---: | ---: | ---: |
| `selectolax.lexbor` | 52.1 | 55.3 | 52.3 |
| `selectolax.parser` (Modest) | 44.6 | 54.4 | 55.7 |
| `html.parser` | 14.8 | 15.0 | 13.8 |

The two engines swap places between runs at the larger sizes — 45.7 to 57.6 MB/s across six
runs of the example's own benchmark — so read them as level on throughput and choose on the
correctness differences instead. The `html.parser` row is not a like-for-like comparison and
the asymmetry runs the wrong way for it: those 14 MB/s buy a token stream, the 52 MB/s rows buy
a whole tree.

**None of those rates is a ceiling, and the reason is upstream rather than the cross build.**
`setup.py` appends `-O0 -g` after `CFLAGS` on every POSIX platform, so the last `-O` wins and
every selectolax wheel — PyPI's desktop one included — is compiled unoptimised. Nothing you put
in your own `pyproject.toml` changes it.

**Do not hold many trees at once: a parsed document costs far more than its source.** Measured
on desktop as peak-RSS growth in a fresh process per engine, divided by the number of trees
held alive at once, after one warm-up parse:

| source | Lexbor per tree | Modest per tree |
| --- | ---: | ---: |
| 1.2 KB | ~320 KB (267×) | ~380 KB (322×) |
| 28 KB | ~870 KB (31×) | ~1.0 MB (36×) |
| 276 KB | ~5.4 MB (20×) | ~5.6 MB (20×) |
| 919 KB | ~19 MB (21×) | ~18 MB (20×) |

Each parser instance has a fixed floor around 300–380 KB — both engines pre-allocate memory
pools — and then costs roughly **20× the source** on top, so a 1 MB page is a ~20 MB object.
Holding a lot of them lowers the per-tree figure as the pools get reused (the 919 KB document
measured 21× per tree with five alive and 9× with fifty), but budget against the table, not
against the floor. Parse, extract what you need into ordinary Python values, and drop the tree.
`MAX_HTML_INPUT_SIZE`, exported by both engine modules as `2.5e9`, is not a limit you will
meet first; memory is.

### App size

Each wheel is approximately 2.0–2.3 MB compressed and unpacks to roughly **7.9–8.0 MB of
native code per 64-bit slice**, or about 4.9 MB on `armeabi-v7a`. An Android build targeting
all three ABIs carries all three sets — about 21 MB — because `jniLibs` is per-ABI even though
the Python half is shared.

Both extensions are loaded by `selectolax/__init__.py`, so **deleting one to halve the payload
does not work**: with `parser.cpython-*.so` removed, even
`from selectolax.lexbor import LexborHTMLParser` fails with `ImportError: cannot import name
'parser' from partially initialized module 'selectolax'`. Budget for both engines.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI. These figures describe the package payload, not the exact amount
added to the final APK or IPA; packaging and compression decide that.

There is about 110 KB per slice worth recovering and no more. Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) already removes the
`.c`, `.pyx`, `.pxd` and `.pyi` files, but its glob list does not include `**.pxi`, so eleven
Cython include files ship and are never read. Adding them recovers the lot:

```toml
[tool.flet.cleanup]
package_files = ["**.pxi"]
```

Verified on desktop that the package imports and parses with every `.pxi` deleted, and that
`flet-cli` 0.86.5 passes the key through as `--cleanup-package-files`; no device build has been
run with it set.

### Other considerations

**The two halves of your app can be on different versions, and that is expected.** PyPI runs
ahead of this index, so a bare `selectolax` can give your laptop a newer release under
`flet run` than the device gets, with different vendored Lexbor and Modest sources behind the
same API. It resolves cleanly either way, because no upstream file carries a tag a mobile
target matches, so the platform slices can only come from here. If a parse differs between
desktop and device and you cannot explain it, compare the two versions before suspecting
anything else — or pin the version, the way the example's `pyproject.toml` does, to make both
halves agree.

**The parse itself does not vary by platform.** Run on an Android emulator and an iPhone
simulator, the example reports the same engine, the same `li.post` count and the same list of
tree repairs as it does on a desktop. Only the timings move, and **every timing on this page is
a desktop timing** — running the example on a phone is what replaces them.

## Things to know

- **Modest keeps two things Lexbor does not have.** The first is encoding detection: handed the
  bytes of a windows-1251 document declaring `<meta charset=windows-1251>`, `HTMLParser(raw)`
  returns `'Русский'` where `LexborHTMLParser(raw)` returns seven U+FFFD replacement
  characters. Decoding the bytes yourself and passing a `str` gives Lexbor the right answer.
  The second is chained selection: `tree.select("li").css("a.title")` works on Modest and
  raises `NotImplementedError: This features is not supported by the lexbor backend. Please use
  Modest backend.` on Lexbor (the typo is upstream's).

- **On ordinary selectors it is Modest that gets them wrong.** `:is(th, td)` and
  `:where(th, td)` match on Lexbor and raise `ValueError: Bad CSS Selectors: :is(th, td)` on
  Modest. The general sibling combinator double-counts: on a `<ul>` of five sibling
  `<li class=p>`, `li.p ~ li` returns 4 nodes on Lexbor and **10** on Modest, one per
  (earlier, later) pair. And Modest answers some malformed selectors with silence — `li[`,
  `li >>` and `li.post[unclosed` each return **0 nodes and raise nothing**, where Lexbor raises
  for all three, so a typo in a scraper looks like a page that changed.

- **Catch two exception types around any selector you did not write yourself.** Lexbor raises
  `selectolax.lexbor.SelectolaxError: Can't parse CSS selector.` and Modest raises
  `ValueError: Bad CSS Selectors: <the selector>`. Inside a Flet event handler an unhandled
  exception ends the session, so wrap the call; the [example](examples/page-scrape) catches
  both and prints the message.

- **`text(strip=True)` strips each text node, not the run of them, so words fuse together.** On
  `<a>Bees <b>and <i>weather</i></b></a>`: `text()` gives `'Bees and weather'`,
  `text(strip=True)` gives `'Beesandweather'`, and `text(separator=" ")` gives
  `'Bees  and  weather'` with doubled spaces. `text(separator=" ", strip=True)` is the spelling
  you want, plus `" ".join(value.split())` when the source indentation still shows through.

- **A node keeps its tree alive, so returned nodes outlive the parser.** Dropping the parser and
  forcing a `gc.collect()` left `nodes[0].attributes` and `nodes[0].text()` working on both
  engines. You do not need to hold a reference to the parser object yourself.

- **Do not import `selectolax.modest`.** It is a directory of Cython includes compiled into the
  `parser` extension at build time, with no runtime module behind it, and this recipe patches
  the package so it no longer tries. Write the import yourself and what you get depends on the
  interpreter and the platform: `ModuleNotFoundError` on some Android slices, an empty
  namespace package on others and on iOS. The engines you want are `selectolax.parser` and
  `selectolax.lexbor`.

- **Where the standard library is actually fine, use it.** `html.parser` handles character
  references, treats a bare `<` in text as text, and puts `<script>`/`<style>` content in CDATA
  mode so markup-shaped strings inside them are not parsed as markup. What it cannot do is build
  a tree: on the example's document it emits 35 start tags and 20 end tags, so 15 elements are
  closed by the HTML5 rules and not by the author, and it never emits the `<tbody>` that a
  browser's DOM contains and that any selector copied out of DevTools expects. If your input is
  a fragment you generated yourself, `html.parser` is 8 MB of native code cheaper.

## Build notes (maintainers)

### Recipe shape

A `meta.yaml` and one patch. Upstream's `setup.py` compiles the vendored Lexbor and Modest C
trees straight into two `Extension`s — no system dependency, no `extra_objects` unless you pass
`--static`, and its only platform fork is `windows_nt` against `posix`, selecting `myport`
sources that a mobile target gets right. There is little for a cross build to trip over, so a
bump that suddenly needs build flags means upstream restructured rather than that the toolchain
drifted.

Two upstream knobs exist and are deliberately unused. `--static` links prebuilt archives
instead of compiling the trees, and we have no archives. `--disable-modest` (or `USE_MODEST=""`
— and only an *empty* value, since `INCLUDE_MODEST = bool(os.environ.get("USE_MODEST", True))`
makes `USE_MODEST=0` mean *enabled*) drops the Modest extension, worth about 43% of the
payload. It cannot be used on its own, because `__init__.py` imports both and a package missing
`parser.cpython-*.so` fails even `from selectolax.lexbor import LexborHTMLParser`. Extending the
patch to drop `parser` from `__init__.py` alongside `modest` would make it viable, at the cost
of the two Modest-only behaviours documented above and of any consumer importing
`selectolax.parser`.

Both extension names collide with a sibling directory of the same name inside the package
(`lexbor.cpython-*.so` beside `lexbor/`, and `modest/` beside no module at all). That is
upstream's layout, and on Android it survives only because those include-only directories hold
no `.py`, `.pyc` or `.soref` member — exactly the condition serious_python's
`synthesizePackageInits()` tests. If upstream ever adds a real Python module under
`selectolax/lexbor/`, the synthesised `__init__.py` would start competing with the extension.
Worth a glance at the wheel's file list on any bump, not just at the version number.

### Upgrade hazards

**The most valuable open change here is not a bump: patch out upstream's `-O0`.** The recipe
inherits `extra_compile_args=[..., "-O0", "-g"]` from `setup.py`'s POSIX branch for both
extensions, and because `extra_compile_args` are appended after `CFLAGS`, **a `script_env`
`CFLAGS` cannot override it** — verified by building the sdist with `CFLAGS="-O2"` on a desktop
and getting a binary indistinguishable from the unmodified build. Editing the two lines in
`setup.py` does work: the same source at `-O2` measured **3.7–3.9× faster and 13.7% smaller**.
Dropping `-g` separately would also account for most of the unstripped iOS `__LINKEDIT` — about
810 KB across the two cp314 device extensions, which `strip -x` recovers. None of this has been
done, and it must be measured on device before it is claimed anywhere consumer-facing.

**The patch's failure mode is Python-version-dependent, which is not obvious from the patch and
is the thing most likely to mislead a future bump.** Reproducing serious_python's Android layout
on a desktop, the unpatched `from . import lexbor, modest, parser` fails on **3.12 and 3.13**
with `ImportError: cannot import name 'modest' from partially initialized module 'selectolax'`
and **succeeds on 3.14**. The reason is CPython, not Flet: 3.14's `zipimport._read_directory`
synthesises implied directory entries into its file table, so `selectolax/modest/` resolves as a
namespace portion; 3.12 and 3.13 have no such loop. So **do not conclude the patch is obsolete
from a green 3.14 run**, and if Flet ever drops 3.12 and 3.13 the patch becomes genuinely
unnecessary rather than merely quiet.

### Re-verification checklist

In rough order of what a green build fails to tell you:

- **Whether `__init__.py` still imports `modest`**, and whether the patch still applies. It is a
  one-line change to a file upstream edits rarely, so a silent rebase failure is the likely way
  it goes wrong. Check the built wheel's `__init__.py` reads `from . import lexbor, parser`, not
  the recipe's patch file.
- **Whether Modest is still there at all.** Upstream calls it deprecated in the class docstring
  shipped in the wheel. The day it is removed, this page's engine comparison, the example's
  segmented button and roughly 43% of the payload all change at once — an improvement to
  document, not a regression.
- **Whether upstream has started publishing a mobile-tagged or a `py3-none-any` wheel.** A bare
  `selectolax` resolves from this index on every mobile slice only because none of upstream's
  files carries a tag a mobile target matches. pip picks the highest *version* before it looks
  at tags, so the first `any` wheel upstream publishes silently takes over every mobile resolve
  and **Install**'s "one entry covers both" claim needs rewriting.
- **The size figures under App size**, the most consumer-visible claim here, which move with
  every vendored-C bump.
- **That `METADATA` still carries only the `Cython` extra**, and that no `.py` in the package has
  acquired a `__file__` read. Either would falsify **Install** without failing anything.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `lexbor.cpython-`/`parser.cpython-` prefixes, not
  an exact suffix — the 3.12 Android slices use a bare `cpython-312` tag where 3.13 and 3.14
  carry the full platform triplet.
- **The linkage**, per slice: `DT_NEEDED` still only bionic and the interpreter with no
  `libc++_shared` (both engines are C, not C++), `0x4000` `PT_LOAD` alignment on all three
  Android ABIs, `MH_DYLIB` on all three iOS ones.
- **The GIL split**, since **Threading** rests on it: `with nogil` around the parse and not
  around the selector path. Upstream extending it to `css()` would invert that section's advice.
- **The engine divergences** — `:is()`, the `~` double-count, the silently-accepted malformed
  selectors — since Things to know states them as properties of the shipped binaries.

### Coverage gaps

`tests/test_selectolax.py` covers one parse-and-select per engine. Worth closing at the next
touch, in rough order of value: **an assertion that `selectolax.modest` is not imported by
`selectolax`**, since that is what the patch exists to guarantee and nothing on device checks it
today; a malformed-markup case (an unclosed `<li>` or a missing `<tbody>`) that would catch an
engine built without its tree-construction rules; and the `:is()` divergence between the
engines, which pins the claim this page's engine recommendation rests on to the shipped
binaries. A timing assertion is deliberately not on that list — it would flake in CI.
