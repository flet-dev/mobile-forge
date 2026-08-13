import cbor2


def test_roundtrip():
    """Dumps/loads round-trips a nested structure through the Rust extension."""
    data = {"key": [1, 2.5, "three", b"four", True, None]}
    assert cbor2.loads(cbor2.dumps(data)) == data


def test_known_vector():
    """Decodes a canonical CBOR test vector (RFC 8949 appendix A)."""
    assert cbor2.loads(bytes.fromhex("a201020304")) == {1: 2, 3: 4}
    assert cbor2.dumps("IETF") == bytes.fromhex("6449455446")


def test_tag():
    """CBORTag survives an encode/decode round trip with tag and value intact."""
    tag = cbor2.CBORTag(4000, ["x"])
    out = cbor2.loads(cbor2.dumps(tag))
    assert out.tag == 4000
    # 6.x decodes arrays inside tags as immutable sequences (tuples)
    assert list(out.value) == ["x"]


def test_bignum():
    """Integers beyond 64 bits use the bignum tag path (num-bigint in Rust)."""
    big = 2**100 + 7
    assert cbor2.loads(cbor2.dumps(big)) == big
