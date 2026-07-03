#!/bin/bash
set -eu

case "$CROSS_VENV_SDK" in

android)
    # ANDROID: ship the REAL LLVM OpenMP runtime. libomp.so lives in clang's
    # per-target runtime dir, keyed by the LLVM arch name (not the Android ABI):
    # arm64-v8a->aarch64, armeabi-v7a->arm, x86_64->x86_64, x86->i386. This is the
    # same libomp.so the toolchain links with -fopenmp.
    case "$HOST_ARCH" in
        arm64-v8a)   omp_arch=aarch64 ;;
        armeabi-v7a) omp_arch=arm ;;
        x86_64)      omp_arch=x86_64 ;;
        x86)         omp_arch=i386 ;;
        *) echo "flet-libomp: unsupported arch '$HOST_ARCH'"; exit 1 ;;
    esac

    toolchain=$(echo "$NDK_ROOT"/toolchains/llvm/prebuilt/*)
    libomp=$(echo "$toolchain"/lib/clang/*/lib/linux/"$omp_arch"/libomp.so)

    if [ ! -f "$libomp" ]; then
        echo "flet-libomp: libomp.so not found at $libomp"
        exit 1
    fi

    mkdir -p "$PREFIX/lib"
    cp "$libomp" "$PREFIX/lib/libomp.so"
    ;;

iphoneos|iphonesimulator)
    # iOS: Apple clang ships no OpenMP runtime. Build a SERIAL STUB libomp.a — the
    # omp_* runtime API implemented as single-threaded no-ops — so C++ libraries
    # that make direct omp_*() calls (e.g. faiss) resolve those symbols at link and
    # run serially. The parallel `#pragma omp` regions are expected to be compiled
    # WITHOUT -fopenmp by the consumer, so clang ignores them (serial) and never
    # emits __kmpc_* runtime calls — only the omp_* API in this stub is referenced.
    #
    # We ship our own omp.h so the consumer compiles against the SAME omp_lock_t
    # layout the stub defines ({ void* }, matching the LLVM ABI) — otherwise
    # sizeof(omp_lock_t) could mismatch and corrupt callers that malloc arrays of
    # locks (faiss HNSW LockVector does exactly this).
    mkdir -p "$PREFIX/include" "$PREFIX/lib"

    cat > "$PREFIX/include/omp.h" <<'OMPH'
#ifndef __FLET_OMP_STUB_H
#define __FLET_OMP_STUB_H
/* Serial single-threaded stub of the OpenMP runtime API (subset). */
#ifdef __cplusplus
extern "C" {
#endif

typedef struct { void *_lk; } omp_lock_t;
typedef struct { void *_lk; int _c; } omp_nest_lock_t;
typedef enum omp_sched_t { omp_sched_static = 1, omp_sched_dynamic = 2,
                           omp_sched_guided = 3, omp_sched_auto = 4 } omp_sched_t;

extern int    omp_get_max_threads(void);
extern int    omp_get_num_threads(void);
extern int    omp_get_thread_num(void);
extern int    omp_get_num_procs(void);
extern int    omp_in_parallel(void);
extern void   omp_set_num_threads(int);
extern void   omp_set_nested(int);
extern int    omp_get_nested(void);
extern void   omp_set_dynamic(int);
extern int    omp_get_dynamic(void);
extern double omp_get_wtime(void);

extern void   omp_init_lock(omp_lock_t *);
extern void   omp_destroy_lock(omp_lock_t *);
extern void   omp_set_lock(omp_lock_t *);
extern void   omp_unset_lock(omp_lock_t *);
extern int    omp_test_lock(omp_lock_t *);

#ifdef __cplusplus
}
#endif
#endif /* __FLET_OMP_STUB_H */
OMPH

    cat > omp_stub.c <<'OMPC'
#include <omp.h>
#include <time.h>

int    omp_get_max_threads(void) { return 1; }
int    omp_get_num_threads(void) { return 1; }
int    omp_get_thread_num(void)  { return 0; }
int    omp_get_num_procs(void)   { return 1; }
int    omp_in_parallel(void)     { return 0; }
void   omp_set_num_threads(int n) { (void)n; }
void   omp_set_nested(int n)      { (void)n; }
int    omp_get_nested(void)       { return 0; }
void   omp_set_dynamic(int n)     { (void)n; }
int    omp_get_dynamic(void)      { return 0; }

double omp_get_wtime(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* Single-threaded: locks are uncontended no-ops; test always succeeds. */
void omp_init_lock(omp_lock_t *l)    { if (l) l->_lk = 0; }
void omp_destroy_lock(omp_lock_t *l) { if (l) l->_lk = 0; }
void omp_set_lock(omp_lock_t *l)     { (void)l; }
void omp_unset_lock(omp_lock_t *l)   { (void)l; }
int  omp_test_lock(omp_lock_t *l)    { (void)l; return 1; }
OMPC

    "$CC" $CFLAGS -O2 -I"$PREFIX/include" -c omp_stub.c -o omp_stub.o
    "$AR" rcs "$PREFIX/lib/libomp.a" omp_stub.o
    ;;

*)
    echo "flet-libomp: unsupported SDK '$CROSS_VENV_SDK'"
    exit 1
    ;;

esac
