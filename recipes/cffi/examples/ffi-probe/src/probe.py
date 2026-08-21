import platform
import random
import sys
import time

import cffi

# ABI mode, in full: declare the C you want, bind the symbols the process
# already has, call them. Nothing is compiled -- cffi parses these declarations
# at runtime and libffi lays out each call frame from them, which is the only
# route into C on a device with no compiler on it.
ffi = cffi.FFI()
ffi.cdef(
    """
    size_t strlen(const char *s);
    int snprintf(char *str, size_t size, const char *format, ...);
    double strtod(const char *nptr, char **endptr);
    long sysconf(int name);
    void qsort(void *base, size_t nmemb, size_t size,
               int (*compar)(const void *, const void *));
    """
)

# dlopen(None) resolves against the running process rather than a file, and libc
# is already loaded into it on both platforms. A filename would have had to be
# "libc.so" on Android and "libSystem.B.dylib" on iOS.
libc = ffi.dlopen(None)

VERSION = f"cffi {cffi.__version__} · {platform.system()} {platform.machine()}"

# sysconf() takes a number, and cdef() is not a C preprocessor: it cannot read
# <unistd.h>, so the constants have to be written out per libc. bionic's
# bits/sysconf.h gives _SC_PAGESIZE 0x27 and _SC_NPROCESSORS_ONLN 0x61; the
# iPhoneOS SDK's unistd.h gives 29 and 58 for the same two. glibc's are a third
# set, which is why "Linux" is absent rather than aliased to Android.
SYSCONF = {
    "Android": (39, 97),
    "iOS": (29, 58),
    "Darwin": (29, 58),
}

# Types whose width is decided by the slice rather than by C. armeabi-v7a is the
# one that answers differently.
WIDTHS = ("int", "long", "long long", "size_t", "void *")


def system_name():
    """Name this platform for the SYSCONF lookup, without trusting one string.

    `platform.system()` answers "Android" only from Python 3.13; the 3.12
    runtime says "Linux", which is also what a desktop says and carries glibc's
    constants rather than bionic's. `sys.getandroidapilevel` is defined on every
    Android build of CPython at every version, so it is the gate that does not
    move. iOS needs no such care -- it has said "iOS" since PEP 730 -- but it is
    still not "Darwin", so a `== "Darwin"` test lands on no entry at all.
    """
    if hasattr(sys, "getandroidapilevel"):
        return "Android"
    return platform.system()


def sysconf_pair():
    """Ask libc for its page size and core count with this platform's numbers.

    Passing the wrong number is worse than passing none: sysconf() returns -1
    for a name it does not recognise instead of raising, so bionic's 39 asked
    of Darwin reads as a failure rather than as a bug.
    """
    numbers = SYSCONF.get(system_name())
    if numbers is None:
        return None
    return libc.sysconf(numbers[0]), libc.sysconf(numbers[1])


def calls():
    """Call five libc functions through libffi and collect what they returned.

    Each row is a value only the C library knows. The interesting ones are the
    last three: snprintf is variadic, and cffi cannot infer the C type of a
    variadic argument, so each one is cast explicitly -- pass a bare Python int
    and the call is a TypeError before it reaches C. strtod returns a double,
    and that return type is taken from the declaration and nowhere else: declare
    it `int` and libffi reads the wrong register, producing a plausible number
    and no error. sysconf takes a constant this file had to hardcode.
    """
    buffer = ffi.new("char[64]")
    libc.snprintf(buffer, 64, b"%.3f x %d", ffi.cast("double", 1.5), ffi.cast("int", 7))
    rows = [
        ('strlen(b"hello world")', libc.strlen(b"hello world")),
        ('snprintf("%.3f x %d", 1.5, 7)', ffi.string(buffer).decode()),
        ('strtod(b"3.25e2xyz")', libc.strtod(b"3.25e2xyz", ffi.NULL)),
    ]
    numbers = sysconf_pair()
    if numbers is None:
        rows.append(("sysconf", f"no constants for {system_name()}"))
    else:
        rows.append(("sysconf(_SC_PAGESIZE)", f"{numbers[0]} bytes"))
        rows.append(("sysconf(_SC_NPROCESSORS_ONLN)", numbers[1]))
    return rows


def widths():
    """Report sizeof for each type in WIDTHS, as the loaded backend sees it.

    ffi.sizeof answers from the compiled `_cffi_backend`, so these are the
    running slice's numbers rather than the ones the declarations were written
    against. A `long` field that is 8 bytes on arm64 is 4 on armeabi-v7a, and a
    struct declared once serves both only because cffi lays it out per slice.
    """
    return [(name, ffi.sizeof(name)) for name in WIDTHS]


def compiler_only():
    """Run the two API-mode features that a phone cannot have, and catch them.

    Both fail for the same reason: they need a C compiler and the real system
    headers at the moment they run. `#include` is rejected by cdef() itself,
    which parses C declarations and not C source. A struct left partial with
    `...` is accepted by cdef() and only fails when something asks for its
    layout -- which the compiler was supposed to have measured.
    """
    attempts = []
    try:
        cffi.FFI().cdef("#include <unistd.h>")
    except Exception as exc:
        attempts.append(("#include in cdef()", _reason(exc)))
    try:
        partial = cffi.FFI()
        partial.cdef("struct tm { int tm_sec; ...; };")
        partial.sizeof("struct tm")
    except Exception as exc:
        attempts.append(("struct declared with ...", _reason(exc)))
    return attempts


def _reason(exc):
    """Render an exception as one line: its class and its last message line."""
    return f"{type(exc).__name__}: {str(exc).strip().splitlines()[-1]}"


def sort_in_c(count):
    """Sort `count` random ints with libc's qsort and a Python comparator.

    This is deliberately the expensive shape. qsort is one call into C, but the
    comparator it drives is a Python function reached through a libffi closure,
    so the work is really a few hundred thousand crossings of the boundary.
    Returns milliseconds in C, milliseconds for sorted() on the same list, the
    number of crossings, and whether the two agreed.

    `compare` stays referenced by this frame for as long as qsort runs, and that
    is not incidental: the closure is freed with the Python object, and calling
    through a pointer to a freed one takes the process down with a signal rather
    than an exception.
    """
    data = [random.randrange(1 << 30) for _ in range(count)]
    array = ffi.new("int[]", data)
    crossings = 0

    @ffi.callback("int(const void *, const void *)")
    def compare(left, right):
        """Compare two ints C handed back as void pointers."""
        nonlocal crossings
        crossings += 1
        return ffi.cast("int *", left)[0] - ffi.cast("int *", right)[0]

    started = time.perf_counter()
    libc.qsort(array, count, ffi.sizeof("int"), compare)
    in_c = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    expected = sorted(data)
    in_python = (time.perf_counter() - started) * 1000

    return in_c, in_python, crossings, [array[i] for i in range(count)] == expected
