"""Everything the tokenizer does: train it, save it, and measure what it says."""

import os
import time

import tokenizers
from tokenizers import Tokenizer, decoders, pre_tokenizers
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel
from tokenizers.trainers import BpeTrainer

SIZES = (500, 1000, 2000, 4000, 8000, 16000)

VOCAB_SIZE = 2000

WINDOW = 64

PARAGRAPH_LINES = 20

SUBJECTS = (
    "the quick brown fox",
    "a curious otter",
    "our neighbour's cat",
    "the night train",
    "an old lighthouse",
    "the harbour crane",
    "a paper aeroplane",
    "the corner bakery",
)

VERBS = (
    "jumps over",
    "drifts past",
    "watches",
    "circles",
    "outlasts",
    "shelters",
    "measures",
    "forgets",
)

OBJECTS = (
    "the lazy dog",
    "seventeen crates",
    "a folded map",
    "the last ferry",
    "every rain gauge",
    "two tired cyclists",
    "the reading room",
    "a bowl of plums",
)

ADVERBS = (
    "slowly",
    "twice",
    "somehow",
    "politely",
    "at length",
    "by mistake",
    "on purpose",
    "half-asleep",
)

TAILS = (
    "before dawn.",
    "again, quietly.",
    "on Tuesday!",
    "without comment.",
    "for the third time?",
    "-- and then stops.",
    "; nobody minds.",
    "in the fog.",
)

# Only the first is in the corpus's vocabulary; the rest are not, and three of them are
# not even ASCII. They still round-trip because the trainer is seeded with
# ByteLevel.alphabet() — that is the claim the table on screen checks.
PROBES = (
    "the night train circles a folded map",
    "hello world",
    "hello,  world!",
    "Zürich — 42 €",
    "a\tb\nc",
    "🙂 emoji test",
    "",
)

OFFSET_SENTENCE = "the crane lifts 17 crates — €5"

STORE = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "models", "trained.json")


def native_origin():
    """The file name the import system resolved the Rust extension to, on this device.

    `__file__` first and `__spec__.origin` second: Flet relocates native extensions
    out of site-packages, and which attribute survives varies by platform.
    """
    module = tokenizers.tokenizers
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def hub_version():
    """`huggingface_hub.__version__`, or why it is not there.

    It arrives as a hard dependency of the tokenizers wheel whether or not an app calls
    `from_pretrained`, and mobile resolves an older version than a desktop lock does.
    """
    try:
        import huggingface_hub
    except ImportError:
        return "not installed"
    return huggingface_hub.__version__


def make_corpus(lines):
    """`lines` sentences built from five fixed word lists, with no randomness.

    The same slider position gives the same text on every install, so two devices are
    directly comparable. Nothing is downloaded and no asset is bundled.
    """
    return [
        f"{SUBJECTS[index % 8]} {VERBS[(index // 8) % 8]} {OBJECTS[(index // 64) % 8]} "
        f"{ADVERBS[(index // 512) % 8]} {TAILS[(index // 4096) % 8]}"
        for index in range(lines)
    ]


def train(corpus):
    """Train a byte-level BPE on `corpus`; return it and the milliseconds it took.

    Three settings make the round trip lossless and they work together: a `ByteLevel`
    pre-tokenizer, the matching `ByteLevel` decoder, and `initial_alphabet` seeded
    with all 256 byte symbols. Drop the last and characters the corpus never held are
    dropped from the output rather than raising. An empty vocabulary is raised because
    an untrained tokenizer encodes to `[]` without complaining.
    """
    tokenizer = Tokenizer(BPE(unk_token=None))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = BpeTrainer(
        vocab_size=VOCAB_SIZE,
        show_progress=False,
        initial_alphabet=ByteLevel.alphabet(),
    )
    started = time.perf_counter()
    tokenizer.train_from_iterator(corpus, trainer=trainer)
    elapsed = (time.perf_counter() - started) * 1000.0
    if not tokenizer.get_vocab_size():
        raise RuntimeError("training produced an empty vocabulary")
    return tokenizer, elapsed


def save(tokenizer):
    """Write the tokenizer under app storage and return the file size in bytes.

    The `makedirs` is load-bearing: `save()` does not create the parent directory, and
    says so with a bare `Exception` reading `No such file or directory (os error 2)`.
    """
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tokenizer.save(STORE)
    return os.path.getsize(STORE)


def probe_rows(tokenizer):
    """Per probe: the text, its token count, whether it round-trips, and a vocab lookup.

    The last check never goes near the decoder — it looks every token up in
    `get_vocab()` and compares those ids against the ones `encode` returned — so a
    decoder bug and a vocabulary bug fail differently instead of one plausible pass.
    """
    vocab = tokenizer.get_vocab()
    rows = []
    for text in PROBES:
        encoded = tokenizer.encode(text)
        rows.append(
            (
                text,
                len(encoded.ids),
                tokenizer.decode(encoded.ids) == text,
                [vocab[token] for token in encoded.tokens] == encoded.ids,
            )
        )
    return rows


def offset_rows(tokenizer):
    """Per token of `OFFSET_SENTENCE`: the token, its `(start, end)`, and that slice.

    Offsets index the original string, so each range on its own is the token's source
    text. They are not a partition of it: every token of a multi-byte character carries
    the same range, which is why rows repeat and why rebuilding text from them is wrong.
    """
    encoded = tokenizer.encode(OFFSET_SENTENCE)
    return [
        (token, start, end, OFFSET_SENTENCE[start:end])
        for token, (start, end) in zip(encoded.tokens, encoded.offsets)
    ]


def budget(tokenizer, corpus):
    """Cost a fixed paragraph in tokens, window its ids, and check that both rejoin.

    Windows have to come from slicing the id list: `enable_truncation` drops the tail
    and leaves `Encoding.overflowing` empty. The ids always rejoin; the text stops
    rejoining the moment a window boundary lands inside a multi-byte character.
    """
    text = " ".join(corpus[:PARAGRAPH_LINES])
    ids = tokenizer.encode(text).ids
    windows = [ids[start : start + WINDOW] for start in range(0, len(ids), WINDOW)]
    return (
        len(text),
        len(ids),
        len(windows),
        [token for window in windows for token in window] == ids,
        "".join(tokenizer.decode(window) for window in windows) == text,
    )


def reload(tokenizer):
    """Read the saved file back; return its size and how many probes give identical ids.

    `tokenizer` is the copy still in memory on purpose: comparing a second `from_file`
    against the first would compare the file with itself and always agree.
    """
    reloaded = Tokenizer.from_file(STORE)
    agree = sum(
        reloaded.encode(text).ids == tokenizer.encode(text).ids for text in PROBES
    )
    return os.path.getsize(STORE), agree, len(PROBES)
