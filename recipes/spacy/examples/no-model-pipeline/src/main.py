import flet as ft
from pipeline import PREVIEW_ENTITIES, PREVIEW_TOKENS, VERSION, analyse


def audit(a):
    """The five checks as (label, agrees, what was measured), ready to put on screen."""
    return [
        (
            "Reconstruction",
            a.token_residual == 0,
            f"residual {a.token_residual} against {a.chars:,} source chars",
        ),
        (
            "Sentence partition",
            a.sentence_residual == 0,
            f"{a.n_sentences} sentences, residual {a.sentence_residual}",
        ),
        (
            "Offset round trip",
            a.n_misplaced == 0,
            f"{a.n_entities} spans re-sliced to their pattern, {a.n_misplaced} wrong",
        ),
        (
            "EntityRuler vs re.finditer",
            a.regex_agrees,
            f"{a.n_entities} spaCy spans against {a.n_regex} regex spans",
        ),
        (
            "PhraseMatcher(attr='LOWER')",
            a.n_lowered == a.n_regex,
            f"{a.n_lowered} of {a.n_regex} — 'corp.' tokenises unlike 'Corp.'",
        ),
    ]


def verdict(label, ok, detail):
    """One audit line: a colour-coded badge, then the number behind it."""
    return ft.Row(
        controls=[
            ft.Text(
                "AGREE" if ok else "DISAGREE",
                color=ft.Colors.GREEN if ok else ft.Colors.ORANGE,
                weight=ft.FontWeight.BOLD,
                size=12,
                width=88,
            ),
            ft.Text(f"{label} — {detail}", size=12, expand=True),
        ]
    )


def main(page: ft.Page):
    """One screen: a model-free pipeline auditing itself over a document you can scale.

    The slider decides how many copies of the sample document to concatenate, so the
    per-document cost and spaCy's own memory pool are read across a range rather than at
    one point. The header says what is loaded against what merely exists.
    """

    def render(a):
        """Move one Analysis onto the controls, without updating the page itself.

        The caller owns the update, because this runs on a worker thread where Flet's
        auto-update does not reach.
        """
        checks.controls = [verdict(*row) for row in audit(a)]
        stats.value = (
            f"{a.chars:,} chars, {a.tokens:,} tokens, {a.ms:.2f} ms/doc, "
            f"doc.mem.size {a.mem:,} bytes"
        )
        word, pos, tag, lemma, dep = a.first
        statistical.value = (
            f"first token {word!r}: pos_={pos!r} tag_={tag!r} "
            f"lemma_={lemma!r} dep_={dep!r}"
        )
        sentences.value = "\n".join(f"· {s}" for s in a.sentences)
        entities.value = "\n".join(
            f"{label} {span!r} [{start}:{end}]"
            for label, span, start, end in a.entities
        ) + (f"\n… {a.n_entities} in total" if a.n_entities > PREVIEW_ENTITIES else "")
        tokens.value = "\n".join(
            f"{i:>3} {tok!r} idx={idx} shape={shape} {','.join(flags) or '-'}"
            for i, tok, idx, shape, flags in a.token_rows
        ) + (f"\n… {a.tokens} in total" if a.tokens > PREVIEW_TOKENS else "")

    def recompute():
        """Re-run the analysis off the UI thread and redraw.

        page.run_thread never retrieves the worker's future, so an exception here would
        vanish silently — hence the broad guard, which also covers the ValueError
        subclasses spaCy raises for its own error codes.
        """
        try:
            render(analyse(int(copies.value)))
        except Exception as exc:
            stats.value = f"{type(exc).__name__}: {exc}"
        page.update()

    def rerun():
        """Slider release: recomputing on every drag frame would be far too much."""
        page.run_thread(recompute)

    page.appbar = ft.AppBar(title=ft.Text("spaCy without a model"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                controls=[
                    ft.Text(VERSION, size=12),
                    ft.Text(
                        "No model, no download, no data file — the rest need one.",
                        size=12,
                        italic=True,
                    ),
                    ft.Divider(),
                    checks := ft.Column(spacing=2),
                    stats := ft.Text(size=12, selectable=True),
                    ft.Divider(),
                    ft.Text("Statistical attributes come back empty", size=12),
                    statistical := ft.Text(size=11, selectable=True),
                    ft.Divider(),
                    copies := ft.Slider(
                        min=1,
                        max=64,
                        divisions=63,
                        value=1,
                        label="{value} copies",
                        on_change_end=rerun,
                    ),
                    ft.Text("Sentences", weight=ft.FontWeight.BOLD, size=12),
                    sentences := ft.Text(size=11, selectable=True),
                    ft.Text("Entities", weight=ft.FontWeight.BOLD, size=12),
                    entities := ft.Text(size=11, selectable=True),
                    ft.Text("Tokens", weight=ft.FontWeight.BOLD, size=12),
                    tokens := ft.Text(size=11, selectable=True),
                ],
            ),
        )
    )

    page.run_thread(recompute)


if __name__ == "__main__":
    ft.run(main)
