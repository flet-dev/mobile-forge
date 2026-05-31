def test_byte_level_bpe_roundtrip():
    """Hugging Face `tokenizers` is a PyO3 wrapper around a Rust core.
    Train + tokenize + detokenize without any pretrained model — keeps
    the test offline."""
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from tokenizers.pre_tokenizers import Whitespace
    from tokenizers.trainers import BpeTrainer

    tok = Tokenizer(BPE(unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    trainer = BpeTrainer(vocab_size=80, special_tokens=["[UNK]"])

    # Train on a tiny in-memory corpus.
    tok.train_from_iterator(
        ["hello mobile forge", "hello world", "forge ahead"] * 5,
        trainer=trainer,
    )

    encoded = tok.encode("hello forge")
    assert len(encoded.ids) > 0
    decoded = tok.decode(encoded.ids)
    # Round-trip preserves the words (whitespace handling is lossy).
    assert "hello" in decoded
    assert "forge" in decoded
