import time
from html.parser import HTMLParser
from importlib.metadata import version

import markupsafe
from markupsafe import Markup, _native, escape

try:
    from markupsafe import _speedups
except ImportError:  # a build whose C extension was silently skipped
    _speedups = None

# The whole of escape(): five characters, no parsing, no notion of context.
SPECIALS = ("&", "<", ">", "'", '"')
ROUNDS = 20000

# One template, filled four ways below. Markup.format escapes what it
# interpolates, so the template's own tags stay live and the value's do not.
TEMPLATE = Markup("<p>Comment from <b>{}</b></p>")

# Which _escape_inner won the try/except import at the top of markupsafe's
# __init__ is the only thing that says whether the C accelerator is live.
# markupsafe.__version__ is deprecated and goes away in 3.1.
ENGINE = markupsafe._escape_inner.__module__
VERSION = f"markupsafe {version('markupsafe')} · _escape_inner from {ENGINE}"


class Comment:
    """A value that renders itself, through the __html__ protocol escape() honours.

    escape() calls __html__ and trusts whatever comes back, so the escaping
    debt does not disappear -- it moves in here. Drop the escaping below and
    every caller of this class inherits the hole, which is why a __html__
    method deserves the review a raw SQL string gets.

    Return Markup, not str. escape(), Markup() and Markup(...) % obj all take
    a plain string from __html__ as-is, but Markup.format escapes whatever
    __html__ returns -- so a str return survives three of the four paths and
    arrives as visible &lt;i&gt; text in the fourth.
    """

    def __init__(self, text):
        self.text = text

    def __html__(self):
        return Markup("<i>{}</i>").format(self.text)


def safe_format(value):
    """Interpolate through Markup.format, which escapes every argument."""
    return TEMPLATE.format(value)


def blessed_concat(value):
    """Assemble the string first and bless it after -- the near miss.

    Markup() never looks at what it is handed, so blessing a string that
    already contains the value promotes the value's tags along with the
    template's. `Markup("<b>") + value` escapes the value; moving the addition
    inside the call is what loses it, and the two read almost alike.
    """
    return Markup("<p>Comment from <b>" + value + "</b></p>")


def trusted_value(value):
    """Hand the raw value to Markup(): the vulnerability, in one call."""
    return Markup(value)


def html_protocol(value):
    """Interpolate an object that carries its own markup."""
    return TEMPLATE.format(Comment(value))


RENDERINGS = (
    ("Markup.format", "TEMPLATE.format(value)", safe_format),
    ("Concatenate, then bless", 'Markup("<b>" + value + "</b>")', blessed_concat),
    ("Trust the value", "Markup(value)", trusted_value),
    ("__html__ protocol", "TEMPLATE.format(Comment(value))", html_protocol),
)


class _Elements(HTMLParser):
    """Collects the element names a browser would find in a fragment."""

    def __init__(self):
        super().__init__()
        self.names = []

    def handle_starttag(self, tag, attrs):
        self.names.append(tag)


def elements(html):
    """The element names in `html`, in document order."""
    parser = _Elements()
    parser.feed(str(html))
    parser.close()
    return parser.names


def renderings(value):
    """Build the same comment four ways and count what the value smuggled in.

    Parsing the output back is the honest test, and it is why this app does it
    rather than just printing the fragment: an element the value contributed is
    an element the browser will run, style or lay out. Rebuilding each fragment
    with an empty value gives the template's own tag count, so the difference
    belongs to the value alone -- and the four numbers come out 0, 1, 1, 0,
    which is the entire lesson.
    """
    rows = []
    for title, source, build in RENDERINGS:
        html = build(value)
        smuggled = len(elements(html)) - len(elements(build("")))
        rows.append((title, source, str(html), smuggled))
    return rows


def replacements():
    """The five characters escape() rewrites -- and it rewrites nothing else."""
    return [(char, str(escape(char))) for char in SPECIALS]


def _per_call(function, value):
    """Microseconds per call, after a warm-up that is thrown away."""
    for _ in range(ROUNDS // 10):
        function(value)
    started = time.perf_counter()
    for _ in range(ROUNDS):
        function(value)
    return (time.perf_counter() - started) / ROUNDS * 1e6


def bench(value):
    """Time both escaping engines, and escape() itself, on this device.

    Both are always timeable: _native is a plain module in the wheel, so the
    fallback is there to measure even when the C accelerator won the import.

    The ratio is not a constant, and it is not always above 1. The C code
    sizes the result with one scan and then copies character by character;
    the fallback is five str.replace passes, each with a fast path that
    returns the input untouched when it matches nothing -- so both engines
    hand back the same object when there is no work to do. On desktop CPython
    the accelerator ran 2-4x the fallback on a short value, about 1.2x on
    32 KB with nothing to escape, 5x on 32 KB that was all specials, and
    0.8x -- slower -- on 32 KB holding one '&'. Sparse specials in a long
    string is the shape where the character loop loses to str.replace.

    escape() costs more than the inner call it wraps, but only on short
    values: building the Markup is a fixed price per call, not per byte, so
    it measured 2-6x the inner call on a short string and disappeared into
    the noise (1.0x) at 32 KB.
    """
    rows = [("escape()", _per_call(escape, value))]
    fallback = _per_call(_native._escape_inner, value)
    if _speedups is None:
        rows.append(("_native._escape_inner", fallback))
        return rows, None
    accelerated = _per_call(_speedups._escape_inner, value)
    rows.append(("_speedups._escape_inner", accelerated))
    rows.append(("_native._escape_inner", fallback))
    return rows, fallback / accelerated
