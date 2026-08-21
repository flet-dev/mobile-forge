# cymem pool lifetime

Thousands of small memory blocks are allocated twice over: once tied to a single
[`cymem`](https://github.com/explosion/cymem) `Pool`, once as an ordinary list of
`bytearray`s. The app throws away half of its own references to each set and reports how
many bytes are still held. The `bytearray` list gives back half its memory. The pool gives
back almost nothing — then gives back everything at once, the moment the pool object itself
goes away. Pick the block size and the count, and the whole table is recomputed on device.

What it demonstrates:

- **When a pool's memory is actually returned** — cymem exists to tie C allocations to a
  Python object's life-cycle, which upstream's
  [overview](https://github.com/explosion/cymem#overview) describes as freeing everything
  when the `Pool` is garbage collected. That is the whole contract, and the middle row of
  the table is what it costs: dropping individual blocks does not shrink the pool.
- **The Python-visible half of a Cython API** — `Pool.alloc` is a `cdef` method, so only
  compiled Cython can call it. From Python the reachable surface is `Address`, a block of
  its own, and `own_pyref`, which puts an object under the pool's ownership. The caption
  under the table is the consequence: `size` and `addresses` are maintained by `alloc`, so
  a pool filled this way reports zero however much it is holding.
- **Measuring memory that Python does not count** —
  [`sys.getsizeof`](https://docs.python.org/3/library/sys.html#sys.getsizeof) reports 56
  bytes for an `Address` whatever its block size, because the block is not a Python object.
  [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html) does see it: cymem
  allocates through
  [`PyMem_Malloc`](https://docs.python.org/3/c-api/memory.html#c.PyMem_Malloc), which
  tracing hooks. Bytes and timings are separate passes, since tracing every allocation
  distorts the timings it would otherwise be reporting — and
  [`gc.collect()`](https://docs.python.org/3/library/gc.html#gc.collect) stays outside both
  timers, because neither structure is cyclic and a collect inside the release timer walks
  the whole heap: on a desktop run, five times the release it was meant to measure.
- **Compute off the UI thread** — the measurement runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind
  a spinner, with the worker wrapped so a failure cannot leave the button disabled, and the
  explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a
  background thread needs. The
  [slider](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) fires on
  release, so one drag runs the measurement once instead of once per pixel travelled.

Watch the per-block overhead row as you change the block size: it barely moves off 73
bytes, so at 64 bytes the wrapper costs more than the payload it wraps. The allocate row
narrows as the payload grows — on a desktop run at 10,000 blocks the pool cost about twice
the `bytearray` path at 64 bytes and about 1.2x at 4 KB, where nearly all that is left is
*when* you get the memory back. The speed argument for cymem lives in Cython, where
`pool.alloc()` returns a raw pointer and no Python object is created at all.

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
