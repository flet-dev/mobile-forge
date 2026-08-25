import platform

import flet as ft
import tokenizers
import tokens

PROBE_WEIGHTS = (9, 3, 3, 4)
OFFSET_WEIGHTS = (4, 4, 4)


def cells(values, weights):
    """One line of a table: a `Text` per value, laid out by weight to fit a phone."""
    return ft.Row(
        controls=[ft.Text(v, size=11, expand=w) for v, w in zip(values, weights)]
    )


def verdict(passed):
    """A boolean check as a table cell."""
    return "PASS" if passed else "FAIL"


def main(page: ft.Page):
    """Train a tokenizer on device, then show what it can and cannot say about text.

    The slider picks how much text to train on; releasing it retrains. Everything
    below the stats line is computed with the tokenizer that came out of the trainer.
    """
    trained = None
    banner = (
        f"tokenizers {tokenizers.__version__} · Python {platform.python_version()} · "
        f"{page.platform.value} · native {tokens.native_origin()} · huggingface_hub "
        f"{tokens.hub_version()}, a dependency of the wheel that nothing here calls"
    )

    def show_size():
        """Report the corpus size the next run will use, as the slider moves."""
        caption.value = f"{tokens.SIZES[int(size.value)]:,} lines of generated text"

    def start():
        """Lock the slider and hand one training run to a background thread.

        The guard is set here, not in the worker: this body is synchronous where
        `run_thread` only schedules.
        """
        if size.disabled:
            return
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Train, then rebuild every panel from the tokenizer that came out.

        The `try/except` is not optional — `run_thread` discards whatever a worker
        raises — and the panels are cleared so an old run's rows cannot sit under a
        new run's error.
        """
        nonlocal trained
        try:
            corpus = tokens.make_corpus(tokens.SIZES[int(size.value)])
            tokenizer, elapsed = tokens.train(corpus)
            trained = tokenizer
            stats.value = (
                f"{len(corpus):,} lines · {sum(map(len, corpus)):,} chars · trained in "
                f"{elapsed:,.0f} ms · vocabulary {tokenizer.get_vocab_size():,} of the "
                f"{tokens.VOCAB_SIZE:,} asked for (corpus variety is the real cap) · "
                f"saved {tokens.save(tokenizer):,} B"
            )
            probes.controls = [
                cells(("probe string", "tokens", "decode", "lookup"), PROBE_WEIGHTS),
                ft.Divider(height=1),
                *(
                    cells((repr(t), f"{n} tok", verdict(d), verdict(v)), PROBE_WEIGHTS)
                    for t, n, d, v in tokens.probe_rows(tokenizer)
                ),
            ]
            chars, ids, windows, rejoin, retext = tokens.budget(tokenizer, corpus)
            budget.value = (
                f"paragraph: {chars:,} chars · {ids:,} tokens · {chars / ids:.1f} "
                f"chars/token · {windows} windows of {tokens.WINDOW} · ids rejoin "
                f"{'yes' if rejoin else 'NO'} · text rejoins "
                f"{'yes' if retext else 'NO'}"
            )
            offsets.controls = [
                cells(("token", "offsets", "source[a:b]"), OFFSET_WEIGHTS),
                ft.Divider(height=1),
                *(
                    cells((repr(t), f"({a},{b})", repr(s)), OFFSET_WEIGHTS)
                    for t, a, b, s in tokens.offset_rows(tokenizer)
                ),
            ]
            storage.value = storage_line(tokenizer)
        except Exception as error:
            trained = None
            probes.controls = []
            offsets.controls = []
            stats.value = budget.value = ""
            storage.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def storage_line(tokenizer):
        """Reload the saved file and describe what came back, or the error it raised.

        Broad `Exception` because that is all `tokenizers` ever raises, file errors
        included: `except OSError` would miss a missing or corrupt file entirely.
        """
        try:
            written, agree, total = tokens.reload(tokenizer)
            return (
                f"reloaded {written:,} B from {tokens.STORE} · "
                f"identical ids on {agree}/{total} probes"
            )
        except Exception as error:
            return f"{type(error).__name__}: {error}"

    def reload_only():
        """Re-read the saved file without retraining, so `from_file` runs alone."""
        storage.value = (
            storage_line(trained)
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
                    ft.Text(banner, size=11),
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
                        max=len(tokens.SIZES) - 1,
                        value=2,
                        divisions=len(tokens.SIZES) - 1,
                        on_change=show_size,
                        on_change_end=start,
                    ),
                    stats := ft.Text(size=11),
                    ft.Divider(),
                    probes := ft.Column(spacing=2),
                    budget := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text(
                        f"offsets for {tokens.OFFSET_SENTENCE!r} — a multi-byte "
                        "character gives several tokens the same range",
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
