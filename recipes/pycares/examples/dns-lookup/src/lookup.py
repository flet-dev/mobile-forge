import dataclasses

import aiodns
import pycares

RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "TXT")
PUBLIC_NAMESERVERS = ["1.1.1.1", "8.8.8.8"]

_TYPE_NAMES = {
    getattr(pycares, name): name.removeprefix("QUERY_TYPE_")
    for name in dir(pycares)
    if name.startswith("QUERY_TYPE_")
}


def system_nameservers():
    """What c-ares discovered on its own — ['127.0.0.1:53'] means it found none."""
    channel = pycares.Channel()
    try:
        return channel.servers
    finally:
        channel.close()


def _value(field):
    return field.decode(errors="replace") if isinstance(field, bytes) else str(field)


def describe(record):
    """One line per answer: name, type, ttl, then the record-specific payload."""
    payload = " ".join(_value(v) for v in dataclasses.astuple(record.data))
    kind = _TYPE_NAMES.get(record.type, record.type)
    return f"{record.name}  {kind}  ttl={record.ttl}\n  {payload}"


async def lookup(host, qtype, nameservers):
    """Resolve one record type. `nameservers=None` uses whatever c-ares found."""
    resolver = aiodns.DNSResolver(nameservers=nameservers, timeout=5.0, tries=2)
    try:
        result = await resolver.query_dns(host, qtype)
        return [describe(record) for record in result.answer]
    finally:
        await resolver.close()
