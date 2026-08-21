# lru-dict

[`lru-dict`](https://github.com/amitdev/lru-dict) is a fixed-size dictionary written in C. It
behaves like a `dict` until it is full, then discards the least recently used entry to make room
for the next one, and can call you back with whatever it discarded. In a Flet app it is the
bounded store for results that are expensive to produce and too large to keep all of: decoded
images, map tiles, rendered pages, parsed responses.

Import the package as `lru`; the class is `LRU`.

## Install

Add lru-dict to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "lru-dict",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`tile-cache`](examples/tile-cache) — caches rendered map tiles, shows eviction happening as
  you pan, and times the LRU against the two standard-library alternatives on the device.

## Usage in a Flet app

A cache is a `get`, a compute and a store, and the eviction happens inside the store:

```python
from lru import LRU

tiles = LRU(64)  # holds 64 entries; the 65th insert drops the coldest one

def tile(key):
    png = tiles.get(key)  # a hit, and the entry becomes the most recent
    if png is None:
        png = render(key)  # a miss: produce it and hand it over
        tiles[key] = png
    return png

view = ft.Image(src=tile((0, 3, 4)), gapless_playback=True)
```

Keys are any hashable object, so a tuple of coordinates works directly. Values are ordinary
references — [`ft.Image`](https://flet.dev/docs/controls/image/) takes `bytes` for `src`, so
encoded image bytes can go straight from the cache into a control.

### Storage

An LRU lives in memory and starts empty at every launch. When entries are expensive enough to
be worth keeping across launches, write them to
[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
as you produce them and let the LRU be the fast tier in front of that directory:

```python
def tile(key):
    png = tiles.get(key)
    if png is None:
        path = os.path.join(os.getenv("FLET_APP_STORAGE_CACHE", "."), name(key))
        png = open(path, "rb").read() if os.path.exists(path) else render_and_save(key, path)
        tiles[key] = png
    return png
```

Do the disk write on the way in, not in the eviction callback: the callback runs inside the
assignment that overflowed the cache, so a file write there puts I/O in the middle of a fast
path and an exception there behaves badly (see **Things to know**).

### Threading

Produce cache misses in [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
so the UI thread is not blocked by whatever the miss costs, and finish the worker with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

A cache with **no** eviction callback takes concurrency well: eight threads doing twenty
thousand interleaved inserts and reads each left capacity respected and `keys()` consistent,
because each operation is one C call under the GIL. A callback ends that — it is Python, and it
runs inside the insert before the new entry is linked in, so the cache is half-built for as
long as it takes. One writer and two readers for five seconds on desktop had the readers find
it over its own capacity in four samples out of five, and `keys()` sampled there comes back
with holes that kill the process when read (see **Things to know**). Give a cache with a
callback one writer, or a `threading.Lock` around every access.

A sequence is not protected either way: between your `get` returning `None` and your insert,
another thread can insert the same key and its eviction can drop something you were counting
on. If more than one worker writes to the same cache, hold a `threading.Lock` across the whole
read-compute-insert.

### Choosing between this and the standard library

Python already ships two least-recently-used caches, and they are not interchangeable:

| Use | When |
| --- | --- |
| [`functools.lru_cache`](https://docs.python.org/3/library/functools.html#functools.lru_cache) | The value is a function of hashable arguments and you never need to put an entry in, take one out, or look at what is resident. |
| [`OrderedDict`](https://docs.python.org/3/library/collections.html#collections.OrderedDict.move_to_end) with `move_to_end` and `popitem(last=False)` | You want a custom policy — weighting entries by cost, expiring by age, evicting more than one at a time. |
| `lru.LRU` | You have the values in hand already, and you want the bound and the eviction hook without writing them. |

Speed is not the deciding factor. On a laptop (macOS, CPython 3.12) a hit costs tens of
nanoseconds through all three and an insert that evicts costs under a hundred. Read the
magnitude and not the ranking: timing the same three under `timeit` rather than an interleaved
loop moves every figure and reverses the middle two. Twenty nanoseconds a thousand times per
frame is twenty microseconds, nothing next to a 16 ms frame. The example app runs the comparison
on the device, which is the only place it can actually be settled for your hardware.

One gap that does hold up is inside `LRU` itself: `LRU.get(key)` costs two to three times
`LRU[key]`, because it is a method call rather than a slot. Write `get()` anyway — it is the
form that tolerates a miss, and the difference is nanoseconds against whatever the miss costs.

What is not a matter of nanoseconds is that `functools.lru_cache` will only ever hold what its
own function returned. It cannot be given a value you decoded elsewhere, cannot drop one entry,
and cannot tell you what it is holding.

### Memory

Capacity is a count of entries, not a byte budget, and it must be at least 1. That is fine while
entries are the same size and misleading when they are not — sixty-four thumbnails and
sixty-four full-resolution frames are the same `LRU(64)` and two very different amounts of RAM.

`sys.getsizeof` will not help: it reports 72 bytes for an `LRU` whether it is empty or holds ten
thousand entries, because the type does not account for its own table. Measure the values
instead. Under `tracemalloc` on desktop the container itself costs 80–100 bytes an entry, of
which exactly 48 is the C node an `LRU` adds on top of what the same entry would cost in a plain
`dict` — real, and irrelevant beside anything worth caching.

For values of uneven size, keep a running byte total in the eviction callback and shrink the
cache with `set_size()` when it grows too large — but call `set_size()` from your own code,
after the assignment has returned, never from inside the callback:

```python
def evicted(key, value):
    global resident
    resident -= len(value)  # accounting only; see Things to know

cache[key] = value
resident += len(value)
while resident > BUDGET and len(cache) > 1:
    cache.set_size(len(cache) - 1)  # each step drops one and calls back
cache.set_size(max(len(cache), FLOOR))  # let it refill when entries are small
```

`set_size()` evicts from the cold end immediately and every entry it drops goes through the
callback, so a total kept this way stays exact.

### App size

The wheel is approximately 10–11 KB compressed and 20–80 KB unpacked per architecture — one
small extension module and the three-line package that re-exports it. There is nothing worth
removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup), and no reason
to narrow [`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
on its account. The memory a cache occupies at runtime is set entirely by what you put in it.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, which is the same source and the same API. The
difference is the machine: a capacity that never evicts on a laptop can be a permanent eviction
storm on a phone, where the hit rate collapses and every frame pays full price. Size the cache
against the device, watch `get_stats()` there rather than under `flet run`, and prefer a byte
total over an entry count when the entries vary.

## Things to know

- **An eviction callback that raises does not raise where you would expect.** lru-dict discards
  the callback's result without checking it, so the assignment that triggered the eviction
  returns normally and the exception stays pending until the next line trips over it. What that
  line reports varies with the interpreter and with whichever C call it happens to make first:
  sometimes the callback's own `ValueError`, more often on 3.13 and 3.14 a `SystemError: …
  returned a result with an exception set` naming something unrelated — a stdout write, `len`,
  the next `LRU(...)` — with the real exception chained beneath as its direct cause. Wrap the
  body of the callback in `try`/`except` and keep it short.

- **The callback must not read the cache it is evicting from.** It runs mid-insert, before the
  new entry is linked into the recency list, and `keys()`, `values()` and `items()` called from
  in there return a list with holes: reading one element segfaults the process, with no
  traceback and nothing in the log. `len()` (capacity + 1 for the duration), `get()`, `in` and
  the peeks are safe there — but the key and value it is handed are all it should need.

- **It must not write to that cache either, and `set_size()` from in there hangs the app.**
  Inserting from the callback quietly defeats the bound: an `LRU(3)` driven that way finished
  holding twenty entries. `clear()` leaves a pending `KeyError` that lands on some unrelated
  later line, because the entry being evicted leaves the table only after the callback returns.
  `set_size()` is the worst of the three — the C loop that drops entries re-enters itself and
  never converges, and since no bytecode runs inside that loop the spin cannot be interrupted:
  neither `KeyboardInterrupt` nor a `SIGALRM` is ever delivered, and on a device the app simply
  stops. Do the accounting in the callback and any resizing after the assignment returns.

- **The callback is an eviction hook, not a removal hook.** It fires when an insert overflows
  capacity and for every entry dropped by `set_size()`. It does not fire for `clear()`, `pop()`,
  `popitem()`, `del cache[key]`, or overwriting a key that is already present. Byte accounting
  or resource release built on the callback alone silently drifts as soon as the code deletes
  anything; adjust at the deletion too.

- **An `LRU` is not iterable.** `for key in cache` raises
  `TypeError: '_lru.LRU' object is not iterable`. Use `keys()`, `values()` or `items()`, which
  return ordinary lists ordered most recently used first, and which do not count as a use.

- **Membership does not refresh recency; `get()` does.** `key in cache`, `has_key()`,
  `peek_first_item()` and `peek_last_item()` leave the order untouched, while `cache[key]` and
  `cache.get(key)` move the entry to the front and count into `get_stats()`. So
  `if key in cache: value = cache[key]` is still correct — the subscript does the refreshing —
  but a membership test on its own will not keep an entry alive.

- **`peek_last_item()` is the entry that goes next**, `peek_first_item()` the most recently used
  one, and both return `None` on an empty cache. `get()` also returns `None` for a key that is
  not resident, so a cache whose values may legitimately be `None` needs a sentinel:
  `cache.get(key, MISSING)`.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version and a build number, and that is the whole recipe: one C source
file built by setuptools, no patches, no requirements of our own. The wheel ships a `lru/`
package with the extension at `lru/_lru` rather than a top-level extension module, and that is
what serious-python stages. Upstream builds its own iOS and Android wheels with cibuildwheel,
but the platform matrix is in `.github/workflows/build-and-deploy.yml`, not in the
`[tool.cibuildwheel]` block of the `pyproject.toml` this recipe builds from — that block only
carries test settings. `CIBW_ARCHS_ANDROID` there is `x86_64 arm64_v8a`, which is why PyPI has
no 32-bit Android wheel.

### Upgrade hazards

Those upstream wheels make the version in `meta.yaml` load-bearing in a way it was not before.
pip ranks candidates by version before it considers platform tags or build tags, so a newer
release on PyPI outranks anything this index holds at an older version, and an app silently
moves to a wheel set with no `armeabi-v7a` and no cp312. At an equal version the wheels here
still win — Android on the higher `android_24` platform tag, iOS on the build tag, the platform
tags there being identical. Keep this recipe at or ahead of PyPI's version.

The sdist pins its own backend (`setuptools==80.9.0` in `build-system.requires`). A pin the
cross-build environment cannot satisfy is the likeliest way a bump stops being a one-line change.

### Re-verification checklist

- **Callback contract:** re-check that a raising callback still leaves a pending exception
  rather than propagating at the assignment, that `clear()`, `pop()`, `del` and overwrite still
  bypass the callback, and that the callback still runs before the new entry is linked in — the
  segfault and the over-capacity window both follow from that ordering, and a fix upstream would
  make two consumer warnings above wrong rather than merely cautious. Re-check the write side
  too: `set_size()` from inside the callback should still be verified to spin, since
  `LRU_set_size` assigning `self->size` only after its drain loop is what makes it non-convergent.
  The exact symptom of the pending exception is interpreter-specific, so re-derive it per
  Python version rather than copying the one in **Things to know**.
- **Recency and stats contract:** `keys()` ordered most recent first, `get()` and `[]` counting
  into `get_stats()`, membership and the peeks not counting, `set_size()` evicting through the
  callback.
- **Iteration:** whether `__iter__` has appeared. The "not iterable" note is a claim about the
  current C type, not about the API being frozen.
- **Extension layout:** confirm the wheel still contains `lru/__init__.py` plus `lru/_lru`, and
  that nothing at runtime reads a file out of the package.
- **PyPI overlap:** list which mobile wheels PyPI carries at the new version, and make sure this
  recipe is not behind it.
- **Size:** re-measure compressed and unpacked from the built wheels rather than scaling these
  figures.

### Coverage gaps

The device test covers import, insertion, a recency touch and one capacity eviction with the
resulting key order. It does not exercise the eviction callback, `set_size()`, `get_stats()`,
the peeks, or concurrent access. The comparison against `functools.lru_cache` and `OrderedDict`
in **Usage** was measured on a laptop; the example app is what runs it on a device, and its
numbers are the ones to trust for a phone.
