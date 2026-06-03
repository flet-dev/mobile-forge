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
    pure-Python fallback wouldn't expose `escape` from this module."""
    from markupsafe import _speedups

    assert callable(_speedups.escape)
    assert str(_speedups.escape("<&>")) == "&lt;&amp;&gt;"
