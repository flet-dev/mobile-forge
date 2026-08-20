# rpds undo stack

A 2002-key document, edited one field at a time, with every version it has ever had kept
alive at once. Type a title, fire off a burst of random field edits, then step back with
undo or drag the timeline slider anywhere in the history and watch the old values return.
Nothing is restored and no edit log is replayed — each version is a separate
[`HashTrieMap`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap) that still
exists. The Compare button times both ways of keeping a history, on the device you are
holding.

What it demonstrates:

- **A snapshot that does not copy the document** —
  [`insert`](https://rpds.readthedocs.io/en/stable/api/#rpds.HashTrieMap.insert) returns a
  new map that shares every untouched node with the old one, rebuilding only the path from
  the root to the changed key. Measured on a macOS desktop that is one to three kilobytes
  per version against a plain dict's 64 KB, and it barely moves as the document grows.
- **Random access to any past state** — the timeline is an index into a plain Python list of
  versions, so it runs on
  [`on_change`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change) rather than
  `on_change_end`: scrubbing costs a list index and two key reads.
  [`rpds.List`](https://rpds.readthedocs.io/en/stable/api/#rpds.List) is the tempting home
  for a history and the wrong one, because it has no `__getitem__` at all — only `first`,
  `rest`, `push_front` and `drop_first`.
- **What reads cost** — the table puts a `HashTrieMap` lookup next to a `dict` lookup, timed
  on the device; expect ten to fifteen times the builtin. The timing loop itself
  costs more per iteration than a dict lookup does, so the timer repeats the subscript ten
  times per iteration rather than subtracting an empty loop, which over-corrects badly.
- **What Python cannot tell you** — `sys.getsizeof` reports 56 bytes for the map whether it
  holds two entries or two hundred thousand, because the entries are Rust allocations the
  interpreter never sees. The dict column of that row is real; the map column is the
  wrapper object and nothing else.
- **Compute off the UI thread** — the comparison runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, ending in the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. No lock is involved: the worker reads versions the UI thread cannot mutate,
  because nothing in `rpds` mutates anything.

Press the burst button a few times and the interesting thing is what does *not* happen. Two
hundred versions of a two-thousand-field document is a few hundred kilobytes of history, the
timeline still scrubs instantly, and the last row of the table prices the same history kept
as dict copies at around 10 MB.

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
