def test_blank_tokenizer():
    """A blank English pipeline exercises spaCy's Cython tokenizer (and pulls
    in the native cymem/preshed/murmurhash/thinc stack) without needing a
    downloaded model."""
    import spacy

    nlp = spacy.blank("en")
    doc = nlp("Hello world from spaCy")
    assert [t.text for t in doc] == ["Hello", "world", "from", "spaCy"]
    assert len(doc) == 4


def test_vocab_and_lexeme():
    """Touch the StringStore / Vocab (Cython, backed by preshed/murmurhash):
    tokenizing interns the token text, whose orth hash round-trips back to the
    original string."""
    import spacy

    nlp = spacy.blank("en")
    doc = nlp("spaCy")
    orth = doc[0].orth  # hash id of the now-interned token
    assert nlp.vocab.strings[orth] == "spaCy"
