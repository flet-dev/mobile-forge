# psutil

[`psutil`](https://psutil.io/) reads process and system metrics through one API — memory,
CPU time, disks, network interfaces, the process table. On a phone the half that earns its
place is the *process* half: how much memory your app is holding right now, how much CPU it
has burned, how many threads and file descriptors it has open. The standard library gives
you `os.cpu_count()`, `shutil.disk_usage()` and a high-water-mark RSS from
`resource.getrusage`, and then stops; everything else on that list means parsing `/proc`
yourself, which is what psutil is.

**This recipe is Android only, and there is no iOS wheel to fall back on.** `import psutil`
on iOS is a `ModuleNotFoundError`: psutil's platform gate would select its macOS backend
there, which links `IOKit` and calls `libproc`, `host_processor_info` and macOS-only
`sysctl` entries that the iOS app sandbox does not offer. Decide how the app answers these
questions on iOS before you write code against psutil.

## Install

Add psutil to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
]

[tool.flet.android]
dependencies = [
    "psutil",
]
```

**The platform table is not a style choice.** Flet
[appends](https://flet.dev/docs/publish/#app-dependencies) `[tool.flet.<platform>].dependencies`
to the project list rather than replacing it, so a top-level `psutil` entry is handed to the
iOS resolution as well — where there is no wheel to select and the build fails outright.
Declaring it under `[tool.flet.android]` leaves the iOS build resolvable and unchanged.

The cost is worth stating plainly: **psutil is then absent from `flet run` on your desktop
as well**, because nothing outside a `flet build android` run reads that table. Every code
path that touches psutil has to guard the import and have something to say when it fails —
and since that is the path you develop against, it will be exercised constantly.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sandbox-probe`](examples/sandbox-probe) — runs 21 psutil calls and shows, per row, the
  answer or the exception, with five of them checked against a stdlib second source.

## Usage in a Flet app

Guard the import, ask about your own process, and put the numbers into a control:

```python
try:
    import psutil
except Exception:  # not only ModuleNotFoundError — see Things to know
    psutil = None

if psutil is not None:
    me = psutil.Process()
    page.add(
        ft.Text(
            f"{me.memory_info().rss / 1e6:.1f} MB resident · "
            f"{me.num_threads()} threads · {me.cpu_times().user:.1f} s user CPU"
        )
    )
```

[`Process()`](https://psutil.io/api/#psutil.Process) with no argument is your own PID, and
your own numbers are the part that always works. Everything system-wide is a different
question.

### What the sandbox decides

On Android *which calls work* is not an API question. Nearly all of psutil's Linux work is
an `open()` on a file under `/proc` and a `split()` — the C extension covers only the handful
of things `/proc` cannot answer — and an app is confined to its own view of that tree. So the
split below is about file permissions rather than syscalls, and the answer moves with the
Android version rather than with the wheel.

| Reads | Calls | Expectation |
| --- | --- | --- |
| libc only | `cpu_count()` (`sysconf`), `disk_usage()` (`statvfs`), `net_if_addrs()` (`getifaddrs`) | works |
| your own `/proc/<pid>/` | `Process()` and its methods | works — a process can always read its own entry |
| system-wide `/proc` | `cpu_times()`, `cpu_percent()`, `boot_time()` (`/proc/stat`); `virtual_memory()`, `swap_memory()` (`/proc/meminfo`); `disk_partitions()` (`/proc/filesystems`); `net_connections()` (`/proc/net/tcp`) | platform decides |
| the process table | `process_iter()`, `pids()` (`os.listdir('/proc')`) | degrades to what you may see, rather than raising |

Build on the first two rows. Treat the third as a runtime question on the device you care
about rather than a prediction — that is what the
[`sandbox-probe`](examples/sandbox-probe) example is for — and remember that a refusal there
arrives as an exception whose class is probably not the one you would guess (see
[Things to know](#things-to-know)).

Two consequences worth knowing before you design around this:

- **`import psutil` cannot fail because of the sandbox.** psutil reads `/proc/stat` at
  import — to shape the `scputimes` namedtuple and to seed the `cpu_percent` baselines — and
  every one of those reads sits inside a bare `except Exception` whose comment says it does
  not want to crash at import time. An import that fails on Android is a packaging problem,
  not a permission one.
- **Constructing your own `Process` never touches system-wide `/proc`.** `psutil.Process()`
  reads `/proc/<pid>/stat` and nothing else: its identity tuple uses
  `create_time(monotonic=True)`, the raw jiffies value, without adding `boot_time()`. So it
  works even where system-wide CPU statistics do not.

### Storage

psutil writes nothing and creates nothing. The only call that concerns your own files is
[`disk_usage(path)`](https://psutil.io/api/#psutil.disk_usage), a plain `os.statvfs` on
whatever path you hand it — no `/proc`, no privilege — so point it at the directory you are
about to write into:

```python
usage = psutil.disk_usage(os.getenv("FLET_APP_STORAGE_DATA", "."))
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the app-private directory that is never auto-deleted and is included in backups.

**`total`, `used` and `free` need not add up, and that is not a bug.** On Android the whole
function is `statvfs` arithmetic: `total` is `f_blocks × f_frsize`, `used` is what is not
free *to root* (`total − f_bfree × f_frsize`), and `free` is what is free *to you*
(`f_bavail × f_frsize`). The shortfall is therefore exactly the root-reserved blocks,
`(f_bfree − f_bavail) × f_frsize` — a few percent on a filesystem that reserves any, and
zero on one that does not. `percent` is `used / (used + free)`, not `used / total`, so it
reads higher than a naive ratio by the same margin, and equals it when nothing is reserved.

**Do not calibrate that on your Mac.** `_psposix.disk_usage` has an `if MACOS:` branch that
replaces `used` with a call into the macOS extension, so the desktop numbers are not the
device's arithmetic at all: on one APFS volume with zero reserved blocks — where the
shortfall above must therefore be zero — psutil still reported 55 GB unaccounted for `$HOME`,
930 GB for `/`, and two percentages 74 points apart for the same volume. Android takes the
plain branch.

Everything psutil reads for itself lives under `/proc` and `/sys`, at absolute paths.
[`psutil.PROCFS_PATH`](https://psutil.io/api/#psutil.PROCFS_PATH) re-points the `/proc` half
if you need it to, but only for reads *after* import — the four made at import time use the
literal path, and the `/sys` paths are hard-coded throughout.

### Threading

**[`cpu_percent()`](https://psutil.io/api/#psutil.cpu_percent) and `cpu_times_percent()`
keep their non-blocking baseline per thread.** `cpu_percent(interval=None)` returns the busy
share since *this thread's* last call, because the previous reading is stored in a dict
keyed on `threading.current_thread().ident`.
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits
to a `ThreadPoolExecutor`, and a pool makes that baseline *unpredictable* rather than simply
absent — which is worse, because the reading looks plausible. Measured on the stock pool:
six jobs submitted one at a time all ran on the **same** worker, so five of them silently
measured since the *previous* job rather than returning the meaningless `0.0` the docstring
warns about; six submitted at once got six workers and mostly returned `0.0`. Idents are
recycled too, so a new worker can inherit a dead one's stored reading — one genuinely first
call reported `100.0` over a window that had ended some arbitrary time earlier. Either
sample from one thread consistently, or pass a real `interval`, which measures across a
`time.sleep()` inside the call and depends on no stored state.

That `interval` blocks the calling thread for its whole duration, which is the other half of
the same point: `cpu_percent(interval=1)` in an event handler freezes the UI for a second.
That one belongs in a background thread — and the rest do not, since they are a handful of
small file reads.

A [`Process`](https://psutil.io/api/#psutil.Process) instance holds a `threading.RLock`, and
`oneshot()` takes it, so two threads cannot set up and tear down one instance's cache at the
same time. Nothing guards the system-wide state above, which is module-level.

The Flet-side rules apply as everywhere else. A `run_thread` worker must end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads, and its body must be wrapped in
`try/except`, because `run_thread` discards whatever it raises — which here would turn a
permission denial into a screen that quietly stopped updating.

### App size

Around 115 KB compressed and 390–400 KB unpacked per architecture, of which the compiled
extension is 18–29 KB. psutil is therefore never the reason to reach for an app bundle,
split APKs or a narrower
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures);
every Android ABI is published, so those levers stay available for whatever else the app
carries.

### Other considerations

psutil is missing in two of the three places you will run this app — iOS, and a desktop
`flet run` — so the fallback path is the common one rather than an edge case. What to use
for the questions psutil would have answered:

- **Free space** — [`shutil.disk_usage`](https://docs.python.org/3/library/shutil.html#shutil.disk_usage),
  or `os.statvfs` for the raw numbers. `psutil.disk_usage` is itself a `statvfs` call with
  the reserved-block arithmetic above layered on, so this one needs a different spelling
  rather than a substitute.
- **CPU count** — `os.cpu_count()`.
- **Your own memory and CPU** — there is no portable stdlib answer.
  [`resource.getrusage(resource.RUSAGE_SELF)`](https://docs.python.org/3/library/resource.html#resource.getrusage)
  gives CPU times and `ru_maxrss`, which is a high-water mark rather than current RSS —
  check first that the runtime ships `resource`, since Flet's iOS Python omits some POSIX
  modules (`pwd`, for one). Anything more precise means calling the platform through
  [`pyobjus`](../pyobjus), declared under `[tool.flet.ios] dependencies`.

Two further differences you will only meet by leaving the desktop. `psutil.heap_info()` and
`psutil.heap_trim()` exist on a desktop Linux box and not here — they are gated on the C
extension exporting `heap_info`, a glibc `mallinfo2` feature bionic does not provide, so
`hasattr(psutil, "heap_info")` is the check and it is `False` on device. And the namedtuples
are the Linux ones, not the macOS ones your development machine returns, which fails silently
rather than loudly and has its own bullet below.

If your app needs the same numbers on both platforms, write the abstraction first and let
psutil be one implementation of it. Retrofitting that after the Android screen is built
against `Process()` is the expensive order.

## Things to know

- **Guard the import, and mean it.** Because psutil lives in `[tool.flet.android]
  dependencies`, `import psutil` fails on iOS *and* on your desktop `flet run`. Catch
  `Exception` rather than `ModuleNotFoundError` alone: a psutil built without this recipe's
  platform patch raises `NotImplementedError: platform android is not supported` from the
  same statement.
- **`except psutil.Error:` is the wrong guard for half the API.** `wrap_exceptions` in
  psutil's Linux backend maps `PermissionError` to `AccessDenied` and `ProcessLookupError`
  to `NoSuchProcess`, and it decorates only `Process` methods. `virtual_memory`,
  `swap_memory`, `cpu_times`, `disk_partitions`, `boot_time` and `net_connections` are
  undecorated module functions, so a denial there arrives as a plain `PermissionError` that
  [`except psutil.Error:`](https://psutil.io/api/#psutil.Error) does not catch. Use
  `except (psutil.Error, OSError):` around any system-wide call, and keep
  [`except psutil.AccessDenied:`](https://psutil.io/api/#psutil.AccessDenied) for the
  `Process` methods where it genuinely fires. An unhandled exception in a Flet event handler
  ends the session, so this is a crash-versus-no-crash difference rather than a style point.
- **The namedtuples are not the shape your Mac showed you.** psutil returns
  platform-specific tuples, and the Linux ones are wider than the macOS ones — read off the
  Android wheel's `psutil/_ntuples.py` against a macOS install of the same release:
  `memory_info()` is `(rss, vms, shared, text, lib, data, dirty)` against
  `(rss, vms, pfaults, pageins)`; `virtual_memory()` has eleven fields against eight and only
  the first seven names line up; `Process.cpu_times()` has five against four (Linux adds
  `iowait`); `open_files()` entries carry `(path, fd, position, mode, flags)` against
  `(path, fd)`. Positional unpacking that works on your laptop silently misaligns here. Use
  `._asdict()` or attribute access, and read the field names off the device — the
  [`sandbox-probe`](examples/sandbox-probe) example prints every tuple as `name=value` pairs
  for exactly this reason.
- **[`cpu_count(logical=False)`](https://psutil.io/api/#psutil.cpu_count) will very likely
  be `None`, not a number.** The physical-core path globs
  `/sys/devices/system/cpu/cpu*/topology/{core_cpus_list,thread_siblings_list}` — and `glob`
  swallows a permission error into an empty list — then falls back to parsing `physical id`
  and `cpu cores` out of `/proc/cpuinfo`, keys an ARM `/proc/cpuinfo` does not emit, and
  finishes with `return result or None`. Note the asymmetry: if `/proc/cpuinfo` itself is
  unreadable the function raises instead of returning `None`. `cpu_count()` without the
  argument is the reliable one — it is `os.sysconf("SC_NPROCESSORS_ONLN")`.
- **[`disk_partitions()`](https://psutil.io/api/#psutil.disk_partitions) and
  `disk_partitions(all=True)` are different questions, not a verbosity flag.** The
  `/proc/filesystems` read and the fstype filter that depends on it are both inside
  `if not all:`; the mount list itself comes from the C extension, reading
  `/proc/self/mounts` — or `realpath("/etc/mtab")`, which it prefers whenever `PROCFS_PATH`
  is left at its default and that file exists. So if `disk_partitions()` raises, try
  `disk_partitions(all=True)` before concluding that mount enumeration is unavailable.
- **[`swap_memory()`](https://psutil.io/api/#psutil.swap_memory) fails soft where its
  neighbours fail hard.** Its `/proc/vmstat` read is wrapped, and an `OSError` there produces
  a `RuntimeWarning` — *"'sin' and 'sout' swap memory stats couldn't be determined and were
  set to 0"* — and a tuple whose `sin`/`sout` are lies rather than an exception. Its
  `/proc/meminfo` read is not wrapped. A warning is invisible on a phone unless you look for
  it, so if you display those two fields, capture warnings around the call.
- **A `/proc/stat` that becomes readable later gives you a `TypeError`, not a permission
  error.** When the import-time probe fails, psutil sets `ntp.scputimes` to an *instantiated*
  three-field tuple instead of a class, and `cpu_times()` later does `ntp.scputimes(*fields)`
  on it. In practice `cpu_times()` re-opens `/proc/stat` first and raises `PermissionError`
  before reaching that line, so this only appears if readability changes after import — but
  `TypeError: 'scputimes' object is not callable` is worth recognising as this and not as
  your own bug.
- **psutil starts no threads, opens no network connections and never shells out to collect a
  metric.** [`psutil.Popen`](https://psutil.io/api/#psutil.Popen) spawns a process only if
  *you* call it; `socket` is imported for address-family constants and one `supports_ipv6()`
  probe that binds a local IPv6 socket; and `inspect` is imported lazily inside `debug()`,
  only when `PSUTIL_DEBUG` is set in the environment, so Flet's default
  [compile-to-`.pyc` cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) takes
  nothing psutil reads back.

## Build notes (maintainers)

### Recipe shape

One line of patch and nothing else, which is the fact worth recording: a package that reads
`/proc` in Python and keeps a small C module for the handful of things `/proc` cannot answer
needs no cross-compilation help beyond forge's stock support — no `build.sh`, no
`requirements`, no `script_env`. If a future version needs any of that, suspect an upstream
restructuring or the toolchain before reaching for a second patch.

The index carries ten wheels at one build number: Python 3.12 across all four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `x86`), and 3.13 and 3.14 across three
each. They are per-Python wheels despite the `_psutil_linux.abi3.so` filename, which comes
from upstream setting `py_limited_api` on Linux: each is tagged `cp3XX-cp3XX` and links its
own `libpython3.<minor>.so`. Two claims in the merged
[pull request](https://github.com/flet-dev/mobile-forge/pull/71) therefore do not survive
inspection of the wheels — that this ships as a real `Py_LIMITED_API` abi3 wheel, and that
the patch selects a `_psutil_posix` extension, of which there is none.

The Android packaging needs no help either: nothing in the package reads a path relative to
its own `__file__`, and the extension's `.abi3` suffix is one of the two spellings
serious_python recognises as an extension module to relocate into `jniLibs` (the other being
`.cpython-*`).

### Upgrade hazards

- The patch changes one line of `psutil/_common.py`, and that constant is the single gate
  for both the build and the import. A release that splits or renames it leaves a patch that
  still applies and a wheel that builds and cannot import.
- Upstream widens the Linux namedtuples without ceremony. The field lists in
  **Things to know** are consumer-facing, and nothing in `tests/` asserts a field name.
- `HAS_PROC_IO_PRIORITY` and `HAS_CPU_AFFINITY` are `hasattr(cext, ...)` gates, so the
  extension's exported set decides which public functions exist. `heap_info`'s absence is a
  bionic fact rather than a psutil one and will not move with a bump.
- The day upstream publishes Android wheels of its own, a bare `psutil` resolves from PyPI
  for an Android target and this recipe may stop being needed.

### Re-verification checklist

- **That the patch still lands on the only platform gate.** `setup.py` must still do
  `from _common import LINUX` and still end its platform chain with
  `sys.exit("platform {} is not supported")`, and `psutil/__init__.py` must still run the
  same chain at import. A patch that applies but covers only one half builds a wheel that
  cannot import.
- **The `.py` files against the sdist, not against a PyPI wheel.** PyPI's binary wheel is not
  identical to its own sdist (`__init__.py` carries `"STATUS_LOCKED"` twice in `__all__`, 21
  bytes more), so that comparison reports a difference the recipe did not make.
- **The capability table under Usage.** It is derived from which file each function opens and
  whether the open is guarded, so re-grep the `open_binary(`/`open_text(` call sites in
  `_pslinux.py` and re-check which definitions `wrap_exceptions` decorates. Either moves a
  consumer-facing row.
- **The namedtuple shapes**, from the `if LINUX:` block of `psutil/_ntuples.py` in the *new*
  wheel, and **the extension's exported set**, which `strings` on the `.so` lists.
- **The linkage and the filename.** `DT_NEEDED` still
  `libm`/`libpython3.<minor>`/`libdl`/`libc` with no `libc++_shared`, 16 KB `PT_LOAD`
  alignment on all four ABIs, and an ABI tag still in the extension's name — an untagged
  `.so` is a silent `ModuleNotFoundError` on device, since serious_python keys its `jniLibs`
  relocation on that suffix.
- **That psutil still publishes no mobile wheels of its own**, and **the sizes**, re-measured
  from the built wheels rather than scaled. The page quotes them decimal; `du` is binary.

### Coverage gaps

`tests/test_psutil.py` is three functions — `cpu_count`, `virtual_memory` and a
self-`Process` — and it is the only device evidence behind this page. The merged pull
request records it passing on an Android emulator under Python 3.12, which is also the only
direct evidence that `/proc/meminfo` is readable at all; an emulator is not a production
device, and every other row of the capability table is reasoning from the shipped source.

The additions that would protect what is claimed above, in rough order of value:
`disk_usage(os.getcwd())` returning a positive `total`, since it is pure `statvfs` and must
work everywhere; the exception-translation asymmetry, asserting that a system-wide
function's failure is *not* a `psutil.Error` subclass; one namedtuple field-name assertion
(`memory_info()._fields`), the claim most likely to move on a bump; and `net_if_addrs()`
returning at least a loopback entry, the only C-extension path outside `disk_partitions` a
consumer is likely to call. The system-wide `/proc` readers are deliberately not on that
list — asserting them would encode one emulator's permissions as a requirement, and
reporting what they do is the example's job rather than CI's.
