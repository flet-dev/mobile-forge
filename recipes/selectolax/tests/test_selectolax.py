def test_modest_parser():
    """Parse HTML + CSS-select with the Modest engine."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser("<div><p class='x'>hello</p><p class='x'>world</p></div>")
    nodes = tree.css("p.x")
    assert [n.text() for n in nodes] == ["hello", "world"]


def test_lexbor_parser():
    """Parse HTML + CSS-select with the Lexbor engine."""
    from selectolax.lexbor import LexborHTMLParser

    tree = LexborHTMLParser("<ul><li>a</li><li>b</li><li>c</li></ul>")
    items = tree.css("li")
    assert [n.text() for n in items] == ["a", "b", "c"]
