# kiwisolver

[`kiwisolver`](https://kiwisolver.readthedocs.io/en/latest/) is the Python binding for
[kiwi](https://github.com/nucleic/kiwi), a C++ implementation of the
[Cassowary](https://constraints.cs.washington.edu/cassowary/) constraint solver. You state a
problem as relationships between variables — this edge sits on that margin, these two must not
overlap, this pair should be equal if possible — mark each relationship required or merely
preferred, and the solver returns an assignment that honours every required relationship and
comes as close as it can to the rest. matplotlib builds its constrained layout on it.

The solver is incremental: it keeps the solved system and updates it, so adding or removing a
constraint adjusts a live system instead of rebuilding one — microseconds on a small one. In a
Flet app that makes it worth reaching for whenever the rules of a layout, a schedule or a fit
interact enough that writing the arithmetic by hand stops being obvious.

## Install

Add kiwisolver to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "kiwisolver",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`layout-solver`](examples/layout-solver) — solves a three-column layout from constraints,
  draws the boxes where the solver puts them, and re-solves as rules are switched on and off.

## Usage in a Flet app

Build a solver, state the constraints, read the values back onto controls:

```python
import kiwisolver as kiwi

left, width = kiwi.Variable("left"), kiwi.Variable("width")
solver = kiwi.Solver()
solver.addConstraint(left == 12)                                     # required
solver.addConstraint(width >= 64)                                    # required
solver.addConstraint((left + width == 300) | kiwi.strength.strong)   # preferred
solver.updateVariables()

panel = ft.Container(left=left.value(), width=width.value())
```

[`updateVariables()`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.updateVariables)
is not the solve.
[`addConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.addConstraint)
and
[`removeConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.removeConstraint)
each re-solve the whole system as they run; `updateVariables` only copies the current values
onto the `Variable` objects, which is linear in their number and stayed under 4 µs at every
size in the table below. Keep one solver alive across events and mutate it rather than
rebuilding it — that is the entire point of an incremental solver, and the measurements under
[Cost of a solve](#cost-of-a-solve) show what rebuilding costs instead.

### Storage

There is nothing to store. kiwisolver reads and writes no files, and a solved system cannot be
serialised: `Solver`, `Variable` and `Constraint` all refuse `pickle` with
`TypeError: cannot pickle 'kiwisolver.Solver' object`, and `copy.deepcopy` fails the same way.

Persist the *inputs* instead — the sizes, the choices, the rules that were switched on — as
JSON in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
and rebuild the solver from them at startup. A few dozen constraints rebuild in a fraction of
a millisecond on desktop; a few hundred are a different matter, as the table below shows.

### Threading

**A `Solver` has no locking of its own.** Two threads mutating one solver is a data race in
C++, not a Python-level error. Give each thread its own solver, or serialise every call behind
one lock.

The extension holds the GIL while it works, so a long solve starves the rest of your Python
code even from a worker thread: on desktop, a half-second build let a competing thread that
sleeps 1 ms per loop run at roughly a seventh of its unloaded rate. What
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) does buy
you is a handler that returns immediately, so put anything large behind it, show a
[`ft.ProgressRing`](https://flet.dev/docs/controls/progressring/), and end the worker with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update). Interactive
re-solves of a small system are microseconds and belong on the UI thread.

### Strength and refusal

Every constraint carries a
[strength](https://kiwisolver.readthedocs.io/en/latest/basis/basic_systems.html#managing-constraints-strength).
`kiwi.strength.required` is the default and is absolute; `strong`, `medium` and `weak` are
preferences, applied with the `|` operator, and
[`strength.create(a, b, c, weight)`](https://kiwisolver.readthedocs.io/en/latest/basis/solver_internals.html#creating-strengths-and-their-internal-representation)
makes intermediate ones. A preference that cannot hold is simply violated —
[`Constraint.violated()`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Constraint.violated)
reports which — and the solver minimises the weighted error across the ones that remain, so a
weak preference yields to a strong one and both yield to anything required.

Only a required constraint can be refused. When one contradicts a required constraint already
in the solver, `addConstraint` raises
[`UnsatisfiableConstraint`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.UnsatisfiableConstraint),
with the offending constraint on the exception's `constraint` attribute. The conflict is proved
from the constraints themselves rather than found by trying values, so the refusal comes back
in microseconds even on a system of a thousand constraints. Catch it around any constraint
whose satisfiability you cannot guarantee — and read the two bullets below before deciding what
to do next, because the exception is not the end of it.

The other exceptions are narrower: `DuplicateConstraint` for adding the same object twice,
`UnknownConstraint` for removing one the solver does not hold, `DuplicateEditVariable` and
`UnknownEditVariable` for the edit-variable equivalents, and `BadRequiredStrength` from
`addEditVariable(v, kiwi.strength.required)`, which is not allowed.

### Cost of a solve

Editing a live system is cheap; building one is not. Measured on desktop (macOS arm64,
CPython 3.12) on a chain of columns with weak equal-width preferences, three constraints per
column:

| Columns | Constraints | Build from scratch | One edit afterwards |
| ---: | ---: | ---: | ---: |
| 25 | 75 | ~1 ms | ~0.25 ms |
| 50 | 150 | ~11 ms | ~1.3 ms |
| 100 | 300 | ~125 ms | ~7.7 ms |
| 200 | 600 | ~1.6 s | ~47 ms |

Both columns are super-linear, and unequally so: each doubling costs the build about twelve
times as much and the edit about six, so the cheaper of the two gets cheaper the bigger the
system is — an edit is a quarter of the rebuild at 25 columns and a thirtieth at 200. So a
system of a few hundred constraints is a background-thread job to build and an interactive one
to adjust. A phone will be slower than these figures; the example's benchmark button reports
both numbers on the device you run it on.

### App size

The wheel is approximately 55–75 KB compressed and 130–260 KB unpacked, depending on
architecture. Almost all of that is the single `_cext` extension, so there is nothing worth
removing with [`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup),
and an app bundle, split APKs or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) are
worth reaching for because of the rest of the payload, not because of this package.

### Other considerations

A desktop `flet run` uses PyPI's own wheel, built from the same sources at the same version,
so the API and the solutions match. Speed does not: the desktop machine is several times
faster than a phone, and the table above was measured there. Size any system that has to stay
interactive against a device, not against `flet run`.

## Things to know

- **A refused constraint can leave the solver silently wrong.** `addConstraint` raising
  `UnsatisfiableConstraint` does not undo the pivots it had already made, so the constraint it
  just refused can end up in force anyway — no exception, no warning, wrong numbers on the next
  read. Reproduced on desktop with the same release the mobile wheel builds: three widths each
  required `>= 72`, a `strong` total of 236, then a required `sidebar == 48` that is refused —
  and the very next `updateVariables()` reports `sidebar = 48`, under its own required minimum.
  It is not rare (across randomly generated required systems, between a quarter and half of
  refusals left an already-accepted constraint violated, depending on the mix of equalities and
  inequalities) and it is not predictable: the same two rules added in the opposite order refuse
  just as firmly and leave the solution intact. Treat the exception as fatal to that solver —
  call [`Solver.reset()`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.reset)
  and re-add the constraints you know are good, which restores correct results.

- **With an edit variable in the solver, that same refusal can kill the app.** After a refused
  constraint,
  [`suggestValue()`](https://kiwisolver.readthedocs.io/en/latest/api/python.html#kiwisolver.Solver.suggestValue)
  can abort the process with
  `libc++abi: terminating due to uncaught exception of type kiwi::InternalSolverError: Dual
  optimize failed.` — a C++ exception with no Python wrapper, so no `except` clause runs and on
  a phone the app simply disappears. `reset()` before the next `suggestValue()` avoids it. If a
  solver can be handed constraints that might be refused, consider expressing the changing
  input as a `strong` equality that you remove and re-add instead of as an edit variable; that
  path survives a refusal, and it is what the example does.

- **`Variable` is unhashable, and `==` does not compare.** `x == y` builds a `Constraint`,
  which is always truthy, so `x in [y]` is `True` for any two variables and `list.remove`,
  `.index` and `.count` all misbehave. `{x: ...}` raises
  `TypeError: unhashable type: 'kiwisolver.Variable'`. Key your own containers by name.

- **A constraint can only be removed through the object that was added.**
  `removeConstraint(x == 5)` raises `UnknownConstraint` even when a structurally identical
  constraint is in the solver, and adding two identical-looking objects adds both — only
  re-adding the *same* object raises `DuplicateConstraint`. Keep a reference to anything you
  intend to remove or to ask `violated()` about.

- **`violated()`, `strength()` and `op()` are methods, not properties.** `if c.violated:` tests
  a bound method and is always true; the parentheses are not optional.

## Build notes (maintainers)

### Recipe shape

A plain C++ extension recipe: the sdist builds unmodified, and the only mobile-specific entry
is the Android `flet-libcpp-shared` host requirement, because the extension links
`libc++_shared.so`. There are no patches, and nothing about the package needs a native-library
split.

### Upgrade hazards

The C++ core carries its own version, reported separately as `__kiwi_version__`, and moves
independently of the Python package version. The refusal behaviour documented above — the
corrupted tableau, and the `InternalSolverError` abort through an edit variable — are
properties of that core, so a bump that changes it can fix or change them. Those bullets are
consumer-facing claims: re-run them rather than carrying them forward.

### Re-verification checklist

- **Android C++ runtime:** the built extension must still list `libc++_shared.so` in
  `DT_NEEDED` and the wheel must still declare `flet-libcpp-shared`; every `PT_LOAD` segment
  must stay 16 KB aligned.
- **iOS binary type:** the extension must be a Mach-O dynamically linked shared library linking
  `/usr/lib/libc++.1.dylib` and the Python framework, not a bundle.
- **Refusal behaviour:** re-run the three probes behind the Things to know bullets — the
  silently wrong state after a refusal, the `suggestValue()` abort with an edit variable, and
  the `reset()` recovery.
- **Cost table:** re-measure the build and edit figures rather than scaling the old ones, and
  re-run the example's benchmark on a device.
- **Wheel contents:** the published mobile wheels install a top-level `src/version.h` that the
  PyPI desktop wheel of the same version does not contain. It is a generated header rather than
  importable code, but it does put a `src/` directory into site-packages; check whether it is
  still emitted, and whether it has grown into anything that matters.

### Coverage gaps

The device tests cover a two-equation solve and one required-versus-weak strength case. They do
not exercise edit variables, `removeConstraint`, `UnsatisfiableConstraint` or the state a
refusal leaves behind, or any system large enough to show the super-linear build cost. Every
claim about those is desktop-verified only.
