# pyerfa

[`pyerfa`](https://pyerfa.readthedocs.io/) wraps
[ERFA](https://github.com/liberfa/erfa) — the BSD-licensed derivative of the IAU's SOFA
library — as roughly 250 [numpy ufuncs](https://numpy.org/doc/stable/reference/ufuncs.html):
time-scale conversions between UTC, UT1, TAI, TT and TDB, precession and nutation, Earth
rotation, and the full catalogue-to-observed astrometry chain. It is the numerical core
underneath [astropy](https://www.astropy.org/), and small enough to use without it. On a
phone every one of those calculations runs offline, because the constants ERFA needs are
compiled into the extension rather than read from a data directory.

Import the package as `erfa`, not `pyerfa`.

## Install

Add PyERFA to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pyerfa",
]
```

`numpy` is installed automatically.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sky-clock`](examples/sky-clock) — runs the device clock through five time scales and
  places five stars over a chosen site.

## Usage in a Flet app

Convert a time, then transform a position. Both are ordinary function calls returning numpy
values, so the result drops straight into a Flet control:

```python
import math

import erfa

utc1, utc2 = erfa.dtf2d("UTC", 2026, 8, 20, 21, 0, 0.0)
tt1, tt2 = erfa.taitt(*erfa.utctai(utc1, utc2))
*_, hmsf = erfa.d2dtf("TT", 3, tt1, tt2)  # 21:01:09.184

astrom, _ = erfa.apco13(
    utc1, utc2, dut1,
    math.radians(2.3522), math.radians(48.8566), 35.0,  # east longitude, latitude, metres
    0.0, 0.0, 1013.25, 12.0, 0.5, 0.55,
)
azimuth, zenith = erfa.atioq(*erfa.atciq(ra, dec, pr, pd, px, rv, astrom), astrom)[:2]
label.value = f"{math.degrees(math.pi / 2 - zenith):.2f}° above the horizon"
```

Angles are radians and times are two-part Julian dates throughout, and neither is checked for
you — the `math.radians` calls above are the whole defence against a site in degrees. The
split into two doubles is not decoration either: a single float64 Julian date resolves to about
40 microseconds near the present epoch, while the day-plus-fraction pair keeps sub-microsecond
precision.

### Storage

**PyERFA reads nothing from disk.** The leap-second table, the precession-nutation series and
every other constant are C data inside `erfa/ufunc.abi3.so`, and the shipped Python imports
only `numpy`, `warnings`, `datetime`, `threading` and `functools` — no `open()`, no
`__file__`, no package data. (`erfa/version.py` also imports `ctypes`, but only on the
fallback path taken when the bundled `ufunc` fails to import, which is a system-`liberfa`
build rather than this one.) It therefore needs no
[`extract_packages`](https://flet.dev/docs/publish/android/) entry on Android and no assets
directory, and it behaves identically from a zipped `sitepackages.zip`.

What an app may want to store is what ERFA cannot compute for itself: a refreshed leap-second
table, or a current UT1−UTC. Ship a fixed snapshot in the
[assets directory](https://flet.dev/docs/cookbook/assets); put a downloaded copy in
[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data),
or in [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
if you would happily fetch it again.

### Threading

**The ufuncs release the GIL.** On desktop, two threads each transforming a 100,000-star
array through `apco13`/`atciq`/`atioq` finished in 24 ms against 48 ms for the same two calls
run serially, while a deliberately GIL-bound loop measured the same way showed no speedup at
all. So [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
buys real parallelism here. Catch exceptions inside the worker and finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which auto-update
does not reach.

Note the absolute figure, though: 100,000 stars in 25 ms. ERFA arithmetic is seldom what makes
a screen slow, so thread to keep the UI free while everything *around* the call happens.

Reach for arrays before threads, and build the astrometry context once rather than per star.
[`atco13`](https://pyerfa.readthedocs.io/en/latest/api/erfa.atco13.html) rebuilds it every
call, and that is the one way to make ERFA slow: over 100,000 stars it measured 20 µs per
star on desktop, against 0.23 µs for
[`apco13`](https://pyerfa.readthedocs.io/en/latest/api/erfa.apco13.html) once plus
[`atciq`](https://pyerfa.readthedocs.io/en/latest/api/erfa.atciq.html) and
[`atioq`](https://pyerfa.readthedocs.io/en/latest/api/erfa.atioq.html) — about 85 times
faster, for answers agreeing to better than a nanoarcsecond. Two seconds against twenty-five
milliseconds, for the same sky.

One shared mutable exists:
[`erfa.leap_seconds.set()` and `.update()`](https://pyerfa.readthedocs.io/en/latest/api.html#module-erfa.leap_seconds)
replace a process-wide C table. Call them at startup, not from a worker while another thread
is converting times.

### Leap seconds and UT1

Two numbers stand between a device clock and a correct sky, and they behave very differently.

**Leap seconds are compiled in.** The table inside the wheel is the one shipped with ERFA
2.0.1 (SOFA release 20231011): 42 entries ending 2017‑01‑01, where TAI−UTC became 37 s. That
value is still correct, because no leap second has been introduced since. Two things
nonetheless look alarming. `erfa.leap_seconds.expires` reports **2017‑06‑30** and
`erfa.leap_seconds.expired` is `True` — that is pyerfa's own heuristic, 180 days past the last
entry, not evidence of a wrong answer. ERFA's own guard fires further out: dates after **2028**
emit `ErfaWarning: ERFA function "dat" yielded 1 of "dubious year (Note 1)"` while still
returning 37 s. If a leap second is announced before your app is next rebuilt, feed it in
without any dependency on astropy:

```python
import numpy as np

erfa.leap_seconds.update(np.array([(2028, 1, 38.0)], dtype=erfa.dt_eraLEAPSECOND))
```

**UT1−UTC cannot be compiled in at all.** It is the Earth's measured rotation angle, published
daily by the [IERS](https://datacenter.iers.org/eop.php) and never predictable to full
accuracy. Every function taking a `dut1` argument accepts `0.0` and returns a plausible answer;
what you lose is bounded but not small. The quantity is kept within ±0.9 s, and 0.9 s of Earth
rotation is 13.5 arcseconds. Projected onto the sky, a desktop check of five bright stars at
one site moved them between 10 and 14 arcseconds — except Polaris, which moved 0.15", because
the error is a rotation about the celestial pole. That is fine for a star chart, marginal for a
telescope pointing model, and irrelevant to the time scales themselves: UTC, TAI, TT and TDB
are unaffected by it.

Polar motion (`xp`, `yp`) is the same kind of unknowable, but it is a couple of tenths of an
arcsecond. Passing zeros costs well under an arcsecond and is the normal choice offline.

### App size

The wheels are approximately 0.3 MB compressed and 1.4–1.6 MB unpacked, of which the single
`erfa/ufunc.abi3.so` is 0.47–0.69 MB depending on architecture. PyERFA is not what makes an app
big — `numpy`, which it requires, is roughly 6.8 MB compressed for Android arm64‑v8a on its own.

`erfa/tests/` accounts for about 170 KB of the unpacked total and nothing imports it, so
Flet's [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) can drop it:

```toml
[tool.flet.cleanup]
package_files = ["erfa/tests"]
```

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when the
application does not need every ABI. These are package figures, not the amount added to the
final APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's `cp39-abi3` wheel, which vendors the same ERFA release as this
recipe: the Android and iOS extensions both report ERFA 2.0.1 and SOFA 20231011 and both carry
a leap-second table ending 2017‑01‑01 at 37 s, so laptop and phone agree. The exception is a
system package rather than a wheel — pyerfa can be built against a distribution's `liberfa` via
`PYERFA_USE_SYSTEM_LIBERFA`, taking that library's version and table. Print
`erfa.version.erfa_version` when two machines disagree.

## Things to know

- **ERFA reports problems as warnings and errors, and the warnings are easy to miss.**
  `ErfaWarning` subclasses `UserWarning` and `ErfaError` subclasses `ValueError`. Under
  Python's default filter a warning is shown once per call site, so a UI recomputing every
  second logs the dubious-year warning once and then looks clean forever. Promote it when a
  suspect answer must not reach the screen:

  ```python
  with warnings.catch_warnings():
      warnings.simplefilter("error", erfa.ErfaWarning)
      tai1, tai2 = erfa.utctai(utc1, utc2)
  ```

  A genuinely invalid input raises instead: `erfa.dtf2d("UTC", 2026, 2, 30, 12, 0, 0.0)` fails
  with `ErfaError: ERFA function "dtf2d" yielded 1 of "bad day"`.

- **Proper motion in right ascension is dRA/dt, not μα·cos δ.** Catalogues publish the second
  form; ERFA's `atciq`, `atco13` and friends want the first, so the published value must be
  divided by cos δ. The divisor is 1.01 for a star near the equator and 78 for Polaris. Nothing
  raises: the position is simply wrong, and wrong by an amount that starts at zero on the
  catalogue epoch and grows linearly away from it. In a desktop check of five bright stars it
  was 0.01" to 1.6" for 2026 and 0.02" to 6" for 2100. Do not read the divisor as the damage —
  Polaris moves only 1.2" despite a divisor of 78, because the same cos δ that inflates the
  divisor compresses the resulting error in RA into a short arc on the sky.

- **Parallax is in arcseconds, not milliarcseconds.** This is the same class of mistake as the
  one above and a far more expensive one: feeding a catalogue's mas value straight in moved the
  same five stars by 6" to 334" in a desktop check. Radial velocity is km/s.

- **Everything comes back as numpy.** Floating-point results are `numpy.float64`, which
  subclasses `float` and causes no trouble. Integer results are `numpy.int32`, which does
  **not** subclass `int`: `isinstance(year, int)` is `False` and `json.dumps` refuses it with
  `TypeError: Object of type int32 is not JSON serializable`. Wrap calendar fields in `int()`
  before they leave your code. Structured returns are stranger still:
  [`d2dtf`](https://pyerfa.readthedocs.io/en/latest/api/erfa.d2dtf.html) hands back year, month
  and day and then a single record carrying `h`, `m`, `s` and `f`, so it unpacks as
  `*_, hmsf = erfa.d2dtf(...)` and not as seven values.

- **PyERFA is not astropy, and the missing part is the data.** ERFA supplies the algorithms;
  astropy's [`iers`](https://docs.astropy.org/en/stable/utils/iers.html) module supplies the
  Earth-orientation and leap-second tables that keep them current, along with `Time` and
  `SkyCoord`. Here you get the algorithms without the downloader — which is exactly why the
  package works offline, and why the UT1 and leap-second questions above are yours.

## Build notes (maintainers)

### Recipe shape

This is a plain sdist recipe with no patches and no `build.sh`. PyERFA's sdist carries the
complete `liberfa` tree — 251 C files, 249 of which its `setup.py` compiles straight into
`erfa.ufunc` (the two `t_*.c` test harnesses are skipped) — so a separate `flet-liberfa`
native-library recipe would add a link step without removing one, and the resulting extension
is self-contained: on Android it needs only `libm`/`libdl`/`libc`/`libpython`, and on iOS only
`libSystem` and the Python framework.

`setup.py` does shell out to liberfa's autotools `configure`, unconfigured for the target, and
that is why no cross-compile patch is needed: the resulting `config.h` is read by exactly one
file, `erfaversion.c`, purely to report version strings, with a `configure.ac`-scanning fallback
if the run fails. `PYERFA_USE_SYSTEM_LIBERFA` is deliberately left unset.

### Upgrade hazards

The consumer sections above quote three things that move with the bundled ERFA release and
nothing else: the leap-second table's final entry, the year past which `eraDat` calls a date
dubious, and the ERFA/SOFA version pair. A pyerfa version bump can change all three silently
while every test still passes, because a stale table returns a plausible number rather than an
error.

`numpy` is a build-time requirement (`>=2.0.0rc1` upstream, pinned as a host requirement here)
as well as a runtime one. The extension is built with `Py_LIMITED_API` at 3.9, but the wheels
are still produced and tagged per interpreter, so each Python leg is a real build.

### Re-verification checklist

- **Leap seconds:** Read the table out of a built wheel, not the recipe, and update the entry
  count, final date and TAI−UTC quoted above along with `erfa.leap_seconds.expires`, which is
  derived from that entry. On desktop that is `erfa.leap_seconds.get()[-1]`. A mobile wheel
  cannot be imported on the build host, but the table is a plain array of
  `{int year; int month; double delat}`: searching the extension for
  `struct.pack("<iid", 2017, 1, 37.0)` and walking back in 16-byte steps counts the entries
  directly, which is how the figures above were confirmed in the Android and iOS extensions
  rather than inferred from the version string.
- **Dubious-year boundary:** Find it by bisecting `erfa.dat`; it tracks ERFA's internal
  verification year, not the table.
- **Versions:** Confirm `erfa.version.erfa_version` and `sofa_version` on both platforms and
  against the current PyPI desktop wheel.
- **Self-containment:** Re-check the Android `DT_NEEDED` list and the iOS Mach-O load commands,
  and that no shipped module gained an `open()` or a `__file__` lookup. The storage guidance
  and the "no `extract_packages`" advice both rest on those staying empty.
- **Size:** Re-measure compressed and unpacked figures, and the `erfa/tests` share, from the
  resulting wheels.

### Coverage gaps

The device tests cover importing `erfa` and one `cal2jd` round trip — enough to prove the
vendored C and the numpy ufunc glue load and run, and no more. They do not exercise the
time-scale chain, the leap-second table or its update path, the astrometry transforms, the
warning and error machinery, or anything vectorised over an array. Every claim above about
those areas comes from desktop measurement or wheel inspection, not an on-device run.
