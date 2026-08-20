# rpds-py

[`rpds-py`](https://github.com/crate-py/rpds) binds the Rust
[`rpds`](https://docs.rs/rpds/) crate: persistent — immutable and structurally shared —
[`HashTrieMap`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap),
[`HashTrieSet`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieSet),
[`List`](https://rpds.readthedocs.io/en/stable/api/#rpds.List),
[`Queue`](https://rpds.readthedocs.io/en/stable/api/#rpds.Queue) and `Stack`. Persistent means
an update returns a new value and the old one keeps working, sharing everything the update did
not touch — so a copy costs a pointer rather than the data. On a phone that is what makes an
undo stack, a snapshot history, or state handed to a background thread affordable.

Import the package as `rpds`. The distribution is named `rpds-py`.

## Install

Add it to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "rpds-py",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`undo-stack`](examples/undo-stack) — edits a 2000-field document, keeps every version, and
  times the sharing against plain dict copies on the device.

## Usage in a Flet app

Keep the current version in one place and let the old ones accumulate in a plain list.
Nothing is copied and nothing has to be undone:

```python
from rpds import HashTrieMap

def main(page: ft.Page):
    history = [HashTrieMap({"title": "Untitled", "body": ""})]
    counter = ft.Text("1 version")

    def on_type(e):
        history.append(history[-1].insert("body", e.control.value))
        counter.value = f"{len(history)} versions"
        page.update()

    page.add(ft.TextField(on_change=on_type), counter)
```

Undo is `history[-2]` and jumping to any earlier state is an index. Reads are
`history[-1]["title"]`, and `dict(...)` converts a version back to a real mapping.

### Storage

Nothing in `rpds` touches the filesystem, and nothing goes into JSON directly:
`json.dumps(document)` raises `TypeError: Object of type HashTrieMap is not JSON
serializable`. Convert first, and write anything the user expects to keep to
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data):

```python
path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "document.json")
with open(path, "w") as handle:
    json.dump(dict(document), handle)
```

Use [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
for anything regenerable and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for scratch files.

**Structural sharing is a memory property and does not survive serialisation.** These
structures do pickle, but each version pickles as its own complete mapping. On a macOS
desktop, 501 versions of a 2000-key document occupied about 1 MB of resident memory, pickled
to a 9 MB blob, and came back from `pickle.loads` occupying 180 MB — the sharing is gone,
because every version is rebuilt independently. Persist a base document plus the edits that
produced each version, and rebuild the history by replaying them.

### Threading

Immutable values need no lock. A version handed to a
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) worker
cannot change underneath it, so the worker can read the whole document while the UI thread
goes on producing new versions — the case that forces a lock or a defensive copy with a
plain `dict`.

What remains shared mutable state is the *variable* holding the current version, and the list
behind it: rebind and append on the UI thread only. End the worker with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which `run_thread`
does not do for you, and catch its exceptions, which it otherwise swallows.

### Sharing, and what it costs to read

Measured on a macOS arm64 desktop with CPython 3.12, as resident-set growth — `sys.getsizeof`
is no use here, because it reports 56 bytes for any `HashTrieMap`. A phone is slower in
absolute terms; the ratios are the point. Keeping every version is cheap, and the cost per
version barely grows with the document:

| Document | One dict copy | One persistent version |
| --- | ---: | ---: |
| 500 keys | ~14 KB, ~2 µs | ~1 KB, ~0.7 µs |
| 2000 keys | ~64 KB, ~6 µs | ~2 KB, ~0.7 µs |
| 8000 keys | ~210 KB, ~23 µs | ~3 KB, ~1.3 µs |

The first version is not free, though: one `HashTrieMap` of 2000 entries occupied roughly
210 KB against roughly 64 KB for the equivalent `dict`. The saving is entirely in the second
and every later version — a thousand of them held under 2 MB, against about 64 MB as copies.

Reads are the other side of the trade. A key lookup costs roughly 80 ns against under 10 ns
for a `dict` — ten to fifteen times dearer — and the map figure barely moves as the map grows,
about 75 ns at ten keys and about 85 ns at a hundred thousand. Bulk operations are dearer
still: at 2000 entries, `list(m.items())` took about 640 µs against 23 µs for a `dict`,
`dict(m)` about 840 µs, and `HashTrieMap(d)` about 200 µs.

So treat it as the store of record, not the thing you iterate: read individual keys freely,
convert to a `dict` once when you need to build a list of controls, and never rebuild that
`dict` on every frame.

### App size

The wheel is approximately 0.3 MB compressed and under 1 MB unpacked per architecture,
nearly all of it the single `rpds` extension. There is no data directory or test suite worth
removing with [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup).

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
app does not need every ABI — a general lever, since this package will not be what makes an
app large.

### Other considerations

A desktop `flet run` uses PyPI's own wheel: the same Rust crate with the same API, so
behaviour matches and the desktop is a fair place to prototype the data model. Timings are
not portable, though. These structures are pointer-chasing over many small allocations, and
the Android emulator's memory subsystem is slow enough that figures taken there say nothing
about a device. Compare against a `dict` on real hardware; the `undo-stack` example measures
both on whatever it is running on.

## Things to know

- **A `HashTrieMap` never compares equal to a `dict`.** `HashTrieMap({"a": 1}) == {"a": 1}`
  is `False` in both directions, with no error and no warning. Compare `dict(m) == other`
  instead. The trap is that `HashTrieSet` *does* compare equal to a builtin `set`, so the
  asymmetry is easy to miss until a test fails.

- **Iteration order is neither insertion order nor stable between runs.**
  `list(HashTrieMap({"b": 2, "a": 1, "c": 3}))` returned a different order on each of five
  consecutive runs, and fixing `PYTHONHASHSEED` does not settle it — the trie is seeded per
  process, integer keys included. Sort the keys before building a list of controls, or the
  same document will render its rows in a different order every time the app starts.

- **`==` and `hash()` walk the whole structure, and nothing is cached.** On a 2000-key map,
  `m == m` took about 195 µs and `hash(m)` about 31 µs on desktop, with no identity fast
  path — so a map used as a `dict` key or a `functools.lru_cache` argument re-hashes on
  every lookup. Key the cache on a version number, and ask "did this change?" with `is`.
  But `is` is never a no-op either, because every operation allocates:
  `m.insert(k, m[k]) is m` is `False`, and so is `m.discard(missing) is m`, so a handler
  wired to `on_blur` will push identical versions onto a history unless it compares first.

- **A mutable value is shared by every version that contains it.** Structural sharing means
  the value object itself is shared, not copied:

  ```python
  v1 = HashTrieMap({"tags": ["a"]})
  v2 = v1.insert("x", 1)
  v2["tags"].append("b")
  list(v1["tags"])            # ['a', 'b'] -- the "old" version changed too
  ```

  Store immutable values, or nest another `HashTrieMap`. Keys must be hashable; values need
  not be, which is exactly what lets this happen.

- **The API is not the `dict` API.**
  [`remove`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap.remove) raises
  `KeyError` where
  [`discard`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap.discard) returns an
  equal map instead; there is no `|` merge operator (`m | other` raises `TypeError`), so use
  [`update`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap.update); and
  `rpds.List` has no `__getitem__` at all — `first`, `rest`, `push_front` and `drop_first`
  only. For a history you can jump around in, keep the versions in a plain Python list.

- **There is no `rpds.__version__`.** The number lives only in the distribution metadata,
  under the distribution name rather than the module name:
  `importlib.metadata.version("rpds-py")`.

## Build notes (maintainers)

### Recipe shape

A stock PyO3/maturin recipe: name, version and build number, plus the target sysconfigdata pin
every Rust recipe here carries. No patches, no host requirements, no excluded architectures —
`armeabi-v7a` builds, so nothing in the crate tree needs 64-bit atomics. The wheel is one
extension plus a five-line `__init__.py` re-exporting from it — with a type stub and an SBOM
alongside, neither of which is imported — which is why there is no packaging behaviour to work
around on either platform.

### Upgrade hazards

- Upstream releases are CalVer, so a version jump carries no semver promise. The sections
  above make several behavioural claims that a release is free to change.
- The distribution's own floor is Python 3.11. The example's `requires-python` has to track
  it, or `uv` fails to resolve the lowest split at build time.
- PyO3 and maturin bumps are where this kind of recipe breaks — a new PyO3 raising its
  minimum CPython, or changing how the extension is named or how it reads the interpreter's
  configuration.
- If a future release pulls in a crate that uses `AtomicU64`, `armeabi-v7a` is the slice that
  fails first — check it builds before assuming the 32-bit slice is safe. The fix is
  `package.excluded_arches` or a `portable_atomic` patch.

### Re-verification checklist

- **Module surface:** confirm `rpds/__init__.py` still re-exports from the extension and
  `__all__` still names the five types; a pure-Python facade would change what to test.
- **The behavioural claims:** dict inequality, iteration order, uncached `==` and `hash`,
  allocating on a no-op `insert`, `List` without `__getitem__` — each is a sentence on this
  page, and each is upstream behaviour the recipe does not control.
- **The measurements:** re-measure rather than scale them; they are the whole reason to
  choose this over a `dict`. Take memory from resident-set growth in a *fresh process* —
  reusing one lets the allocator hand back freed pages and reports near zero — and time
  lookups with several subscripts per loop iteration, because subtracting an empty loop
  over-corrects enough to halve the dict figure.
- **Android package layout:** test from zipped site-packages. Nothing here reads a file at
  runtime, so `extract_packages` should stay unnecessary; add it only with a failure symptom.

### Coverage gaps

The device tests cover `HashTrieMap` and `HashTrieSet` — insert, get, remove, and that an
earlier version is unaffected. They do not exercise `List`, `Queue`, `Stack`, pickling, hashing,
equality, or any of the memory behaviour that is the reason to use the package. The
`undo-stack` example is the only thing that measures sharing on a device, and CI does not run
it. Every figure on this page was measured on a macOS desktop, not on a phone.
