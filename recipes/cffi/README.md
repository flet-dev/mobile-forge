# cffi

[`cffi`](https://cffi.readthedocs.io/) calls C from Python. Most apps that ship it never
import it — it arrives underneath something else in the dependency list and works without
anyone asking about it.

The reason to open this page is that you want to call C yourself. cffi has two ways of
doing that, and only one of them survives the trip to a phone.

## Install

```toml
dependencies = [
    "flet",
    "cffi",
]
```

Anything declared `char *` takes `bytes`. A `str` raises `TypeError: initializer for ctype
'char *' must be a bytes or list or tuple, not str`, so encode at the boundary and turn
what comes back into a Python object with
[`ffi.string()`](https://cffi.readthedocs.io/en/stable/ref.html#ffi-string-ffi-unpack).

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`ffi-probe`](examples/ffi-probe) — binds libc without naming a file, calls into it, and
  prices a Python callback driven from C.

## Usage in a Flet app

Declare, bind, call:

```python
import sys

from cffi import FFI

ffi = FFI()
ffi.cdef("long sysconf(int name);")
libc = ffi.dlopen(None)              # the running process, not a file on disk
android = hasattr(sys, "getandroidapilevel")
cores = libc.sysconf(97 if android else 58)   # bionic's number, else Darwin's
```

That is [ABI mode](https://cffi.readthedocs.io/en/stable/overview.html#abi-versus-api).
[`cdef()`](https://cffi.readthedocs.io/en/stable/cdef.html#ffi-ffibuilder-cdef-declaring-types-and-functions)
parses the declarations at runtime,
[`dlopen()`](https://cffi.readthedocs.io/en/stable/cdef.html#ffi-dlopen-loading-libraries-in-abi-mode)
resolves the symbols, and libffi assembles each call frame from what it was told. Nothing
is compiled at any point, which is what makes it the half of cffi a device can run.

API mode is the other half:
[`ffi.set_source()`](https://cffi.readthedocs.io/en/stable/cdef.html#ffibuilder-set-source-preparing-out-of-line-modules)
and `ffi.compile()` generate a C file, compile it, and produce an extension module — a
build step needing a C compiler and the target's real system headers at the moment it
runs. **Every API-mode binding your app uses therefore has to be compiled into a wheel
before the app is packaged**, so a dependency that builds a cffi extension during
installation needs a [recipe](../../README.rst), not a workaround in your app.

### Threading

A C call releases the GIL for its duration, so work handed to
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) really
overlaps instead of queueing: four Python threads each calling `usleep(200 ms)` finished
in 206 ms on a desktop, where the same four calls in sequence took 831 ms.

That property belongs to the call, not to the library behind it. cffi's own lock covers
`cdef()` and the first lookup of each symbol, never the call, so a C library that is not
thread-safe is not thread-safe here either — put one lock around it, as you would anywhere
else. Callbacks run the other way and take the GIL back, so callback-driven work does not
merely fail to overlap, it gets slower: four of the example's sorts took 2.2 s across four
threads on a desktop against 0.39 s one after another. Keep that shape on one thread. Catch
exceptions inside the worker and end it with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update), which a background
thread does not get for free.

### What you may open at runtime

`ffi.dlopen(None)` is the portable target: it resolves against the running process rather
than a file, and libc is already loaded there on both platforms. The recipe's mobile test
binds `strlen` this way and calls it, on the Android emulator and the iOS simulator.

Naming a file is where the platforms part: the same C library is `libc.so` on Android and
`/usr/lib/libSystem.B.dylib` on iOS. Beyond libc:

- **iOS will not load code that was not signed into the app.** `dlopen` reaches the
  operating system's own libraries and what shipped inside the signed bundle; a dylib
  written to app storage, downloaded, or produced at runtime is not loadable, and shipping
  one that way is against App Store policy too. A design that fetches or generates a
  native plugin does not port.
- **Android restricts an app to a published list of system libraries.** For an app
  targeting API 24 or later the linker refuses a system library that is not on the
  [public NDK list](https://developer.android.com/about/versions/nougat/android-7.0-changes#ndk),
  whether or not the file is on the device.

This recipe tests neither boundary; both are platform rules rather than cffi behaviour.
The route that does work for your own C library is a wheel that carries it, which is what a
mobile-forge recipe produces: packaging puts the binary where each platform's loader looks.

### Cost of a call

Per call the overhead is small; the number of calls is what costs. A plain ABI-mode call
into libc measured 0.07–0.08 µs on a desktop, over a million repetitions of
`libc.strlen(b"hello world")`. Crossings in the other direction cost more: sorting 20,000
integers with libc's `qsort` and a Python comparator took about 95 ms across roughly
295,000 calls back into Python, 0.32 µs each, where `sorted()` took about 1.5 ms.

Design for one crossing per batch: hand C an array, let it do the loop, read the array
back. A Python function called once per element is the shape to recognise and avoid,
whichever direction it is called in.

### App size

The wheel is 179–200 KB compressed per architecture and 538–684 KB unpacked: the compiled
`_cffi_backend`, then cffi's own Python package, roughly half of which is the API-mode code
generator a device will never run. Too small a payload for a
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) rule to be
worth writing.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. Wheel size is not the amount added to the final
APK or IPA; packaging and compression determine that.

### Other considerations

A desktop `flet run` uses PyPI's wheel, and the Python API is identical. What differs is
everything cffi reports *about* the machine, which is exactly what ABI-mode code tends to
depend on: `ffi.sizeof("long")` and `ffi.sizeof("void *")` are 8 on a 64-bit desktop and on
arm64 but 4 on armeabi-v7a; `platform.system()` returns `"iOS"` on iOS rather than
`"Darwin"`, so a `== "Darwin"` gate quietly takes the desktop branch on a phone; and the
`_SC_*` constants you hardcode are bionic's on Android and Darwin's on iOS —
`_SC_PAGESIZE` is 39 on Android and 29 on iOS, as the NDK's `bits/sysconf.h` and the
iPhoneOS SDK's `unistd.h` define them. Check anything that depends on those on a device.

Do not pick between those constant sets with `platform.system() == "Android"`. CPython only
taught `platform` about Android in 3.13, which is also when
[`android_ver()`](https://docs.python.org/3/library/platform.html#platform.android_ver)
arrived; an earlier build answers `"Linux"`, the same string a desktop gives, and glibc's
`_SC_*` numbers are a third set again.
[`sys.getandroidapilevel()`](https://docs.python.org/3/library/sys.html#sys.getandroidapilevel)
exists only on Android and has since 3.7, so `hasattr(sys, "getandroidapilevel")` is the
gate that answers the same on every Python your app might be built against.

## Things to know

- **A wrong declaration is not an error, it is a wrong answer.** The declaration is the
  only description of the function cffi has; it does not check it against the library.
  Declaring `strtod` as returning `int` makes libffi read the wrong register:
  `libc.strtod(b"3.25e2xyz", ffi.NULL)` returned `1` instead of `325.0` on a desktop, with
  nothing raised — and what that register holds differs per architecture, so one slice can
  look plausible while another does not. A mismatched pointer or struct is the same mistake
  with memory corruption at the end of it.

- **A callback that raises tells C nothing.** cffi prints `Exception ignored from cffi
  callback ...` to stderr, returns 0 — or whatever
  [`ffi.callback(..., error=)`](https://cffi.readthedocs.io/en/stable/using.html#callbacks)
  names — and the C function carries on: a `qsort` whose comparator raised every time
  returned an unsorted array and no exception. On a device that traceback goes to the
  console log, nowhere the app can see, so catch inside the callback or pass `onerror=`.

- **Keep a reference to every `ffi.callback` for as long as C holds the pointer.** The
  libffi closure is freed with the Python object. Calling through a pointer to a freed one
  killed a desktop process with SIGSEGV, no traceback and no exit message; on a phone that
  is the app vanishing.

- **Variadic arguments must be cast explicitly.**
  `libc.snprintf(buf, 64, b"%d", 7)` raises `TypeError: argument 4 passed in the variadic
  part needs to be a cdata object`; pass `ffi.cast("int", 7)`. cffi cannot infer the C type
  of a [variadic argument](https://cffi.readthedocs.io/en/stable/using.html#variadic-function-calls),
  and the promotion rules are not Python's.

- **`cdef()` reads C declarations, not C source.** `#include <unistd.h>` raises
  `CDefError: ... Directives not supported yet`, which is why constants have to be written
  out by hand. A struct left partial with `...` is accepted by `cdef()` and then raises
  `VerificationMissing` the first time anything asks for its layout — the measurement a
  compiler was supposed to make.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name, a version, a build number and one host requirement; the patch
preamble owns its hunks. Two things about the resulting binaries are recorded nowhere else:

**libffi is linked statically.** The Android `_cffi_backend` names only `libm.so`, the
CPython library, `libdl.so` and `libc.so`; the iOS one names only the Python framework and
`libSystem`. The libffi symbols are inside the module, so nothing has to find one at
runtime.

**iOS callbacks depend on which closure allocator libffi compiled.** Both arm64 slices,
device and simulator, contain `ffi_closure_trampoline_table_page` — libffi's
`FFI_EXEC_TRAMPOLINE_TABLE` implementation, the one that exists because iOS will not map a
page writable and executable. If a libffi or configuration change ever selected the
mmap-based allocator instead, `ffi.callback` would stop working on an iOS device while
every other test kept passing. The x86_64 simulator slice is built the other way round: it
carries `ffi_prep_closure_loc_efi64` and no trampoline table, so it is the wrong wheel to
check this on.

### Upgrade hazards

An API-mode extension built by another recipe imports `_cffi_backend` by name at load time
and hands it a version tag, so the two are a matched set. The backend's own message names
the failure: `cffi extension module '...' uses an unknown version tag ...  This module
might need a more recent version of cffi than the one currently installed`. A consumer
whose sources were generated by a newer cffi than the `_cffi_backend` this recipe ships
breaks at import, not at build.

The C parser is not built here. `cffi/cparser.py` imports `pycparser`, trying a vendored
`cffi._pycparser` first that this wheel does not contain, so `cdef()` on a device runs a
pure-Python package resolved from PyPI outside this recipe's pins. A pycparser release can
break it with no recipe change; a future cffi that vendors its own copy removes it.

The patch edits `setup.py` and `src/c/malloc_closure.h`, both of which upstream moves;
re-read its preamble before refreshing either hunk.

### Re-verification checklist

- **ABI mode on both platforms:** the existing device test — `cdef`, `dlopen(None)`, one
  call — is the only thing proving the wheel works at all, so it has to stay green.
- **Callbacks on an iOS device**, not only the simulator: check that
  `ffi_closure_trampoline_table_page` is still in the **arm64** binaries *and* that an
  `ffi.callback` actually runs. The trampoline-table path is the reason it can work at all.
- **Static libffi:** confirm no libffi appears in the Android `DT_NEEDED` list or the iOS
  load commands, and that no libffi binary ships in the wheel.
- **Android 16 KB alignment:** every `PT_LOAD` segment is currently aligned to 0x4000.
- **Runtime parsing from zipped site-packages:** `pycparser` is imported when `FFI()` is
  constructed, not lazily at `cdef()`, so it has to be importable from Android's
  `sitepackages.zip` or the first `FFI()` raises `ModuleNotFoundError`.
- **The constants quoted above:** re-read `_SC_PAGESIZE` and `_SC_NPROCESSORS_ONLN` from the
  NDK sysroot and the iPhoneOS SDK if this page still quotes them.
- **Size:** re-measure the compressed and unpacked ranges from the wheels themselves.

### Coverage gaps

`tests/test_cffi.py` is one function: `cdef` a single declaration, `dlopen(None)`, one call.
No callback, no variadic call, no struct or array, no threading, no named library — every
claim here about callbacks, threading and timing is a desktop measurement or an inspection
of the shipped binaries, not a device result.
