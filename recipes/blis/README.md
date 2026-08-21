# blis

[`blis`](https://github.com/explosion/cython-blis) packages the
[BLIS](https://github.com/flame/blis) linear-algebra library as a self-contained Python
extension: the C library is compiled into the wheel rather than linked from the system, so
a matrix multiply runs with no BLAS installed anywhere, which is the property that carries
it onto Android and iOS. It is a low-level building block, closer to a compiled routine
than to a library you would design an app around, and it more often arrives underneath
something else than as a deliberate choice.

The functions live in a submodule literally named `py`, so the import is
`from blis.py import gemm`.

## Install

Add `blis` to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "blis",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`matrix-kernels`](examples/matrix-kernels) — times a square GEMM against numpy's matmul
  at a size and thread count you pick.

## Usage in a Flet app

Everything goes through [`numpy`](https://numpy.org/doc/stable/) arrays, and the result is
an ordinary array you can format into a
[`ft.Text`](https://flet.dev/docs/controls/text/) or feed to a chart:

```python
import numpy as np
from blis.py import gemm

a = np.ascontiguousarray(batch, dtype="float32")     # 2-D, C-contiguous
b = np.ascontiguousarray(weights, dtype="float32")
out = np.zeros((a.shape[0], b.shape[1]), dtype="float32")

gemm(a, b, out=out)                                  # out += a @ b
status.value = f"{out.shape[0]} rows, max {out.max():.3f}"
```

### Threading

**BLIS is compiled here without threading**, on both platforms: the flags that would turn on
its [OpenMP or pthreads backend](https://github.com/flame/blis/blob/master/docs/Multithreading.md)
are off, so one call uses one core and `BLIS_NUM_THREADS` changes nothing. Upstream's own
desktop wheels are built the same way, so it is not a mobile-only restriction.

The multiply does release the GIL for its whole duration. Move it off the Flet UI thread
with [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
catch and display exceptions inside the worker, and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update):

```python
def work():
    try:
        gemm(a, b, out=out)
        status.value = f"{out.max():.3f}"
    except Exception as exc:
        status.value = str(exc)
    page.update()  # auto-update does not reach background threads
```

Because the GIL is released, more than one core is reachable by running several multiplies
on several threads. Upstream's
[thread-safety notes](https://github.com/explosion/cython-blis#thread-safety) call the library
re-entrant and free of global state, and safe to use concurrently *with immutable data* — so
**give every thread its own output array**, since two threads writing one buffer
is a data race nothing will report. On a desktop Apple M4, eight 384×384 float32 multiplies
took about 27 ms on one thread, 14 ms on two and 7 ms on four; device figures come from
the example.

### Which kernels this wheel contains

BLIS picks a microkernel family at build time, not at run time, and that choice is the
single biggest influence on how fast it goes. These wheels are configured `generic`: the
only GEMM microkernels in either extension are BLIS's portable
[C reference kernels](https://github.com/flame/blis/tree/master/ref_kernels) —
`bli_sgemm_generic_ref` and its siblings — and none of the hand-written
[armv8a assembly kernels](https://github.com/flame/blis/tree/master/kernels/armv8a) are in
the binary on any slice. Upstream calls those reference kernels portable C99 that runs
almost anywhere, and
[warns](https://github.com/flame/blis/blob/master/docs/BuildSystem.md) they yield
relatively low performance because they carry no architecture-specific optimisation beyond
what the compiler finds by itself.

It remains the defensible choice: a wheel tagged `arm64_v8a` has to run on every arm64 phone
from an old Cortex-A53 to a current Apple SoC, and cython-blis's arm configurations compile
in exactly one kernel family with no run-time choice — the Linux aarch64 desktop wheel is
built for `cortexa57` and contains those kernels and nothing else.

What that costs is measurable. PyPI's macOS arm64 desktop wheel is configured identically —
same reference kernels, same threading setting — and on one Apple M4 core it sustains
roughly 31–36 GFLOP/s in float32 and 23–25 GFLOP/s in float64 for square multiplies between
128 and 512 elements a side. **That is a desktop figure**; a phone core is slower, and the
example prints the device's own number. Read it against the right baseline, too: the mobile
`numpy` wheel is built with no BLAS at all, so `a @ b` on device is numpy's own fallback
loop rather than a tuned library, and the contest on a phone is not the one a laptop stages.

### Precision

`gemm` takes float32 and float64 and nothing else, and the choice shows in the timings as
well as the result: in the desktop measurement above float64 runs at roughly seven-tenths of
the float32 rate, because half as many elements fit in a vector register.

Neither will match numpy bit for bit. BLIS blocks and packs the operands to keep the
microkernel fed, so it sums the same products in a different order; the example's relative
difference at float32 is around 10⁻⁶ and grows with the matrix size. Compare with
[`np.allclose`](https://numpy.org/doc/stable/reference/generated/numpy.allclose.html)
rather than `==`.

### App size

Expect approximately 1.2–1.6 MB compressed and 4.0–5.5 MB unpacked per architecture, across
the ABIs a Flet app can ship and every bundled Python version — the top of each range being
`x86_64`, the bottom the arm64 ones. Almost all of it is the two extension modules, each of
which carries a complete copy of BLIS, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
useful to remove.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not the
exact amount added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` on Apple Silicon uses a wheel with the same kernels and threading
setting as the mobile ones, so a rate measured there is at least the same kind of number.
On Intel macOS, Linux and Windows it is not: those wheels ship tuned assembly kernels — the
x86_64 ones carry several families and dispatch on the CPU at run time — and a timing taken
on them says nothing about a phone. Desktop numpy usually has a real BLAS behind `a @ b`
where the mobile wheel has none, so any ratio between the two must be re-measured on device.

## Things to know

- **`import blis` does not give you the functions.** The package's `__init__` imports only
  `blis.cy`, so a bare `import blis` followed by `blis.py.gemm(...)` raises
  `AttributeError: module 'blis' has no attribute 'py'`. Import the submodule explicitly:
  `from blis.py import gemm`.

- **`out=` adds to the buffer instead of replacing it.** `gemm` computes
  `out = alpha·A·B + beta·out`, and `beta` defaults to `1`, so a second call into the same
  array doubles it with no warning. Zero the buffer between calls, or pass `beta=0.`.

- **Operands must be 2-D, C-contiguous and exactly float32 or float64.** Nothing is
  converted: an integer or 1-D array raises `TypeError: No matching signature found`, mixing
  the two float types raises `ValueError: Buffer dtype mismatch`, and a Fortran-ordered array
  raises `ValueError: ndarray is not C-contiguous`. Convert with
  `np.ascontiguousarray(x, dtype="float32")`.

- **`trans1` and `trans2` are broken in float64, and they fail silently.** That branch
  ignores both flags when it sizes the result and when it hands the dimensions to BLIS, so a
  transpose that changes the shape returns an array of the *untransposed* shape and raises
  nothing — and BLIS reads past the end of the operand while filling it. The
  `ValueError: operands could not be broadcast together` that follows comes from your own
  comparison against the right answer, not from `gemm`. Only square operands come out right.
  float32 handles both flags correctly; in float64, transpose the array yourself.

- **Parts of `blis.py` do nothing.** `axpy` on a float32 array returns zeros — that branch
  never calls the BLIS routine, while the float64 one works — and `einsum("ab,a->ab")`
  returns `None`. `einsum` understands a fixed list of subscripts and raises
  `ValueError: Invalid einsum` for the rest.

- **`import blis.benchmark` fails.** It ends with `if __name__:` instead of a `__main__`
  guard, so importing it calls the module's `main()`. That prints a banner announcing a
  thousand-iteration timing run, then dies before timing anything on
  `AttributeError: module 'numpy.__config__' has no attribute 'blas_opt_info'` — an API
  numpy removed.

- **Do not call `blis.cy.finalize()`** — it is already registered to run at interpreter exit.
  Calling it and then multiplying again terminates the process with `SIGSEGV` rather than
  raising, which on a device is an app that simply disappears.

## Build notes (maintainers)

### Recipe shape

This is a plain sdist build with one patch, and there is no `flet-libblis` native-library
recipe in front of it because there is no shared library to produce: cython-blis vendors the
whole of BLIS under `blis/_src`, compiles it with its own object builder rather than through
distutils, and links the resulting objects statically into each of the two extension
modules. That is also why the payload is roughly twice the size of the library — `cy` and
`py` each end up with a full copy, 2 880 `bli_*` symbols apiece on the arm slices. Only
`cy`'s copy is ever reached from Python: `blis/py`'s `gemm` just dispatches on dtype and
then calls `__pyx_fuse_0gemm`/`__pyx_fuse_1gemm` out of `blis/cy`'s `__pyx_capi__` table,
which is where `bli_sgemm_ex`/`bli_dgemm_ex` are called. `py`'s own BLIS is dead weight,
and neither extension can be dropped from the wheel. `numpy` is a host requirement because
`setup.py` imports it at configure time for its include directory.

The patch preamble owns the explanation of the kernel selection, the compiler redirect, the
Android barrier flip and the iOS deployment-target flag. Do not restate those mechanisms here.

### Upgrade hazards

The patch edits `blis/_src/include/linux-generic/blis.h`, a *generated* header shipped inside
the sdist and regenerated whenever the vendored BLIS is refreshed. A bump can move the barrier
`#if` it targets; the hunk will fail rather than misapply, so read the reject before assuming
the bump is clean. The same patch pins `BLIS_ARCH` from inside `setup.py`, so if upstream
grows real `android` or `ios` branches in its platform detection, that hunk stops being the
right place to do it and the `make/<platform>-<arch>.jsonl` and `include/<platform>-<arch>/`
pair the build lands on can change with it.

Upstream caps `Requires-Python` at `<3.15`. That cap, not this recipe, decides which Python
versions can resolve the wheel.

### Re-verification checklist

- **Kernel family:** confirm the built extensions still contain only `*_generic_ref` GEMM
  microkernels and no assembly kernels. The consumer page states this as fact and a bump
  that changed the arch pin would invalidate the whole speed discussion.
- **Threading:** `bli_info_get_enable_threading`, `bli_info_get_enable_openmp` and
  `bli_info_get_enable_pthreads` must still compile down to a constant zero. Read them out
  of the binary; the absence of a flag is not evidence.
- **iOS file type:** both `cy` and `py` must be `MH_DYLIB`. An `MH_BUNDLE` fails at link
  time with "Unsupported mach-o filetype".
- **Android alignment:** check every `PT_LOAD` segment is 16 KB aligned.
- **API behaviour:** the float32 `axpy`, the float64 transpose sizing and the
  `blis.benchmark` import are upstream defects a bump could fix, and the `beta=1` default is
  a deliberate choice a bump could still change. Re-run all four before repeating the bullets.
- **Size:** re-measure compressed and unpacked from the built wheels rather than scaling
  these figures.

### Coverage gaps

The device tests import both extensions and run one `einsum("ab,bc->ac")`, taking the
float64, untransposed path. That reaches further than the call site suggests: because
`blis/py` delegates through `blis/cy`'s `__pyx_capi__`, the single test does execute the
BLIS copy compiled into `cy` — so a green suite is real evidence that the linked-in library
runs on the device, not just that both extensions load. The third test is a numpy FFT canary
that only exercises numpy. Nothing on device covers float32 `gemm`, either transpose flag,
`gemv`, `dotv`, `ger`, `axpy`, buffer reuse, or concurrent calls from more than one thread.
The example is the only place those are exercised.
