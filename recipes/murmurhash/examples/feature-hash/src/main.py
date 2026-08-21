import flet as ft
from hashing import (
    BITS,
    HOT,
    VERSION,
    corpus,
    probe,
    stability,
    table,
    throughput,
    vectorize,
    with_vocabulary,
)

LABELS = {12: "4K", 14: "16K", 16: "64K", 18: "256K"}


def row(label, value):
    """One line of a panel: a label on the left, a measured value on the right."""
    return ft.Row(
        controls=[
            ft.Text(label, expand=5, size=12),
            ft.Text(value, expand=4, size=12, weight=ft.FontWeight.BOLD),
        ]
    )


def heading(text):
    """A section title for one of the panels below the collision table."""
    return ft.Text(text, size=12, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Hash a generated corpus once, before anything on screen is touched.

    The vocabulary is built from the training documents and then asked about the
    held-out ones, which is where hashing earns its keep: it has an answer for a word
    it has never seen.
    """
    train, held_out = corpus()

    def run(event=None):
        """Lock the picker and hand the whole pass to a background thread."""
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Fill the collision table at the chosen width, and the panels below once.

        The body is wrapped because page.run_thread swallows exceptions: a raise here
        would otherwise leave the picker disabled and the spinner turning forever.
        Only the first panel depends on the width, so the other two are measured once —
        recomputing them per press would jitter numbers the width cannot affect.
        """
        try:
            bits = int(picker.selected[0])
            stats = table(train, bits)
            _, hashed_ms = vectorize(train, bits)
            hashed.controls = [
                row("buckets", f"{stats['buckets']:,}"),
                row("distinct features", f"{stats['features']:,}"),
                row("sharing a bucket", f"{stats['collided']:.1f}%"),
                row(f"{HOT} most frequent, with each other", f"{stats['hot']:.0f}%"),
                row("fullest bucket", f"{stats['fullest']} features"),
                row("one collision", " + ".join(stats["example"])),
                row("corpus vectorised in", f"{hashed_ms:.0f} ms"),
            ]
            if not vocab.controls:
                elapsed, _, footprint, unseen = with_vocabulary(train, held_out)
                counted, murmur_ms, blake_ms = throughput(train)
                vocab.controls = [
                    row("built and vectorised in", f"{elapsed:.0f} ms"),
                    row("dict and its keys", f"{footprint / 1e6:.2f} MB"),
                    row("unseen in the held-out 200", f"{unseen:.0f}%"),
                ]
                other.controls = [
                    *(row(*entry) for entry in stability()),
                    row(f"{counted:,} features hashed", f"{murmur_ms:.1f} ms"),
                    row("the same through BLAKE2b", f"{blake_ms:.1f} ms"),
                ]
            typed(None)
        except Exception as error:
            hashed.controls = [ft.Text(f"{type(error).__name__}: {error}", size=12)]
        finally:
            picker.disabled = False
            spinner.visible = False
            page.update()  # auto-update does not reach background threads

    def typed(event):
        """Hash the field's text and show where it lands at the chosen width.

        One call, so it stays on the UI thread: this is the whole reason the trick
        works on a phone at all — a column index costs a function call, not a lookup
        in a table that has to be built and carried first.
        """
        value, index, sign = probe(field.value, int(picker.selected[0]))
        landing.value = f"{value}  →  bucket {index:,}, sign {sign:+d}"
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("Feature hash"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    picker := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=str(b), label=ft.Text(LABELS[b]))
                            for b in BITS
                        ],
                        selected=[str(BITS[-1])],  # a list in Flet 0.86, not a set
                        show_selected_icon=False,
                        on_change=run,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text("buckets in the vector", size=11, expand=True),
                            spinner := ft.ProgressRing(
                                width=14, height=14, visible=False
                            ),
                        ]
                    ),
                    hashed := ft.Column(spacing=4),
                    ft.Divider(),
                    heading("The same corpus with a vocabulary dict"),
                    vocab := ft.Column(spacing=4),
                    ft.Divider(),
                    heading("Why not the builtin hash, or a real one?"),
                    other := ft.Column(spacing=4),
                    ft.Divider(),
                    field := ft.TextField(
                        label="Hash any text",
                        value="apple",
                        dense=True,
                        on_change=typed,
                    ),
                    landing := ft.Text(size=12),
                ],
            ),
        )
    )

    run()


if __name__ == "__main__":
    ft.run(main)
