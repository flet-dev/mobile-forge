# PyYAML

[`PyYAML`](https://pyyaml.org/wiki/PyYAMLDocumentation) is the YAML parser and emitter almost
every Python config file goes through: `yaml.safe_load` on the way in, `yaml.safe_dump` on the
way out. On a phone the reason to want it is the same reason a desktop app wants it — a
settings file, a bundled ruleset, a document a server handed you in YAML instead of JSON — with
one difference that matters more here than anywhere else.

**PyYAML ships two complete implementations, and the fast one is not the default.** The scanner,
parser, emitter and serialiser are written twice: once in Python, and once in C on top of
[libyaml](https://pyyaml.org/wiki/LibYAML). The Python pair is what `safe_load` and `safe_dump`
use. This recipe's entire job is to make the C pair — `CSafeLoader` and `CSafeDumper` — actually
present on a phone, which is worth roughly 8× on reading and 4–5× on writing. Nothing switches to
it for you, and nothing tells you if it is missing.

The two are not quite interchangeable, either. On everything tested here they produce identical
output and identical objects, but they disagree about which documents are *valid*, and only the
Python one can point a caret at the character it choked on. Both are covered below.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pyyaml",
]
```

One more wheel comes along and needs no configuring: `flet-libyaml`, which carries the C library.
It is named in the wheel's `Requires-Dist`, so the resolver brings it in on both platforms —
though only Android actually loads it at runtime, see [iOS notes](#ios-notes).

Then change your two call sites, because the defaults leave this whole recipe unused:

```python
import yaml
from yaml import CSafeDumper, CSafeLoader

settings = yaml.load(text, Loader=CSafeLoader)
text = yaml.dump(settings, Dumper=CSafeDumper, sort_keys=False, allow_unicode=True)
```

Importing the two classes by name at the top of the module is the point of that second line — see
the third bullet in [Things to know](#things-to-know) for what happens if you skip it.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: the wheel contains no data files, and across its 18 Python files there is not one
occurrence of `__file__`, `getsource`, `pkgutil`, `pkg_resources`, `importlib.resources` or
`resource_filename` — nothing builds a path or reads its own source. The extension carries a full
CPython ABI tag. So it runs as-is out of Android's zipped site-packages, and Flet's default
[`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup) — which compiles
site-packages to `.pyc` and deletes the `.py` files — takes nothing away from it.

Builds for all three Android ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and for iOS on
device and both simulator slices, on Python 3.12, 3.13 and 3.14. Nineteen wheels at the same build
number: those eighteen combinations plus a legacy 32-bit `android_24_x86` slice on 3.12, and every
one of them carries the C extension. No
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) narrowing
is needed.

## Storage

A YAML file is an ordinary file, so anything the app owns belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
— the app-private directory that is never auto-deleted and is included in backups. From Flet
0.86.0 it is also the process working directory on device, so a bare relative filename lands
there; spelling it out costs one line and behaves the same on desktop:

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.yaml")
with open(path, "w", encoding="utf-8") as handle:
    yaml.dump(settings, handle, Dumper=CSafeDumper, sort_keys=False, allow_unicode=True)
with open(path, encoding="utf-8") as handle:
    settings = yaml.load(handle, Loader=CSafeLoader)
```

Each of those keyword arguments overrides a default you almost certainly do not want for a file a
human may open — see the `allow_unicode` bullet in [Things to know](#things-to-know). Both loaders
take a file object as happily as a string, so there is no reason to read the file in yourself
first.

Use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. PyYAML leaves nothing beside the file you asked for — after
that round trip the directory holds `settings.yaml` and nothing else: no lock file, no journal, no
temp sibling.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`settings-file`](examples/settings-file) — writes the app's own settings file, times both
  loaders against it on the device, and shows which one rejects a document the other accepts.

## Threading

**Neither loader releases the GIL, so a parse in a background thread competes with the UI thread
rather than running alongside it.** There is not one `nogil` in PyYAML's Cython sources
(`yaml/_yaml.pyx`, `yaml/_yaml.pxd`, `yaml/__init__.pxd` — zero occurrences), and neither
platform's built extension imports `PyEval_SaveThread`, `PyEval_RestoreThread` or any
`PyGILState_*` entry point: zero matches in the dynamic symbols of all three Android ABIs and in
the undefined symbols of all three iOS slices. Nothing starts a thread either — `pthread_create`
is absent from every slice.

What that does *not* mean is that a load freezes everything. `CSafeLoader` is libyaml's parser
plus PyYAML's own pure-Python `SafeConstructor` and `Resolver`, so control returns to the
interpreter constantly and the GIL gets shared as it would with any Python work. Measured on
desktop with a 219 KB document parsed in a worker thread while a busy loop counted turns on the
main thread: around 25,000 turns/ms with nothing else running, and 10,000–12,000 during a load —
with either loader, in either order. Roughly half the interpreter each, which is what two threads
of ordinary Python work look like. What the C loader changes is how long the competition lasts:
under that contention the pure load took 629 ms and the C load 74 ms.

So the practical shape is the ordinary one. Push a large parse to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end the
worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads — and wrap its body in `try/except`, because `run_thread` discards
whatever the worker raises. A parse bug in a worker looks like a screen that stopped updating,
not like an error. For a document big enough to stutter even at C speed, split it into documents
and [`load_all`](https://pyyaml.org/wiki/PyYAMLDocumentation) them in chunks so the worker has
somewhere to yield.

There is no shared handle here to serialise between threads: `yaml.load` constructs a loader,
calls `get_single_data()` and disposes it in a `finally`, so each call owns its own state.

## Android notes

**libyaml is a separate shared library, resolved by bare soname.** `_yaml.*.so` names
`libyaml.so` in its `DT_NEEDED` list on all three ABIs — alongside `libm.so`,
`libpython3.<minor>.so`, `libdl.so` and `libc.so` — carries no `RPATH` or `RUNPATH`, and leaves
29 `yaml_*` symbols undefined for it to satisfy. `flet-libyaml`'s own `SONAME` is exactly
`libyaml.so`, and serious_python's Android packaging — its Gradle `copyOpt` task — copies every
`.so` under a wheel's `opt/` directory into `jniLibs/<abi>/` under its plain basename, so the
linker namespace resolves it. That is what makes `flet-libyaml` load-bearing here, and why it
needs no `extract_packages` entry of its own.

Of `flet-libyaml`'s 166 KB unpacked, 111 KB survives Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) — and it is the part
that matters, `libyaml.so` itself. The 54 KB `opt/include/yaml.h` goes, matched by the `**.h`
glob. Nothing to configure.

All three extensions and `libyaml.so` carry 16 KB `PT_LOAD` alignment, which Android 15
requires.

**`yaml._yaml.__file__` on Android is the relocated library, not a path inside your app.** Flet
moves every tagged extension out of site-packages into `jniLibs`, leaving a `.soref` marker at the
import path. Measured on an arm64 emulator (2026-08-17), the header line reads
`_yaml.__file__ libyaml-_yaml.so` — a bare `jniLibs` filename, with the package directory the
module nominally lives in nowhere in it. Do not assume this generalises: for the same Flet version
[`pydantic-core`](../pydantic-core) reports **no** `__file__` at all on Android, so whether the
attribute exists depends on the package rather than on the platform. Either way, code that locates
a resource relative to a native module's `__file__` breaks here — with an `AttributeError`, a
`TypeError` on `None`, or a path that simply is not where the package's data files are. The
[`settings-file`](examples/settings-file) example prints the value in its header line so you can
read the answer off the device instead of taking this paragraph's word for it.

## iOS notes

**libyaml is linked *into* the extension here, not loaded beside it.** All three iOS extensions
are `MH_DYLIB` marked `NOUNDEFS`; `otool -L` on each lists only its own install name,
`@rpath/Python.framework/Python` and `/usr/lib/libSystem.B.dylib` — no libyaml anywhere — and each
defines 54 `_yaml_*` symbols itself while leaving none undefined. Of the 175 symbols the device
slice imports, everything outside CPython's own API is libc — `malloc`, `memcpy`, `strdup`,
`fread`, `fwrite`, `ferror` and the rest of that family, plus the stack guard and
`dyld_stub_binder`.

That absorbed copy is most of the size difference between the platforms: 373,760 bytes for the
iOS device extension against 197,520 for Android arm64-v8a. Not all of it, though — Android's
extension plus its separate `libyaml.so` still only come to 308,744, so about 65 KB of the gap is
Mach-O's 16 KB segment alignment and 64 KB `__LINKEDIT` rather than code.

The practical consequence is that **`flet-libyaml` contributes nothing at runtime on iOS.** Its
payload there is a static archive, a header, and one dylib. Flet's default cleanup removes the
first two — `**.a` and `**.h` account for 488 KB of the wheel's 652 KB — and what is left is a
165 KB top-level `libyaml.so` that nothing links: the extension's `otool -L` does not name it,
and in the wheel its install name is still the CI build path it was compiled with
(`/Users/runner/work/mobile-forge/…/opt/lib/libyaml.dylib`).

It does not sit inertly in `site-packages`, though. It ends in `.so`, so serious_python's iOS
packaging treats it like any extension module — read out of the
[`settings-file`](examples/settings-file) example's own simulator build, it becomes a signed
`Frameworks/libyaml.framework` with its install name rewritten to
`@rpath/libyaml.framework/libyaml`, and a one-line `site-packages/libyaml.fwork` left at the old
path, by the same mechanism the last paragraph of this section describes for the extension.
Nothing loads it — neither the app binary nor `App.framework` names it in `otool -L`, and no
Python module is called `libyaml` — but it is embedded and code-signed, and on a simulator build
it is a fat binary of both simulator slices, 346,368 B in that bundle rather than the 165 KB one
slice costs.

**Do not try to remove it with a
[`[tool.flet.cleanup] package_files`](https://flet.dev/docs/publish/#compilation-and-cleanup)
glob.** On Android a file of exactly that name is the library the app cannot import without, and
the setting is not per-platform. Leave it. Dropping it belongs in the
`flet-libyaml` recipe, not in your app — see [Build notes](#build-notes-maintainers).

**`yaml._yaml.__file__` is a `.fwork` path on iOS**, not `None` as on Android. serious_python
turns each site-packages `.so` into a framework and leaves a `<name>.fwork` pointer file at the
module's original path, and CPython's own `AppleFrameworkLoader` reports that pointer's path as
`__file__` — which is how [`pydantic-core`](../pydantic-core) comes to report
`_pydantic_core.fwork` on an iOS device. So the same `getattr` that yields `None` on Android yields
something ending in `_yaml.fwork` here. Neither is the name in the wheel; read it as which file the
import system resolved, and read it off the example's header line rather than off this page.

## Things to know

- **`yaml.safe_load` and `yaml.safe_dump` do not use the C accelerator.** They are the spelling
  in every tutorial and they run the Python scanner: the shipped `yaml/__init__.py` is literally
  `return load(stream, SafeLoader)`, and `SafeLoader` in `yaml/loader.py` is built from
  `Reader, Scanner, Parser, Composer, SafeConstructor, Resolver` — all Python. So an app can ship
  this wheel, load its config on every launch, and never touch libyaml. Measured on desktop, best
  of 25, on a settings-shaped document at four sizes from 3,448 to 219,049 bytes and with the flags
  [Storage](#storage) recommends: over two independent passes the C loader ran 6.8–8.4× faster
  and the C emitter 4.2–5.4× faster, with no size making either one stop paying — the load ratio
  drifts a little down and the emit ratio a little up as the document grows (at 54,763 bytes:
  68 ms → 8.8 ms loading, 37 ms → 7.7 ms emitting). The fix is `Loader=`/`Dumper=` on the calls
  you already have. For
  scale, `json.loads` of the same data as JSON — 51,982 bytes of it — took 0.23 ms against the C
  loader's 8.8 ms. YAML is not a fast format, and the C accelerator does not make it one; if you
  chose YAML for a file only your app reads, JSON is another 30–40× cheaper on top of everything
  the accelerator buys you.
- **It really is a drop-in.** Not just documented as one: `yaml.dump` produced byte-identical
  output under `SafeDumper` and `CSafeDumper` across ten emitter stress cases (a 120-character
  scalar, non-ASCII with and without `allow_unicode`, a shared object emitted as an alias, flow
  style, `bytes`, a tuple key, leading and trailing whitespace, the quote-forcing strings `yes`
  / `null` / `1.0` / `on` / `~`, four-deep nesting, and a tuple/set/date battery), and the two
  loaders returned equal objects at every document size measured above. The example re-checks both
  on the device rather than trusting this.
- **If the accelerator is ever missing, nothing tells you.** `yaml/__init__.py` wraps its import
  in `try: from .cyaml import * … except ImportError: __with_libyaml__ = False`, and `cyaml.py`
  is the only place the C classes are defined. So with `yaml._yaml` unavailable,
  `yaml.__with_libyaml__` is `False`, `hasattr` is `False` for all five C loaders and all three C
  dumpers, `yaml.CSafeLoader` raises
  `AttributeError: module 'yaml' has no attribute 'CSafeLoader'` — and `yaml.safe_load` keeps
  working perfectly, about eight times slower. `from yaml import CSafeDumper, CSafeLoader` at the
  top of your module turns that silent regression into an `ImportError` on the first line of the
  app. If you would rather degrade than fail, bind once at import
  (`Loader = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader`) instead of
  branching per call, and put `yaml.__with_libyaml__` somewhere you will see it.
- **`import _yaml` is the deprecated spelling and warns.** The shipped `_yaml/__init__.py` is a
  compatibility stub: it re-exports `yaml._yaml` and then emits a `DeprecationWarning` saying
  the module moved. Under `python -W error::DeprecationWarning` that import fails outright. Use
  `from yaml import CSafeLoader, CSafeDumper`, or `import yaml._yaml` when you want the module
  itself — `yaml._yaml.get_version_string()` is how you ask which libyaml you got.
- **The C loader accepts documents the Python one rejects. Tabs are the common case.** `a:\tb`
  gives `{'a': 'b'}` under `CSafeLoader` and
  `ScannerError: found character '\t' that cannot start any token` under `SafeLoader`; same split
  for a trailing tab (`a: b\t`) and a tab inside a flow sequence (`a: [1,\t2]`). libyaml is the
  more permissive and the more spec-correct one here. The trap is not the tab, it is *mixing*:
  one call site says `yaml.safe_load` and another says `Loader=CSafeLoader`, and the same file
  then loads in one code path and fails in the other inside one app. Pick one loader for the
  whole app. If you accept user-edited YAML, normalise tabs to spaces before parsing so the file
  behaves the same whatever the build.
- **And it rejects three kinds of document the Python one accepts.** An unrecognised directive
  (`%FOO bar\n---\na: 1`) is `{'a': 1}` to the Python loader and
  `ScannerError: found unknown directive name` to the C one. A byte-order mark part-way through a
  stream (`a: 1\n\ufeffb: 2`) is a key beginning with U+FEFF to the Python loader and
  `ParserError: did not find expected key` to the C one. A lone surrogate escape (`a: "\uD800"`)
  is a string to the Python loader and
  `ScannerError: found invalid Unicode character escape code` to the C one. None of that matters
  for hand-written config; it matters when you concatenate documents or take files from
  arbitrary editors. Join with an explicit `---` separator and `load_all`, and strip a BOM before
  concatenating rather than after.
- **Switching to the C loader costs you the caret in error messages.** Both loaders raise the
  *same* exception classes at the *same* place — `yaml._yaml.ScannerError is
  yaml.scanner.ScannerError` is `True`, likewise for `ParserError` and `ComposerError`, and
  across seven malformed documents both reported the identical class, line and column every
  time. What differs is the mark: the Python loader's `problem_mark` carries the buffer, so
  `get_snippet()` returns something like `'     bad_indent: 1\n     ^'`, while the C loader's has
  `buffer` and `pointer` both `None` and `get_snippet()` returns `None`. The `problem` text is
  also less specific — on one bad-indent document, `expected <block end>, but found '<block
  mapping start>'` against `did not find expected key`. For a config-editing screen, build the
  caret yourself from `error.problem_mark.line` and `.column` (both zero-based) against the text
  you already hold; or parse with the C loader for speed and, only on failure, re-parse with
  `SafeLoader` purely to get a message with a caret in it.
- **`yaml.dump` escapes non-ASCII by default, so an accented settings file comes out
  unreadable.** `yaml.safe_dump({"k": "café — ok"})` is `'k: "caf\\xE9 \\u2014 ok"\n'`; with
  `allow_unicode=True` it is `'k: café — ok\n'`. Identical for both dumpers. `sort_keys=True` is
  also the default, which silently reorders any file you round-trip. Pass both
  (`allow_unicode=True, sort_keys=False`) whenever a human might open the file.
- **A round trip erases every comment and every blank line, and both implementations do it
  identically.** The loader produces plain Python objects and the comments are simply not in
  them — `yaml.compose` hands back a node tree with no comment attribute either — so load-edit-save
  over a file a human maintains silently deletes their notes. For a settings file only your app
  reads that is fine, and it is why the [Storage](#storage) snippet is written the way it is. If
  you need the comments back, [`ruamel.yaml`](https://yaml.readthedocs.io/) is the library that
  keeps them and it needs no recipe — measured for Android arm64 / 3.14, it resolves as
  `ruamel_yaml-0.19.1-py3-none-any.whl`. Its C accelerator `ruamel.yaml.clib` is *not* on this
  index, though, so that is a straight trade of this recipe's speed for round-trip fidelity.
- **Neither dumper can represent `Decimal`, `complex` or `pathlib.Path`,** and the failure comes
  at save time rather than at edit time: `RepresenterError: ('cannot represent an object',
  Decimal('1.5'))`, the same from `SafeDumper` and `CSafeDumper`. Convert at the boundary
  (`str(path)`, `str(dec)`), or register a representer — and note the keyword:
  `yaml.add_representer(Decimal, fn, Dumper=yaml.CSafeDumper)`. Registering on the default
  `Dumper` does not reach `CSafeDumper`.
- **Four of the ten loaders execute arbitrary Python from a document, and the C ones are exactly
  as dangerous as their Python twins.** Loading `!!python/object/apply:os.getpid []` returns a pid
  under `Loader`, `CLoader`, `UnsafeLoader` and `CUnsafeLoader`; raises
  `ConstructorError: could not determine a constructor for the tag …` under `SafeLoader`,
  `CSafeLoader`, `FullLoader` and `CFullLoader`; and comes back as an empty list under
  `BaseLoader` and `CBaseLoader`, which ignore tags altogether. There is no unsafe default left in
  6.x — `def load(stream, Loader)` has no default, and `yaml.load("a: 1")` raises
  `TypeError: load() missing 1 required positional argument: 'Loader'`. Stay on the `Safe` pair
  for anything you did not write.
- **Duplicate keys are silently last-wins in both loaders.** `a: 1\na: 2` is `{'a': 2}` either
  way, so a config that says one thing twice quietly takes the second value. (A duplicate
  *anchor* does raise `ComposerError`, in both.) If you validate user-edited YAML, catch it
  yourself: `yaml.compose(text, Loader=CSafeLoader)` returns the node tree with both keys still
  in it and a usable `start_mark.line` per key — `[('a', 0), ('b', 1), ('a', 2)]`, identical with
  either loader — so you can report the line the second one is on.
- **Everything else the two loaders agree on, including the things people expect to differ.**
  Recursive anchors build self-referential objects in both (`&a [1, *a]`, `&a {self: *a, n: 1}`);
  merge keys (`<<: *b`) resolve in both; and the tag resolver is shared, so `12:30:45` → `45045`,
  `0x1F` → `31`, `yes` → `True`, `.inf`/`.nan` → floats and `2026-08-17 10:00:00` → a `datetime`
  come out the same. Upstream's documentation applies to both.
- **Size: small, and the C library is the only thing that moves.** 24 files per wheel: 219 KB of
  Python, 5 KB of metadata and licence, and one extension. Everything but the extension comes to
  the same 224 KB on every single slice — 223,772 to 223,805 bytes across all nineteen, the whole
  33-byte spread being the length of the extension's filename in `RECORD` and of the platform tag
  in `WHEEL`. Per slice, on Python 3.14; the other two minors are within a few KB on every row
  except the two arm64 iOS ones, where the extension moves by up to 17 KB (3.12 and 3.13 are both
  about 16 KB smaller than 3.14 on the device slice, and on the arm64 simulator 3.13 alone is):

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 120 KB | 421 KB | 198 KB |
  | Android armeabi-v7a | 115 KB | 360 KB | 136 KB |
  | Android x86_64 | 127 KB | 419 KB | 195 KB |
  | iOS arm64 (device) | 164 KB | 598 KB | 374 KB |
  | iOS arm64 (simulator) | 167 KB | 584 KB | 360 KB |
  | iOS x86_64 (simulator) | 173 KB | 560 KB | 336 KB |

  Add `flet-libyaml` on top: 55 KB → 166 KB on Android arm64, of which 111 KB is installed;
  215 KB → 652 KB on iOS device, of which 165 KB is installed and none of it used. Nothing in the
  pyyaml wheel matches one of Flet's junk-file globs, so nothing is deleted — but the default
  `compile.packages` swaps the 18 `.py` files for `.pyc`, and on 3.14 that lands the Python half
  at 263 KB rather than 219 KB in the APK's `sitepackages.zip`. Compiling this wheel makes it
  bigger, not smaller.
- **The Python half of the wheel is upstream's, byte for byte.** All 18 `.py` files — the
  `_yaml` stub plus `yaml/`'s `__init__`, `composer`, `constructor`, `cyaml`, `dumper`, `emitter`,
  `error`, `events`, `loader`, `nodes`, `parser`, `reader`, `representer`, `resolver`, `scanner`,
  `serializer` and `tokens` — hash identical between the Android wheel, the iOS wheel and the
  same-version PyPI macOS wheel, and all three hold the same 24 files once the extension's platform
  tag is set aside (the desktop wheel additionally records four directory entries, which the mobile
  wheels omit). The recipe carries no patches, which is why. And it is the same
  libyaml as the desktop wheel bundles: `0.2.5`, read out of `flet-libyaml`'s `libyaml.so`, out
  of the statically linked iOS extension, and out of the PyPI macOS extension. So upstream's
  documentation applies here without a translation step.

## Build notes (maintainers)

Two recipes: `flet-libyaml` builds the C library, `recipes/pyyaml` consumes it. The pyyaml half is
eight lines of settings in `meta.yaml` with no patches and no `build.sh`, and the one non-obvious
setting carries its own comment there, so what is left here is shape and the bump checklist.

**A change here can go green and still be broken.** The one failure this recipe exists to prevent
does not fail the build — it produces a perfectly valid pure-Python wheel, for the reason
`meta.yaml` comments — so the only thing standing between that and a release is the pair of
extension assertions in `tests/`, which are very nearly the whole of CI's coverage. Every claim on
this page that distinguishes the two implementations assumes the extension is there.

**`flet-libyaml` is `requirements.host`, not `requirements.host_build`, and that is deliberate.**
`host_build` would put it in the cross environment for the link and then not ship it — right on
iOS, where it is statically absorbed, and fatal on Android, where the extension resolves
`libyaml.so` by bare soname at load time. One recipe has to satisfy both, so it is an ordinary
runtime dependency and appears in `Requires-Dist` on both platforms. On iOS that is redundant
rather than harmful, and Flet's cleanup deletes most of the redundant part unprompted. Same
trade-off as [`lxml`](../lxml).

**The 161 KB of dead weight on iOS is fixable here and nowhere else.** `flet-libyaml`'s
`build.sh` ends with `mv $PREFIX/lib/libyaml.dylib $PREFIX/../libyaml.so` on the Apple SDKs,
which is what makes pyyaml's `-lyaml` pick `libyaml.a` instead of the dylib. Moving the dylib out
of `opt/lib` is necessary; leaving it at `$PREFIX/..` — the wheel root — is not, and that is the
only reason it ships. A destination outside the wheel would achieve the same link behaviour and
drop a whole embedded, code-signed framework from every iOS app — 165 KB on a device build, twice
that on a simulator one, since serious_python lifts it like any other `.so`. The app-side
workaround does not exist: a
`cleanup.packages` glob on `libyaml.so` would also delete Android's load-bearing copy, which is
why [iOS notes](#ios-notes) tells readers not to try.

What to re-verify on a bump — everything above this section is a claim about one build, and most
of it can be falsified without the build failing:

- **The extension's presence in every published wheel**, per the paragraph above.
  `unzip -l | grep '\.so$'` is the whole check, and it is the one that matters most.
- **The libyaml version**, in three places: `flet-libyaml`'s Android `opt/lib/libyaml.so`, the
  statically linked iOS extension, and the same-version PyPI desktop wheel. The claim that mobile
  and desktop run the same libyaml rests on those matching; `strings … | grep -E '^0\.[0-9]+\.[0-9]+$'`
  finds it. Note the Android pyyaml extension does *not* contain the string — it is in the shared
  library, which is the point.
- **The linkage split.** Android: `DT_NEEDED` still names `libyaml.so`, with no `RPATH`/`RUNPATH`,
  and `flet-libyaml`'s `SONAME` is still exactly `libyaml.so` — the two have to agree or the app
  cannot import. iOS: still `MH_DYLIB` + `NOUNDEFS`, with `otool -L` naming no libyaml. If iOS
  ever links dynamically instead, the dead-weight paragraph, the size table and the
  `Requires-Dist` reasoning all change. Also confirm the Android ELFs still carry 16 KB `PT_LOAD`
  alignment.
- **The accept/reject divergences and the exception wording.** These are the most consumer-visible
  claims on the page and the least protected: they are properties of libyaml versus PyYAML's own
  scanner, so a bump of *either* can move them, and the `problem` strings are upstream's prose in
  both implementations. Re-run the six divergent documents (three tab cases, unknown directive,
  mid-stream BOM, lone surrogate escape) and the seven both-reject documents that establish the
  same-class-same-line-same-column claim.
- **The GIL claim.** Grep the sdist's `yaml/*.pyx` and `yaml/*.pxd` for `nogil`, and the built
  extensions for `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState` and `pthread_create`.
  All are absent today. A symbol grep is worth only as much as its control, so check the behaviour
  as well: four threads each parsing a *different* document take the same wall time as the four
  parses run one after another (measured 1.07×, against 3.52× for `hashlib` on the same machine,
  which does release the GIL). A release that added a `nogil` block would rewrite
  [Threading](#threading) without breaking anything.
- **The byte-identical Python files and the 24-file inventory**, against the desktop wheel of the
  *same* version. A new data file, or a diverging `__init__.py`, would put both the
  no-`extract_packages` claim and "upstream's documentation applies" back in question.
- **The measurements.** The 6.8–8.4× / 4.2–5.4× figures, the desktop GIL-sharing turns/ms and the
  size table are all measured. Re-measure; do not scale. The ratios are the transferable part —
  absolute times on a phone are worse than any of the desktop numbers quoted, and the desktop ones
  were themselves taken on a machine with other work on it, which is why they are given as ranges
  over repeated runs.

**The tests cover presence and nothing else, and two of the three have problems.**
`tests/test_pyyaml.py` asserts that `_yaml` carries `CParser` and that
`from yaml import CSafeDumper, CSafeLoader` works — which is exactly the right thing to guard, and
is why the silent-pure-wheel failure would turn CI red. But `test_basic`'s docstring says it
round-trips "through PyYAML's C-loader and C-dumper" while its body calls `yaml.safe_dump` and
`yaml.safe_load`, i.e. the pure ones; and `test_c_extension` uses `import _yaml`, the deprecated
spelling, which would fail under a `-W error::DeprecationWarning` runner. Fix the docstring or the
body, and prefer `import yaml._yaml`.

Worth adding, in rough order of value: an equality check between `CSafeLoader` and `SafeLoader`
on one document and a byte-equality check between `CSafeDumper` and `SafeDumper` on another —
together those are the [Things to know](#things-to-know) drop-in claim, on the device; one of the
tab documents, asserting that `CSafeLoader` accepts what `SafeLoader` rejects, which is the claim
most likely to move under a libyaml bump; and a `FLET_APP_STORAGE_DATA` round trip, since nothing
in `tests/` currently touches the filesystem. Per the repo's test convention, assert
relationships rather than version numbers — `get_version_string()` belongs on screen in the
example, not in an assertion a bump has to chase — and give every test function a docstring.
