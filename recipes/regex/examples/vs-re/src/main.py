"""Run one pattern through `re` and through `regex` and show where the stdlib stops."""

import platform
import re
import sys
import threading
import time
import unicodedata

import flet as ft

try:
    import regex

    IMPORT_ERROR = None
except Exception as error:
    regex = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

GREEK = "Είναι 42 μέρες"
CLUSTERS = "\U0001f469‍\U0001f469‍\U0001f467‍\U0001f466\U0001f1ec\U0001f1edé"

# The subject for the contention scan. Sized by its match count, not its
# length: the cost being measured there is one GIL handoff per match, so 200
# repeats — one address each — is what makes the effect legible.
CORPUS = "Order 4471 shipped 2026-05-09 to alice@example.com for USD 1,299.00. " * 200
EMAIL = r"\w+@\w+\.\w+"

# `re` is exponential in this pattern's input length, so the ladder is walked
# from the cheap end and abandoned before it gets expensive. A phone slower
# than a laptop stops a rung or two earlier instead of freezing the screen.
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


def cases():
    """The fixed list of comparisons, each a label, a pattern, a subject, a probe and the answer.

    The expected value is the `repr` of what `regex` must return, and it is
    checked rather than described — a row whose engine changed under it turns
    red here instead of quietly printing something new. Nothing is asserted
    about the `re` half: what it raises is a message that varies by CPython
    version, so it is displayed as observed and never compared.
    """
    return (
        (
            "property class: any Unicode letter",
            r"\p{L}+",
            GREEK,
            findall,
            "['Είναι', 'μέρες']",
        ),
        (
            "script name as a class",
            r"\p{Greek}+",
            GREEK,
            findall,
            "['Είναι', 'μέρες']",
        ),
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
        (
            "overlapping matches",
            r"\d\d",
            "12345",
            overlapping,
            "['12', '23', '34', '45']",
        ),
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
        (
            "branch reset: one group number, two branches",
            r"(?|(a)|(b))",
            "ab",
            reset_groups,
            "['a', 'b']",
        ),
        (
            "POSIX leftmost-longest alternation",
            r"(?p)a|ab",
            "abc",
            whole,
            "'ab'",
        ),
        (
            "full case folding: ß against SS",
            r"(?V1)(?i)straße",
            "STRASSE",
            folded,
            "True",
        ),
        (
            "a list of literals passed as data",
            r"\L<words>",
            "the cat sat on the mat",
            named_list,
            "['cat', 'mat']",
        ),
        (
            "recursion into the whole pattern",
            r"\((?:[^()]++|(?R))*\)",
            "((((()))))",
            whole,
            "'((((()))))'",
        ),
    )


def attempt(module, pattern, subject, probe):
    """Run one probe against one engine and return either its `repr` or how it refused.

    The catch is broad on purpose. The `re` half of most rows raises
    `re.error`, but a probe can also fail with `AttributeError` (no
    `fuzzy_counts` on an `re` match) or `TypeError` (no `overlapped` keyword),
    and an unhandled exception inside a Flet handler ends the session rather
    than printing anything.
    """
    try:
        return repr(probe(module, pattern, subject))
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def blowup(engine, length):
    """Time `(a+)+b` against a run of `a` with no `b` to find — the classic blowup.

    The subject cannot match, so a backtracking engine must exhaust every way
    of splitting the run before it can say so.
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
    previous one still fits. Checking afterwards instead would mean paying for
    the very rung the budget exists to avoid.
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
            lines.append(
                f"stopped: n={length + 2} would pass the {BUDGET_MS} ms budget"
            )
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
    time. The busy thread here is a stand-in for that second worker.
    """
    stop = threading.Event()

    def burn():
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
    handoff. `concurrent=False` is the switch that turns that off; `re` never
    had it on.
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


def main(page: ft.Page):
    """Show the comparison table at once, and put the three timed probes behind a button.

    The table runs inline: all fifteen rows through both engines cost about
    14 ms of CPU on a cold desktop cp312 and a tenth of that once the pattern
    caches are warm. The measurements are seconds — the `re` half of the blowup
    ladder is allowed up to 1.5 s on its own — so they go to
    `page.run_thread`, guarded by a `threading.Event` so two taps cannot
    overlap, the body wrapped because `run_thread` discards what a worker
    raises, and an explicit `page.update()` at the end because auto-update does
    not reach a background thread.
    """

    running = threading.Event()

    def row(index, label, pattern, stdlib, third, ok):
        """One comparison: a verdict dot, the pattern, and what each engine did with it."""
        return ft.Column(
            spacing=1,
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.CIRCLE,
                            size=9,
                            color=ft.Colors.GREEN if ok else ft.Colors.RED,
                        ),
                        ft.Text(f"{index}. {label}", size=11, expand=True),
                    ]
                ),
                ft.Text(f"    {pattern}", size=10, font_family="monospace"),
                ft.Text(f"    re    {stdlib}", size=10),
                ft.Text(f"    regex {third}", size=10),
            ],
        )

    def compare():
        """Fill the table, counting how many rows `regex` answered as expected."""
        agreed = 0
        for index, (label, pattern, subject, probe, expected) in enumerate(cases(), 1):
            third = attempt(regex, pattern, subject, probe)
            ok = third == expected
            agreed += ok
            stdlib = attempt(re, pattern, subject, probe)
            table.controls.append(row(index, label, pattern, stdlib, third, ok))
            if not ok:
                table.controls.append(
                    ft.Text(f"    expected {expected}", size=10, italic=True)
                )
        return agreed

    def measured():
        """Run the three timed probes and hand back their lines, or the failure."""
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

    def benchmark():
        """The button handler: measure off the UI thread, then redraw.

        `run.disabled` is not the guard against a second tap — it only reaches
        the client a round trip later, and a tap already in flight still
        arrives. Two workers measuring thread contention at once would be
        measuring each other, so the guard is checked here.
        """
        if running.is_set():
            return
        running.set()

        def work():
            try:
                numbers.controls = [
                    ft.Text(line, size=10, font_family="monospace")
                    for line in measured()
                ]
            except Exception as error:
                numbers.controls = [
                    ft.Text(f"{type(error).__name__}: {error}", size=11)
                ]
            finally:
                running.clear()
                run.disabled = False
                page.update()

        run.disabled = True
        numbers.controls = [ft.Text("measuring…", size=11)]
        page.run_thread(work)

    def evaluate():
        """The playground handler: the typed pattern compiled by `re`, run by `regex`.

        `re` is compiled and not run. It has no timeout, and it does not
        release the GIL, so a typed pattern that backtracks freezes the whole
        session — from a `run_thread` worker exactly as much as from here.
        `regex` takes `timeout=`, a real per-call CPU budget, so it is the one
        of the two that may be handed a pattern somebody typed;
        `concurrent=False` for the reason the contention numbers above give.
        """
        try:
            subject = text.value or ""
            source = ("(?V1)" if version1.value else "") + (query.value or "")
            try:
                re.compile(query.value or "")
                stdlib = "compiles (not run)"
            except Exception as error:
                stdlib = f"{type(error).__name__}: {error}"
            try:
                third = repr(
                    regex.findall(source, subject, timeout=1.0, concurrent=False)
                )
            except Exception as error:
                third = f"{type(error).__name__}: {error}"
            played.controls = [
                ft.Text(f"re    {stdlib}", size=10),
                ft.Text(f"regex {third}", size=10),
            ]
        except Exception as error:
            played.controls = [ft.Text(f"{type(error).__name__}: {error}", size=11)]

    page.appbar = ft.AppBar(title=ft.Text("regex vs re"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    table := ft.Column(spacing=6),
                    ft.Divider(),
                    run := ft.Button("measure this device", icon=ft.Icons.TIMER),
                    numbers := ft.Column(spacing=1),
                    ft.Divider(),
                    ft.Text("try one yourself", size=11, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "re is compiled here, not run: it has no timeout, and the "
                        "backtracking numbers above are what one typed pattern can "
                        "cost. regex runs with timeout=1.0.",
                        size=10,
                        italic=True,
                    ),
                    query := ft.TextField(
                        label="pattern",
                        value=r"\p{Lu}\p{Ll}+",
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=12,
                    ),
                    text := ft.TextField(
                        label="subject",
                        value="Καλημέρα from Flet on Android and iOS",
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=12,
                    ),
                    version1 := ft.Checkbox(label="prepend (?V1)", value=False),
                    ft.Button("findall", icon=ft.Icons.PLAY_ARROW, on_click=evaluate),
                    played := ft.Column(spacing=1),
                ],
            ),
        )
    )

    if regex is None:
        header.value = (
            f"{IMPORT_ERROR}\nregex is a compiled extension; the wheel comes from "
            "pypi.flet.dev on a device and from PyPI on a desktop."
        )
        run.disabled = True
        return

    run.on_click = benchmark
    agreed = compare()
    total = len(cases())
    # `getattr` rather than plain attribute access: Flet relocates ABI-tagged
    # extensions out of site-packages, and on Android the moved module can end
    # up with no `__file__` at all — which as an AttributeError here would be a
    # crash screen instead of a line of text.
    where = getattr(regex._regex, "__file__", None) or "no __file__"
    header.value = (
        f"regex {regex.__version__} · Python {platform.python_version()} · "
        f"{page.platform.value}/{platform.machine()} · "
        f"{agreed}/{total} rows as expected\n{where}"
    )
    evaluate()


if __name__ == "__main__":
    ft.run(main)
