# pendulum

[`pendulum`](https://pendulum.eustace.io/docs/) is a friendlier `datetime`. Its types
*subclass* the standard library's — `DateTime.__mro__` is `(DateTime, datetime, Date,
FormattableMixin, date, object)`, `Duration` inherits from `timedelta`, and
`pendulum.Time` from `datetime.time` — so a pendulum value drops into code that expects a
stdlib one, and the reverse is `pendulum.instance(dt)`. What you get on top is an
[ISO-8601 parser](https://pendulum.eustace.io/docs/#parsing) written in Rust that reads
week dates, ordinal dates, durations and intervals; calendar arithmetic that
[respects DST](https://pendulum.eustace.io/docs/#addition-and-subtraction); and
[human-readable differences](https://pendulum.eustace.io/docs/#difference-for-humans)
in 29 bundled locales, all of which ship inside the wheel and need no network.

On a phone the reason to reach for it is the time-zone half. A phone is the device most
likely to be carried across zones, and the mobile Python runtimes are exactly where the
standard library's zone story is thinnest: the Android and iOS support tarballs this repo
pins both compile in the stock Unix `TZPATH`
(`/usr/share/zoneinfo:/usr/lib/zoneinfo:/usr/share/lib/zoneinfo:/etc/zoneinfo`) and ship no
IANA tree of their own. pendulum does not fix that by carrying its own copy either — there
is no zone database anywhere in the wheel, only `tz/data/windows.py`, a
Windows-registry-name lookup table that is dead code here. It fixes it by *depending* on
the `tzdata` wheel unconditionally, so named zones work out of the box where
[`pandas`](../pandas) and [`polars`](../polars) both make you add that dependency by hand.

**One thing to know before you write a line of it:** `pendulum.now()` with no argument
asks the operating system what zone it is in, through a code path that has nothing to look
at on a phone. Where it finds nothing it warns once, on stderr, which nothing in a Flet UI
surfaces — and returns **UTC**. Pass a zone explicitly, or read
[Things to know](#things-to-know) first.

Both platforms are published, for Python 3.12, 3.13 and 3.14.

## Install

```toml
# pyproject.toml
dependencies = [
    "flet",
    "pendulum",
]
```

Three more wheels come along, and **none of them needs configuring**: the wheel's
`METADATA` declares `python-dateutil>=2.6` and `tzdata>=2020.1` with no environment
marker at all, so a resolve of `flet` + `pendulum` alone pulls in
[`tzdata`](https://pypi.org/project/tzdata/), `python-dateutil` and its `six`. That is
worth stating plainly because the two other date-handling packages on this index behave
differently: both reach the stdlib
[`zoneinfo`](https://docs.python.org/3/library/zoneinfo.html) for named zones too, but
[`pandas`](../pandas#things-to-know) declares `tzdata` only under
`sys_platform == "win32"` and `"emscripten"` (read off `pandas-3.0.3`'s own `METADATA` on
this index), and [`polars`](../polars#things-to-know) only under
`platform_system == 'Windows' and extra == 'timezone'` — so on mobile it arrives for
neither, and both READMEs tell you to add it yourself. Here you do not.

`python-dateutil` is not optional either, and it is not lazy:
`pendulum/parsing/__init__.py` does a module-level `from dateutil import parser`, and
`import pendulum` reaches it through `pendulum.parser`. It is only *used* on the
`strict=False` path, but it is imported whether you go there or not.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed, for pendulum or for `tzdata`. Across the 122 files of the pendulum
package there is not one occurrence of `__file__`, `importlib.resources`, `pkgutil`,
`pkg_resources`, `getsource` or `ctypes`, and both of its `open()` calls sit in
`tz/local_timezone.py` — one reading `/etc/localtime` or `/usr/local/etc/localtime`, the
other reading whatever `$TZ` names when `$TZ` is a path. `tzdata` *is* read as data, but through
`importlib.resources`, which works out of a zip: staging `pendulum`, `tzdata`, `dateutil`
and `six.py` into a stored zip as `.pyc` with the `.py` sources deleted — Android's
packaging shape — then importing from that zip with `zoneinfo`'s search path emptied,
`pendulum.now("Europe/Paris")` and `zoneinfo.ZoneInfo("Pacific/Chatham")` both resolve and
`available_timezones()` still returns all 598 zones `tzdata` 2026.3 carries. (That is a
desktop simulation of the Android packaging, not a device run; the recipe's own on-device
test asserts the same call for real — see [Build notes](#build-notes-maintainers).)

Nineteen wheels at one build number: Python 3.12, 3.13 and 3.14 × the three Android ABIs
Flet targets (arm64-v8a, armeabi-v7a, x86_64) and the three iOS slices (device, arm64
simulator, x86_64 simulator), plus a legacy `android_24_x86` slice on 3.12 only. No arch is
excluded, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`dst-clock`](examples/dst-clock) — asks the device what it knows about zones, then makes
  one calendar day and 24 hours disagree on screen.

## Android notes

The extension links nothing beyond the interpreter and libc. `DT_NEEDED` is
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on all ten Android slices — no
`libc++_shared`, so pendulum brings no `flet-libcpp-shared` with it — and there is no
`SONAME`. All `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires.
arm64-v8a and x86_64 are `ELF64/AArch64` and `ELF64/x86-64`; armeabi-v7a is a genuine
`ELF32/ARM` build and the legacy 3.12-only x86 slice a genuine `ELF32/i386` one. Each slice
exports exactly one symbol, `PyInit__pendulum`, against 123 to 130 undefined ones — the
count tracks the Python version and the word size, lowest on 3.12 armeabi-v7a and highest
on 3.14 arm64-v8a.

**On 32-bit Android, half the Rust extension is deliberately not used.**
`pendulum/helpers.py` raises `ImportError` on itself when `struct.calcsize("P") == 4`,
which is true on armeabi-v7a (and on the legacy x86 slice), so `precise_diff`,
`days_in_year`, `is_leap`, `is_long_year`, `local_time` and `week_day` come from the
pure-Python `pendulum/_helpers.py` there. `pendulum/parsing/__init__.py` carries no such
gate, so `parse_iso8601` stays native on every ABI. This is upstream's own guard, not
something this recipe does, and it is silent. The numbers come out the same either way —
every field of `precise_diff` matched between the two paths, as did `diff_for_humans` and
`format` — but the **repr does not**: the Rust `PreciseDiff` prints
`PreciseDiff(years=0, months=3, days=8, …)` and its pure-Python twin prints
`0 years 3 months 8 days …`. Put a `precise_diff` result straight into an f-string and
armeabi-v7a renders a different string from arm64-v8a; read the fields instead. It also
means armeabi-v7a carries 475 KB of extension — more than arm64-v8a's 459 KB — and uses
less of it than any 64-bit slice does.

**The extension's filename is not the same on every Python**, which matters if you go
looking for it in an app payload: 3.13 and 3.14 ship
`pendulum/_pendulum.cpython-3<minor>-aarch64-linux-android.so` (and
`…-arm-linux-androideabi.so`, `…-x86_64-linux-android.so`), while all four 3.12 Android
slices ship a bare `pendulum/_pendulum.cpython-312.so` with no platform triple. Both
spellings carry the `cpython-<minor>` ABI tag, which is what Android's relocation keys on.

Flet relocates every tagged extension out of site-packages into `jniLibs`, so
`pendulum._pendulum.__file__` is not a path inside your app and may be absent altogether.
Nothing in pendulum reads it, so this is informational — but it means you cannot use it to
answer "did the native module load?". Read
`pendulum.parsing.parse_iso8601.__module__` instead: that import has no 32-bit gate, so it
is `pendulum._pendulum` on every ABI when the extension loaded and
`pendulum.parsing.iso8601` when it did not. **Do not use
`pendulum.helpers.precise_diff.__module__` for that question** — it reports
`pendulum._helpers` on armeabi-v7a and the legacy x86 slice while the extension is loaded
and in use, because of the guard above. Verified by forcing `struct.calcsize("P") == 4`
with the extension present: `pendulum._pendulum` stayed in `sys.modules` and the parser
stayed native while `precise_diff` fell back. It answers a narrower question — which
helper implementation ran — and both readings are worth printing side by side.

## iOS notes

**The extension needs no fixing up.** All three iOS 3.14 slices are already `MH_DYLIB`
marked `NOUNDEFS` (`otool -hv`), which is the filetype Flet 0.86's iOS packaging needs, and
there is no third-party dylib to ship beside it. `nm -gU` exports exactly
`_PyInit__pendulum` and nothing else. The device slice and the x86_64 simulator slice carry
`LC_VERSION_MIN_IPHONEOS`; the arm64 simulator slice carries `LC_BUILD_VERSION` platform 7.

Besides its own install name, `otool -L` names three libraries:
`@rpath/Python.framework/Python`, `/usr/lib/libiconv.2.dylib` and
`/usr/lib/libSystem.B.dylib` — the same three lines [`orjson`](../orjson#ios-notes)'s iOS
wheels carry on this index, and all three are the OS's or CPython's rather than anything
the wheel brings. As orjson's iOS notes record, serious_python turns each site-packages
extension into a framework and leaves a `<name>.fwork` pointer file behind, so as on
Android `pendulum._pendulum.__file__` is not the path in the wheel.

**iOS does not take the Darwin branch of pendulum's local-zone detection.**
`pendulum/tz/local_timezone.py` dispatches on `sys.platform`: `win32` to the registry,
`"darwin" in sys.platform` to `os.readlink("/etc/localtime")`, everything else to the
generic Unix probe. Flet's iOS runtime reports `sys.platform == "ios"` (PEP 730), so it
takes the *same* branch Android takes, on a Darwin ABI. Whether that branch finds anything
inside the app sandbox is the one thing on this page that a simulator cannot settle for
you — the simulator resolves `/etc/localtime` and `/usr/share/zoneinfo` against the host
Mac and would answer correctly whether or not an iPhone does. The
[`dst-clock`](examples/dst-clock) example prints which of those paths exist, so a device
run answers it.

Zone *lookup* by name is safe on iOS either way, because it goes through `tzdata` rather
than through the filesystem.

## Things to know

- **`pendulum.now()` and `pendulum.local_timezone()` are the two calls to distrust on
  mobile.** They route through `_get_system_timezone()`, which on both platforms takes the
  generic Unix branch and tries, in order: `$TZ`, `/etc/timezone`,
  `/etc/sysconfig/clock`, `/etc/conf.d/clock`, an `/etc/localtime` symlink, then
  `/etc/localtime` and `/usr/local/etc/localtime` as files. When none of those exists it
  calls `warnings.warn("Unable not find any timezone configuration, defaulting to UTC.")`
  and returns UTC — reproduced by pointing that function at a root that does not exist. The
  result is then cached in a module global, so the warning fires **once per process**, on
  stderr, where a Flet app shows nothing. Android is where this is expected to bite: it
  keeps its zone database "in a bionic-specific format that Python cannot read", as
  [`pandas`](../pandas#things-to-know) records after reproducing the sibling failure there.
  **Always pass the zone you mean** — `pendulum.now("Europe/Paris")` — or take
  the device's own offset from libc with `datetime.datetime.now().astimezone()`, which does
  not go through `zoneinfo` at all. The example prints both side by side, which is the
  quickest way to see what your device does.
- **`.add(days=1)` and `+ timedelta(days=1)` are different operations on the same object,
  and both compile.** From `2026-03-28 12:00` in Europe/Paris, `.add(days=1)` gives
  `2026-03-29 12:00+02:00` — the same wall clock, 23 real hours later — while
  `+ datetime.timedelta(days=1)` gives `13:00+02:00`, a true 24 hours. Subclassing
  `datetime.datetime` is only what makes both *compile*; the 24-hour answer comes from
  pendulum **overriding** `__add__` to add `delta.total_seconds()`, and it is the reverse
  of the stdlib's own meaning — `datetime(2026, 3, 28, 12, tzinfo=ZoneInfo("Europe/Paris"))
  + timedelta(days=1)` keeps the wall clock and gives `12:00+02:00`, agreeing with
  pendulum's `.add(days=1)` rather than with pendulum's `+`. So the one line that survives a
  port between stdlib and pendulum unchanged is the one that silently changes answer. (A
  `pendulum.duration(days=1)` on the right-hand side goes back to calendar semantics, so the
  operator's meaning depends on the type of *both* operands.) "Same time tomorrow" is `.add(days=1)`;
  "twenty-four hours from now" is `.add(hours=24)` or a `timedelta`. Over a longer span the
  two transitions cancel: 220 days from `2026-03-25 12:00` Paris crosses both and nets
  exactly 5,280 hours, while 4 days crosses only the spring-forward and nets 95 against a
  nominal 96.
- **`DateTime.__add__` decides what to do by looking at the name of the function that
  called it.** It runs `traceback.extract_stack(limit=2)[0].name` on every `+`, and if that
  name is `astimezone` it defers to `datetime.__add__` instead. So the *same* expression
  gives `2026-03-29 12:00+02:00` inside a method or function you happened to call
  `astimezone` and `13:00+02:00` anywhere else. Nothing warns. Do not name a function
  `astimezone` in a module that does pendulum arithmetic — and note that this stack walk
  runs on every single addition, so `+` in a tight loop is far more expensive than it looks;
  prefer `.add(...)` there.
- **Ambiguous and non-existent local times do not raise by default.**
  `pendulum.timezone("Europe/Paris").datetime(2026, 10, 25, 2, 30)` — a wall clock that
  happens twice — returns the post-transition `02:30+01:00`, and
  `…datetime(2026, 3, 29, 2, 30)` — a wall clock that never happens — returns
  `03:30+02:00`. To be told instead, use
  [`Timezone.convert`](https://pendulum.eustace.io/docs/#shifting-time-to-transition):
  `convert(naive_dt, raise_on_unknown_times=True)` raises
  `pendulum.tz.exceptions.AmbiguousTime` and `NonExistingTime`. A stdlib `fold=` on a naive
  datetime carrying the pendulum `Timezone` also works, selecting `+02:00` for `fold=0` and
  `+01:00` for `fold=1`. Note that the constants and the keyword are **not** where older
  code puts them: `pendulum.PRE_TRANSITION` raises `AttributeError` (they live in
  `pendulum.tz`), and `pendulum.datetime(..., dst_rule="pre")` raises
  `TypeError: datetime() got an unexpected keyword argument 'dst_rule'`.
- **Catch broad `Exception` around any parse of user input.**
  `pendulum.parse("not a date")` raises `pendulum.parsing.exceptions.ParserError`, which is
  a `ValueError` subclass — but `pendulum.parse("")` raises a **plain** `ValueError` from
  the `datetime` constructor (its wording changes between Python versions), which
  `except ParserError` does not catch, and an empty text field is the single most likely
  input an app will see. `pendulum.timezone("Mars/Olympus")` raises `InvalidTimezone`, also
  a `ValueError` subclass. An unhandled exception in a Flet handler makes the framework
  crash the session, so the narrow catch is the one that bites.
- **`parse` returns three different types, and that is the point.** `2026-03-29T01:30:00Z`,
  the basic form `20260329T013000Z`, the week date `2026-W14-1` and the ordinal date
  `2026-089` all give a `DateTime`; `P3DT4H5M` gives a `Duration`;
  `2007-03-01T13:00:00Z/2008-05-11T15:30:00Z` gives an `Interval`. A date-only or time-only
  string still gives a `DateTime` with the missing half filled in, unless you pass
  `exact=True`, which gives a `Date` or a `Time` instead. With `strict=False`,
  `March 29 2026 1:30pm`, `29/03/2026` and `Sun, 29 Mar 2026 01:30:00 GMT` parse too — that
  path is where `python-dateutil` earns its place in `Requires-Dist`.
- **ISO-8601 and RFC-3339 output are not the same string.** For a UTC value,
  `to_iso8601_string()` gives `2026-03-29T01:30:00Z` while `to_rfc3339_string()`,
  `to_atom_string()` and `to_w3c_string()` all give `2026-03-29T01:30:00+00:00`. If an API
  contract says one of them, say which.
- **Localisation is fully offline.** 29 locale packages ship in the wheel — `bg cs da de en
  en_gb en_us es fa fo fr he hi id it ja ko lt nb nl nn pl pt_br ru sk sv tr ua zh` — and
  they cost 192 KB of the 900 KB unpacked payload. `dt.format("dddd D MMMM YYYY",
  locale="fr")` gives `dimanche 29 mars 2026`, and
  `pendulum.now().subtract(minutes=95).diff_for_humans(locale="es")` gives `hace 1 hora`.
  An unrecognised name does **not** fall back to English — it raises
  `ValueError: Locale [xx] does not exist.` — and the list is less obvious than it looks:
  there is `pt_br` but no plain `pt`, so `locale="pt"` raises. Validate any locale that
  comes from a device setting rather than from a literal.
- **Do not depend on `pendulum[test]`, and expect `pendulum.travel` to raise.** The extra
  pins `time-machine>=2.6.0,<3.0.0`, and this index publishes `time-machine` 2.16.0 for
  cp312 only and 3.2.0 for cp312/cp313/cp314 — nothing inside that range exists above
  cp312, so the extra cannot resolve for a 3.13 or 3.14 build. Without it,
  [`pendulum.travel`](https://pendulum.eustace.io/docs/#testing), `travel_to` and `freeze`
  raise `NotImplementedError: Time travelling is an optional feature…`. It is a test
  facility; an app has no reason to want it.
- **`pendulum.__version__` still answers but is deprecated**, emitting
  `DeprecationWarning: The '__version__' attribute is deprecated and will be removed in
  Pendulum 3.4` and pointing at `importlib.metadata.version("pendulum")`. That replacement
  reads the `dist-info` directory, which is a packaging artefact rather than something the
  package carries, so wrap it if you put it on screen — the example does.
- **`import pendulum` is not free.** It adds 98 entries to `sys.modules` on a cold
  interpreter and takes 16–18 ms there (best of several, desktop CPython 3.12 on an arm64
  Mac) against `import datetime`'s well under a millisecond. Inside a Flet app most of that
  is not yours: after `import flet`, the marginal cost measured **8–10 ms** for 54 further modules — `datetime`, `decimal`,
  `calendar`, `zoneinfo`, `sysconfig`, the eleven `dateutil` modules and `six`. Phone
  figures will be larger on both sides. If an app only ever formats a timestamp, the
  stdlib is cheaper.
- **Nothing in the package reads the network, spawns a thread or writes a file.** There is
  no `socket`, `urllib`, `http`, `ssl` or `subprocess` import anywhere in it, no
  `threading` and no `Lock`, and the only two `open()` calls are the local-zone probes in
  `tz/local_timezone.py`. So there is no
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  question to answer here, and no background-work rule beyond Flet's own.
- **Size: 313–354 KB to download and 887–932 KB unpacked across the six slices a Flet app
  can actually use, and half of it is the extension.** (The legacy 3.12-only `android_24_x86`
  slice is the outlier at 367 KB / 942 KB.) Per slice on Python 3.14:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | Android arm64-v8a | 335 KB | 900 KB | 459 KB |
  | Android armeabi-v7a | 354 KB | 917 KB | 475 KB |
  | Android x86_64 | 346 KB | 932 KB | 492 KB |
  | iOS arm64 (device) | 313 KB | 900 KB | 459 KB |
  | iOS arm64 (simulator) | 316 KB | 887 KB | 446 KB |
  | iOS x86_64 (simulator) | 328 KB | 888 KB | 447 KB |

  Every slice checked is 127 files. Beyond the extension, the payload is 400 KB of Python
  (192 KB of it locales) and a 40 KB `dist-info`, 22 KB of which is a CycloneDX SBOM naming the 19
  Rust crates the extension was built from. Then add the dependencies, which are the larger
  half of the bill: unpacked, `tzdata` is 502 KB (627 files — 598 `TZif` zone binaries,
  seven text indexes such as `zones` and `zone.tab`, and 22 `.py`),
  `dateutil` 418 KB and `six.py` 34 KB. Staged the way Android packages them — byte-compiled
  to `.pyc` with the sources stripped — pendulum and its three dependencies together came to
  **1.9 MB** in a stored zip. Flet's default
  [package cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) removes
  `_pendulum.pyi` and `py.typed`, which nothing reads at runtime.

## Build notes (maintainers)

The recipe has no patches, and the two `meta.yaml` settings it does carry are not explained
in the file — add those comments before assuming this section covers them. What is here is
the bump checklist, and it is longer than the recipe's size suggests, because almost
everything this README promises is invisible to a green build.

- **A green build proves the extension exists, not that it is used.** Both native imports
  sit behind `try/except ImportError` with working pure-Python twins — deleting the `.so`
  outright still gives a clean import and **2 passed** from `tests/`, measured.
  `tests/test_pendulum.py` should assert
  `pendulum.parsing.parse_iso8601.__module__ == "pendulum._pendulum"` on every slice and
  `pendulum.helpers.precise_diff.__module__ == "pendulum._pendulum"` only on 64-bit ones;
  until it does, nothing anywhere catches a silently dead extension.
- **`tests/test_pendulum.py::test_timezone` is the only assertion in this repo that a named
  IANA zone resolves on a phone**, and everything the Install section claims about `tzdata`
  rests on it — a build cannot fail on it, and the desktop simulation quoted there is not a
  device. Keep it in the suite, and re-run it on a device after a Flet packaging change as
  much as after a pendulum bump. (It also has no docstring, against this repo's test
  convention; fix that when you next touch the file.)
- **The 32-bit `helpers` fallback is upstream's, and it is version-coupled.** If a bump
  removes the `struct.calcsize("P") == 4` guard in `pendulum/helpers.py`, or adds one to
  `pendulum/parsing/__init__.py`, the Android notes are wrong. Grep both files on every
  bump; the runtime tell is the pair of `__module__` values above.
- **`Requires-Dist` is the whole Install section.** The unconditional `tzdata>=2020.1` is
  what makes pendulum different from pandas and polars here. Re-read `METADATA` out of a
  built wheel after a bump — if upstream ever moves `tzdata` behind an environment marker,
  every consumer on Android loses named zones and nothing in the build fails. It does at
  least fail loudly at runtime rather than silently: with `tzdata` unimportable and `TZPATH`
  empty — the shape of an Android device — `import pendulum` itself raises
  `InvalidTimezone: UTC`, because `pendulum/tz/timezone.py` ends on a module-level
  `UTC = Timezone("UTC")` that goes through `zoneinfo`. Both tests in `tests/` import
  pendulum, so the on-device leg does catch this; the build does not. There is no degraded
  mode to detect and no screen an example could print it on; the app simply does not start.
- **The Android 3.12 wheels' extension is named `_pendulum.cpython-312.so` and the Android
  3.13/3.14 ones carry a full platform triple** (the iOS slices are `-iphoneos` /
  `-iphonesimulator` on every Python). Both Android spellings are relocated correctly today.
  If a bump changes which one comes out, confirm the Android on-device import still works
  rather than assuming, since that filename is what serious_python's relocation matches on.
- **The size table, the locale list, the crate count and the module counts are measured.**
  Re-measure them rather than adjusting by eye; the wheel contents are otherwise stable
  enough that a surprise there is worth investigating.
- **Every non-`.so` file is byte-identical between the Android and iOS wheels**, `METADATA`
  included, and the SBOM's component list matches too (the SBOM file itself differs only in
  its serial number, timestamp and build path). That is a cheap post-bump sanity check: if
  `diff -r --exclude='*.so' --exclude=RECORD --exclude=WHEEL --exclude='*.json'` between an
  unpacked Android and iOS wheel stops being empty, something platform-specific leaked into
  the pure-Python half.
- **iOS local-zone detection is unverified on a real device.** The iOS notes say only what
  the code does and which branch it takes; whether `/etc/localtime` resolves inside an iPhone
  sandbox is open, and a simulator run cannot answer it because the simulator reads the host
  Mac's files. If someone runs the example on a device, fold the answer in and delete this
  entry.
