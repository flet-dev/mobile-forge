# yarl

[`yarl`](https://github.com/aio-libs/yarl) is an immutable URL object. Where `urllib.parse`
hands you five strings and leaves the encoding to you, a
[`yarl.URL`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL) is percent-encoded and
IDNA-encoded the moment you build it, exposes every part in both a decoded and an encoded form
(`path` / `raw_path`, `host` / `raw_host`), and returns a new URL from every modification. It is
the URL type `aiohttp` uses, and it is worth having on its own for anything that assembles an
API request on a phone.

**Which of two very similar wheels you end up with is decided at resolve time, silently.**
yarl's quoting is a Cython extension, `yarl._quoting_c`, with a pure-Python twin,
`yarl._quoting_py`, that `yarl/_quoting.py` substitutes without a word if the extension will not
import. Upstream publishes a `py3-none-any` wheel beside its compiled ones, and that wheel is a
legal answer for an Android or an iOS target — so an unpinned `yarl` resolves the pure-Python
quoter on every mobile target this index serves. The fix is one pin, and
[Install](#install) has it.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "yarl",
]
```

**Put a `==` pin on that second entry if you want the C quoter — `yarl==1.24.2`.** Left bare it
resolves upstream's pure-Python wheel on every mobile target, and that is the one place this
page's snippet is not the whole answer. The table below is the measurement; the paragraph after
it is what the pin costs.

The entry belongs in top-level `[project] dependencies` and not in a `[tool.flet.android]` /
`[tool.flet.ios]` table: `flet build` resolves for the build host first, and PyPI has a desktop
wheel for every host you would build from. What PyPI has for a *phone* is only that
`py3-none-any` wheel — no release upstream publishes carries an Android or an iOS tag — so it is
the one candidate an unpinned resolve can find there, and it wins on version.

Checked with `pip download` (pip 26.2.1), once per platform tag and per Python, under the index
and binary settings serious_python 4.5.1 hands its own pip — `--only-binary :all:` plus
`--extra-index-url https://pypi.flet.dev/` on top of the default `https://pypi.org/simple`
(`bin/package_command.dart`):

| requirement | android arm64-v8a / armeabi-v7a / x86_64 | iOS device / arm64-sim / x86_64-sim |
| --- | --- | --- |
| bare `yarl` | **PyPI's `py3-none-any` wheel** on 3.12, 3.13 and 3.14 | same |
| `yarl==1.24.2` | this index's compiled wheel, all three ABIs × all three Pythons | this index's compiled wheel, all three slices × all three Pythons |

Both halves follow from ordinary pip rules and neither is a bug. Unpinned, pip picks the highest
version first, and PyPI's newest release beats this index's whatever tags are involved. Pinned,
the platform tag beats `any` at the same version — the build tag this index adds never has to
break a tie. Eighteen of the eighteen targets `flet build` actually asks for came back with this
index's wheel under the pin.

**What the pin costs is upstream's security hardening.** Between 1.24.2 and 1.24.5 upstream
started rejecting invisible characters in a host. `URL("http://пример\u200b.рф/")` returns
`http://xn--e1afmkfd.xn--p1ai/` on 1.24.2, silently deleting the zero-width space through UTS-46
mapping, and raises `ValueError: Host 'пример\u200b.рф' cannot contain '\u200b' (at position 6)`
on 1.24.5; a soft hyphen behaves the same way. If a URL in your app can come from a message, a
QR code or a clipboard, that is the trade to weigh against the quoter. On every other probe on
this page the two versions agreed exactly.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`url-workbench`](examples/url-workbench) — the same URL through `yarl.URL` and
  `urllib.parse` side by side, RFC 3986's reference vectors scored on the device, and the
  two quoting implementations timed against each other.

## Usage in a Flet app

```python
import flet as ft
import yarl._quoting
from yarl import URL

assert yarl._quoting._Quoter.__module__ == "yarl._quoting_c"  # not the slow fallback

url = URL("https://пример.рф/каталог/").with_query({"q": "книга 42", "tag": "a"})

label = ft.Text(url.human_repr())  # the readable form, for the screen
target = str(url)                  # the encoded form, for the request
```

That assertion is the line to keep in real code, and it is the only thing that answers the
question. The two quoters produce byte-identical output — a 5,000-URL differential fuzz over a
mixed alphabet gave the same SHA-256 from both — so nothing downstream can tell them apart. Only
the clock can, and [Which implementation you got](#which-implementation-you-got) has the size of
the gap. `yarl.__version__` answers the same question a second way: `1.24.2` is this index's
compiled wheel, and anything newer is PyPI's pure-Python one.

### Threading

**The extension never releases the GIL.** `PyEval_SaveThread` and `PyEval_RestoreThread` are
absent from the symbol tables of every published slice — there is no `Py_BEGIN_ALLOW_THREADS`
anywhere in the binding. Confirmed by measurement on desktop: 40,000 URL constructions took
76.9 ms on one thread and 77.4 ms split across four (**0.99×**), while the control in the same
harness — four `time.sleep(0.4)` calls — went from 1,615 ms to 404 ms (3.99×). The harness sees
parallelism when there is any, and there is none here.

That does not make yarl a bad candidate for
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) — it makes
the thread useful for the *rest* of the job. Parsing is cheap enough that it is rarely what
blocks you, at roughly 2 µs per URL on desktop; what belongs off the UI thread is the HTTP round
trip or the file read around it, and the URL work rides along. The one shape worth moving
deliberately is a bulk pass — sorting or de-duplicating tens of thousands of URLs — which at
desktop speed is 2 ms per thousand and proportionally worse on a phone.

**Sharing URL objects across threads is safe, and so are the caches.** `URL` is immutable: every
modifier returns a new object. The module-level state is a set of `functools.lru_cache`
wrappers, which CPython guards internally —
[`cache_info()`](https://yarl.aio-libs.org/en/latest/api/#yarl.cache_info) reports five keys over
three caches, and `_url.py` decorates several more it does not expose. Measured on desktop:
eight threads each building 5,000 URLs from the same seeded sequence and hashing every result
produced **one digest across all eight threads, on 3 of 3 runs**, with the shared host cache
holding its expected 17 entries. Reach for
[`cache_clear()`](https://yarl.aio-libs.org/en/latest/api/#yarl.cache_clear) only if you are
deliberately measuring, and note that `cache_configure()` reaches inside module globals, so call
it once at startup rather than from a worker.

The Flet-side rules apply as everywhere else, and the [example](examples/url-workbench) shows
both. A `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because auto-update
does not reach background threads; and its body must be wrapped in `try`/`except`, because
`run_thread` never retrieves the worker's future and discards whatever it raised — with no log,
no dialog and no crash.

### Which implementation you got

The gap is worth closing. On an Apple M4 desktop under CPython 3.14.6, encoding 2,000 Cyrillic
path segments through yarl's own path quoter, best of five passes: `yarl._quoting_c` **0.22 µs**
per segment against `yarl._quoting_py`'s **5.03 µs**, a 23× difference, with **2,000 of 2,000
segments encoding to identical bytes**. Whole-URL construction narrows it, because parsing does
more than quoting: [`URL(str)`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL) over 2,000
distinct URLs cost 1.83 µs each with the extension and 8.27 µs without — still 4.5×.

**Measured on device on 2026-08-20**, on an arm64-v8a Android 14 emulator and an iPhone 16
simulator, both CPython 3.14.6. The answer the page derives from metadata holds at runtime, and
it is mixed on both platforms alike: the example's header reads `quoting yarl._quoting_c,
multidict multidict._multidict_py, propcache propcache._helpers_py` — yarl's own quoting is the
compiled Cython path, while both of the packages it brings with it run their pure-Python
fallbacks. See [Other considerations](#other-considerations) for what that second half costs.
Every comparison against `urllib.parse` came out identical on the two devices, including the one
that matters most on a phone screen: yarl normalises `Example.COM:443` to `example.com` and
percent-encodes the space and the `ü`, where `urlsplit` hands the string back untouched, and
`human_repr()` has no stdlib equivalent at all. No timings are quoted from that run, because an
emulator's CPU is not a phone's — run the [example](examples/url-workbench) on the hardware you
care about.

### App size

Approximately 87–95 KB compressed and 270–350 KB unpacked per architecture. What reaches the
device is smaller than the unpacked wheel, because serious_python compiles the `.py` files and
deletes `_quoting_c.pyx` and `py.typed` on the way: about 210 KB of yarl over nine files,
roughly 96 KB of it the extension and another 10 KB the pure-Python quoter you will not run.
With `multidict` and `propcache` beside it the three come to about 310 KB. Each package's
`dist-info` survives pip's `--target` install, so yarl's 94 KB `METADATA` is very likely on the
device too — that last part is read from serious_python's `bin/package_command.dart` rather than
from a built payload, so measure before budgeting on it, and measure with a decimal-unit tool
rather than `du -h`.

An app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are levers
worth pulling for other packages rather than for this one; every ABI `flet build` asks for is
published here, and a third of a megabyte is not where an APK goes. There is no data directory
or test suite to reach for with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) either.

### Other considerations

**Your laptop and the device do not run the same code, and the difference is not the one you
would guess.** A desktop `flet run` resolves PyPI's compiled `yarl` together with compiled
`multidict` and `propcache`. A mobile build with the pin gets this index's compiled yarl and the
*interpreted* `multidict._multidict_py` and `propcache._helpers_py`, because neither of those
publishes an Android or an iOS wheel and both publish a `py3-none-any` one. So yarl's own
accelerator is present and does the quoting, while the query multidict is Python.

Measured on desktop with `MULTIDICT_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1`, which reproduces
the mobile combination, against the all-C desktop default, over 2,000 distinct URLs:

| µs per URL | all C (desktop) | yarl C + interpreted multidict (mobile) | all pure Python |
| --- | ---: | ---: | ---: |
| `URL(str)` | 1.83 | 1.78 | 8.27 |
| `URL(str)` then `.query.getall(…)` | 2.60 | 6.67 | 14.68 |

Parsing is unaffected, because yarl builds the query multidict lazily; reading `.query` costs
about 2.6× more than it does on your laptop. All six figures move by up to 10% run to run and
the ratios do not. If a screen parses a handful of URLs that is nothing. If it parses thousands,
read `raw_query_string` or take one `.query` and hold it, rather than looking up repeatedly —
and do not carry an assumption from a desktop profile that the multidict is C.

## Things to know

- **Two URLs that print identically can compare unequal.** `URL("HTTP://Example.COM:80/a%20b")`
  and `URL("http://example.com/a b")` both `str()` to `http://example.com/a%20b`, and both
  `repr()` the same way, yet `==` is `False` and their hashes differ — so one will not find the
  other in a `dict` or a `set`. Equality compares the internal split value, where the first
  still carries `example.com:80`; the redundant default port is hidden by `str()` and by
  `repr()`, and surfaces only in
  [`explicit_port`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.explicit_port) (`80`
  against `None`) and in
  [`human_repr()`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.human_repr), which prints
  `http://example.com:80/a b` against `http://example.com/a b`. That property has no stdlib
  equivalent either: drop the `:443` from an `https` URL and
  [`urlsplit`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urlsplit)`(...).port`
  answers `None`, never having heard of a scheme default, while `port` still answers `443`. If
  you are de-duplicating URLs, normalise through `str()` first, or compare `str(a) == str(b)`.

- **`human_repr()` is for display and does not round-trip.** It is the readable inverse of the
  encoded form — a URL built from `https://пример.рф/путь/файл.html?q=привет мир&t=a b`
  humanises back to exactly that, and `URL(u.human_repr()) == u` holds for it. It stops holding
  the moment an escape was meaningful: `https://example.com/a%20b/%2Fc?x=1%262` humanises to
  `https://example.com/a b//c?x=1%262`, where the `%2F` has become a bare slash, and re-parsing
  gives a different URL. Show it; do not store it.

- **`dict(url.query)` silently keeps the first value of a repeated key.** `?tag=x&tag=y&empty=`
  gives `{'tag': 'x', 'empty': ''}` through `dict()`, and
  `[('tag', 'x'), ('tag', 'y'), ('empty', '')]` through `list(url.query.items())`. Use
  [`getall(key)`](https://multidict.aio-libs.org/en/stable/multidict/#multidict.MultiDict.getall)
  when a key may repeat. The stdlib's failure here is the mirror image:
  [`parse_qs`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.parse_qs) keeps
  both `tag` values but **drops `empty` entirely** unless you pass `keep_blank_values=True`.

- **`urlencode` needs `doseq=True` for a repeated key and says nothing when it does not get one.**
  Given `{"t": ["a", "b"]}`,
  [`urlencode`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urlencode)
  produces `t=%5B%27a%27%2C+%27b%27%5D` — the percent-encoded `repr` of the Python list, which a
  server reads as one nonsense value.
  [`with_query`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.with_query) produces
  `t=a&t=b`.

- **A URL inside a query parameter must be encoded, not concatenated.** Writing
  `"…/fetch?url=" + "https://cdn.example.com/img.png?w=100&h=50"` looks right and corrupts the
  result silently: `parse_qs` on it returns
  `{'url': ['https://cdn.example.com/img.png?w=100'], 'h': ['50']}` — the inner URL truncated at
  its own `&`, and `h=50` promoted into the outer query. `with_query({"url": inner})` escapes the
  `&` and the `=` and the value reads back byte-exact. This is the shape a thumbnail proxy, an
  OAuth `redirect_uri` and a deep link all take.

- **`with_query` refuses types that `urlencode` would stringify.** `with_query({"v": True})`
  raises `TypeError: Invalid variable type: value should be str, int or float, got True of type
  <class 'bool'>`, and `None` raises the same way, where `urlencode` cheerfully produces `v=True`
  and `v=None` — two strings no server means to receive. `int` and `float` are accepted. Convert
  booleans yourself, deliberately.

- **A query-only reference against a base with a fragment is where yarl is wrong and `urljoin`
  is right.** RFC 3986 [§5.3](https://www.rfc-editor.org/rfc/rfc3986#section-5.3) takes the
  result's fragment from the *reference*, so
  [`urljoin`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urljoin) of
  `"http://a/b/c/d;p?q#frag"` and `"?y"` is `http://a/b/c/d;p?y`. yarl's
  [`join`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.join) returns
  `http://a/b/c/d;p?y#frag`, because a `URL` cannot distinguish "no fragment" from "empty
  fragment" — `URL("?y").fragment` is `''`. Reproduced identically on 1.24.2 and 1.24.5.
  Everywhere the RFC's own [§5.4](https://www.rfc-editor.org/rfc/rfc3986#section-5.4) table goes
  the two agree: 41 of 42 each, both returning the permitted non-strict `http://a/b/c/g` for
  `http:g`. Do not replace `urljoin` expecting a correctness win — replace it for the encoding.

- **`with_path` drops the query and the fragment unless you ask it not to.**
  `URL("https://x/a?q=1#f").`[`with_path`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.with_path)`("/new")`
  is `https://x/new`; the signature carries `keep_query=False, keep_fragment=False`.
  [`joinpath`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.joinpath) and `/` keep both —
  and split their argument on `/`, so `joinpath("a/b")` makes two segments. To put a literal
  slash inside one segment you must pass it pre-encoded: `joinpath("a%2Fb", encoded=True)`.

- **Invalid percent escapes are escaped, not passed through.** `URL("https://x/a%2/b")` gives
  `https://x/a%252/b` and `.path` `/a%2/b`; `%zz` and a lone `%` behave the same way. That is a
  deliberate requoting rule — valid escapes survive untouched, `%2f` is normalised to uppercase
  `%2F` — and it means yarl never emits a string that decodes differently from the one you gave
  it. The stdlib idiom for re-normalising a URL — `quote(unquote(path))`, using
  [`quote`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.quote) over
  [`unquote`](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.unquote) — is not
  a round trip, and this is where that bites: on `/box/a%2Fb` it yields `/box/a/b`, turning one
  path segment named `a/b` into two. yarl re-quotes without decoding first, keeps the `%2F`, and
  [`parts`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.parts) reports `a/b` as one
  segment.

- **yarl rejects two authority shapes `urlsplit` resolves.** A backslash in the authority raises
  `ValueError: Invalid URL: backslash ('\') is not allowed in the authority component per RFC
  3986.`, where `urlsplit("http://example.com\\@evil.com/").hostname` answers `evil.com` — the
  RFC-correct reading, and the opposite of what a browser does with the same string, which is
  the shape open-redirect and SSRF bypasses take. Bracket ambiguity (`http://127.0.0.1[::1]/`)
  raises `Invalid IPv6 URL` in both. They agree on removing tab, CR and LF from a URL, per
  WHATWG.

- **`raw_host` is the string to show a user, not `host`.** For `http://аpple.com/login`, whose
  first letter is Cyrillic U+0430, `urlsplit(...).hostname` and yarl's
  [`host`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.host) both give back `аpple.com`,
  which renders exactly like the real thing;
  [`raw_host`](https://yarl.aio-libs.org/en/latest/api/#yarl.URL.raw_host) gives
  `xn--pple-43d.com`, which does not. Whatever a phone screen shows about where a link goes,
  show the punycode.

- **yarl grows a pydantic integration if pydantic is present.** `_url.py` runs
  `HAS_PYDANTIC = find_spec("pydantic_core") is not None` at import and defines
  `__get_pydantic_core_schema__` when it succeeds, so `URL` becomes a usable
  [`pydantic`](../pydantic-core) field type with no import of pydantic in the common case.
  Nothing to configure; worth knowing because the behaviour of your model changes with an
  unrelated dependency.

- **Import costs about 9 ms on desktop, and most of it is not yarl.** `python -X importtime -c
  "import yarl"` reports 8.8–13.2 ms cumulative, of which multidict is 2.5 ms, `urllib.parse`
  1.2 ms, `idna` 1.0 ms, propcache 0.6 ms and the extension itself 0.6 ms. `urllib.parse` is
  already loaded in a Flet app, so that much is free; the rest is not, checked by looking at
  `sys.modules` after `import flet.app`. Import at module scope, not inside the first handler
  that needs a URL.

- **Python 3.14 does not make this redundant.** `urllib.parse` has gained nothing that encodes
  on construction, resolves IDN, or keeps repeated query keys, and the standard library has no
  multidict at all.

## Build notes (maintainers)

### Recipe shape

The recipe is a name, a version, a build number and one build requirement, `cython`, and that
last line is load-bearing rather than defensive. Upstream ships an **in-tree PEP 517 backend**
(`packaging/pep517_backend/hooks.py`, wired up by `backend-path = ["packaging"]`) whose
`build-system.requires` lists only `expandvars`, `setuptools` and `tomli`; Cython is declared
dynamically from `get_requires_for_build_wheel`, which returns `['Cython >= 3.1.2']` only when
the build is not in pure-Python mode. forge runs `python -m build --no-isolation`, which does
not install dynamic requirements, so without the explicit `requirements.build` entry there is
nothing to cythonize `yarl/_quoting_c.pyx` — and the sdist ships no pre-generated `.c`.

Nothing in the package branches on the platform, so there is no place for the iOS-specific
failure that quietly empties pure-Python networking helpers to bite. Grepping the shipped
modules for `sys.platform`, `platform.system`, `os.name` and `sys.implementation` finds exactly
one hit — `_quoting.py`'s CPython check, which selects the pure-Python quoter on a non-CPython
interpreter and is inert here.

### Upgrade hazards

- **`YARL_NO_EXTENSIONS` is both the runtime switch and the build switch.**
  `packaging/pep517_backend/_backend.py` reads it as `PURE_PYTHON_ENV_VAR`, and
  `yarl/_quoting.py` reads it at import. If it ever leaks into a forge build environment, the
  backend prints `* Pure Python build *` to stderr and emits a wheel with no extension at all —
  which installs, imports, produces byte-identical output and passes every test in `tests/`. It
  would simply be several times slower on device. [`msgpack`](../msgpack) has a build-time
  switch of exactly this shape in `MSGPACK_PUREPYTHON`; the difference is that yarl's is spelled
  the same as its runtime one, so an environment set for a benchmark is enough to poison a
  build.
- **PyPI's newest release outranking this index's is what makes the pin advice necessary.** If
  the recipe's version ever equals or passes PyPI's newest, a bare `yarl` starts winning from
  this index and [Install](#install) should be softened rather than repeated. Upstream also
  publishes a `py3-none-any` wheel on every release; the day it stops, the whole resolution
  problem disappears.
- **The IDN hardening moved between 1.24.2 and 1.24.5.** 1.24.2 silently maps a zero-width space
  or a soft hyphen out of a host; 1.24.5 raises. [Install](#install) states both behaviours by
  version, and a bump changes which one a consumer gets.
- **`multidict` and `propcache` publishing mobile wheels** would falsify
  [Other considerations](#other-considerations), which tells people their query multidict is
  interpreted and quotes a 2.6× cost for reading `.query`. Neither does today; the day either
  ships an Android or an iOS tag, that section is wrong and the recipe set arguably gains two
  members.
- **The 3.12 Android slices name the extension `_quoting_c.cpython-312.so`, without the platform
  triplet,** while 3.13 and 3.14 use the full `_quoting_c.cpython-31X-<triplet>.so`. Both carry
  the `.cpython-*` tag serious_python's `jniLibs` relocation keys on, so both work, but the
  untriplet-ed form means forge's foreign-arch drop (the `\.cpython-\d+-<triplet>\.so$` filter in
  `src/forge/build.py`) cannot tell the four 3.12 Android slices apart by filename. Currently
  harmless — the `e_machine` of every slice was checked and each is the right architecture — but
  it is the first thing to look at if a 3.12 Android wheel ever imports on one ABI and not
  another.

### Re-verification checklist

- **That each wheel actually contains a `_quoting_c*.so`.** `unzip -l` every one. Nothing else
  catches a pure-Python build, for the reason above, and this is the check the whole page rests
  on.
- **The resolution table in [Install](#install).** Re-run the `pip download` sweep with
  `--index-url https://pypi.org/simple --extra-index-url https://pypi.flet.dev/`, unpinned and
  pinned, per platform tag and per Python — a single-target check will not show the split. Note
  that the legacy `android_24_x86` ABI, which `flet build` never requests, has a wheel here only
  for 3.12 and falls back to the `any` wheel on the other two. That gap costs a consumer nothing;
  the same gap appearing in one of the six targets `flet build` does request would.
- **That `METADATA` still declares exactly `idna`, `multidict` and `propcache`**, and that no
  `.py` in the package has acquired a `__file__` read, an `importlib.resources` call or a data
  file. Today the only such reference across the whole Python layer is `_quoting.py`'s
  `os.environ.get("YARL_NO_EXTENSIONS")`, which is why consumer guidance names no
  [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) entry. Add one
  only if a real runtime filesystem read makes it mandatory, and give the failure symptom when
  you do.
- **The extension filename per slice.** It must keep a CPython ABI tag: an untagged `NAME.so`
  gets no `.soref`, is not relocated into `jniLibs`, and becomes a silent `ModuleNotFoundError`
  on device. The module lands as `libyarl-_quoting_c.so` because serious_python's Gradle step
  replaces dots with dashes (`mangledLib` in
  `serious_python_android-4.5.1/android/build.gradle.kts`), leaving a `yarl/_quoting_c.soref`
  marker in `sitepackages.zip`.
- **Linkage, per slice.** Android `DT_NEEDED` is exactly `libm.so`, `libpython3.<minor>.so`,
  `libdl.so` and `libc.so`, with no `SONAME`, `RPATH`, `RUNPATH` or `libc++_shared` — the
  generated source is C, so none of the usual Android C++ staging applies. Every `PT_LOAD`
  segment must keep 16 KB alignment (`0x4000`) for Android 15, and armeabi-v7a and the legacy
  `x86` slice must stay genuine `ELF32` builds rather than stubs. On iOS, `otool -hv` must
  report `DYLIB` and not `BUNDLE`, or the app fails at link time with *Unsupported mach-o
  filetype*, and `otool -L` should add only `@rpath/Python.framework/Python` and
  `/usr/lib/libSystem.B.dylib`.
- **The GIL claim behind [Threading](#threading).** Grep the new slices' undefined symbols for
  `PyEval_SaveThread` and `PyEval_RestoreThread`; both must stay absent. Everything outside
  CPython's own API was seven libc symbols on the Android arm64-v8a slice (`memcmp`, `memcpy`,
  `memset`, `strrchr`, the `__cxa_*` pair and `__register_atfork`) out of 166, with no file,
  socket, `getenv` or `dlopen` binding on any slice — quoting is arithmetic over strings.
- **Size.** Re-measure compressed and unpacked from the built wheels rather than scaling the
  figures in [App size](#app-size), which are decimal. The iOS device slice is about half again
  the size of the Android arm64-v8a one for the same code — 143 KB against 96 KB, with `__text`
  and `.text` within 300 bytes of each other — so segment padding and link metadata, not a
  regression.

### Coverage gaps

`tests/test_yarl.py` is a single `test_basic`, asserting one IDN plus percent-encoding round
trip. It is a good assertion — it passes on 1.24.2 and on 1.24.5 — but **it passes unchanged on
the pure-Python fallback**, verified by running it under `YARL_NO_EXTENSIONS=1`, so nothing on
device currently proves the extension is the code that ran. One line closes that
(`assert yarl._quoting._Quoter.__module__ == "yarl._quoting_c"`) and it is the highest-value
test this recipe could gain.

After that, in rough order: a docstring on `test_basic`, per the repo convention that every test
function carries one; a `%2F`-survives-requoting assertion, which pins the escaped-slash claim
in [Things to know](#things-to-know); and a repeated-key `query.getall` assertion, which is the
one place the interpreted multidict shipped alongside is actually exercised. Nothing on device
exercises relative-reference resolution, the equality trap, `with_query`'s type refusal or the
authority rejections — all of that is desktop inspection, re-run on screen by the
[example](examples/url-workbench).
