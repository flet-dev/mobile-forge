# LRU tile cache

A 5×5 map of Mandelbrot tiles, nine of them on screen, each one rendered in pure Python so a
miss costs real milliseconds. [`lru-dict`](https://github.com/amitdev/lru-dict) holds the
rendered PNGs. Pan and the counters move: hits, misses, how many tiles have been evicted, how
many kilobytes are resident, and which tile goes next. Change the capacity and watch the same
gesture become cheap or ruinous. A second button times the LRU against the two standard-library
caches on the device you are holding.

What it demonstrates:

- **A bounded cache of values you already have** — `LRU(n)` stores what
  [`render_tile`](src/tiles.py) produced, and the `n+1`th insert drops the coldest entry with no
  bookkeeping from the app. That is the thing
  [`functools.lru_cache`](https://docs.python.org/3/library/functools.html#functools.lru_cache)
  cannot do: it only ever holds what its own decorated function returned.
- **Eviction as an event** — the cache is built with a callback, which fires with the key and
  value being discarded, both when an insert overflows and when the capacity buttons shrink it
  through `set_size()`. That is what turns a bound on entries into the running kilobyte total in
  the table. It does not fire for `clear()`, `pop()` or an overwrite, so accounting built only
  on it drifts the moment the app deletes something.
- **Working set versus capacity** — nine tiles are on screen. At capacity 24 a pan keeps six of
  them whichever way you go; at 4 every frame evicts tiles it is about to ask for again and the
  hit count sits at zero. Capacity 9 is the one to sit on: it fits the nine exactly, yet panning
  right or down keeps six while panning left or up keeps **none** — the redraw reads the grid in
  the order the cache aged it, so the first miss evicts the tile the next fetch wants and that
  cascades. A cache the size of the working set is not a cache that fits it.
- **The key decides what a gesture costs** — zoom is part of the tile key, so a zoom step
  normally lands on keys nothing has seen and costs nine renders. The exception is a round
  trip: halving the indices is the exact inverse of doubling them, so at capacity 24, where
  both levels stay resident, zooming out and straight back in is nine hits and nine hits. At
  9 or 4 the level you left has already been evicted and every leg costs nine renders again.
- **Rendering off the UI thread** — misses run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  pad disabled and a spinner up, and the worker ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Tiles are PNG `bytes` handed straight to
  [`ft.Image.src`](https://flet.dev/docs/controls/image/#flet.Image.src) with
  [`gapless_playback`](https://flet.dev/docs/controls/image/#flet.Image.gapless_playback) on, so
  a redraw does not blank the map.

Press **Time three caches** and the interesting result is how boring it is: a hit through the C
LRU, through `lru_cache`, and through an `OrderedDict` with
[`move_to_end`](https://docs.python.org/3/library/collections.html#collections.OrderedDict.move_to_end)
land within tens of nanoseconds of each other, while one missed tile above them costs hundreds
of thousands of times more. The cache you pick is not what makes the app fast; the hit rate is,
and the hit rate is set by the capacity next to the working set.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
