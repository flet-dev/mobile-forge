# ruamel.yaml.clib

[`ruamel.yaml.clib`](https://yaml.dev/doc/ruamel.yaml.clib/) is the compiled reader, parser
and emitter behind [`ruamel.yaml`](https://yaml.dev/doc/ruamel.yaml/): libyaml's C code with
a Cython wrapper, installed as one extension module named `_ruamel_yaml`. Every call you
write still goes through `ruamel.yaml`, which binds that module's `CParser` and `CEmitter`
when it is present.

So the real decision is which YAML library the app uses: `ruamel.yaml`, which is pure Python
and comes from PyPI, or [`pyyaml`](../pyyaml), which carries its own accelerator. Add this
wheel once `ruamel.yaml` is the answer and the app parses enough YAML on device for the
difference to show — on desktop, a 160 KB document loaded through `YAML(typ="safe")` in
55 ms with the compiled parser and 275 ms without it.

## Install

```toml
dependencies = [
    "flet",
    "ruamel.yaml",
    "ruamel.yaml.clib",
]
```

**Name the accelerator yourself.** `ruamel.yaml` 0.19.1 reaches the compiled parser only
through an extra, upstream having pointed the default at a newer accelerator that supports
free-threaded CPython. A bare `ruamel.yaml` therefore resolves to one file — the pure-Python
wheel — and the app builds, runs, parses correctly and never mentions that it is doing so in
Python. Naming both requirements, as above, is what makes the compiled wheel arrive.

Reach for an extra instead and the name decides what you get. `ruamel.yaml[oldlibyaml]` means
this package and resolves to 0.19.1 plus the compiled wheel. The adjacent-looking
`ruamel.yaml[libyaml]` means a different accelerator distribution which publishes source only,
so the resolver walks back to `ruamel.yaml` 0.18.17 — the last release that required this
package outright — and takes the compiled wheel from there. The only sign is a build-log
warning that the version it settled on *does not provide the extra 'libyaml'*. Two plain
requirements do not depend on which name is current.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`yaml-speed`](examples/yaml-speed) — times the compiled parser and emitter against the
  pure-Python ones and shows what the fast path discards.

## Usage in a Flet app

Nothing in the code changes. Ask for a loader that has a compiled implementation and you get
it:

```python
from ruamel.yaml import YAML

yaml = YAML(typ="safe")
config = yaml.load(text)
```

[`load`](https://yaml.dev/doc/ruamel.yaml/basicuse/) accepts a `pathlib.Path`, an open
stream, or a `str` or `bytes` holding the document itself;
[`dump(data, target)`](https://yaml.dev/doc/ruamel.yaml/api/) takes the same kinds of target
and writes YAML to it.

### Storage

Configuration the user edits or the app rewrites belongs in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
config_path = Path(os.getenv("FLET_APP_STORAGE_DATA", ".")) / "settings.yaml"
yaml.dump(settings, config_path)
```

YAML shipped with the application is an asset: put it in the
[assets directory](https://flet.dev/docs/cookbook/assets) and reach it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).
Anything parsed once and reduced to a faster form belongs in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache):
at the sizes where this wheel matters, the fastest parse is the one that does not run.

### Threading

At document sizes worth accelerating, a parse is long enough to be visible. Move it into
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
spinner, catch exceptions inside the worker because `run_thread` swallows them, and end with
an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Threads will not make it finish sooner. The extension holds the GIL for the whole parse: two
parses run concurrently in two threads took the same wall time as running them one after the
other — a 0.93x speedup on desktop, where the same harness measured 1.81x for a
`zlib.compress` control. Use a thread to keep the UI responsive, not to add throughput, and
give each worker its own `YAML` instance: the object carries per-load state, and one costs
about 37 µs.

### Which loader you actually get

Only some of them reach the C code. These are the classes each instance holds:

| Constructed as | Parser | Emitter |
| --- | --- | --- |
| `YAML()`, `YAML(typ="rt")` | `RoundTripParser` | `RoundTripEmitter` |
| `YAML(typ="safe")` | `CParser` | `CEmitter` |
| `YAML(typ="unsafe")` | `CParser` | `CEmitter` |
| `YAML(typ="base")` | `CParser` | `Emitter` |
| `YAML(typ="full")` — dumping only | `CParser` | `CEmitter` |
| `"safe"`, `"unsafe"`, `"base"` or `"full"` with `pure=True` | `Parser` | `Emitter` |

`typ="safe"` is the one to reach for, and it is a different answer as well as a faster one:
its constructor returns plain `dict`, `list`, `int`, `float`, `str`, `bool`, `date` and
`datetime` values, so re-emitting drops the comments and the block layout and sorts the keys.
The emitter is compiled too and gains less — re-emitting that 160 KB document took 65 ms
against 190 ms. `typ="base"` returns every scalar as a `str`; `typ="unsafe"` also constructs
Python-specific tags such as `!!python/tuple`, which is only safe on input you produced
yourself; and `typ="full"` holds the compiled classes but is refused a loader outright, so
`YAML(typ="full").load(text)` raises
`YAMLError: you can only use yaml=YAML(typ='full') for dumping`.

Assert at startup that the instance you are about to use really is the compiled one:

```python
from ruamel.yaml import YAML
from ruamel.yaml.parser import Parser

accelerated = YAML(typ="safe").Parser is not Parser
```

`ruamel.yaml` wraps its `import _ruamel_yaml` in a bare `except` and falls back to the
pure-Python parser, so a build that failed to pick up the wheel produces an app that still
parses nearly everything, is five times slower, and says nothing. Compare the class on the
instance rather than testing some import: it answers for the object about to be used, stays
correct when a caller passed `pure=True`, and stays correct if something else in the tree
drags in the rival `ruamel.yaml.clibz`, which this code path never consults.

### App size

The wheel runs 118–149 KB compressed and 226–416 KB unpacked, one architecture and one Python
version each: a single extension module and its metadata. The Python half of the pair is the
larger one — `ruamel.yaml` is 541 KB of source, which reaches the device as 630 KB of
bytecode, because `compile.packages` is on by default and modules ship as `.pyc`. Budget about
a megabyte for the two together: 0.95 MB on Android arm64, 1.04 MB on iOS arm64. Narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) or
using an app bundle is not worth doing for this package alone, though the wheel is
per-architecture and follows along where the app already does it for a larger dependency.

### Other considerations

A desktop `flet run` installs PyPI's own build of the same C sources, and the libyaml `0.1.7`
string `get_version_string()` reports there is embedded in all eighteen mobile binaries too,
so most of what the app does with YAML on a laptop is what it will do on a phone. Malformed
documents, duplicate keys, tab indentation, undirected YAML 1.1-style octals, underscored
integers, bare dates, merge keys, anchors and `!!binary` all came back identical from the two
implementations, value and `YAMLError` subclass alike; the documents that did not are under
*Things to know*. Timing is what does not carry over: every millisecond on this page was
measured on a desktop machine, so run the example on hardware for the numbers your users will
see.

## Things to know

- **The round-trip loader is never accelerated.** Plain `YAML()` is `RoundTripParser`, and the
  extension exports `CParser` and `CEmitter` and nothing round-trip-shaped. If comment- and
  order-preserving editing is why the app uses `ruamel.yaml`, this wheel does not make that
  faster: the same 160 KB document that `typ="safe"` loaded in 55 ms took 390 ms through
  `YAML()`.

- **The two implementations do not accept quite the same language.** A tab used as a
  separator — `key:\tvalue`, or a trailing tab after a value — loads through `CParser` and
  raises `ScannerError` in pure Python. And a `%YAML 1.1` directive switches the pure loader
  to YAML 1.1 resolution while the compiled one ignores it: under that directive `a: 0755` is
  `755` through C and `493` through Python, and `a: yes` is the string `'yes'` through C and
  `True` through Python. Both held on `ruamel.yaml` 0.18.17 and 0.19.1 and on Python 3.12 and
  3.13. So the silent fallback above is not only slower: a document the app parsed all through
  testing can start raising once the wheel goes missing.

- **A lone surrogate breaks the compiled emitter.** Dumping a `str` that carries one — which
  is what `os.fsdecode` and `bytes.decode(..., "surrogateescape")` return for a device
  filename that is not valid UTF-8 — makes `CEmitter` raise `UnicodeEncodeError: 'utf-8' codec
  can't encode character '\udce9' ... surrogates not allowed`, where the pure emitter writes
  `"caf\uDCE9.yaml"` and carries on. `UnicodeEncodeError` is not a `YAMLError`, so an
  `except YAMLError` around the dump does not catch it: catch `UnicodeError` too, or sanitise
  device-derived strings first. Loading diverges the same way, with `ScannerError: found
  invalid Unicode character escape code` for a `"\uD800"` the pure reader accepts.

- **A `str` handed to `load` is the document, not a filename.** `yaml.load("config.yaml")`
  returns the string `'config.yaml'` — a valid YAML scalar — rather than reading the file and
  rather than raising. Pass a `pathlib.Path` when you mean a path.

- **`_ruamel_yaml` cannot be imported on its own.** Its module initialisation imports twelve
  `ruamel.yaml` modules for the exception, token, event and node classes it uses, so with
  `ruamel.yaml` absent it fails with `ModuleNotFoundError: No module named 'ruamel'`, raised
  from `init ruamel.yaml.clib._ruamel_yaml`. The two go in together.

- **`get_version_string()` reports libyaml, not this package.** It returns `0.1.7`, the
  libyaml generation the C sources derive from, and will keep returning it across version
  bumps. For the accelerator's own version, read the distribution metadata.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version and a build number, and that is the whole recipe. The sdist
ships libyaml's C sources and the Cython-generated `_ruamel_yaml.c` alongside them, so there
is nothing to fetch, nothing external to link against and nothing to patch — forge's default
Python build path produces the extension directly. That is also why there is no `flet-lib*`
companion, unlike the sibling `pyyaml` recipe and its `flet-libyaml`.

### Upgrade hazards

Whether this wheel is reachable at all depends on one import in the *other* package.
`ruamel/yaml/main.py` binds `CParser` and `CEmitter` from `_ruamel_yaml` and from nowhere
else, and that is what every `YAML(...)` instance selects from. The rival `_ruamel_yaml_clibz`
is known only to `cyaml.py`, which learned about it in 0.18.17 preferring it and flipped to
preferring `_ruamel_yaml` in 0.19.1 — all that churn while `main.py` stayed put. Re-read that
import at every `ruamel.yaml` release before repeating any claim on this page; if it ever
changes, most of this page changes with it.

Upstream's `setup.py` also has branches that return no extensions at all — a `--plat-name`
argument containing `win`, a `--version` invocation, Jython. Nothing forge does reaches them
today, but a build can therefore succeed and produce a wheel with no extension in it: treat
the archive contents as the evidence, not the exit status.

### Re-verification checklist

- **The extension is in the wheel:** confirm each slice contains a top-level
  `_ruamel_yaml.cpython-3XX*.so` with the right ABI tag for its leg, and that the file is not
  a stub.
- **Android binaries:** every `PT_LOAD` aligned to 16 KB (currently `0x4000` on all three
  ABIs), and `DT_NEEDED` limited to platform libraries — `libm`, `libpython3.X`, `libdl`,
  `libc`.
- **iOS binaries:** all three slices `MH_DYLIB`.
- **No GIL release:** the threading advice rests on `PyEval_SaveThread` and friends being
  absent from the symbol table and `nogil` appearing nowhere in `_ruamel_yaml.pyx`.
- **The consumer check still holds:** `YAML(typ="safe").Parser is not
  ruamel.yaml.parser.Parser` on device, and the `typ` table above re-derived by reading
  `.Parser` and `.Emitter` off fresh instances rather than from upstream docs. `typ="full"` is
  dump-only because `load` tests `self.typ` and raises, not because of what it holds.
- **The divergences:** re-run a lone surrogate, a tab separator and a `%YAML 1.1` document
  through both implementations. Those were the three differences a 27-document sweep found; a
  libyaml generation bump could remove them or add others.
- **Ratios and size:** re-measure load and dump on hardware, and compressed and unpacked
  bytes from the built wheels. Neither survives a bump of either package unexamined.

### Coverage gaps

`tests/` asserts only that `find_spec("_ruamel_yaml")` locates a compiled extension; it never
imports it, since importing needs `ruamel.yaml`, which the recipe-tester does not install, so
no device test has loaded a document through the C parser. Adding `ruamel.yaml` to
`test.requires` in `meta.yaml` would put the identity check and a real round trip on device;
until then the example app is the only evidence that the wheel works rather than merely ships.
