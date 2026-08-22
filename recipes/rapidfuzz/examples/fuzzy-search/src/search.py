"""The rapidfuzz half of the example: one corpus, six scorers, three ways to the same answer."""

import random
import sys
import time
from collections import namedtuple

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
DEFAULT_SCORER = "WRatio"

# 20 x 20 x 10 = 4,000 names from a fixed seed, so every device searches the same
# list with no data file and no network. Title Case is deliberate: the default
# query is lowercase, which is what makes rapidfuzz's case sensitivity visible.
CORPUS = [f"{head} {stem} {tail}" for head in HEADS for stem in STEMS for tail in TAILS]
random.Random(SEED).shuffle(CORPUS)
CORPUS_SIZE = len(CORPUS)

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
SCORER_NAMES = tuple(SCORERS)

TABLE_NOTE = (
    "the same query under every scorer — Levenshtein is normalized_similarity ×100, "
    "and the last column is the same pair with no processor"
)
CASE_NOTE = (
    f"case only: fuzz.ratio('CAFE', 'cafe') = {fuzz.ratio('CAFE', 'cafe'):.1f}, and "
    f"{fuzz.ratio('CAFE', 'cafe', processor=utils.default_process):.1f} with "
    f"processor=default_process"
)

Answer = namedtuple("Answer", "caption ranked table cdist_note speed_note")


def describe():
    """What actually loaded, for the header line.

    COMPILED versus PURE-PYTHON is the only runtime check on this screen that can
    really fail: when a native module will not load, rapidfuzz falls back to its
    pure-Python twin silently, with identical answers and tens of times the cost,
    and the module name behind fuzz.ratio is the only tell.
    """
    kind = "PURE-PYTHON" if fuzz.ratio.__module__.endswith("_py") else "COMPILED"
    return (
        f"rapidfuzz {rapidfuzz.__version__} · {kind} · "
        f"fuzz.ratio→{fuzz.ratio.__module__} · "
        f"process.extract→{process.extract.__module__} · numpy {np.__version__}"
    )


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


def search(query, name):
    """Rank the corpus for one query, then check the ranking two other ways.

    process.extract does the work; python_top recomputes the same top LIMIT in a
    Python loop, and process.cdist scores the query against every choice into a
    numpy array whose argmax should name the same string. Returns everything the
    screen shows and no controls: the caption, the top LIMIT as (name, score)
    pairs already on a 0-100 scale, the six-scorer table, and the two verdict
    lines.
    """
    scorer, scale = SCORERS[name]
    ranked, extract_s = fastest(
        lambda: process.extract(
            query, CORPUS, scorer=scorer, processor=utils.default_process, limit=LIMIT
        )
    )
    by_hand, loop_s = fastest(lambda: python_top(query, scorer, LIMIT))
    matrix = process.cdist(
        [query], CORPUS, scorer=scorer, processor=utils.default_process
    )

    winner = CORPUS[int(matrix.argmax())]
    top = ranked[0][0]
    cdist_note = (
        f"cdist([query], choices) -> {matrix.shape} {matrix.dtype}, "
        f"{matrix.nbytes} bytes; its argmax is {winner!r}, "
        f"extract's top hit is {top!r} — "
        f"{'AGREE' if winner == top else 'DISAGREE'}"
    )

    # Divide the rounded figures rather than the raw ones, so the three numbers
    # on the line agree with each other as printed.
    quick = max(round(extract_s * 1e3, 3), 0.001)
    slow = round(loop_s * 1e3, 3)
    speed_note = (
        f"process.extract {quick:.3f} ms vs the same top {LIMIT} by hand "
        f"{slow:.3f} ms — {slow / quick:.1f}x, same answer: "
        f"{[match for match, _, _ in ranked] == by_hand}"
    )

    return Answer(
        caption=f"{CORPUS_SIZE} choices ranked by {name}",
        ranked=[(match, score * scale) for match, score, _ in ranked],
        table=compare_scorers(query),
        cdist_note=cdist_note,
        speed_note=speed_note,
    )
