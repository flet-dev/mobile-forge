"""The spaCy half of the example: one blank pipeline, and one audited pass over text.

Nothing here imports Flet, and nothing here reads a file or opens a socket.
"""

import re
import threading
import time
from typing import NamedTuple

import spacy
from spacy.matcher import PhraseMatcher
from spacy.util import registry

SOURCE = (
    "Dr. Smith invoiced ACME Corp. $4,500.00 on 2026-01-15 via acme.com. "
    "Pay by Friday. A late fee of 1.5% applies after that."
)
PHRASES = {"ACME Corp.": "ORG", "Dr. Smith": "PERSON"}
REPEATS = 5
PREVIEW_SENTENCES = 3
PREVIEW_ENTITIES = 6
PREVIEW_TOKENS = 24

# spacy.blank() builds the tokenizer, the Vocab and the rule components out of
# spacy/lang/en's ordinary Python source: no model, no download, no file read.
nlp = spacy.blank("en")
nlp.add_pipe("sentencizer")
nlp.add_pipe("entity_ruler").add_patterns(
    [{"label": label, "pattern": phrase} for phrase, label in PHRASES.items()]
)

VERSION = (
    f"spacy {spacy.__version__} · blank('en') · loaded {nlp.pipe_names} of "
    f"{len(registry.factories.get_all())} registered factories"
)

# Deliberately wrong, and the point of the DISAGREE row: 'acme corp.' tokenises as
# three tokens while the text's 'Corp.' is one, so this matcher finds nothing and
# reports nothing — an empty result is indistinguishable from "the phrase is absent".
_lower_matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
_lower_matcher.add("ORG", [nlp.make_doc(phrase.lower()) for phrase in PHRASES])

# One pipeline mutating one shared Vocab, and page.run_thread hands work to a pool that
# can overlap two slider releases: one pass at a time.
_lock = threading.Lock()


class Analysis(NamedTuple):
    """What one pass measured, as plain values for the caller to format."""

    chars: int
    tokens: int
    ms: float
    mem: int
    token_residual: int
    sentence_residual: int
    n_sentences: int
    n_entities: int
    n_misplaced: int
    n_regex: int
    n_lowered: int
    regex_agrees: bool
    first: tuple  # text, pos_, tag_, lemma_, dep_ of doc[0]
    sentences: list
    entities: list
    token_rows: list


def residual(rebuilt, text):
    """Characters by which a reassembled string misses `text`; 0 if they are equal."""
    return sum(a != b for a, b in zip(rebuilt, text)) + abs(len(rebuilt) - len(text))


def token_row(tok):
    """One token as plain fields: index, text, offset, shape, and the set flags."""
    flags = [
        name
        for name, on in (
            ("alpha", tok.is_alpha),
            ("num", tok.like_num),
            ("punct", tok.is_punct),
            ("stop", tok.is_stop),
            ("url", tok.like_url),
        )
        if on
    ]
    return tok.i, tok.text, tok.idx, tok.shape_, flags


def analyse(copies):
    """Tokenise `copies` copies of SOURCE and audit the result against plain regex.

    Every check yields the residual it measured rather than a bare pass, so a
    disagreement reaches the screen as a number instead of as a missing exception. The
    regex reference deliberately knows nothing about spaCy: it is `re.finditer` over the
    same string, which is the only independent answer available offline.

    The lock spans the whole body — every attribute read below goes through the shared
    Vocab that a concurrent pass would be growing.
    """
    text = " ".join([SOURCE] * copies)
    with _lock:
        start = time.perf_counter()
        for _ in range(REPEATS):
            doc = nlp(text)
        ms = (time.perf_counter() - start) / REPEATS * 1000

        rebuilt = "".join(tok.text_with_ws for tok in doc)
        sentences = list(doc.sents)
        ruled = sorted((e.start_char, e.end_char, e.label_) for e in doc.ents)
        expected = sorted(
            (m.start(), m.end(), label)
            for phrase, label in PHRASES.items()
            for m in re.finditer(re.escape(phrase), text)
        )
        first = doc[0]
        return Analysis(
            chars=len(text),
            tokens=len(doc),
            ms=ms,
            mem=doc.mem.size,
            token_residual=residual(rebuilt, text),
            sentence_residual=residual(
                "".join(s.text_with_ws for s in sentences), text
            ),
            n_sentences=len(sentences),
            n_entities=len(doc.ents),
            n_misplaced=sum(
                text[e.start_char : e.end_char] not in PHRASES for e in doc.ents
            ),
            n_regex=len(expected),
            n_lowered=len(_lower_matcher(doc)),
            regex_agrees=ruled == expected,
            # Empty strings rather than errors: these are the model-dependent
            # attributes, and a blank pipeline answers every one of them with ''.
            first=(first.text, first.pos_, first.tag_, first.lemma_, first.dep_),
            sentences=[s.text for s in sentences[:PREVIEW_SENTENCES]],
            entities=[
                (e.label_, e.text, e.start_char, e.end_char)
                for e in doc.ents[:PREVIEW_ENTITIES]
            ],
            token_rows=[token_row(t) for t in doc[:PREVIEW_TOKENS]],
        )
