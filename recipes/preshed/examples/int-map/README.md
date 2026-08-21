# preshed int map

Twenty-five thousand synthetic tokens — or two hundred thousand — are folded down to 64-bit
keys and indexed twice: once in a [`PreshMap`](https://github.com/explosion/preshed/blob/master/preshed/maps.pyx),
once in a plain `dict`. The table prices the two against each other: bytes held, nanoseconds
per lookup, milliseconds to tally a stream of occurrences. The field at the bottom hashes
whatever you type and shows the key it produces and where that key lands.

What it demonstrates:

- **A key is a `uint64`, so text has to be hashed first** — the map stores the integer and
  never sees the string.
  [`hashlib.blake2b`](https://docs.python.org/3/library/hashlib.html) with `digest_size=8` is
  the portable way to make one; the builtin `hash()` is salted per process, so an index keyed
  with it would stop matching after a restart. Keys `0` and `1` are preshed's own empty and
  deleted markers, so the two digests that would collide with them are nudged clear.
- **The memory column is the whole reason the package exists** — a `dict` allocates an `int`
  object for every key and every value, while a preshed cell is a `uint64` next to a
  pointer-sized value: 16 bytes flat, on 32-bit `armeabi-v7a` as much as on `arm64-v8a`,
  because there the key's alignment pads the half-width pointer straight back.
  `sys.getsizeof` on the dict reports only the hash table, which is the smaller half, so
  `vocab.dict_bytes` adds up the boxed integers as well. The ratio holds at 2.8× across all
  three sizes.
- **Counting is a second table** —
  [`PreshCounter.inc`](https://github.com/explosion/preshed/blob/master/preshed/counter.pyx)
  reads and writes a cell in one call, where `tally[key] += 1` is two dict operations and a
  fresh `int` object. The stream is deliberately skewed: every token appears once and the
  hottest 1% appear a hundred times more, which is why a word from the head of the vocabulary
  comes back as `101`.
- **Compute off the UI thread** — building 200,000 entries runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/) disabled and a spinner
  up. The worker body is wrapped end to end, because `run_thread` swallows an exception and the
  size buttons would otherwise stay greyed out with no clue why, and it finishes with the
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs.

The lookup column is the one that does not go preshed's way: at every size the plain `dict`
reads faster, because both pay the same interpreter overhead and dict's is the more tuned C
lookup underneath. What the table is really selling is the row above it — the same index for a
third of the memory — and the row below it, where `inc()` wins because it does in one call what
a `Counter` does in three steps.

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
