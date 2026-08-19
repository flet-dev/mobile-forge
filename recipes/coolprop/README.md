# coolprop

[CoolProp](https://coolprop.org/) is a thermophysical property library: reference equations
of state for 124 pure fluids and their mixtures, a
[humid-air model](https://coolprop.org/fluid_properties/HumidAir.html), and a library of
[incompressible fluids and brines](https://coolprop.org/fluid_properties/Incompressibles.html).
It is what an HVAC, refrigeration or process app asks when it needs the density of R134a on
its saturation line or the wet-bulb temperature of a room.

The reason it works well on a phone is that **all of that data is compiled into the
extension**. There is no database to bundle, no table to download and no service to call —
`import CoolProp` and the whole property library is in the process. Which is also the one
thing to plan for: that import is not cheap (see [Things to know](#things-to-know)).

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "coolprop",
]
```

The distribution is published as `CoolProp` and pip normalises the name, so the lowercase
`coolprop` above resolves the same wheel. The import name is the capitalised one:
`import CoolProp`.

Nothing else to configure. In particular no
[`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed: the Python modules `import CoolProp` loads open no files, and the fluid and
incompressible databases live *inside* the extension rather than beside it, so Android's
zipped site-packages has nothing to fail to serve. Two wheels come along on their own and
neither needs configuring: `numpy`, which the `Requires-Dist` asks for (CoolProp uses it to
return arrays, but works without it — see [Things to know](#things-to-know)), and, on
Android only, `flet-libcpp-shared`, the NDK C++ runtime both extensions link against.

Eighteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × the three Android
ABIs Flet targets (arm64-v8a, armeabi-v7a, x86_64) and the three iOS slices (device,
arm64 simulator, x86_64 simulator).

## Storage

By default CoolProp writes nothing and reads nothing: it never touches the filesystem, and
the wheel's non-code files — a BibTeX bibliography, a directory of C++ headers and a config
file belonging to a Python 2-era plotting module nothing imports — are opened only if you
go looking for them with `copy_BibTeX_library()` or `get_include_directory()`.

The exception is the [tabular backends](https://coolprop.org/coolprop/Tabular.html)
(`BICUBIC&HEOS`, `TTSE&HEOS`), which build an interpolation table per fluid and cache it
under `$HOME/.CoolProp/Tables/`. Measured on desktop, one fluid costs **16–19 MB** on disk
(`AbstractState("BICUBIC&HEOS", "n-Propane")` wrote 15,921,841 bytes; R134a wrote
18,893,141) and the default cap on that directory is 1 GB. If you use them, redirect the
cache into [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
first, and **end the path with a separator** — CoolProp concatenates the value with the
backend descriptor and inserts nothing between them, so a path without a trailing separator
creates a sibling directory instead of writing inside the one you named:

```python
CP.set_config_string(CP.ALTERNATIVE_TABLES_DIRECTORY, os.path.join(cache, "coolprop-tables") + os.sep)
```

Where `$HOME` resolves to under Flet on Android and iOS is not established here, which is a
second reason to set the path rather than let CoolProp choose it.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`property-check`](examples/property-check) — fluid properties cross-checked against published reference values, and the out-of-range request that returns a wrong number instead of raising.

## Threading

**CoolProp never releases the GIL.** Neither shipped extension imports
`PyEval_SaveThread` or `PyEval_RestoreThread`, which is what Cython's `with nogil` compiles
to, so a call holds the interpreter for its whole duration and no other Python code runs
meanwhile.

That is fine for almost everything CoolProp offers, because almost every call is short. In
a desktop canary sampling a 1 kHz ticker, 5000 `PropsSI` calls costing 2.0 s in total
delayed the ticker by at most **8.4 ms** — the interpreter switches between calls, so a
sweep of thousands of points stays responsive. The same canary against one
`sum(range(3e8))` was blocked for the entire 2.1 s.

So push sweeps to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads, and `run_thread` swallows worker exceptions, so wrap the body
in `try/except` and render what it caught.

What `run_thread` cannot save you from is a **single** long call, and CoolProp has one worth
knowing: constructing a tabular `AbstractState` builds the table. In the same canary,
`AbstractState("BICUBIC&HEOS", "R32")` took 7.8 s and blocked the ticker for all 7.8 s.
There is no thread that makes that call feel any different.

CoolProp itself imposes no thread rules — there is no shared handle to serialise — but an
`AbstractState` is a mutable object holding one state point, so give each thread its own
rather than sharing one.

## Android notes

The extensions carry a CPython ABI tag (`CoolProp/CoolProp.cpython-314.so`,
`CoolProp/_constants.cpython-314.so`); both link `libc++_shared.so`, which is why the wheel
declares `flet-libcpp-shared` in its `Requires-Dist` and iOS does not. Both extensions load
during `import CoolProp`: the package `__init__` imports `constants`, which imports
`_constants`.

## iOS notes

The extensions are `CoolProp/CoolProp.so` and `CoolProp/_constants.so` — Mach-O dylibs
against the OS's own `/usr/lib/libc++.1.dylib`, so nothing extra is installed. They are also
unstripped: `CoolProp.so` keeps a 15,824-entry symbol table with 990,504 bytes of strings
that the Android build's `--strip-unneeded` pass throws away. That is what makes the iOS
extension the larger of the two (9,237,936 bytes against 8,973,320) even though its
`__text` is the *smaller* — 2,932,312 bytes against Android's `.text` at 3,098,644.

Nothing functional differs. Every slice carries the same records — the same 124 fluids out
of the same 9,075,745 bytes of fluid JSON, the same 126 incompressibles out of the same
179,194 bytes, the same 105 predefined mixtures out of the same 24,254. Those blobs are
byte-identical between the two Android ABIs but **not** between Android and iOS: iOS
serialises the fluid and incompressible arrays in a different order, so they hash
differently while comparing equal once parsed. The mixtures blob is identical everywhere.

## Things to know

- **CoolProp does not police its own inputs, and will answer an impossible question with a
  confident number.** `PropsSI("Tmax", "Water")` reports 2000 K and the wheel's own fluid
  data declares `T_max` 2000 K for water — and `PropsSI("D", "T", 100000, "P", 101325,
  "Water")` still returns `0.0021954…`, with no exception, no warning and no NaN. Nitrogen
  below its triple point does the same (`T` = 50 K against `Ttriple` 63.151 K returns
  919.35 kg/m³), and `DONT_CHECK_PROPERTY_LIMITS` is already off. **Range-check before you
  call**, reading the bounds out of CoolProp itself with `PropsSI("Tmin"/"Tmax"/"pmax",
  fluid)`. Where it *does* refuse cleanly is worth preferring when you have the choice:
  saturation calls outside the dome (*"Temperature to QT_flash [700 K] may not be above the
  numerical critical point of 647.095999999987 K"*), the incompressible backend (*"Your
  temperature 250.000000 is below the freezing point of 265.201217."*) and `HAPropsSI`
  (*"The input for key (12) with value (100) is outside the range of validity: (130) to
  (623.15)"*). Even then it is not uniform: water at 200 K and 1 atm raises, but as a solver
  failure — *"Inputs in Brent […] do not bracket the root"* — while a saturation pressure
  below the triple point returns silently.
- **`import CoolProp` is the expensive thing in the whole package.** On a fast desktop it
  costs about **110 MiB of resident memory and 480–540 ms**, and `-X importtime` puts 440 ms
  of that in the package `__init__` body, which unconditionally asks the extension for the
  full fluid list and so forces the embedded database to be decompressed and parsed. There
  is no lazy path and no way to load a subset. Do the import inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  something on screen, and budget the memory — device figures are not established here, and
  the [`property-check`](examples/property-check) example prints them.
- **[`PropsSI`](https://coolprop.org/coolprop/HighLevelAPI.html) rebuilds its backend on
  every single call.** Reusing one
  [`AbstractState`](https://coolprop.org/coolprop/LowLevelAPI.html) is two to three orders of
  magnitude faster: over the same 200-point saturation sweep the example measures around
  80 µs per `PropsSI` call against well under 1 µs per `state.update(...)` on a desktop —
  a ratio in the hundreds, which is the number the example prints.
  Water is also unusually expensive per construction — 419 µs for a `D|PT` call, against
  82 µs for the same call on R134a — because it builds superancillary curves each time;
  `set_config_bool(ENABLE_SUPERANCILLARIES, False)` brings it to 89.8 µs with the answer
  unchanged to six digits.
- **Everything is in the binary, and it is complete.** 124 pure fluids plus 310 aliases for
  them (besides `Water`, water answers to `water`, `WATER`, `H2O`, `h2o` and `R718`), 74 pure
  incompressibles plus 52 solutions and brines, humid air via `HAPropsSI`, the cubic
  backends (`SRK::Propane`, `PR::Propane`), 105 predefined mixtures (`R410A.mix`) and
  arbitrary [HEOS mixtures](https://coolprop.org/fluid_properties/Mixtures.html)
  (`HEOS::Methane[0.5]&Ethane[0.5]`). Read the lists off the running library with
  `CoolProp.__fluids__`, `__incompressibles_pure__` and `__incompressibles_solution__`.
- **Three things are compiled in but cannot work on a phone.**
  [REFPROP](https://coolprop.org/coolprop/REFPROP.html) interop `dlopen`s a NIST library no
  device has, and fails by printing a dozen advisory lines to stdout before raising; the
  PCSAFT backend ships with an empty fluid library, so every `PCSAFT::…` request raises
  *"key […] was not found in string_to_index_map in PCSAFTLibraryClass"*; and
  `CoolProp.GUI` needs wxPython, which pypi.flet.dev does not carry.
  `CoolProp.Plots` is a softer case — it imports `matplotlib`, which this wheel does not
  pull in but which *is* available for mobile, so add it yourself if you want those plots.
- **Errors are plain `ValueError`.** There is no CoolProp-specific exception class to catch,
  so catch `ValueError` and show the message — it is specific, and usually names both the
  offending value and the valid range.
- **`numpy` is declared but not required.** The extension does `import numpy` at module
  scope inside a `try`, uses it to return an `ndarray` when you pass lists to `PropsSI`, and
  falls back to returning a plain `list` when it is absent. With numpy uninstalled,
  `import CoolProp`, `PropsSI` and `HAPropsSI` all work; only `CoolProp.Plots` fails. You
  cannot drop it from the install — it is in the wheel's `Requires-Dist` — but nothing in
  your app has to import it.
- **Size.** The wheel is 5.78 MB on Android arm64-v8a and 5.69 MB on iOS arm64, unpacking to
  10.6 MB and 10.9 MB; the extensions are ~9 MB of that. About **1.57 MB of every wheel is
  ballast** your app will never touch — 1.19 MB of C++ headers under `CoolProp/include/`,
  a 134 KB BibTeX bibliography, `CoolProp/Plots/`, `CoolProp/GUI/`, `CoolProp/tests/` and
  the `.pxd` files. Counting what comes along, a slice costs roughly **13.0 MB on Android**
  (coolprop 5.78 + numpy 6.85 + flet-libcpp-shared 0.41) and **12.3 MB on iOS** (5.69 +
  6.59).

## Build notes (maintainers)

`patches/mkdir-cython-output.patch` explains itself in its own preamble. `meta.yaml` does
**not**: unlike its scikit-build-core siblings (`recipes/faiss-cpu`, `recipes/scipy`,
`recipes/duckdb`) it carries no comments at all, so the dual `Python_*`/`Python3_*`
variables, `-DANDROID_STL=c++_shared`, the 16 KB `max-page-size` linker flags and the iOS
`CMAKE_OSX_*` block are currently unexplained anywhere. They belong in comments next to the
settings, not here — that is a separate commit.

What is left is the bump checklist, and it starts from an uncomfortable fact: **`tests/`
verifies almost nothing this page claims.** Both tests call only `PropsSI` on water (a
saturation temperature and a saturated-liquid density), and `test_phase_envelope`
additionally misdescribes itself — it builds no phase envelope and touches no humid-air
path. A green CI run today proves the extension imports and that water boils.

- The counts above — 124 fluids, 310 aliases, 74 + 52 incompressibles, 105 predefined
  mixtures — come from the shipped binary and from a desktop CoolProp of the same upstream
  version, not from a test. Re-read them off a built wheel after a bump, and preferably add
  the assertions to `tests/` so the next bump cannot move them silently. When comparing two
  slices, compare the **raw** decompressed blobs: hashing after a `json.loads` and re-dump
  canonicalises away the Android/iOS ordering difference described under *iOS notes*, so it
  would report identity where there is none.
- The silent-extrapolation behaviour is upstream's, and it is the sharpest claim on this
  page. Re-check it after a bump: if CoolProp ever starts raising on `PropsSI("D", "T",
  100000, "P", 101325, "Water")`, the first bullet of *Things to know* and the third section
  of the `property-check` example both become wrong.
- Every size, timing and memory figure here is measured, not estimated. Re-measure rather
  than adjusting by eye; the ballast breakdown in particular is a `unzip -l` sum.
- The import cost, the `PropsSI`-versus-`AbstractState` gap and the RSS figures are
  **desktop** numbers. The example prints the device equivalents on screen; if a bump moves
  them noticeably, they are worth recording here.
- armeabi-v7a was checked only structurally: it carries the same databases and the same
  backends, but its numerics were not compared against the 64-bit slices. The C++ core
  formats solver diagnostics with `%Lg`, and `long double` is the same width as `double` on
  32-bit ARM, so a numeric spot-check on a v7a device is worth doing rather than assuming.
- Bumping the recipe means bumping `examples/property-check/pyproject.toml` and rebuilding
  it — its nine cross-checks against IAPWS-95, NIST and ASHRAE values are the closest thing
  this recipe has to a numerical regression test. If a row is ever added or retargeted,
  check that the published figure is quoted for the state the call actually computes: the
  familiar 997.047 kg/m³ for water at 25 °C is the density at 101325 Pa, and comparing it
  against a `Q=0` call buys a spurious 4.4e-5 that looks like an EOS disagreement.
