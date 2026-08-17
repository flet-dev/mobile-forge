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
platforms, and exactly one capability differs between Android and iOS. Both are covered below.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "lxml",
]
```

Two more wheels come along and need no configuring: `flet-libxml2` and `flet-libxslt`, which
carry the two C libraries. They are named in the wheel's `Requires-Dist`, so the resolver
brings them in on both platforms — though only Android actually loads them at runtime, see
[iOS notes](#ios-notes).

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS
on device and both simulator slices, on Python 3.12, 3.13 and 3.14. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed — the 32-bit ARM wheel is built and complete.

No [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry is
needed for `lxml.etree`, `lxml.html` or `lxml.objectify`: nothing in the package reads a file
from disk at import, so it runs as-is out of Android's zipped site-packages. The one exception
is [`lxml.isoschematron`](https://lxml.de/validation.html#schematron-1), whose module body
loads five stylesheets and a RelaxNG schema by building filesystem paths from `__file__` —
which inside the zip is not a path anything can open. If you import it, add:

```toml
[tool.flet.android]
extract_packages = ["lxml"]
```

The four optional integrations upstream offers all resolve from PyPI as pure-Python wheels, so
none of them needs a recipe. The mobile wheels carry upstream's extras metadata unchanged, so
`lxml[cssselect]` works too — but naming the package outright is clearer about what is actually
being installed:

| you want | add | without it |
| --- | --- | --- |
| [`Element.cssselect()`](https://lxml.de/cssselect.html), `lxml.cssselect` | `cssselect` | `ImportError: cssselect does not seem to be installed.` |
| [`lxml.html.html5parser`](https://lxml.de/html5parser.html) | `html5lib` | `ModuleNotFoundError: No module named 'html5lib'` |
| [`lxml.html.soupparser`](https://lxml.de/elementsoup.html) | `beautifulsoup4` | `ModuleNotFoundError: No module named 'BeautifulSoup'` (it tries `bs4` first and falls back to the Python 2 module name, and that second failure is the one you see) |
| `lxml.html.clean` | `lxml_html_clean` | `ImportError: lxml.html.clean module is now a separate project lxml_html_clean.` |

## Storage

[`etree.parse`](https://lxml.de/parsing.html) and
[`ElementTree.write`](https://lxml.de/api.html#serialisation) take ordinary filesystem paths,
so anything the app owns belongs in
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
that libxml2 has no zlib and routes the bytes through Python's `GzipFile` instead. Nothing
does that for you on the way in, so open it yourself:

```python
with gzip.open(path, "rb") as f:
    tree = etree.parse(f)
```

See the gzip bullet in [Things to know](#things-to-know) for why `decompress=True` is not the
answer.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`invoice-xslt`](examples/invoice-xslt) — validates a generated invoice against an XSD and
  renders it with an XSLT stylesheet that adds the money up itself.

## Threading

**lxml releases the GIL for the work that matters, and libxml2 here is built with threading
on.** The `with nogil` blocks are in the shipped Cython sources — twelve in `parser.pxi`, five
in `serializer.pxi`, four in `xpath.pxi`, three each in `xslt.pxi` and `xmlschema.pxi` — and
`LIBXML_THREAD_ENABLED` is set in the shipped `xmlversion.h`, with libxml2 importing the
pthread mutex and thread-local-storage functions to match. So parsing, serialising, XPath,
XSLT and schema validation in a background thread genuinely overlap with the UI rather than
only deferring the freeze.

Push that work to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads. Note that `run_thread` also swallows any exception the worker
raises, so wrap the body in `try/except` if you want to know it failed.

Upstream's [threading rules](https://lxml.de/FAQ.html#can-i-use-threads-to-concurrently-access-the-lxml-api)
apply unchanged, and they are mostly permissive: `XSLT`, `XMLSchema` and `RelaxNG` objects can
be shared between threads. Two things are worth knowing. Sharing a *parser* serialises access
to it, so use the default parser or `.copy()` one per thread. And an
[`XPath`](https://lxml.de/xpathxslt.html#the-xpath-class) evaluator holds an internal lock
around its compiled context, so give each thread its own instead of sharing one.

## Android notes

**There is no iconv, so libxml2's character-set support stops at what it has built in.** This
is the one functional difference between the two mobile platforms — Android's bionic had no
iconv at the API level this recipe targets, so `flet-libxml2` is configured without it, and
the shipped `xmlversion.h` leaves `LIBXML_ICONV_ENABLED` undefined. What Android has built in,
and therefore what works with no iconv behind it at all:

- UTF-8, UTF-16 (little- and big-endian, with or without a BOM), US-ASCII
- ISO-8859-1 through ISO-8859-11 and ISO-8859-13 through ISO-8859-16
- windows-1252

Only the ISO-8859-2-and-up entries in that list are conditional: libxml2 compiles those
conversion tables in only when neither iconv nor ICU is enabled, so they are in the Android
`libxml2.so` and absent from the iOS `libxml2.a`, where the same names are libiconv's to serve.
Apple's libiconv knows all of them, so a caller should see no difference — but on iOS it is
libiconv answering rather than a built-in table, which is why the example probes instead of
trusting a list.

Everything else libxml2 knows the name of — Shift_JIS, EUC-JP, ISO-2022-JP, UCS-2, UCS-4,
IBM037 — and every name it does not, such as KOI8-R, GBK, Big5 and the other windows-125x
pages, is left for iconv to handle. On Android there is nothing to hand them to, so the parse
raises `XMLSyntaxError: Unsupported encoding: Shift_JIS` — with the line and column of the
declaration appended, so it looks like a syntax error rather than a missing codec. Serialising
*to* one of those encodings fails differently, with
`LookupError: unknown encoding: 'Shift_JIS'`.

The fix is to keep the conversion in Python, whose codec set is complete on both platforms:
decode the bytes yourself and hand lxml text or UTF-8 bytes, dropping or rewriting the XML
declaration as you go. Do not branch on the encoding name — ask the build instead, with
`"iconv" in etree.LIBXML_FEATURES`. The
[`invoice-xslt`](examples/invoice-xslt) example prints that answer next to four probe
encodings, which is the quickest way to see the split on a device.

The three C libraries ride into the APK as `jniLibs` and resolve by bare soname: `etree.so`
names `libxslt.so`, `libexslt.so` and `libxml2.so` in its `DT_NEEDED` list and carries no
`RPATH` or `RUNPATH` at all. That is why `flet-libxml2` and `flet-libxslt` are load-bearing
here and why they need no `extract_packages` entry of their own.

## iOS notes

**libxml2 and libxslt are linked *into* lxml here, not loaded beside it.** `etree.so` is a
`MH_DYLIB` marked `NOUNDEFS`, and `otool -L` on it lists only `Python.framework`,
`/usr/lib/libiconv.2.dylib`, `/usr/lib/libz.1.dylib` and `libSystem` — no libxml2 or libxslt
dylib, because both are statically absorbed. That is what makes the iOS `etree.so` 3.9 MB
against Android's 1.9 MB.

The practical consequence is that `flet-libxml2` and `flet-libxslt` contribute nothing at
runtime on iOS: their payload is static archives, headers and command-line tools, none of
which the app can use. They are still named in `Requires-Dist` and still installed, so they
would be 10 MB of dead weight — except that Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes `*.a`,
headers and any `bin` directory, which happens to be their entire contents. Nothing to
configure; see the size table in [Things to know](#things-to-know) for what actually lands.

iconv **is** present here, unlike on Android — `etree.so` imports `_iconv`, `_iconv_open` and
`_iconv_close` from `/usr/lib/libiconv.2.dylib`, and `LIBXML_ICONV_ENABLED` is set. So an
encoding name libxml2 has no built-in converter for goes to the system libiconv here instead of
failing outright, which is what makes the list in [Android notes](#android-notes) a limitation
of one platform rather than of the recipe. Which names iOS's libiconv actually accepts is its
business, not lxml's; the [`invoice-xslt`](examples/invoice-xslt) example probes four of them so
you can check on the device you care about. That gate is the only line that differs between the
two platforms' `xmlversion.h`, and everything switched off is switched off on both. It is not a
one-line difference in the built library, though: enabling iconv also drops libxml2's built-in
ISO-8859-2 through ISO-8859-16 tables, which is why the list in
[Android notes](#android-notes) is Android's built-in set and not a shared one.

## Things to know

- **`etree.Schematron` is compiled out on both platforms and raises the moment you construct
  one.** libxml2 is built without `LIBXML_SCHEMATRON_ENABLED`, so lxml's own
  `config.ENABLE_SCHEMATRON` is 0 and `__init__` raises
  `SchematronError: lxml.etree was compiled without Schematron support.` The class is still in
  the binary, so `dir(etree)` and editor autocomplete both suggest it. Use
  [`lxml.isoschematron.Schematron`](https://lxml.de/validation.html#schematron-1) instead: it
  is shipped complete — the RelaxNG grammar and all five stylesheets are in the wheel — and it
  implements ISO Schematron in pure XSLT on top of the XSLT engine that *is* here. Upstream
  deprecates `etree.Schematron` anyway, with a `DeprecationWarning` saying it will be removed
  from libxml2 and lxml. Remember the `extract_packages` entry from [Install](#install) if you
  go this way.
- **libxml2 has no network layer at all**, and this is a hardening improvement as much as a
  limitation. HTTP support was removed from libxml2 in 2.15 outright, and `xmlNanoHTTPOpen` is
  not in the shipped library. So parsing from a URL, fetching an external DTD, XInclude over
  `http`, and XSLT `document()` against a remote URL all fail. lxml's parsers already default
  to `no_network=True` regardless. Fetch the bytes yourself and pass them to
  `etree.fromstring`, or a file object to `etree.parse`; for entity and DTD resolution, supply
  an [`etree.Resolver`](https://lxml.de/resolvers.html) subclass that serves bytes you already
  have.
- **gzip input is never decompressed, and `decompress=True` does not change that.** libxml2 is
  built without zlib on both platforms, so the `XML_PARSE_UNZIP` flag that
  `decompress=True` sets has nothing behind it. Feeding gzip bytes to the parser gives
  `XMLSyntaxError: Start tag expected, '<' not found, line 1, column 1`, which reads like
  corrupt XML rather than like a missing codec. Every parser in the shipped source defaults to
  `decompress=False`, so this only bites code that opts in. Decompress with the `gzip` module;
  writing compressed output still works, as [Storage](#storage) describes.
- **libxml2's own resource limits apply, and one of them is reachable with ordinary data.** A
  single text node over `XML_MAX_TEXT_LENGTH` — 10,000,000 bytes in the `parserInternals.h`
  both platforms ship, byte-identical — stops the parse with
  `XMLSyntaxError: Resource limit exceeded: Text node too long, try XML_PARSE_HUGE`, which
  reads like malformed input rather than a cap. A base64 payload or an embedded document is the
  usual way to trip it. `etree.XMLParser(huge_tree=True)` raises the ceiling to
  `XML_MAX_HUGE_LENGTH`, a thousand times higher, but it lifts the depth and entity-expansion
  guards with it, so keep it for documents you produced yourself. Entity expansion is otherwise
  safe by default: every parser here defaults to `resolve_entities='internal'`, so a document
  declaring an external entity gets `XMLSyntaxError: Entity 'x' not defined` rather than a
  fetch, while its own internal entities still expand.
- **EXSLT is there, minus crypto.** `libexslt` registers common, dates-and-times, dynamic,
  functions, math, sets and strings, plus the `http://icl.com/saxon` namespace — the same list
  on both platforms, read out of the Android shared library's string table and out of the
  statically linked iOS `etree.so`. The exception is the `http://exslt.org/crypto` namespace:
  these builds are configured without it, and neither binary contains a single crypto, md5,
  sha1 or rc4 string, so `crypto:md5`, `crypto:sha1` and `crypto:rc4_encrypt` have nothing to
  bind to. Hash in Python with `hashlib` and either precompute the value into the source tree
  or
  [register it as an extension function](https://lxml.de/extensions.html).
  [EXSLT regular expressions](https://lxml.de/xpathxslt.html#regular-expressions-in-xpath)
  (`re:test`, `re:match`, `re:replace`) work regardless of libexslt, because lxml implements
  that namespace itself on top of Python's `re`.
- **The HTML parser is not an HTML5 tree builder.** libxml2's own header says so: as of 2.14
  the tokenizer conforms to HTML5, but "tree construction still follows a custom, unspecified
  algorithm with many differences to HTML5". For forgiving extraction the built-in parser is
  fine and fast, and it is what [`lxml.html`](https://lxml.de/lxmlhtml.html) uses. When the
  shape of the tree matters — because you are matching what a browser would produce — add
  `html5lib` and use `lxml.html.html5parser.fromstring`, which builds a spec-conformant tree
  and still hands you lxml elements, XPath and cssselect.
- **What is compiled in.** Everything else you would reach for: XPath, XInclude, XML Schema,
  RelaxNG, DTD validation, C14N canonicalisation, the regexp and pattern engines, the push
  parser behind [`iterparse`](https://lxml.de/parsing.html#iterparse-and-iterwalk), incremental
  writing via [`etree.xmlfile`](https://lxml.de/api.html#incremental-xml-generation), and
  threading. Switched off on **both** platforms, not one: Schematron, ICU, zlib, HTTP and
  per-thread allocation. It is worth stating that plainly, because a reader coming from
  [`pyarrow`](../pyarrow) — where the codecs really do differ by platform — will be expecting
  an asymmetry that is not here. The iconv gate is the whole of it, though it takes libxml2's
  built-in ISO-8859-2 through ISO-8859-16 tables with it; see [Android notes](#android-notes).
- **Ask the wheel rather than trusting this page.** `etree.LIBXML_FEATURES` is a set, built by
  asking libxml2 at runtime which of its optional pieces are present, and
  `etree.LIBXML_COMPILED_FEATURES` is the same question answered from the headers lxml was
  compiled against. Alongside them, `etree.LXML_VERSION`, `etree.LIBXML_VERSION` and
  `etree.LIBXSLT_VERSION` give you the three version numbers that matter. The example app puts
  all of it in its header line, which is the fastest way to see what a particular device got.
- **Every Python file here is the desktop package's, byte for byte.** The wheel holds 97 files:
  7 native extensions (`etree`, `objectify`, `builder`, `sax`, `_elementpath`, `html/diff`,
  `html/_difflib`), 6 of `.dist-info` metadata, and 84 others — every one of which is
  hash-identical to the same-version PyPI wheel for macOS. Android and iOS ship exactly the
  same 97 file names as each other, the native suffix aside. Nothing was patched, which is why
  upstream's documentation can be trusted here without a translation step. One thing is
  genuinely absent: the desktop wheel also carries 77 files under
  `lxml/includes/{libxml,libxslt,libexslt,extlibs}/` — bundled C headers plus four
  `__init__.py` — because it bundles libxml2 and libxslt, and these wheels link against
  external copies instead. Nothing reads them at runtime; only a Cython extension that
  `cimport`s lxml's includes would notice.
- **Size.** Small by the standards of this index, and per-architecture:

  | slice | lxml, download → unpacked | the two lib wheels, download → unpacked | installed, after cleanup |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 1.6 MB → 4.9 MB | 0.9 MB → 2.6 MB | 6.3 MB |
  | iOS arm64 (device) | 2.9 MB → 8.7 MB | 3.7 MB → 10.2 MB | 8.3 MB |

  The last column is what survives Flet's default package cleanup, which is also why the iOS
  figure is smaller than the wheels suggest — see [iOS notes](#ios-notes). What cleanup does
  *not* remove is 0.58 MB of lxml's own `.pxi` Cython sources, which are not on its glob list
  and which nothing at runtime reads. Take them off with
  `[tool.flet.cleanup] package_files = ["lxml/*.pxi"]` if you are counting megabytes. Do not
  widen that glob towards `opt/lib`: on Android those are the libraries the app cannot start
  without.

## Build notes (maintainers)

Three recipes in a chain — `flet-libxml2` and `flet-libxslt` build the C libraries,
`recipes/lxml` consumes both. The patch and `meta.yaml` explain their own contents, so what is
left here is the shape and the bump checklist.

**The two libraries are `requirements.host`, not `requirements.host_build`, and that is
deliberate.** `host_build` would put them in the cross environment for the link and then not
ship them, which is fine on iOS — where they are statically absorbed and genuinely not needed
at runtime — and fatal on Android, where `etree.so` resolves all three by bare soname out of
`jniLibs`. A single recipe has to satisfy both, so they are ordinary runtime dependencies and
appear in `Requires-Dist`. On iOS that is redundant rather than harmful, and Flet's default
cleanup deletes the redundant part unprompted. Making the dependency conditional on the SDK
would save nothing an app author can measure and would give the two platforms different
metadata.

The Android-shared / iOS-static split is a property of the two `flet-lib*` recipes' own
`build.sh`, not of anything in this recipe. Most of [iOS notes](#ios-notes) and the linkage
paragraph in [Android notes](#android-notes) rest on it, so a change there lands here.

**The tests are one test.** `tests/test_lxml.py` parses a two-element document and checks the
tags — nothing exercises XSLT, EXSLT, XML Schema, RelaxNG, the encoding split, or the
Android soname resolution for the three shared libraries. So essentially none of the
consumer-facing claims above is protected by CI, and every one of them has to be re-checked by
hand on a bump. Extending that file is the highest-value change available to this recipe: an
XSLT round trip, an XSD pass/fail pair, an assertion that `etree.Schematron` raises, and an
encoding probe gated on `"iconv" in etree.LIBXML_FEATURES` would cover most of this page. Per
the repo's test convention, assert the feature set and the relationships rather than exact
version numbers, and give every test function a docstring.

What to re-verify on a bump, in rough order of how quietly it can go wrong:

- **The feature gates, from the shipped headers rather than from the configure line.** Diff
  `opt/include/libxml/xmlversion.h` between the Android and iOS `flet-libxml2` wheels: it must
  differ on exactly one line, the `LIBXML_ICONV_ENABLED` gate. Any second difference means the
  two platforms have diverged in a way this page denies, and a *change* to the off-set
  (Schematron, ICU, zlib, HTTP) silently falsifies two or three bullets in
  [Things to know](#things-to-know) without failing the build. libxslt's `xsltconfig.h` should
  stay byte-identical between the platforms, and so should libxml2's `parserInternals.h`, which
  is where the 10 MB text-node limit quoted above comes from.
- **The encoding list.** It is `defaultHandlers[]` in libxml2's `encoding.c`, where the
  ISO-8859-2-and-up entries sit behind
  `!LIBXML_ICONV_ENABLED && !LIBXML_ICU_ENABLED && LIBXML_ISO8859X_ENABLED` — so they are
  built in on Android and libiconv's job on iOS, and checking `LIBXML_ISO8859X_ENABLED` alone
  gives the wrong answer for iOS. Upstream does move entries in and out —
  `windows-1252` only became a built-in in 2.15. Re-derive it from the source of the version
  being built, not from the old list, because a name that quietly stops being built in becomes
  an Android-only runtime failure in an app that was working.
- **The linkage model on both sides.** Android: `etree.so`'s `DT_NEEDED` still names
  `libxslt.so`, `libexslt.so` and `libxml2.so`, with no `RPATH`/`RUNPATH`. iOS: `otool -hv`
  still reports `NOUNDEFS` and `otool -L` still shows no libxml2 dylib. If iOS ever links
  dynamically instead, the dead-weight paragraph and the size table both change, and the
  wheels stop being interchangeable in the way this page assumes.
- **Whether cleanup still empties the iOS lib wheels.** The `**.a` / `**.h` / `bin` globs are
  serious_python's `junkFilesMobile`, not something this recipe controls, and `cleanup.packages`
  defaulting to true is a `flet build` setting. Both are outside the recipe, so a Flet bump can
  invalidate the iOS size figure without anything here moving.
- **The EXSLT namespace list, and the absence of crypto.** Read it off the built binaries:
  `strings` on the Android `libexslt.so`, and on the iOS `etree.so` for the static side. A
  libxslt release that starts building crypto unconditionally would make one bullet wrong in
  the direction users notice least.
- **The exact error strings.** The four optional-integration messages in [Install](#install)
  are upstream's, produced by `lxml/cssselect.py`, `lxml/html/clean.py` and plain import
  failures; the Schematron and encoding messages come from `schematron.pxi`, libxml2's
  `encoding.c` and `serializer.pxi`. All of them get reworded between releases.
- **The file count and the sizes.** The 97-file wheel, the 7 native modules, the 84 files that
  hash-match a same-version desktop wheel, the per-slice size table and the 0.58 MB of `.pxi`
  are all measured. Recount and re-measure; do not scale.
