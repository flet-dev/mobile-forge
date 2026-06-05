def test_escape():
    """The MarkupSafe C accelerator is the reason this is a recipe — without
    it, escape() falls back to slow pure-Python."""
    from markupsafe import Markup, escape

    assert str(escape("<script>alert('xss')</script>")) == (
        "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;"
    )

    # Markup pass-through: already-safe strings shouldn't be double-escaped.
    safe = Markup("<b>hi</b>")
    assert str(escape(safe)) == "<b>hi</b>"


def test_speedups_loaded():
    """Confirms the C extension `markupsafe._speedups` actually loaded; the
    pure-Python fallback wouldn't expose the C accelerator at all.

    Markupsafe 3.0 renamed the C entry point: `escape` (2.x) became
    `_escape_inner` (3.x). The public `markupsafe.escape` dispatches to
    it. We probe whichever name the installed version exposes so the
    test stays useful across version bumps."""
    from markupsafe import _speedups

    fn = getattr(_speedups, "_escape_inner", None) or getattr(_speedups, "escape", None)
    assert callable(fn), (
        f"neither _escape_inner nor escape on markupsafe._speedups; "
        f"have: {[n for n in dir(_speedups) if not n.startswith('__')]}"
    )
    assert str(fn("<&>")) == "&lt;&amp;&gt;"
