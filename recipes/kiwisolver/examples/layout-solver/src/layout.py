import time
from typing import NamedTuple

import kiwisolver as kiwi

COLUMNS = ("sidebar", "content", "aside")
MARGIN = 12.0
GUTTER = 10.0
MIN_WIDTH = 32.0
PINNED = 48.0
FLOOR = 72.0
BENCH_COLUMNS = 100

VERSION = f"kiwisolver {kiwi.__version__} · kiwi {kiwi.__kiwi_version__}"

# One solver unit is one Flet logical pixel here, so a solved number goes straight
# onto a Stack child's `left` and `width`. Variables are unhashable -- `==` builds a
# Constraint instead of comparing -- so they live in dicts keyed by name.
CANVAS = kiwi.Variable("canvas")
LEFT = {name: kiwi.Variable(f"{name}.left") for name in COLUMNS}
WIDTH = {name: kiwi.Variable(f"{name}.width") for name in COLUMNS}

SOLVER = kiwi.Solver()

# Weak, so every rule below outranks them. Kept in a list because a Constraint can
# only be removed, or asked whether it is violated, through the exact object added.
EQUAL_WIDTHS = [
    (WIDTH[before] == WIDTH[after]) | kiwi.strength.weak
    for before, after in zip(COLUMNS, COLUMNS[1:])
]

RULES = {
    "pin": (
        f"Sidebar is exactly {PINNED:.0f} (required)",
        [WIDTH["sidebar"] == PINNED],
    ),
    "double": (
        "Content is twice the aside (strong)",
        [(WIDTH["content"] == 2 * WIDTH["aside"]) | kiwi.strength.strong],
    ),
    "floor": (
        f"No column under {FLOOR:.0f} (required)",
        [WIDTH[name] >= FLOOR for name in COLUMNS],
    ),
}


class Solution(NamedTuple):
    """One solved layout: what was asked for, what came out, what it cost."""

    asked: float
    width: float
    boxes: tuple
    yielded: int
    micros: float


def assemble():
    """Fill an empty solver with every constraint the current state calls for.

    Nothing here states a position or a size: the layout is written as
    relationships and the numbers fall out. The first column sits on the margin,
    each one starts a gutter after the one before it, the last closes against the
    frame, and none may collapse below MIN_WIDTH. Three columns under those
    required constraints leave two degrees of freedom, which is the room the weak
    equal-width preferences and the optional rules compete for.

    Called once at import, and again after reset() when a refusal has spoiled the
    tableau.
    """
    SOLVER.addConstraint(LEFT[COLUMNS[0]] == MARGIN)
    for before, after in zip(COLUMNS, COLUMNS[1:]):
        SOLVER.addConstraint(LEFT[after] == LEFT[before] + WIDTH[before] + GUTTER)
    SOLVER.addConstraint(LEFT[COLUMNS[-1]] + WIDTH[COLUMNS[-1]] + MARGIN == CANVAS)
    for name in COLUMNS:
        SOLVER.addConstraint(WIDTH[name] >= MIN_WIDTH)
    for constraint in EQUAL_WIDTHS:
        SOLVER.addConstraint(constraint)
    for rule in _active:
        for constraint in RULES[rule][1]:
            SOLVER.addConstraint(constraint)
    if _preference is not None:
        SOLVER.addConstraint(_preference)


_asked = 0.0
_preference = None
_active = []
_last = None

assemble()


def resize(points):
    """Ask for a new frame width by swapping one strong constraint.

    kiwi's documented way to feed a changing input is an edit variable and
    suggestValue(). This uses a plain strong equality, removed and re-added,
    because an edit variable sharing a row with a constraint the solver later
    refuses can abort the process on the next suggestValue() -- a C++
    InternalSolverError that no `except` can catch. Swapping a constraint costs
    a few microseconds and stays inside Python.

    Strong rather than required, so that a required minimum can overrule it: turn
    the floor rule on and drag down, and the frame stops shrinking while the
    slider keeps going.
    """
    global _asked, _preference
    started = time.perf_counter()
    if _preference is not None:
        SOLVER.removeConstraint(_preference)
    _asked = float(points)
    _preference = (CANVAS == _asked) | kiwi.strength.strong
    SOLVER.addConstraint(_preference)
    return _read(started)


def toggle(rule, wanted):
    """Add or drop one rule on the live solver and re-solve everything.

    Raises kiwisolver.UnsatisfiableConstraint when a required rule contradicts a
    required constraint already in the solver: the conflict is proved from the
    constraints, not discovered by trying values, so it comes back immediately.

    A refusal does not undo itself: the pivots addConstraint had already made
    stand, so the refused rule can be left in force with no exception at all.
    Turn the floor on and then the pin, without the rebuild below, and the solver
    answers with a 48-wide sidebar under its own required minimum of 72. So the
    whole tableau is thrown away and rebuilt from the rules already accepted.
    """
    started = time.perf_counter()
    try:
        for constraint in RULES[rule][1]:
            if wanted:
                SOLVER.addConstraint(constraint)
            else:
                SOLVER.removeConstraint(constraint)
    except kiwi.UnsatisfiableConstraint:
        SOLVER.reset()
        assemble()
        _read(started)
        raise
    if wanted:
        _active.append(rule)
    else:
        _active.remove(rule)
    return _read(started)


def current():
    """The solution the solver holds now, without touching it.

    Needed after a refusal, because toggle() has thrown the tableau away and
    rebuilt it by then. A rebuild does not always land where the incremental
    edits had: at a frame of 160 with the pin and the double rule both on, the
    two answers differ by 12 pixels of content width and both are optimal --
    widening content by 12 buys back exactly the 12 it costs the strong frame
    width, so the weighted error ties and the order the constraints went in
    decides. Redraw from here rather than leaving the old picture up.
    """
    return _last


def _read(started):
    """Copy the tableau back onto the variables and package the result.

    updateVariables() is not the solve -- addConstraint and removeConstraint
    already did that, incrementally -- it only writes current values onto the
    Variable objects, and costs a fraction of a microsecond on a system this
    size (it is linear in the variable count, so a big one costs more).
    """
    global _last
    SOLVER.updateVariables()
    micros = (time.perf_counter() - started) * 1e6
    boxes = tuple((name, LEFT[name].value(), WIDTH[name].value()) for name in COLUMNS)
    yielded = sum(constraint.violated() for constraint in EQUAL_WIDTHS)
    _last = Solution(_asked, CANVAS.value(), boxes, yielded, micros)
    return _last


def benchmark(count=BENCH_COLUMNS):
    """Build a `count`-column system from scratch, then make one edit to it.

    These two numbers are the argument for keeping a solver alive rather than
    rebuilding it. Building the tableau is badly super-linear: on desktop (macOS
    arm64, CPython 3.12) this chain took about 1 ms at 25 columns, 11 ms at 50
    and 125 ms at 100, while swapping the frame width on the finished 100-column
    system re-solved in under 8 ms. The gap widens with size -- at 25 columns the
    edit is a quarter of the build, at 200 a thirtieth. Run it here to see what
    the device does.
    """
    started = time.perf_counter()
    solver = kiwi.Solver()
    lefts = [kiwi.Variable(f"l{index}") for index in range(count)]
    widths = [kiwi.Variable(f"w{index}") for index in range(count)]
    solver.addConstraint(lefts[0] == MARGIN)
    for index in range(count - 1):
        solver.addConstraint(lefts[index + 1] == lefts[index] + widths[index] + GUTTER)
        solver.addConstraint((widths[index] == widths[index + 1]) | kiwi.strength.weak)
    total = count * 40.0 + GUTTER * (count - 1) + 2 * MARGIN
    frame = lefts[-1] + widths[-1] + MARGIN == total
    solver.addConstraint(frame)
    for width in widths:
        solver.addConstraint(width >= MIN_WIDTH)
    solver.updateVariables()
    build_ms = (time.perf_counter() - started) * 1e3

    started = time.perf_counter()
    solver.removeConstraint(frame)
    solver.addConstraint(lefts[-1] + widths[-1] + MARGIN == total + 100)
    solver.updateVariables()
    edit_ms = (time.perf_counter() - started) * 1e3
    # Three per column: the chain step, the weak equal-width, the minimum. The edit
    # swaps one constraint for another, so the system stays this size throughout.
    return 3 * count, build_ms, edit_ms
