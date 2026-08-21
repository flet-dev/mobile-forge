# cffi FFI probe

Five C library functions, declared in Python and called on the device: the page size the
kernel reports, how many cores are online, a string formatted by C's `snprintf`. Then a
list of integers sorted by libc's `qsort` while Python decides every comparison, so the
app can price what one crossing of the FFI boundary costs. Nothing here was compiled when
the app was built.

What it demonstrates:

- **ABI mode, the only mode a phone can run.**
  [`ffi.cdef()`](https://cffi.readthedocs.io/en/stable/cdef.html#ffi-ffibuilder-cdef-declaring-types-and-functions)
  parses the declarations at runtime and
  [`ffi.dlopen()`](https://cffi.readthedocs.io/en/stable/cdef.html#ffi-dlopen-loading-libraries-in-abi-mode)
  binds the symbols; libffi lays out each call frame from what it was told. Its
  counterpart, [API mode](https://cffi.readthedocs.io/en/stable/overview.html#abi-versus-api),
  generates C and compiles it — which a device cannot do. The last panel runs the two
  API-mode-only features and prints the exceptions they raise.
- **`dlopen(None)` instead of a library name.** It resolves against the running process,
  where libc is already loaded, so the same line works on both platforms. A filename would
  have had to be `libc.so` on Android and `libSystem.B.dylib` on iOS.
- **The constants are yours to write down.** `cdef()` reads C declarations, not C source,
  so it cannot `#include <unistd.h>` and `_SC_PAGESIZE` has to be a literal — 39 for
  bionic, 29 for Darwin. `sysconf()` returns -1 for a name it does not know, so the wrong
  number reads as a failure rather than as a bug.
- **`sizeof` is answered by the slice, not by the source.** The table comes from the
  compiled backend, so `long` and `void *` are 8 bytes on arm64 and 4 on armeabi-v7a from
  the same declarations.
- **A Python function passed to C as a function pointer.**
  [`ffi.callback()`](https://cffi.readthedocs.io/en/stable/using.html#callbacks) builds a
  libffi closure that `qsort` calls once per comparison, and the app counts them. Keeping a
  reference to it for as long as C holds the pointer is a hard requirement.
- **Compute off the UI thread** — the sort runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the button disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a
  background thread needs.

The sort is the row worth staring at. It is one call into C, and it is also a few hundred
thousand returns into Python: on a desktop, 20,000 integers took about 95 ms and roughly
295,000 crossings — 0.32 µs each — against 1.5 ms for `sorted()` on the same list. Every
crossing is cheap and there are far too many of them, which is the shape to recognise and
keep on the C side of the boundary. The device number is what this app is for.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
