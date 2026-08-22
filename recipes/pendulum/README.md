# pendulum

[`pendulum`](https://pendulum.eustace.io/docs/) is a friendlier `datetime`. Its types
*subclass* the standard library's — `DateTime` inherits from `datetime.datetime`, `Duration`
from `timedelta` and `pendulum.Time` from `datetime.time` — so a pendulum value drops into
code that expects a stdlib one, and the reverse is `pendulum.instance(dt)`. What you get on
top is an [ISO-8601 parser](https://pendulum.eustace.io/docs/#parsing) written in Rust that
reads week dates, ordinal dates, durations and intervals; calendar arithmetic that
[respects DST](https://pendulum.eustace.io/docs/#addition-and-subtraction); and
[human-readable differences](https://pendulum.eustace.io/docs/#difference-for-humans) in 29
locales, all of which ship inside the wheel and need no network.

On a phone the reason to reach for it is the time-zone half. A phone is the device most
likely to be carried across zones, and the mobile Python runtimes are exactly where the
standard library's zone story is thinnest: the Android and iOS support tarballs this repo
pins both compile in the stock Unix `TZPATH`
(`/usr/share/zoneinfo:/usr/lib/zoneinfo:/usr/share/lib/zoneinfo:/etc/zoneinfo`) and ship no
IANA tree of their own.

**One thing to know before you write a line of it:** `pendulum.now()` with no argument asks
the operating system what zone it is in, through a code path that has nothing to look at on
a phone. Where it finds nothing it warns once, on stderr, which nothing in a Flet UI
surfaces — and returns **UTC**. Pass a zone explicitly, or read
[Things to know](#things-to-know) first.

## Install

Add pendulum to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "pendulum",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`dst-clock`](examples/dst-clock) — asks the device what it knows about zones, then makes
  one calendar day and 24 hours disagree on screen.

## Usage in a Flet app

```python
import pendulum

now = pendulum.now("Europe/Paris")        # never a bare now() on a phone
tomorrow = now.add(days=1)                # the same wall clock: 23, 24 or 25 real hours
label = ft.Text(now.format("dddd D MMMM YYYY", locale="fr"))
```

The zone argument on the first line is not optional in a mobile app: leave it out and the
answer is UTC on a device and right on your desktop, so the bug ships. The `.add(days=1)` on
the second line is calendar arithmetic, and `+ datetime.timedelta(days=1)` on the same object
compiles too and means something else. The third line needs no network for any of the 29
locales.

### Zones and the device clock

Looking a zone up *by name* is safe on both platforms, because it never touches the
filesystem: `pendulum.now("Asia/Kolkata")` and `pendulum.timezone("Pacific/Chatham")` resolve
out of the [`tzdata`](https://pypi.org/project/tzdata/) wheel, which pendulum's
`Requires-Dist` names unconditionally and with no environment marker.

Asking the device *which* zone it is in is the part that fails.
`pendulum/tz/local_timezone.py` dispatches on `sys.platform`: `win32` to the registry,
`"darwin" in sys.platform` to `os.readlink("/etc/localtime")`, and everything else to a
generic Unix probe that reads `$TZ`, `/etc/timezone`, `/etc/sysconfig/clock`,
`/etc/conf.d/clock`, an `/etc/localtime` symlink, and then `/etc/localtime` and
`/usr/local/etc/localtime` as files — the only two `open()` calls anywhere in the package.
Flet's iOS runtime reports `sys.platform == "ios"`
([PEP 730](https://peps.python.org/pep-0730/)), so **iOS takes the same generic-Unix branch
Android takes**, on a Darwin ABI.

So write the zone into the call. Where what you want is the device's own offset rather than
a named zone, take it from libc with `datetime.datetime.now().astimezone()`, which does not
go through `zoneinfo` at all. (On Android that also makes it immune to a missing
`/etc/localtime`; whether the same holds inside an iPhone sandbox is untested — see Coverage
gaps.) Keep
stored instants in UTC and convert for display; a stored wall clock means nothing without
the zone it was written in.

Whether that Unix probe finds anything inside an iPhone sandbox is the one question on this
page a simulator cannot settle for you — the simulator resolves `/etc/localtime` and
`/usr/share/zoneinfo` against the host Mac and would answer correctly whether or not an
iPhone does. The [`dst-clock`](examples/dst-clock) example prints which of those paths exist
and what each source says, so a device run answers it in a few seconds.

### Parsing

[`pendulum.parse`](https://pendulum.eustace.io/docs/#parsing) hands back a different type
depending on the shape of the string, which is the feature rather than an accident:

| input | comes back as |
| --- | --- |
| `2026-03-29T01:30:00Z`, the basic form `20260329T013000Z`, the week date `2026-W14-1`, the ordinal date `2026-089` | `DateTime` |
| `P3DT4H5M` | `Duration` |
| `2007-03-01T13:00:00Z/2008-05-11T15:30:00Z` | `Interval` |
| a date-only or time-only string | `DateTime` with the missing half filled in — or `Date` / `Time` with `exact=True` |

With `strict=False`, `March 29 2026 1:30pm`, `29/03/2026` and
`Sun, 29 Mar 2026 01:30:00 GMT` parse too; that path is where `python-dateutil` earns its
place in `Requires-Dist`.

Branch on the type you get back rather than assuming a `DateTime`, and put every parse of
user input inside a broad `except Exception` — the empty text field is the input that gets
past a narrow catch, and [Things to know](#things-to-know) says why.

### App size

**320–362 KB to download and 905–952 KB unpacked** across the six slices a Flet app can
actually use, and half of it is the extension. (The legacy 3.12-only `android_24_x86` slice
is the outlier at 376 KB / 964 KB.) The rest is 409 KB of Python — 197 KB of it the 31 locale
packages — and a 41 KB `dist-info`.

Then add the dependencies, which are the larger half of the bill: unpacked, `tzdata` is
516 KB (627 files — 598 `TZif` zone binaries, seven text indexes such as `zones` and
`zone.tab`, and 22 `.py`), `dateutil` 428 KB and `six.py` 35 KB. Staged the way Android
packages them — byte-compiled to `.pyc` with the sources stripped — pendulum and its three
dependencies together came to about **2.0 MB** in a stored zip. Flet's default
[package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes
`_pendulum.pyi` and `py.typed`, which nothing reads at runtime.

At around two megabytes the Android levers — an app bundle, split APKs, or a narrowed
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) — are
worth reaching for because of what else is in the app, not because of this.

### Other considerations

A desktop `flet run` uses PyPI's wheel: the same version and the same Rust code. It is also
the environment in which every local-zone answer looks right, so `pendulum.now()`,
`local_timezone()` and anything derived from them are the calls to re-read on a device
instead of trusting a desktop run. The import-cost figures in
[Things to know](#things-to-know) were measured on desktop as well, and a phone's will be
larger.

Nothing in the package reads its own source or a data file, so Flet's default
compile-to-`.pyc` and Android's zipped site-packages are both safe. `tzdata` *is* read as
data, but through `importlib.resources`, which works out of a zip: staged as `.pyc` in a
stored zip with the `.py` sources deleted — Android's packaging shape — and with `zoneinfo`'s
search path emptied, `pendulum.now("Europe/Paris")` and `zoneinfo.ZoneInfo("Pacific/Chatham")`
both resolve, and `available_timezones()` still returns all 598 zones `tzdata` 2026.3 carries.
(That is a desktop simulation of the Android packaging rather than a device run; the recipe's
own on-device test asserts a named zone for real.)

What is not safe is reading the native module's location. Flet relocates every tagged
extension out of site-packages — into `jniLibs` on Android, and on iOS into a framework with
a `_pendulum.fwork` pointer file left in its place — so **`pendulum._pendulum.__file__` is
not a path inside your app**, and may be absent altogether. Nothing in pendulum reads it, so
this only bites if you meant to use it to answer "did the native module load?". Read
`pendulum.parsing.parse_iso8601.__module__` instead: that import carries no word-size gate,
so it is `pendulum._pendulum` on every slice where the extension loaded and
`pendulum.parsing.iso8601` where it did not. Do **not** use
`pendulum.helpers.precise_diff.__module__` for that question — it reports `pendulum._helpers`
on 32-bit builds while the extension is loaded and in use. Both readings are worth printing
side by side, and the [`dst-clock`](examples/dst-clock) example does.

## Things to know

- **`pendulum.now()` and `pendulum.local_timezone()` are the two calls to distrust on
  mobile.** When the Unix probe above finds none of its files, `_get_system_timezone()` calls
  `warnings.warn("Unable not find any timezone configuration, defaulting to UTC.")` and
  returns UTC — reproduced by pointing that function at a root that does not exist. The
  result is then cached in a module global, so the warning fires **once per process**, on
  stderr, where a Flet app shows nothing. Android has a documented reason to come up empty:
  it keeps its zone database in a bionic-specific format that Python cannot read. iOS takes
  the same branch and has not been checked on a real device. **Always pass the zone you
  mean** — `pendulum.now("Europe/Paris")` — or take the device's own offset from libc with
  `datetime.datetime.now().astimezone()`. The example prints both side by side, which is the
  quickest way to see what your device does.

- **`.add(days=1)` and `+ timedelta(days=1)` are different operations on the same object, and
  both compile.** From `2026-03-28 12:00` in Europe/Paris, `.add(days=1)` gives
  `2026-03-29 12:00+02:00` — the same wall clock, 23 real hours later — while
  `+ datetime.timedelta(days=1)` gives `13:00+02:00`, a true 24 hours. Subclassing
  `datetime.datetime` is only what makes both *compile*; the 24-hour answer comes from
  pendulum **overriding** `__add__` to add `delta.total_seconds()`, and it is the reverse of
  the stdlib's own meaning — `datetime(2026, 3, 28, 12, tzinfo=ZoneInfo("Europe/Paris"))
  + timedelta(days=1)` keeps the wall clock and gives `12:00+02:00`, agreeing with pendulum's
  `.add(days=1)` rather than with pendulum's `+`. So the one line that survives a port between
  stdlib and pendulum unchanged is the one that silently changes answer. (A
  `pendulum.duration(days=1)` on the right-hand side goes back to calendar semantics, so the
  operator's meaning depends on the type of *both* operands.) "Same time tomorrow" is
  `.add(days=1)`; "twenty-four hours from now" is `.add(hours=24)` or a `timedelta`. Over a
  longer span the two transitions cancel: 220 days from `2026-03-25 12:00` Paris crosses both
  and nets exactly 5,280 hours, while 4 days crosses only the spring-forward and nets 95
  against a nominal 96.

- **`DateTime.__add__` decides what to do by looking at the name of the function that called
  it.** It runs `traceback.extract_stack(limit=2)[0].name` on every `+`, and if that name is
  `astimezone` it defers to `datetime.__add__` instead. So the *same* expression gives
  `2026-03-29 12:00+02:00` inside a method or function you happened to call `astimezone` and
  `13:00+02:00` anywhere else. Nothing warns. Do not name a function `astimezone` in a module
  that does pendulum arithmetic — and note that this stack walk runs on every single addition,
  so `+` in a tight loop is far more expensive than it looks; prefer `.add(...)` there.

- **Ambiguous and non-existent local times do not raise by default.**
  `pendulum.timezone("Europe/Paris").datetime(2026, 10, 25, 2, 30)` — a wall clock that
  happens twice — returns the post-transition `02:30+01:00`, and
  `…datetime(2026, 3, 29, 2, 30)` — a wall clock that never happens — returns `03:30+02:00`.
  To be told instead, use
  [`Timezone.convert`](https://pendulum.eustace.io/docs/#shifting-time-to-transition):
  `convert(naive_dt, raise_on_unknown_times=True)` raises
  `pendulum.tz.exceptions.AmbiguousTime` and `NonExistingTime`. A stdlib `fold=` on a naive
  datetime carrying the pendulum `Timezone` also works, selecting `+02:00` for `fold=0` and
  `+01:00` for `fold=1`. Note that the constants and the keyword are **not** where older code
  puts them: `pendulum.PRE_TRANSITION` raises `AttributeError` (they live in `pendulum.tz`),
  and `pendulum.datetime(..., dst_rule="pre")` raises
  `TypeError: datetime() got an unexpected keyword argument 'dst_rule'`.

- **Catch broad `Exception` around any parse of user input.**
  `pendulum.parse("not a date")` raises `pendulum.parsing.exceptions.ParserError`, which is a
  `ValueError` subclass — but `pendulum.parse("")` raises a **plain** `ValueError` from the
  `datetime` constructor (its wording changes between Python versions), which
  `except ParserError` does not catch, and an empty text field is the single most likely input
  an app will see. `pendulum.timezone("Mars/Olympus")` raises `InvalidTimezone`, also a
  `ValueError` subclass. An unhandled exception in a Flet handler makes the framework crash
  the session, so the narrow catch is the one that bites.

- **On a 32-bit build, half the Rust extension is deliberately not used.**
  `pendulum/helpers.py` raises `ImportError` on itself when `struct.calcsize("P") == 4` —
  today that is `armeabi-v7a` and the legacy Android x86 slice — so `precise_diff`,
  `days_in_year`, `is_leap`, `is_long_year`, `local_time` and `week_day` come from the
  pure-Python `pendulum/_helpers.py` there. `pendulum/parsing/__init__.py` carries no such
  gate, so `parse_iso8601` stays native on every slice. This is upstream's own guard, not
  something this recipe does, and it is silent. The numbers come out the same either way —
  every field of `precise_diff` matched between the two paths, as did `diff_for_humans` and
  `format` — but the **repr does not**: the Rust `PreciseDiff` prints
  `PreciseDiff(years=0, months=3, days=8, …)` and its pure-Python twin prints
  `0 years 3 months 8 days …`. Put a `precise_diff` result straight into an f-string and
  `armeabi-v7a` renders a different string from `arm64-v8a`; read the fields instead. It also
  means `armeabi-v7a` carries 485 KB of extension — more than `arm64-v8a`'s 468 KB — and uses
  less of it than any 64-bit slice does.

- **ISO-8601 and RFC-3339 output are not the same string.** For a UTC value,
  `to_iso8601_string()` gives `2026-03-29T01:30:00Z` while `to_rfc3339_string()`,
  `to_atom_string()` and `to_w3c_string()` all give `2026-03-29T01:30:00+00:00`. If an API
  contract says one of them, say which.

- **Localisation is fully offline.** 29 locale packages ship in the wheel — `bg cs da de en
  en_gb en_us es fa fo fr he hi id it ja ko lt nb nl nn pl pt_br ru sk sv tr ua zh` — and they
  cost 197 KB of the 919 KB unpacked payload. `dt.format("dddd D MMMM YYYY", locale="fr")`
  gives `dimanche 29 mars 2026`, and
  `pendulum.now().subtract(minutes=95).diff_for_humans(locale="es")` gives `hace 1 hora`. An
  unrecognised name does **not** fall back to English — it raises
  `ValueError: Locale [xx] does not exist.` — and the list is less obvious than it looks:
  there is `pt_br` but no plain `pt`, so `locale="pt"` raises. Validate any locale that comes
  from a device setting rather than from a literal.

- **Do not depend on `pendulum[test]`, and expect `pendulum.travel` to raise.** The extra pins
  `time-machine>=2.6.0,<3.0.0`, and this index publishes `time-machine` 2.16.0 for cp312 only
  and 3.2.0 for cp312/cp313/cp314 — nothing inside that range exists above cp312, so the extra
  cannot resolve for a 3.13 or 3.14 build. Without it,
  [`pendulum.travel`](https://pendulum.eustace.io/docs/#testing), `travel_to` and `freeze`
  raise `NotImplementedError: Time travelling is an optional feature…`. It is a test facility;
  an app has no reason to want it.

- **`pendulum.__version__` still answers but is deprecated**, emitting
  `DeprecationWarning: The '__version__' attribute is deprecated and will be removed in
  Pendulum 3.4` and pointing at `importlib.metadata.version("pendulum")`. That replacement
  reads the `dist-info` directory, which is a packaging artefact rather than something the
  package carries, so wrap it if you put it on screen — the example does.

- **`import pendulum` is not free.** It adds 98 entries to `sys.modules` on a cold interpreter
  and takes 16–18 ms there (best of several, desktop CPython 3.12 on an arm64 Mac) against
  `import datetime`'s well under a millisecond. Inside a Flet app most of that is not yours:
  after `import flet`, the marginal cost measured **8–10 ms** for 54 further modules —
  `datetime`, `decimal`, `calendar`, `zoneinfo`, `sysconfig`, the eleven `dateutil` modules
  and `six`. Phone figures will be larger on both sides. If an app only ever formats a
  timestamp, the stdlib is cheaper.

## Build notes (maintainers)

### Recipe shape

There is little to explain: the upstream sdist cross-compiles as-is, so the recipe has no
patches and no `build.sh`. The two `meta.yaml` settings it does carry are not explained in the
file — add those comments before assuming this section covers them. What follows is the bump
checklist, and it is longer than the recipe's size suggests, because almost everything this
README promises is invisible to a green build.

### Upgrade hazards

- **The 32-bit `helpers` fallback is upstream's, and it is version-coupled.** If a bump
  removes the `struct.calcsize("P") == 4` guard in `pendulum/helpers.py`, or adds one to
  `pendulum/parsing/__init__.py`, the consumer sections are wrong. Grep both files on every
  bump; the runtime tell is the pair of `__module__` values in *Other considerations*.

- **`Requires-Dist` is the whole zone story.** The unconditional `tzdata>=2020.1` is what
  makes named zones resolve on a phone at all. If upstream ever moves it behind an environment
  marker, every consumer on Android loses named zones and nothing in the build fails. It does
  at least fail loudly at runtime rather than silently: with `tzdata` unimportable and `TZPATH`
  empty — the shape of an Android device — `import pendulum` itself raises
  `InvalidTimezone: UTC`, because `pendulum/tz/timezone.py` ends on a module-level
  `UTC = Timezone("UTC")` that goes through `zoneinfo`. Both tests in `tests/` import pendulum,
  so the on-device leg catches this; the build does not. There is no degraded mode to detect
  and no screen an example could print it on — the app simply does not start.

- **The extension's filename is not the same on every Python.** The Android 3.12 wheels ship a
  bare `pendulum/_pendulum.cpython-312.so` while the 3.13 and 3.14 ones carry a full platform
  triple (`…-aarch64-linux-android.so`, `…-arm-linux-androideabi.so`,
  `…-x86_64-linux-android.so`); the iOS slices are `-iphoneos` / `-iphonesimulator` on every
  Python. Both Android spellings are relocated correctly today. If a bump changes which one
  comes out, confirm the Android on-device import still works rather than assuming, since that
  filename is what serious_python's relocation matches on.

### Re-verification checklist

- **Re-read `METADATA` out of a built wheel**, for the `tzdata` marker above and for the
  `python-dateutil` requirement the `strict=False` parse path depends on.

- **Re-measure the sizes rather than adjusting them by eye.** The consumer range covers the
  six usable slices; the per-slice baseline, on Python 3.14, is:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 342 KB | 919 KB | 468 KB |
  | Android armeabi-v7a | 362 KB | 937 KB | 485 KB |
  | Android x86_64 | 353 KB | 952 KB | 501 KB |
  | iOS arm64 (device) | 320 KB | 905 KB | 453 KB |
  | iOS arm64 (simulator) | 323 KB | 908 KB | 457 KB |
  | iOS x86_64 (simulator) | 335 KB | 909 KB | 458 KB |

  Every slice checked is 127 files. Of the 40 KB `dist-info`, 22 KB is a CycloneDX SBOM naming
  the 19 Rust crates the extension was built from. The locale list, the crate count and the
  module counts are measured too; the wheel contents are otherwise stable enough that a
  surprise in any of them is worth investigating.

- **Check the binaries against the last known shape.** Each Android slice exports exactly one
  symbol, `PyInit__pendulum`, against 123 to 130 undefined ones — the count tracks the Python
  version and the word size, lowest on 3.12 `armeabi-v7a` and highest on 3.14 `arm64-v8a`.
  `DT_NEEDED` is `libpython3.<minor>.so`, `libdl.so` and `libc.so` with no `libc++_shared`,
  there is no `SONAME`, and every `PT_LOAD` segment carries the 16 KB alignment Android 15
  requires. The iOS slices are `MH_DYLIB` marked `NOUNDEFS`, export only `_PyInit__pendulum`,
  and name nothing beyond `@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib` and
  `/usr/lib/libSystem.B.dylib` — all of them the OS's or CPython's, so there is no third-party
  dylib to ship alongside.

- **Diff the pure-Python half across platforms.** Every non-`.so` file is byte-identical
  between the Android and iOS wheels, `METADATA` included, and the SBOM's component list
  matches too (the SBOM file itself differs only in its serial number, timestamp and build
  path). If `diff -r --exclude='*.so' --exclude=RECORD --exclude=WHEEL --exclude='*.json'`
  between an unpacked Android and iOS wheel stops being empty, something platform-specific
  leaked into the pure-Python half.

- **Re-check the `pendulum[test]` claim** whenever `time-machine` is rebuilt on this index: it
  rests on which cp3xx tags exist inside `>=2.6.0,<3.0.0`, not on anything pendulum ships.

### Coverage gaps

- **A green build proves the extension exists, not that it is used.** Both native imports sit
  behind `try/except ImportError` with working pure-Python twins — deleting the `.so` outright
  still gives a clean import and **2 passed** from `tests/`, measured.
  `tests/test_pendulum.py` should assert
  `pendulum.parsing.parse_iso8601.__module__ == "pendulum._pendulum"` on every slice and
  `pendulum.helpers.precise_diff.__module__ == "pendulum._pendulum"` only on 64-bit ones;
  until it does, nothing anywhere catches a silently dead extension.

- **`tests/test_pendulum.py::test_timezone` is the only assertion in this repo that a named
  IANA zone resolves on a phone**, and the whole zone story above rests on it — a build cannot
  fail on it, and the desktop zip simulation quoted in *Other considerations* is not a device.
  Keep it in the suite, and re-run it on a device after a Flet packaging change as much as
  after a pendulum bump. (It also has no docstring, against this repo's test convention; fix
  that when you next touch the file.)

- **iOS local-zone detection is unverified on a real device.** The consumer sections say only
  what the code does and which branch it takes; whether `/etc/localtime` resolves inside an
  iPhone sandbox is open, and a simulator run cannot answer it because the simulator reads the
  host Mac's files. If someone runs the example on a device, fold the answer in and delete
  this entry.
