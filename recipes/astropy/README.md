# astropy

[astropy](https://docs.astropy.org/) is the core library of Python astronomy: physical
units and quantities that refuse to be added wrongly, the time scales real observations are
recorded in (UTC, TAI, TT, TDB, UT1), celestial coordinate frames and the transforms between
them, [FITS](https://docs.astropy.org/en/stable/io/fits/) and
[VOTable](https://docs.astropy.org/en/stable/io/votable/) I/O, WCS, tables, convolution,
statistics and cosmology.

A phone is a plausible place for all of that: it knows where it is and what time it is, and
it is the thing you actually carry to a telescope. The catch is that astronomy is
data-hungry, and a phone may have no network. This page is mostly about which half of
astropy still works when it doesn't — the short answer being *most of it*, from tables that
ship inside the wheels.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "astropy",
]

[tool.flet.android]
extract_packages = ["astropy", "astropy_iers_data"]
```

The [`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) list is
**not optional on Android**. Flet ships pure-Python site-packages inside `sitepackages.zip`
and imports from it with `zipimport`, and both packages read data files through a real
`Path(__file__).parent / …` path, which a zip cannot serve:

- **`astropy`** reads `astropy/CITATION` in its own package `__init__`, so leaving it out
  breaks `import astropy` itself.
- **`astropy_iers_data`** builds the paths to its Earth-orientation tables the same way, and
  leaving *that* one out is the nastier failure, because the app looks healthy: it launches,
  units and `Time` conversions between UTC, TAI, TT and TDB work, ICRS→galactic works, and
  then `Time.ut1` and every AltAz transform die with an uncaught `NotADirectoryError` whose
  path has `sitepackages.zip` as a directory component.

Both are **import** names — `astropy_iers_data` with underscores, not the `astropy-iers-data`
distribution name — and both have to be in *your* `pyproject.toml`.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`offline-almanac`](examples/offline-almanac) — sky positions and time scales with the
  network switched off, and a slider that walks the date past the end of the bundled tables.

## Usage in a Flet app

Point astropy at Flet's app storage, switch the network off, then transform a position. The
whole startup sequence belongs in one place, because the first eight lines have to run before
`import astropy` does:

```python
import os
import tempfile

temp = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
data = os.getenv("FLET_APP_STORAGE_DATA") or temp
config_dir = os.path.join(data, "astropy", "config")
cache_dir = os.path.join(temp, "astropy", "cache")
os.makedirs(config_dir, exist_ok=True)   # the load-bearing half — see Storage
os.makedirs(cache_dir, exist_ok=True)
os.environ.setdefault("ASTROPY_CONFIG_DIR", config_dir)
os.environ.setdefault("ASTROPY_CACHE_DIR", cache_dir)

import astropy.units as u  # noqa: E402
import astropy.utils.data  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402
from astropy.utils import iers  # noqa: E402

iers.conf.auto_download = False
astropy.utils.data.conf.allow_internet = False

berlin = EarthLocation(lat=52.520008 * u.deg, lon=13.404954 * u.deg, height=34 * u.m)
m31 = SkyCoord(ra=10.684708 * u.deg, dec=41.268750 * u.deg, frame="icrs")
altaz = m31.transform_to(AltAz(obstime=Time.now(), location=berlin))

label = ft.Text(f"M31  alt {altaz.alt.deg:+.2f}°  az {altaz.az.deg:.2f}°")
```

Import `astropy.utils.data` by name, as above: plain `import astropy` leaves it unbound and
the second switch dies with `AttributeError: module 'astropy.utils' has no attribute 'data'`.

### Storage

astropy resolves its configuration directory *while `import astropy` is still running* (the
logger's config items force it), and if nothing tells it where that is, it falls back to
`Path.home()`. The Flet iOS runtime has no `pwd` module to fall back to when `HOME` is unset,
so the import dies with `RuntimeError: Could not determine home directory.` — before any
astronomy happens. That is what the preamble prevents.

**The `os.makedirs` calls are the load-bearing half, not the `os.environ` ones.** astropy 8
ignores `ASTROPY_CONFIG_DIR` / `ASTROPY_CACHE_DIR` unless the directory already exists: it
emits `AstropyUserWarning: ASTROPY_CONFIG_DIR is set to … but no such file or directory was
found. This environment variable will be ignored.` and falls back to `Path.home()`, i.e.
straight back into the crash above. Setting the variables without creating the directories is
worse than not setting them at all, because most apps never surface that warning — and code
written against astropy 7, which only set the variables, regresses here.

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the right home for the config directory — app-private, backed up, never auto-deleted — and
[`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for the cache. With downloads off astropy writes nothing into either; they just have to exist.
Files your app produces belong in `FLET_APP_STORAGE_DATA` too — `astropy.io.fits` writes to
whatever path you hand it.

### Threading

The expensive moment is the first Earth-orientation lookup, not the astronomy. Opening the
table parses ~20,000 rows out of the two bundled files — 330 ms on a development machine, and
a phone is slower — after which astropy caches it and an AltAz transform takes about 1 ms on
that same machine. The imports cost a further ~280 ms there.

So do the first transform in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) rather
than on the first frame, catch broadly inside the worker, and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads, and `run_thread` never retrieves the worker's future, so an
exception in it surfaces nowhere at all.

Unit and angle *string* parsing is explicitly made thread-safe upstream:
`astropy/utils/parsing.py` wraps the generated PLY lexer and parser in locks. Nothing else
here is documented as safe to share, so give each worker its own objects.

### Working offline

Units, time scales, coordinates, cosmology and I/O all work from data inside the wheels, and
`import astropy` opens no socket and creates no file. The Earth-orientation and leap-second
tables live in [`astropy-iers-data`](https://pypi.org/project/astropy-iers-data/), a separate
pure-Python distribution that astropy hard-depends on and that resolves from PyPI. Three of
its files are tables:

| File | Size | What it is |
|---|---:|---|
| `finals2000A.all` | 3.8 MB | IERS-A: Earth orientation, including the predictions |
| `eopc04.1962-now` | 5.2 MB | IERS-B: the definitive values, substituted over IERS-A's |
| `Leap_Second.dat` | 1.4 kB | the leap-second table |

The first two are load-bearing and do not fail helpfully: measured with one actually removed,
`Time.ut1` and every AltAz transform raise `AttributeError: 'NoneType' object has no attribute
'group'` from astropy's CDS reader (`astropy/io/ascii/cds.py`), naming neither the file nor
the reason. Leap seconds are the robust part — `pyerfa` carries a 42-row table compiled into
its extension, so UTC↔TAI/TT still returns the right answer (measured: TAI−UTC = 37 s) with
all three files unreadable.

Four APIs are downloads with **nothing** bundled behind them, and they raise offline rather
than degrading. They are, unhelpfully, the ones a tutorial reaches for first:

- `EarthLocation.of_site(...)` and `EarthLocation.get_site_names()` → `URLError`; there is no
  site catalogue in the wheel, so hard-code an `EarthLocation` instead
- `SkyCoord.from_name(...)` → `NameResolveError` from Sesame
- `EarthLocation.of_address(...)` → `NameResolveError` from the geocoder
- `solar_system_ephemeris.set("jpl")` → `ModuleNotFoundError` before it reaches the network:
  `jplephem` is not installed, and the JPL kernels are large downloads anyway

The substitutes are good, and each was confirmed to return a value with a socket audit hook
watching: `get_body()` for the Sun, Moon and planets on the built-in ERFA ephemeris,
`get_constellation()` from a table in the wheel, and the bundled `Planck` and `WMAP`
cosmologies.

**Set both kill switches, not one.** Checked across all four combinations, counting sockets
and asserting an answer came back: `auto_download = False` alone silences the
Earth-orientation path but leaves `of_site` reaching for the network; `allow_internet = False`
alone stops the sockets but still emits the warnings. Only both give zero sockets and zero
warnings on the transform path.

The cost of skipping them is a frozen UI. `auto_download` defaults to **True**, so a
`Time.ut1` lookup tries two download URLs at `iers.conf.remote_timeout` = 10 s each, and
re-tries on *every* subsequent call because a failed download caches nothing. A transform
costs two lookups, not one — measured with an audit hook on `urllib.Request`, **four**
requests and **six** `IERSWarning`s per AltAz transform, every transform. Where the network
blackholes rather than refusing, as behind a captive portal, that multiplies out to roughly
20 s of frozen UI for a bare `Time.ut1` and about 40 s for an AltAz transform; airplane mode
refuses at once. Either way the call then falls back to
the bundled table and produces the identical answer.

One API escapes both switches: `EarthLocation.of_address()` calls `urllib.request.urlopen`
itself instead of going through `astropy.utils.data`, so with both off it still connects to
`nominatim.openstreetmap.org` before raising. No setting stops it; do not call it. If your app
genuinely wants fresher tables, refresh explicitly in `page.run_thread(...)` behind a
user-visible control — never on the transform path.

### Stale tables and the silent freeze

The bundled IERS-A table carries roughly a year of predictions past its last measured value:
the copy measured here runs to 2027-08-21, with genuine values only to 2026-08-13.

**Past the end of the table, UT1−UTC is clamped to its last value with no exception and no
warning.** The `iers_degraded_accuracy` setting defaults to `error` but never fires here,
because its own documentation scopes it to IERS-B used on its own rather than to the default
`IERS_Auto`. The only warning you do get is about polar motion — a much smaller effect. The
loud warning covers the small error and the big one is mute.

The damage is bounded, but the bound is on the *difference* between the frozen value and the
true one, and leap seconds cap each of the two at 0.9 s independently, so that difference
reaches 1.8 s. One second of UT1 error turns the sky by 15.04″ × cos(dec): measured on an
AltAz transform from Berlin, 11.28″/s for M31 at dec +41°, 15.04″/s on the celestial equator,
0.17″/s for Polaris. The ceiling is therefore **~27″**, and ~15″ against the value this build
freezes at (−0.068 s). A planetarium or field-observing app can ship on the bundled tables and
say so; arcsecond astrometry cannot.

Do not rely on astropy to tell you the tables are stale — read the span off the table and put
it on screen:

```python
mjd = np.asarray(iers.IERS_Auto.open()["MJD"].value, dtype=float)
days_left = mjd.max() - Time.now().mjd
```

The leap-second table has an explicit expiry, `iers.LeapSeconds.from_erfa().expires` —
2027-06-28 in the copy measured here. **Read it after your first time conversion, not at
startup.** astropy loads `Leap_Second.dat` into ERFA lazily, on the first UTC↔TAI/TT
conversion; before that it returns pyerfa's compiled-in **2017-06-30**, so a staleness check
on the first frame reports a table nine years out of date. Past the real expiry ERFA flags
conversions with `ErfaWarning: … "dubious year"`, which appeared for dates in late 2028 on.

### App size

Approximately 6.4–6.6 MB compressed and 22–25 MB unpacked per architecture (Android
arm64-v8a 6.5 / 23.1, armeabi-v7a 6.4 / 22.4, iOS device 6.6 / 24.2).

**9.5 MB of that unpacked payload, across 738 of the wheel's 1434 entries, is astropy's own
`tests` data** — `m13.fits`, `1904-66_AZP.fits`, the VOTable validator's corpora — which your
app will never import. Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) leaves them alone,
since it strips headers, static archives and `__pycache__`:

```toml
[tool.flet.cleanup]
package_files = ["astropy/*/tests", "astropy/*/*/tests",
                 "astropy/*/*/*/tests", "astropy/*/*/*/*/tests"]
```

Four patterns because the subpackages nest that deep — `astropy/io/fits/hdu/compressed/tests`
is real. **Do not add `astropy/tests` itself**: `astropy/__init__.py` runs
`from .tests.runner import TestRunner` at import time, so dropping that one directory breaks
`import astropy`, and it is 70 kB anyway.

The rest of the stack: `astropy-iers-data` is 2.0 MB compressed and 8.9 MB unpacked, pyerfa
0.3 / 1.4–1.6, numpy 6.5–8.2 / 19–27 — roughly 15–17 MB of wheels and 52–61 MB unpacked
before your own assets. Flet compiles `.py` to `.pyc` and zips site-packages, so what lands on
the device is smaller than the unpacked figure; the wheel sizes are the honest floor. On
Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, and apart from build metadata and one Android
compiler directive every `.py` in these wheels is byte-identical to that release. So
[upstream's documentation](https://docs.astropy.org/en/stable/) applies unchanged and anything
you work out on a laptop transfers — except the platform-, loader- and size-dependent things
this page is about, which a desktop run cannot show you.

The two failures this page opens with split by platform in opposite directions — the
home-directory crash is iOS's, because Android's Python ships `pwd`; the `sitepackages.zip`
reads are Android's — so write the preamble and both `extract_packages` entries once and
neither gets a chance to surprise you. Validate on a device or simulator regardless: the zip
behaviour was reproduced with a real `zipimport` on the build host, not on a phone.

## Things to know

- **The light-year is `u.lyr`, not `u.ly`.** `u.ly` raises `AttributeError`, and an unhandled
  exception in a Flet event handler produces a crash screen rather than a message. More
  generally, wrap anything that parses user input in a broad `except Exception`: astropy
  raises its own
  [`UnitConversionError`](https://docs.astropy.org/en/stable/api/astropy.units.UnitConversionError.html)
  (measured: `Can only apply 'add' function to quantities with compatible dimensions` for
  `1*u.m + 1*u.s`) but also plain `ValueError`/`KeyError` from `Time` parsing.
- **`erfa/ufunc.abi3.so` is not a limited-API build, whatever the filename says.**
  pypi.flet.dev publishes pyerfa separately for cp312, cp313 and cp314, and each copy of that
  `.so` links its own `libpython3.<minor>.so`. Resolution is by wheel tag, so it costs you
  nothing — but do not conclude from the name that a Flet Python bump skips pyerfa.
- **scipy is optional, and a separate recipe on pypi.flet.dev.** Nothing in the wheel imports
  it at module level; the features that need it — `cosmology.z_at_value`, the spline models in
  `astropy.modeling`, parts of `astropy.stats` — reach for it lazily, and
  `astropy.convolution`'s FFT size optimisation falls back cleanly without it. Add scipy only
  if you need one of those; it is a large wheel.
- **Licensing:** astropy's metadata declares
  [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html), and its own code is that. What
  the badge cannot tell you is that `astropy/wcs/_wcs.…so` statically links WCSLIB 8.6, whose
  source headers offer it under the GNU
  [LGPL-3.0-or-later](https://spdx.org/licenses/LGPL-3.0-or-later.html) — so an app shipping
  this wheel distributes a combined work containing an LGPL library, whether or not it ever
  calls `astropy.wcs`. In practice: keep the notices, which ship in the wheel at
  `dist-info/licenses/licenses/WCSLIB_LICENSE.rst`, and leave a user able to substitute their
  own build of the library; for an open-source app, nothing at all. Check any wheel yourself
  with `unzip -p <wheel> '*.dist-info/METADATA' | grep -i license`. Flagging it, not advising
  you — we are not lawyers. Every part of this was checked against the artifacts on
  2026-08-23: the version and the grant come from `cextern/wcslib/README` in the sdist
  ("WCSLIB 8.6", "either version 3 of the License, or (at your option) any later
  version") rather than from LGPL boilerplate, which says "or later" regardless; the
  licence file is in the published wheel at the path above; and `_wcs` defines `wcsset`,
  `wcsp2s`, `wcss2p`, `celset` and `prjset` while linking no external wcs library, which
  is what makes it a combined work rather than a caller.

## Build notes (maintainers)

### Recipe shape

**The recipe is minimal on purpose and should stay that way.** astropy vendors wcslib,
cfitsio's Rice/HCOMPRESS codecs and expat into its own extensions, so there is no `flet-lib*`
chain and no PEP 517 shim: the eighteen extension modules need nothing beyond `libc`, `libdl`,
`libm` and `libpython` on Android, or `Python.framework` and `libSystem` on iOS. If a bump
makes one of those vendored libraries a system dependency, that is a shape change, not a
version bump.

Normalise the ABI tag and the Android and iOS wheels' file listings are identical, down to the
same eighteen extensions. The one difference is a single Cython directive on the cosmology
kernel, which `patches/android-cython-cpow.patch` justifies in its own preamble.

### Upgrade hazards

- **The IERS dates move with `astropy-iers-data`, not with astropy.** That distribution is
  released continuously from PyPI and is not a forge recipe, so the "runs to 2027-08-21,
  measured to 2026-08-13" figures under *Stale tables* go stale on their own, with nobody
  touching this recipe.
- **The kill switches are upstream configuration**, read out of `astropy/utils/iers/iers.py`
  and `astropy/utils/data.py`. `auto_download = True`, `remote_timeout = 10.0`, the
  re-try-per-call behaviour and the four-requests-per-AltAz count are defaults a major version
  could change silently.
- **The silent UT1 clamping is the claim most worth re-testing**, because it is the one a
  consumer cannot discover for themselves. It rests on `iers_degraded_accuracy` being scoped
  to standalone IERS-B; if upstream widens that scope, the warning becomes wrong in the safe
  direction and should be rewritten rather than deleted. The arcsecond ceiling is arithmetic
  (15.04″ × cos(dec) × 1.8 s) and survives a bump; the frozen value it is compared against
  does not.
- **The cleanup globs** in *App size* are measured off the wheel's entry list. A new nesting
  level adds a pattern, and `astropy/tests` stays out of that list for as long as
  `astropy/__init__.py` imports `TestRunner` from it.

### Re-verification checklist

- **`extract_packages` needs `astropy_iers_data`, and CI cannot currently catch it.** The
  requirement was established by reproducing Flet's `sitepackages.zip` shape with a real
  `zipimport` on the host: `import astropy`, UTC→TAI, UTC→TT and ICRS→galactic keep working,
  while `Time.ut1` and AltAz raise `NotADirectoryError`. **It has not been confirmed on an
  Android device**, and this recipe's own `meta.yaml` lists only `astropy` — so the first job
  is to confirm the failure on device and then close the gap in both `tests/` and that list.
- **The IERS tables:** re-read the coverage span and the leap-second expiry off the installed
  table rather than adjusting the dates by eye.
- **The socket-counting matrix** behind *Working offline* is cheap to re-run and is what
  catches an API like `of_address` slipping past both switches. Count sockets *and* assert a
  value came back — zero sockets is also what a call that never ran produces.
- **The size figures**, including the 9.5 MB / 738-entry `tests` share, are byte totals from
  the Android arm64-v8a and iOS device wheels. Total the entries rather than reading `du -h`,
  which answers in binary units.
- **The 18-extension, four-`NEEDED`-library claim** is what says this recipe has no native
  dependency chain. Re-run `llvm-readelf -d` across the Android wheel's `.so` files: a new
  vendored library appearing there is the tell that the shape has to change.
- **The WCSLIB version and its grant**, which the licensing note quotes, are in the vendored
  source headers under `cextern/wcslib/`; the text that ships is
  `dist-info/licenses/licenses/WCSLIB_LICENSE.rst`.

### Coverage gaps

The five device tests cover a UTC→JD/TT conversion, a FITS round trip, a WCS pixel↔world round
trip, an ICRS→galactic transform, and the cosmology kernel the Android patch touches. They do
not touch `.ut1`, build an AltAz frame, open the IERS table, or exercise either kill switch —
so none of the offline, staleness or `extract_packages` claims on this page has device
coverage. They rest on host measurement and wheel inspection.
