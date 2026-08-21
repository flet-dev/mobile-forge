# cymem

[`cymem`](https://github.com/explosion/cymem) is a small Cython utility that ties C memory
to a Python object's life-cycle. A `Pool` hands out zero-filled blocks and frees every one
of them when the pool itself is garbage collected, which removes the deallocator that a
nest of C structs would otherwise need; an `Address` is a single block with the same
property. It is a low-level building block rather than something you would reach for while
writing an app — it arrives with compiled Cython extensions that were written against it,
and does its work below the Python code you type.

## Install

Add cymem to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "cymem",
]
```

The classes live in the compiled submodule, not the package, so the import is
`from cymem.cymem import Pool, Address` — `from cymem import Pool` raises `ImportError`.
`Address(number, elem_size)` takes two integers and multiplies them, so `Address(1024, 1)`
and `Address(256, 4)` both allocate 1024 bytes. The version string is at
`cymem.about.__version__`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`pool-lifetime`](examples/pool-lifetime) — measures a pool against a list of
  `bytearray`s and shows when each one actually gives its memory back.

## Usage in a Flet app

The Python-reachable API is deliberately thin: allocate blocks, put them under a pool's
ownership, and let go of the pool to free them together.

```python
import flet as ft
from cymem.cymem import Address, Pool

pool = Pool()
for _ in range(1000):
    pool.own_pyref(Address(4096, 1))  # 4 KB, zero-filled

caption = ft.Text(f"{len(pool.refs) * 4096 / 1e6:.1f} MB tied to one object")
del pool  # every block goes at once, here
```

### Threading

Upstream documents `Pool` as thread-safe from version 2.0.12 onwards: `alloc`, `free` and
`realloc` take a Cython critical section around the pool's `size` and `addresses`
bookkeeping, and `own_pyref` is a single list append. The
[thread-safety notes](https://github.com/explosion/cymem#thread-safety) are explicit that
this covers the pool's own accounting and not the contents of the blocks — sharing a block
between threads is still yours to synchronise.

That guarantee is aimed at free-threaded CPython. The mobile wheels are built for the
default builds — the tags on [pypi.flet.dev](https://pypi.flet.dev/cymem/) are `cp312`,
`cp313` and `cp314` with no `t` variant — so on device the GIL is serialising the
bookkeeping anyway.

What still needs care is where the work happens. Allocating in bulk is CPU work on the
calling thread, so put it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), catch
exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). Freeing is work
too, in proportion to how many blocks the pool accumulated, and it is refcounting rather
than the cycle collector that does it: under `gc.disable()` a desktop run still gave back
all 20.8 MB of a pool of 5,000 4 KB blocks the instant the last reference went. Whichever
thread drops that reference pays for it.

### Lifetime

A pool's promise is that nothing leaks, not that anything is returned early. Memory goes
back when the pool is collected — CPython's refcounting makes that the moment the last
reference disappears, so `del pool` is usually immediate, but a pool caught in a reference
cycle waits for the garbage collector. In a long-lived app that means the scope you give a
pool *is* its memory profile: a pool reachable from a module-level object or from a Flet
control is a pool that never frees. Create one per unit of work and let it go with the work.

Neither class supports weak references, so you cannot attach a
[`weakref.finalize`](https://docs.python.org/3/library/weakref.html#weakref.finalize) to
watch a pool die; `weakref.ref(Pool())` raises `TypeError: cannot create weak reference to
'cymem.cymem.Pool' object`.

The blocks are also invisible to the obvious accounting.
[`sys.getsizeof`](https://docs.python.org/3/library/sys.html#sys.getsizeof) reports 56
bytes for an `Address` regardless of the block behind it, against 1081 bytes for a
`bytearray(1024)`. [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html) is
the tool that does see them, because cymem allocates through
[`PyMem_Malloc`](https://docs.python.org/3/c-api/memory.html#c.PyMem_Malloc) rather than
plain `malloc`: on a desktop machine, a list of 5,000 `Address` objects traced about 64
bytes per block on top of the payload itself.

Those 64 bytes are what a block costs beyond its data — the 56-byte wrapper, plus 8 bytes
for every reference kept to it. The example app, which keeps each block both in a pool and
in a list of its own, measures about 73. That is worth knowing before allocating a very
large number of very small blocks from Python: at a 64-byte block size the bookkeeping is
larger than the data.

### App size

The wheels are approximately 34–45 KB compressed and 68–176 KB unpacked, depending on
architecture — one small extension module and a handful of text files. There is nothing
here worth removing with
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup); the usual
Android levers — an app bundle, split APKs, or narrowing
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) —
act on the application as a whole.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, built from the same sdist with the same
API. The one configuration that exists there and not on device is free-threading: PyPI
publishes `cp313t`/`cp314t` wheels, so thread-safety behaviour validated on a free-threaded
desktop interpreter is not the configuration your app will run in.

The wheel also carries `cymem.pxd` and `cymem.pyx`, which is what another Cython project
`cimport`s to allocate through a pool at C speed. Those are build-time inputs: there is no
compiler on the device, so an extension that uses them has to be compiled into a wheel
before packaging — which for a mobile target means a recipe of its own.

## Things to know

- **The allocation methods are Cython-only.** `alloc`, `free` and `realloc` are `cdef`
  methods, so `hasattr(pool, "alloc")` is `False` and no Python code can call them. What
  Python sees on a `Pool` is the constructor, the read-only `size`, `addresses`, `refs`,
  `pymalloc` and `pyfree` attributes, and `own_pyref(obj)`. On an `Address` it is the
  constructor, the same read-only `pymalloc` and `pyfree`, and `addr` — the pointer as an
  integer.

- **A pool filled from Python reports zero.** `size` and `addresses` are updated by
  `alloc`, so a pool that owns its memory through `own_pyref` shows `size == 0` and
  `addresses == {}` no matter how much is really tied to it. `len(pool.refs)` is the
  number that moves — do not use `pool.size` as a memory gauge.

- **Blocks arrive zero-filled.** Both `Address` and `Pool.alloc` `memset` the block after
  allocating; for `Address` that is confirmed on a desktop machine by reading it back
  through `ctypes.string_at(block.addr, 32)`. It is `calloc` semantics, so a partially
  written block has zeros in the gaps rather than whatever was there before.

- **Upstream's custom-allocator snippet does not translate to Python.**
  [`Pool(WrapMalloc(f), WrapFree(g))`](https://github.com/explosion/cymem#custom-allocators)
  needs `WrapMalloc` and `WrapFree`, which are `cdef` functions:
  `from cymem.cymem import WrapMalloc` raises `ImportError`. `PyMalloc()` and `PyFree()`
  *are* constructible from Python and a `Pool` built from empty ones constructs without
  complaint, but the wrappers hold no function. That pool is safe because `alloc` is out of
  reach; `Address` *does* call its allocator, and it refuses to be given one —
  `Address(4, 1, PyMalloc(), PyFree())` raises `TypeError: __init__() takes exactly 2
  positional arguments (4 given)`.

## Build notes (maintainers)

### Recipe shape

The recipe is a bare `meta.yaml` with one platform-specific requirement, commented in
place. cymem's sdist ships only `cymem.pyx` — no pre-generated C++ — so `cythonize()` runs
during the build and the Cython version resolved into the build environment is part of
what produced the wheel.

### Upgrade hazards

The consumer-facing claims above rest on a very small API, and a small API is easy to
change without it looking like a breaking change:

- If `alloc` ever becomes `cpdef`, both the "Cython-only" bullet and the "reports zero"
  bullet stop being true, and the example app's central measurement stops being the point.
- If the default allocator moves off `PyMem_Malloc`, blocks become invisible to
  `tracemalloc` and the memory figures quoted here can no longer be reproduced the way
  they were taken.
- 2.0.12 added the free-threading critical sections; a future release that changes the
  locking strategy changes what the Threading section promises.

### Re-verification checklist

- **Python-visible surface:** re-run `[n for n in dir(Pool) if not n.startswith("_")]` and
  confirm it is still `addresses`, `own_pyref`, `pyfree`, `pymalloc`, `refs`, `size` —
  in particular that `alloc`/`free`/`realloc` have not appeared and that `own_pyref` has
  not been renamed. Do the same for `Address`, which should stay `addr`, `pymalloc`,
  `pyfree`; both lists are quoted verbatim above.
- **Default allocator:** confirm `Default_Malloc` still wraps `PyMem_Malloc`, since the
  page's `tracemalloc` guidance depends on it.
- **Free-threading:** check whether the built wheel tags gain a `t` variant; the Threading
  section says they do not.
- **Android:** confirm `libc++_shared.so` is still reaching the device through the wheel
  dependency, and that the extension still names it in `DT_NEEDED`.
- **iOS:** confirm the extension is still `MH_DYLIB` rather than `MH_BUNDLE`, which
  `flet build` cannot link.
- **Size:** re-measure compressed and unpacked from the built wheels rather than scaling
  the figures above.

### Coverage gaps

The device test constructs a `Pool`. cymem has exactly one extension module, so that does
prove it loaded and initialised on the platform — but it allocates nothing. `Address`,
`own_pyref`, pool teardown and the zero-fill are not covered on device by the test suite;
the example app is what exercises them. The `cdef` allocation path is not reachable from
either, and can only be tested by a Cython extension compiled against this wheel.
