"""Exercise greenlet's per-architecture assembly switch on the device that runs it.

Four panels: what a switch costs against a generator and a thread; how that cost
grows with the depth of the parked greenlet; a conformance run covering the paths
that machine code can get wrong; and the two greenlets that prove the GIL is still
there. Everything runs inside `page.run_thread`, so a green result is also a
statement that greenlets work on a Flet worker thread and not only on the main one.
"""

import contextvars
import platform
import queue
import sys
import threading
import time

import flet as ft

try:
    import greenlet
except Exception as error:  # the wheel may be missing or fail to load
    greenlet = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

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

ROW_WEIGHTS = (5, 4, 4)


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
        def descend(remaining):
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
        while True:
            yield 1

    stream = source()

    def run(units):
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
        while True:
            if out.get() is None:
                return
            back.put(1)

    partner = threading.Thread(target=responder, daemon=True)
    partner.start()
    try:

        def run(units):
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
        for _ in range(units):
            greenlet.greenlet(lambda: None).switch()

    return bench(run, min(count, 20_000))


def costs(trips):
    """Table rows comparing the three ways one Python task hands off to another."""
    rows = []
    if greenlet is not None:
        pair = switch_ns(trips)
        rows.append(("greenlet switch pair", pair, 1e9 / pair))
        made = create_ns(trips)
        rows.append(("greenlet create + run", made, 1e9 / made))
    else:
        rows.append(("greenlet switch pair", None, None))
        rows.append(("greenlet create + run", None, None))
    gen = generator_ns(trips)
    rows.append(("generator next()", gen, 1e9 / gen))
    handoff = thread_ns(trips)
    rows.append(("thread round trip", handoff, 1e9 / handoff))
    return rows


def depth_rows(trips):
    """Switch cost and saved-stack bytes at each depth in `DEPTHS`.

    The interesting result is that the two columns disagree: the bytes copied stay
    flat while the time keeps climbing, because a switch also walks the parked
    greenlet's frame chain.
    """
    if greenlet is None:
        return []
    budget = max(2000, trips // 10)
    return [(depth, stack_saved(depth), switch_ns(budget, depth)) for depth in DEPTHS]


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
        def descend(remaining):
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
        total = 0
        for step in range(BURN_STEPS):
            total += step * step
        return total

    home = greenlet.getcurrent()

    def half():
        burn()
        home.switch()

    def serial():
        burn()
        burn()

    def cooperative():
        for _ in range(2):
            greenlet.greenlet(half).switch()

    burn()  # warm the specialising interpreter, or whichever runs first looks slow
    rounds = [(elapsed(serial), elapsed(cooperative)) for _ in range(GIL_ROUNDS)]
    return min(one for one, _ in rounds), min(two for _, two in rounds)


def table_row(values, weight=None):
    """One row of a numeric table: a `Text` per cell, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=width)
            for value, width in zip(values, weight or ROW_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Measure and validate greenlet's switch on this device, on a worker thread.

    Without the wheel the app still runs: the header turns red and names what the
    import raised, the generator and thread rows are still measured so the device's
    baseline is visible, and every greenlet cell reads a dash.
    """
    shown = next(iter(BUDGETS))

    def start():
        """Send one measurement to the thread pool and lock the picker while it runs.

        The guard is set in this synchronous handler rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker would not
        have reached the client before a second tap could start an overlapping run.
        A tap that beats it is dropped and the picker is put back to the size being
        measured, because the client moves its own highlight the instant it is
        tapped.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, BUDGETS[shown])

    def run(trips):
        """Measure, sweep the depth, run the conformance checks, then price the GIL.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises — without this a failure would look like a screen that quietly
        stopped updating. The panels are cleared on the error path so numbers from
        the previous run cannot be read as describing the error.
        """
        try:
            where.color = None  # an earlier failure may have left it red
            where.value = f"measured on thread {threading.current_thread().name!r}" + (
                ""
                if greenlet is None
                else f" - running its own main greenlet: "
                f"{greenlet.getcurrent().parent is None}"
            )
            speeds.controls = [
                table_row(("handoff", "ns each", "per second")),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            label,
                            "-" if ns is None else f"{ns:,.0f}",
                            "-" if rate is None else f"{rate:,.0f}",
                        )
                    )
                    for label, ns, rate in costs(trips)
                ),
            ]

            rows = depth_rows(trips)
            depths.controls = (
                [ft.Text("greenlet absent - no depth sweep", size=11)]
                if not rows
                else [
                    table_row(("frames parked", "stack saved", "ns / pair")),
                    ft.Divider(height=1),
                    *(
                        table_row((f"{depth:,}", f"{saved:,} B", f"{ns:,.0f}"))
                        for depth, saved, ns in rows
                    ),
                ]
            )

            results = conformance()
            passed = sum(1 for _, ok, _ in results if ok)
            checks.controls = (
                [ft.Text("greenlet absent - nothing to check", size=11)]
                if not results
                else [
                    ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE if ok else ft.Icons.CANCEL,
                                size=14,
                                color=ft.Colors.GREEN if ok else ft.Colors.ERROR,
                            ),
                            ft.Text(f"{label} - {detail}", size=11, expand=True),
                        ],
                        spacing=6,
                    )
                    for label, ok, detail in results
                ]
            )
            score.value = "" if not results else f"{passed}/{len(results)} checks pass"
            score.color = (
                ft.Colors.ERROR
                if results and passed != len(results)
                else ft.Colors.GREEN
            )

            timings = gil_ratio()
            if timings is None:
                gil.value = "greenlet absent - the GIL comparison needs it"
            else:
                serial, cooperative = timings
                gil.value = (
                    f"{BURN_STEPS:,} multiplies twice: {serial:,.0f} ms serial "
                    f"against {cooperative:,.0f} ms split over two greenlets "
                    f"({cooperative / serial:.2f}x)"
                )
        except Exception as error:  # the worker must never let one escape
            speeds.controls = []
            depths.controls = []
            checks.controls = []
            score.value = gil.value = ""
            where.value = f"{type(error).__name__}: {error}"
            where.color = ft.Colors.ERROR

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    library = (
        f"greenlet absent - {IMPORT_ERROR}"
        if greenlet is None
        else f"greenlet {greenlet.__version__} - {platform.machine()}"
    )
    page.appbar = ft.AppBar(title=ft.Text("greenlet switch report"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library,
                        size=11,
                        color=ft.Colors.ERROR if greenlet is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=label, label=ft.Text(label))
                                    for label in BUDGETS
                                ],
                                selected=[next(iter(BUDGETS))],  # a set dies in msgpack
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    where := ft.Text(size=11),
                    speeds := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("cost against the depth of the parked greenlet", size=11),
                    depths := ft.Column(spacing=4),
                    ft.Divider(),
                    ft.Text("what the assembly has to get right", size=11),
                    checks := ft.Column(spacing=2),
                    score := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("greenlets are not a second core", size=11),
                    gil := ft.Text(size=11),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
