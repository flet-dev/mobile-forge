import hashlib
import random
import sys
import time

from murmurhash import hash as mmh
from murmurhash.about import __version__

BITS = (12, 14, 16, 18)
LEXICON = 4000
DOCS = 700
HELD_OUT = 200
DOC_LEN = 55
HOT = 100
SYLLABLES = "ka re mo ti lu sa nde vi po zu fe gra tor mi lan dre sol vex ny qua"
VERSION = f"murmurhash {__version__} — {DOCS - HELD_OUT} documents, seed 7"


def corpus():
    """Build a fixed corpus, split into documents to learn from and documents to test.

    A feature is a token or an adjacent token pair, the way a bag-of-n-grams text
    classifier makes them, because the pairs are what push the feature count past
    anything you would want to carry as a vocabulary. Tokens come from a Zipf-like
    distribution, so a handful are very common and most appear once or twice — that
    shape is what decides whether a collision costs anything.

    The seed is fixed, so every number this app reports is reproducible. The last
    HELD_OUT documents are held back: a vocabulary built from the rest has never seen
    some of their words, and hashing is what makes that a non-question.
    """
    rng = random.Random(7)
    syllables = SYLLABLES.split()
    words = set()
    while len(words) < LEXICON:
        words.add("".join(rng.choice(syllables) for _ in range(rng.choice((2, 2, 3)))))
    words = sorted(words)

    cumulative = []
    running = 0.0
    for rank in range(len(words)):
        running += 1.0 / (rank + 1) ** 1.07
        cumulative.append(running)

    documents = []
    for _ in range(DOCS):
        tokens = rng.choices(words, cum_weights=cumulative, k=DOC_LEN)
        documents.append(tokens + [f"{a}|{b}" for a, b in zip(tokens, tokens[1:])])
    return documents[: DOCS - HELD_OUT], documents[DOCS - HELD_OUT :]


def bucket(feature, bits):
    """Map one feature string to a (bucket, sign) pair — the hashing trick itself.

    `hash` returns a signed 32-bit int, so the low bits pick the column and the sign
    bit comes free as a second hash. Adding +1 or -1 rather than always +1 keeps
    collisions from piling up in one direction, which is what scikit-learn's
    `alternate_sign` does. Masking is correct only because the table size is a power
    of two; for any other size use `%`. Python's `&` works on the two's-complement
    bits of a negative int, so the bucket is non-negative without an `abs()`.
    """
    value = mmh(feature)
    return value & ((1 << bits) - 1), 1 if value >= 0 else -1


def vectorize(documents, bits):
    """Turn every document into a sparse hashed vector and time the whole pass.

    Nothing is looked up and nothing is stored: the column index is computed from the
    feature string every time, which is why this needs no fitted state and why the
    vector width is whatever you chose rather than whatever the data turned out to be.
    """
    started = time.perf_counter()
    mask = (1 << bits) - 1
    vectors = []
    for features in documents:
        vector = {}
        for feature in features:
            value = mmh(feature)
            index = value & mask
            vector[index] = vector.get(index, 0) + (1 if value >= 0 else -1)
        vectors.append(vector)
    return vectors, (time.perf_counter() - started) * 1000


def with_vocabulary(documents, held_out):
    """Vectorize the same corpus the obvious way, with a dict of feature -> column.

    Returns milliseconds for building the vocabulary and running one vectorizing pass,
    the byte cost of the dict plus its keys, and the share of feature occurrences in
    the held-out documents that the vocabulary has never seen. That last number is the
    point of the comparison: those features are silently dropped, and the only fix is
    to rebuild the vocabulary — which renumbers the columns every model weight was
    learned against.
    """
    started = time.perf_counter()
    vocabulary = {}
    for features in documents:
        for feature in features:
            if feature not in vocabulary:
                vocabulary[feature] = len(vocabulary)
    for features in documents:
        vector = {}
        for feature in features:
            index = vocabulary.get(feature)
            if index is not None:
                vector[index] = vector.get(index, 0) + 1
    elapsed = (time.perf_counter() - started) * 1000

    # getsizeof of the dict alone counts the table, not the strings it points at.
    footprint = sys.getsizeof(vocabulary) + sum(sys.getsizeof(k) for k in vocabulary)
    seen = missed = 0
    for features in held_out:
        for feature in features:
            seen += 1
            missed += feature not in vocabulary
    return elapsed, len(vocabulary), footprint, 100.0 * missed / seen


def table(documents, bits):
    """Report what a table of 2**bits buckets does to this corpus's features.

    Counts every distinct feature into its bucket and returns the table size, the
    number of distinct features, the percentage sharing a bucket with at least one
    other, the fullest bucket, the same percentage restricted to the HOT most frequent
    features, and one concrete colliding pair to put on screen.

    The two percentages are the whole tradeoff. Rare features collide constantly and
    nobody notices, because a weight learned for a feature seen twice is noise anyway.
    A collision between two features the classifier leans on is the one that costs
    accuracy, and it stays rare far longer because there are so few of them.
    """
    counts = {}
    for features in documents:
        for feature in features:
            counts[feature] = counts.get(feature, 0) + 1
    hottest = set(sorted(counts, key=lambda feature: -counts[feature])[:HOT])

    buckets = {}
    for feature in counts:
        buckets.setdefault(bucket(feature, bits)[0], []).append(feature)
    shared = [group for group in buckets.values() if len(group) > 1]

    hot_hits = 0
    for group in shared:
        hot_in_group = sum(1 for feature in group if feature in hottest)
        hot_hits += hot_in_group if hot_in_group > 1 else 0
    example = next(
        (group for group in shared if all("|" not in f for f in group)),
        shared[0] if shared else ["—", "—"],
    )
    return {
        "buckets": 1 << bits,
        "features": len(counts),
        "collided": 100.0 * sum(len(g) for g in shared) / len(counts),
        "fullest": max(len(group) for group in buckets.values()),
        "hot": 100.0 * hot_hits / HOT,
        "example": example[:2],
    }


def stability():
    """Show why a feature index cannot be built on Python's own `hash`.

    CPython salts `str.__hash__` per process, so the same string gives a different
    number after every launch and any index built from it is worthless the moment the
    app restarts. murmurhash returns the same 32-bit value on every run, every
    platform and every architecture in this wheel. Relaunch the app: the second row
    changes and the third does not.
    """
    return [
        ("hash randomisation", "on" if sys.flags.hash_randomization else "off"),
        ("builtin hash('apple')", f"{hash('apple')}"),
        ("murmurhash hash('apple')", f"{mmh('apple')}"),
    ]


def throughput(documents):
    """Time murmurhash against a cryptographic hash over the corpus's features.

    Both sides pay one UTF-8 encode per feature — murmurhash does it inside
    `hash_unicode`, BLAKE2b needs it at the call — so this is like for like. Neither
    touches the hash CPython caches on a str, so repeating the pass over the same
    objects does not drift. BLAKE2b rather than SHA-256 because arm64 has SHA-2
    instructions an emulator does not, which would make that ratio an artefact of the
    emulator rather than a fact about the hashes.
    """
    features = [feature for document in documents for feature in document]

    started = time.perf_counter()
    for feature in features:
        mmh(feature)
    murmur = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    for feature in features:
        hashlib.blake2b(feature.encode(), digest_size=8).digest()
    blake = (time.perf_counter() - started) * 1000
    return len(features), murmur, blake


def probe(text, bits):
    """Hash whatever the user typed and report the raw value, bucket and sign.

    The raw signed 32-bit number is the fact everything above rests on, so it is worth
    seeing directly: an empty string hashes to 0, and about half of all inputs come
    back negative.
    """
    index, sign = bucket(text, bits)
    return mmh(text), index, sign
