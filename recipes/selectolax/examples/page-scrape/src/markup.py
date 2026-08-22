"""A deliberately broken HTML page, read with selectolax and with html.parser."""

import platform
import time
from html.parser import HTMLParser as TokenParser

try:
    import selectolax
    from selectolax.lexbor import LexborHTMLParser
    from selectolax.parser import HTMLParser as ModestHTMLParser

    IMPORT_ERROR = None
except Exception as error:
    selectolax = LexborHTMLParser = ModestHTMLParser = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

AVAILABLE = IMPORT_ERROR is None

# A small feed page carrying the breakages real pages carry: unquoted attribute
# values, <li>/<tr>/<td>/<p> that are never closed, a <b>/<i> pair closed in the
# wrong order, a bare "<" in running text, a <table> with no <tbody>, a comment
# holding "</div>", and a <script> whose string literal looks like another post.
DOCUMENT = """<!DOCTYPE html>
<html lang=en>
<head>
  <meta charset="utf-8">
  <title>Field Notes &mdash; Issue 42</title>
</head>
<body>
<div id=main class="feed wide">
  <h1>Field&nbsp;Notes</h1>
  <!-- generated block; do not hand-edit </div> -->
  <ul class=posts>
    <li class=post data-id=101>
      <a href="/p/101" class=title>Bees <b>and <i>weather</b></i></a>
      <span class=meta>2026-04-02 &middot; 6 min</span>
    <li class=post data-id=102>
      <a href="/p/102" class=title>Why 5 < 6 matters</a>
      <span class=meta>2026-04-09 &middot; 4 min</span>
    <li class="post draft" data-id=103>
      <a href=/p/103 class=title>Unfinished thoughts</a>
      <span class=meta>2026-04-11 &middot; 2 min</span>
  </ul>
  <p>Older issues live in the <a href="/archive">archive</a>.
  <div class=footer>
    <table class=stats>
      <tr><th>metric<th>value
      <tr><td>posts<td>3
      <tr><td>drafts<td>1
    </table>
    <script>
      var tpl = "<li class=post data-id=999><a href='/p/999'>ghost</a></li>";
      if (a < b && c > d) { render(tpl); }
    </script>
    <style>.post > .title { font-weight: 600 }</style>
    <p>&copy; 2026 Field Notes
  </div>
</div>
</body>
</html>
"""

ENGINES = ("lexbor", "modest")
PRESETS = (
    "li.post",
    "li.post:not(.draft) > a.title",
    "table.stats tbody tr",
    'a[href^="/p/"]',
    ":is(th, td)",
    "li.post ~ li",
)
BENCH_COPIES = 40
BENCH_SECONDS = 0.25


def versions(engine, device):
    """The header line: package, engine, interpreter and device."""
    return (
        f"selectolax {selectolax.__version__} · {engine} engine · "
        f"Python {platform.python_version()} · {device}"
    )


def engine_class(engine):
    """The parser class for `engine`, or None when the package is absent."""
    if LexborHTMLParser is None:
        return None
    return LexborHTMLParser if engine == "lexbor" else ModestHTMLParser


def parse(engine, html):
    """Build a tree for `html` with the chosen engine."""
    return engine_class(engine)(html)


def scaled(copies):
    """`DOCUMENT` with its post list repeated `copies` times.

    The benchmark needs a payload big enough that the measurement is not all
    call overhead, and repeating the list rather than the whole file keeps one
    well-formed document instead of a stack of concatenated ones.
    """
    head, rest = DOCUMENT.split("<ul class=posts>", 1)
    items, tail = rest.split("</ul>", 1)
    return f"{head}<ul class=posts>{items * copies}</ul>{tail}"


def records(tree):
    """The feed as rows a caller could store: id, title, date, minutes, draft.

    Everything here comes out of the repaired tree, which is the point — the
    `<li>` elements are never closed in the source, so "the `<a>` belonging to
    this post" is a question only a tree can answer.
    """
    rows = []
    for node in tree.css("li.post"):
        link = node.css_first("a.title")
        meta = node.css_first("span.meta")
        text = meta.text(separator=" ", strip=True) if meta else ""
        date, _, minutes = text.partition("·")
        rows.append(
            {
                "id": node.attributes.get("data-id"),
                "title": link.text(separator=" ", strip=True) if link else "",
                "href": link.attributes.get("href") if link else "",
                "date": date.strip(),
                "minutes": minutes.strip(),
                "draft": "draft" in (node.attributes.get("class") or ""),
            }
        )
    return rows


def stats(tree):
    """The footer table as (metric, value) pairs, read through the implied tbody.

    The source has no `<tbody>` and closes no cell; the selector used here is
    the one a browser's DOM inspector would hand you, and it only matches
    because the parser inserted the element the HTML5 spec requires.
    """
    pairs = []
    for row in tree.css("table.stats tbody tr"):
        cells = [cell.text(separator=" ", strip=True) for cell in row.css("th, td")]
        if len(cells) == 2:
            pairs.append(tuple(cells))
    return pairs


def tokens(html):
    """What `html.parser` reports for `html`: tag counts and the b/i order.

    This is the honest stdlib comparison — `html.parser` is a tokenizer, so it
    hands back the tags the source contains and nothing else. It is used here
    as the baseline, not as a straw man: it gets character references, the
    script's CDATA content and the bare "<" right.
    """
    starts, ends, order = {}, {}, []

    class Counter(TokenParser):
        """Tally the tag events the tokenizer emits, in the order it emits them."""

        def handle_starttag(self, tag, attrs):
            """Count one start tag, recording `<b>`/`<i>` in sequence."""
            starts[tag] = starts.get(tag, 0) + 1
            if tag in ("b", "i"):
                order.append(tag)

        def handle_endtag(self, tag):
            """Count one end tag; the source contains far fewer of these than starts."""
            ends[tag] = ends.get(tag, 0) + 1
            if tag in ("b", "i"):
                order.append(f"/{tag}")

    Counter().feed(html)
    return {
        "starts": starts,
        "ends": ends,
        "total_starts": sum(starts.values()),
        "total_ends": sum(ends.values()),
        "tbody": starts.get("tbody", 0),
        "order": ", ".join(order),
    }


def repairs(tree, seen):
    """Six things the tree contains that the source did not, each checked live.

    Every entry is `(what happened, the evidence)` computed from this run, so a
    device that repairs the page differently prints something different rather
    than repeating a claim baked into the file.
    """
    body = tree.css_first("#main")
    bold = tree.css_first("li.post b")
    title = tree.css_first('li.post[data-id="102"] a.title')
    ghosts = [n for n in tree.css("li.post") if n.attributes.get("data-id") == "999"]
    implied = seen["total_starts"] - seen["total_ends"]
    return [
        (
            "inserted the tbody the source omits",
            f"source has {seen['tbody']} tbody start tags, tree has "
            f"{len(tree.css('table.stats tbody'))}, carrying "
            f"{len(tree.css('table.stats tbody tr'))} rows",
        ),
        (
            "closed the elements the source leaves open",
            f"{seen['total_starts']} start tags and {seen['total_ends']} end tags "
            f"in the source: {implied} elements closed by the parser, not the author",
        ),
        (
            "re-nested <b>and <i>weather</b></i>",
            f"tree says {bold.html if bold else 'no <b> found'}",
        ),
        (
            "kept the bare < in running text",
            f"title 102 reads {title.text(separator=' ', strip=True)!r}"
            if title
            else "post 102 not found",
        ),
        (
            "did not read the <script> string as markup",
            f"{len(ghosts)} posts with data-id 999, "
            f"{len(tree.css('li.post'))} posts in total",
        ),
        (
            "did not let the comment's </div> close #main",
            f"#main still holds {len(body.css('.footer')) if body else 0} footer "
            f"and {len(body.css('li.post')) if body else 0} posts",
        ),
    ]


def throughput(fn, payload, seconds=BENCH_SECONDS):
    """Milliseconds and MB/s for `fn(payload)`, best of three timed batches."""
    fn(payload)
    best = None
    for _ in range(3):
        runs, started = 0, time.perf_counter()
        while time.perf_counter() - started < seconds:
            fn(payload)
            runs += 1
        each = (time.perf_counter() - started) / runs
        best = each if best is None else min(best, each)
    return best * 1000, len(payload.encode()) / best / 1e6


def benchmark(engine):
    """Parse rate for the chosen engine and for `html.parser` on the same bytes.

    The comparison is not like for like and that is the finding: selectolax
    builds a whole tree in less time than the tokenizer takes to emit tags.
    """
    payload = scaled(BENCH_COPIES)
    out = {"bytes": len(payload.encode())}

    def tokenize(text):
        """Feed `text` to a bare tokenizer, so only the parsing itself is timed."""
        TokenParser().feed(text)

    out["stdlib_ms"], out["stdlib_mbs"] = throughput(tokenize, payload)
    if engine_class(engine) is not None:
        out["engine_ms"], out["engine_mbs"] = throughput(engine_class(engine), payload)
    return out


def query(tree, selector):
    """Run `selector` and return `(rows, error)`; a bad selector is data, not a crash.

    The Modest engine rejects selectors Lexbor accepts, so the error text is
    part of what this screen is for — see `:is(th, td)` in the presets.
    """
    try:
        nodes = tree.css(selector)
    except Exception as error:
        return [], f"{type(error).__name__}: {error}"
    rows = []
    for node in nodes:
        attrs = " ".join(f"{k}={v!r}" for k, v in node.attributes.items() if v)
        # strip=True trims each text node, not the run of them, so the joined
        # result still carries the source's indentation as double spaces.
        text = " ".join(node.text(separator=" ", strip=True).split())
        rows.append((node.tag, attrs, text[:70] + ("…" if len(text) > 70 else "")))
    return rows, None


def match_pairs(matches, error):
    """The selector's hits as label/value pairs, or the reason there are none."""
    if error:
        return [("rejected", error)]
    if not matches:
        return [("matched", "nothing")]
    return [
        (f"{index}. {tag}", f"{attrs}   {text}" if attrs else text)
        for index, (tag, attrs, text) in enumerate(matches, 1)
    ]


def record_pairs(rows, table):
    """The scrape itself: one pair per post, then the footer table on one line."""
    pairs = [
        (
            post["id"],
            f"{post['title']} — {post['date']}, {post['minutes']}"
            + (" (draft)" if post["draft"] else ""),
        )
        for post in rows
    ]
    pairs.append(("stats table", " · ".join(f"{k}={v}" for k, v in table)))
    return pairs


def comparison_pairs(engine, elements, table, seen, bench):
    """selectolax against html.parser on the same bytes, as label/value pairs."""
    rate = (
        f"{bench['engine_ms']:.2f} ms · {bench['engine_mbs']:.1f} MB/s"
        if "engine_ms" in bench
        else "-"
    )
    return [
        (
            "tags vs elements",
            f"html.parser reports {seen['total_starts']} start tags; "
            f"selectolax builds {elements} elements",
        ),
        (
            "tbody",
            f"html.parser {seen['tbody']} · selectolax "
            f"{len(table)} rows readable through it",
        ),
        (
            "b/i nesting",
            f"html.parser hands back {seen['order']}; the tree nests them",
        ),
        (
            f"parse {bench['bytes']:,} B",
            f"{engine} {rate} · html.parser "
            f"{bench['stdlib_ms']:.2f} ms · {bench['stdlib_mbs']:.1f} MB/s",
        ),
    ]


def analyse(engine, selector):
    """Everything one pass of the screen shows, from one parse of the document.

    Returns a panel of `(label, value)` pairs per section, so the screen only
    has to lay them out.
    """
    tree = parse(engine, DOCUMENT)
    seen = tokens(DOCUMENT)
    table = stats(tree)
    matches, error = query(tree, selector)
    return {
        "matches": match_pairs(matches, error),
        "records": record_pairs(records(tree), table),
        "repairs": repairs(tree, seen),
        "comparison": comparison_pairs(
            engine, len(tree.css("*")), table, seen, benchmark(engine)
        ),
    }


def absent_report():
    """Header, note and the one fact left when the wheel is missing.

    `html.parser` still runs, so the screen can say what a tokenizer alone
    knows about the document — and, by omission, what it cannot.
    """
    seen = tokens(DOCUMENT)
    return (
        f"selectolax absent · Python {platform.python_version()}",
        f'{IMPORT_ERROR}\nAdd "selectolax" to [project] dependencies — the '
        "package has desktop wheels as well as the mobile ones, so one entry "
        "covers `flet run` and `flet build` alike.",
        [
            (
                "html.parser alone",
                f"{seen['total_starts']} start tags, {seen['total_ends']} end tags, "
                f"{seen['tbody']} tbody — no tree, so no CSS selector to run",
            )
        ],
    )
