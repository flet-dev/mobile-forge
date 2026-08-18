"""Train a byte-level BPE tokenizer on this device, then count, decode and locate tokens with it."""

import os
import platform
import time

import flet as ft
import tokenizers
from tokenizers import Tokenizer, decoders, pre_tokenizers
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel
from tokenizers.trainers import BpeTrainer

SIZES = (500, 1000, 2000, 4000, 8000, 16000)

VOCAB_SIZE = 2000

WINDOW = 64

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

TRIP_WEIGHTS = (9, 3, 3, 4)

OFFSET_WEIGHTS = (4, 4, 4)

STORE = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "models", "trained.json")


def native_origin():
    """Where the import system found the Rust extension on this device, as a short name.

    Read through `__file__` first and `__spec__.origin` second: Flet relocates native
    extensions out of site-packages, and which attribute survives varies by platform.
    """
    module = tokenizers.tokenizers
    origin = getattr(module, "__file__", None) or getattr(
        getattr(module, "__spec__", None), "origin", None
    )
    return origin.rsplit("/", 1)[-1] if origin else "unreported"


def hub_version():
    """`huggingface_hub.__version__`, or why it is not there.

    It arrives as a hard `Requires-Dist` of the tokenizers wheel whether or not an app
    calls `from_pretrained`, and `flet build` resolves an older version for mobile than a
    desktop lock does — so the number worth trusting is the one this device reports.
    """
    try:
        import huggingface_hub
    except ImportError:
        return "not installed"
    return huggingface_hub.__version__


def make_corpus(lines):
    """`lines` sentences built from five fixed word lists.

    Deterministic, so the same slider position produces the same text on every install and
    two devices are directly comparable. Nothing is downloaded and no asset is bundled.
    """
    return [
        f"{SUBJECTS[index % 8]} {VERBS[(index // 8) % 8]} {OBJECTS[(index // 64) % 8]} "
        f"{ADVERBS[(index // 512) % 8]} {TAILS[(index // 4096) % 8]}"
        for index in range(lines)
    ]


def train(corpus):
    """Train a byte-level BPE on `corpus` and return it with the milliseconds it took.

    Three settings make the round trip lossless and they work together: a `ByteLevel`
    pre-tokenizer with the matching `ByteLevel` decoder, and `initial_alphabet` seeded with
    all 256 byte symbols. Drop the last one and characters the corpus never contained are
    dropped from the output instead of raising — the text just comes back shorter.
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
    return tokenizer, (time.perf_counter() - started) * 1000.0


def save(tokenizer):
    """Write the tokenizer to app storage and return the file size.

    `save()` does not create the parent directory — it raises a bare `Exception` reading
    `No such file or directory (os error 2)` — so the `makedirs` is load-bearing. `pretty`
    defaults to True; False roughly halves the file.
    """
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tokenizer.save(STORE)
    return os.path.getsize(STORE)


def trip_rows(tokenizer):
    """One row per probe string: token count, `decode(encode(s)) == s`, and a second check.

    The second column is deliberately not the decoder: it looks every token up in
    `get_vocab()` and compares the ids that gives against the ids `encode` returned. A
    decoder bug and a vocabulary bug then show up as two different failures rather than one
    plausible-looking pass.
    """
    vocab = tokenizer.get_vocab()
    rows = []
    for text in PROBES:
        encoded = tokenizer.encode(text)
        trip = tokenizer.decode(encoded.ids) == text
        lookup = [vocab[token] for token in encoded.tokens] == encoded.ids
        rows.append(
            (
                repr(text),
                f"{len(encoded.ids)} tok",
                "PASS" if trip else "FAIL",
                "PASS" if lookup else "FAIL",
            )
        )
    return rows


def offset_rows(tokenizer):
    """Token, its `(start, end)` offsets, and the literal source slice those offsets name.

    Offsets index the original string, so each range on its own is the token's source text.
    They are not a partition of it: every token of a multi-byte character carries the same
    range, which is why the rows repeat and why rebuilding text from them is wrong.
    """
    encoded = tokenizer.encode(OFFSET_SENTENCE)
    return [
        (repr(token), f"({start},{end})", repr(OFFSET_SENTENCE[start:end]))
        for token, (start, end) in zip(encoded.tokens, encoded.offsets)
    ]


def budget_line(tokenizer, corpus):
    """Token budget for a paragraph, and the chunking that `overflowing` will not give you.

    `enable_truncation` drops the tail and leaves `Encoding.overflowing` empty, so windows
    over a long document have to come from slicing the id list. The line reports whether
    the windows rejoin to the original ids and whether decoding them rejoins to the text.
    """
    text = " ".join(corpus[:20])
    ids = tokenizer.encode(text).ids
    windows = [ids[start : start + WINDOW] for start in range(0, len(ids), WINDOW)]
    rejoined = [token for window in windows for token in window] == ids
    same_text = "".join(tokenizer.decode(window) for window in windows) == text
    return (
        f"paragraph: {len(text):,} chars · {len(ids):,} tokens · "
        f"{len(text) / len(ids):.1f} chars/token · {len(windows)} windows of {WINDOW} · "
        f"ids rejoin {'yes' if rejoined else 'NO'} · "
        f"text rejoins {'yes' if same_text else 'NO'}"
    )


def reload_line(tokenizer):
    """Read the saved file back and report whether the reloaded tokenizer agrees, in one line.

    Everything `tokenizers` raises is a bare `Exception`, file errors included, so
    `except OSError` would miss a missing or corrupt file entirely.
    """
    try:
        reloaded = Tokenizer.from_file(STORE)
        agree = sum(
            reloaded.encode(text).ids == tokenizer.encode(text).ids for text in PROBES
        )
        return (
            f"reloaded {os.path.getsize(STORE):,} B from {STORE} · "
            f"identical ids on {agree}/{len(PROBES)} probes"
        )
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def table_row(values, weights, size=11):
    """One row of a table: a `Text` per value, laid out by weight so it fits a phone."""
    return ft.Row(
        controls=[
            ft.Text(value, size=size, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Train a tokenizer on device, then show what it can and cannot tell you about text.

    The slider picks how much text to train on; releasing it retrains. Everything below the
    stats line is computed with the tokenizer that just came out of the trainer: whether the
    round trip is lossless for text the corpus never contained, what a paragraph costs in
    tokens, where each token sits in its source string, and whether the copy written to app
    storage reloads to the same ids. No model is downloaded and no asset is bundled.
    """
    trained = None

    def show_size():
        """Report the corpus size the next run will use, as the slider moves."""
        caption.value = f"{SIZES[int(size.value)]:,} lines of generated text"

    def start():
        """Hand one training run to a background thread and lock the slider while it works.

        Driven by the slider's on_change_end, which fires once on release, so one gesture
        means one run. The guard is tested and set here rather than in the worker: this
        body is synchronous where `run_thread` only schedules, so a `disabled` set inside
        the worker would not have taken effect before Flet pushed the control states.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Train, then rebuild every panel from the tokenizer that came out.

        Worth a thread: `train_from_iterator` genuinely releases the GIL, unlike a single
        `encode`. The `try/except` is not optional — `page.run_thread` discards whatever a
        worker raises, so an error in here would look like a screen that stopped updating —
        and the panels are cleared on the way out so the previous run's rows cannot sit
        under this run's error message.
        """
        nonlocal trained
        try:
            corpus = make_corpus(SIZES[int(size.value)])
            tokenizer, elapsed = train(corpus)
            if not tokenizer.get_vocab_size():
                raise RuntimeError("training produced an empty vocabulary")
            trained = tokenizer

            stats.value = (
                f"{len(corpus):,} lines · {sum(map(len, corpus)):,} chars · "
                f"trained in {elapsed:,.0f} ms · vocabulary {tokenizer.get_vocab_size():,} "
                f"of the {VOCAB_SIZE:,} asked for (corpus variety is the real cap) · "
                f"saved {save(tokenizer):,} B"
            )
            trips.controls = [
                table_row(("probe string", "tokens", "decode", "lookup"), TRIP_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(row, TRIP_WEIGHTS) for row in trip_rows(tokenizer)),
            ]
            budget.value = budget_line(tokenizer, corpus)
            offsets.controls = [
                table_row(("token", "offsets", "source[a:b]"), OFFSET_WEIGHTS),
                ft.Divider(height=1),
                *(table_row(row, OFFSET_WEIGHTS) for row in offset_rows(tokenizer)),
            ]
            storage.value = reload_line(tokenizer)
        except Exception as error:
            trained = None
            trips.controls = []
            offsets.controls = []
            stats.value = budget.value = ""
            storage.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def reload_only():
        """Re-read the saved file without retraining, so `from_file` is exercisable alone.

        It is handed the tokenizer still in memory, and that is the whole point: `reload_line`
        opens the file itself, so passing it a second `from_file` of the same path would
        compare the file against itself and report a perfect match whatever is on disk.
        """
        storage.value = (
            reload_line(trained)
            if trained is not None
            else "nothing trained yet to compare against"
        )

    page.appbar = ft.AppBar(
        title=ft.Text("tokenizers train and count"), center_title=True
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"tokenizers {tokenizers.__version__} · "
                        f"Python {platform.python_version()} · {page.platform.value} · "
                        f"native {native_origin()}",
                        size=11,
                    ),
                    ft.Text(
                        f"huggingface_hub {hub_version()} — installed as a dependency, "
                        "never called: nothing here is downloaded",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=0,
                        max=len(SIZES) - 1,
                        value=2,
                        divisions=len(SIZES) - 1,
                        on_change=show_size,
                        on_change_end=start,
                    ),
                    stats := ft.Text(size=11),
                    ft.Divider(),
                    trips := ft.Column(spacing=2),
                    budget := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text(
                        f"offsets for {OFFSET_SENTENCE!r} — a multi-byte character gives "
                        "several tokens the same range",
                        size=11,
                    ),
                    offsets := ft.Column(spacing=2),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            ft.Button(
                                "Reload from disk",
                                icon=ft.Icons.REFRESH,
                                on_click=reload_only,
                            )
                        ]
                    ),
                    storage := ft.Text(size=11),
                ],
            ),
        )
    )

    show_size()
    start()


if __name__ == "__main__":
    ft.run(main)
