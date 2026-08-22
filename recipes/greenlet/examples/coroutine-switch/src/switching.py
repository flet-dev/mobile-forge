"""Everything the app measures about greenlet, as plain values `main.py` can render.

The constants, the guarded import and the switching itself live here; nothing in
this module knows what a control is.
"""

import contextvars
import platform
import queue
import sys
import threading
import time

try:
    import greenlet
except Exception as error:  # the wheel may be missing or fail to load
    greenlet = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

VERSION = (
    f"greenlet absent - {IMPORT_ERROR}"
    if greenlet is None
    else f"greenlet {greenlet.__version__} - {platform.machine()}"
)

RUNTIME = f"Python {platform.python_version()}"

# Round trips per measurement. A phone under thermal load needs the larger counts
# before the numbers settle; the smallest is there so the first tap is quick.
BUDGETS = {"20k": 20_000, "100k": 100_000, "500k": 500_000}

# Frames the greenlet is parked under. Since 3.11 a Python-to-Python call does not
# recurse in C, so these cost heap frames rather than machine stack.
DEPTHS = (0, 100, 1000)

# The deepest panel parks 1,000 frames and the default limit is 1,000. Raising it is
# safe here because since 3.11 those frames live on the heap, not the machine stack.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 4000))

CONFORMANCE_DEPTH = 1000

CONFORMANCE_SWITCHES = 50_000

BURN_STEPS = 400_000

# The GIL panel needs more rounds than the timing panels: each round is a handful of
# milliseconds, so a single scheduling hiccup moves the ratio by more than the effect.
GIL_ROUNDS = 5

THREAD_TRIPS = 20_000

REPEATS = 3


def thread_note():
    """Name the thread the measurements ran on, and what greenlet made of it.

    Every thread gets its own main greenlet, so a `parent is None` reported from a
    worker is the on-screen proof that greenlets are not confined to the
    interpreter's main thread.
    """
    note = f"measured on thread {threading.current_thread().name!r}"
    if greenlet is None:
        return note
    own = greenlet.getcurrent().parent is None
    return f"{note} - running its own main greenlet: {own}"


def bench(work, units):
    """Nanoseconds per unit for `work(units)`, best of `REPEATS` runs.

    Best-of rather than mean: a phone schedules across cores of different speeds
    and throttles under load, so the fastest run is the one that says what a switch
    costs and the slow ones say what else the device was doing.
    """
    best = float("inf")
    for _ in range(REPEATS):
        started = time.perf_counter_ns()
        work(units)
        best = min(best, (time.perf_counter_ns() - started) / units)
    return best


def parked(depth):
    """A greenlet suspended `depth` Python frames deep, ready to ping-pong.

    It bounces back to whichever greenlet is current when this is called, so it
    must be built on the same thread that will drive it — greenlets belong to the
    thread that created them and switching across threads is refused.
    """
    home = greenlet.getcurrent()

    def worker():
        """Reach the target depth, then hand control back on every switch."""

        def descend(remaining):
            """Spend one Python frame per level on the way down."""
            if remaining:
                return descend(remaining - 1)
            while True:
                home.switch()

        descend(depth)

    switcher = greenlet.greenlet(worker)
    switcher.switch()
    return switcher


def switch_ns(trips, depth=0):
    """Nanoseconds for one out-and-back switch pair through a parked greenlet.

    The greenlet is killed in a `finally`, not left to the collector: a parked
    greenlet holds its saved machine stack until something raises `GreenletExit`
    inside it, and `throw()` is the one call that does so on purpose.
    """
    switcher = parked(depth)
    try:

        def run(units):
            """One out-and-back switch per unit, which is what `bench` times."""
            for _ in range(units):
                switcher.switch()

        return bench(run, trips)
    finally:
        switcher.throw()


def stack_saved(depth):
    """Bytes of machine stack greenlet copied out to park a greenlet `depth` deep.

    `_stack_saved` is private but it is the only window onto the memcpy the switch
    performs, and it is what separates the two costs the depth panel shows.
    """
    switcher = parked(depth)
    try:
        return getattr(switcher, "_stack_saved", -1)
    finally:
        switcher.throw()


def generator_ns(trips):
    """Nanoseconds for one `next()` on a generator — the same round trip, in C."""

    def source():
        """An endless generator; only the cost of resuming it is of interest."""
        while True:
            yield 1

    stream = source()

    def run(units):
        """One `next()` per unit — the same handoff, done by the interpreter."""
        for _ in range(units):
            next(stream)

    return bench(run, trips)


def thread_ns(trips):
    """Nanoseconds for one round trip between two OS threads through two queues.

    Capped well below the switch counts: at microseconds per trip a phone would
    spend minutes here, and the point of the row is the order of magnitude.
    """
    out, back = queue.SimpleQueue(), queue.SimpleQueue()

    def responder():
        """Echo a token per request until the sentinel says to stop."""
        while True:
            if out.get() is None:
                return
            back.put(1)

    partner = threading.Thread(target=responder, daemon=True)
    partner.start()
    try:

        def run(units):
            """One queue round trip per unit: two context switches by the OS."""
            for _ in range(units):
                out.put(1)
                back.get()

        return bench(run, min(trips, THREAD_TRIPS))
    finally:
        out.put(None)
        partner.join()


def create_ns(count):
    """Nanoseconds to construct a greenlet, run it to completion and drop it."""

    def run(units):
        """Build, run to completion and drop one greenlet per unit."""
        for _ in range(units):
            greenlet.greenlet(lambda: None).switch()

    return bench(run, min(count, 20_000))


def costs(trips):
    """Table rows comparing the three ways one Python task hands off to another.

    A row is `(handoff, ns each, per second)`, printable as it stands. The greenlet
    rows read as a dash where the wheel is missing, and the generator and thread
    rows are measured either way so the device's own baseline is still on screen.
    """
    measured = []
    if greenlet is None:
        measured += [("greenlet switch pair", None), ("greenlet create + run", None)]
    else:
        measured += [
            ("greenlet switch pair", switch_ns(trips)),
            ("greenlet create + run", create_ns(trips)),
        ]
    measured.append(("generator next()", generator_ns(trips)))
    measured.append(("thread round trip", thread_ns(trips)))
    return [
        (label, "-", "-") if ns is None else (label, f"{ns:,.0f}", f"{1e9 / ns:,.0f}")
        for label, ns in measured
    ]


def depth_rows(trips):
    """Switch cost and saved-stack bytes at each depth in `DEPTHS`.

    The interesting result is that the two columns disagree: the bytes copied stay
    flat while the time keeps climbing, because a switch also walks the parked
    greenlet's frame chain. Empty without greenlet, which is the panel's cue to say
    the sweep was skipped.
    """
    if greenlet is None:
        return []
    budget = max(2000, trips // 10)
    return [
        (f"{depth:,}", f"{stack_saved(depth):,} B", f"{switch_ns(budget, depth):,.0f}")
        for depth in DEPTHS
    ]


def conformance():
    """Run the paths that hand-written assembly and lifecycle code can get wrong.

    Returns `(label, ok, detail)` per check. These are the things a wheel can fail
    at while still importing: a switch that loses registers shows up as a wrong
    accumulated value, a broken stack copy as a crash under recursion, and a
    mishandled exception state as a traceback that never arrives.
    """
    if greenlet is None:
        return []
    home = greenlet.getcurrent()
    checks = []

    total = 0

    def counter():
        """Add to the accumulator and park, so a lost register shows as a bad sum."""
        nonlocal total
        for step in range(CONFORMANCE_SWITCHES):
            total += step
            home.switch()

    runner = greenlet.greenlet(counter)
    for _ in range(CONFORMANCE_SWITCHES):
        runner.switch()
    runner.throw()  # it is still parked in the loop; do not leave it to the collector
    expected = CONFORMANCE_SWITCHES * (CONFORMANCE_SWITCHES - 1) // 2
    checks.append(
        (
            f"{CONFORMANCE_SWITCHES:,} switches keep the accumulator exact",
            total == expected,
            f"{total:,} of {expected:,}",
        )
    )

    def deep():
        """Park at the bottom of a deep stack, then unwind it after the switch."""

        def descend(remaining):
            """Park at the bottom, and count the frames back on the way up."""
            if remaining:
                return descend(remaining - 1) + 1
            home.switch()
            return 0

        home.switch(descend(CONFORMANCE_DEPTH))

    diver = greenlet.greenlet(deep)
    diver.switch()
    unwound = diver.switch()
    checks.append(
        (
            f"unwinds {CONFORMANCE_DEPTH:,} frames after a switch",
            unwound == CONFORMANCE_DEPTH,
            f"{unwound} frames returned",
        )
    )

    def thrower():
        """Raise inside a greenlet, giving the switch an exception to carry out."""
        raise ValueError("raised inside the greenlet")

    caught = None
    frames = 0
    try:
        greenlet.greenlet(thrower).switch()
    except ValueError as error:
        caught = str(error)
        trace = error.__traceback__
        while trace:
            frames += 1
            trace = trace.tb_next
    checks.append(
        (
            "an exception crosses the switch with its traceback",
            caught == "raised inside the greenlet" and frames >= 2,
            f"{caught} over {frames} traceback frames",
        )
    )

    inside = []

    def waiter():
        """Park, then report which exception `throw()` delivered into the frame."""
        try:
            home.switch()
        except KeyError as error:
            inside.append(repr(error))
            return "handled"
        return "never reached"

    parked_waiter = greenlet.greenlet(waiter)
    parked_waiter.switch()
    thrown = parked_waiter.throw(KeyError("delivered"))
    checks.append(
        (
            "throw() lands inside a parked greenlet",
            thrown == "handled" and inside == ["KeyError('delivered')"],
            f"returned {thrown!r}",
        )
    )

    dropped = []

    def abandoned():
        """Park, then name whatever arrives when the last reference is dropped."""
        try:
            home.switch()
        except BaseException as error:  # noqa: BLE001 - the point is which one
            dropped.append(type(error).__name__)
            raise

    forgotten = greenlet.greenlet(abandoned)
    forgotten.switch()
    del forgotten
    checks.append(
        (
            "dropping a parked greenlet raises GreenletExit in it",
            dropped == ["GreenletExit"],
            f"received {dropped or 'nothing'}",
        )
    )

    other = {}

    def elsewhere():
        """Create a greenlet on another thread, which this one may not switch to."""
        other["gl"] = greenlet.greenlet(lambda: None)

    stranger = threading.Thread(target=elsewhere)
    stranger.start()
    stranger.join()
    refused = ""
    try:
        other["gl"].switch()
    except greenlet.error as error:
        refused = str(error)
    checks.append(
        (
            "switching to another thread's greenlet is refused",
            bool(refused),
            refused or "the switch was allowed",
        )
    )

    marker = contextvars.ContextVar("marker", default="home")

    def rebinder():
        """Set a ContextVar inside the greenlet and hand back what it reads."""
        marker.set("greenlet")
        home.switch(marker.get())

    seen = greenlet.greenlet(rebinder).switch()
    checks.append(
        (
            "each greenlet carries its own contextvars context",
            seen == "greenlet" and marker.get() == "home",
            f"inside {seen!r}, outside {marker.get()!r}",
        )
    )

    finished = greenlet.greenlet(lambda: "done")
    finished.switch()
    returned = finished.switch("ignored")
    checks.append(
        (
            "switching to a dead greenlet returns instead of raising",
            finished.dead and returned == "ignored",
            f"returned {returned!r}",
        )
    )

    return checks


def elapsed(work):
    """Milliseconds for one call of `work`."""
    started = time.perf_counter()
    work()
    return (time.perf_counter() - started) * 1000.0


def gil_ratio():
    """Wall time for the same arithmetic split across two greenlets, over serial.

    A ratio of about 1 is the correct answer and the useful one: greenlets are one
    OS thread taking turns, so they buy interleaving and never a second core.
    """
    if greenlet is None:
        return None

    def burn():
        """CPU-bound arithmetic with no allocation and no I/O to hide behind."""
        total = 0
        for step in range(BURN_STEPS):
            total += step * step
        return total

    home = greenlet.getcurrent()

    def half():
        """One share of the work, then back to whoever switched here."""
        burn()
        home.switch()

    def serial():
        """Both shares back to back, on one greenlet."""
        burn()
        burn()

    def cooperative():
        """The same two shares, each on a greenlet of its own."""
        for _ in range(2):
            greenlet.greenlet(half).switch()

    burn()  # warm the specialising interpreter, or whichever runs first looks slow
    rounds = [(elapsed(serial), elapsed(cooperative)) for _ in range(GIL_ROUNDS)]
    return min(one for one, _ in rounds), min(two for _, two in rounds)


def gil_note():
    """The GIL panel's sentence: two greenlets against the same work done twice."""
    timings = gil_ratio()
    if timings is None:
        return "greenlet absent - the GIL comparison needs it"
    serial, cooperative = timings
    return (
        f"{BURN_STEPS:,} multiplies twice: {serial:,.0f} ms serial against "
        f"{cooperative:,.0f} ms split over two greenlets "
        f"({cooperative / serial:.2f}x)"
    )
