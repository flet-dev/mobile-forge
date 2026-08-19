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
ship inside the wheels, with two switches you should set and one silent failure mode you
should know about.

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

That is the whole configuration, and the
[`extract_packages`](https://flet.dev/docs/publish/android/#extract-packages) list is **not
optional on Android**. Flet ships pure-Python site-packages inside `sitepackages.zip` and
imports from it with `zipimport`, and both of these packages read data files through a real
`Path(__file__).parent / …` path, which a zip cannot serve:

- **`astropy`** reads `astropy/CITATION` in its own package `__init__`, so leaving it out
  breaks `import astropy` itself.
- **`astropy_iers_data`** — pulled in automatically, see below — builds the paths to its
  Earth-orientation tables the same way. Leaving *that* one out is the nastier failure,
  because the app looks healthy: it launches, units work, `Time` conversions between UTC,
  TAI, TT and TDB work, ICRS→galactic works, and then `Time.ut1` and every AltAz transform
  die with an uncaught `NotADirectoryError` whose path has `sitepackages.zip` as a
  directory component and ends in `astropy_iers_data/data/finals2000A.all`.

Both entries are **import** names (`astropy_iers_data`, with underscores, not the
`astropy-iers-data` distribution name), and both have to be in *your* `pyproject.toml` —
this recipe declares a list of its own in `meta.yaml`, but that copy is read only by
mobile-forge's on-device test app and travels nowhere near your build.
[iOS needs no equivalent](#ios-notes); the zip is an Android packaging detail.

List nothing else. The wheel's `Requires-Dist` pulls
[`astropy-iers-data`](https://pypi.org/project/astropy-iers-data/), `numpy`,
[`pyerfa`](https://pyerfa.readthedocs.io/), `PyYAML` and `packaging`, and none of them needs
configuring. astropy itself brings no native library along: its eighteen extension modules
need nothing beyond `libc`, `libdl`, `libm` and `libpython` on Android, and
`Python.framework` plus `libSystem` on iOS — wcslib, cfitsio's compression codecs and expat
are compiled into them. You will still see `flet-libcpp-shared` scroll past in an Android
build, but that is numpy's dependency, not astropy's.

Eighteen wheels at the same build number: Python 3.12, 3.13 and 3.14 × three Android ABIs
(arm64-v8a, armeabi-v7a, x86_64) and three iOS slices (device, arm64 simulator, x86_64
simulator). Nothing on PyPI competes for a mobile target — upstream's own 8.0.0 release
carries only macOS, Linux and Windows tags.

## Storage

### Before you import: two directories that must exist

astropy resolves its configuration directory *while `import astropy` is still running* (the
logger's config items force it), and if nothing tells it where that is, it falls back to
`Path.home()`. On the Flet iOS runtime there is no `pwd` module to fall back to when `HOME`
is unset, and the import dies with `RuntimeError: Could not determine home directory.` —
before any astronomy happens. Point it at Flet's app storage first:

```python
import os
import tempfile

_temp = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
_data = os.getenv("FLET_APP_STORAGE_DATA") or _temp
_config_dir = os.path.join(_data, "astropy", "config")
_cache_dir = os.path.join(_temp, "astropy", "cache")
os.makedirs(_config_dir, exist_ok=True)   # not optional — see below
os.makedirs(_cache_dir, exist_ok=True)
os.environ.setdefault("ASTROPY_CONFIG_DIR", _config_dir)
os.environ.setdefault("ASTROPY_CACHE_DIR", _cache_dir)

import astropy  # noqa: E402
```

**The `os.makedirs` calls are the load-bearing half, not the `os.environ` ones.** astropy 8
ignores `ASTROPY_CONFIG_DIR` / `ASTROPY_CACHE_DIR` unless the directory already exists: it
emits `AstropyUserWarning: ASTROPY_CONFIG_DIR is set to … but no such file or directory was
found. This environment variable will be ignored.` and then falls straight back to
`Path.home()` — i.e. straight back into the crash above. Setting the variables without
creating the directories is worse than not setting them at all, because the warning is one
most apps never surface. Code written against astropy 7 that only sets the variables will
regress here.

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the right home for the config directory — app-private, backed up, never auto-deleted —
and [`FLET_APP_STORAGE_TEMP`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_temp)
for the cache, which holds only re-downloadable files. With downloads off (see below)
astropy writes nothing into either; they just have to exist.

Data your app produces — FITS files, exported tables — belongs in `FLET_APP_STORAGE_DATA`
as well. `astropy.io.fits` writes to whatever path you hand it.

### What ships in the wheels, and what is a download

Everything astropy needs for units, time scales, coordinates, cosmology and I/O is inside
the two wheels. Nothing is fetched at import: `import astropy` opens no socket and creates
no file.

The Earth-orientation and leap-second tables live in `astropy-iers-data`, a separate
pure-Python distribution that astropy hard-depends on. It is not a forge recipe — there is
nothing to compile, so it resolves straight from PyPI as `py3-none-any`. It carries three
data files, and the first two are both load-bearing: delete either one and `Time.ut1` and
every AltAz transform stop working. They do not fail helpfully — measured with the file
actually removed, the exception is `AttributeError: 'NoneType' object has no attribute
'group'` from astropy's CDS reader (`astropy/io/ascii/cds.py`), naming neither the file nor
the reason.

| File | Size | What it is |
|---|---:|---|
| `finals2000A.all` | 3.6 MiB | IERS-A: Earth orientation, including the predictions |
| `eopc04.1962-now` | 4.9 MiB | IERS-B: the definitive values, substituted over IERS-A's |
| `Leap_Second.dat` | 1.3 kB | the leap-second table |

Leap seconds are the robust part: `pyerfa` carries a 42-row table compiled into its
extension, so UTC↔TAI/TT keeps returning the right answer (measured: TAI−UTC = 37 s) even
with all three files unreadable — with `Leap_Second.dat` alone missing you get an
`IERSStaleWarning` and the correct value.

Four APIs are downloads with **nothing** bundled behind them, and they raise offline rather
than degrading. They are, unhelpfully, the ones a tutorial reaches for first:

- `EarthLocation.of_site(...)` and `EarthLocation.get_site_names()` → `URLError` (there is
  no site catalogue in the wheel; hard-code an `EarthLocation` instead)
- `SkyCoord.from_name(...)` → `NameResolveError` from Sesame
- `EarthLocation.of_address(...)` → `NameResolveError` from the geocoder
- `solar_system_ephemeris.set("jpl")` → `ModuleNotFoundError`, before it even reaches the
  network: `jplephem` is not installed, and the JPL kernels are large downloads anyway

The offline substitutes are good: `get_body()` for the Sun, the Moon and the planets on the
default built-in ERFA ephemeris, `get_constellation()` from a table in the wheel, and the
bundled `Planck` and `WMAP` cosmologies — all measured at zero sockets.

### Turn the network off explicitly — both switches

```python
import astropy.utils.data
from astropy.utils import iers

iers.conf.auto_download = False
astropy.utils.data.conf.allow_internet = False
```

Import `astropy.utils.data` by name, as above. Plain `import astropy` on its own leaves
`astropy.utils.data` unbound and the second line dies with `AttributeError: module
'astropy.utils' has no attribute 'data'`; it happens to be bound after any import that
reaches it — `from astropy.utils import iers` does — but spelling it out is one line and
does not depend on that.

`iers.conf.auto_download` defaults to **True**, so a `Time.ut1` lookup tries to fetch a
3.6 MiB file from two URLs in sequence, each capped by `iers.conf.remote_timeout` at 10 s —
and it re-tries on *every* subsequent call, because a failed download leaves nothing cached
to short-circuit the next one. An AltAz transform costs two lookups, not one: measured with
an audit hook on `urllib.Request`, **four** requests and **six** `IERSWarning`s per
transform, on every transform. On a device with no connectivity, or behind a captive portal
that blackholes rather than refuses, that is up to ~20 s of frozen UI for a bare `Time.ut1`
and ~40 s for an AltAz transform — after which it uses the bundled table anyway and produces
the identical answer.

The two switches cover different things, measured across all four combinations with sockets
counted: `auto_download = False` alone silences the Earth-orientation path but leaves
`of_site` reaching for the network; `allow_internet = False` alone stops the sockets but
still emits the warnings. Only both together give zero sockets and zero warnings on the
transform path. Set them once at startup, before the first transform.

One API escapes both switches. `EarthLocation.of_address()` calls `urllib.request.urlopen`
itself instead of going through `astropy.utils.data`, so with `auto_download` and
`allow_internet` both off it still opens a connection to `nominatim.openstreetmap.org`
before raising `NameResolveError`. No setting stops it; just do not call it.

If your app genuinely wants fresher tables, do the refresh explicitly in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
user-visible control — never on the transform path.

### The one thing that degrades silently

The bundled IERS-A table carries roughly a year of predictions past its last measured value:
the copy measured here runs to 2027-08-21, with genuine values only to 2026-08-13.

**Past the end of the table, UT1−UTC is clamped to its last value with no exception and no
warning.** The `iers_degraded_accuracy` setting defaults to `error` but never fires here,
because its own documentation scopes it to IERS-B used on its own rather than to the default
`IERS_Auto`. The only warning you do get is about polar motion — a much smaller effect. So
the loud warning covers the small error and the big one is mute.

The damage is bounded, which is the reassuring half — but the bound is on the *difference*
between the frozen value and the true one, and leap seconds cap each of the two at 0.9 s
independently, so that difference reaches 1.8 s. One second of UT1 error turns the sky by
15.04″ × cos(dec): measured on an AltAz transform from Berlin, 11.28″/s for M31 at dec +41°,
15.04″/s for a target on the celestial equator, 0.17″/s for Polaris. The ceiling is
therefore **~27″**, and ~15″ against the value this particular build freezes at (−0.068 s).
A planetarium or field-observing app can ship with the bundled tables and simply say so;
arcsecond astrometry cannot.

Do not rely on astropy to tell you the tables are stale — read the span off the table and
put it on screen:

```python
import numpy as np
from astropy.time import Time
from astropy.utils import iers

mjd = np.asarray(iers.IERS_Auto.open()["MJD"].value, dtype=float)
days_left = mjd.max() - Time.now().mjd
```

The leap-second table carries an explicit expiry you can read the same way —
`erfa.leap_seconds.expires`, or `iers.LeapSeconds.from_erfa().expires` (2027-06-28 in the
copy measured here). **Read it after your first time conversion, not at startup.** astropy
loads `Leap_Second.dat` into ERFA lazily, on the first UTC↔TAI/TT conversion; before that,
both spellings return pyerfa's compiled-in **2017-06-30**, so a staleness check on the first
frame reports a table nine years out of date. Past the real expiry ERFA eventually starts
flagging conversions with `ErfaWarning: … "dubious year"`; that appeared for dates in late
2028 and later.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`offline-almanac`](examples/offline-almanac) — sky positions and time scales with the
  network switched off, and a slider that walks the date past the end of the bundled tables.

## Threading

The expensive moment is the first Earth-orientation lookup, not the astronomy. Opening the
table parses ~20,000 rows out of the two bundled files — 330 ms on a development machine,
and a phone is slower — after which astropy caches it and subsequent AltAz transforms take
about 1 ms. Importing `astropy`, `astropy.time` and `astropy.coordinates` costs a further
~280 ms on the same machine. So do the first transform in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) rather
than on the first frame, and end that handler with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) — auto-update does
not reach background threads, and `run_thread` never retrieves the worker's future, so an
exception in it surfaces nowhere at all.

Unit and angle *string* parsing is explicitly made thread-safe upstream:
`astropy/utils/parsing.py` wraps the generated PLY lexer and parser in locks. Nothing else
here is documented as safe to share, so give each worker its own objects.

## Android notes

`[tool.flet.android] extract_packages = ["astropy", "astropy_iers_data"]` is mandatory; see
[Install](#install) for the two failures it prevents and why the second one is the dangerous
one.

Otherwise the two platforms agree to an unusual degree: normalise the ABI tag and the two
wheels' file listings are identical, right down to the same eighteen extension modules. The
one difference is that the cosmology `scalar_inv_efuncs` kernel is compiled with an extra
Cython directive on Android; `patches/android-cython-cpow.patch` explains why, and argues
there that the arithmetic is unchanged.

## iOS notes

No `extract_packages` equivalent is needed or exists: iOS keeps site-packages as a real
directory in the app bundle, so both packages' `__file__`-relative reads resolve there
without help.

The import-time home-directory crash described under
[Storage](#before-you-import-two-directories-that-must-exist) is specifically an iOS risk —
Android ships `pwd`, so `Path.home()` resolves something there even with `HOME` unset. The
preamble makes the question moot on both platforms; write it once and stop thinking about
it.

## Things to know

- **The light-year is `u.lyr`, not `u.ly`.** `u.ly` raises `AttributeError`, and an
  unhandled exception in a Flet event handler produces a crash screen rather than a message.
  More generally, wrap anything that parses user input in a broad `except Exception`:
  astropy raises its own
  [`UnitConversionError`](https://docs.astropy.org/en/stable/api/astropy.units.UnitConversionError.html)
  (measured: `Can only apply 'add' function to quantities with compatible dimensions` for
  `1*u.m + 1*u.s`) but also plain `ValueError`/`KeyError` from `Time` parsing.
- **Size.** The Android arm64-v8a wheel is 6.2 MiB and unpacks to 22 MiB (armeabi-v7a 6.1 /
  21.3; iOS device 6.3 / 23.1). Of the unpacked 22 MiB, **9.1 MiB across 738 of the 1434
  entries is astropy's own `tests/` data** — `m13.fits`, `1904-66_AZP.fits`, the VOTable
  validator's corpora — which upstream ships in its own wheels too and which your app will
  never import. Add `astropy-iers-data` (1.9 MiB → 8.5 MiB), pyerfa (0.3 → 1.4) and numpy
  (6.5 → 21) and the astropy stack is roughly 15 MiB of wheels and 53 MiB unpacked before
  your own assets. Flet compiles `.py` to `.pyc` and zips site-packages, so what lands on
  the device is smaller than the unpacked figure; the wheel sizes are the honest floor.
- **Nothing here is a mobile fork.** Apart from build metadata and the one Android patch,
  every `.py` in the wheel is byte-identical to the PyPI release, so
  [upstream's documentation](https://docs.astropy.org/en/stable/) applies unchanged and
  anything you work out on a laptop transfers — except for the platform-, loader- and
  size-dependent things this page is about.
- **`erfa/ufunc.abi3.so` is not a limited-API build, whatever the filename says.**
  pypi.flet.dev publishes pyerfa separately for cp312, cp313 and cp314, and each copy of
  that `.so` links its own `libpython3.<minor>.so` (`llvm-readelf -d`) and is a different
  size. It costs you nothing, since resolution is by wheel tag — but do not conclude from
  the name that a Flet Python bump skips pyerfa.
- **scipy is optional, and a separate recipe on pypi.flet.dev.** Nothing in the wheel
  imports it at module level; the features that reach for it do so lazily —
  `cosmology.z_at_value`, the spline models in `astropy.modeling`,
  `poisson_conf_interval(interval="frequentist-confidence")`, `jackknife_stats`, and an FFT
  size optimisation in `astropy.convolution` that falls back cleanly without it. Add scipy
  only if you need one of those; it is a large wheel.

## Build notes (maintainers)

`meta.yaml` is a handful of settings with a comment on the one that needs it, and
`patches/android-cython-cpow.patch` carries its own rationale, so neither is re-explained
here. What has no home in those two files:

**The recipe is minimal on purpose and should stay that way.** astropy vendors wcslib,
cfitsio's Rice/HCOMPRESS codecs and expat into its own extensions, so there is no
`flet-lib*` chain to maintain and no PEP 517 shim. If a bump ever makes one of those a
system dependency, that is a shape change, not a version bump.

What to re-verify on a bump — the sections above make consumer-facing claims that a green
build does not check:

- **`extract_packages` needs `astropy_iers_data`, and CI cannot currently catch it.** The
  requirement was established by reproducing Flet's `sitepackages.zip` shape with a real
  `zipimport` on the host: `import astropy`, UTC→TAI, UTC→TT and ICRS→galactic all keep
  working, while `Time.ut1` and AltAz raise `NotADirectoryError`. **It has not been confirmed
  on an Android device.** None of the five tests in `tests/` touches `.ut1` or builds an
  AltAz frame, and this recipe's own `meta.yaml` lists only `astropy` — so the first job is
  to confirm it on device and then close the gap by extending both the test file and the
  `meta.yaml` list.
- **The IERS coverage dates move with `astropy-iers-data`, not with astropy.** That
  distribution is released continuously from PyPI and is not a forge recipe, so the "runs to
  2027-08-21, measured to 2026-08-13" figures under *Storage* go stale on their own,
  without anyone touching this recipe. Re-read them off the table rather than adjusting them
  by eye, and re-read `erfa.leap_seconds.expires` at the same time.
- **The two kill switches and their defaults** are read out of the installed
  `astropy/utils/iers/iers.py` and `astropy/utils/data.py`. `auto_download = True`,
  `remote_timeout = 10.0`, the re-try-per-call behaviour and the four-requests-per-AltAz
  count are all upstream defaults that a major version could change; the four-mode
  socket-counting matrix behind that section is cheap to re-run, and it is what catches an
  API like `of_address` slipping past both switches.
- **The silent UT1 clamping is the claim most worth re-testing**, because it is the one a
  consumer cannot discover for themselves. It rests on `iers_degraded_accuracy` being scoped
  to standalone IERS-B; if upstream ever widens that scope, the *Storage* section's central
  warning becomes wrong in the safe direction and should be rewritten rather than deleted.
  The arcsecond ceiling next to it is arithmetic (15.04″ × cos(dec) × 1.8 s) and does not
  move with a bump, but the frozen value it is compared against does.
- **The size figures** — wheel and unpacked totals, the 9.1 MiB / 738-file `tests/` share,
  and the per-dependency numbers — are measured off the Android arm64-v8a wheel. Re-measure;
  nothing in CI checks them.
- **The 18-extension / four-`NEEDED`-libraries claim** is what says this recipe has no native
  dependency chain. Re-run `llvm-readelf -d` across the Android wheel's `.so` files after a
  bump: a new vendored library showing up there is the tell that the recipe shape has to
  change.
