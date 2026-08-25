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

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`property-check`](examples/property-check) — fluid properties cross-checked against published reference values.

## Usage in a Flet app

One [`PropsSI`](https://coolprop.org/coolprop/HighLevelAPI.html) call answers most
questions, and its result is a plain float that goes straight into a
[`ft.Text`](https://flet.dev/docs/controls/text/):

```python
from CoolProp.CoolProp import PropsSI

t_sat = PropsSI("T", "P", 101325, "Q", 0, "Water")
readout = ft.Text(f"Water boils at {t_sat - 273.15:.2f} °C at 1 atm")
```

The `import` on the first line is the expensive part of that snippet, not the call. Run it
inside [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
with a frame already on screen, and bind the module to something your handlers can reach
afterwards.

### Storage

By default CoolProp writes nothing and reads nothing — it never touches the filesystem.

The exception is the [tabular backends](https://coolprop.org/coolprop/Tabular.html)
(`BICUBIC&HEOS`, `TTSE&HEOS`), which build an interpolation table per fluid and cache it
under `$HOME/.CoolProp/Tables/`. Measured on desktop, one fluid costs **16–19 MB** on disk
(`AbstractState("BICUBIC&HEOS", "n-Propane")` wrote 15,921,841 bytes; R134a wrote
18,893,141) and the default cap on that directory is 1 GB. If you use them, redirect the
cache into [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
before the first tabular call:

```python
import os

import CoolProp.CoolProp as CP

cache = os.getenv("FLET_APP_STORAGE_CACHE", ".")
CP.set_config_string(
    CP.ALTERNATIVE_TABLES_DIRECTORY, os.path.join(cache, "coolprop-tables") + os.sep
)
```

**End that path with a separator.** CoolProp concatenates the value with the backend
descriptor and inserts nothing between them, so `.../coolprop-tables` without the trailing
`os.sep` creates a *sibling* directory named after the backend instead of writing inside
the one you named — no error, just tables in the wrong place and a cache that never hits.

Where `$HOME` resolves to under Flet on Android and iOS is not established here, which is a
second reason to set the path rather than let CoolProp choose it.

### Threading

**CoolProp never releases the GIL.** Neither shipped extension imports the symbols Cython's
`with nogil` compiles to, so a call holds the interpreter for its whole duration.

That is fine for almost everything it offers, because almost every call is short. In a
desktop canary sampling a 1 kHz ticker, 5000 `PropsSI` calls costing 2.0 s in total delayed
the ticker by at most **8.4 ms** — the interpreter switches between calls, so a sweep of
thousands of points stays responsive. (The same canary was blocked for the whole 2.1 s of a
single `sum(range(3e8))`.)

Push sweeps to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) and end
the handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads, and `run_thread` swallows worker exceptions, so wrap the body
in `try/except` and render what it caught.

What no thread saves you from is a **single** long call, and CoolProp has one: constructing
a tabular [`AbstractState`](https://coolprop.org/coolprop/LowLevelAPI.html) builds the
table. `AbstractState("BICUBIC&HEOS", "R32")` took 7.8 s in that canary and blocked the
ticker for all 7.8 s.

CoolProp imposes no thread rules of its own — there is no shared handle to serialise — but
an `AbstractState` is a mutable object holding one state point, so give each thread its own
rather than sharing one.

### App size

The wheel is roughly **5.7–5.8 MB compressed** and **10.6–10.9 MB unpacked** per
architecture, about 9 MB of which is the two extensions and the databases inside them.
Counting what installs alongside it, a slice costs approximately **13.0 MB on Android**
(coolprop 5.78 + numpy 6.85 + flet-libcpp-shared 0.41) and **12.3 MB on iOS**
(5.69 + 6.59).

About 1.5 MB of every wheel is ballast your app never touches, and Flet's package cleanup —
[on by default](https://flet.dev/docs/publish/#compilation-and-cleanup) — already removes
most of it: on mobile it deletes `**.h`, `**.hpp`, `**.pxd` and `**.pyx` from
site-packages, which is the 1.19 MB header tree under `CoolProp/include/` and the Cython
declaration files beside it. What survives is Python source and one 134 KB data file, so
name those yourself if the last few hundred KB matter:

```toml
[tool.flet.cleanup]
package_files = ["CoolProp/Plots", "CoolProp/GUI", "CoolProp/tests", "**CoolProp/*.bib"]
```

Drop `CoolProp/Plots` from that list if you added `matplotlib` in order to use it.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not
the exact amount added to the final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's own CoolProp wheel rather than this one. The API and the
fluid data are the same; the environment is not, and three of the differences hide a mobile
failure. Every timing and memory figure on this page is a desktop figure, so measure the
import, a sweep and the resident-set growth on the device you ship to — the
[`property-check`](examples/property-check) example prints all three on screen. `$HOME`
exists at a desk, so the tabular cache works there without being told where to go and the
trailing-separator trap above costs nothing visible; set `ALTERNATIVE_TABLES_DIRECTORY` in
the desktop run too, so both targets exercise the same path. And the package's non-code
files exist at a desk, so the two helpers that read them succeed there and not in a built
app (below).

## Things to know

- **CoolProp does not police its own inputs, and will answer an impossible question with a
  confident number.** `PropsSI("Tmax", "Water")` reports 2000 K, and `PropsSI("D", "T",
  100000, "P", 101325, "Water")` still returns `0.0021954…` — no exception, no warning, no
  NaN. Nitrogen below its triple point does the same (`T` = 50 K against `Ttriple` 63.151 K
  returns 919.35 kg/m³), and `DONT_CHECK_PROPERTY_LIMITS` is already off. **Range-check
  before you call**, reading the bounds out of CoolProp itself with
  `PropsSI("Tmin"/"Tmax"/"pmax", fluid)`. Some paths do refuse cleanly and are worth
  preferring where you have the choice — saturation calls outside the dome, the
  incompressible backend and
  [`HAPropsSI`](https://coolprop.org/fluid_properties/HumidAir.html) each raise with the
  offending value and the valid range in the message. Even there it is not uniform: water
  at 200 K and 1 atm raises only as a solver failure (*"Inputs in Brent […] do not bracket
  the root"*), while a saturation pressure below the triple point returns silently.
- **`import CoolProp` is the expensive thing in the whole package.** On a fast desktop it
  costs about **110 MiB of resident memory and 480–540 ms**, and `-X importtime` puts 440 ms
  of that in the package `__init__` body, which unconditionally asks the extension for the
  full fluid list and so forces the embedded database to be decompressed and parsed. There
  is no lazy path and no way to load a subset, and it is unavoidably both extensions: the
  package `__init__` imports `constants`, which imports `_constants`. Do the import inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  something on screen, and budget the memory — device figures are not established here, and
  the [`property-check`](examples/property-check) example prints them.
- **`PropsSI` rebuilds its backend on every single call.** Reusing one
  [`AbstractState`](https://coolprop.org/coolprop/LowLevelAPI.html) is two to three orders of
  magnitude faster: over the same 200-point saturation sweep the example measures around
  80 µs per `PropsSI` call against well under 1 µs per `state.update(...)` on a desktop, and
  prints the ratio it gets on the device.
  Water is also unusually expensive per construction — 419 µs for a `D|PT` call, against
  82 µs for the same call on R134a — because it builds superancillary curves each time;
  [`set_config_bool(ENABLE_SUPERANCILLARIES, False)`](https://coolprop.org/coolprop/Configuration.html)
  brings it to 89.8 µs with the answer unchanged to six digits.
- **The wheel's non-code files are not there to be read on a device.** CoolProp ships a
  134 KB BibTeX bibliography, a tree of C++ headers and a config file belonging to a
  Python 2-era plotting module nothing imports.
  [`copy_BibTeX_library()` and `get_include_directory()`](https://coolprop.org/coolprop/wrappers/Python/index.html)
  go looking for them, and in a built app they are not there to find: cleanup deletes the
  headers on both platforms, and on Android what remains lives inside a zipped
  site-packages that an ordinary file read cannot open. Nothing else in the package opens a
  file — the fluid and incompressible databases live *inside* the extension rather than
  beside it — so those two helpers are the entire cost of the zipped layout.
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
- **`numpy` is declared but not required.** The extension imports it inside a `try` and uses
  it to return an `ndarray` when you pass lists to `PropsSI`, falling back to a plain `list`
  when it is absent — with numpy uninstalled, only `CoolProp.Plots` fails. You cannot drop
  it from the install, but nothing in your app has to import it.

## Build notes (maintainers)

### Recipe shape

A stock scikit-build-core/CMake cross-build of upstream's own tree; nothing needed splitting
out. `patches/mkdir-cython-output.patch` explains itself in its own preamble; `meta.yaml`
carries no comments at all, so its build flags are undocumented where a reader would look for
them — next to the settings.

Two per-platform consequences, before anyone reads a wheel and wonders: the Android
extensions carry a CPython ABI tag and link `libc++_shared.so`, which is why the Android
wheel alone declares `flet-libcpp-shared` in its `Requires-Dist`; the iOS extensions link
the OS's own `/usr/lib/libc++.1.dylib` and ship unstripped, which is what makes the iOS
extension the larger of the two even though its `__text` is the smaller.

### Upgrade hazards

- The silent-extrapolation behaviour is upstream's, and it is the sharpest claim on this
  page. Re-check it after a bump: if CoolProp ever starts raising on `PropsSI("D", "T",
  100000, "P", 101325, "Water")`, the first bullet of *Things to know* and the third section
  of the `property-check` example both become wrong.
- Bumping the recipe means bumping `examples/property-check/pyproject.toml` and rebuilding
  it — its nine cross-checks against IAPWS-95, NIST and ASHRAE values are the closest thing
  this recipe has to a numerical regression test. If a row is ever added or retargeted,
  check that the published figure is quoted for the state the call actually computes: the
  familiar 997.047 kg/m³ for water at 25 °C is the density at 101325 Pa, and comparing it
  against a `Q=0` call buys a spurious 4.4e-5 that looks like an EOS disagreement.
- The `ALTERNATIVE_TABLES_DIRECTORY` concatenation is what makes the trailing separator
  load-bearing. If upstream ever joins that path properly, the *Storage* warning becomes
  noise and should go.

### Re-verification checklist

- The counts quoted above — 124 fluids, 310 aliases, 74 + 52 incompressibles, 105 predefined
  mixtures — come from the shipped binary and from a desktop CoolProp of the same upstream
  version, not from a test. Re-read them off a built wheel after a bump, and preferably add
  the assertions to `tests/` so the next bump cannot move them silently. When comparing two
  slices, compare the **raw** decompressed blobs: iOS serialises the fluid and incompressible
  arrays in a different order from Android, and hashing after a `json.loads` and re-dump
  canonicalises that away, so it would report identity where there is none.
- Every size, timing and memory figure here is measured, not estimated, and quoted decimal.
  Re-measure rather than adjusting by eye; the ballast breakdown in particular is a
  `unzip -l` sum, so use that rather than `du`.
- Confirm neither extension has acquired `PyEval_SaveThread`/`PyEval_RestoreThread` before
  repeating the never-releases-the-GIL claim; that is the whole evidence for it.
- Test from zipped site-packages on Android. The page states the package needs no
  `extract_packages`; add one to consumer guidance only if a real runtime filesystem read
  makes it mandatory, and include the failure symptom.
- The import cost, the `PropsSI`-versus-`AbstractState` gap and the RSS figures are
  **desktop** numbers. The example prints the device equivalents on screen; if a bump moves
  them noticeably, they are worth recording here.
- Where `$HOME` resolves under Flet on each platform is still unestablished. Establish it
  once and the *Storage* hedge can be replaced with a statement.

### Coverage gaps

`tests/` verifies almost nothing this page claims. Both tests call only `PropsSI` on water
(a saturation temperature and a saturated-liquid density), and `test_phase_envelope`
additionally misdescribes itself — it builds no phase envelope and touches no humid-air
path. A green CI run today proves the extension imports and that water boils. Nothing on
device exercises the tabular backends or their cache redirect, `HAPropsSI`, the
incompressible or mixture backends, the config setters, or the silent-extrapolation
behaviour; the `property-check` example is the only thing that touches any of them.

armeabi-v7a was checked only structurally: it carries the same databases and the same
backends, but its numerics were not compared against the 64-bit slices. The C++ core formats
solver diagnostics with `%Lg`, and `long double` is the same width as `double` on 32-bit ARM,
so a numeric spot-check on a v7a device is worth doing rather than assuming.
