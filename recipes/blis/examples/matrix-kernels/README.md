# BLIS matrix kernels

One square matrix multiply, run twice: once through BLIS and once through numpy, at a size
and a thread count you choose. The table reports milliseconds and GFLOP/s for both, in
float32 and float64, how far the two results drift apart, and what happens when the same
output buffer is reused. The caption at the top names the versions and the BLAS numpy was
built against, which is the line that explains why the same app reads differently on a
laptop and on a phone.

What it demonstrates:

- **A rate you can compare against a tuned BLAS.** These wheels contain BLIS's portable C
  reference microkernel rather than the hand-written
  [arm64 assembly kernels](https://github.com/flame/blis/tree/master/kernels/armv8a) that the
  Linux aarch64 desktop wheel carries, and the GFLOP/s figure is where that shows up. A
  square GEMM is 2·n³ operations, so the arithmetic behind the number is checkable by hand.
- **Which matmul numpy actually has.** The mobile numpy wheel is built with no BLAS, so
  `A @ B` there is numpy's own fallback loop; a desktop wheel usually links a tuned library.
  The caption prints the name
  [`numpy.show_config`](https://numpy.org/doc/stable/reference/generated/numpy.show_config.html)
  reports, so the comparison never has to be taken on trust.
- **float32 against float64 in the same run.** Both are a single
  [`blis.py.gemm`](https://github.com/explosion/cython-blis#usage) call, and the wider type
  moves half as many elements per vector register. Nothing else changes.
- **The reused-buffer trap.** `gemm` computes `out = A·B + beta·out` with `beta` defaulting
  to 1, so multiplying twice into one buffer doubles it. The app measures that ratio rather
  than asserting it.
- **Parallelism the caller has to supply** — BLIS is compiled here without threading, so
  one call uses one core no matter what `BLIS_NUM_THREADS` says. The wrapper releases the
  GIL for the whole call, so eight multiplies split across
  [`threading.Thread`](https://docs.python.org/3/library/threading.html#thread-objects)
  workers finish in a fraction of the serial time. Each worker owns its output buffer.
- **Compute off the UI thread** — every run goes through
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.

The two results never match bit for bit, and that is the point: BLIS blocks and packs the
operands to keep the microkernel fed, so it adds the same products in a different order.
At float32 the relative gap sits around 10⁻⁶ and grows with the matrix size, because a
longer inner dimension means more rounding to accumulate.

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
