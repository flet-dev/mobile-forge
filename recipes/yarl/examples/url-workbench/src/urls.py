"""The URL work: the same input through yarl and through `urllib.parse`.

`main.py` owns the screen; this module owns the comparisons and hands back plain
strings. The yarl import is guarded, so a build that did not get the wheel still
runs, still computes every standard-library answer, and reads `-` on the yarl side
instead of crashing.
"""

import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

try:
    import yarl
    from yarl import URL
except Exception as error:  # the wheel may be missing or fail to load
    yarl = URL = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

HAVE_YARL = URL is not None

# Both quoting implementations ship in every yarl wheel and can be imported side by
# side, which is how the timing panel prices one against the other on the device.
try:
    from yarl._quoting_c import _Quoter as CQuoter
except Exception:
    CQuoter = None

try:
    from yarl._quoting_py import _Quoter as PyQuoter
except Exception:
    PyQuoter = None

MISSING = "-"

SAMPLES = {
    "unicode": (
        "https://Example.COM:443/search results/über?tag=x&tag=y&empty=#frag ment"
    ),
    "idn": "https://пример.рф/каталог/книга 42.html?q=привет мир&tag=a&tag=b#раздел",
    "escaped": "https://files.example.com/box/a%2Fb/%c3%bc?p=1%262&p=3",
}

CONFUSABLE = "http://аpple.com/login"  # first letter is Cyrillic U+0430

NESTED = "https://cdn.example.com/img.png?w=100&h=50"

PROXY = "https://proxy.example.com/fetch"

# RFC 3986 section 5.4, base and reference vectors, verbatim from the RFC.
RFC_BASE = "http://a/b/c/d;p?q"

RFC_VECTORS = (
    ("g:h", "g:h"),
    ("g", "http://a/b/c/g"),
    ("./g", "http://a/b/c/g"),
    ("g/", "http://a/b/c/g/"),
    ("/g", "http://a/g"),
    ("//g", "http://g"),
    ("?y", "http://a/b/c/d;p?y"),
    ("g?y", "http://a/b/c/g?y"),
    ("#s", "http://a/b/c/d;p?q#s"),
    ("g#s", "http://a/b/c/g#s"),
    ("g?y#s", "http://a/b/c/g?y#s"),
    (";x", "http://a/b/c/;x"),
    ("g;x", "http://a/b/c/g;x"),
    ("g;x?y#s", "http://a/b/c/g;x?y#s"),
    ("", "http://a/b/c/d;p?q"),
    (".", "http://a/b/c/"),
    ("./", "http://a/b/c/"),
    ("..", "http://a/b/"),
    ("../", "http://a/b/"),
    ("../g", "http://a/b/g"),
    ("../..", "http://a/"),
    ("../../", "http://a/"),
    ("../../g", "http://a/g"),
    ("../../../g", "http://a/g"),
    ("../../../../g", "http://a/g"),
    ("/./g", "http://a/g"),
    ("/../g", "http://a/g"),
    ("g.", "http://a/b/c/g."),
    (".g", "http://a/b/c/.g"),
    ("g..", "http://a/b/c/g.."),
    ("..g", "http://a/b/c/..g"),
    ("./../g", "http://a/b/g"),
    ("./g/.", "http://a/b/c/g/"),
    ("g/./h", "http://a/b/c/g/h"),
    ("g/../h", "http://a/b/c/h"),
    ("g;x=1/./y", "http://a/b/c/g;x=1/y"),
    ("g;x=1/../y", "http://a/b/c/y"),
    ("g?y/./x", "http://a/b/c/g?y/./x"),
    ("g?y/../x", "http://a/b/c/g?y/../x"),
    ("g#s/./x", "http://a/b/c/g#s/./x"),
    ("g#s/../x", "http://a/b/c/g#s/../x"),
    ("http:g", "http:g"),
)

# Same shape as the RFC's "?y" row but with a fragment on the base, which the RFC's
# own table never exercises. Section 5.3 takes the fragment from the reference, so a
# reference carrying none leaves the result with none.
FRAGMENT_BASE = "http://a/b/c/d;p?q#frag"

FRAGMENT_REF = "?y"

FRAGMENT_WANT = "http://a/b/c/d;p?y"

# The quoter configuration yarl uses for path segments (yarl/_quoters.py).
QUOTER_ARGS = dict(safe="@:", protected="/+", requote=False)

BENCH_PATHS = tuple(f"/каталог/книга {i}.html" for i in range(2000))

BENCH_URLS = tuple(
    f"https://example{i % 13}.com/каталог/книга {i}.html?tag=a&tag=b#f{i}"
    for i in range(2000)
)

BENCH_ROUNDS = 5


def attempt(call):
    """Run `call` and return its result, or the exception spelled out as text."""
    try:
        return call()
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def implementation():
    """Name the version and which implementation of each moving part actually loaded.

    This is the header line, and on a device it is the only thing that answers the
    accelerator question: the C quoter and the pure-Python one produce identical
    bytes, so nothing downstream can tell them apart. Expect
    `yarl._quoting_c` beside `multidict._multidict_py` and `propcache._helpers_py` —
    yarl's own accelerator is compiled here, the two packages it brings are not.
    """
    if not HAVE_YARL:
        return f"yarl absent - {IMPORT_ERROR}"
    parts = []
    for label, module_name, attribute in (
        ("quoting", "yarl._quoting", "_Quoter"),
        ("multidict", "multidict", "MultiDict"),
        ("propcache", "propcache.api", "under_cached_property"),
    ):
        try:
            module = __import__(module_name, fromlist=["x"])
            parts.append(f"{label} {getattr(module, attribute).__module__}")
        except Exception as error:
            parts.append(f"{label} {type(error).__name__}")
    return f"yarl {yarl.__version__} - " + ", ".join(parts)


def parse_rows(text):
    """Six fields of one URL as (label, yarl, stdlib), for the comparison table.

    The fields are chosen where the two libraries answer differently rather than
    where they agree: yarl returns the URL already percent-encoded and IDNA-encoded,
    `urlsplit` returns the characters it was handed. `port` is the clearest small
    case - yarl knows the scheme's default and `urlsplit` has never heard of it.
    """
    split = urlsplit(text)
    if not HAVE_YARL:
        parsed = None
    else:
        parsed = attempt(lambda: URL(text))
        if isinstance(parsed, str):  # construction raised; report it once
            return [("URL(text)", parsed, split.geturl())]

    def ours(read):
        """One yarl field, or `-` when there is no URL object to read it from."""
        return MISSING if parsed is None else read(parsed)

    return [
        ("full URL", ours(str), split.geturl()),
        ("host", ours(lambda url: url.raw_host), split.hostname),
        (
            "port",
            ours(lambda url: f"{url.port} (explicit {url.explicit_port})"),
            attempt(lambda: split.port),
        ),
        ("path", ours(lambda url: url.raw_path), split.path),
        ("query", ours(lambda url: url.raw_query_string), split.query),
        ("readable", ours(lambda url: url.human_repr()), "(no equivalent)"),
    ]


def requote(text):
    """Re-encode one URL both ways and say whether the results agree.

    `quote(unquote(path))` is what code reaches for when it has to normalise a URL
    with only the standard library, and it is not a round trip: `unquote` turns an
    escaped `%2F` into a real slash and `quote` then leaves it as a path separator,
    so the two strings name different resources. yarl re-quotes without decoding
    first. Returns the block to display and whether the two agreed, which is what
    colours it.
    """
    split = urlsplit(text)
    naive = urlunsplit(
        (
            split.scheme,
            split.netloc,
            quote(unquote(split.path)),
            split.query,
            split.fragment,
        )
    )
    if not HAVE_YARL:
        return f"yarl    {MISSING}\nstdlib  {naive}\nyarl absent", False
    ours = attempt(lambda: str(URL(text)))
    same = ours == naive
    verdict = "same" if same else "DIFFERENT"
    return (
        f"yarl    {ours}\nstdlib  {naive}\n"
        f"{verdict} - stdlib decodes before re-encoding, yarl does not",
        same,
    )


def query_rows(text):
    """The same query string read four ways, since repeats and blanks divide them.

    `parse_qs` drops a key whose value is empty unless asked not to, and hands back
    lists for every key whether or not it repeats; yarl hands back a multidict whose
    `getall` keeps the repeats while ordinary lookup gives the first. `dict()` over
    that multidict silently keeps only one value per key, which is the trap.
    """
    raw = urlsplit(text).query
    stdlib = [
        ("parse_qs", str(parse_qs(raw))),
        ("parse_qs keep_blank_values", str(parse_qs(raw, keep_blank_values=True))),
    ]
    if not HAVE_YARL:
        return stdlib
    parsed = attempt(lambda: URL(text))
    if isinstance(parsed, str):
        return stdlib + [("yarl", parsed)]
    return [
        ("yarl query items", str(list(parsed.query.items()))),
        ("yarl dict(query)", str(dict(parsed.query))),
    ] + stdlib


def fixed_panels():
    """The three comparisons that bring their own URL, as (heading, rows).

    They do not move with the input field, so the screen builds them once. Each
    needs a shape the samples cannot carry: the RFC's vector table, a URL nested
    inside another URL's query, and a host that is not the host it looks like.
    """
    return (
        ("resolving relative references", _join_rows()),
        ("a URL inside a query parameter", _nested_rows()),
        ("a host that is not the host it looks like", _confusable_rows()),
    )


def _join_rows():
    """Score RFC 3986 section 5.4's reference vectors with both libraries.

    These are the normative examples every URL parser is measured against, so the
    score is a claim about correctness rather than taste, and a tie is a useful
    result: it means `urljoin` is not the weak part of the standard library. The
    third row is the one genuine divergence, and it goes against yarl - the RFC's
    own table never puts a fragment on the base, so it never reaches the case.

    Without the wheel the yarl score reads `absent` and only `urljoin`'s misses are
    listed, so a missing package cannot show up as 42 failures.
    """
    misses, mine, theirs = [], 0, 0
    base = URL(RFC_BASE) if HAVE_YARL else None
    for reference, want in RFC_VECTORS:
        stdlib = attempt(lambda ref=reference: urljoin(RFC_BASE, ref))
        theirs += stdlib == want
        if base is None:
            if stdlib != want:
                misses.append(f"{reference!r} -> want {want}, urljoin said {stdlib}")
            continue
        ours = attempt(lambda ref=reference: str(base.join(URL(ref))))
        mine += ours == want
        if want not in (ours, stdlib):
            misses.append(f"{reference!r} -> want {want}, both said {stdlib}")
        elif ours != want:
            misses.append(f"{reference!r} -> want {want}, yarl said {ours}")
        elif stdlib != want:
            misses.append(f"{reference!r} -> want {want}, urljoin said {stdlib}")

    total = len(RFC_VECTORS)
    scored = "absent" if base is None else f"{mine}/{total}"
    frag_ours = (
        attempt(lambda: str(URL(FRAGMENT_BASE).join(URL(FRAGMENT_REF))))
        if HAVE_YARL
        else MISSING
    )
    return [
        (f"RFC 3986 5.4, {total} vectors", f"yarl {scored}, urljoin {theirs}/{total}"),
        ("disagreements", "\n".join(misses) or "none with the RFC's own table"),
        (
            f"{FRAGMENT_REF!r} against {FRAGMENT_BASE} (RFC says {FRAGMENT_WANT})",
            f"yarl    {frag_ours}\n"
            f"stdlib  {attempt(lambda: urljoin(FRAGMENT_BASE, FRAGMENT_REF))}",
        ),
    ]


def _nested_rows():
    """Put a URL inside another URL's query, both ways, and read it back.

    Concatenation is the obvious way to write it and it corrupts the result: the
    inner URL's own `&` ends the outer parameter, so the receiver sees a truncated
    value plus whatever followed it as extra parameters of its own.
    """
    naive = f"{PROXY}?url={NESTED}"
    rows = [
        (
            "string concatenation",
            f"{naive}\nparse_qs: {parse_qs(urlsplit(naive).query)}",
        )
    ]
    if not HAVE_YARL:
        return [("yarl with_query", MISSING)] + rows
    built = URL(PROXY).with_query({"url": NESTED})
    read_back = built.query["url"]
    return [
        (
            "yarl with_query",
            f"{built}\nread back: {read_back}\n"
            f"round trip {'exact' if read_back == NESTED else 'BROKEN'}",
        )
    ] + rows


def _confusable_rows():
    """Show what each library calls a host whose first letter is not Latin."""
    stdlib = urlsplit(CONFUSABLE).hostname
    if not HAVE_YARL:
        return [(CONFUSABLE, f"stdlib hostname {stdlib}")]
    parsed = URL(CONFUSABLE)
    return [
        (
            CONFUSABLE,
            f"yarl raw_host   {parsed.raw_host}\n"
            f"yarl host       {parsed.host}\n"
            f"stdlib hostname {stdlib}",
        )
    ]


def timing_lines():
    """Price the two quoters against each other on this device, as display lines.

    Both are importable from the same wheel and produce identical output, so the
    clock is the only thing that can tell you which one a build ended up with -
    this is that clock. The two URL rows are separate because yarl builds the query
    multidict lazily: parsing alone never touches multidict, and reading `.query`
    does, which is where an interpreted multidict shows up.

    Slow enough to belong in a worker thread rather than an event handler: four
    passes of `BENCH_ROUNDS` over 2,000 items each.
    """
    quoter = CQuoter(**QUOTER_ARGS) if CQuoter is not None else None
    fallback = PyQuoter(**QUOTER_ARGS) if PyQuoter is not None else None
    timings = {}
    if quoter is not None:
        timings["C quoter"] = _best_of(
            lambda paths: [quoter(path) for path in paths], BENCH_PATHS
        )
    if fallback is not None:
        timings["pure-Python quoter"] = _best_of(
            lambda paths: [fallback(path) for path in paths], BENCH_PATHS
        )
    if HAVE_YARL:
        timings["URL(str)"] = _best_of(
            lambda urls: [URL(url) for url in urls], BENCH_URLS
        )
        timings["URL(str) + .query"] = _best_of(
            lambda urls: [URL(url).query.getall("tag") for url in urls], BENCH_URLS
        )

    lines = [f"{label}  {value:,.2f} us" for label, value in timings.items()]
    fast, slow = timings.get("C quoter"), timings.get("pure-Python quoter")
    if fast and slow:
        lines.append(f"C is {slow / fast:,.1f}x the pure-Python quoter here")
        same = sum(quoter(path) == fallback(path) for path in BENCH_PATHS)
        lines.append(
            f"{same:,}/{len(BENCH_PATHS):,} paths encode identically - "
            "only the clock tells them apart"
        )
    return lines or ["yarl absent - nothing to time"]


def _best_of(work, items):
    """Microseconds per item for `work`, best of `BENCH_ROUNDS` passes.

    Best-of rather than mean: a phone schedules across cores of different speeds and
    throttles under load, so the fastest pass is the one that describes the code and
    the slow ones describe what else the device was doing.
    """
    best = None
    for _ in range(BENCH_ROUNDS):
        started = time.perf_counter()
        work(items)
        elapsed = (time.perf_counter() - started) * 1_000_000.0
        best = elapsed if best is None else min(best, elapsed)
    return best / len(items)
