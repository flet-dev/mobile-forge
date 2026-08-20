"""Give yarl and `urllib.parse` the same URL and put the differences on screen.

Type or pick a URL and the top three panels re-parse it with both. Below them are
three fixed comparisons that need a URL of their own: RFC 3986's reference-resolution
vectors, a URL carried inside another URL's query, and a host that is not the host it
looks like. The last panel times yarl's C quoter against the pure-Python one that
ships beside it in the same wheel.
"""

import platform
import time
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

import flet as ft

try:
    import yarl
    from yarl import URL
except Exception as error:  # the wheel may be missing or fail to load
    yarl = URL = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

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

SAMPLES = {
    "unicode": (
        "https://Example.COM:443/search results/über?tag=x&tag=y&empty=#frag ment"
    ),
    "idn": "https://пример.рф/каталог/книга 42.html?q=привет мир&tag=a&tag=b#раздел",
    "escaped": "https://files.example.com/box/a%2Fb/%c3%bc?p=1%262&p=3",
}

CONFUSABLE = "http://аpple.com/login"  # first letter is Cyrillic U+0430

NESTED = "https://cdn.example.com/img.png?w=100&h=50"

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
# own table never exercises. RFC 3986 5.3 takes the fragment from the reference, so
# a reference without one leaves the result without one.
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

SMALL = 11

TINY = 10


def attempt(call):
    """Run `call` and return its result, or the exception spelled out as text."""
    try:
        return call()
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def parse_rows(text):
    """Six fields of one URL as (label, yarl, stdlib), for the comparison table.

    The pairs are chosen where the two libraries answer differently rather than
    where they agree: yarl returns the URL already percent-encoded and IDNA-encoded,
    `urlsplit` returns the characters it was handed. `port` is the clearest small
    case - yarl knows the scheme's default and `urlsplit` has never heard of it.
    """
    split = urlsplit(text)
    if URL is None:
        parsed = None
    else:
        parsed = attempt(lambda: URL(text))
        if isinstance(parsed, str):  # construction raised; report it once
            return [("URL(text)", parsed, split.geturl())]
    return [
        ("full URL", "-" if parsed is None else str(parsed), split.geturl()),
        ("host", "-" if parsed is None else parsed.raw_host, split.hostname),
        (
            "port",
            "-"
            if parsed is None
            else f"{parsed.port} (explicit {parsed.explicit_port})",
            attempt(lambda: split.port),
        ),
        ("path", "-" if parsed is None else parsed.raw_path, split.path),
        ("query", "-" if parsed is None else parsed.raw_query_string, split.query),
        (
            "readable",
            "-" if parsed is None else parsed.human_repr(),
            "(no equivalent)",
        ),
    ]


def requote(text):
    """Re-encode one URL with yarl and with the usual stdlib idiom, and compare.

    `quote(unquote(path))` is what code reaches for when it has to normalise a URL
    with only the standard library, and it is not a round trip: `unquote` turns an
    escaped `%2F` into a real slash and `quote` then leaves it as a path separator,
    so the two are different resources. yarl re-quotes without decoding first.
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
    if URL is None:
        return None, naive, False
    mine = attempt(lambda: str(URL(text)))
    return mine, naive, mine == naive


def query_report(text):
    """The same query string read four ways, since repeats and blanks divide them.

    `parse_qs` drops a key whose value is empty unless asked not to, and hands back
    lists for every key whether or not it repeats; yarl hands back a multidict whose
    `getall` keeps the repeats while ordinary lookup gives the first. `dict()` over
    that multidict silently keeps only one value per key, which is the trap.
    """
    raw = urlsplit(text).query
    rows = [
        ("parse_qs", str(parse_qs(raw))),
        ("parse_qs keep_blank_values", str(parse_qs(raw, keep_blank_values=True))),
    ]
    if URL is None:
        return rows
    parsed = attempt(lambda: URL(text))
    if isinstance(parsed, str):
        return rows + [("yarl", parsed)]
    return [
        ("yarl query items", str(list(parsed.query.items()))),
        ("yarl dict(query)", str(dict(parsed.query))),
    ] + rows


def join_report():
    """Resolve RFC 3986 section 5.4's reference vectors with both libraries.

    These are the normative examples every URL parser is measured against, so the
    score is a claim about correctness rather than taste, and the disagreements it
    returns are the rows worth reading. Without the wheel the yarl score is None and
    only urljoin's misses are listed, so an absent package cannot read as 42 failures.
    """
    rows, mine, theirs = [], 0, 0
    base = None if URL is None else URL(RFC_BASE)
    for reference, want in RFC_VECTORS:
        stdlib = attempt(lambda ref=reference: urljoin(RFC_BASE, ref))
        theirs += stdlib == want
        if base is None:
            if stdlib != want:
                rows.append(f"{reference!r} -> want {want}, urljoin said {stdlib}")
            continue
        yarl_out = attempt(lambda ref=reference: str(base.join(URL(ref))))
        mine += yarl_out == want
        if want not in (yarl_out, stdlib):
            rows.append(f"{reference!r} -> want {want}, both said {stdlib}")
        elif yarl_out != want:
            rows.append(f"{reference!r} -> want {want}, yarl said {yarl_out}")
        elif stdlib != want:
            rows.append(f"{reference!r} -> want {want}, urljoin said {stdlib}")
    return (None if base is None else mine), theirs, len(RFC_VECTORS), rows


def fragment_case():
    """The query-only reference against a base that carries a fragment.

    RFC 3986 5.3 assigns the result's fragment from the reference, so a reference
    with no fragment must produce a URL with none. The RFC's own table never puts a
    fragment on the base, which is why this case is checked separately.
    """
    stdlib = attempt(lambda: urljoin(FRAGMENT_BASE, FRAGMENT_REF))
    if URL is None:
        return "-", stdlib, FRAGMENT_WANT
    mine = attempt(lambda: str(URL(FRAGMENT_BASE).join(URL(FRAGMENT_REF))))
    return mine, stdlib, FRAGMENT_WANT


def nested_report():
    """Put a URL inside another URL's query, both ways, and read it back.

    Concatenation is the obvious way to write it and it corrupts the result: the
    inner URL's own `&` ends the outer parameter, so the receiver sees a truncated
    value plus whatever came after it as extra parameters of its own.
    """
    naive = "https://proxy.example.com/fetch?url=" + NESTED
    naive_back = parse_qs(urlsplit(naive).query)
    if URL is None:
        return None, None, None, naive, naive_back
    built = URL("https://proxy.example.com/fetch").with_query({"url": NESTED})
    return (
        str(built),
        built.query["url"],
        built.query["url"] == NESTED,
        naive,
        naive_back,
    )


def confusable_report():
    """Show what each library calls a host whose first letter is not Latin."""
    stdlib = urlsplit(CONFUSABLE).hostname
    if URL is None:
        return "-", "-", stdlib
    parsed = URL(CONFUSABLE)
    return parsed.raw_host, parsed.host, stdlib


def implementations():
    """Which implementation of each moving part actually loaded, as (name, module)."""
    rows = []
    for label, module_name, attribute in (
        ("quoting", "yarl._quoting", "_Quoter"),
        ("multidict", "multidict", "MultiDict"),
        ("propcache", "propcache.api", "under_cached_property"),
    ):
        try:
            module = __import__(module_name, fromlist=["x"])
            rows.append((label, getattr(module, attribute).__module__))
        except Exception as error:
            rows.append((label, f"{type(error).__name__}"))
    return rows


def best_of(work, items):
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


def quoter_timings():
    """Price yarl's C quoter against the pure-Python one on this device.

    Both are importable from the same wheel and produce identical output, so the
    only way to tell which one a build ended up with is the clock - this is that
    clock. The two URL rows are separate because yarl builds the query multidict
    lazily: parsing alone never touches multidict, and reading `.query` does.
    """
    result = {}
    if CQuoter is not None:
        quoter = CQuoter(**QUOTER_ARGS)
        result["C quoter"] = best_of(
            lambda paths: [quoter(path) for path in paths], BENCH_PATHS
        )
    if PyQuoter is not None:
        fallback = PyQuoter(**QUOTER_ARGS)
        result["pure-Python quoter"] = best_of(
            lambda paths: [fallback(path) for path in paths], BENCH_PATHS
        )
    if URL is not None:
        result["URL(str)"] = best_of(
            lambda urls: [URL(url) for url in urls], BENCH_URLS
        )
        result["URL(str) + .query"] = best_of(
            lambda urls: [URL(url).query.getall("tag") for url in urls], BENCH_URLS
        )
    return result


def agreement(quoted):
    """Whether both quoters produce the same bytes for every benchmark path."""
    if CQuoter is None or PyQuoter is None:
        return None
    quoter, fallback = CQuoter(**QUOTER_ARGS), PyQuoter(**QUOTER_ARGS)
    return sum(quoter(path) == fallback(path) for path in quoted)


def field_block(label, mine, theirs):
    """One field of the parse table: its name, then each library's answer."""
    return ft.Column(
        spacing=0,
        controls=[
            ft.Text(label, size=TINY, weight=ft.FontWeight.BOLD),
            ft.Text(f"yarl    {mine}", size=SMALL, color=ft.Colors.PRIMARY),
            ft.Text(f"stdlib  {theirs}", size=SMALL),
        ],
    )


def labelled(label, value):
    """A dimmer label above a value, for the panels that are not two-sided."""
    return ft.Column(
        spacing=0,
        controls=[
            ft.Text(label, size=TINY, weight=ft.FontWeight.BOLD),
            ft.Text(value, size=SMALL),
        ],
    )


def main(page: ft.Page):
    """Parse whatever is in the field with both libraries and show the difference.

    Everything on screen is computed on the device. Without the yarl wheel the app
    still runs: the header turns red and names what the import raised, every stdlib
    answer is still computed, and the yarl side of each comparison reads `-`.
    """

    def analyse():
        """Re-run the three input-driven panels against the current field value.

        Wrapped in try/except because an exception escaping a Flet event handler
        ends the session with a crash screen, and a malformed URL typed into the
        field is an ordinary thing for a workbench to be handed.
        """
        try:
            text = query.value or ""
            table.controls = [field_block(*row) for row in parse_rows(text)]
            mine, naive, same = requote(text)
            verdict = (
                "yarl absent"
                if mine is None
                else f"{'same' if same else 'DIFFERENT'} - "
                "stdlib decodes before re-encoding, yarl does not"
            )
            requoted.value = f"yarl    {mine or '-'}\nstdlib  {naive}\n{verdict}"
            requoted.color = ft.Colors.PRIMARY if same else ft.Colors.ERROR
            queries.controls = [labelled(*row) for row in query_report(text)]
        except Exception as error:
            table.controls = []
            queries.controls = []
            requoted.value = f"{type(error).__name__}: {error}"
            requoted.color = ft.Colors.ERROR

    def pick():
        """Copy the chosen sample into the field, then re-parse.

        Empty selection is allowed - tapping the highlighted segment clears it - so
        the list is checked rather than indexed, and clearing leaves the field alone.
        """
        if picker.selected:
            query.value = SAMPLES[picker.selected[0]]
        analyse()

    def submitted():
        """Re-parse after the keyboard's return key, dropping the sample highlight."""
        picker.selected = []
        analyse()

    def start():
        """Send the timing run to the thread pool and lock the button while it runs.

        The guard is set in the handler rather than in the worker because
        `run_thread` only schedules: a `disabled` set inside the worker would not
        have reached the client before a second tap could start an overlapping run.
        """
        if timer.disabled:
            return
        timer.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Time both quoters, then report the ratio and that they agree.

        Wrapped in try/except because `page.run_thread` never retrieves the worker's
        future and discards whatever it raised - with no log, no dialog and no crash,
        so an unguarded failure would look like a panel that stopped updating.
        """
        try:
            timings = quoter_timings()
            lines = [f"{label}  {value:,.2f} us" for label, value in timings.items()]
            fast = timings.get("C quoter")
            slow = timings.get("pure-Python quoter")
            if fast and slow:
                lines.append(f"C is {slow / fast:,.1f}x the pure-Python quoter here")
            matched = agreement(BENCH_PATHS)
            if matched is not None:
                lines.append(
                    f"{matched:,}/{len(BENCH_PATHS):,} paths encode identically - "
                    "only the clock tells them apart"
                )
            numbers.value = "\n".join(lines)
        except Exception as error:
            numbers.value = f"{type(error).__name__}: {error}"
        timer.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    library = (
        f"yarl absent - {IMPORT_ERROR}"
        if URL is None
        else f"yarl {yarl.__version__} - "
        + ", ".join(f"{name} {module}" for name, module in implementations())
    )
    mine, theirs, total, misses = join_report()
    joined = (
        f"RFC 3986 5.4 reference vectors: "
        f"yarl {'absent' if mine is None else f'{mine}/{total}'}, "
        f"urljoin {theirs}/{total}"
    )
    frag_mine, frag_theirs, frag_want = fragment_case()
    built, read_back, round_trips, naive_nested, naive_back = nested_report()
    punycode, unicode_host, stdlib_host = confusable_report()

    page.appbar = ft.AppBar(title=ft.Text("yarl URL workbench"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library,
                        size=TINY,
                        color=ft.Colors.ERROR if URL is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=TINY,
                    ),
                    query := ft.TextField(
                        label="URL",
                        value=SAMPLES["unicode"],
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=12,
                        multiline=True,
                        min_lines=1,
                        max_lines=3,
                        on_submit=submitted,
                    ),
                    # expand=True inside a scrolling Column collapses the whole
                    # viewport on iOS; the Row gives it bounded width instead.
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                allow_empty_selection=True,  # a typed URL is no sample
                                segments=[
                                    ft.Segment(value=name, label=ft.Text(name))
                                    for name in SAMPLES
                                ],
                                selected=["unicode"],  # a set dies in msgpack
                                on_change=pick,
                            ),
                        ],
                    ),
                    table := ft.Column(spacing=6),
                    ft.Divider(),
                    ft.Text("re-encoding the same URL", size=TINY),
                    requoted := ft.Text(size=SMALL),
                    ft.Divider(),
                    ft.Text("the query string, four readings", size=TINY),
                    queries := ft.Column(spacing=6),
                    ft.Divider(),
                    ft.Text("resolving relative references", size=TINY),
                    ft.Text(joined, size=SMALL),
                    ft.Text(
                        "\n".join(misses) or "no disagreement with the RFC's table",
                        size=SMALL,
                        color=ft.Colors.ERROR if misses else None,
                    ),
                    labelled(
                        f"{FRAGMENT_REF!r} against {FRAGMENT_BASE} "
                        f"(RFC says {FRAGMENT_WANT})",
                        f"yarl    {frag_mine}\nstdlib  {frag_theirs}",
                    ),
                    ft.Divider(),
                    ft.Text("a URL inside a query parameter", size=TINY),
                    labelled(
                        "yarl with_query",
                        "yarl absent"
                        if round_trips is None
                        else f"{built}\nread back: {read_back}\n"
                        f"round trip {'exact' if round_trips else 'BROKEN'}",
                    ),
                    labelled(
                        "string concatenation",
                        f"{naive_nested}\nparse_qs: {naive_back}",
                    ),
                    ft.Divider(),
                    ft.Text("a host that is not the host it looks like", size=TINY),
                    labelled(
                        CONFUSABLE,
                        f"yarl raw_host   {punycode}\n"
                        f"yarl host       {unicode_host}\n"
                        f"stdlib hostname {stdlib_host}",
                    ),
                    ft.Divider(),
                    ft.Row(
                        controls=[
                            timer := ft.Button(
                                "time the two quoters",
                                icon=ft.Icons.TIMER,
                                on_click=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    numbers := ft.Text(size=SMALL),
                ],
            ),
        )
    )

    analyse()


if __name__ == "__main__":
    ft.run(main)
