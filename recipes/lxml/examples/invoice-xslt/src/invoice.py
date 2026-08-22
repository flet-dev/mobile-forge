import random
import time
from typing import NamedTuple

from lxml import etree

NS = {"inv": "urn:example:invoice"}
# A string, not a float: XSLT parameters are XPath expressions, and lxml refuses
# anything that is not text. "0.2" is the XPath number 0.2; a bare word would be
# evaluated as a node test and arrive as NaN.
VAT = "0.2"

SCHEMA = """
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:inv="urn:example:invoice"
           targetNamespace="urn:example:invoice"
           elementFormDefault="qualified">
  <xs:element name="invoice">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="supplier" type="xs:string"/>
        <xs:element name="terms" type="xs:string"/>
        <xs:element name="line" maxOccurs="unbounded">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="sku" type="xs:string"/>
              <xs:element name="unitPrice" type="xs:decimal"/>
            </xs:sequence>
            <xs:attribute name="quantity" type="xs:positiveInteger" use="required"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
      <xs:attribute name="number" type="xs:string" use="required"/>
      <xs:attribute name="issued" type="xs:date" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

# XSLT 1.0 has no way to sum a product over a node-set, so the net is computed by
# a tail-recursive named template. math:max, str:tokenize and date:year come from
# libexslt, which is linked into lxml's etree module on both mobile platforms.
STYLESHEET = """
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:inv="urn:example:invoice"
    xmlns:math="http://exslt.org/math"
    xmlns:str="http://exslt.org/strings"
    xmlns:date="http://exslt.org/dates-and-times">
  <xsl:output method="text"/>
  <xsl:param name="vat" select="0.2"/>

  <xsl:template name="net">
    <xsl:param name="lines"/>
    <xsl:param name="acc" select="0"/>
    <xsl:choose>
      <xsl:when test="$lines">
        <xsl:call-template name="net">
          <xsl:with-param name="lines" select="$lines[position() &gt; 1]"/>
          <xsl:with-param name="acc"
              select="$acc + $lines[1]/@quantity * $lines[1]/inv:unitPrice"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:otherwise><xsl:value-of select="$acc"/></xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template match="/inv:invoice">
    <xsl:variable name="net">
      <xsl:call-template name="net">
        <xsl:with-param name="lines" select="inv:line"/>
      </xsl:call-template>
    </xsl:variable>
    <xsl:text>invoice&#9;</xsl:text>
    <xsl:value-of select="@number"/>
    <xsl:text>&#10;year&#9;</xsl:text>
    <xsl:value-of select="date:year(@issued)"/>
    <xsl:text>&#10;supplier&#9;</xsl:text>
    <xsl:value-of select="inv:supplier"/>
    <xsl:text>&#10;terms&#9;</xsl:text>
    <xsl:for-each select="str:tokenize(inv:terms, ',')">
      <xsl:if test="position() &gt; 1"><xsl:text> / </xsl:text></xsl:if>
      <xsl:value-of select="."/>
    </xsl:for-each>
    <xsl:text>&#10;lines&#9;</xsl:text>
    <xsl:value-of select="count(inv:line)"/>
    <xsl:text>&#10;dearest unit&#9;</xsl:text>
    <xsl:value-of select="format-number(math:max(inv:line/inv:unitPrice), '0.00')"/>
    <xsl:text>&#10;net&#9;</xsl:text>
    <xsl:value-of select="format-number($net, '0.00')"/>
    <xsl:text>&#10;vat </xsl:text>
    <xsl:value-of select="format-number($vat * 100, '0')"/>
    <xsl:text>%&#9;</xsl:text>
    <xsl:value-of select="format-number($net * $vat, '0.00')"/>
    <xsl:text>&#10;total&#9;</xsl:text>
    <xsl:value-of select="format-number($net * (1 + $vat), '0.00')"/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>
</xsl:stylesheet>
"""

# Two encodings that resolve on both platforms, and two that need iconv — which
# iOS has and Android does not. The sample text is chosen so each encoding can
# actually represent it.
ENCODINGS = [
    ("ISO-8859-2", "iso-8859-2", "Živa"),
    ("windows-1252", "cp1252", "café €"),
    ("Shift_JIS", "shift_jis", "請求書"),
    ("KOI8-R", "koi8_r", "Счёт"),
]

SKUS = ["AC-1001", "AC-1002", "AC-2050", "AC-3100", "AC-4275", "AC-5060"]


def _dotted(numbers):
    """One of lxml's version tuples as a dotted string."""
    return ".".join(str(n) for n in numbers)


VERSIONS = (
    f"lxml {_dotted(etree.LXML_VERSION[:3])}"
    f" — libxml2 {_dotted(etree.LIBXML_VERSION)}"
    f" — libxslt {_dotted(etree.LIBXSLT_VERSION)}"
)
# The build describing itself. `iconv` is the one entry of this set that differs
# between the platforms, and the encoding rows below are what that looks like.
FEATURES = "libxml2 features: " + ", ".join(sorted(etree.LIBXML_FEATURES))


class Result(NamedTuple):
    """One pass over the invoice, as label/value pairs a control can hold.

    Plain strings rather than lxml objects, so nothing that needs the GIL
    released or a tree kept alive escapes into the UI thread.
    """

    statement: list
    checks: list
    encodings: list
    timings: str


def invoice_xml(lines):
    """Build an invoice document of `lines` items as UTF-8 bytes.

    Unit prices are whole multiples of 0.05 and quantities are integers, so the
    net, the VAT and the total are all exact to the cent — which is what lets the
    stylesheet's arithmetic and Python's be compared as strings further down
    without a rounding tolerance. The seed is fixed, so two devices produce the
    same document and the same totals.
    """
    rng = random.Random(20260817)
    # One line item per source line, so the line numbers libxml2 reports when
    # validation fails point at something a reader could go and look at.
    items = "".join(
        f'<inv:line quantity="{rng.randint(1, 9)}">'
        f"<inv:sku>{rng.choice(SKUS)}</inv:sku>"
        f"<inv:unitPrice>{rng.randrange(100, 5000, 5) / 100.0:.2f}</inv:unitPrice>"
        "</inv:line>\n"
        for _ in range(lines)
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<inv:invoice xmlns:inv="urn:example:invoice" number="INV-2026-0042"'
        ' issued="2026-08-17">\n'
        "<inv:supplier>Ada Components Ltd</inv:supplier>\n"
        "<inv:terms>net30,eur,no-refund</inv:terms>\n"
        f"{items}</inv:invoice>\n"
    ).encode()


def _python_net(root):
    """Total quantity x unit price over the whole invoice, in Python.

    The same sum the stylesheet's recursive template produces, read out of the
    tree with two namespace-mapped XPath expressions.
    """
    quantities = root.xpath("inv:line/@quantity", namespaces=NS)
    prices = root.xpath("inv:line/inv:unitPrice/text()", namespaces=NS)
    return sum(int(q) * float(p) for q, p in zip(quantities, prices))


def _first_error(schema):
    """The source line and message of a failed validation's first complaint.

    Validation errors accumulate on the validator's own error_log, which is reset
    at the start of each validate() call — so read it before validating anything
    else. Column is 0 for XML Schema errors, so only the line is worth showing.
    """
    entry = schema.error_log[0]
    return f"line {entry.line}: {entry.message}"


def _probe(label, codec, sample):
    """Hand libxml2 a tiny document in `label` and say what came back.

    Python encodes the bytes — its codec set is complete on both platforms — so
    the only thing left under test inside the try is whether libxml2 has a
    converter for the name in the XML declaration. A name it lacks gives
    `XMLSyntaxError: Unsupported encoding: <name>` with the line and column of
    the declaration appended, and the message is returned rather than the
    exception raised, so that one missing converter cannot abort the whole run.
    """
    raw = f"<?xml version='1.0' encoding='{label}'?><n>{sample}</n>".encode(codec)
    try:
        return f"decoded {etree.fromstring(raw).text}"
    except etree.LxmlError as exc:
        return str(exc).split(",")[0]


def run(lines):
    """Parse, validate, transform, cross-check and probe encodings; return a Result.

    The three timed steps are the ones libxml2 and libxslt actually do: the
    parse, the XML Schema validation, and the XSLT transform. lxml releases the
    GIL inside all three, so calling this from a background thread genuinely
    overlaps with the UI rather than only deferring the freeze.

    The tampered document is the same invoice with a non-integer quantity, so the
    second check is a real xs:positiveInteger complaint at the source line
    libxml2 reported — not a generic failure icon.
    """
    raw = invoice_xml(lines)

    started = time.perf_counter()
    tree = etree.fromstring(raw).getroottree()
    parsed = (time.perf_counter() - started) * 1000.0

    schema = etree.XMLSchema(etree.XML(SCHEMA))
    started = time.perf_counter()
    valid = schema.validate(tree)
    validated = (time.perf_counter() - started) * 1000.0

    tampered = etree.fromstring(raw.replace(b'quantity="', b'quantity="x', 1))
    rejected = not schema.validate(tampered)
    complaint = _first_error(schema) if rejected else "accepted, which it should not be"

    transform = etree.XSLT(etree.XML(STYLESHEET))
    started = time.perf_counter()
    statement = str(transform(tree, vat=VAT))
    transformed = (time.perf_counter() - started) * 1000.0

    rendered = [
        tuple(line.split("\t", 1)) for line in statement.splitlines() if "\t" in line
    ]
    net = dict(rendered)["net"]

    return Result(
        statement=rendered,
        checks=[
            ("invoice against XSD", "valid" if valid else "rejected"),
            ("tampered copy", complaint),
            ("net: XSLT vs Python", f"{net} vs {_python_net(tree.getroot()):.2f}"),
        ],
        encodings=[(label, _probe(label, codec, s)) for label, codec, s in ENCODINGS],
        timings=(
            f"{len(raw):,} bytes parsed in {parsed:.1f} ms, "
            f"validated in {validated:.1f} ms, transformed in {transformed:.1f} ms"
        ),
    )
