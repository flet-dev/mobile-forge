def test_basic_encoding():
    """tiktoken is OpenAI's tokenizer (PyO3 wrapper around a Rust BPE).
    Use the simple gpt2 encoding which is bundled (no network)."""
    import tiktoken

    enc = tiktoken.get_encoding("gpt2")
    ids = enc.encode("hello world")
    assert isinstance(ids, list)
    assert len(ids) > 0
    assert enc.decode(ids) == "hello world"


def test_encoding_name():
    """Confirm a well-known encoding is registered — protects against a
    shipping wheel that lost its encoding registry."""
    import tiktoken

    # cl100k_base is GPT-4's tokenizer; if it's not registered the recipe
    # didn't bundle the data files correctly.
    enc = tiktoken.get_encoding("cl100k_base")
    assert enc.name == "cl100k_base"
