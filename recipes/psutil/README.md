# psutil

[`psutil`](https://psutil.io/) reads process and system metrics through one API — memory,
CPU time, disks, network interfaces, the process table. On a phone the half that earns its
place is the *process* half: how much memory your app is holding right now, how
much CPU it has burned, how many threads and file descriptors it has open. The standard
library gives you `os.cpu_count()`, `shutil.disk_usage()` and a high-water-mark RSS from
`resource.getrusage`, and then stops; everything else on that list means parsing `/proc`
yourself, which is what psutil is.

**This recipe is Android only, deliberately, and there is no iOS wheel to fall back on.**
`import psutil` on iOS is a `ModuleNotFoundError`; the reason is structural rather than a
build that has not been attempted yet, and the alternatives are in [iOS notes](#ios-notes).
Plan for that before you write code against psutil, because it means the package cannot go
in `[project] dependencies` at all — see [Install](#install).

The second thing to know before you start is that on Android *which calls work* is not an
API question. Everything psutil reports about the whole system it parses out of files under
`/proc`, and an app is confined to its own view of that tree. Calls that go through libc
(`cpu_count`, `disk_usage`, `net_if_addrs`) and calls that read your own
`/proc/<pid>/` files behave normally; calls that read system-wide files
(`/proc/stat`, `/proc/meminfo`, `/proc/net/tcp`) or enumerate other processes are decided by
the platform, and the answer moves with the Android version. The
[`sandbox-probe`](examples/sandbox-probe) example exists to give you that answer on a device
you care about rather than a prediction.

## Install

```toml
# pyproject.toml
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
to the project list rather than replacing it (`flet_cli/commands/build_base.py`:
`toml_dependencies.extend(platform_dependencies)`), so a top-level `psutil` entry is handed
to the iOS resolution too — and there is no wheel on the index for it to select. Declaring
it under `[tool.flet.android]` keeps the iOS build resolvable and unchanged.

The cost of that is worth stating plainly: **psutil is then absent from `flet run` on your
desktop as well**, because nothing outside a `flet build android` run reads that table. App
code has to guard the import and have something to say when it fails; the example does
exactly this and is the honest shape to copy.

Nothing else comes along with it. The wheel's `METADATA` carries 38 `Requires-Dist` lines
and every one of them is gated on `extra == "dev"` or `extra == "test"`, so no `flet-lib*`
wheel and no transitive dependency follows psutil in.

No [`[tool.flet.android] extract_packages`](https://flet.dev/docs/publish/android/#extract-packages)
entry is needed either. The whole wheel is sixteen entries — ten `.py` files, one extension
and five `dist-info` files — with no data file of any kind, so the Flet 0.86 Android
`sitepackages.zip` class of failure has nothing to bite on. Nothing in the package reads a
path relative to its own `__file__` either: every file psutil opens is an absolute
`/proc/...` or `/sys/...` path, so running out of a zip is irrelevant to it. The extension
is named `psutil/_psutil_linux.abi3.so`, and an `.abi3` suffix is one of the two spellings
serious_python's Android packaging recognises as an extension module to relocate into
`jniLibs` (the other is `.cpython-*`; see the comment in `src/forge/build.py`), so it needs
no shim.

Ten wheels on the index at the same build number: Python 3.12 across all four Android ABIs
(arm64-v8a, armeabi-v7a, x86_64 and the legacy 32-bit `android_24_x86`), and 3.13 and 3.14
across three each. That is the standard forge matrix, so no
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures)
narrowing is needed. `Requires-Python` in the wheel is upstream's `>=3.6`, so the floor you
will actually hit is Flet's. And nothing on PyPI competes for these targets: upstream's own
7.2.2 release is 21 files — macOS, manylinux, musllinux, Windows and an sdist — with not one
Android or iOS tag among them.

## Storage

psutil writes nothing and creates nothing. The only call that concerns your own files is
[`disk_usage(path)`](https://psutil.io/api/#psutil.disk_usage), which is a plain
`os.statvfs` on whatever path you hand it (`psutil/_psposix.py`) — no `/proc`, no privilege
— so point it at the directory you are about to write into:

```python
usage = psutil.disk_usage(os.getenv("FLET_APP_STORAGE_DATA", "."))
```

[`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
is the app-private directory that is never auto-deleted and is included in backups.

**`total`, `used` and `free` need not add up, and that is not a bug.** On Android the whole
function is plain `statvfs` arithmetic: `total` is `f_blocks × f_frsize`, `used` is what is
not free *to root* (`total − f_bfree × f_frsize`), and `free` is what is free *to you*
(`f_bavail × f_frsize`). The shortfall is therefore exactly the root-reserved blocks,
`(f_bfree − f_bavail) × f_frsize` — a few percent on a filesystem that reserves any, and
zero on one that does not. `percent` is `used / (used + free)`, not `used / total`, so it
reads higher than a naive ratio by the same margin, and equals it when nothing is reserved.

**Do not calibrate that on your Mac.** `_psposix.disk_usage` has an `if MACOS:` branch that
replaces `used` with `_psutil_osx.disk_usage_used(path, used)`, so the desktop numbers are
not the device's arithmetic at all: on one APFS volume where `f_bfree == f_bavail` — zero
reserved blocks, so the shortfall above must be zero — psutil 7.2.2 still reported 55 GB
unaccounted for `$HOME` and 930 GB for `/`, and two percentages 74 points apart for the same
volume. Android takes the plain branch; a Mac reading tells you nothing about it.

Everything psutil reads for itself lives under `/proc` and `/sys`, at absolute paths.
[`psutil.PROCFS_PATH`](https://psutil.io/api/#psutil.PROCFS_PATH) re-points the `/proc`
half of that if you ever need it to — every `/proc` read *after import* goes through
`_common.get_procfs_path()`, while the four at import time (the `scputimes` probe and three
`os.path.exists` checks in `psutil/_pslinux.py`) use the literal `/proc` and cannot be
redirected. The `/sys` paths are hard-coded literals and are not affected either.

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`sandbox-probe`](examples/sandbox-probe) — runs 21 psutil calls and shows, per row, the
  answer or the exception, with five of them checked against a stdlib second source.

## Threading

**[`cpu_percent()`](https://psutil.io/api/#psutil.cpu_percent) and `cpu_times_percent()`
keep their non-blocking baseline per thread.** `cpu_percent(interval=None)` returns the
busy share since *this thread's* last call, because the previous reading is stored in a
dict keyed on `threading.current_thread().ident` (`psutil/__init__.py`, `_last_cpu_times`
and its three siblings).
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) submits
to a `ThreadPoolExecutor`, and a pool makes that baseline *unpredictable* rather than
simply absent — which is worse, because the reading looks plausible. Measured on the stock
`ThreadPoolExecutor` 0.86.5 builds in `flet/app.py`: six jobs submitted one at a time all
ran on the **same** worker, so only the first returned the meaningless `0.0` the docstring
warns about and the other five measured since the previous job; six submitted at once got
six workers and mostly returned `0.0`. And thread idents are recycled, so a brand-new worker
can inherit a dead one's ident and with it its stored reading — in that run a genuinely
first call reported `100.0` instead of `0.0`, over a window that had ended some arbitrary
time earlier. Either sample from one thread consistently, or pass a real `interval`, which
measures across a `time.sleep()` inside the call and depends on no stored state.

That `interval` blocks the calling thread for its whole duration, which is the other half of
the same point: `cpu_percent(interval=1)` in an event handler freezes the UI for a second.
That one belongs in a background thread — and everything else here does not, since the
remaining calls are a handful of small file reads.

A [`Process`](https://psutil.io/api/#psutil.Process) instance does hold a
`threading.RLock`, and `oneshot()` takes it, so two threads cannot set up and tear down one
instance's cache at the same time. Nothing guards the system-wide state above, which is
module-level.

The Flet-side rules apply as everywhere else. A `run_thread` worker must end with an
explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), because
auto-update does not reach background threads, and its body must be wrapped in
`try/except`, because `run_thread` discards whatever it raises — which here would turn a
permission denial into a screen that quietly stopped updating.

## Android notes

**`import psutil` cannot fail because of the sandbox.** psutil reads `/proc/stat` at import
— to shape the `scputimes` namedtuple (`psutil/_pslinux.py`) and to seed the `cpu_percent`
baselines (`psutil/__init__.py`) — and every one of those reads sits inside a bare
`except Exception` whose comment says "Don't want to crash at import time". The remaining
import-time probes are `os.path.exists` on two `/proc/<pid>/smaps*` paths,
`os.sysconf("SC_CLK_TCK")` and `cext.getpagesize()`, none of which raise on a denial. So an
import that fails on Android is a packaging problem, not a permission one.

**What is decided by the platform, and what is not.** The split is not by ABI; it is by what
the call reads.

| Reads | Calls | Expectation |
| --- | --- | --- |
| libc only | `cpu_count()` (`sysconf`), `disk_usage()` (`statvfs`), `net_if_addrs()` (`getifaddrs`) | works |
| your own `/proc/<pid>/` | `Process()` and its methods | works — a process can always read its own entry |
| system-wide `/proc` | `cpu_times()`, `cpu_percent()`, `boot_time()` (`/proc/stat`); `virtual_memory()`, `swap_memory()` (`/proc/meminfo`); `disk_partitions()` (`/proc/filesystems`); `net_connections()` (`/proc/net/tcp`) | platform decides |
| the process table | `process_iter()`, `pids()` (`os.listdir('/proc')`) | degrades to what you may see, rather than raising |

Three of the calls in that table have device evidence behind them, plus the import
itself:
`tests/test_psutil.py` asserts `virtual_memory().total > 0` and
`Process(os.getpid()).memory_info().rss > 0`, and that `cpu_count()` returns `None` or a
positive int — which makes that third row evidence that the call does not *raise*, not that
it answers. The merged recipe
[pull request](https://github.com/flet-dev/mobile-forge/pull/71) records that test passing on
an Android emulator under Python 3.12 — which is also the only direct evidence that
`/proc/meminfo` is readable. Everything else in that table is reasoning from the shipped
source, and an emulator is not a production device. That gap is what
[`sandbox-probe`](examples/sandbox-probe) is for.

**A denial is a plain `PermissionError`, not `psutil.AccessDenied` — for the system-wide
calls.** `wrap_exceptions` in `psutil/_pslinux.py` maps `PermissionError` to `AccessDenied`
and `ProcessLookupError` to `NoSuchProcess`, and it decorates only `Process` methods.
`virtual_memory`, `swap_memory`, `cpu_times`, `disk_partitions`, `boot_time` and
`net_connections` are undecorated module functions, so
[`except psutil.Error:`](https://psutil.io/api/#psutil.Error) does not catch what they
raise. In an app that is the difference between a handled row and a Flet crash screen.

**The extension links nothing but the interpreter and bionic.** `DT_NEEDED` is `libm.so`,
`libpython3.<minor>.so`, `libdl.so` and `libc.so` on every slice, with no `SONAME`, `RPATH`
or `RUNPATH` and no `libc++_shared`, so none of the usual Android C++ staging applies. Of
the 79 undefined symbols on the 3.14 arm64-v8a slice, the 42 outside CPython's own API are
all bionic libc — `getifaddrs`/`freeifaddrs`/`getnameinfo` for `net_if_addrs`,
`setmntent`/`getmntent`/`endmntent` for `disk_partitions`, `sched_getaffinity`,
`getpriority`, `sysinfo`, `socket`/`ioctl` for the interface flags, and the ordinary string
and stdio family. All `PT_LOAD` segments carry 16 KB alignment, which Android 15 requires.
arm64-v8a and x86_64 are `ELF64`; armeabi-v7a and the legacy `x86` slice are genuine
`ELF32`/`ARM` and `ELF32`/`i386` builds rather than stubs.

**The extension is small because most of psutil's Linux work is Python.** Its whole surface
is seventeen functions: `disk_partitions`, `net_if_addrs` and the four `net_if_*` helpers,
`users`, `getpagesize`, `linux_sysinfo`, `check_pid_range`, `set_debug`, and the three
get/set pairs for priority, I/O priority and CPU affinity. Everything else you call is an
`open()` on a file under `/proc` and a `split()`, which is exactly why the capability table
above is about file permissions rather than about syscalls.

## iOS notes

**Nothing ships, and nothing is expected to.** The index carries ten psutil wheels and all
ten are `android_24_*`; `meta.yaml` says `platforms: [android]`. The reason is in the
recipe's patch preamble and in `meta.yaml`'s own comment: on iOS psutil's platform gate
selects the macOS backend `_psutil_osx`, which links the `IOKit` framework and calls
`libproc`, `host_processor_info` and macOS-only `sysctl` entries that iOS either does not
expose or restricts inside the app sandbox. The one-line "treat android as Linux" fix that
makes Android work has no iOS analogue, because iOS is not the platform whose backend is
wrong — it is the platform whose backend cannot run.

What to use instead, for the questions psutil would have answered:

- **Free space** — [`shutil.disk_usage`](https://docs.python.org/3/library/shutil.html#shutil.disk_usage),
  or `os.statvfs` for the raw numbers. `psutil.disk_usage` is itself a `statvfs` call with
  the reserved-block arithmetic above layered on; this one needs no substitute, only a
  different spelling.
- **CPU count** — `os.cpu_count()`.
- **Your own memory and CPU** — there is no portable stdlib answer.
  [`resource.getrusage(resource.RUSAGE_SELF)`](https://docs.python.org/3/library/resource.html#resource.getrusage)
  gives CPU times and `ru_maxrss`, which is a high-water mark rather than current RSS —
  check first that the runtime ships `resource`, since Flet's iOS Python omits some POSIX
  modules (`pwd`, for one). Anything more precise means calling the platform through
  `pyobjus`, declared under `[tool.flet.ios] dependencies` — the twin of the table in
  [Install](#install).

If your app needs the same numbers on both platforms, write the abstraction first and let
psutil be one implementation of it. Retrofitting that after the Android screen is built
against `Process()` is the expensive order.

## Things to know

- **Guard the import, and mean it.** Because psutil lives in `[tool.flet.android]
  dependencies`, `import psutil` fails on iOS *and* on your desktop `flet run` — so the
  failing path is the one you develop against, and it will be exercised constantly. Catch
  `Exception` rather than `ModuleNotFoundError` alone: a psutil built without this recipe's
  platform patch raises `NotImplementedError: platform android is not supported` from the
  same statement.
- **`except psutil.Error:` is the wrong guard for half the API.** Only `Process` methods are
  exception-translated (see [Android notes](#android-notes)). Use
  `except (psutil.Error, OSError):` — or plain `except Exception:` — around any system-wide
  call, and keep
  [`except psutil.AccessDenied:`](https://psutil.io/api/#psutil.AccessDenied) for the
  `Process` methods where it genuinely fires. An unhandled exception in a Flet event
  handler ends the session, so this is a crash-versus-no-crash difference rather than a
  style point.
- **The namedtuples are not the shape your Mac showed you.** psutil returns
  platform-specific tuples, and the Linux ones are wider than the macOS ones — measured on
  7.2.2, from the Android wheel's `psutil/_ntuples.py` against a macOS install of the same
  version: `memory_info()` is `(rss, vms, shared, text, lib, data, dirty)` against
  `(rss, vms, pfaults, pageins)`; `virtual_memory()` has eleven fields against eight and only
  the first seven names line up; `Process.cpu_times()` has five against four (Linux adds
  `iowait`); `open_files()` entries carry `(path, fd, position, mode, flags)` against
  `(path, fd)`. Positional unpacking that works on your laptop silently misaligns here. Use
  `._asdict()` or attribute access, and read field names off the device — the
  [`sandbox-probe`](examples/sandbox-probe) example prints every tuple as `name=value` pairs
  for exactly this reason.
- **[`cpu_count(logical=False)`](https://psutil.io/api/#psutil.cpu_count) will very likely
  be `None`, not a number.** The physical-core path globs
  `/sys/devices/system/cpu/cpu*/topology/{core_cpus_list,thread_siblings_list}` — and `glob`
  swallows a permission error into an empty list — then falls back to parsing
  `physical id` and `cpu cores` out of `/proc/cpuinfo`, keys an ARM `/proc/cpuinfo` does not
  emit, and finishes with `return result or None`. Note the asymmetry: if `/proc/cpuinfo`
  itself is unreadable the function raises instead of returning `None`. `cpu_count()`
  without the argument is the reliable one — it is `os.sysconf("SC_NPROCESSORS_ONLN")`.
- **[`disk_partitions()`](https://psutil.io/api/#psutil.disk_partitions) and
  `disk_partitions(all=True)` are different questions, not a verbosity flag.** The
  `/proc/filesystems` read and the fstype filter that depends on it are both inside
  `if not all:`; the mount list itself comes from the C extension, reading
  `/proc/self/mounts` — or `realpath("/etc/mtab")`, which it prefers whenever `PROCFS_PATH`
  is left at its default and that file exists. So if `disk_partitions()` raises, try
  `disk_partitions(all=True)` before concluding that mount enumeration is unavailable.
- **[`swap_memory()`](https://psutil.io/api/#psutil.swap_memory) fails soft where its
  neighbours fail hard.** Its `/proc/vmstat` read is
  wrapped, and an `OSError` there produces a `RuntimeWarning` — *"'sin' and 'sout' swap
  memory stats couldn't be determined and were set to 0"* — and a tuple whose `sin`/`sout`
  are lies rather than an exception. Its `/proc/meminfo` read is not wrapped. A warning is
  invisible on a phone unless you look for it, so if you display those two fields, capture
  warnings around the call.
- **A `/proc/stat` that becomes readable later gives you a `TypeError`, not a permission
  error.** When the import-time probe fails, psutil sets `ntp.scputimes` to an *instantiated*
  three-field tuple instead of a class, and `cpu_times()` later does `ntp.scputimes(*fields)`
  on it. In practice `cpu_times()` re-opens `/proc/stat` first and raises `PermissionError`
  before reaching that line, so this only appears if readability changes after import — but
  `TypeError: 'scputimes' object is not callable` is worth recognising as this and not as
  your own bug.
- **`psutil.heap_info()` and `psutil.heap_trim()` do not exist on Android.** They are gated
  on the C extension exporting `heap_info`, which is a glibc `mallinfo2` feature; the shipped
  `.so` exports no such symbol, because bionic is not glibc. `hasattr(psutil, "heap_info")`
  is the check, and it is `False` here while being `True` on a desktop Linux box — a
  difference that will not show up until the device.
- **The `.abi3.so` filename does not mean one wheel serves every Python.** Upstream sets
  `py_limited_api` for Linux builds (`setup.py`), which is where the name comes from, but
  each wheel here still links its own interpreter: `DT_NEEDED` names `libpython3.12.so` on
  the 3.12 wheels and `libpython3.14.so` on the 3.14 ones, and the wheel tags are
  correspondingly `cp312-cp312` and `cp314-cp314`. There is nothing to do about this as a
  consumer — resolution picks the right one — but do not conclude from the filename that a
  wheel is portable across minors.
- **Constructing a `Process` for yourself touches only your own `/proc` entry.**
  `psutil.Process()` reads `/proc/<pid>/stat` and nothing else: its identity tuple uses
  `create_time(monotonic=True)`, which returns the raw jiffies value *without* adding
  `boot_time()`. So construction never reads system-wide `/proc/stat`, and works even where
  system-wide CPU statistics do not.
- **psutil starts no threads, opens no network connections and never shells out to collect a
  metric.** It does not, however, avoid `subprocess` altogether: `psutil/__init__.py` imports
  it and calls `subprocess.Popen` inside the public
  [`psutil.Popen`](https://psutil.io/api/#psutil.Popen) wrapper class, which spawns a process
  only if *you* call it. (`_psaix.py` and `_pssunos.py` do shell out for their own metrics,
  but neither backend can load here.) `socket` is imported for address-family constants and one
  `supports_ipv6()` probe that binds a local IPv6 socket. `inspect` is imported lazily inside
  `debug()` and only when `PSUTIL_DEBUG` is set in the environment, so Flet's default
  [compile-to-`.pyc` cleanup](https://flet.dev/docs/publish/#compilation-and-cleanup) takes
  nothing psutil reads back.
- **Size: 113–116 KB to download, 388–399 KB unpacked, and the extension is 4.6–7.2% of
  that.** Per slice:

  | slice | wheel | unpacked | the `.so` alone |
  | --- | --- | --- | --- |
  | cp314 arm64-v8a | 115,022 B | 398,630 B | 28,752 B |
  | cp314 x86_64 | 115,267 B | 396,859 B | 26,984 B |
  | cp312 arm64-v8a | 115,005 B | 398,486 B | 28,608 B |
  | cp312 armeabi-v7a | 113,136 B | 387,872 B | 17,992 B |
  | cp312 x86 (32-bit) | 115,610 B | 394,644 B | 24,772 B |

  Note where the bulk actually goes: **122,096 bytes — 30.6% of the unpacked cp314 arm64
  wheel — is `_psaix.py`, `_psbsd.py`, `_psosx.py`, `_pssunos.py` and `_pswindows.py`**,
  backends that can never be selected on Android. Another 25 KB is `dist-info`. That leaves
  roughly 222 KB of Python that can run and 29 KB of native code. There is no `tests`
  package in the wheel, no `.pyi` stub and no `py.typed`. The extension is small partly
  because it is stripped: it carries no `.symtab` and no `.debug_*` sections, where
  upstream's own `manylinux2014_aarch64` build of the same version — the same architecture —
  ships both and is 321,912 bytes.

## Build notes (maintainers)

The patch explains itself in its own preamble and `meta.yaml` carries its own comments, so
what is left here is shape, two corrections, and the bump checklist.

**The shape is one line of patch and nothing else**, which is the fact worth recording: a
package that reads `/proc` in Python and keeps a small C module for the handful of things
`/proc` cannot answer needs no cross-compilation help beyond forge's stock support — no
`build.sh`, no `requirements`, no `script_env`. If a future version needs any of that,
suspect an upstream restructuring or the toolchain before reaching for a second patch.

Two claims made in the merged [pull request](https://github.com/flet-dev/mobile-forge/pull/71)
do not survive inspection of the wheels and should not be repeated:

- It says the recipe "ships as a real `Py_LIMITED_API` abi3 wheel". The *filename* is
  `_psutil_linux.abi3.so`, because upstream's `setup.py` sets `py_limited_api` on Linux, but
  the wheels are tagged `cp312-cp312` / `cp313-cp313` / `cp314-cp314` and each links its own
  `libpython3.<minor>.so`. They are per-Python wheels, and building them that way is correct.
- It says the patch "selects the correct `_psutil_linux`/`_psutil_posix` extensions". There
  is no `_psutil_posix` in psutil 7.2.2 — the wheel contains exactly one native file, and
  `_psposix.py` is pure Python.

What to re-verify on a bump, in rough order of what a green build fails to tell you:

- **That the patch still lands on the only platform gate.** It changes one line of
  `psutil/_common.py` (`LINUX = sys.platform.startswith(...)`). Confirm the constant is still
  the single gate for both halves — `setup.py` still doing `from _common import LINUX` and
  still ending its platform chain with `sys.exit("platform {} is not supported")`, and
  `psutil/__init__.py` still running the same chain at import. A patch that applies but no
  longer covers both halves produces a wheel that builds and cannot import.
- **The `.py` files against the sdist, not against a PyPI wheel.** Every `.py` in the shipped
  wheel is byte-identical to `psutil-7.2.2.tar.gz`'s except the one patched line — but the
  PyPI `cp36-abi3` binary wheel is *not* identical to its own sdist (its `__init__.py`
  carries `"STATUS_LOCKED"` twice in `__all__`, 21 bytes more). Diff against the sdist; a
  comparison against the binary wheel reports a difference the recipe did not make.
- **The capability table in [Android notes](#android-notes).** It is derived from which file
  each function opens and whether the open is guarded; a release that adds a guard, changes a
  path, or moves a function under `wrap_exceptions` moves a consumer-facing row. Re-grep the
  `open_binary(`/`open_text(` call sites in `_pslinux.py` and re-check which definitions
  `wrap_exceptions` decorates.
- **The namedtuple shapes.** Read the `if LINUX:` block of `psutil/_ntuples.py` in the *new*
  wheel and re-derive the field lists in [Things to know](#things-to-know). Upstream widens
  these without ceremony, and nothing in `tests/` asserts a field name.
- **Whether the C extension gained or lost functions.** `heap_info` being absent is a bionic
  fact, but `HAS_PROC_IO_PRIORITY` and `HAS_CPU_AFFINITY` are also `hasattr(cext, ...)` gates,
  and the exported set is what decides them. `strings` on the `.so` lists them.
- **The linkage and the filename.** `DT_NEEDED` still `libm`/`libpython3.<minor>`/`libdl`/`libc`
  with no `libc++_shared`, 16 KB `PT_LOAD` alignment on all four ABIs, and the extension
  still named with an ABI tag — an *untagged* `.so` would be a silent `ModuleNotFoundError`
  on device, since serious_python keys its `jniLibs` relocation on that suffix.
- **That psutil still has no mobile wheels of its own on PyPI.** Today it publishes none, so
  a bare `psutil` can only resolve from this index for an Android target; the day upstream
  ships one, this recipe may stop being needed.
- **The size table**, which is measured, including the share that is other platforms'
  backends.

`tests/test_psutil.py` is three docstringed functions — `cpu_count`, `virtual_memory` and a
self-`Process` — with no version assertion, so it already matches the repo's test
conventions. It is also the *only* device evidence behind this page, which makes its
narrowness the thing to fix. In rough order of value, the additions that would protect what
is claimed above: `disk_usage(os.getcwd())` returning a positive `total`, since it is pure
`statvfs` and must work everywhere; the exception-translation asymmetry, asserting that a
system-wide function's failure is *not* a `psutil.Error` subclass; one namedtuple field-name
assertion (`memory_info()._fields`), which is the claim most likely to move on a bump and is
currently unprotected; and `net_if_addrs()` returning at least a loopback entry, which is the
only C-extension path outside `disk_partitions` that a consumer is likely to call. The
system-wide `/proc` readers are deliberately not on that list — asserting them would encode
one emulator's permissions as a requirement, and what they do is the example's job to
report, not CI's to enforce.
