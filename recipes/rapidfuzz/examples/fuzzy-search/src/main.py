"""Fuzzy search over 4,000 in-app strings, with every number on screen checked a second way."""

import random
import sys
import time

import flet as ft
import numpy as np
import rapidfuzz
from rapidfuzz import fuzz, process, utils
from rapidfuzz.distance import Levenshtein

HEADS = (
    "North South East West Upper Lower Old New Great Little "
    "Black White Red Green Stone Iron Silver Golden Kings Queens"
).split()
STEMS = (
    "Haven Brook Field Bridge Ford Wick Thorpe Dale Combe Mere "
    "Holt Ridge Moor Cliff Gate Market Chester Hampton Bourne Worth"
).split()
TAILS = "Bay Junction Crossing Green Hill Mills Point Springs Valley Wood".split()

SEED = 20260817
LIMIT = 8
REPEATS = 3
# Misspelled *and* reordered, which is the pair of problems the six scorers
# disagree most visibly about.
DEFAULT_QUERY = "junctn havn nrth"

# 20 x 20 x 10 = 4,000 names from a fixed seed, so every device searches the same
# list with no data file and no network. Title Case is deliberate: the default
# query is lowercase, which is what makes rapidfuzz's case sensitivity visible.
CORPUS = [f"{head} {stem} {tail}" for head in HEADS for stem in STEMS for tail in TAILS]
random.Random(SEED).shuffle(CORPUS)

# The multiplier puts every scorer on one 0-100 scale: the fuzz.* scorers are
# already percentages, the distance metrics are normalised to 0.0-1.0.
SCORERS = {
    "ratio": (fuzz.ratio, 1.0),
    "partial_ratio": (fuzz.partial_ratio, 1.0),
    "token_sort_ratio": (fuzz.token_sort_ratio, 1.0),
    "token_set_ratio": (fuzz.token_set_ratio, 1.0),
    "WRatio": (fuzz.WRatio, 1.0),
    "Levenshtein": (Levenshtein.normalized_similarity, 100.0),
}


def native_origin():
    """The file the import system actually opened for the module behind fuzz.ratio.

    Worth printing because Flet relocates native extensions out of site-packages on
    both platforms, so only on desktop is this the path you would guess. Read
    through __spec__ rather than __file__: which of the two survives relocation
    varies by platform and by package.
    """
    module = sys.modules.get(fuzz.ratio.__module__)
    return getattr(getattr(module, "__spec__", None), "origin", None) or "unknown"


def fastest(call, repeats=REPEATS):
    """Call something a few times; return its value and the shortest time it took."""
    value = None
    best = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = call()
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return value, best


def python_top(query, scorer, limit):
    """The same top-N picked by hand, so process.extract's answer has a rival.

    Deliberately does exactly what extract does — process the query once, each
    choice once — because a loop handed a pre-processed corpus is not the same
    workload and would flatter extract by a factor of its own.
    """
    processed = utils.default_process(query)
    scored = ((scorer(processed, utils.default_process(c)), c) for c in CORPUS)
    return [choice for _, choice in sorted(scored, key=lambda pair: -pair[0])[:limit]]


def compare_scorers(query):
    """Score one query against the whole corpus under each of the six scorers.

    Returns the best match, its score, and the same pair rescored with no
    processor. The scorers disagree — sometimes only in the number, sometimes in
    which string wins — and nothing tells you that you picked the wrong one, so
    the table is the point of the screen rather than decoration. The second number
    is what a lowercase query costs against this Title Cased corpus.
    """
    rows = []
    for label, (scorer, scale) in SCORERS.items():
        match, score, _ = process.extractOne(
            query, CORPUS, scorer=scorer, processor=utils.default_process
        )
        rows.append((label, match, score * scale, scorer(query, match) * scale))
    return rows


def main(page: ft.Page):
    """A search box over a fixed 4,000-string corpus; every figure is cross-checked.

    The header is read off the device rather than assumed. `COMPILED` versus
    `PURE-PYTHON` is the one runtime check that can really fail here: when a native
    module will not load, rapidfuzz falls back to its pure-Python twin silently, with
    identical answers and tens of times the cost, and `fuzz.ratio.__module__` is the
    only tell.
    """

    def clear():
        """Blank every computed row, so a failure cannot leave the last answer under it."""
        results.controls = []
        table.rows = []
        for row in (caption, cross, speed):
            row.value = ""

    def render(query, label):
        """Fill in every row for one query. Runs in the thread pool, not on the UI thread."""
        scorer, scale = SCORERS[label]
        ranked, extract_s = fastest(
            lambda: process.extract(
                query,
                CORPUS,
                scorer=scorer,
                processor=utils.default_process,
                limit=LIMIT,
            )
        )
        by_hand, loop_s = fastest(lambda: python_top(query, scorer, LIMIT))
        matrix = process.cdist(
            [query], CORPUS, scorer=scorer, processor=utils.default_process
        )

        caption.value = f"{len(CORPUS)} choices ranked by {label}"
        results.controls = [
            ft.Text(f"{rank}. {match}   {score * scale:.1f}", size=13)
            for rank, (match, score, _) in enumerate(ranked, 1)
        ]
        table.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(cell, size=12))
                    for cell in (name, match, f"{score:.1f}", f"{raw:.1f}")
                ]
            )
            for name, match, score, raw in compare_scorers(query)
        ]

        winner = CORPUS[int(matrix.argmax())]
        cross.value = (
            f"cdist([query], choices) -> {matrix.shape} {matrix.dtype}, "
            f"{matrix.nbytes} bytes; its argmax is {winner!r}, "
            f"extract's top hit is {ranked[0][0]!r} — "
            f"{'AGREE' if winner == ranked[0][0] else 'DISAGREE'}"
        )

        # Divide the rounded figures rather than the raw ones, so the three numbers
        # on the line agree with each other as printed.
        quick = max(round(extract_s * 1e3, 3), 0.001)
        slow = round(loop_s * 1e3, 3)
        speed.value = (
            f"process.extract {quick:.3f} ms vs the same top {LIMIT} by hand "
            f"{slow:.3f} ms — {slow / quick:.1f}x, same answer: "
            f"{[match for match, _, _ in ranked] == by_hand}"
        )

    def work():
        """Run one search, then hand the inputs back whatever happened.

        page.run_thread never retrieves the worker's future, so anything raised in
        here would vanish without a log; the blanket except puts the message in the
        field instead. rapidfuzz signals bad input with plain builtin TypeErrors
        ("object of type 'int' has no len()", "score_cutoff has to be in the range
        of 0.0 - 1.0"), not a class of its own, and an unhandled exception in a Flet
        handler produces a crash screen rather than a log line.
        """
        query = (field.value or "").strip()
        try:
            if query:
                field.error = None
                render(query, picker.value)
            else:
                clear()
                field.error = "type something to search for"
        except Exception as error:
            clear()
            field.error = f"{type(error).__name__}: {error}"
        finally:
            field.disabled = False
            picker.disabled = False
            page.update()  # auto-update does not reach background threads

    def start():
        """Send one search off the UI thread, for the field's Enter or a new scorer.

        The guard reads `disabled` back rather than trusting it to have taken effect:
        disabling only queues the new state for the client, and page.run_thread
        submits to a shared pool, so a second gesture inside that window would put
        two workers on the same rows and nothing on screen would admit it.
        """
        if field.disabled:
            return
        field.disabled = True
        picker.disabled = True
        page.update()
        page.run_thread(work)

    page.appbar = ft.AppBar(title=ft.Text("rapidfuzz fuzzy search"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"rapidfuzz {rapidfuzz.__version__} · "
                        f"{'PURE-PYTHON' if fuzz.ratio.__module__.endswith('_py') else 'COMPILED'} · "
                        f"fuzz.ratio→{fuzz.ratio.__module__} · "
                        f"process.extract→{process.extract.__module__} · "
                        f"numpy {np.__version__} · {page.platform.value}",
                        size=11,
                        selectable=True,
                    ),
                    ft.Text(f"loaded from {native_origin()}", size=11, selectable=True),
                    field := ft.TextField(
                        label="Search 4,000 place names",
                        value=DEFAULT_QUERY,
                        on_submit=start,
                    ),
                    picker := ft.Dropdown(
                        label="Ranking scorer",
                        value="WRatio",
                        options=[ft.DropdownOption(key=name) for name in SCORERS],
                        on_select=start,
                    ),
                    caption := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    results := ft.Column(spacing=2),
                    ft.Text(
                        "the same query under every scorer — Levenshtein is "
                        "normalized_similarity ×100, and the last column is the same "
                        "pair with no processor",
                        size=11,
                    ),
                    # A DataTable this wide overflows a phone; a non-scrolling Row
                    # around it would paint Flutter's OVERFLOWED stripes instead.
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[
                            table := ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text("scorer")),
                                    ft.DataColumn(ft.Text("top match")),
                                    ft.DataColumn(ft.Text("score")),
                                    ft.DataColumn(ft.Text("no processor")),
                                ],
                                column_spacing=18,
                            )
                        ],
                    ),
                    cross := ft.Text(size=12),
                    speed := ft.Text(size=12),
                    ft.Text(
                        f"case only: fuzz.ratio('CAFE', 'cafe') = "
                        f"{fuzz.ratio('CAFE', 'cafe'):.1f}, and "
                        f"{fuzz.ratio('CAFE', 'cafe', processor=utils.default_process):.1f} "
                        f"with processor=default_process",
                        size=12,
                    ),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
