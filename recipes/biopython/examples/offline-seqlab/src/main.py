"""A sequence lab that runs entirely on the device: parse, translate, align, benchmark.

Every checked answer sits next to one derived independently — a plain-Python codon table,
school arithmetic, or a published textbook score — so the first four panels state a
verdict instead of a number you would have to take on trust; the fifth measures rather
than checks, and its number is the point. Each panel also catches its
own exceptions and prints them, which is what turns a missing Android `extract_packages`
entry into a readable `NotADirectoryError` on one row rather than a blank screen.
"""

import itertools
import os
import random
import time

import flet as ft
from Bio import Align, SeqIO, SeqUtils
from Bio.Align import substitution_matrices
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

DATA = os.getenv("FLET_APP_STORAGE_DATA") or "."
FASTA = os.path.join(DATA, "sequences.fasta")

RECORDS = [
    ("seq1", "thirteen codons, no stop", "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTG"),
    ("seq2", "stops at codon eight", "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG"),
    ("seq3", "", "ATGAAACGCATTAGCACCACCATTACCACCACCATCACC"),
    ("seq4", "six codons", "ATGTGCACCGGTAAATAA"),
]

# NCBI translation table 1, written out by hand. Listing the bases in TCAG order is what
# makes the amino acids line up positionally with itertools.product — the layout every
# reference that prints this table uses.
_BASES = "TCAG"
_AMINO_ACIDS = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODON_TABLE = {
    "".join(codon): amino
    for codon, amino in zip(itertools.product(_BASES, repeat=3), _AMINO_ACIDS)
}

# Gaps priced far above a mismatch, so the optimal alignment of these two equal-length
# sequences cannot contain one and its score is plain arithmetic.
DNA_PAIR = ("GATTACA", "GATCACA")
MATCH, MISMATCH, GAP = 2, -1, -10

# Durbin et al., Biological Sequence Analysis (1998), section 2.3: this pair under
# BLOSUM50 with a linear gap cost of 8 scores 1 globally and 28 locally.
DURBIN = ("HEAGAWGHEE", "PAWHEAE")


def hand_translate(dna):
    """Translate whole codons with the table above — the check on `Seq.translate`."""
    end = len(dna) - len(dna) % 3
    return "".join(CODON_TABLE[dna[i : i + 3]] for i in range(0, end, 3))


def hand_gc(dna):
    """(G+C)/length, the definition `SeqUtils.gc_fraction` is checked against."""
    return (dna.count("G") + dna.count("C")) / len(dna)


def describe(aligner, scoring):
    """One line naming the mode, algorithm and gap costs an aligner actually used."""
    return (
        f"{aligner.mode} / {aligner.algorithm} · {scoring} "
        f"open={aligner.open_gap_score:g} extend={aligner.extend_gap_score:g}"
    )


def round_trip():
    """Write the records to a FASTA in app storage and read them straight back.

    The file is the point: `SeqIO.write` and `SeqIO.parse` have to agree through a real
    path on the device's own filesystem, not through an in-memory handle. FASTA has no
    separate description field — the title line is `id description` — so that is what a
    parsed record's `description` is compared against.
    """
    written = [
        SeqRecord(Seq(seq), id=name, description=desc) for name, desc, seq in RECORDS
    ]
    SeqIO.write(written, FASTA, "fasta")
    read = list(SeqIO.parse(FASTA, "fasta"))
    ok = len(read) == len(RECORDS) and all(
        got.id == name
        and got.description == f"{name} {desc}".strip()
        and str(got.seq) == seq
        for got, (name, desc, seq) in zip(read, RECORDS)
    )
    return (
        f"{'PASS' if ok else 'FAIL'}  {len(read)}/{len(RECORDS)} records survived a "
        f"write and re-parse of {os.path.getsize(FASTA)} bytes\n{FASTA}"
    )


def per_record():
    """GC fraction and translation per record, biopython's answer beside the hand one."""
    lines = [f"{'id':<6}{'GC':>10}{'by hand':>10}  protein"]
    for name, _desc, seq in RECORDS:
        gc, gc_hand = SeqUtils.gc_fraction(seq), hand_gc(seq)
        protein, protein_hand = str(Seq(seq).translate()), hand_translate(seq)
        ok = abs(gc - gc_hand) < 1e-12 and protein == protein_hand
        verdict = "=" if ok else f"DIFFERS, by hand {protein_hand}"
        lines.append(f"{name:<6}{gc:>10.6f}{gc_hand:>10.6f}  {protein}  {verdict}")
    return "\n".join(lines)


def gap_free_check():
    """Score a same-length pair whose optimal alignment cannot contain a gap.

    Six identical columns and one mismatch, so the answer is 6x2 + 1x(-1) with no
    alignment theory involved — and the printed alignment shows the single `.` column
    the arithmetic assumed.
    """
    aligner = Align.PairwiseAligner(
        mode="global",
        match_score=MATCH,
        mismatch_score=MISMATCH,
        open_gap_score=GAP,
        extend_gap_score=GAP,
    )
    started = time.perf_counter()
    score = aligner.score(*DNA_PAIR)
    ms = (time.perf_counter() - started) * 1e3
    hand = 6 * MATCH + 1 * MISMATCH
    scoring = f"match={MATCH:g} mismatch={MISMATCH:g}"
    return (
        f"{'PASS' if score == hand else 'FAIL'}  {DNA_PAIR[0]} vs {DNA_PAIR[1]}: "
        f"biopython {score:g}, hand 6x{MATCH:g} + 1x{MISMATCH:g} = {hand:g}"
        f"   {ms:.3f} ms\n{describe(aligner, scoring)}\n{aligner.align(*DNA_PAIR)[0]}"
    )


def durbin_check():
    """Score the textbook BLOSUM50 pair globally and locally against published values.

    This is the only panel that loads a substitution matrix, so on Android it is the one
    that fails without `[tool.flet.android] extract_packages = ["Bio"]`: the matrices are
    read through a real `__file__` path that `sitepackages.zip` cannot serve.
    """
    matrix = substitution_matrices.load("BLOSUM50")
    lines = []
    for mode, published in (("global", 1.0), ("local", 28.0)):
        aligner = Align.PairwiseAligner(
            mode=mode,
            substitution_matrix=matrix,
            open_gap_score=-8,
            extend_gap_score=-8,
        )
        started = time.perf_counter()
        score = aligner.score(*DURBIN)
        ms = (time.perf_counter() - started) * 1e3
        lines.append(
            f"{'PASS' if score == published else 'FAIL'}  {DURBIN[0]} vs {DURBIN[1]} "
            f"{mode}: biopython {score:g}, Durbin et al. 1998 {published:g}"
            f"   {ms:.3f} ms\n{describe(aligner, 'matrix=BLOSUM50')}"
        )
    return "\n".join(lines)


def random_pair(length, seed=0):
    """A random DNA sequence of `length` and a copy mutated at 5% of its positions."""
    rng = random.Random(seed)
    first = "".join(rng.choices("ACGT", k=length))
    second = list(first)
    for i in rng.sample(range(length), length // 20):
        second[i] = "ACGT"["ACGT".index(second[i]) - 1]
    return first, "".join(second)


def main(page: ft.Page):
    """Five panels of biopython output, each checked and each guarding its own failure.

    Four are computed once at startup; only the benchmark re-runs, off the slider.
    """

    def benchmark():
        """Time one `PairwiseAligner.score` call at the slider's length, off the UI thread.

        biopython never releases the GIL during an alignment, so the thread pool buys no
        concurrency here — it keeps the pattern honest for a real app, and the measured
        milliseconds are exactly how long the Python side is frozen for.
        """
        try:
            length = int(size.value)
            first, second = random_pair(length)
            aligner = Align.PairwiseAligner(
                mode="global",
                match_score=2,
                mismatch_score=-1,
                open_gap_score=-2,
                extend_gap_score=-0.5,
            )
            started = time.perf_counter()
            score = aligner.score(first, second)
            ms = (time.perf_counter() - started) * 1e3
            timing.value = (
                f"{length} nt vs {length} nt at 5% divergence: "
                f"score {score:g} in {ms:.1f} ms\n"
                f"{describe(aligner, 'match=2 mismatch=-1')}"
            )
        except Exception as exc:
            timing.value = f"{type(exc).__name__}: {exc}"
        page.update()  # auto-update does not reach background threads

    def rerun():
        """Recompute on on_change_end, so a drag does not queue one alignment per pixel."""
        page.run_thread(benchmark)

    def fill(target, work):
        """Run one panel's work and show either its text or the exception it raised.

        Every panel gets this: an unhandled exception in a Flet handler ends the session
        with a crash screen, which would hide both which panel failed and why.
        """
        try:
            target.value = work()
        except Exception as exc:
            target.value = f"{type(exc).__name__}: {exc}"

    mono = dict(
        size=11,
        font_family="monospace",
        font_family_fallback=["Courier"],
        selectable=True,
    )
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
                    fasta := ft.Text(**mono),
                    ft.Divider(),
                    ft.Text("GC and translation, checked by hand", weight=bold),
                    records := ft.Text(**mono),
                    ft.Divider(),
                    ft.Text("Alignment score, checked by arithmetic", weight=bold),
                    gapfree := ft.Text(**mono),
                    ft.Divider(),
                    ft.Text(
                        "Alignment scores, checked against a textbook", weight=bold
                    ),
                    durbin := ft.Text(**mono),
                    ft.Divider(),
                    ft.Text("How long one alignment takes on this device", weight=bold),
                    size := ft.Slider(
                        min=200,
                        max=4000,
                        divisions=19,
                        value=1000,
                        label="{value} nt",
                        on_change_end=rerun,
                    ),
                    timing := ft.Text("measuring…", **mono),
                ],
            ),
        )
    )

    # After page.add, so the walrus-bound controls above exist.
    fill(fasta, round_trip)
    fill(records, per_record)
    fill(gapfree, gap_free_check)
    fill(durbin, durbin_check)
    page.run_thread(benchmark)


if __name__ == "__main__":
    ft.run(main)
