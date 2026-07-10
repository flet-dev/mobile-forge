def test_import_greenlet():
    """Forces the native `_greenlet.cpython-*.so` to load. On Android this is
    the libc++_shared.so canary — `_greenlet.so` has
    DT_NEEDED=[libc++_shared.so] (greenlet's C++ inline-asm context switcher
    is built with libstdc++). If `flet-libcpp-shared` isn't in the wheel's
    Requires-Dist, libc++_shared.so won't be in jniLibs/<abi>/ and import
    fails with `dlopen failed: library "libc++_shared.so" not found`."""
    import greenlet

    assert hasattr(greenlet, "greenlet")
    assert hasattr(greenlet, "getcurrent")


def test_switch():
    """greenlet implements stackful coroutines via inline-asm context
    switching — the recipe is all about porting that asm to mobile arches.
    Two greenlets pass control back and forth via switch()."""
    import greenlet

    log = []

    def worker():
        log.append("worker:start")
        # Yield back to parent, then resume.
        x = main_gl.switch("hello")
        log.append(("worker:got", x))
        return "worker:done"

    main_gl = greenlet.getcurrent()
    worker_gl = greenlet.greenlet(worker)

    msg = worker_gl.switch()
    log.append(("main:got", msg))
    result = worker_gl.switch("world")
    log.append(("main:final", result))

    assert log == [
        "worker:start",
        ("main:got", "hello"),
        ("worker:got", "world"),
        ("main:final", "worker:done"),
    ]


def test_dead_greenlet():
    """A returned greenlet reports dead — sanity for the lifecycle path."""
    import greenlet

    gl = greenlet.greenlet(lambda: 42)
    assert not gl.dead
    assert gl.switch() == 42
    assert gl.dead
