"""Interfaces, runtime verification and an adapter registry for one small domain.

Everything the example knows about zope.interface lives here: the interfaces, the
records that declare them, the adapters that turn a record into a summary, and the
deliberately broken classes that `verifyObject` is asked to reject. Nothing in this
module imports Flet, and every function returns plain values.
"""

import time
from importlib.metadata import version

from zope.interface import Attribute, Interface, implementer, providedBy
from zope.interface.adapter import AdapterRegistry, LookupBase
from zope.interface.exceptions import Invalid
from zope.interface.interface import adapter_hooks
from zope.interface.verify import verifyObject

VERSION = f"zope.interface {version('zope.interface')}"
DETAIL_WIDTH = 46
BENCHMARK_LOOKUPS = 200_000
ACCELERATOR = "_zope_interface_coptimizations"


class IRecord(Interface):
    """Anything the catalogue holds."""

    identifier = Attribute("Stable identifier, unique within its kind.")


class IUser(IRecord):
    """A person. Extends IRecord, which is what makes the fallback lookup work."""


class IOrder(IRecord):
    """A purchase."""


class IEvent(IRecord):
    """Something that happened."""


class ISummary(Interface):
    """A one-line description of a record, plus a longer form.

    An interface body declares, it does not define: `headline` is an `Attribute`
    with no value, and `detail` is written without `self` because the signature
    describes how a caller invokes it.
    """

    headline = Attribute("Single line, already formatted.")

    def detail(width):
        """Return the long form, clipped to `width` characters."""


@implementer(IUser)
class User:
    """A record providing IUser, and IRecord through it."""

    def __init__(self, identifier, name, email):
        self.identifier = identifier
        self.name = name
        self.email = email


@implementer(IOrder)
class Order:
    """A record providing IOrder."""

    def __init__(self, identifier, total, currency):
        self.identifier = identifier
        self.total = total
        self.currency = currency


@implementer(IEvent)
class Event:
    """A record providing IEvent, which starts out with no adapter of its own."""

    def __init__(self, identifier, kind, actor):
        self.identifier = identifier
        self.kind = kind
        self.actor = actor


@implementer(ISummary)
class GenericSummary:
    """The fallback adapter, registered against the base interface IRecord."""

    def __init__(self, record):
        self.record = record
        self.headline = f"{type(record).__name__} {record.identifier}"

    def detail(self, width):
        """Say only what IRecord guarantees, because that is all it was told."""
        return f"Reached through IRecord: identifier {self.record.identifier}"[:width]


@implementer(ISummary)
class UserSummary:
    """The adapter registered for IUser."""

    def __init__(self, record):
        self.record = record
        self.headline = f"{record.name} <{record.email}>"

    def detail(self, width):
        """Use the fields IUser adds on top of IRecord."""
        return f"{self.record.name} signs in as {self.record.email}"[:width]


@implementer(ISummary)
class OrderSummary:
    """The adapter registered for IOrder."""

    def __init__(self, record):
        self.record = record
        self.headline = f"{record.total:.2f} {record.currency}"

    def detail(self, width):
        """Use the fields IOrder adds on top of IRecord."""
        amount = f"{self.record.total:.2f} {self.record.currency}"
        return f"Order {self.record.identifier} came to {amount}"[:width]


@implementer(ISummary)
class EventSummary:
    """The adapter for IEvent, registered and withdrawn while the app runs."""

    def __init__(self, record):
        self.record = record
        self.headline = f"{record.kind} by {record.actor}"

    def detail(self, width):
        """Use the fields IEvent adds on top of IRecord."""
        return f"{self.record.kind} raised by {self.record.actor}"[:width]


REGISTRY = AdapterRegistry()
REGISTRY.register([IRecord], ISummary, "", GenericSummary)
REGISTRY.register([IUser], ISummary, "", UserSummary)
REGISTRY.register([IOrder], ISummary, "", OrderSummary)

RECORDS = (
    User("u-1041", "Ada Lovelace", "ada@example.org"),
    Order("o-2277", 148.5, "EUR"),
    Event("e-9003", "password-reset", "u-1041"),
)


def _summary_hook(provided, obj):
    """Resolve `ISummary(record)` through REGISTRY.

    Calling an interface is the ergonomic form of a lookup, and `adapter_hooks` is
    what connects it to a particular registry: with no hook installed,
    `ISummary(record)` raises `TypeError` however much has been registered.
    """
    return REGISTRY.queryAdapter(obj, provided)


adapter_hooks.append(_summary_hook)


def accelerator():
    """Report whether the compiled lookup path is the one actually in use.

    The C module is never imported by name at run time — `zope.interface._compat`
    swaps compiled objects in for the Python ones as each module is imported — so
    importing it proves only that it exists. Asking where a swapped name ended up
    living is the check that means something, and `LookupBase` is the registry
    lookup machinery the accelerator exists for.
    """
    return LookupBase.__module__.endswith(ACCELERATOR), LookupBase.__module__


def use_event_adapter(enabled):
    """Register the IEvent adapter, or withdraw it: registering None removes."""
    REGISTRY.register([IEvent], ISummary, "", EventSummary if enabled else None)


def summarise(record):
    """Adapt one record to ISummary and report what the registry decided.

    `declares` is what the record itself claims; `resolved` is the adapter class
    the registry picked for that claim. An Event with no registration of its own
    resolves to the IRecord fallback, which is the case worth watching.
    """
    summary = ISummary(record)
    declares = ", ".join(i.__name__ for i in providedBy(record).interfaces())
    return {
        "record": type(record).__name__,
        "declares": declares,
        "resolved": type(summary).__name__,
        "headline": summary.headline,
        "detail": summary.detail(DETAIL_WIDTH),
    }


class Named:
    """Give a verification failure a readable subject.

    Every message starts with `repr(target)`, so without this each line on screen
    would carry a memory address that changes on every run.
    """

    def __repr__(self):
        return f"<{type(self).__name__}>"


@implementer(ISummary)
class Complete(Named):
    """Satisfies ISummary: the attribute is there and the signature matches."""

    headline = "Complete"

    def detail(self, width):
        """Take the argument the interface says a caller will pass."""
        return "as declared"[:width]


@implementer(ISummary)
class NoHeadline(Named):
    """Declares ISummary but never provides the `headline` attribute."""

    def detail(self, width):
        """Match the declaration; the attribute is the missing half."""
        return "as declared"[:width]


@implementer(ISummary)
class NoDetail(Named):
    """Declares ISummary and omits the `detail` method entirely."""

    headline = "NoDetail"


@implementer(ISummary)
class WrongArity(Named):
    """Declares ISummary but its `detail` refuses the argument callers pass."""

    headline = "WrongArity"

    def detail(self):
        """Take no width, which is the whole defect."""
        return "wrong"


class Undeclared(Named):
    """Has everything ISummary asks for and never says so."""

    headline = "Undeclared"

    def detail(self, width):
        """Match the declaration, which is not the same as making one."""
        return "as declared"[:width]


CANDIDATES = (Complete, NoHeadline, NoDetail, WrongArity, Undeclared)


def verify_candidates():
    """Run `verifyObject` over each candidate and return (name, ok, message).

    The message is the reason to reach for zope.interface rather than a
    `typing.Protocol`: it names the attribute or the method at fault, and for a
    method it prints the signature that could not satisfy the contract. Every
    verification failure derives from `Invalid`, so one except clause covers a
    missing attribute, a missing method, a bad signature and a missing
    declaration alike.
    """
    results = []
    for candidate in CANDIDATES:
        try:
            verifyObject(ISummary, candidate())
        except Invalid as exc:
            results.append((candidate.__name__, False, str(exc)))
        else:
            results.append((candidate.__name__, True, "verifyObject returned True"))
    return results


def lookup_rate(iterations=BENCHMARK_LOOKUPS):
    """Time repeated adapter lookups and return (elapsed_seconds, per_second).

    A registry lookup is meant to be cheap enough to do on every call rather than
    cached, and this is the number that decides whether that is true on a given
    device. The Event is the record used because, until the switch registers an
    adapter for it, its lookup has to walk up to IRecord to find one.
    """
    record = RECORDS[-1]
    started = time.perf_counter()
    for _ in range(iterations):
        REGISTRY.queryAdapter(record, ISummary)
    elapsed = time.perf_counter() - started
    return elapsed, iterations / elapsed
