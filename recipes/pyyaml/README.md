# PyYAML

[`PyYAML`](https://pyyaml.org/wiki/PyYAMLDocumentation) is the YAML parser and emitter almost
every Python config file goes through: `yaml.safe_load` on the way in, `yaml.safe_dump` on the
way out. On a phone the reason to want it is the same reason a desktop app wants it — a settings
file, a bundled ruleset, a document a server handed you in YAML instead of JSON — with one
difference that matters more here than anywhere else.

**PyYAML ships two complete implementations, and the fast one is not the default.** The scanner,
parser, emitter and serialiser are written twice: once in Python, and once in C on top of
[libyaml](https://pyyaml.org/wiki/LibYAML). The Python pair is what `safe_load` and `safe_dump`
use. This recipe's entire job is to make the C pair — `CSafeLoader` and `CSafeDumper` — actually
present on a phone. Nothing switches to it for you, and nothing tells you if it is missing.

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

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`settings-file`](examples/settings-file) — writes the app's own settings file, times both
  loaders against it on the device, and shows which one rejects a document the other accepts.

## Usage in a Flet app

Name the C classes at the top of the module and pass them at the two call sites, because the
defaults leave this whole recipe unused:

```python
import yaml
from yaml import CSafeDumper, CSafeLoader

settings = yaml.load(text, Loader=CSafeLoader)
text = yaml.dump(settings, Dumper=CSafeDumper, sort_keys=False, allow_unicode=True)
view = ft.TextField(value=text, multiline=True, read_only=True)
```

Both calls deal in plain strings, so the emitted text drops straight into an
[`ft.TextField`](https://flet.dev/docs/controls/textfield/) or an
[`ft.Text`](https://flet.dev/docs/controls/text/) with no conversion step. The
`from yaml import …` line is doing real work, though: if the accelerator is ever absent, those
two names are simply not in the `yaml` namespace and `safe_load` keeps working several times
slower, so importing them by name turns a silent regression into an `ImportError` on the app's
first line. The two keyword arguments override defaults you almost certainly do not want; see
[Things to know](#things-to-know).

### Storage

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

Both loaders take a file object as happily as a string, so there is no reason to read the file in
yourself first. Use
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files you can re-derive and
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything you can afford to lose. PyYAML leaves nothing beside the file you asked for — after
that round trip the directory holds `settings.yaml` and nothing else: no lock file, no journal,
no temp sibling.

### Threading

**Neither loader releases the GIL, so a parse in a background thread competes with the UI thread
rather than running alongside it.** That does not mean a load freezes everything. `CSafeLoader`
is libyaml's parser plus PyYAML's own pure-Python `SafeConstructor` and `Resolver`, so control
returns to the interpreter constantly and the GIL gets shared as it would with any Python work.
Measured on desktop, with a 219 KB document parsed in a worker while a busy loop counted turns on
the main thread: about 25,000 turns/ms idle against 10,000–12,000 during a load, with either
loader — roughly half the interpreter each. What the C loader changes is how long the competition
lasts: under that contention the pure load took 629 ms and the C load 74 ms.

So the practical shape is the ordinary one. Push a large parse to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), end the
worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does not
reach background threads — and wrap its body in `try/except`, because `run_thread` discards
whatever the worker raises. A parse bug in a worker looks like a screen that stopped updating,
not like an error. For a document big enough to stutter even at C speed, split it into documents
and [`load_all`](https://pyyaml.org/wiki/PyYAMLDocumentation) them in chunks so the worker has
somewhere to yield.

There is no shared handle to serialise between threads: `yaml.load` constructs a loader, calls
`get_single_data()` and disposes it in a `finally`, so each call owns its own state.

### App size

The wheel is approximately 115–175 KB compressed and 360–600 KB unpacked per slice — the
extension is 135–375 KB of that and the rest is the same 220 KB of Python everywhere — and the C
library adds roughly 110 KB more on Android, 165 KB on iOS. That is small enough that narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) or moving
to an app bundle or split APKs is a decision to make for the app's other dependencies, not for
this one.

Flet compiles site-packages to `.pyc` and deletes the `.py` files by default on **both**
platforms ([`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup)). Leave
it on. It does not shrink this wheel — measured in an Android APK's `sitepackages.zip` on
Python 3.14, the Python half lands at 263 KB compiled against 219 KB as source — but nothing in
the package reads its own source, so nothing breaks.

### Android

**libyaml ships as a separate `libyaml.so` and the extension resolves it by bare soname.** It
arrives with the wheel and is installed for you, so there is nothing to configure — but nothing
that deletes a file of that name may run against an Android build, or `import yaml` fails at
startup.

**`yaml._yaml.__file__` is the relocated library, not a path inside your app.** Flet moves every
tagged extension out of site-packages into `jniLibs`, leaving a marker at the import path.
Measured on an arm64 emulator (2026-08-17) the value reads `libyaml-_yaml.so` — a bare `jniLibs`
filename, with the package directory the module nominally lives in nowhere in it. Do not assume
this generalises: for the same Flet version [`pydantic-core`](../pydantic-core) reports **no**
`__file__` at all on Android, so whether the attribute exists depends on the package rather than
on the platform. Either way, code that locates a resource relative to a native module's
`__file__` breaks here — as an `AttributeError`, a `TypeError` on `None`, or a path that is
simply not where the package's files are.

### iOS

**libyaml is linked *into* the extension here, not loaded beside it,** so nothing separate has to
load at import time and the extension is correspondingly larger — 374 KB on the device slice
against 198 KB for Android arm64-v8a.

A top-level `libyaml.so` still ships in the payload, and nothing on iOS uses it. It is not inert,
though: it ends in `.so`, so serious_python treats it like any extension module and it becomes a
signed `libyaml.framework` in the bundle — about 165 KB on a device build and roughly twice that
on a simulator build, where it is fat. **Do not try to remove it with a
[`[tool.flet.cleanup] package_files`](https://flet.dev/docs/publish/#compilation-and-cleanup)
glob.** On Android a file of exactly that name is the library the app cannot import without, and
the setting is not per-platform. Leave it; the fix belongs in the recipe, not in your app.

**`yaml._yaml.__file__` is a `.fwork` path on iOS.** serious_python turns each site-packages
`.so` into a framework and leaves a `<name>.fwork` pointer file at the module's original path,
and CPython's `AppleFrameworkLoader` reports that pointer's path as `__file__` — which is how
[`pydantic-core`](../pydantic-core) comes to report `_pydantic_core.fwork`; pyyaml's own reads `libyaml-_yaml.so` on Android and `_yaml.fwork` on iOS on an iOS device.
Neither platform's value is the name in the wheel; read it as which file the import system
resolved, and read it off the [example](examples/settings-file)'s header line rather than off
this page.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, and for this package that is an unusually faithful
rehearsal. The recipe carries no patches, so the Python half is upstream's byte for byte, the
mobile extensions are built from the same libyaml release the desktop wheel bundles, and both
loaders behave identically on everything measured here. Upstream's documentation applies without
a translation step, and so does everything on this page — except `__file__`, which is a packaging
artefact of the two mobile platforms and has no desktop equivalent. Confirm that one on a device;
`yaml._yaml.get_version_string()` is how you ask which libyaml you actually got.

## Things to know

- **`yaml.safe_load` and `yaml.safe_dump` do not use the C accelerator.** They are the spelling in
  every tutorial and they run the Python scanner, so an app can ship this wheel, load its config
  on every launch, and never touch libyaml. Measured on desktop, best of 25, on settings-shaped
  documents from 3.4 KB to 219 KB and with the flags [Storage](#storage) recommends: the C loader
  ran 6.8–8.4× faster and the C emitter 4.2–5.4× faster, with no size making either stop paying.
  The fix is `Loader=`/`Dumper=` on the calls you already have. For scale, `json.loads` of the
  same data as JSON took 0.23 ms where the C loader took 8.8 ms — the accelerator does not make
  YAML a fast format, so if you chose it for a file only your app reads, JSON is another 30–40×
  cheaper on top.
- **If the accelerator is ever missing, nothing tells you.** `yaml/__init__.py` swallows the
  `ImportError` from `cyaml`, the only place the C classes are defined, so `yaml.__with_libyaml__`
  becomes `False`, all five C loaders and all three C dumpers are simply absent from the
  namespace, `yaml.CSafeLoader` raises `AttributeError` — and `yaml.safe_load` keeps working
  perfectly, at the pure-Python speed above. If you would rather degrade than fail, bind once at
  import (`Loader = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader`) instead of
  branching per call, and put `yaml.__with_libyaml__` somewhere you will see it.
- **It really is a drop-in.** Not just documented as one:
  [`yaml.dump`](https://pyyaml.org/wiki/PyYAMLDocumentation) produced byte-identical output under
  `SafeDumper` and `CSafeDumper` across ten emitter stress cases — non-ASCII, aliases, flow style,
  `bytes`, tuple keys, edge whitespace, quote-forcing scalars, deep nesting — and the two loaders
  returned equal objects at every document size measured above. The example re-checks both on the
  device rather than trusting this.
- **`import _yaml` is the deprecated spelling and warns.** The shipped `_yaml/__init__.py` is a
  stub that re-exports `yaml._yaml` and emits a `DeprecationWarning`; under
  `python -W error::DeprecationWarning` that import fails outright. Use
  `from yaml import CSafeLoader, CSafeDumper`, or `import yaml._yaml` for the module itself.
- **The C loader accepts documents the Python one rejects. Tabs are the common case.** `a:\tb`
  gives `{'a': 'b'}` under `CSafeLoader` and
  `ScannerError: found character '\t' that cannot start any token` under `SafeLoader`; same split
  for a trailing tab (`a: b\t`) and a tab inside a flow sequence (`a: [1,\t2]`). libyaml is the
  more permissive and the more spec-correct one here. The trap is not the tab, it is *mixing*:
  one call site says `yaml.safe_load` and another says `Loader=CSafeLoader`, and the same file
  then loads in one code path and fails in the other inside one app. Pick one loader for the whole
  app, and if you accept user-edited YAML, normalise tabs to spaces before parsing.
- **And it rejects three kinds of document the Python one accepts.** An unrecognised directive
  (`%FOO bar\n---\na: 1`) is `{'a': 1}` to the Python loader and
  `ScannerError: found unknown directive name` to the C one. A byte-order mark part-way through a
  stream (`a: 1\n\ufeffb: 2`) is a key beginning with U+FEFF to the Python loader and
  `ParserError: did not find expected key` to the C one. A lone surrogate escape (`a: "\uD800"`)
  is a string to the Python loader and `ScannerError: found invalid Unicode character escape code`
  to the C one. None of that matters for hand-written config; it matters when you concatenate
  documents or take files from arbitrary editors. Join with an explicit `---` separator and
  [`load_all`](https://pyyaml.org/wiki/PyYAMLDocumentation), and strip a BOM before concatenating
  rather than after.
- **Switching to the C loader costs you the caret in error messages.** Both raise the same
  exception classes at the same place — across seven malformed documents both reported the
  identical class, line and column. What differs is the mark: the Python loader's `problem_mark`
  carries the buffer, so `get_snippet()` returns something like `'     bad_indent: 1\n     ^'`,
  while the C loader's has `buffer` and `pointer` both `None` and `get_snippet()` returns `None`.
  The `problem` text is less specific too. For a config-editing screen, build the caret yourself
  from `error.problem_mark.line` and `.column` (both zero-based) against the text you already
  hold; or parse with the C loader for speed and, only on failure, re-parse with `SafeLoader`
  purely to get a message with a caret in it.
- **`yaml.dump` escapes non-ASCII by default, so an accented settings file comes out unreadable.**
  `yaml.safe_dump({"k": "café — ok"})` is `'k: "caf\\xE9 \\u2014 ok"\n'`; with
  `allow_unicode=True` it is `'k: café — ok\n'`. Identical for both dumpers. `sort_keys=True` is
  also the default, which silently reorders any file you round-trip. Pass both
  (`allow_unicode=True, sort_keys=False`) whenever a human might open the file.
- **A round trip erases every comment and every blank line, and both implementations do it
  identically.** The loader produces plain Python objects and the comments are simply not in them
  — [`yaml.compose`](https://pyyaml.org/wiki/PyYAMLDocumentation) hands back a node tree with no
  comment attribute either — so load-edit-save over a file a human maintains silently deletes
  their notes. For a settings file only your app reads that is fine, and it is why the
  [Storage](#storage) snippet is written the way it is. If you need the comments back,
  [`ruamel.yaml`](https://yaml.readthedocs.io/) is the library that keeps them: it resolves as a
  pure-Python wheel and needs no recipe, while its compiled accelerator has one of its own,
  [`ruamel.yaml.clib`](../ruamel.yaml.clib).
- **Neither dumper can represent `Decimal`, `complex` or `pathlib.Path`,** and the failure comes at
  save time rather than at edit time: `RepresenterError: ('cannot represent an object',
  Decimal('1.5'))`, the same from `SafeDumper` and `CSafeDumper`. Convert at the boundary
  (`str(path)`, `str(dec)`), or register a representer — and note the keyword:
  [`yaml.add_representer`](https://pyyaml.org/wiki/PyYAMLDocumentation)`(Decimal, fn,
  Dumper=yaml.CSafeDumper)`. Registering on the default `Dumper` does not reach `CSafeDumper`.
- **Four of the ten loaders execute arbitrary Python from a document, and the C ones are exactly
  as dangerous as their Python twins.** `!!python/object/apply:os.getpid []` returns a pid under
  `Loader`, `CLoader`, `UnsafeLoader` and `CUnsafeLoader`; raises `ConstructorError` under
  `SafeLoader`, `CSafeLoader`, `FullLoader` and `CFullLoader`; and is an empty list under
  `BaseLoader` and `CBaseLoader`, which ignore tags. There is no unsafe default left in 6.x —
  `yaml.load("a: 1")` raises
  `TypeError: load() missing 1 required positional argument: 'Loader'`. Stay on the `Safe` pair
  for anything you did not write.
- **Duplicate keys are silently last-wins in both loaders.** `a: 1\na: 2` is `{'a': 2}` either
  way, so a config that says one thing twice quietly takes the second value. (A duplicate *anchor*
  does raise `ComposerError`, in both.) If you validate user-edited YAML, catch it yourself:
  `yaml.compose(text, Loader=CSafeLoader)` returns the node tree with both keys still in it and a
  usable `start_mark.line` per key, so you can report the line the second one is on.
- **Everything else the two loaders agree on, including the things people expect to differ.**
  Recursive anchors build self-referential objects in both (`&a [1, *a]`); merge keys (`<<: *b`)
  resolve in both; and the tag resolver is shared, so `12:30:45` → `45045`, `0x1F` → `31`,
  `yes` → `True`, `.inf`/`.nan` → floats and `2026-08-17 10:00:00` → a `datetime` come out the
  same either way.

## Build notes (maintainers)

### Recipe shape

Two recipes: `flet-libyaml` builds the C library, `recipes/pyyaml` consumes it. The pyyaml half
is eight lines of settings in `meta.yaml` with no patches and no `build.sh`, and the one
non-obvious setting carries its own comment there.

**`flet-libyaml` is `requirements.host`, not `requirements.host_build`, and that is deliberate.**
`host_build` would put it in the cross environment for the link and then not ship it — right on
iOS, where it is statically absorbed, and fatal on Android, where the extension resolves
`libyaml.so` by bare soname at load time. One recipe has to satisfy both, so it is an ordinary
runtime dependency and appears in `Requires-Dist` on both platforms. On iOS that is redundant
rather than harmful, and Flet's cleanup deletes most of the redundant part unprompted.

The two linkage halves behind the platform sections above: on Android `_yaml.*.so` names
`libyaml.so` in `DT_NEEDED` on all three ABIs, carries no `RPATH`/`RUNPATH` and leaves 29
`yaml_*` symbols undefined, while `flet-libyaml`'s `SONAME` is exactly `libyaml.so` and
serious_python's Gradle `copyOpt` task copies every `.so` under a wheel's `opt/` into
`jniLibs/<abi>/` under its plain basename. On iOS all three extensions are `MH_DYLIB` marked
`NOUNDEFS`, define the 54 `_yaml_*` symbols themselves, and name no libyaml in `otool -L`.

The build covers all three Android ABIs, iOS device and both simulator slices, on Python 3.12,
3.13 and 3.14 — nineteen wheels at one build number, those eighteen combinations plus a legacy
32-bit `android_24_x86` slice on 3.12, every one carrying the C extension.

**The dead weight on iOS is fixable here and nowhere else.** `flet-libyaml`'s `build.sh` ends with
`mv $PREFIX/lib/libyaml.dylib $PREFIX/../libyaml.so` on the Apple SDKs, which is what makes
pyyaml's `-lyaml` pick `libyaml.a` instead of the dylib. Moving the dylib out of `opt/lib` is
necessary; leaving it at `$PREFIX/..` — the wheel root — is not, and that is the only reason it
ships and ends up an embedded, code-signed framework in every iOS app. A destination outside the
wheel would achieve the same link behaviour. There is no app-side workaround: a
`cleanup.packages` glob on `libyaml.so` would also delete Android's load-bearing copy, which is
why [iOS](#ios) tells readers not to try.

### Upgrade hazards

**A change here can go green and still be broken.** The one failure this recipe exists to prevent
does not fail the build — it produces a perfectly valid pure-Python wheel, for the reason
`meta.yaml` comments — so the only thing between that and a release is the pair of extension
assertions in `tests/`. Every claim on this page that distinguishes the two implementations
assumes the extension is there.

**The accept/reject divergences and the exception wording are the least protected claims on the
page.** They are properties of libyaml versus PyYAML's own scanner, so a bump of *either* can move
them, and the `problem` strings are upstream's prose in both implementations.

**If iOS ever links libyaml dynamically** instead of absorbing it, the dead-weight paragraph, the
size figures and the `Requires-Dist` reasoning all change together. And a release that added a
`nogil` block would rewrite [Threading](#threading) without failing anything.

### Re-verification checklist

- **The extension's presence in every published wheel.** `unzip -l | grep '\.so$'` is the whole
  check, and the one that matters most.
- **The libyaml version**, in three places: `flet-libyaml`'s Android `opt/lib/libyaml.so`, the
  statically linked iOS extension, and the same-version PyPI desktop wheel — the claim that mobile
  and desktop run the same libyaml rests on those matching, and
  `strings … | grep -E '^0\.[0-9]+\.[0-9]+$'` finds it. The Android pyyaml extension does *not*
  contain the string; it is in the shared library, which is the point.
- **The linkage split.** Android: `DT_NEEDED` still names `libyaml.so`, with no `RPATH`/`RUNPATH`,
  and `flet-libyaml`'s `SONAME` is still exactly `libyaml.so` — the two have to agree or the app
  cannot import. iOS: still `MH_DYLIB` + `NOUNDEFS`, with `otool -L` naming no libyaml. Confirm
  too that the Android ELFs and `libyaml.so` still carry the 16 KB `PT_LOAD` alignment Android 15
  requires.
- **The accept/reject divergences and the exception wording.** Re-run the six divergent documents
  (three tab cases, unknown directive, mid-stream BOM, lone surrogate escape) and the seven
  both-reject documents behind the same-class-same-line-same-column claim.
- **The GIL claim.** Grep the sdist's `yaml/*.pyx` and `yaml/*.pxd` for `nogil`, and the built
  extensions for `PyEval_SaveThread`, `PyEval_RestoreThread`, `PyGILState` and `pthread_create`;
  all are absent today. A symbol grep is worth only as much as its control, so check the behaviour
  too: four threads each parsing a *different* document take the same wall time as the four parses
  run one after another (measured 1.07×, against 3.52× for `hashlib` on the same machine, which
  does release the GIL).
- **That nothing in the package builds a path or reads its own source.** Across the 18 Python
  files there is not one occurrence of `__file__`, `getsource`, `pkgutil`, `pkg_resources`,
  `importlib.resources` or `resource_filename`, and the wheel contains no data files — which is
  what lets it run out of Android's zipped site-packages with no `extract_packages` entry and lets
  `compile.packages` stay on.
- **The byte-identical Python files and the 24-file inventory**, against the desktop wheel of the
  *same* version. A new data file, or a diverging `__init__.py`, would put both the preceding
  check and "upstream's documentation applies" back in question.
- **The measurements.** The speed ratios, the desktop GIL-sharing turns/ms and the size figures
  are all measured. Re-measure; do not scale. The ratios are the transferable part — absolute
  times on a phone are worse than any desktop number quoted, and the desktop ones were taken on a
  machine with other work on it, which is why they are given as ranges.

### Coverage gaps

`tests/test_pyyaml.py` asserts that the `_yaml` extension carries `CParser` and that
`from yaml import CSafeDumper, CSafeLoader` works — exactly the right thing to guard, and why the
silent-pure-wheel failure would turn CI red. It covers presence and nothing else, and two of the
three tests have problems: `test_basic`'s docstring says it round-trips "through PyYAML's C-loader
and C-dumper" while its body calls the pure `yaml.safe_dump`/`yaml.safe_load`, and
`test_c_extension` uses `import _yaml`, the deprecated spelling, which would fail under a
`-W error::DeprecationWarning` runner. Fix the docstring or the body, and prefer
`import yaml._yaml`.

Nothing on device currently checks the two implementations against each other, the divergences, or
the filesystem. Worth adding, in rough order of value: an equality check between `CSafeLoader` and
`SafeLoader` on one document and a byte-equality check between `CSafeDumper` and `SafeDumper` on
another — together those are the drop-in claim, on the device; one of the tab documents, asserting
that `CSafeLoader` accepts what `SafeLoader` rejects, the claim most likely to move under a
libyaml bump; and a `FLET_APP_STORAGE_DATA` round trip.
