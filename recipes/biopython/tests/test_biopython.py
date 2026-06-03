def test_seq_basics():
    """`Bio.Seq` is pure-Python — this test mainly catches import-path or
    package-data regressions in the wheel (e.g. a missing submodule)."""
    from Bio.Seq import Seq

    s = Seq("ATGCGT")
    # Reverse complement of ATGCGT is ACGCAT.
    assert str(s.reverse_complement()) == "ACGCAT"
    # Length is the same after complement (no IUPAC ambiguity here).
    assert len(s.complement()) == 6


def test_seqio_roundtrip():
    """SeqIO parses FASTA via a text stream — verifies the parser graph
    is intact (Bio.SeqIO.FastaIO + Bio.SeqRecord + Bio.Seq all importable
    and wired)."""
    from io import StringIO

    from Bio import SeqIO

    fasta = ">seq1\nATGCGTAA\n>seq2\nTTTAGCAT\n"
    records = list(SeqIO.parse(StringIO(fasta), "fasta"))
    assert len(records) == 2
    assert records[0].id == "seq1"
    assert str(records[0].seq) == "ATGCGTAA"
    assert str(records[1].seq) == "TTTAGCAT"
