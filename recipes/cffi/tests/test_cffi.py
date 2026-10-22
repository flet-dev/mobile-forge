import gc
import sys
import threading
from typing import Any

from cffi import FFI

CDEF = """
    size_t strlen(char *str);
    void qsort(void *base, size_t nmemb, size_t size,
               int (*compar)(const void *, const void *));
    typedef unsigned long pthread_t;
    int pthread_create(pthread_t *thread, void *attr,
                       void *(*start)(void *), void *arg);
    int pthread_join(pthread_t thread, void **retval);
    int snprintf(char *str, size_t size, const char *format, ...);
"""


def _libc() -> tuple[FFI, Any]:
    """ABI-mode handle on the C library: bionic's public libc.so on Android, the
    process's own symbols (libSystem) on iOS."""
    ffi = FFI()
    ffi.cdef(CDEF)
    # Not sys.platform: Android's Python 3.12 still reports "linux".
    android = hasattr(sys, "getandroidapilevel")
    return ffi, ffi.dlopen("libc.so" if android else None)


def test_basic() -> None:
    """ABI-mode call into libc through a dlopen'd handle."""
    ffi, lib = _libc()
    assert lib.strlen(ffi.new("char[]", b"hello world")) == 11


def test_callback_called_from_c() -> None:
    """C calls a Python ffi.callback() (qsort's comparator). On iOS this needs
    libffi's ffi_closure_alloc(): cffi's own allocator asks for W+X pages."""
    ffi, lib = _libc()

    @ffi.callback("int(const void *, const void *)")
    def cmp(a: Any, b: Any) -> int:
        x, y = ffi.cast("int *", a)[0], ffi.cast("int *", b)[0]
        return (x > y) - (x < y)

    arr = ffi.new("int[]", [5, 3, 9, 1, 7, 2])
    lib.qsort(arr, 6, ffi.sizeof("int"), cmp)
    assert list(arr) == [1, 2, 3, 5, 7, 9]


def test_callback_from_native_thread() -> None:
    """A callback entered on a thread Python did not create, as PortAudio and
    libsndfile's virtual I/O do."""
    ffi, lib = _libc()
    seen: list[tuple[int, int]] = []

    @ffi.callback("void *(void *)")
    def start(arg: Any) -> Any:
        seen.append((threading.get_ident(), int(ffi.cast("intptr_t", arg))))
        return ffi.NULL

    tid = ffi.new("pthread_t *")
    assert lib.pthread_create(tid, ffi.NULL, start, ffi.cast("void *", 1234)) == 0
    assert lib.pthread_join(tid[0], ffi.NULL) == 0
    assert len(seen) == 1
    assert seen[0][1] == 1234
    assert seen[0][0] != threading.get_ident()


def test_many_callbacks_freed_and_reallocated() -> None:
    """3000 live closures, freed, then 3000 more. On arm64 iOS a libffi trampoline
    table holds 1024, so this grows past one table, releases them and starts again."""
    ffi, _ = _libc()
    cbs = [
        ffi.callback("int(int)", (lambda k: lambda x: x + k)(k)) for k in range(3000)
    ]
    assert [cbs[k](1) for k in (0, 1023, 1024, 2999)] == [1, 1024, 1025, 3000]
    del cbs
    gc.collect()
    again = [ffi.callback("int(int)", lambda x: -x) for _ in range(3000)]
    assert again[0](5) == -5
    assert again[-1](7) == -7


# Last on purpose: a backend without ffi_prep_cif_var() can crash here, not just fail.
def test_variadic_call() -> None:
    """snprintf with a string, an int and a double in the variadic part. arm64
    Apple passes varargs on the stack, so this is garbage or a crash unless cffi
    prepares the call with ffi_prep_cif_var()."""
    ffi, lib = _libc()
    buf = ffi.new("char[64]")
    n = lib.snprintf(
        buf,
        64,
        b"[%s] [%d] [%.2f]",
        ffi.new("char[]", b"hi"),
        ffi.cast("int", 42),
        ffi.cast("double", 3.5),
    )
    assert ffi.string(buf) == b"[hi] [42] [3.50]"
    assert n == 16
