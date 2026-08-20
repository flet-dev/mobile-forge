# selectolax

[`selectolax`](https://github.com/rushter/selectolax) is a Cython binding for two C HTML5
parsers. It takes a string or a byte string of markup, builds a real DOM out of it the way a
browser would, and lets you query that DOM with CSS selectors. The reason to want it on a
phone is not raw speed so much as **not hand-rolling a tokenizer**: real-world HTML leaves
elements unclosed, nests formatting tags in the wrong order, omits `<tbody>`, and puts
markup-shaped text inside `<script>`, and the standard library's
[`html.parser`](https://docs.python.org/3/library/html.parser.html) hands you the tags the
source happened to contain and leaves the repairs to you.

**This wheel ships both engines**, as two independent extension modules with no symbols in
common:

- [`selectolax.lexbor`](https://selectolax.readthedocs.io/en/latest/lexbor.html) — the
  [Lexbor](https://lexbor.com/) engine. `4,576,696` bytes on the cp314 Android arm64 slice,
  exporting 1,955 `lxb_*` and 244 `lexbor_*` symbols and zero Modest ones.
- [`selectolax.parser`](https://selectolax.readthedocs.io/en/latest/parser.html) — the
  [Modest](https://github.com/lexborisov/Modest) engine. `3,415,088` bytes on the same slice,
  exporting 2,190 symbols under Modest's `myhtml_`, `mycss_`, `modest_`, `mycore_`,
  `myencoding_` and `myfont_` prefixes, and zero Lexbor ones.

**Reach for `LexborHTMLParser` and treat `HTMLParser` as the fallback.** Upstream's own
docstring for the Modest class, shipped in the wheel and rendered on its docs page, reads
"This backend is deprecated. Please use lexbor backend instead." Three measured differences
back that up, all on a desktop with selectolax 0.4.10 under CPython 3.14.6:

- `:is(th, td)` and `:where(th, td)` match 6 cells under Lexbor and raise
  `ValueError: Bad CSS Selectors: :is(th, td)` under Modest.
- The general sibling combinator double-counts under Modest. On a `<ul>` of five sibling
  `<li class=p>`, `li.p ~ li` returns 4 nodes under Lexbor and **10** under Modest — one per
  (earlier sibling, later sibling) pair, C(5,2), with only 4 distinct.
- Modest answers some malformed selectors with silence. `li[`, `li >>` and
  `li.post[unclosed` each return **0 nodes and raise nothing** under Modest, where Lexbor
  raises `SelectolaxError: Can't parse CSS selector.` for all three. A typo in a scraper
  therefore looks like a page that changed.

Modest keeps two things Lexbor does not have, so do not delete it from your head entirely:
it detects the document encoding from a `<meta charset>` when you hand it bytes, and its
`select(...)` chain supports a nested `.css(...)`. Both are in
[Things to know](#things-to-know).

On speed, the honest summary is that **the engines are level with each other and roughly 3.7×
the standard library while doing strictly more work**. Desktop (Apple M4, macOS 26.6, CPython
3.14.6), best of seven timed batches over the same bytes, parsing only:

| MB/s | 1,186 B | 28,267 B | 276,127 B |
| --- | --- | --- | --- |
| `selectolax.lexbor` | 52.1 | 55.3 | 52.3 |
| `selectolax.parser` (Modest) | 44.6 | 54.4 | 55.7 |
| `html.parser` | 14.8 | 15.0 | 13.8 |

The two engines swap places between runs at the larger sizes (45.7 to 57.6 MB/s across six
runs of the example's own benchmark), so read them as equal on throughput and choose on the
correctness differences above. The `html.parser` row is not a like-for-like comparison, and
the asymmetry runs the wrong way for it: those 14 MB/s buy a token stream, the 52 MB/s rows
buy a whole tree. On the example's bundled page, `html.parser` reports 35 start tags where
selectolax builds 36 elements.

**Every number in that table is well below what the code can do, and the reason is upstream's
own build flags rather than anything the cross build does.** `setup.py` appends `-O0 -g` to
`extra_compile_args` on every POSIX platform, and `extra_compile_args` land *after* `CFLAGS`
on the command line, so the last `-O` wins and the extensions are compiled unoptimised. The
published Android arm64 slice shows it directly: `lxb_css_selector_create` disassembles to 24
instructions there, the same count as a host `-O0` build of that source and twice the 12 the
same source gives at `-O2`, and two of its three unconditional branches jump to the
immediately following instruction. Rebuilding the Lexbor extension from the sdist with `-O2`
instead, on this desktop, took it from 54.0 to 212.4 MB/s at 28,267 bytes and from 54.8 to
202.1 MB/s at 276,127 — **3.9× and 3.7×** — and made the `.so` 13.7% smaller, 4,663,904 down
to 4,024,608 bytes. Nothing you can put in your own `pyproject.toml` changes this; it is
noted here so the table is not mistaken for the ceiling, and it is on the fix list in
[Build notes](#build-notes-maintainers).

**No device numbers appear anywhere on this page.** Everything below was measured on a desktop
or read out of the published wheels, and each claim says which. The
[`page-scrape`](examples/page-scrape) example exists to replace the timings with a phone's own.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. Both report the `lexbor` engine and produce identical results
from the bundled document: `li.post` matches three items, the scrape recovers all three posts
plus the stats table, and the tree repairs are the same on each — a `tbody` inserted where the
source has **0** start tags and the tree has 1 carrying 3 rows, **15 of 35** elements closed by
the parser rather than the author, `<b>and <i>weather</b></i>` re-nested as
`<b>and <i>weather</i></b>`, and a bare `<` kept as text so a title reads `Why 5 < 6 matters`.
That last one is the case `html.parser` is most likely to get wrong.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "selectolax",
]
```

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.<platform>]`
table: `flet build` resolves for the build host first, and PyPI has desktop wheels for every
host you would build from. The 0.4.10 release is 64 files — CPython 3.9 through 3.14 on macOS
(`x86_64` and `arm64`), Linux (`manylinux` and `musllinux` × `x86_64` and `aarch64`) and
Windows (`win32`, `win_amd64`, `win_arm64`), nine free-threaded `cp314t` wheels, and an sdist.
**None of those 64 files carries an Android or iOS tag**, which is why this recipe exists, and
it also means there is no shadowing question to think about: resolving each of the eighteen
mobile slices with `pip download --only-binary :all:` (pip 26.2.1) against PyPI with
`https://pypi.flet.dev` as `--extra-index-url` — the way serious_python 4.5.1 invokes pip —
picked this index's wheel eighteen times out of eighteen.

**The two halves of your app can be different versions, and that is expected.** PyPI is ahead
of this index — 0.4.11 is published there while this recipe ships 0.4.10 — so a bare
`selectolax` gives your laptop 0.4.11 under `flet run` and the device 0.4.10, with different
vendored Lexbor and Modest sources behind the same API. It resolves cleanly because neither
release carries a mobile tag, so the platform slices can only come from here. If a parse
differs between desktop and device and you cannot explain it, check the two versions before
suspecting anything else; pin `selectolax==0.4.10` in the example's style to make both halves
agree.

`Requires-Python` on every mobile wheel is `<3.15,>=3.9`, which constrains nothing you can
ship. The only `Requires-Dist` line is `Cython; extra == "cython"`, behind an extra nobody
enables, so nothing follows the wheel in — no `flet-lib*` and no transitive dependency.

No
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: the package's entire Python layer is a 141-byte `__init__.py` that names no
`__file__`, no `importlib.resources`, no `pkgutil` and no `open`, and nothing in the package
is read by path at run time — its only non-module members are a zero-byte `py.typed` and
eleven Cython `.pxi` includes, both build-time inputs. Both extensions carry a CPython ABI tag
on every slice, which is what serious_python's relocation into `jniLibs` keys on. No
architecture is excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed either.

**Budget for the size before you commit — this is a big wheel and it is the thing most likely
to surprise you.** Eighteen wheels at the current build number: Android arm64-v8a,
armeabi-v7a and x86_64 plus iOS device, arm64-simulator and x86_64-simulator, on each of
Python 3.12, 3.13 and 3.14. The wheels themselves are 2,033,209 to 2,300,764 bytes, but they
are compressed: what lands on the device, after
`flet build`'s default `--cleanup-packages` pass removes `**.c`, `**.pyx`, `**.pxd`, `**.pyi`
and `**.typed`, is

| per slice | bytes |
| --- | --- |
| `lexbor` extension | 4,486,032 – 4,604,144 (3,136,128 – 3,138,680 on armeabi-v7a) |
| `parser` extension | 3,376,552 – 3,468,600 (1,801,088 – 1,802,824 on armeabi-v7a) |
| `.pxi` Cython includes, 11 files | 109,890 |
| `__init__.py` | 141 |

That is **7.86 to 8.04 MB of native code per 64-bit slice** and 4.94 MB on armeabi-v7a. An
Android build targeting all three ABIs carries all three sets — 20,959,576 bytes measured
across the cp314 Android wheels — because `jniLibs` is per-ABI even though the Python half is
shared. The `.pxi` files are the cheap half of that and the only part you can recover; see
[Things to know](#things-to-know).

## Storage

**selectolax opens nothing on your behalf, so there is no cache directory to relocate and no
environment variable to set before importing.** The Cython sources shipped in the wheel — both
`.pyx` files and all eleven `.pxi` includes — contain no `open`, no `os.`, no `Path`, no
`getenv` and no networking call, and neither parser class takes a path: the first argument of
`LexborHTMLParser` and of `HTMLParser` is a `str` or a `bytes` of markup, and every argument
after it is a parsing option — `is_fragment`, `detect_encoding` and the like. (The C engines do
import `fopen`, `fread` and `fclose` from bionic, and Lexbor additionally `opendir`,
`readdir` and `stat`, because both libraries have file-loading entry points in C — but
nothing on the Python side reaches them.) Reading the file is your
job:

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
document declaring its own charset returns nothing but replacement characters where the
Modest backend returns the right text. The measurement is in
[Things to know](#things-to-know).

Where the file goes is the usual Flet split:
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
for something the app owns and cannot rebuild,
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a page you fetched and will fetch again.

**Do not hold many trees at once — a parsed document costs far more than its source.**
Measured on desktop as peak-RSS growth in a fresh process per engine, divided by the number of
trees held alive at once, after one warm-up parse so the allocator's own setup does not count:

| source bytes | Lexbor per tree | Modest per tree |
| --- | --- | --- |
| 1,186 | 316,621 (267×) | 382,157 (322×) |
| 28,267 | 869,171 (30.7×) | 1,008,026 (35.7×) |
| 276,127 | 5,449,318 (19.7×) | 5,593,498 (20.3×) |
| 918,727 | 19,378,995 (21.1×) | 18,038,784 (19.6×) |

So each parser instance has a fixed floor around 300–380 KB — both engines pre-allocate
memory pools — and then costs roughly **20× the source** on top. A 1 MB page is a ~20 MB
object. Hold a lot of them and the per-tree figure drops, because the pools get reused: the
918,727-byte document measured 20.7× per tree with five alive and 9.1× with fifty. Budget
against the table, not against the floor. Parse, extract what you need into ordinary Python
values, and drop the tree.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`page-scrape`](examples/page-scrape) — a deliberately broken feed page turned into records,
  with the parser's repairs listed, a live CSS selector box, and a timing comparison against
  `html.parser`.

## Threading

**Parsing releases the GIL; querying does not.** Both extensions import `PyEval_SaveThread`
and `PyEval_RestoreThread` as undefined symbols on every slice, and the shipped Cython sources
put `with nogil` around the document creation and the parse call — `lexbor.pyx` at the
`lxb_html_document_create`/`_parse_html_document` pair and `parser.pyx` around
`myhtml_create`/`myhtml_init`/`myhtml_parse` — and around nothing in the selector path.

Measured on a 10-core desktop, four threads each parsing its own 276,127-byte document, serial
wall time over parallel wall time, median of nine runs: **2.6–3.0× for Lexbor** (2.64 and 3.04
in two sweeps) and **2.8× for Modest**, against a `time.sleep` control at 3.87–3.95× and
`html.parser` at 0.99×. The same harness pointed at `tree.css("li.post > a.title")` on a
shared tree gives **0.90×** — no parallelism at all, because the query never drops the
interpreter.

The practical shape for a Flet app follows from that: put the parse in a
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker and
it genuinely competes with an idle event loop rather than blocking it; do not expect a pool of
threads running `css()` to go any faster than one.

**Reading one tree from several threads did not misbehave, but do not mutate one.** Eight
threads running 200 `css()` calls each against a single shared tree finished with zero
exceptions and exactly one distinct match count. That is a read-only result, and it is
the only thing measured: `decompose()`, `unwrap()`, `strip_tags()` and node insertion all
mutate the C tree, and nothing guards it — the only mutex in either generated `.c` file is
Cython's own `__Pyx_ModuleStateLookup_mutex`. Give each thread its own tree, or hold a
`threading.Lock` across the mutation.

The Flet-side rules apply as everywhere else, and the example shows both. A `run_thread`
worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try/except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no
log, no dialog and no crash.

## Android notes

- **Neither extension links anything but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all eighteen Android
  extensions, with no `SONAME`, no `RPATH`, no `RUNPATH` and **no `libc++_shared`** — both
  engines are C, not C++, so none of the usual Android C++ staging applies. Every `PT_LOAD`
  segment carries `0x4000` alignment, which Android 15 requires. arm64-v8a and x86_64 are
  `ELF64`; armeabi-v7a is a genuine `ELF32`/`ARM` build. All eighteen are stripped: zero
  `.symtab` and zero `.debug_*` sections.
- **The modules land in `jniLibs` as `libselectolax-lexbor.so` and `libselectolax-parser.so`.**
  serious_python's Gradle step mangles the dotted name by replacing dots with dashes
  (`mangledLib` in `serious_python_android-4.5.1/android/build.gradle.kts`), leaving
  `selectolax/lexbor.soref` and `selectolax/parser.soref` markers in `sitepackages.zip`. Read
  from serious_python's source, not from a built APK.
- **`selectolax/lexbor.soref` and a `selectolax/lexbor/` directory coexist in that zip, and the
  extension wins.** The directory holds six `.pxi` include files and no importable module, so
  nothing resolves through it; and serious_python's `_sp_bootstrap._SorefFinder` is inserted at
  the *front* of `sys.meta_path`, so `import selectolax.lexbor` is answered by the relocated
  extension before any path-based finder is consulted. A desktop install has the same pair
  side by side on disk and lands the same way — `selectolax.lexbor.__file__` resolves to
  `lexbor.cpython-314-darwin.so`, and `hasattr(selectolax.lexbor, "__path__")` is `False`.
- **`selectolax.modest` is importable on some Pythons here and not others, and nothing should
  import it.** It is a directory of three `.pxi` files compiled into `parser` at build time,
  with no runtime module behind it, and this recipe patches `__init__.py` so the package no
  longer tries. Write it yourself and the interpreter decides: reproducing serious_python's
  zip layout on a desktop from the shipped wheel, `import selectolax.modest` raises
  `ModuleNotFoundError: No module named 'selectolax.modest'` on 3.12 and 3.13, and
  `from selectolax import modest` raises `ImportError: cannot import name 'modest' from
  'selectolax'`; both succeed on 3.14 and hand back an empty namespace package. The
  *partially initialized module* error under [Build notes](#build-notes-maintainers) looks
  similar but is a different failure — the unpatched `__init__` dying mid-import, which is
  what the patch exists to prevent. The engines are `selectolax.parser` (Modest) and
  `selectolax.lexbor`; neither is affected.
- **The 3.12 Android slices name the extensions `lexbor.cpython-312.so` and
  `parser.cpython-312.so`, without the platform triplet**, while 3.13 and 3.14 use the full
  `lexbor.cpython-31X-aarch64-linux-android.so` form. Both spellings match the
  `\.(cpython-[^/]+|abi3)\.so$` tag serious_python's `jniLibs` relocation keys on, so both
  work.

## iOS notes

- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all eighteen iOS extensions, so the *Unsupported mach-o
  filetype (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not arise
  here. `otool -L` names exactly two libraries on every slice besides the extension's own
  install name: `@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib`.
- **The iOS slices are not stripped, and that is 809,064 bytes carried for nothing.** The
  cp314 device slice keeps an `LC_SYMTAB` of 22,521 entries on `lexbor` and 17,259 on
  `parser`, whose `__LINKEDIT` occupies 678,816 and 524,312 bytes of file (688,128 and 540,672
  of `vmsize`, if that is the field you read). `strip -x` takes `lexbor` from 4,545,440 to
  4,054,840 bytes and `parser` from 3,457,048 to 3,138,584 —
  490,600 and 318,464 saved. The eighteen Android extensions are stripped already.
- **`selectolax/modest/` and `selectolax/lexbor/` ship as real directories here**, not zip
  entries, so both are ordinary PEP 420 namespace packages and `import selectolax.modest`
  succeeds (and gives you an empty module). See the Android note above for why the same line
  behaves differently there.

## Things to know

- **Use `LexborHTMLParser` unless you need one of Modest's two remaining advantages.** The
  first is encoding detection. Handed the bytes of a windows-1251 document that declares
  `<meta charset=windows-1251>`, `HTMLParser(raw)` returns `'Русский'` and
  `LexborHTMLParser(raw)` returns a string of seven U+FFFD replacement characters;
  `HTMLParser(raw, detect_encoding=False)` returns `''`. Decoding the bytes yourself and
  passing a `str` gives Lexbor the right answer. The second is chained selection:
  `tree.select("li").css("a.title")` returns 3 matches on Modest and raises
  `NotImplementedError: This features is not supported by the lexbor backend. Please use
  Modest backend.` on Lexbor (the typo is upstream's). Everything else measured pointed the
  other way — see the `:is()` and `~` results at the top of this page.
- **`text(strip=True)` strips each text node, not the run of them, so words fuse together.**
  On `<a>Bees <b>and <i>weather</i></b></a>`: `text()` gives `'Bees and weather'`,
  `text(strip=True)` gives `'Beesandweather'`, `text(separator=" ")` gives
  `'Bees  and  weather'` with doubled spaces, and `text(separator=" ", strip=True)` gives
  `'Bees and weather'`. Prefer the last spelling, and `" ".join(value.split())` when the
  source indentation still shows through. Verified on desktop; this is upstream behaviour,
  not something the mobile build changes.
- **A node keeps its tree alive, so returned nodes outlive the parser.** Dropping the parser
  and forcing a `gc.collect()` left `nodes[0].attributes` and `nodes[0].text()` working on
  both engines. You do not need to keep a reference to the parser object yourself.
- **Catch two exception types around any selector you did not write yourself.** Lexbor raises
  `selectolax.lexbor.SelectolaxError: Can't parse CSS selector.`; Modest raises
  `ValueError: Bad CSS Selectors: <the selector>`. The two do not agree on *which* selectors
  are bad, either — over `li[`, `li >>`, `(((` and `li..post`, Lexbor rejected all four while
  Modest rejected only the last two and answered the first two with an empty list. Inside a
  Flet event handler an unhandled exception ends the session, so wrap the call; the
  [example](examples/page-scrape) catches both and prints the message.
- **You can recover 109,890 bytes per slice, and only that.** `flet build`'s default cleanup
  removes the two `.c` files, the `.pyx`, `.pxd`, `.pyi` and `py.typed` — 4,983,869 bytes of
  the 13,085,684-byte unpacked `selectolax/` directory on the cp314 Android arm64 wheel — but
  its glob list does not include `**.pxi`, so eleven Cython include files ship and are never read
  there. Adding them recovers the lot:

  ```toml
  [tool.flet.cleanup]
  package_files = ["**.pxi"]
  ```

  Verified on desktop that the package imports and parses with every `.pxi` deleted; the
  config key itself is read by `flet-cli` 0.86.5 and passed through as
  `--cleanup-package-files`, and no device build was run with it set.
- **You cannot ship only one engine.** `__init__.py` is `from . import lexbor, parser`, so
  deleting `parser.cpython-*.so` to save 3.4 MB makes even `from selectolax.lexbor import
  LexborHTMLParser` fail — reproduced on desktop, in a fresh process, as `ImportError: cannot
  import name 'parser' from partially initialized module 'selectolax'`. Both extensions load
  on every `import selectolax`; budget for both.
- **`MAX_HTML_INPUT_SIZE` is `2.5e9`**, a float, exported from both engine modules. It is not
  a limit you will meet on a phone — the memory table under [Storage](#storage) will stop you
  three orders of magnitude earlier.
- **Where the standard library is actually fine, use it.** `html.parser` handles character
  references, treats a bare `<` in text as text, and puts `<script>`/`<style>` content in CDATA
  mode so markup-shaped strings inside them are not parsed as markup — all three verified
  against the example's document. What it cannot do is build a tree: on that document it emits
  35 start tags and 20 end tags, so 15 elements are closed by the HTML5 rules and not by the
  author, and it never emits the `<tbody>` that a browser's DOM contains and that any selector
  copied out of DevTools will expect. If your input is a fragment you generated yourself,
  `html.parser` is 8 MB of native code cheaper.

## Build notes (maintainers)

The recipe is a `meta.yaml` and one patch. Upstream's `setup.py` compiles the vendored Lexbor
and Modest C trees straight into two `Extension`s — no system dependency, no `extra_objects`
unless you pass `--static`, and its only platform fork is `windows_nt` against `posix`, which
selects the `myport`/`ports` source files and nothing a mobile target gets wrong. So there is
little for a cross build to trip over, and a bump that suddenly needs build flags means
upstream restructured rather than that the toolchain drifted.

Two upstream knobs exist and are not used. `--static` links prebuilt archives instead of
compiling the trees, which we have no archives for. `--disable-modest` (or `USE_MODEST=""` —
and only an *empty* value, since `INCLUDE_MODEST = bool(os.environ.get("USE_MODEST", True))`
makes `USE_MODEST=0` mean *enabled*) drops the Modest extension, worth 3,376,552 to
3,468,600 bytes per 64-bit slice — about 43% of the payload. It cannot be used on its own —
`__init__.py` imports both, and a package missing `parser.cpython-*.so` fails even
`from selectolax.lexbor import LexborHTMLParser`, reproduced on a desktop in a fresh process
as `ImportError: cannot import name 'parser' from partially initialized module 'selectolax'`.
Extending the existing patch to drop `parser` from `__init__.py` alongside `modest` would
make it viable, at the cost of the two Modest-only behaviours documented under
[Things to know](#things-to-know) and of any consumer already importing
`selectolax.parser`.

**The most valuable open change here is not a bump: patch out upstream's `-O0`.** The recipe
inherits `extra_compile_args=[..., "-O0", "-g"]` from `setup.py`'s POSIX branch for both
extensions, and because `extra_compile_args` are appended after `CFLAGS`, **a `script_env`
`CFLAGS` cannot override it** — verified by building the sdist with `CFLAGS="-O2"` on a
desktop and getting a 4,625,888-byte extension running at 51.7 MB/s, indistinguishable from
the unmodified build. Editing the two lines in `setup.py` does work: the same source at `-O2`
was 4,024,608 bytes and 202–212 MB/s against 54 MB/s, i.e. **3.7–3.9× faster and 13.7%
smaller**, which is 639,296 bytes on the Lexbor extension alone, before counting Modest's.
Dropping `-g` separately would also account for most of the unstripped iOS `__LINKEDIT`
noted above. This has not been done,
and it should be measured on device before it is claimed anywhere consumer-facing.

**The patch's failure mode is Python-version-dependent, which is not obvious from the patch
and is the thing most likely to mislead a future bump.** Reproducing serious_python's Android
layout on a desktop — a `STORED` zip built from the wheel with each tagged `.so` replaced by
its `.soref` marker, `synthesizePackageInits()` applied exactly as
`serious_python_android-4.5.1/android/build.gradle.kts` implements it, and a stand-in
meta_path finder for the markers — the unpatched `from . import lexbor, modest, parser` fails
on **3.12.13 and 3.13.14** with `ImportError: cannot import name 'modest' from partially
initialized module 'selectolax'` and **succeeds on 3.14.6**. The reason is CPython, not Flet:
3.14's `Lib/zipimport.py` `_read_directory` synthesises implied directory entries into its
file table (the `files[name] = None` loop), so `_is_dir` finds `selectolax/modest/` and
zipimport returns a namespace portion for it; 3.12 and 3.13 have no such loop. The patched
`__init__` passes on all three. So: **do not conclude the patch is obsolete from a green 3.14
run**, and if Flet ever drops 3.12 and 3.13 the patch becomes genuinely unnecessary rather
than merely quiet.

Both extension names collide with a sibling directory of the same name inside the package
(`lexbor.cpython-*.so` beside `lexbor/`, and `modest/` beside no module at all). That is
upstream's layout, and it survives only because the include-only directories contain no
`.py`/`.pyc`/`.soref` member, which is exactly the condition
`synthesizePackageInits()` tests. If upstream ever adds a real Python module under
`selectolax/lexbor/`, Android would synthesise `selectolax/lexbor/__init__.py` and the
directory would start competing with the extension — worth a glance at the wheel's file list
on any bump, not just at the version number.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **Whether `__init__.py` still imports `modest`**, and whether the patch still applies. It is
  a one-line change to a file upstream edits rarely, so a silent rebase failure is the likely
  way it goes wrong. Check the built wheel's `__init__.py` reads `from . import lexbor,
  parser`, not the recipe's patch file.
- **Whether Modest is still there at all.** Upstream calls it deprecated in the class docstring
  shipped in the wheel. The day it is removed, this page's engine comparison, the example's
  segmented button and roughly 3.4 MB per slice all change at once — and that is an
  improvement to document, not a regression.
- **Whether upstream has started publishing a mobile-tagged or a `py3-none-any` wheel.** PyPI
  is already ahead of this recipe — 0.4.11 was published there while this page was written —
  and a bare `selectolax` still resolves from this index on every mobile slice only because
  none of upstream's 64 files for either release carries a tag a mobile target matches. pip
  picks the highest *version* before it looks at tags, so the first `any` wheel upstream
  publishes silently takes over every mobile resolve and [Install](#install)'s "no shadowing
  question" paragraph becomes wrong.
- **The size table under [Install](#install)**, which is the most consumer-visible claim here
  and moves with every vendored-C bump.
- **That `METADATA` still carries only the `Cython` extra**, and that no `.py` in the package
  has acquired a `__file__` read. Either would falsify [Install](#install) without failing
  anything.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an untagged
  `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent
  `ModuleNotFoundError` on device. Match the `lexbor.cpython-`/`parser.cpython-` prefixes, not
  an exact suffix.
- **The linkage**, per slice: `DT_NEEDED` still four bionic and interpreter entries with no
  `libc++_shared`, `0x4000` `PT_LOAD` alignment on all three Android ABIs, `MH_DYLIB` on all
  three iOS ones.
- **The GIL split**, since [Threading](#threading) rests on it: `with nogil` around the parse
  and not around the selector path. Upstream extending it to `css()` would invert that
  section's advice.

`tests/test_selectolax.py` covers one parse-and-select per engine. The gaps worth closing at
the next touch, in rough order of value: **an assertion that `selectolax.modest` is not
imported by `selectolax`**, since that is what the patch exists to guarantee and nothing on
device checks it today; a malformed-markup case (an unclosed `<li>` or a missing `<tbody>`)
that would catch an engine built without its tree-construction rules; and the `:is()`
divergence between the engines, which pins the claim this page's opening rests on to the
shipped binaries. A timing assertion is deliberately not on that list — it would flake in CI.
