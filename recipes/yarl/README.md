# yarl

[`yarl`](https://github.com/aio-libs/yarl) is an immutable URL object. Where
`urllib.parse` hands you five strings and leaves the encoding to you, a
[`yarl.URL`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL) is percent-encoded and
IDNA-encoded the moment you build it, exposes every part in both a decoded and an encoded
form (`path` / `raw_path`, `host` / `raw_host`), and returns a new URL from every
modification. It is the URL type `aiohttp` uses, and it is worth having on its own for
anything that assembles an API request on a phone.

**The interesting part on mobile is which of two very similar packages you end up with.**
yarl's quoting is a Cython extension, `yarl._quoting_c`, with a pure-Python twin,
`yarl._quoting_py`, that `yarl/_quoting.py` substitutes without a word if the extension
will not import. This index's wheels all carry the extension — checked, all nineteen. But
upstream publishes a `py3-none-any` wheel beside the compiled ones — 1.24.2 has one and so
does the current release — and that wheel is a legal answer for an Android or iOS target,
so **an unpinned `yarl` resolves the pure-Python one on every mobile target this index
serves**. [Install](#install) has the resolution table and the one-line fix.

The gap is worth closing. On an Apple M4 desktop under CPython 3.14.6, encoding 2,000
Cyrillic path segments through yarl's own path quoter, best of five passes:
`yarl._quoting_c` **0.22 µs** per segment against `yarl._quoting_py`'s **5.03 µs**, a
23× difference, with **2,000 of 2,000 segments encoding to identical bytes**. Whole-URL
construction narrows it, because parsing does more than quoting: `URL(str)` over 2,000
distinct URLs cost 1.83 µs each with the extension and 8.27 µs without — still 4.5×. A
5,000-URL differential fuzz over a mixed alphabet produced the same SHA-256 from both
implementations, so nothing downstream can tell them apart. Only the clock can, and
[Things to know](#things-to-know) has the one line that reads the answer on the device.

Where `urllib.parse` is merely awkward, yarl is a convenience; where it is wrong, yarl is
a fix. All of the following are desktop measurements, and all of them are recomputed on
the device by the [`url-workbench`](examples/url-workbench) example:

- `urlsplit("https://Example.COM:443/search results/über?…").geturl()` returns that string
  unchanged — spaces and all — where yarl encodes on construction. Drop the `:443` and
  `urlsplit(...).port` becomes `None`, because it has no idea what scheme defaults are,
  while yarl still answers `443` and records the difference in `explicit_port`.
- `quote(unquote(path))`, the stdlib idiom for re-normalising a URL, is not a round trip:
  on `/box/a%2Fb` it yields `/box/a/b`, turning one path segment named `a/b` into two.
  yarl re-quotes without decoding first and keeps `%2F`, with `.parts` reporting `a/b` as
  one segment.
- `urlencode({"t": ["a", "b"]})` without `doseq=True` produces `t=%5B%27a%27%2C+%27b%27%5D`
  — the percent-encoded `repr` of the list. `with_query({"t": ["a", "b"]})` produces
  `t=a&t=b`.
- Concatenating a URL into a query string corrupts it silently: `parse_qs` on
  `?url=https://cdn.example.com/img.png?w=100&h=50` returns
  `{'url': ['https://cdn.example.com/img.png?w=100'], 'h': ['50']}`. `with_query` escapes
  the `&` and `=` and the value reads back byte-exact.
- On relative-reference resolution the two are level, which is worth knowing so you do not
  replace `urljoin` expecting a correctness win: on RFC 3986
  [§5.4](https://www.rfc-editor.org/rfc/rfc3986#section-5.4)'s 42 normative vectors both
  score 41, both missing `http:g` the same permitted way. The one genuine divergence is
  outside that table and goes *against* yarl — see [Things to know](#things-to-know).

**Not yet measured on device.** Every number on this page is a desktop measurement or an
inspection of the published wheels, and each says which. The
[`url-workbench`](examples/url-workbench) example exists to replace them with a phone's
own.

**Measured on device, 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. The accelerator question the page answers from metadata is
confirmed at runtime, and the answer is mixed on both platforms alike: the example's header
reads `quoting yarl._quoting_c, multidict multidict._multidict_py, propcache
propcache._helpers_py` — yarl's own quoting is the compiled Cython path, while **both
dependencies run their pure-Python fallbacks**. Every comparison against `urllib.parse` came out
identical on the two devices, including the one that matters most on a phone screen: yarl
normalises `Example.COM:443` to `example.com` and percent-encodes the space and the `ü`, where
`urlsplit` hands the string back untouched, and `human_repr()` has no stdlib equivalent at all.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "yarl",
]
```

**Put a `==` pin on that second entry if you want the C quoter.** Left bare it resolves
upstream's pure-Python wheel on every mobile target — the one place this page's snippet is
not the whole answer. The resolution table below is the measurement; `yarl==1.24.2` is the
fix, and the paragraph after it is what the pin costs.

The entry belongs in top-level `[project] dependencies` and not in a
`[tool.flet.android]` / `[tool.flet.ios]` table: `flet build` resolves for the build host
first, and PyPI has a desktop wheel for every host you would build from. The 1.24.2
release is 104 files — an sdist, a `py3-none-any` wheel, and 102 CPython binaries covering
3.10 through 3.14 (including free-threaded `cp314t`) on macOS, Linux (manylinux and
musllinux across six architectures each, riscv64 included) and Windows (`win_amd64`,
`win_arm64`). **None of the 104 carries an Android or an iOS tag**, which is why this
recipe exists.

**But that `py3-none-any` wheel is what a mobile build gets unless you pin.** Checked with
`pip download` (pip 26.2.1) once per platform tag and per Python, under the index and
binary settings serious_python 4.5.1 hands its own pip — `--only-binary :all:` plus
`--extra-index-url https://pypi.flet.dev/` on top of the default `https://pypi.org/simple`
(`bin/package_command.dart`):

| requirement | android arm64-v8a / armeabi-v7a / x86_64 | iOS device / arm64-sim / x86_64-sim |
| --- | --- | --- |
| bare `yarl` | **PyPI `yarl-1.24.5-py3-none-any.whl`** on 3.12, 3.13 and 3.14 | same |
| `yarl==1.24.2` | this index's compiled wheel, all three ABIs × all three Pythons | this index's compiled wheel, all three slices × all three Pythons |

Both halves of that follow from ordinary pip rules and neither is a bug. Unpinned, pip
picks the highest version first, and PyPI's newest release beats this index's 1.24.2
whatever tags are involved. Pinned, the platform tag beats `any` at the same version — the
build tag `1` this index adds never has to break a tie. Eighteen of the eighteen targets
`flet build` actually asks for came back with this index's wheel under the pin; the legacy
`android_24_x86` ABI, which `flet build` never requests, has a wheel here only for 3.12
and falls back to the `any` wheel on 3.13 and 3.14.

So pin `yarl==1.24.2` when you want the accelerator, and understand what the pin costs:
it freezes you behind upstream's security hardening. Between 1.24.2 and 1.24.5 upstream
started **rejecting invisible characters in a host**. `URL("http://пример\u200b.рф/")`
returns `http://xn--e1afmkfd.xn--p1ai/` on 1.24.2, silently deleting the zero-width space
via UTS-46 mapping, and raises
`ValueError: Host 'пример\u200b.рф' cannot contain '\u200b' (at position 6)` on 1.24.5;
a soft hyphen behaves the same way. On every other probe on this page the two versions
agreed exactly, including the 5,000-URL fuzz digest.

**Three packages come along with it, and all three arrive as pure Python.** `METADATA` in
all nineteen wheels declares exactly `idna>=2.0`, `multidict>=4.0` and `propcache>=0.2.1`,
with `Requires-Python: >=3.10`. Neither
[`multidict`](https://github.com/aio-libs/multidict) 6.7.1 (146 files on PyPI) nor
[`propcache`](https://github.com/aio-libs/propcache) 0.5.2 (121 files) publishes an Android
or iOS wheel, and both publish a `py3-none-any` one, so a mobile resolve gets
`multidict._multidict_py` and `propcache._helpers_py` — the fallbacks, not the C
extensions your laptop uses. `idna` is pure Python everywhere and **already arrives with
Flet**: resolving `flet==0.86.5` for `android_24_arm64_v8a` / cp314 against this index
fetched twelve wheels — flet and eleven dependencies — one of which is
`idna-3.19-py3-none-any.whl`, without idna being named anywhere.

That split shapes the performance you get, and it is not the one you would guess. yarl's
own accelerator is present and does the quoting; the query multidict is interpreted.
Measured on desktop with `MULTIDICT_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1`, which
reproduces the mobile combination, against the all-C desktop default, over 2,000 distinct
URLs:

| µs per URL | all C (desktop) | yarl C + pure-Python multidict (mobile) | all pure Python |
| --- | --- | --- | --- |
| `URL(str)` | 1.83 | 1.78 | 8.27 |
| `URL(str)` then `.query.getall(…)` | 2.60 | 6.67 | 14.68 |

Parsing is unaffected, because yarl builds the query multidict lazily. Reading `.query`
costs about 2.6× more than it does on your laptop. All six figures move by up to 10% run
to run; the ratios do not. If a screen parses a handful of URLs
that is nothing; if it parses thousands, prefer `raw_query_string` or a single `.query`
read over repeated lookups.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed. Every wheel is exactly seventeen entries — one extension, eight `.py`
modules, `_quoting_c.pyx`, `py.typed` and six `dist-info` files — with no data file of
any kind, and the only `os.environ`, `open`, `__file__`, `importlib.resources` or
`pkgutil` reference across the whole Python layer is `_quoting.py`'s
`os.environ.get("YARL_NO_EXTENSIONS")`. The extension carries a CPython ABI tag on every
slice, which is what serious_python's relocation of native modules into `jniLibs` keys on.

Nineteen wheels at build number 1: Python 3.12 across all four Android ABIs (arm64-v8a,
armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`), 3.13 and 3.14 across three
each, plus all three iOS slices for each of the three Pythons. No architecture is
excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. The wheels are 87,373–94,478 bytes to download and 267,638–346,587
unpacked.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`url-workbench`](examples/url-workbench) — the same URL through `yarl.URL` and
  `urllib.parse` side by side, RFC 3986's reference vectors scored on the device, and the
  two quoting implementations timed against each other.

## Threading

**The extension never releases the GIL.** `PyEval_SaveThread` and `PyEval_RestoreThread`
are absent from the symbol tables of all nineteen slices — there is no
`Py_BEGIN_ALLOW_THREADS` anywhere in the binding. Confirmed by measurement on desktop:
40,000 URL constructions took 76.9 ms on one thread and 77.4 ms split across four
(**0.99×**), while the control in the same harness — four `time.sleep(0.4)` calls — went
from 1,615 ms to 404 ms (3.99×). So the harness sees parallelism when there is any, and
there is none here.

That does not make yarl a bad candidate for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — it
makes the thread useful for the *rest* of the job. Parsing is cheap enough that it is
rarely what blocks you, at roughly 2 µs per URL on this desktop; what belongs off the UI
thread is the HTTP round trip or the file read around it, and the URL work rides along.
The one shape worth moving deliberately is a bulk pass — sorting or de-duplicating tens of
thousands of URLs — which at desktop speed is 2 ms per thousand and proportionally worse
on a phone.

**Sharing URL objects across threads is safe, and so are the caches.** `URL` is immutable:
every modifier returns a new object. The module-level state is a set of
`functools.lru_cache` wrappers, which CPython's `lru_cache` guards internally:
[`cache_info()`](https://yarl.aio-libs.org/en/latest/api/#yarl.cache_info) reports five
keys over three caches — `encode_host`, `host_validate` and `ip_address` all return the
same 512-entry wrapper, alongside `idna_encode` and `idna_decode` at 256 each — and
`_url.py` decorates several more that it does not expose. Measured on desktop:
eight threads each building 5,000 URLs from the same seeded sequence and hashing every
result produced **one digest across all eight threads, on 3 of 3 runs**, with the shared
host cache holding its expected 17 entries. Reach for
[`cache_clear()`](https://yarl.aio-libs.org/en/latest/api/#yarl.cache_clear) only if you
are deliberately measuring, and note that `cache_configure()` reaches inside module
globals, so call it once at startup rather than from a worker.

The Flet-side rules apply as everywhere else, and the
[example](examples/url-workbench) shows both. A `run_thread` worker must end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads; and its body must be wrapped in
`try`/`except`, because `run_thread` never retrieves the worker's future and discards
whatever it raised — with no log, no dialog and no crash.

## Android notes

- **The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is exactly
  `libm.so`, `libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices,
  with no `SONAME`, no `RPATH`, no `RUNPATH` and no `libc++_shared` — the generated source
  is C, so none of the usual Android C++ staging applies. Every `PT_LOAD` segment carries
  16 KB alignment (`0x4000`), which Android 15 requires. arm64-v8a and x86_64 are `ELF64`;
  armeabi-v7a and the legacy `x86` slice are genuine `ELF32`/`ARM` and `ELF32`/`i386`
  builds rather than stubs. The slices are stripped: no `.symtab`, no `.debug_*`.
- **The whole non-CPython surface is seven libc symbols.** `llvm-nm -D -u` on the cp314
  arm64-v8a slice lists 166 undefined symbols, of which 159 are `Py*`/`_Py*` and the rest
  are `memcmp`, `memcpy`, `memset`, `strrchr`, `__cxa_atexit`, `__cxa_finalize` and
  `__register_atfork`. It exports two symbols, `PyInit__quoting_c` and Cython's
  `__pyx_module_is_main_yarl___quoting_c`, and nothing else. No file, socket, `getenv` or
  `dlopen` call at any binding on any slice — quoting is arithmetic over strings.
- **The module lands in `jniLibs` as `libyarl-_quoting_c.so`.** serious_python's Gradle
  step mangles the dotted name `yarl._quoting_c` by replacing dots with dashes
  (`mangledLib` in `serious_python_android-4.5.1/android/build.gradle.kts:161`), leaving a
  `yarl/_quoting_c.soref` marker in `sitepackages.zip`. Read from serious_python's source,
  not from a built APK.
- **multidict and propcache run interpreted here**, per [Install](#install), and
  `multidict/_multidict_py.pyc` is 88,021 bytes of live code rather than dead weight. Do
  not carry over an assumption from a desktop profile that the query multidict is C.

## iOS notes

- **The extensions are `MH_DYLIB`, which is what Flet 0.86 needs.** `otool -hv` reports
  filetype `DYLIB` (not `BUNDLE`) on all nine iOS slices, so the *Unsupported mach-o
  filetype (only MH_OBJECT and MH_DYLIB can be linked)* failure at app link time does not
  arise here. Besides each extension's own install name, `otool -L` lists exactly two
  dependencies on every slice: `@rpath/Python.framework/Python` and
  `/usr/lib/libSystem.B.dylib`. The three arm64-simulator slices are ad-hoc
  linker-signed; the other six are unsigned, as expected.
- **The file is half again as big as Android's and the code is the same size.** 142,968
  bytes on the cp314 device slice against 96,192 on Android arm64-v8a — but `__text` is
  57,172 bytes against a `.text` of 57,460, so the difference is segment padding and link
  metadata, not code: `__TEXT` rounds to 98,304 with `__DATA_CONST` and `__DATA` at 16,384
  each and 11,896 of `__LINKEDIT`. Unlike some packages here, the iOS symbol table is not
  carrying a debug map — `LC_SYMTAB` is 166 entries, 164 of them undefined imports, so
  there is nothing for `strip -x` to remove. The x86_64 simulator slice is the smallest of
  the three cp314 builds at 89,616 bytes.
- **Nothing in the package branches on the platform**, so the iOS-specific failure that
  quietly empties pure-Python networking helpers has nothing to bite on. Grepping the
  eight shipped modules for `sys.platform`, `platform.system`, `os.name` and
  `sys.implementation` finds exactly one hit — `_quoting.py`'s CPython check, which
  selects the pure-Python quoter on a non-CPython interpreter and is inert here.

## Things to know

- **Read the implementation off the module name, on the device.** This is the one check
  worth wiring into a startup log, because a silent fallback costs 4.5× on parsing and
  reports nothing:

  ```python
  import yarl._quoting
  assert yarl._quoting._Quoter.__module__ == "yarl._quoting_c"
  ```

  `yarl.__version__` answers the same question a second way: `1.24.2` is this index's
  compiled wheel and anything newer is PyPI's pure-Python one. The
  [example](examples/url-workbench) prints both, alongside
  `multidict.MultiDict.__module__` and `propcache.api.under_cached_property.__module__`.
- **Two URLs that print identically can compare unequal.**
  `URL("HTTP://Example.COM:80/a%20b")` and `URL("http://example.com/a b")` both `str()` to
  `http://example.com/a%20b`, and both `repr()` the same way, yet `==` is `False` and their
  hashes differ — so one will not find the other in a `dict` or a `set`. Equality compares
  the internal split value, where the first still carries `example.com:80`; the redundant
  default port is hidden by `str()` and by `repr()`, and surfaces only in
  `explicit_port` (`80` against `None`) and in
  [`human_repr()`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.human_repr), which
  prints `http://example.com:80/a b` against `http://example.com/a b`. If you are
  de-duplicating URLs, normalise through
  `str()` first, or compare `str(a) == str(b)`.
- **`human_repr()` is for display and does not round-trip.** It is the readable inverse of
  the encoded form — a URL built from `https://пример.рф/путь/файл.html?q=привет мир&t=a b`
  humanises back to exactly that, and `URL(u.human_repr()) == u` holds for it. It stops
  holding the moment an escape was meaningful:
  `https://example.com/a%20b/%2Fc?x=1%262` humanises to `https://example.com/a b//c?x=1%262`,
  where the `%2F` has become a bare slash, and re-parsing gives a different URL. Show it;
  do not store it.
- **`dict(url.query)` silently keeps the first value of a repeated key.**
  `?tag=x&tag=y&empty=` gives `{'tag': 'x', 'empty': ''}` through `dict()`, and
  `[('tag', 'x'), ('tag', 'y'), ('empty', '')]` through `list(url.query.items())`. Use
  `getall(key)` when a key may repeat. The stdlib's failure here is the mirror image:
  `parse_qs` keeps both `tag` values but **drops `empty` entirely** unless you pass
  `keep_blank_values=True`.
- **`with_query` refuses types that `urlencode` would stringify.**
  `with_query({"v": True})` raises `TypeError: Invalid variable type: value should be str,
  int or float, got True of type <class 'bool'>`, and `None` raises the same way, where
  `urlencode` cheerfully produces `v=True` and `v=None` — two strings no server means to
  receive. `int` and `float` are accepted. Convert booleans yourself, deliberately.
- **A query-only reference against a base with a fragment is where yarl is wrong and
  `urljoin` is right.** RFC 3986 §5.3 takes the result's fragment from the *reference*, so
  `urljoin("http://a/b/c/d;p?q#frag", "?y")` is `http://a/b/c/d;p?y`. yarl's `join` returns
  `http://a/b/c/d;p?y#frag`, because a `URL` cannot distinguish "no fragment" from "empty
  fragment" — `URL("?y").fragment` is `''`. Reproduced identically on 1.24.2 and 1.24.5.
  Everywhere the RFC's own §5.4 table goes, the two agree: 41 of 42 each, both returning
  the permitted non-strict `http://a/b/c/g` for `http:g`.
- **`with_path` drops the query and the fragment unless you ask it not to.**
  `URL("https://x/a?q=1#f").with_path("/new")` is `https://x/new`; the signature carries
  `keep_query=False, keep_fragment=False`. `joinpath` and `/` keep both — and split their
  argument on `/`, so `joinpath("a/b")` makes two segments. To put a literal slash inside
  one segment you must pass it pre-encoded: `joinpath("a%2Fb", encoded=True)`.
- **Invalid percent escapes are escaped, not passed through.** `URL("https://x/a%2/b")`
  gives `https://x/a%252/b` and `.path` `/a%2/b`; `%zz` and a lone `%` behave the same way.
  That is a deliberate requoting rule — valid escapes survive untouched, `%2f` is
  normalised to uppercase `%2F` — and it means yarl never emits a string that decodes
  differently from the one you gave it. `unquote` in the standard library returns
  `a%2/b` unchanged, which looks like success.
- **yarl rejects two authority shapes `urlsplit` resolves.** A backslash in the authority
  raises `ValueError: Invalid URL: backslash ('\') is not allowed in the authority
  component per RFC 3986.`, where `urlsplit("http://example.com\\@evil.com/").hostname`
  answers `evil.com` — the RFC-correct reading, and the opposite of what a browser does
  with the same string, which is the shape open-redirect and SSRF bypasses take. Bracket
  ambiguity (`http://127.0.0.1[::1]/`) raises `Invalid IPv6 URL` in both. They agree on
  removing tab, CR and LF from a URL, per WHATWG.
- **`raw_host` is the string to show a user, not `host`.** For
  `http://аpple.com/login`, whose first letter is Cyrillic U+0430,
  `urlsplit(...).hostname` and yarl's `host` both give back `аpple.com`, which renders
  exactly like the real thing; `raw_host` gives `xn--pple-43d.com`, which does not. Whatever
  a phone screen shows about where a link goes, show the punycode.
- **What ships to the device is about 313 KB of code, and 96 KB of it is the extension.**
  Compiling each wheel's `.py` files with CPython 3.14 and applying serious_python's junk
  list — which deletes `**.pyx` and `**.typed`, so `_quoting_c.pyx` and `py.typed` never
  arrive — leaves yarl at 207,403 bytes over nine files (the Android arm64 extension
  96,192, `_url.pyc` 80,361, and `_quoting_py.pyc` 10,467 of fallback you will not run —
  every `.pyc` figure here swings by a hundred bytes or so with the install path, because
  `co_filename` records it, so re-measuring under a longer path legitimately gives slightly
  larger numbers),
  multidict at 98,657 and propcache at 6,620. Each package's `dist-info` survives pip's
  `--target` install and nothing removes it, so yarl's 94,214-byte `METADATA` is very
  likely on the device too — that last part is read from
  `serious_python-4.5.1/bin/package_command.dart`, not verified against a built payload
  here.
- **yarl grows a pydantic integration if pydantic is present.** `_url.py` runs
  `HAS_PYDANTIC = find_spec("pydantic_core") is not None` at import and defines
  `__get_pydantic_core_schema__` when it succeeds, so `URL` becomes a usable pydantic field
  type with no import of pydantic in the common case. Nothing to configure; worth knowing
  because the behaviour of your model changes with an unrelated dependency.
- **Import costs about 9 ms on desktop, most of it not yarl.** `python -X importtime -c
  "import yarl"` reports 8.8–13.2 ms cumulative, of which multidict is 2.5 ms, urllib.parse
  1.2 ms, idna 1.0 ms, propcache 0.6 ms and the extension itself 0.6 ms. `urllib.parse` is
  already loaded in a Flet app, so that much is free — but `idna` and `multidict` are not,
  checked by looking at `sys.modules` after `import flet.app`, even though Flet's own
  dependency set installs idna.
- **Python 3.14 does not make this redundant.** `urllib.parse` has gained nothing that
  encodes on construction, resolves IDN, or keeps repeated query keys, and the standard
  library has no multidict at all.

## Build notes (maintainers)

The recipe is a name, a version, a build number and one build requirement, `cython`, and
that last line is load-bearing rather than defensive. Upstream ships an **in-tree PEP 517
backend** (`packaging/pep517_backend/hooks.py`, wired up by `backend-path = ["packaging"]`)
whose `build-system.requires` lists only `expandvars`, `setuptools` and `tomli`; Cython is
declared dynamically from `get_requires_for_build_wheel`, which returns
`['Cython >= 3.1.2']` only when the build is not in pure-Python mode. forge runs
`python -m build --no-isolation`, which does not install dynamic requirements, so without
the explicit `requirements.build` entry there is nothing to cythonize `yarl/_quoting_c.pyx`
— and the sdist ships no pre-generated `.c`.

**The trap to know about before touching this recipe: `YARL_NO_EXTENSIONS` is both the
runtime switch and the build switch.** `packaging/pep517_backend/_backend.py` reads it as
`PURE_PYTHON_ENV_VAR`, and `yarl/_quoting.py` reads it at import. If it ever leaks into a
forge build environment, the backend prints `* Pure Python build *` to stderr and emits a
wheel with no extension at all — which installs, imports, produces byte-identical output,
and passes every test in `tests/`. It would simply be several times slower on device. This
is the same failure shape msgpack has with `MSGPACK_PUREPYTHON`, and it is why the first
check below is the one that matters.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That each wheel actually contains a `_quoting_c*.so`.** `unzip -l` all nineteen. Nothing
  else catches it, for the reason above.
- **The resolution table in [Install](#install).** It is the whole point of this page and a
  bump changes it directly: if the recipe's version ever equals PyPI's newest, a bare
  `yarl` starts winning from this index and the pin advice should be softened rather than
  repeated. Re-run the `pip download` sweep with `--index-url https://pypi.org/simple
  --extra-index-url https://pypi.flet.dev/`, unpinned and pinned, per platform tag and per
  Python — a single-target check will not show the split.
- **Whether `multidict` and `propcache` have started publishing mobile wheels.** Today
  neither does, so [Install](#install) tells people their query multidict is interpreted
  and quotes a 2.6× cost for reading `.query`. The day either ships an Android or iOS tag,
  that paragraph is wrong and the recipe set arguably gains two members.
- **The IDN hardening.** 1.24.2 silently maps a zero-width space or soft hyphen out of a
  host; 1.24.5 raises. A bump changes what
  `URL("http://пример\u200b.рф/")` does, and [Install](#install) states both behaviours by
  version.
- **That `METADATA` still declares exactly `idna`, `multidict` and `propcache`**, and that
  no `.py` in the package has acquired a `__file__` read or a data file — either would
  falsify the "no `extract_packages`" claim without failing anything.
- **The extension filenames**, per slice: they must keep a CPython ABI tag, since an
  untagged `NAME.so` gets no `.soref`, is not relocated into `jniLibs`, and becomes a
  silent `ModuleNotFoundError` on device. Note that the 3.12 Android slices are named
  `_quoting_c.cpython-312.so` without the platform triplet while 3.13 and 3.14 use the
  full `_quoting_c.cpython-31X-<triplet>.so`; both match the tag serious_python keys on, but
  the untripleted form means forge's foreign-arch drop (`foreign_ext_re` at
  `src/forge/build.py:896`, which matches only triplet-bearing names) cannot tell the four
  3.12 Android slices apart by filename. Currently harmless — the `e_machine` of every slice was checked
  and each is the right architecture — but it is the first thing to look at if a 3.12
  Android wheel ever imports on one ABI and not another.
- **The linkage**, per slice: `DT_NEEDED` still four bionic and interpreter entries with no
  `libc++_shared`, 16 KB `PT_LOAD` alignment on all four Android ABIs, `MH_DYLIB` on all
  three iOS ones.
- **The GIL claim behind [Threading](#threading).** Grep the new slices' symbols for
  `PyEval_SaveThread`; the first `Py_BEGIN_ALLOW_THREADS` to land would invert that section.

`tests/test_yarl.py` is a single `test_basic` with no docstring, asserting one IDN plus
percent-encoding round trip. It is a good assertion — it passes on 1.24.2 and on 1.24.5 —
but it has the same blind spot as msgpack's suite: **it passes unchanged on the pure-Python
fallback**, verified by running it under `YARL_NO_EXTENSIONS=1`, so nothing on device
currently proves the extension is the code that ran. One line closes that
(`assert yarl._quoting._Quoter.__module__ == "yarl._quoting_c"`) and it is the highest-value
test this recipe could gain. After that, in rough order: a docstring on `test_basic`, per
the repo convention that every test function carries one; an `%2F`-survives-requoting
assertion, which pins the claim [Things to know](#things-to-know) makes about escaped
slashes; and a repeated-key `query.getall` assertion, which is the one place the
pure-Python multidict shipped alongside is actually exercised.
