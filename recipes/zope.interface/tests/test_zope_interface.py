def test_basic():
    """zope.interface ships a C accelerator (`_zope_interface_coptimizations`).
    Define an interface, declare a provider, verify membership — that touches
    the C path on both `directlyProvides` and `verifyObject`."""
    from zope.interface import Interface, implementer
    from zope.interface.verify import verifyObject

    class IGreeter(Interface):
        def greet(name):
            """Return a greeting."""

    @implementer(IGreeter)
    class Greeter:
        def greet(self, name):
            return f"hi, {name}"

    g = Greeter()
    assert IGreeter.providedBy(g)
    assert verifyObject(IGreeter, g)
    assert g.greet("world") == "hi, world"


def test_speedups_present():
    """Sanity: the recipe's whole purpose is to ship the C extension, so
    verify it's importable."""
    from zope.interface import _zope_interface_coptimizations  # noqa: F401
