def test_cpu_count():
    """`cpu_count` is backed by the C extension / sysconf on POSIX and is one
    of the few queries that works inside the mobile sandbox."""
    import psutil

    logical = psutil.cpu_count()
    assert logical is None or (isinstance(logical, int) and logical >= 1)


def test_virtual_memory():
    """`virtual_memory()` reads total/available RAM via the native ext
    (sysconf/sysctl). Total must be a positive byte count."""
    import psutil

    vm = psutil.virtual_memory()
    assert vm.total > 0
    assert 0.0 <= vm.percent <= 100.0


def test_current_process():
    """Construct a Process for our own PID and read a couple of fields that
    don't require elevated permissions in the sandbox."""
    import os

    import psutil

    p = psutil.Process(os.getpid())
    assert p.pid == os.getpid()
    # memory_info().rss is resident set size in bytes -- always > 0 for a
    # live process.
    assert p.memory_info().rss > 0
