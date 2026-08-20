# jiter

[`jiter`](https://github.com/pydantic/jiter) is a standalone build of the JSON parser that
[`pydantic-core`](../pydantic-core) uses. It is written in Rust, its whole API is one parsing
function plus two cache helpers and a float wrapper, and it only reads: there is no serialiser
in the package. What it has that the other JSON parsers do not is **partial parsing** —
`from_json` can decode a document that stops in the middle, which is the shape of an LLM reply
arriving token by token, or of any long response read a chunk at a time.

The import name is `jiter`. Upstream's own advice is to use it directly only if the app does
not already use pydantic, because `pydantic-core` carries the same parser inside it.

## Install

Add jiter to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "jiter",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`partial-json`](examples/partial-json) — replays a JSON document five bytes at a time,
  parses every prefix of it, and times jiter against `json` and `ujson` on the device.

## Usage in a Flet app

```python
import jiter

def on_chunk(buffer):
    """Called with every byte received so far, not just the new ones."""
    try:
        reply = jiter.from_json(buffer, partial_mode="trailing-strings")
    except ValueError:
        return  # too few bytes to be anything yet
    choices = reply.get("choices") or [{}]
    answer.value = choices[0].get("message", {}).get("content", "")
    page.update()
```

Every step of that lookup is defensive on purpose. A partial parse returns the document as
far as it got: keys are absent, arrays are short, and the innermost string may be half a
word. Code that indexes into a partial result the way it indexes into a finished one raises
`KeyError` or `IndexError` long before anything is actually malformed.

### Storage

`from_json` takes bytes, so read files in binary and skip the decode:

```python
data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
settings = jiter.from_json(Path(data_dir, "settings.json").read_bytes())
```

Keep documents the user expects to survive in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
put re-downloadable bodies in
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache),
and use [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for a partial download still being assembled. A JSON file shipped with the app is an asset:
put it in the [assets directory](https://flet.dev/docs/cookbook/assets) and reach it through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

There is no `json.load(fp)` equivalent — no file object, no incremental reader — and writing
is not jiter's job at all, so keep `json.dumps` (or `ujson`/`orjson`) for the save path.

### Threading

A parse holds the GIL from the first byte to the last. Measured on desktop, four threads
each parsing a 1.2 MB payload finish in four times the wall clock of one thread parsing it
once — about 3 ms per parse either way. There is no parallelism to be had, and while a parse
runs, no other Python in the app runs either.

[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) is still
worth using for a large document — it keeps the handler from blocking — but it is not a way to
hide a slow parse. Catch exceptions inside the worker, display them, and end with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

### Partial parsing

[`partial_mode`](https://github.com/pydantic/jiter/tree/main/crates/jiter-python#handling-partial-json)
decides what happens when the bytes run out mid-document. For the input
`b'{"choices": [{"delta": {"content": "Hello wor'`:

| `partial_mode` | Result |
| --- | --- |
| `False` / `'off'` (default) | raises `ValueError: EOF while parsing a string at line 1 column 45` |
| `True` / `'on'` | `{'choices': [{'delta': {}}]}` — the incomplete tail is dropped |
| `'trailing-strings'` | `{'choices': [{'delta': {'content': 'Hello wor'}}]}` |

Three things a walk through the prefixes teaches:

- **A truncated number is not dropped, it is truncated.** Strings get discarded or kept
  according to the mode, but a number is parsed as far as it is valid, in every mode. A
  `1766217600` timestamp arrives as `17`, then `1766217`, then its real value, and nothing in
  the result distinguishes those first two from a finished field. Treat numbers from a partial
  parse as provisional until the document closes.
- **A partial mode is not a promise that nothing raises.** An empty buffer, or one that has
  not yet reached a value, still raises `ValueError: EOF while parsing a value at line 1
  column 0`. The `try` stays.
- **Every call parses from the first byte.** Re-parsing on each chunk costs quadratic work
  over a stream: on desktop, a 41 KB document re-parsed at every 64-byte chunk is 664 parses
  and about 35 ms, against 0.1 ms to parse it once; at 512-byte chunks the same stream costs
  about 4 ms. Re-parse on a cadence the screen can actually show, not on every chunk.

### Speed and memory

On desktop (macOS arm64, CPython 3.12), a 382 KB document took about 1.7 ms with `json`,
1.3 ms with `ujson` and 1.2 ms with `jiter` — a modest win, not a different league, and the
margin narrows further on documents whose strings barely repeat. The gap is wider on small
documents, where fixed per-call cost dominates: a 130-byte chat chunk took about 1 µs with
`json` against 0.3 µs with `jiter`. If a package is being added purely to parse faster,
measure first; the `partial-json` example prints the same comparison from the device.

The `cache_mode` argument is the setting that matters more on a phone. It defaults to `'all'`,
which returns one shared Python string for every repeat of the same text — both keys and
values. On a 1.2 MB document of highly repetitive records, the parsed result retained roughly
4 MB with `'all'`, 6 MB with `'keys'` and 8 MB with `'none'` (desktop, `tracemalloc`), at
indistinguishable speed. Leave it alone unless the document's strings are mostly unique, in
which case the cache is pure overhead. Note that `'keys'` shares only the key strings: repeated
*values* come back as separate objects, which is most of the difference between it and `'all'`.

**Only short strings are cached.** The cutoff is 64 UTF-8 bytes — 64 ASCII characters, or 16
emoji — and at or above it nothing is shared in any mode. Field names, status values and
currency codes fall well inside it; repeated URLs, sentences and base64 blobs do not, so a
document whose repetition is all in long strings gets no dedup whatever `cache_mode` says.

The cache lives in the process, not in the call: `jiter.cache_clear()` releases it after a
one-off parse of something large, and `jiter.cache_usage()` reports how many strings are being
held — a count, despite the type stub describing it as bytes, and a 0 after a big parse is that
length cutoff rather than a broken cache. The compiled functions carry no docstrings and the
mobile wheel ships no stub, so `help()` will not settle it on device.

### App size

Roughly 0.3 MB compressed per architecture. Unpacked, the extension is about 0.6 MB on Android
and 0.7 MB on iOS, and it is very nearly the whole wheel — everything else is a 103-byte
`__init__.py` and a 40 KB SBOM in `dist-info` — so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing. The Android levers of an app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
worth reaching for because of what else is in the app, not because of this.

### Other considerations

A desktop `flet run` uses PyPI's wheel, which is the same Rust code at the same version. The
one difference in the box is that the mobile wheel does not ship `__init__.pyi` or `py.typed`:
editor type checking comes from the desktop install, and nothing at runtime reads either file.
Every timing on this page was measured on desktop; re-measure on a device before designing
around one.

## Things to know

- **`from_json` takes `bytes` and only `bytes`.** A `str` fails with `TypeError: argument
  'json_data': 'str' object is not an instance of 'bytes'`, and so do `bytearray` and
  `memoryview`: a buffer accumulated from a socket needs `bytes(buf)`. Bytes straight off the
  network are the fast path.

- **It parses; it does not write.** There is no `dumps`, so an app that both reads and writes
  JSON keeps a second implementation around anyway. That is the honest cost of adding it.

- **Nesting deeper than about 200 levels raises `ValueError: recursion limit exceeded`,**
  where `json.loads` handled thousands of levels in the same test. It raises rather than
  overflowing the Rust stack, so it is safe — but a deeply nested document needs the standard
  library.

- **Floats can come back exact.** `float_mode='decimal'` returns `Decimal` and
  `float_mode='lossless-float'` returns a `LosslessFloat` holding the original bytes, so
  `123.456789012345678901234567890` survives a round trip that ordinary parsing rounds to
  `123.45678901234568`. Prices and coordinates from someone else's API are the reason to care.

- **Two strictness knobs are off by default.** Duplicate keys silently take the last value
  unless `catch_duplicate_keys=True`, which raises `ValueError: Detected duplicate key "a" at
  line 1 column 14`; and `NaN`/`Infinity` parse into floats unless `allow_inf_nan=False`, just
  as they do in `json.loads`.

- **Every parse failure is a `ValueError` carrying a line and column,** so one `except`
  covers malformed, truncated and duplicate-key input alike, and `str(exc)` is short enough
  to put straight on screen.

## Build notes (maintainers)

### Recipe shape

One maturin/PyO3 crate with no patches and no host requirements: jiter vendors its Rust
dependencies and links against nothing but the interpreter and libc. The cp312 Android
extension's `DT_NEEDED` list is `libpython3.12.so`, `libdl.so`, `libc.so` — no
`libc++_shared`, so unlike [`ujson`](../ujson) next door it needs no `flet-libcpp-shared`. On
iOS it links `Python.framework`, `libiconv` and `libSystem`.

`otool -L` on the iOS extension reports its own install name as a build-tree path that maturin
left behind. The module is a self-contained extension loaded by path, so that name is inert;
it would only matter if another binary linked against it. Do not read it as a relocation bug.

### Upgrade hazards

- Almost everything this page tells an app author is behaviour, not structure: the partial
  modes, truncated numbers, the recursion limit, the bytes-only argument, the string cache.
  All of it lives in Rust and can change in a point release without the build so much as
  blinking, so a green CI run is not evidence that those claims survived.
- The build-side risk is Rust dependency drift on `armeabi-v7a`. It is 32-bit, and a
  transitive crate that reaches for a 64-bit atomic fails there with `E0432: unresolved
  import` on `AtomicU64` while every other slice builds. Check that slice specifically.
- `pydantic-core` vendors this parser too. The two recipes bump independently and can both be
  installed; a fix landing here does not land there.

### Re-verification checklist

- **Partial modes:** re-walk a document prefix by prefix in all three modes and confirm the
  table above, including the truncated-number behaviour and that an empty buffer still raises.
- **Recursion limit:** confirm the depth at which `recursion limit exceeded` appears, and that
  it is still an exception rather than a stack overflow.
- **Argument types:** `str`, `bytearray` and `memoryview` should all still be rejected.
- **Cache semantics:** identical strings still share one object under `cache_mode='all'`, the
  64-byte length cutoff above which nothing is cached still holds, and `cache_usage()` still
  counts strings rather than the bytes its stub claims.
- **Wheel shape:** the extension must keep an ABI-tagged name. The tag is not one pattern —
  today Android cp312 is `jiter.cpython-312.so` while cp313 and cp314 are fully qualified
  (`jiter.cpython-314-aarch64-linux-android.so`), and every iOS slice is
  `jiter.cpython-3XX-iphoneos.so`. What matters is that it never degrades to a bare
  `jiter.so`, which does not import from Android's zipped site-packages. Recheck `DT_NEEDED`
  for a new shared library and `PT_LOAD` alignment (0x4000 today).
- **Size:** re-measure from the wheel rather than scaling these figures.

### Coverage gaps

The device tests cover `from_json` on a mixed-type document and `partial_mode='trailing-strings'`.
They do not exercise the other partial modes, `cache_mode`, `float_mode`, `catch_duplicate_keys`,
the recursion limit, large payloads or the GIL behaviour, and every timing and memory figure on
this page was measured on desktop. The `partial-json` example runs the parser comparison on the
device; nothing else here is a device-side performance claim.
