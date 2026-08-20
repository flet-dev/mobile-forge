# markupsafe escape inspector

Type into the field and the same comment is built four ways: through
`Markup.format`, by concatenating first and blessing afterwards, by handing the raw
value straight to `Markup()`, and through an object that carries its own markup.
Each fragment is shown as literal source and then parsed back, so the count beside
it is the number of live elements your input smuggled into the page. Underneath are
the five characters `escape()` rewrites, and a button that times the C accelerator
against the pure-Python fallback on the device in your hand.

What it demonstrates:

- **`Markup()` is a promise, not a check** —
  [`Markup`](https://markupsafe.palletsprojects.com/page/escaping/#markupsafe.Markup)
  never looks at the string it is given; it declares the string already safe. So
  `Markup(value)` is an injection in one call, and
  `Markup("<b>" + value + "</b>")` is the same bug in a template's clothing —
  `Markup("<b>") + value` would have escaped it, because the operator escapes what it
  is combined with and the constructor does not.
- **Escaping is one function and five characters** —
  [`escape()`](https://markupsafe.palletsprojects.com/page/escaping/#markupsafe.escape)
  replaces `&`, `<`, `>`, `'` and `"` and touches nothing else. The table makes it hard
  to forget that this is an HTML rule and knows nothing about URLs, JavaScript or
  Markdown.
- **`__html__` moves the responsibility rather than removing it** — the
  [HTML representations](https://markupsafe.palletsprojects.com/page/html/) protocol
  lets a value render itself and `escape()` trusts the result verbatim, so `Comment`
  escapes its own text. It returns `Markup` rather than `str` on purpose: three of the
  four paths accept a plain string from `__html__`, but
  [`Markup.format`](https://markupsafe.palletsprojects.com/page/formatting/#format-method)
  escapes whatever it returns and the tags then arrive as visible text.
- **Which engine is live, and what it buys** — the header reads
  `markupsafe._escape_inner.__module__`, the one thing that says whether the C extension
  won the import. The button times both engines in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
  with the button disabled, a
  [`ProgressRing`](https://flet.dev/docs/controls/progressring/) up and the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.

Put a complete tag in the field and the same two panels go red every time, while the
escaped two never do however hard you try — that asymmetry is the whole library. Take the
tag out and all four go quiet: the danger arrives in the input, and only two of these four
ways of building one string care. The timing surprises. On desktop the accelerator ran two
to four times the fallback on short values, only 1.2x on 32 KB with nothing to escape, and
0.8x — slower than pure Python — on 32 KB holding a single `&`, which is why the panel
prints a bare multiple rather than "x faster". `escape()` cost several times its inner call
on a short string yet nothing measurable at 32 KB: the `Markup` wrapper is a fixed price
per call, not per byte. Read your own numbers on a phone.

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
