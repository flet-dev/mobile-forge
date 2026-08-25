import itertools
import os
import random
import time

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
MATCHED_COLUMNS, MISMATCHED_COLUMNS = 6, 1

# Durbin et al., Biological Sequence Analysis (1998), section 2.3: this pair under
# BLOSUM50 with a linear gap cost of 8 scores 1 globally and 28 locally.
DURBIN_PAIR = ("HEAGAWGHEE", "PAWHEAE")
DURBIN_PUBLISHED = (("global", 1.0), ("local", 28.0))
DURBIN_GAP = -8


def hand_gc(dna):
    """(G+C)/length, the definition `SeqUtils.gc_fraction` is checked against."""
    return (dna.count("G") + dna.count("C")) / len(dna)


def hand_translate(dna):
    """Translate whole codons with the table above — the check on `Seq.translate`."""
    end = len(dna) - len(dna) % 3
    return "".join(CODON_TABLE[dna[i : i + 3]] for i in range(0, end, 3))


def describe(aligner, scoring):
    """Name the mode, the algorithm and the gap costs an aligner actually used.

    `algorithm` is the interesting one: the same PairwiseAligner is Needleman-Wunsch,
    Gotoh or Smith-Waterman depending on the mode and gap costs it was handed, and
    nothing else on screen says which one produced the score.
    """
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

    Returns how many records were written, how many came back, the size of the file on
    disk, and whether every id, description and sequence survived.
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
    return len(written), len(read), os.path.getsize(FASTA), ok


def gc_and_translation():
    """Per record, biopython's GC fraction and protein beside the hand-computed pair.

    `gc_fraction` returns a *fraction*; the old `SeqUtils.GC`, which returned a
    percentage, no longer exists. Yields one row of `(id, gc, gc by hand, protein,
    protein by hand, agree)`.
    """
    for name, _desc, seq in RECORDS:
        gc, gc_hand = SeqUtils.gc_fraction(seq), hand_gc(seq)
        protein, protein_hand = str(Seq(seq).translate()), hand_translate(seq)
        ok = abs(gc - gc_hand) < 1e-12 and protein == protein_hand
        yield name, gc, gc_hand, protein, protein_hand, ok


def gap_free_alignment():
    """Score a same-length pair whose optimal alignment cannot contain a gap.

    Six identical columns and one mismatch, so the answer is 6x2 + 1x(-1) with no
    alignment theory involved. Returns biopython's score, the hand arithmetic, the
    milliseconds it took, the aligner's own settings line, and the printed alignment —
    which shows the single `.` column the arithmetic assumed.
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
    hand = MATCHED_COLUMNS * MATCH + MISMATCHED_COLUMNS * MISMATCH
    scoring = f"match={MATCH:g} mismatch={MISMATCH:g}"
    return score, hand, ms, describe(aligner, scoring), aligner.align(*DNA_PAIR)[0]


def textbook_alignments():
    """Score the textbook BLOSUM50 pair globally and locally against published values.

    This is the only panel that loads a substitution matrix, so on Android it is the one
    that fails without `[tool.flet.android] extract_packages = ["Bio"]`: matrices are
    read through a real `__file__` path that `sitepackages.zip` cannot serve. Yields one
    row of `(mode, score, published score, milliseconds, settings line)`.
    """
    matrix = substitution_matrices.load("BLOSUM50")
    for mode, published in DURBIN_PUBLISHED:
        aligner = Align.PairwiseAligner(
            mode=mode,
            substitution_matrix=matrix,
            open_gap_score=DURBIN_GAP,
            extend_gap_score=DURBIN_GAP,
        )
        started = time.perf_counter()
        score = aligner.score(*DURBIN_PAIR)
        ms = (time.perf_counter() - started) * 1e3
        yield mode, score, published, ms, describe(aligner, "matrix=BLOSUM50")


def random_pair(length, seed=0):
    """A random DNA sequence of `length` and a copy mutated at 5% of its positions."""
    rng = random.Random(seed)
    first = "".join(rng.choices("ACGT", k=length))
    second = list(first)
    for i in rng.sample(range(length), length // 20):
        second[i] = "ACGT"["ACGT".index(second[i]) - 1]
    return first, "".join(second)


def time_alignment(length):
    """Time one `PairwiseAligner.score` call on a fresh random pair of that length.

    biopython holds the GIL for the whole call, so these milliseconds are exactly how
    long the Python side is frozen for — running it in a thread buys no concurrency,
    only the right structure. Returns the score, the milliseconds and the settings line.
    """
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
    return score, ms, describe(aligner, "match=2 mismatch=-1")
