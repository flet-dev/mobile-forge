# lxml invoice xslt

A slider sets how many line items the invoice has — 25 to 250. Let it go and the app builds
the document, validates it against a bundled
[XML Schema](https://lxml.de/validation.html#xmlschema), runs it through an XSLT 1.0
stylesheet that adds the money up itself, and reports how long each step took.

What it demonstrates:

- **XSLT, on a phone, doing arithmetic XSLT 1.0 cannot express.** There is no way to sum a
  product over a node-set in XSLT 1.0, so `net` comes out of a tail-recursive named template
  that walks the line items one at a time. Three
  [EXSLT](https://exslt.github.io/) modules fill in the rest —
  `math:max` for the dearest unit price, `str:tokenize` to split the payment terms, and
  `date:year` for the header — and all three come from the `libexslt` these wheels link. The
  VAT rate is passed in from Python as an
  [XSLT parameter](https://lxml.de/xpathxslt.html#stylesheet-parameters), and the stylesheet
  prints it back into the row label so you can see it arrived.
- **The totals are checkable, not just present.** The `net: XSLT vs Python` row sets the
  stylesheet's answer against the same sum computed in Python from two namespace-mapped
  [XPath](https://lxml.de/xpathxslt.html) expressions. Unit prices are whole multiples of
  0.05, so both are exact to the cent and the two strings should match character for
  character.
- **A validation failure you can read.** The invoice is validated twice: once as generated,
  and once as a tampered copy whose first `quantity` is not an integer. The second row is
  libxml2's own complaint, pulled off the validator's
  [`error_log`](https://lxml.de/api.html#error-logging) with the source line it came from —
  `line 5: Element '{urn:example:invoice}line', attribute 'quantity': 'x1' is not a valid
  value of the atomic type 'xs:positiveInteger'.`
- **The one thing that differs between Android and iOS.** The last four rows hand libxml2 a
  tiny document in ISO-8859-2, windows-1252, Shift_JIS and KOI8-R. The first two decode on
  both platforms — windows-1252 is a libxml2 built-in everywhere, ISO-8859-2 is a built-in on
  Android and libiconv's job on iOS; the other two need iconv, which iOS has and Android
  does not, so on Android each comes back `Unsupported encoding: <name>`. Python encodes
  the bytes in every case, so the only thing being tested is libxml2's converter set — which
  the header line names directly as `libxml2 features: … iconv …`.
- **Parsing and transforming off the UI thread** — the whole run happens in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the slider disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that a background
  thread needs. lxml releases the GIL inside the parse, the validation and the transform, so
  this genuinely overlaps with the UI rather than only deferring the freeze.

The document is generated in Python from a fixed seed rather than shipped as an asset, so
every install produces the same invoice and the same totals and two devices can be compared
directly. The slider stops at 250 because `xsltMaxDepth` counts nested template calls *and*
their parameters, so each line item costs two of its 3000 frames rather than one: bisected
against desktop lxml 6.1.1, whose bundled libxslt is 1.1.43, the recursion survives 1497 items
and dies at 1498 with *A potential infinite template recursion was detected* — not at 3000 as
the limit's name suggests. These wheels link libxslt 1.1.45, where the accounting is the same
but the boundary has not been re-measured; 250 leaves enough headroom either way. Nothing is
written to disk.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
