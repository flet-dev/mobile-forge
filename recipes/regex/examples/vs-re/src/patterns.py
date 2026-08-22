"""The fifteen comparisons, the three device measurements, and the playground call.

Nothing here touches Flet; `main.py` renders what these return.
"""

import platform
import re
import sys
import threading
import time
import unicodedata
from typing import NamedTuple

try:
    import regex

    IMPORT_ERROR = None
except Exception as error:
    regex = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

GREEK = "Είναι 42 μέρες"
CLUSTERS = "\U0001f469‍\U0001f469‍\U0001f467‍\U0001f466\U0001f1ec\U0001f1edé"

# The subject for the contention scan. Sized by its match count, not its length:
# the cost being measured is one GIL handoff per match, so 200 repeats — one
# address each — is what makes the effect legible.
CORPUS = "Order 4471 shipped 2026-05-09 to alice@example.com for USD 1,299.00. " * 200
EMAIL = r"\w+@\w+\.\w+"

# `re` is exponential in this pattern's input length, so the ladder is walked
# from the cheap end and abandoned before it gets expensive. A phone slower than
# a laptop stops a rung or two earlier instead of freezing the screen.
LADDER = (14, 16, 18, 20, 22, 24, 26)
BUDGET_MS = 1500


def findall(module, pattern, subject):
    """The default probe: `findall` on whichever engine is passed in."""
    return module.findall(pattern, subject)


def overlapping(module, pattern, subject):
    """`findall` asking for overlapping matches — a keyword `re` has no equivalent for."""
    return module.findall(pattern, subject, overlapped=True)


def groups(module, pattern, subject):
    """Every repetition of group 1, not just the last one the group held."""
    match = module.match(pattern, subject)
    return match.captures(1) if match else None


def reset_groups(module, pattern, subject):
    """Group 1 of each match, so a branch reset reads as one group rather than two."""
    return [match.group(1) for match in module.finditer(pattern, subject)]


def whole(module, pattern, subject):
    """The whole of the first match, for cases where the span itself is the answer."""
    match = module.match(pattern, subject)
    return match.group(0) if match else None


def fuzzy(module, pattern, subject):
    """The approximate match and its error breakdown as (substitutions, insertions, deletions)."""
    match = module.search(pattern, subject)
    return (match.group(0), match.fuzzy_counts) if match else None


def folded(module, pattern, subject):
    """Whether the pattern matches under full case folding, where ß folds to ss."""
    return bool(module.fullmatch(pattern, subject))


def named_list(module, pattern, subject):
    """A set of literal alternatives passed as data rather than compiled into the pattern."""
    return module.findall(pattern, subject, words=["cat", "mat"])


# Label, pattern, subject, probe, and the `repr` of what `regex` must return.
# The expected value is checked rather than described, so a row whose engine
# changed under it turns red instead of quietly printing something new. Nothing
# is asserted about the `re` half: what it raises is a message that varies by
# CPython version, so it is displayed as observed and never compared.
CASES = (
    ("property class: any Unicode letter", r"\p{L}+", GREEK, findall, "['Είναι', 'μέρες']"),
    ("script name as a class", r"\p{Greek}+", GREEK, findall, "['Είναι', 'μέρες']"),
    (
        "grapheme clusters, not code points",
        r"\X",
        CLUSTERS,
        findall,
        "['👩\\u200d👩\\u200d👧\\u200d👦', '🇬🇭', 'é']",
    ),
    (
        "fuzzy match within 2 errors",
        r"(?:Ljubljana){e<=2}",
        "flight to Lujbljana",
        fuzzy,
        "('Lujbljana', (2, 0, 0))",
    ),
    ("overlapping matches", r"\d\d", "12345", overlapping, "['12', '23', '34', '45']"),
    (
        "variable-width lookbehind",
        r"(?<=USD ?)\d+",
        "USD 40 and USD50",
        findall,
        "['40', '50']",
    ),
    (
        "set difference, with (?V1)",
        r"(?V1)[\p{L}--[aeiou]]+",
        "beautiful day",
        findall,
        "['b', 't', 'f', 'l', 'd', 'y']",
    ),
    (
        "set intersection, with (?V1)",
        r"(?V1)[\p{Greek}&&\p{Lu}]+",
        "ΑΒΓ αβγ ABC",
        findall,
        "['ΑΒΓ']",
    ),
    # Checked against the answer that looks wrong, because that is the answer
    # V0 really gives: `&&` degenerates to two more members of the set, so an
    # intersection quietly becomes a union. Green here means the trap is live.
    (
        "the same set WITHOUT (?V1) — silently a union",
        r"[\p{Greek}&&\p{Lu}]+",
        "ΑΒΓ αβγ ABC",
        findall,
        "['ΑΒΓ', 'αβγ', 'ABC']",
    ),
    (
        "every repetition of a group",
        r"(?:(\w+),?)+",
        "alpha,beta,gamma",
        groups,
        "['alpha', 'beta', 'gamma']",
    ),
    ("branch reset: one group number, two branches", r"(?|(a)|(b))", "ab", reset_groups, "['a', 'b']"),
    ("POSIX leftmost-longest alternation", r"(?p)a|ab", "abc", whole, "'ab'"),
    ("full case folding: ß against SS", r"(?V1)(?i)straße", "STRASSE", folded, "True"),
    ("a list of literals passed as data", r"\L<words>", "the cat sat on the mat", named_list, "['cat', 'mat']"),
    ("recursion into the whole pattern", r"\((?:[^()]++|(?R))*\)", "((((()))))", whole, "'((((()))))'"),
)


class Row(NamedTuple):
    """One comparison: the pattern, what each engine did with it, and the verdict."""

    label: str
    pattern: str
    stdlib: str
    third: str
    expected: str
    ok: bool


def attempt(module, pattern, subject, probe):
    """Run one probe against one engine and return either its `repr` or how it refused.

    The catch is broad on purpose. The `re` half of most rows raises `re.error`,
    but a probe can also fail with `AttributeError` (no `fuzzy_counts` on an `re`
    match) or `TypeError` (no `overlapped` keyword), and an unhandled exception
    inside a Flet handler ends the session rather than printing anything.
    """
    try:
        return repr(probe(module, pattern, subject))
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def compare():
    """Run every case through both engines and return the rows, verdicts included."""
    rows = []
    for label, pattern, subject, probe, expected in CASES:
        third = attempt(regex, pattern, subject, probe)
        stdlib = attempt(re, pattern, subject, probe)
        rows.append(Row(label, pattern, stdlib, third, expected, third == expected))
    return rows


def blowup(engine, length):
    """Time `(a+)+b` against a run of `a` with no `b` to find — the classic blowup.

    The subject cannot match, so a backtracking engine must exhaust every way of
    splitting the run before it can say so.
    """
    subject = "a" * length + "!"
    pattern = engine.compile(r"(a+)+b")
    start = time.perf_counter()
    pattern.match(subject)
    return (time.perf_counter() - start) * 1000


def backtracking():
    """The blowup ladder, stopped before the rung that would break the budget, as text lines.

    The stop is predictive rather than reactive: two more characters cost `re`
    about four times as much, so a rung is only attempted while four times the
    previous one still fits. Checking afterwards would mean paying for the very
    rung the budget exists to avoid.
    """
    lines = []
    for length in LADDER:
        stdlib = blowup(re, length)
        third = blowup(regex, length)
        lines.append(
            f"n={length:2d}  re {stdlib:9.2f} ms   regex {third:7.3f} ms   "
            f"{stdlib / third:8,.0f}x"
        )
        if stdlib * 4 > BUDGET_MS:
            lines.append(f"stopped: n={length + 2} would pass the {BUDGET_MS} ms budget")
            break
    return lines


def scan(pattern, **kwargs):
    """Milliseconds for one `findall` pass over the corpus, and its match count."""
    start = time.perf_counter()
    found = pattern.findall(CORPUS, **kwargs)
    return (time.perf_counter() - start) * 1000, len(found)


def alongside(work):
    """Run `work` while a second thread burns CPU, and return what `work` returned.

    This is what `page.run_thread` looks like from the inside once a user taps
    twice: its workers share one pool, so two of them genuinely run at the same
    time. The busy thread here stands in for that second worker.
    """
    stop = threading.Event()

    def burn():
        """Keep one core busy until the measured call has finished."""
        counter = 0
        while not stop.is_set():
            counter += 1

    sibling = threading.Thread(target=burn, daemon=True)
    sibling.start()
    time.sleep(0.05)
    try:
        return work()
    finally:
        stop.set()
        sibling.join()


def contention():
    """What a busy sibling thread costs each engine, as text lines.

    `regex` releases the GIL while matching a `str` unless told not to, and
    reacquires it often enough that every reacquisition waits out a scheduler
    handoff. `concurrent=False` is the switch that turns that off; `re` never had
    it on. Read the three rows only on an otherwise idle device — the multiplier
    is noisy, and a loaded machine can invert even the `alone` column.
    """
    stdlib = re.compile(EMAIL)
    third = regex.compile(EMAIL)
    lines = [
        f"corpus {len(CORPUS):,} chars, switch interval {sys.getswitchinterval() * 1000:.0f} ms"
    ]
    for label, work in (
        ("re.findall", lambda: scan(stdlib)),
        ("regex.findall (default)", lambda: scan(third)),
        ("regex.findall concurrent=False", lambda: scan(third, concurrent=False)),
    ):
        alone, count = work()
        busy, _ = alongside(work)
        lines.append(
            f"{label:31} alone {alone:8.2f} ms   busy {busy:9.2f} ms   "
            f"{busy / alone:6.1f}x   {count} hits"
        )
    return lines


def tables():
    """How far this runtime's `unicodedata` trails the tables compiled into `regex`.

    Every code point is offered to both. A disagreement in one direction only —
    `regex` calling something a letter that `unicodedata` has never heard of —
    means `regex` is carrying the newer Unicode release, which is the whole
    reason `\\p{...}` and `str.isalpha()` can disagree on the same character.
    """
    letter = regex.compile(r"\p{L}")
    start = time.perf_counter()
    ahead = behind = 0
    sample = []
    for code in range(0x110000):
        if 0xD800 <= code <= 0xDFFF:
            continue
        char = chr(code)
        unassigned = unicodedata.category(char) == "Cn"
        matched = bool(letter.match(char))
        if matched and unassigned:
            ahead += 1
            if len(sample) < 4:
                sample.append(f"U+{code:04X}")
        elif char.isalpha() and not matched:
            behind += 1
    elapsed = (time.perf_counter() - start) * 1000
    return [
        f"unicodedata {unicodedata.unidata_version} · scanned 1,112,064 code points in {elapsed:,.0f} ms",
        f"regex says letter, unicodedata says unassigned: {ahead:,}  e.g. {', '.join(sample)}",
        f"the other way round: {behind:,}",
    ]


def measure():
    """Run the three device probes in turn and return their lines, failures included.

    Each probe is wrapped separately so one that fails on a device names itself
    without costing the other two.
    """
    lines = []
    for name, probe in (
        ("catastrophic backtracking", backtracking),
        ("a CPU-busy sibling thread", contention),
        ("Unicode tables", tables),
    ):
        lines.append(f"— {name}")
        try:
            lines.extend(probe())
        except Exception as error:
            lines.append(f"  {type(error).__name__}: {error}")
    return lines


def evaluate(pattern, subject, version1):
    """Compile the typed pattern with `re`, run it with `regex`, and return both lines.

    `re` is compiled and not run, and the asymmetry is the point rather than a
    shortcut: it has no timeout and it holds the GIL for the whole match, so a
    typed pattern that backtracks freezes the session from a background thread
    exactly as much as from the event loop. `regex` takes `timeout=`, a real
    per-call CPU budget, which makes it the engine that may be handed a pattern
    somebody typed — with `concurrent=False`, so that budget stays this thread's
    own rather than being spent by a sibling.
    """
    try:
        re.compile(pattern)
        stdlib = "compiles (not run)"
    except Exception as error:
        stdlib = f"{type(error).__name__}: {error}"
    try:
        source = ("(?V1)" if version1 else "") + pattern
        third = repr(regex.findall(source, subject, timeout=1.0, concurrent=False))
    except Exception as error:
        third = f"{type(error).__name__}: {error}"
    return stdlib, third


def runtime():
    """The engine version, the interpreter, and where the extension says it lives.

    `getattr` rather than plain attribute access: Flet relocates ABI-tagged
    extensions out of site-packages on both platforms, and on Android the moved
    module can end up with no `__file__` at all — which as an AttributeError
    raised while the page is being built is a crash screen, not a line of text.
    """
    where = getattr(regex._regex, "__file__", None) or "no __file__"
    return f"regex {regex.__version__} · Python {platform.python_version()}", where
