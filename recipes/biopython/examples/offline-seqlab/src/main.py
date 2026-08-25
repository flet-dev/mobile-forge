import flet as ft
from sequences import (
    DNA_PAIR,
    DURBIN_PAIR,
    FASTA,
    MATCH,
    MATCHED_COLUMNS,
    MISMATCH,
    MISMATCHED_COLUMNS,
    gap_free_alignment,
    gc_and_translation,
    round_trip,
    textbook_alignments,
    time_alignment,
)

MONO = dict(
    size=11,
    font_family="monospace",
    font_family_fallback=["Courier"],
    selectable=True,
)


def verdict(ok):
    """The word every checked panel opens with."""
    return "PASS" if ok else "FAIL"


def fasta_panel():
    """The round-trip verdict, the size of the file, and the path it went through."""
    written, read, size, ok = round_trip()
    return (
        f"{verdict(ok)}  {read}/{written} records survived a write and re-parse of "
        f"{size} bytes\n{FASTA}"
    )


def records_panel():
    """A row per record: biopython's GC and protein beside the hand-computed pair."""
    lines = [f"{'id':<6}{'GC':>10}{'by hand':>10}  protein"]
    for name, gc, gc_hand, protein, protein_hand, ok in gc_and_translation():
        agreement = "=" if ok else f"DIFFERS, by hand {protein_hand}"
        lines.append(f"{name:<6}{gc:>10.6f}{gc_hand:>10.6f}  {protein}  {agreement}")
    return "\n".join(lines)


def arithmetic_panel():
    """The gap-free score against the arithmetic, over the alignment it came from."""
    score, hand, ms, settings, alignment = gap_free_alignment()
    first, second = DNA_PAIR
    return (
        f"{verdict(score == hand)}  {first} vs {second}: biopython {score:g}, hand "
        f"{MATCHED_COLUMNS}x{MATCH:g} + {MISMATCHED_COLUMNS}x{MISMATCH:g} = {hand:g}"
        f"   {ms:.3f} ms\n{settings}\n{alignment}"
    )


def textbook_panel():
    """One row per mode: biopython's score against the published one."""
    first, second = DURBIN_PAIR
    return "\n".join(
        f"{verdict(score == published)}  {first} vs {second} {mode}: biopython "
        f"{score:g}, Durbin et al. 1998 {published:g}   {ms:.3f} ms\n{settings}"
        for mode, score, published, ms, settings in textbook_alignments()
    )


def main(page: ft.Page):
    """Five panels of biopython output, each checked and each guarding its own failure.

    Four are computed once at startup; only the benchmark re-runs, off the slider.
    """

    def measure():
        """Time one alignment at the slider's length, off the UI thread."""
        try:
            length = int(size.value)
            score, ms, settings = time_alignment(length)
            timing.value = (
                f"{length} nt vs {length} nt at 5% divergence: score {score:g} "
                f"in {ms:.1f} ms\n{settings}"
            )
        except Exception as exc:
            timing.value = f"{type(exc).__name__}: {exc}"
        page.update()  # auto-update does not reach background threads

    def rerun():
        """Re-measure on release, so a drag does not queue one alignment per pixel."""
        page.run_thread(measure)

    def fill(target, panel):
        """Run one panel's work and show either its text or the exception it raised.

        Every panel gets this: an unhandled exception in a Flet handler ends the session
        with a crash screen, which would hide both which panel failed and why.
        """
        try:
            target.value = panel()
        except Exception as exc:
            target.value = f"{type(exc).__name__}: {exc}"

    bold = ft.FontWeight.BOLD
    page.appbar = ft.AppBar(title=ft.Text("Offline seqlab"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text("FASTA round trip through app storage", weight=bold),
                    fasta := ft.Text(**MONO),
                    ft.Divider(),
                    ft.Text("GC and translation, checked by hand", weight=bold),
                    records := ft.Text(**MONO),
                    ft.Divider(),
                    ft.Text("Alignment score, checked by arithmetic", weight=bold),
                    gapfree := ft.Text(**MONO),
                    ft.Divider(),
                    ft.Text(
                        "Alignment scores, checked against a textbook", weight=bold
                    ),
                    durbin := ft.Text(**MONO),
                    ft.Divider(),
                    ft.Text("How long one alignment takes on this device", weight=bold),
                    size := ft.Slider(
                        min=200,
                        max=4000,
                        divisions=19,
                        value=1000,
                        label="{value} nt",
                        # on_change would queue an alignment for every pixel the thumb
                        # travels; on_change_end runs one, on release.
                        on_change_end=rerun,
                    ),
                    timing := ft.Text("measuring…", **MONO),
                ],
            ),
        )
    )

    # After page.add, so the walrus-bound controls above exist.
    fill(fasta, fasta_panel)
    fill(records, records_panel)
    fill(gapfree, arithmetic_panel)
    fill(durbin, textbook_panel)
    page.run_thread(measure)


if __name__ == "__main__":
    ft.run(main)
