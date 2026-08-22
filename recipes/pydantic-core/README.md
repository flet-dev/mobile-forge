# pydantic-core

[`pydantic-core`](https://github.com/pydantic/pydantic-core) is the compiled engine behind
[pydantic](https://docs.pydantic.dev/latest/) v2: a Rust extension that holds the validators,
the serialisers and pydantic's own JSON parser. You will rarely import it — you add `pydantic`,
and this wheel is what makes it work on a phone.

The reason to want it there is that a mobile app is mostly a consumer of data it did not
produce: a JSON response, a cached file, a scanned payload. `validate_json` takes those bytes
straight to typed Python objects in one pass and, when they are wrong, hands back a precise
path to each offending field instead of a `KeyError` three screens later. The checking runs in
compiled code rather than in a hand-written validation layer, and the
[`feed-validator`](examples/feed-validator) example prints what a few hundred nested records
cost on the device in front of you.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pydantic",
]
```

**Depend on `pydantic`, not on `pydantic-core`.** pydantic pins its core with `==`, so the
version you get is whichever one your pydantic release names. A bare `pydantic` is the safe
spelling: it resolves to the newest release whose core pin this index carries. Writing the core
pin out yourself is the one thing on this page that can fail your build, or quietly leave you
on pydantic 1.x — see the first entry in [Things to know](#things-to-know) for the four ways it
goes wrong. `pydantic[email]` is a valid spelling here as well: the extra adds `email-validator`, `dnspython` and `idna`, all pure Python.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`feed-validator`](examples/feed-validator) — validates a generated JSON order feed and
  reports exactly which records it refused and why.

## Usage in a Flet app

```python
import decimal

import flet as ft
from pydantic import BaseModel, TypeAdapter, ValidationError


class Order(BaseModel):
    id: str
    total: decimal.Decimal


FEED = TypeAdapter(list[Order])

try:
    orders = FEED.validate_json(payload)  # raw bytes in, typed objects out
    rows = [ft.Text(f"{order.id}  {order.total}") for order in orders]
except ValidationError as error:
    rows = [
        ft.Text(f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}")
        for problem in error.errors(include_url=False)
    ]

table = ft.Column(controls=rows)
```

[`validate_json`](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.validate_json)
accepts `bytes` as readily as `str`, so a response body or a file read in binary goes in with no
decode step, and pydantic's parser feeds the validators directly — no intermediate dicts. A
[`TypeAdapter`](https://docs.pydantic.dev/latest/api/type_adapter/) is what lets the top level
be a `list`; a single record can use `Order.model_validate_json(payload)` instead.

The error side is what makes the screen readable.
[`errors(include_url=False)`](https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.ValidationError.errors)
drops the link to errors.pydantic.dev that every entry otherwise carries, and each entry's
`loc` is a tuple path — `(214, 'lines', 0, 'qty')` for the 215th record of a list — which is
what turns a rejection into a table row rather than a paragraph.

### Storage

Validated models are ordinary Python objects; what needs a decision is the bytes on either side
of them. Anything the user expects to keep belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
the app-private directory that is never auto-deleted:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "orders.json")
with open(path, "wb") as handle:
    handle.write(FEED.dump_json(orders))
with open(path, "rb") as handle:
    orders = FEED.validate_json(handle.read())
```

Note the modes.
[`TypeAdapter.dump_json`](https://docs.pydantic.dev/latest/api/type_adapter/#pydantic.type_adapter.TypeAdapter.dump_json)
returns **bytes**, so a text-mode `open(path, "w")` raises `TypeError: write() argument must be
str, not bytes` — while
[`BaseModel.model_dump_json`](https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_dump_json)
on a single record returns `str`. The two spellings differ, and mixing them up is the mistake
that reaches a device as a crash in a save handler.

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for a payload you could fetch again and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files. There is no atomic-write machinery in pydantic — one `write()` of one
`bytes` object is the whole operation — so if a truncated file on a killed app would hurt,
write beside the target and `os.replace` it yourself.

### Threading

**Validation holds the GIL for the whole call.** No validator in pydantic-core detaches from
the interpreter, so two threads validating at once take turns, and pushing a large
`validate_json` into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does not
keep the UI moving through it. What `run_thread` does buy you is that the event handler returns
immediately; if the pause still matters, split the payload and validate it in chunks so the
thread yields between them. The extension does import the GIL-release entry points, but that is
not evidence that a validator releases the GIL — they belong to pyo3's own internal lock waits,
which are not on any validation path.

Nothing in the wheel starts a thread of its own either, so validation scales with clock speed,
never with core count, and there is no pool to size.

pydantic hands you no connection or cursor to serialise, and because the GIL is held for the
whole of a validation call there is nothing for two threads to interleave inside one. The
Flet-side rules still apply: a `run_thread` worker must end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) because auto-update
does not reach background threads, and it should be wrapped in `try/except`, because
`run_thread` discards whatever it raises — a validation bug in a worker looks like a screen
that stopped updating, not like an error.

### Recovering a batch

One bad record fails the whole list, which on a phone usually means an empty screen instead of
a partly useful one. The error carries a path per problem, so the leading index of each `loc`
names the record to drop and a second pass returns the rest:

```python
try:
    orders, problems = FEED.validate_json(payload), []
except ValidationError as error:
    problems = error.errors(include_url=False)
    rejected = {problem["loc"][0] for problem in problems if problem["loc"]}
    records = json.loads(payload)
    orders = FEED.validate_python(
        [record for index, record in enumerate(records) if index not in rejected]
    )
```

The salvage pass has to start from parsed records rather than from the original bytes, so
recovering costs one stdlib parse over rejecting the batch outright. Keep `problems` and show
it: the records you dropped are the only explanation the user will get.

### App size

Roughly 1.8–2.0 MB compressed per slice and 4.7–5.4 MB unpacked, of which 4.3–5.1 MB is the
single extension module. There is nothing to trim — the Rust *is* the package — and
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) finds only the
46 KB type stub and the `py.typed` marker beside it, neither of which is read at runtime. On
Android the levers are an app bundle, split APKs, or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI; this wheel builds for all of them, so reach for those because of
what else is in the app rather than because of this.

### Other considerations

A desktop `flet run` resolves pydantic-core from PyPI, where every version exists. The mobile
index carries a subset, so a pydantic pin that runs perfectly on a laptop can fail at
`flet build` with `Could not find a version that satisfies the requirement pydantic-core==<x>
(from pydantic)` — a green `flet run` is not evidence that the app resolves for a device. Build
once for a device early, before the pin is buried under other work.

Two more differences are invisible under `flet run` because they are produced by packaging
rather than by pydantic: your `.py` sources are compiled away on device, which empties
attribute-docstring field descriptions, and the extension module is relocated out of
site-packages, which changes or removes its `__file__`. Both are below, and both are worth a
device run rather than an assumption.

## Things to know

- **You get pydantic's version of pydantic-core, not this recipe's, and pinning both breaks
  something.** pydantic pins its core with `==`, and the two versions move on separate schedules:
  today the newest stable pydantic pins the *previous* core version, while the version this
  recipe builds is pinned only by a pydantic pre-release. Both are on the index, so a bare
  `pydantic` resolves fine. What does not work is spelling out the pin yourself. Four ways it
  goes wrong, with the output of four real resolves against this index — the version numbers in
  them are whatever your project and the index happen to hold:

  | what you write | when it bites | what you see |
  | --- | --- | --- |
  | `pydantic==<x>` and `pydantic-core==<y>` that disagree | `flet build`, at pip resolution | `Cannot install pydantic-core==2.47.0 and pydantic==2.13.4 because these package versions have conflicting dependencies` … `ResolutionImpossible` |
  | bare `pydantic` and `pydantic-core==<recipe version>` | never — it resolves, and quietly gives you pydantic **1.x** | `Would install pydantic-1.10.26 pydantic_core-2.47.0`; on device `from pydantic import TypeAdapter` raises `ImportError`, because v1 has none of the v2 API |
  | `pydantic==<a release whose core pin is not on this index>` | `flet build`, at pip resolution | `Could not find a version that satisfies the requirement pydantic-core==2.41.5 (from pydantic) (from versions: 0.0.1, 2.46.4, 2.47.0)` |
  | a mismatched pair that somehow got installed | on device, at `import pydantic` | `SystemError: The installed pydantic-core version (2.47.0) is incompatible with the current pydantic version, which requires 2.46.4.` |

  The second row is the nasty one: nothing fails, because pip is free to satisfy your core pin
  by walking pydantic back to 1.10.26, which does not depend on pydantic-core at all. The
  `(from versions: …)` line in the third is what pip could see for that platform and ABI across
  both indexes — `0.0.1` is a placeholder wheel on PyPI, everything after it is pypi.flet.dev's
  inventory — so the error does tell you which mobile pins exist. The fourth is not a packaging
  problem to work around — pydantic checks the pair at import and refuses — it means the
  resolved pair is wrong. If you must pin pydantic, read the core version off its metadata
  first and check
  [pypi.flet.dev/pydantic-core](https://pypi.flet.dev/pydantic-core/) for a wheel at that
  version and Python tag.
- **Field descriptions taken from attribute docstrings come back empty on device.**
  [`ConfigDict(use_attribute_docstrings=True)`](https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.use_attribute_docstrings)
  works by reading the source of the file the model class is defined in — normally one of yours
  — and Flet's default
  [`compile.app`](https://flet.dev/docs/publish/#compilation-and-cleanup) compiles the app to
  `.pyc` and deletes the `.py` files. With no source to read pydantic returns no descriptions at
  all: no exception, no warning, `model_fields[...].description` is simply `None`. Write them
  out with
  [`Field(description=...)`](https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.Field),
  or set `app = false` under `[tool.flet.compile]` and pay the size and startup cost. Note it is
  the `app` half and not `packages`: with pydantic's own sources stripped but the model's file
  kept, the descriptions still resolve, so turning off the site-packages half fixes nothing.
  Source is the only thing this needs — everything else in pydantic validates identically with
  the `.py` files gone.
- **`validate_json` gives up on deeply nested JSON far sooner than `json.loads` does, and does
  not say so.** pydantic's parser carries its own recursion limit — 201 levels of nested arrays
  on a desktop Mac, orders of magnitude below the stdlib parser, whose ceiling is the thread's
  C stack rather than a constant and therefore moves with the interpreter build: on one Mac
  `json.loads` refused at about 10 000 levels under one Python 3.12 build and about 12 000
  under another, and at about 116 000 under 3.14, none of those figures moved by
  `sys.setrecursionlimit`. Since Flet 0.86 defaults to 3.14, the gap on the runtime most apps
  get is nearer three orders of magnitude than two. One level past pydantic's limit the failure
  is reported as
  [`json_invalid`](https://docs.pydantic.dev/latest/errors/validation_errors/#json_invalid)
  with `Invalid JSON: recursion limit exceeded at line 1 column 202`, i.e. as bad input rather
  than as a limit. The pydantic figure is a constant compiled into the parser, so it does not
  move with the interpreter; the [`feed-validator`](examples/feed-validator) example measures it
  on the device rather than trusting the desktop figure. For input that really is that deep,
  parse with `json.loads` and hand the result to `validate_python`.
- **Recursive models stop at 255 levels, and the error blames a cycle that is not there.**
  `pydantic_core._pydantic_core._recursion_limit` is 255, a hard cap that
  `sys.setrecursionlimit` does not move, and a self-referencing model nested past it raises
  [`recursion_loop`](https://docs.pydantic.dev/latest/errors/validation_errors/#recursion_loop)
  — `Recursion error - cyclic reference detected` — on input with no cycle in it at all.
- **Strip the documentation URL out of errors before you show them.** Every entry from
  `ValidationError.errors()` carries a `url` into errors.pydantic.dev, and `str(e)` ends each
  error with *For further information visit …*. On a phone that is a line of noise pointing at a
  page the user probably cannot reach, which is why the snippets above pass `include_url=False`
  and build the display from `type`, `loc`, `msg` and `input`.
- **`Decimal` fields are backed by the C accelerator on both platforms.** pydantic routes every
  `Decimal` through the stdlib `decimal` module, so a pure-Python `_pydecimal` fallback would be
  a large and completely silent slowdown. Both of Flet's mobile Python runtimes ship the native
  `_decimal` — for all three Python minors, on Android and iOS alike. It is the Python runtime's
  property rather than this wheel's, so the example prints
  `decimal.__libmpdec_version__` on screen instead of taking anyone's word for it. The
  accelerator is present on both but is not the same build: measured on 2026-08-17 with
  Python 3.14, Android reports libmpdec **2.5.1** and iOS **4.0.0**. Nothing in pydantic
  depends on the difference, but it is the kind of thing to check on screen rather than assume
  when a `Decimal` result differs between the two.
- **On Android this extension module has no `__file__` at all.** Flet relocates every native
  extension out of site-packages, leaving a `.soref` pointer behind: on iOS the loaded module
  still reports a path (`_pydantic_core.fwork`), while on Android
  `getattr(pydantic_core._pydantic_core, "__file__", None)` is `None` — the example's header
  prints `no __file__` there. It is not a blanket rule for the platform, though: under the same
  Flet version [`pyyaml`](../pyyaml)'s `_yaml.__file__` on Android reads `libyaml-_yaml.so`, a
  bare `jniLibs` filename. So the attribute may be missing *or* point somewhere unrelated to the
  package. Either way, code locating a resource relative to a native module's `__file__` breaks
  on Android — as an `AttributeError`, a `TypeError` on `None`, or a wrong path, never as an
  import error.
- **Zone-aware datetimes need no `tzdata` wheel.** A `datetime` string's offset is parsed inside
  the extension and comes back as pydantic-core's own
  [`TzInfo`](https://docs.pydantic.dev/latest/api/pydantic_core/#pydantic_core.TzInfo), which is
  fixed-offset and reads no time-zone database — unlike
  [`pandas`](../pandas) or [`polars`](../polars), which do want one. If you construct a
  `zoneinfo.ZoneInfo` yourself you are back in stdlib territory and its rules apply.
- **Upstream's documentation applies unchanged.** Nothing has been removed from the mobile
  wheels and nothing platform-specific has been added, so any difference you see on device comes
  from the surrounding Python runtime rather than from this wheel. The example prints the
  extension's own `build_info` so you can check that on the device instead of here.

## Build notes (maintainers)

### Recipe shape

The recipe is four settings in `meta.yaml`: name, version, build number, and the stock
`_PYTHON_SYSCONFIGDATA_NAME` line that every maturin recipe here carries so PyO3 reads the
target ABI's sysconfig rather than the build host's. There are no patches and no `build.sh`,
and that is the fact worth recording — a maturin/PyO3 package with no C dependencies
cross-compiles to all six slices on forge's stock Rust support alone, so the day this recipe
needs a patch, suspect the toolchain or an upstream restructuring rather than reaching for one.
It is also one of the three recipes in `SMOKE_TEST_PACKAGES` in
`.github/workflows/build-wheels.yml`, built and on-device tested on every non-recipe change,
which makes it the repo's Rust canary: a failure here on an unrelated PR is usually about
forge, not about pydantic-core.

The build covers all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and iOS
device plus both simulator slices, on Python 3.12, 3.13 and 3.14, with no `target_arch`
narrowing needed anywhere.

What the wheels look like, since the consumer sections rest on it:

- **Ten entries, identical everywhere.** Every wheel — Android, iOS, and the desktop macOS
  wheel of the same version — contains the same ten entries, differing only in the extension
  module's platform tag, and the three Python files (`__init__.py`, `core_schema.py`,
  `_pydantic_core.pyi`) are byte-identical across all three. That is the evidence behind
  "upstream's documentation applies unchanged".
- **Nothing follows it in.** `Requires-Dist` names only `typing-extensions`, and no `flet-lib*`
  wheel comes along. No `extract_packages` entry either: one extension module plus two Python
  files, and no data file read from disk, so it runs as-is out of Android's zipped
  site-packages.
- **The GIL-release symbols are present and prove nothing.** `PyEval_SaveThread` and
  `PyEval_RestoreThread` are undefined symbols in every slice, but they come from pyo3's
  `lock_py_attached` / `get_or_init_py_attached` helpers, which detach only while *blocking* on
  one of pydantic-core's own locks: the compiled-`pattern` cache in `validators/string.rs`,
  touched when a constrained-string schema is built, and the one-shot cell behind
  `Url::serialized`. Neither hands the interpreter to another thread for the length of a
  validation call.
- **No thread is ever started.** `pthread_create` is absent from the extension's undefined
  symbols on all six slices — Android's thread symbols are thread-local-storage keys, plus
  rwlocks on the two 64-bit ABIs, and iOS's are mutexes and `pthread_threadid_np`.
- **The same Rust everywhere.** The Android arm64 and iOS arm64 builds resolve exactly the same
  87 crates at the same versions, and the only platform conditionals in the whole Rust source
  tree are the four in `recursion_guard.rs`, which on every mobile target take the branch a
  macOS or Linux build takes: the 255 limit and the overflow-checked depth guard that goes with
  it. The mobile builds carry upstream's release profile — fat LTO, a single codegen unit,
  stripped — and no PGO, which is not a mobile regression: a PyPI wheel reports
  `profile=release pgo=false` too.
- **About 105 KB of each wheel is a CycloneDX SBOM** under `dist-info/sboms/`, which nothing
  reads and which Flet's cleanup does not remove. It is useful here as the crate manifest the
  parity check above is read out of.

### Upgrade hazards

- **Settle the pydantic pairing before anything else.** Everything in [Install](#install) and
  the example's `pydantic==` pin rests on two questions a green build does not answer: which
  pydantic release pins the new core version, and whether the core version the current *stable*
  pydantic pins is still published on the index. If the new version is only pinned by a
  pre-release, the example must keep pinning the older pydantic and let the older core arrive
  transitively — the recipe version and the version a pydantic app actually gets are not the
  same thing. If the index ever stops carrying what stable pydantic pins, a bare `pydantic`
  stops resolving for mobile and the [Install](#install) snippet becomes wrong.
- **A green example run may not exercise the new wheel at all.** `pydantic==2.13.4` resolves
  `pydantic-core==2.46.4` on every one of the six slices and all three Python minors, never the
  version this recipe currently builds, so the example verifies the *previous* wheel. Only a
  `tests/` run exercises what a bump just produced. Whenever stable pydantic catches up, bump
  the example's pin and note which core version came with it.
- **The two limits are compiled-in constants.** 201 levels for `validate_json` and 255 for
  `_recursion_limit` live in the vendored JSON parser and in `recursion_guard.rs`; the first
  moves when the parser is bumped, the second when upstream changes the guard, and neither
  failure looks like a build failure.
- **The threading promise can change without breaking anything.** A release that reached pyo3's
  detach helpers from inside a validator, or spawned a worker of its own, would rewrite
  [Threading](#threading) while the build stayed green.
- **The `_decimal` claim is about Flet, not about this wheel.** It was read out of the
  python-build release that flet-cli pins (`PYTHON_BUILD_RELEASE_DATE`), so re-check it when
  Flet moves that pin, not when pydantic-core moves.

### Re-verification checklist

- **The ten-entry inventory and the byte-identical Python files**, compared against the desktop
  wheel of the *same* version. A new data file, or a `__init__.py` that diverges, would put both
  the no-`extract_packages` claim and "upstream's docs apply unchanged" back in question.
- **The linkage lists.** Android `DT_NEEDED` is `libpython3.<minor>.so`, `libdl.so`, `libc.so`
  and nothing else; iOS loads `@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib` and
  `/usr/lib/libSystem.B.dylib`, as an `MH_DYLIB` with a two-level namespace and no `LC_RPATH` of
  its own. Anything new in either list is a runtime dependency [Install](#install) does not
  mention. Also confirm the Android ELFs still carry 16 KB `PT_LOAD` alignment, which Android 15
  needs and which forge supplies through a link argument rather than through this recipe.
- **The threading evidence.** Grepping the sdist's `src/` for `allow_threads` and `detach`
  proves nothing — both words are absent today, yet the extension does detach. Grep for
  `_py_attached` as well, check that the call sites are still only the `pattern` cache in
  `validators/string.rs` and `Url::serialized` in `url.rs`, and check the built extensions for
  `pthread_create`.
- **The two limits**, re-measured on the interpreter in play. The stdlib figures they are
  compared against are not constants at all — they are the thread's C stack divided by a frame,
  so they differ between two builds of the same Python minor, never mind between minors. Keep
  that comparison qualitative rather than carrying numbers forward.
- **The platform conditionals and the 87-crate parity**, read out of the sdist and the wheels'
  SBOMs. Grep the conditionals with `grep -rnE` and include `target_family`, `windows` and
  `PyPy`, since a bare `target_os|target_arch` pattern misses three of the four (and in a shell
  `grep -rn 'a|b'` matches nothing at all). armeabi-v7a resolves one extra crate
  (`portable-atomic`, the 32-bit substitute for 64-bit atomics); the SBOM is a
  resolved-dependency manifest rather than a link map, so read that as a resolution difference,
  not as proof of extra code.
- **The sizes**, all measured. Re-measure from the wheels rather than scaling, and quote decimal
  MB — `du -h` reports binary units and will look like a regression.

### Coverage gaps

`tests/test_pydantic_core.py` exercises only `validate_python` against a hand-built
`core_schema` and the `ValidationError` path. Nothing there touches `validate_json`,
`dump_json`, `Decimal` or datetime parsing, all of which this README makes claims about; the
[`feed-validator`](examples/feed-validator) example covers them, but only on a device somebody
actually ran.

The `use_attribute_docstrings` finding was reproduced on a desktop by compiling to `.pyc` and
deleting the sources — both halves separately, which is how the cause was pinned on the app's
own file rather than on site-packages — but that is what `compile.app` does, not the same as
observing it on a phone.
