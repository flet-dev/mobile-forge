# greenlet coroutine switch

One screen that runs greenlet's stack-switching assembly on the device and reports what it
cost and whether it was correct. Four panels: a switch pair priced against a generator
`next()` and a round trip between two OS threads; the same switch measured against the depth
of the parked greenlet, next to the bytes of machine stack it copied; eight conformance
checks over the paths hand-written assembly and lifecycle code can get wrong; and two
CPU-bound greenlets against the same work done twice in a row, which is the GIL.

Everything runs inside
[`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), so a green
screen is also the statement that greenlets work on a Flet worker thread and not only on the
main one — the panel header names the thread it ran on. That matters because greenlets belong
to the thread that created them, and every consumer path in a Flet app (a background query,
SQLAlchemy's async bridge) is a worker thread.

What it demonstrates:

- **What a switch costs, against the two alternatives Python already has.** Measured on an
  Apple M4 desktop under CPython 3.14.6, greenlet 3.5.1 from PyPI, at the app's own `100k`
  budget:

  | handoff | ns each | per second |
  | --- | --- | --- |
  | greenlet switch pair | 237 | 4,224,779 |
  | greenlet create + run | 2,166 | 461,649 |
  | generator `next()` | 23 | 44,141,165 |
  | thread round trip | 3,260 | 306,779 |

  A greenlet switch is roughly ten times a generator resume and roughly a tenth of waking
  another thread. If a generator can express what you need, it is an order of magnitude
  cheaper; the reason to reach for greenlet is that it can suspend a whole call stack,
  including frames you did not write, and a generator can only suspend itself.
- **That the cost is not constant — it scales with how deep the parked greenlet is.** The
  second panel parks the same greenlet 0, 100 and 1,000 Python frames down and reports both
  the time and `_stack_saved`, the bytes greenlet copied off the machine stack:

  | frames parked | machine stack copied | ns per switch pair |
  | --- | --- | --- |
  | 0 | 1,416 B | 223 |
  | 100 | 1,416 B | 712 |
  | 1,000 | 1,416 B | 7,082 |

  The two columns disagree on purpose. Since CPython 3.11 a Python-to-Python call does not
  recurse in C, so a thousand extra Python frames cost no extra machine stack — and yet the
  switch is 32× dearer, because greenlet walks the parked greenlet's interpreter-frame chain
  on the way out and again on the way back in so that a traceback taken later still works.
  A greenlet parked at the *bottom* of a deep call stack is an expensive greenlet.
- **Eight things that can be broken while `import greenlet` still succeeds.** All eight pass
  on desktop; the point of running it on a phone is that these are the paths that depend on
  the per-architecture assembly and on greenlet's own bookkeeping rather than on portable C:
  50,000 switches leaving an accumulator exact to the last unit (a switch that loses a
  callee-saved register shows up here as a wrong number, not a crash), a 1,000-frame unwind
  resumed after a switch, an exception leaving a greenlet with its traceback attached,
  `throw()` landing inside a parked greenlet, a dropped greenlet receiving `GreenletExit`,
  `greenlet.error` on a switch to another thread's greenlet, contextvars staying inside the
  greenlet that set them, and a switch to a dead greenlet returning instead of raising.
- **That greenlets are not a second core.** The last panel times 400,000 multiplies done
  twice against the same work split across two greenlets, best of five rounds each. Three
  desktop runs of it reported **1.05×, 1.00× and 0.96×** — one, within the noise of an 18 ms
  measurement. The extension never releases the GIL (no `PyEval_SaveThread`,
  `PyEval_RestoreThread` or `PyGILState_*` in any of the nineteen published wheels), so
  greenlets buy interleaving and a parkable call stack, never parallelism. A blocking call
  inside one blocks every other greenlet on that thread, with no preemption.
- **Cleaning up after itself, which is half of using greenlet correctly.** Every timing loop
  kills its greenlet with `gl.throw()` in a `finally` rather than leaving it to the
  collector: a parked greenlet holds its saved machine stack until something raises
  `GreenletExit` inside it, and one you keep a reference to and never resume is a leak that
  reports `dead == False` forever.
- **Degrading instead of crashing.** The import of `greenlet` is guarded. Without the wheel
  the header turns red and names what the import raised, the `generator next()` and
  `thread round trip` rows are still measured so the device's baseline is visible, every
  greenlet cell reads a dash, and the three panels below say what was skipped.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.6,
greenlet 3.5.1 from PyPI). The point of running the app is to replace them with the device's
own. Read the iOS numbers with the caveat in the recipe's
[iOS notes](../../README.md#ios): the published iOS slices are compiled without
optimisation, and the same flags reproduced on this desktop moved the switch pair from
228 ns to 1,601 ns and the depth-1,000 row from 6,768 ns to 16,940.

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

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the
panels before committing to a build.
