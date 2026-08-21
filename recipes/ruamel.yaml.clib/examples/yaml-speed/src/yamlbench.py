"""Timing the compiled YAML path against the pure-Python one.

Every function here returns plain values, so the Flet app never touches
ruamel.yaml itself.
"""

import io
import time

import ruamel.yaml
from ruamel.yaml import YAML
from ruamel.yaml.parser import Parser

RECORD_COUNTS = (100, 400, 1000)
REPS = 3

COMMENTED = """\
# written by the fleet controller - hand edits are preserved
service: edge-sync    # the dashboards key off this name
replicas: 3
hosts:
  - 10.0.0.7
  - 10.0.1.7
"""


def backend():
    """Report which parser `YAML(typ="safe")` will really use, by identity.

    ruamel.yaml wraps its `import _ruamel_yaml` in a bare `except` and falls back
    to the pure-Python parser without a word, so a working app is no evidence that
    the accelerator shipped. Comparing the class the instance is holding against
    `ruamel.yaml.parser.Parser` answers the question for the exact object about to
    be used, and stays right when someone passes `pure=True`.

    `get_version_string()` names the libyaml generation the C sources derive from,
    not this package's version, so it stays 0.1.7 across releases.
    """
    yaml = YAML(typ="safe")
    accelerated = yaml.Parser is not Parser
    libyaml = ""
    if accelerated:
        import _ruamel_yaml

        libyaml = _ruamel_yaml.get_version_string()
    version = ".".join(str(part) for part in ruamel.yaml.version_info[:3])
    return {
        "accelerated": accelerated,
        "label": f"{yaml.Parser.__name__} · ruamel.yaml {version}"
        + (f" · libyaml {libyaml}" if libyaml else ""),
    }


def document(records):
    """Build a fleet inventory with `records` host entries, as YAML text."""
    lines = ["service: edge-sync", "replicas: 3", "hosts:"]
    for index in range(records):
        lines += [
            f"  - id: node-{index:05d}",
            f"    host: 10.{index % 250}.{index // 250}.7",
            f"    port: {8000 + index % 1000}",
            f"    enabled: {'true' if index % 3 else 'false'}",
            f"    weight: {index * 0.5:.2f}",
            "    tags: [alpha, beta, gamma]",
            f'    note: "host {index} in the edge fleet"',
        ]
    return "\n".join(lines) + "\n"


def measure(records):
    """Load and dump one document both ways, and time the default path too.

    The two `YAML` objects differ in nothing but `pure=`, so the same constructor
    and the same representer run either side of the comparison and the ratio
    isolates the compiled reader, parser and emitter. Each figure is the best of
    `REPS` runs: a phone's scheduler can add time to a run but never remove it.

    The third timing is the one that surprises people. `YAML()` with no arguments
    is the round-trip loader, and no compiled parser exists for it at any version
    of this wheel, so it stays on pure Python however much you accelerate.

    `agree` compares the two results because a speedup that came from the fast
    path doing less work would not be a speedup.
    """
    text = document(records)
    fast = YAML(typ="safe")
    slow = YAML(typ="safe", pure=True)
    parsed = fast.load(text)
    return {
        "records": records,
        "bytes": len(text.encode()),
        "load_fast": _best(lambda: fast.load(text)),
        "load_slow": _best(lambda: slow.load(text)),
        "dump_fast": _best(lambda: _emit(fast, parsed)),
        "dump_slow": _best(lambda: _emit(slow, parsed)),
        "load_round_trip": _best(lambda: YAML().load(text)),
        "agree": fast.load(text) == slow.load(text),
    }


def report(result):
    """Turn one `measure()` result into the table and the caption below it."""
    table = "\n".join(
        (
            f"{'':>5}{'C':>9}{'Python':>9}{'ratio':>8}",
            _row("load", result["load_fast"], result["load_slow"]),
            _row("dump", result["dump_fast"], result["dump_slow"]),
        )
    )
    note = (
        f"{result['bytes'] / 1000:.0f} KB · best of {REPS} · milliseconds · both paths "
        f"returned {'the same data' if result['agree'] else 'DIFFERENT data'}.\n"
        f"Plain YAML() loaded it in {result['load_round_trip']:.0f} ms and has no "
        "compiled parser to switch to."
    )
    return table, note


def comment_demo():
    """Re-emit one commented config through both loaders, and return the text.

    This is the bill for the speed. The accelerator serves `typ="safe"`, whose
    constructor keeps values and throws everything else away, so a safe round trip
    returns plain dicts and lists and loses the comments, the key order and the
    block layout. The round-trip loader keeps the comments and the order, and
    still renormalises the sequence indentation.
    """
    round_trip = YAML()
    safe = YAML(typ="safe")
    return {
        "source": COMMENTED,
        "round_trip": _emit(round_trip, round_trip.load(COMMENTED)),
        "safe": _emit(safe, safe.load(COMMENTED)),
    }


def _row(name, fast, slow):
    """One timing row: the two measurements and what the C path bought."""
    return f"{name:>5}{fast:>9.1f}{slow:>9.1f}{slow / fast:>7.1f}x"


def _emit(yaml, data):
    """Dump to a string, because `YAML.dump` writes to a stream."""
    stream = io.StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def _best(call):
    """Fastest of `REPS` runs of `call`, in milliseconds."""
    timings = []
    for _ in range(REPS):
        started = time.perf_counter()
        call()
        timings.append((time.perf_counter() - started) * 1000)
    return min(timings)
