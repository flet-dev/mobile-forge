def test_cpp_extension_loaded():
    """Import the generic compiled module directly — the canary that the C++
    extension actually cross-compiled and links its C++ runtime (libc++_shared
    on Android). If the recipe had silently fallen back to the pure-Python wheel,
    rapidfuzz.fuzz_cpp would be absent and this import would raise."""
    import rapidfuzz.fuzz_cpp  # noqa: F401


def test_fuzz_ratio():
    """fuzz.ratio runs the compiled scalar edit-distance path. Identical strings
    score 100; a small edit scores below 100 but well above 0."""
    from rapidfuzz import fuzz

    assert fuzz.ratio("hello world", "hello world") == 100.0
    partial = fuzz.ratio("hello world", "hallo world")
    assert 0.0 < partial < 100.0, partial


def test_levenshtein_distance():
    """distance.Levenshtein exercises the compiled distance module — a known
    edit distance proves the metric computes correctly, not just that it loads."""
    from rapidfuzz.distance import Levenshtein

    assert Levenshtein.distance("kitten", "sitting") == 3
    assert Levenshtein.distance("flaw", "lawn") == 2


def test_process_extract_one():
    """process.extractOne drives process_cpp_impl — the module that links
    Taskflow (std::thread) and, on 32-bit armeabi-v7a, libatomic for 64-bit
    atomics. This is the most cross-compile-fragile module, so pick the best
    match from a small list to exercise it end to end."""
    from rapidfuzz import process, fuzz

    choices = ["apple", "banana", "orange", "pineapple"]
    match, score, index = process.extractOne("appel", choices, scorer=fuzz.ratio)
    assert match == "apple", match
    assert choices[index] == "apple"
    assert score > 70.0, score
