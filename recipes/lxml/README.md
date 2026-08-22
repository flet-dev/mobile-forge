# lxml

[`lxml`](https://lxml.de/) is the Python binding for libxml2 and libxslt: the ElementTree API
you already know, backed by a C parser, plus the whole XML stack the standard library never
had — [XPath 1.0](https://lxml.de/xpathxslt.html#xpath),
[XSLT 1.0](https://lxml.de/xpathxslt.html#xslt) with EXSLT,
[XML Schema](https://lxml.de/validation.html#xmlschema),
[RelaxNG](https://lxml.de/validation.html#relaxng),
[DTD](https://lxml.de/validation.html#dtd-1), C14N canonicalisation, XInclude, and a forgiving
[HTML parser](https://lxml.de/lxmlhtml.html). On a phone the case for it is the same as on a
server, only sharper: parsing, validating and transforming all happen in C with the GIL
released, so a document that would cost thousands of Python objects costs one call. The
standard library's `xml.etree` has no XSLT engine and no schema validation at all, so those two
arrive with this wheel or not at all.

Every Python file in these wheels is byte-identical to the desktop package's, so
[upstream's documentation](https://lxml.de/index.html#documentation) applies unchanged. What
differs is the libxml2 underneath: a few of its optional pieces are compiled out on both
platforms, and one capability — character-set conversion — differs between Android and iOS.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "lxml",
]
```

[`lxml.isoschematron`](https://lxml.de/validation.html#schematron-1) needs an
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry. Its module
body loads five stylesheets and a RelaxNG schema by building filesystem paths from `__file__`,
and inside Android's zipped site-packages that is not a path anything can open, so the import
dies on the first of them with
`OSError: Error reading file '.../resources/xsl/XSD2Schtrn.xsl': failed to load external entity`.
If you import it, add:

```toml
[tool.flet.android]
extract_packages = ["lxml"]
```

The mobile wheels carry upstream's extras metadata unchanged, so `lxml[cssselect]` works too —
but naming the package outright is clearer about what is actually being installed:

| you want | add | without it |
| --- | --- | --- |
| [`Element.cssselect()`](https://lxml.de/cssselect.html), `lxml.cssselect` | `cssselect` | `ImportError: cssselect does not seem to be installed.` |
| [`lxml.html.html5parser`](https://lxml.de/html5parser.html) | `html5lib` | `ModuleNotFoundError: No module named 'html5lib'` |
| [`lxml.html.soupparser`](https://lxml.de/elementsoup.html) | `beautifulsoup4` | `ModuleNotFoundError: No module named 'BeautifulSoup'` (it tries `bs4` first and falls back to the Python 2 module name, and that second failure is the one you see) |
| `lxml.html.clean` | `lxml_html_clean` | `ImportError: lxml.html.clean module is now a separate project lxml_html_clean.` |

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`invoice-xslt`](examples/invoice-xslt) — validates a generated invoice against an XSD and
  renders it with an XSLT stylesheet that adds the money up itself.

## Usage in a Flet app

Parse, query or transform, and put the result in a control:

```python
from lxml import etree

root = etree.fromstring(blob)                     # bytes in, parsed in C
total = root.xpath("sum(//line/@amount)")         # XPath 1.0, returns a float
report = etree.XSLT(etree.XML(stylesheet))(root)  # XSLT 1.0 with EXSLT
page.add(ft.Text(str(report)))
```

Feed the parser bytes, not `str`. [`etree.fromstring`](https://lxml.de/parsing.html) accepts
text, but a document whose declaration names an encoding raises
`ValueError: Unicode strings with encoding declaration are not supported.` — decode-then-parse
is a habit that survives on desktop and bites once real files arrive.
[`etree.parse`](https://lxml.de/parsing.html) takes a path or any file object.

### Storage

`etree.parse` and [`ElementTree.write`](https://lxml.de/api.html#serialisation) take ordinary
filesystem paths, so anything the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "catalogue.xml")
tree.write(path, encoding="UTF-8", xml_declaration=True)
tree = etree.parse(path)
```

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose.

**Writing a compressed file works; reading one back does not.**
`tree.write(path, compression=9)` produces a real gzip file on both platforms — lxml notices
that libxml2 has no zlib and routes the bytes through Python's `GzipFile` instead. Nothing does
that for you on the way in, so open it yourself:

```python
with gzip.open(path, "rb") as f:
    tree = etree.parse(f)
```

`decompress=True` is not the alternative; see the gzip bullet in
[Things to know](#things-to-know).

### Threading

**lxml releases the GIL for the work that matters, and libxml2 here is built with threading
on.** Parsing, serialising, XPath, XSLT and schema validation in a background thread genuinely
overlap with the UI rather than only deferring the freeze.

Push that work to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end the
handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads. `run_thread` also swallows any exception the worker raises, so wrap
the body in `try/except` if you want to know it failed.

Upstream's [threading rules](https://lxml.de/FAQ.html#can-i-use-threads-to-concurrently-access-the-lxml-api)
apply unchanged and are mostly permissive: `XSLT`, `XMLSchema` and `RelaxNG` objects can be
shared between threads. Two things are worth knowing. Sharing a *parser* serialises access to
it, so use the default parser or `.copy()` one per thread. And an
[`XPath`](https://lxml.de/xpathxslt.html#the-xpath-class) evaluator holds an internal lock
around its compiled context, so give each thread its own rather than sharing one.

### Encodings

**This is the one place the two platforms answer differently.** iOS has the system libiconv
behind libxml2's converter table. Android's bionic had none at the API level this recipe
targets, so libxml2 there is built without iconv and its character-set support stops at what it
has compiled in: UTF-8, UTF-16 (little- and big-endian, with or without a BOM), US-ASCII,
ISO-8859-1 through ISO-8859-11 and ISO-8859-13 through ISO-8859-16, and windows-1252.

Only the ISO-8859-2-and-up entries are conditional: libxml2 compiles those tables in only when
neither iconv nor ICU is enabled, so they are Android built-ins and libiconv's job on iOS.
Apple's libiconv knows all of them, so a caller should see no difference — but it is a
different piece of software answering, which is why the example probes rather than trusting a
list.

Everything else libxml2 knows the name of — Shift_JIS, EUC-JP, ISO-2022-JP, UCS-2, UCS-4,
IBM037 — and every name it does not, such as KOI8-R, GBK, Big5 and the other windows-125x
pages, is left for iconv. On iOS those reach the system libiconv; on Android there is nothing
to hand them to, so the parse raises `XMLSyntaxError: Unsupported encoding: Shift_JIS` — with
the line and column of the declaration appended, so it looks like a syntax error rather than a
missing codec. Serialising *to* one of those encodings fails differently, with
`LookupError: unknown encoding: 'Shift_JIS'`.

Keep the conversion in Python instead, whose codec set is complete on both platforms: decode
the bytes yourself and hand lxml text or UTF-8 bytes, dropping or rewriting the XML declaration
as you go. Do not branch on the encoding name, and do not branch on the platform — ask the
build, with `"iconv" in etree.LIBXML_FEATURES`. The
[`invoice-xslt`](examples/invoice-xslt) example prints that answer next to four probe
encodings, which is the quickest way to see the split on a device.

### App size

Small by the standards of this index, and per-architecture:

| slice | lxml, download → unpacked | supporting wheels, download → unpacked | installed, after cleanup |
| --- | --- | --- | --- |
| Android arm64-v8a | 1.6 MB → 4.9 MB | 0.9 MB → 2.6 MB | 6.3 MB |
| iOS arm64 (device) | 2.9 MB → 8.7 MB | 3.7 MB → 10.2 MB | 8.3 MB |

Decimal MB; `du -h` reports binary units and will show these as smaller numbers. The last
column is what survives Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup), which is also why
iOS lands under what its wheels suggest: there the C libraries are linked *into* lxml rather
than loaded beside it, so what ships alongside is static archives, headers and command-line
tools — exactly what cleanup deletes.

Two levers. Cleanup does not take lxml's own `.pxi` Cython sources, 0.58 MB that nothing at
runtime reads: add `[tool.flet.cleanup] package_files = ["lxml/*.pxi"]` if you are counting
megabytes, and do not widen that glob towards `opt/lib`, which on Android holds the libraries
the app cannot start without. And the table is per-ABI, so on Android an app bundle, split
APKs, or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) saves
considerably more.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, which bundles a libxml2 built with a wider feature
set than these. Three things therefore work on your laptop and fail on a device, none of them
at build time: `etree.Schematron` constructs fine on desktop and raises on device;
`decompress=True` really decompresses on desktop and is a no-op on device, turning gzip input
into what looks like malformed XML; and Shift_JIS, KOI8-R and the rest of the iconv-only names
parse on desktop and on iOS but fail on Android.

So validate anything touching schemas, compressed input or non-Latin encodings on a real device
or emulator/simulator. Printing `etree.LIBXML_FEATURES` once at startup is the fastest check —
all three answers are in it.

## Things to know

- **`etree.Schematron` is compiled out on both platforms and raises the moment you construct
  one.** libxml2 is built without `LIBXML_SCHEMATRON_ENABLED`, so lxml's `config.ENABLE_SCHEMATRON`
  is 0 and `__init__` raises
  `SchematronError: lxml.etree was compiled without Schematron support.` The class is still in
  the binary, so `dir(etree)` and editor autocomplete both suggest it. Use
  [`lxml.isoschematron.Schematron`](https://lxml.de/validation.html#schematron-1) instead: it is
  shipped complete — the RelaxNG grammar and all five stylesheets are in the wheel — and
  implements ISO Schematron in pure XSLT on top of the XSLT engine that *is* here. Upstream
  deprecates `etree.Schematron` anyway. Remember the `extract_packages` entry from
  [Install](#install) if you go this way.
- **libxml2 has no network layer at all**, which is a hardening improvement as much as a
  limitation. HTTP support was removed from libxml2 in 2.15 outright, so parsing from a URL,
  fetching an external DTD, XInclude over `http` and XSLT `document()` against a remote URL all
  fail; lxml's parsers already default to `no_network=True` regardless. Fetch the bytes
  yourself and pass them to `etree.fromstring`, or a file object to `etree.parse`; for entity
  and DTD resolution, supply an [`etree.Resolver`](https://lxml.de/resolvers.html) subclass that
  serves bytes you already have.
- **gzip input is never decompressed, and `decompress=True` does not change that.** libxml2 is
  built without zlib on both platforms, so the `XML_PARSE_UNZIP` flag that `decompress=True`
  sets has nothing behind it. Feeding gzip bytes to the parser gives
  `XMLSyntaxError: Start tag expected, '<' not found, line 1, column 1`, which reads like
  corrupt XML rather than a missing codec. Every parser in the shipped source defaults to
  `decompress=False`, so this only bites code that opts in. Decompress with the `gzip` module;
  writing compressed output still works, as [Storage](#storage) describes.
- **libxml2's own resource limits apply, and one is reachable with ordinary data.** A single
  text node over `XML_MAX_TEXT_LENGTH` — 10,000,000 bytes in the `parserInternals.h` both
  platforms ship, byte-identical — stops the parse with
  `XMLSyntaxError: Resource limit exceeded: Text node too long, try XML_PARSE_HUGE`, which
  reads like malformed input rather than a cap. A base64 payload or an embedded document is the
  usual way to trip it. `etree.XMLParser(huge_tree=True)` raises the ceiling a thousandfold but
  lifts the depth and entity-expansion guards with it, so keep it for documents you produced
  yourself. Entity expansion is otherwise safe by default: every parser here defaults to
  `resolve_entities='internal'`, so a document declaring an external entity gets
  `XMLSyntaxError: Entity 'x' not defined` rather than a fetch, while its own internal entities
  still expand.
- **EXSLT is there, minus crypto.** `libexslt` registers common, dates-and-times, dynamic,
  functions, math, sets and strings, plus the `http://icl.com/saxon` namespace — the same list
  on both platforms. The `http://exslt.org/crypto` namespace is the exception: these builds are
  configured without it, so `crypto:md5`, `crypto:sha1` and `crypto:rc4_encrypt` have nothing to
  bind to. Hash in Python with `hashlib` and either precompute the value into the source tree or
  [register it as an extension function](https://lxml.de/extensions.html).
  [EXSLT regular expressions](https://lxml.de/xpathxslt.html#regular-expressions-in-xpath)
  (`re:test`, `re:match`, `re:replace`) work regardless of libexslt, because lxml implements
  that namespace itself on top of Python's `re`.
- **The HTML parser is not an HTML5 tree builder.** libxml2's own header says so: as of 2.14 the
  tokenizer conforms to HTML5, but "tree construction still follows a custom, unspecified
  algorithm with many differences to HTML5". For forgiving extraction the built-in parser is
  fine and fast, and it is what [`lxml.html`](https://lxml.de/lxmlhtml.html) uses. When the
  shape of the tree matters — because you are matching what a browser would produce — add
  `html5lib` and use `lxml.html.html5parser.fromstring`, which builds a spec-conformant tree and
  still hands you lxml elements, XPath and cssselect.
- **What is compiled in.** Everything else you would reach for: XPath, XInclude, XML Schema,
  RelaxNG, DTD validation, C14N canonicalisation, the regexp and pattern engines, the push
  parser behind [`iterparse`](https://lxml.de/parsing.html#iterparse-and-iterwalk), incremental
  writing via [`etree.xmlfile`](https://lxml.de/api.html#incremental-xml-generation), and
  threading. Switched off on **both** platforms, not one: Schematron, ICU, zlib, HTTP and
  per-thread allocation. The iconv gate under [Encodings](#encodings) is the whole of the
  Android/iOS difference — there is no second asymmetry to go looking for.
- **Ask the wheel rather than trusting this page.** `etree.LIBXML_FEATURES` is a set built by
  asking libxml2 at runtime which of its optional pieces are present, and
  `etree.LIBXML_COMPILED_FEATURES` is the same question answered from the headers lxml was
  compiled against. Alongside `etree.LXML_VERSION`, `etree.LIBXML_VERSION` and
  `etree.LIBXSLT_VERSION`, that is the fastest way to see what a particular device got; the
  example app puts all of it in its header lines.

## Build notes (maintainers)

### Recipe shape

Three recipes in a chain: `flet-libxml2` and `flet-libxslt` build the C libraries, and this one
consumes both. They are `requirements.host`, **not** `requirements.host_build`, and that is
deliberate. `host_build` would put them in the cross environment for the link and then not ship
them — fine on iOS, where they are statically absorbed into `etree.so` (a `MH_DYLIB` marked
`NOUNDEFS`, naming no libxml2 or libxslt dylib in `otool -L`), and fatal on Android, where
`etree.so` resolves `libxslt.so`, `libexslt.so` and `libxml2.so` by bare soname out of
`jniLibs`, with no `RPATH` or `RUNPATH` at all. One recipe has to satisfy both, so they are
ordinary runtime dependencies and appear in `Requires-Dist` on both platforms. On iOS that is
redundant rather than harmful: their payload is static archives, headers and a `bin` directory,
which is exactly serious_python's `junkFilesMobile` set, so Flet's default cleanup empties them
unprompted. Making the dependency conditional on the SDK would save nothing an app author can
measure and would give the two platforms different metadata.

The Android-shared / iOS-static split is a property of the two `flet-lib*` recipes' own
`build.sh`, not of anything here, and most of what this page says about linkage and size rests
on it — so a change there lands here.

The wheel holds 97 files: 7 native extensions (`etree`, `objectify`, `builder`, `sax`,
`_elementpath`, `html/diff`, `html/_difflib`), 6 of `.dist-info` metadata, and 84 others, every
one hash-identical to the same-version PyPI wheel for macOS. Android and iOS ship the same 97
names as each other, the native suffix aside; nothing was patched at the Python level, which is
what lets this page point at upstream's documentation without a translation step. The desktop
wheel additionally carries 77 files under `lxml/includes/{libxml,libxslt,libexslt,extlibs}/` —
bundled C headers plus four `__init__.py` — because it bundles the two libraries where this
recipe links against external copies. Nothing reads them at runtime.

The four optional integrations in [Install](#install) all resolve from PyPI as pure-Python
wheels, so none of them needs a recipe of its own.

### Upgrade hazards

`meta.yaml` routes lxml 5.x to libxml2 2.9.8 / libxslt 1.1.32 and 6.x to 2.15.3 / 1.1.45, so a
major bump is a three-recipe move rather than one.

**Do not "fix" the Android encoding gap by enabling iconv.** Turning `LIBXML_ICONV_ENABLED` on
for Android would also switch *off* libxml2's built-in ISO-8859-2 through ISO-8859-16 tables,
which are compiled in only when neither iconv nor ICU is enabled. Unless bionic's iconv at the
targeted API level covers all of them, that trades three broken encodings for fifteen — and
does it silently, since nothing in `tests/` would notice.

### Re-verification checklist

Almost every consumer claim above rests on a build-time gate rather than on a test, so work
through this on a bump, in rough order of how quietly each can go wrong.

- **The feature gates, from the shipped headers rather than the configure line.** Diff
  `opt/include/libxml/xmlversion.h` between the Android and iOS `flet-libxml2` wheels: it must
  differ on exactly one line, the `LIBXML_ICONV_ENABLED` gate. A second difference means the
  platforms have diverged in a way this page denies, and a *change* to the off-set (Schematron,
  ICU, zlib, HTTP) silently falsifies two or three bullets in [Things to know](#things-to-know)
  without failing the build. libxslt's `xsltconfig.h` should stay byte-identical between the
  platforms, and so should `parserInternals.h`, which is where the 10 MB text-node limit comes
  from.
- **The encoding list.** It is `defaultHandlers[]` in libxml2's `encoding.c`, where the
  ISO-8859-2-and-up entries sit behind
  `!LIBXML_ICONV_ENABLED && !LIBXML_ICU_ENABLED && LIBXML_ISO8859X_ENABLED` — so they are built
  in on Android and libiconv's job on iOS, and checking `LIBXML_ISO8859X_ENABLED` alone gives
  the wrong answer for iOS. Upstream moves entries in and out: `windows-1252` only became a
  built-in in 2.15. Re-derive the list from the source of the version being built, because a
  name that quietly stops being built in becomes an Android-only runtime failure in an app that
  was working.
- **Threading.** `LIBXML_THREAD_ENABLED` set in the shipped `xmlversion.h`, libxml2 importing
  the pthread mutex and thread-local-storage functions, and the `with nogil` blocks in the
  shipped Cython sources — twelve in `parser.pxi`, five in `serializer.pxi`, four in
  `xpath.pxi`, three each in `xslt.pxi` and `xmlschema.pxi`.
- **The linkage model on both sides.** Android: `etree.so`'s `DT_NEEDED` still names
  `libxslt.so`, `libexslt.so` and `libxml2.so`, with no `RPATH`/`RUNPATH`. iOS: `otool -hv`
  still reports `NOUNDEFS`, `otool -L` still shows no libxml2 dylib, and `_iconv`, `_iconv_open`
  and `_iconv_close` still come from `/usr/lib/libiconv.2.dylib`. If iOS ever links dynamically,
  the static-absorption argument above and the size table both change.
- **Whether cleanup still empties the iOS lib wheels.** The `**.a` / `**.h` / `bin` globs are
  serious_python's, and `cleanup.packages` defaulting to true is a `flet build` setting; both
  are outside this recipe, so a Flet bump can invalidate the iOS size figure with nothing here
  moving.
- **The EXSLT namespace list, and the absence of crypto.** Read it off the built binaries:
  `strings` on the Android `libexslt.so`, and on the iOS `etree.so` for the static side. A
  libxslt release that starts building crypto unconditionally would make one bullet wrong in the
  direction users notice least.
- **The exact error strings.** The four optional-integration messages and the isoschematron
  `OSError` in [Install](#install) come from `lxml/cssselect.py`, `lxml/html/clean.py`, plain
  import failures and libxml2's file loader; the Schematron and encoding messages come from
  `schematron.pxi`, libxml2's `encoding.c` and `serializer.pxi`. All get reworded between
  releases.
- **The file count and the sizes.** The 97-file wheel, the 7 native modules, the 84 hash-matched
  files, the per-slice size table and the 0.58 MB of `.pxi` are all measured. Recount and
  re-measure in decimal; do not scale.

### Coverage gaps

`tests/test_lxml.py` parses a two-element document and checks the tags. That is the whole of
it: nothing exercises XSLT, EXSLT, XML Schema, RelaxNG, the encoding split, `isoschematron`
under `extract_packages`, or the Android soname resolution for the three shared libraries. So
essentially none of the consumer-facing claims above is protected by CI, and every one has to be
re-checked by hand. Extending that file is the highest-value change available to this recipe:
an XSLT round trip, an XSD pass/fail pair, an assertion that `etree.Schematron` raises, and an
encoding probe gated on `"iconv" in etree.LIBXML_FEATURES` would cover most of this page. Per
the repo's test convention, assert the feature set and the relationships rather than exact
version numbers, and give every test function a docstring.
