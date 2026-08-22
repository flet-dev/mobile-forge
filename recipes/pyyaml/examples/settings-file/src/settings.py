"""The YAML work behind this example: emit, save, read back, and diagnose.

Everything that touches PyYAML lives here and hands `main.py` plain strings and
tuples, so the screen never has to know which loader produced what.
"""

import os
import platform
import time

import yaml

# Importing the C classes by name at module top is deliberate: PyYAML's fallback
# is silent — with the extension missing, `CSafeLoader` is simply absent from the
# namespace and `safe_load` keeps working several times slower. This turns that
# into an ImportError on the first line of the app instead.
from yaml import CSafeDumper, CSafeLoader
from yaml import _yaml as libyaml

EMIT = {"sort_keys": False, "allow_unicode": True}

SNIPPET = "version: 3\nretries:\t3\nlabel: café — edge\ntimeout: 2.5\nenabled: yes\n"

LOADERS = (("SafeLoader", yaml.SafeLoader), ("CSafeLoader", CSafeLoader))


def settings_path():
    """The settings file's home: app-private storage, or the cwd on desktop."""
    return os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.yaml")


def make_settings(blocks):
    """Build a settings document with `blocks` service entries.

    Deterministic, so the same slider position gives the same bytes on every
    device and two phones can be compared directly. The non-ASCII `label` is
    there to make `allow_unicode` visible in the file that lands on disk.
    """
    return {
        "version": 3,
        "label": "café — edge fleet",
        "services": {
            f"service-{index:04d}": {
                "host": f"10.0.{index // 256}.{index % 256}",
                "port": 8000 + index,
                "retries": index % 5,
                "enabled": bool(index % 3),
                "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
                "timeout": 1.5 + (index % 10) / 10,
            }
            for index in range(blocks)
        },
    }


def _fastest(work, reps=3):
    """Best of `reps` calls of `work`, in milliseconds, plus its last result."""
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def round_trip(blocks):
    """Emit a settings document both ways, save it, and read it back both ways.

    Returns `(summary, rows, verdict)`: a line about the file, four table rows of
    `(step, call, ms, result)`, and the ratio between the implementations. The
    two "identical" cells are computed rather than asserted — a speedup between
    implementations that disagreed about the data would be worth nothing, so the
    row says which happened.

    The timings run on bytes that made a real round trip through the filesystem,
    not on a string held in memory, because that is the shape a settings file
    actually has.
    """
    document = make_settings(blocks)
    emit_c, text = _fastest(lambda: yaml.dump(document, Dumper=CSafeDumper, **EMIT))
    emit_pure, pure = _fastest(
        lambda: yaml.dump(document, Dumper=yaml.SafeDumper, **EMIT)
    )

    path = settings_path()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    with open(path, encoding="utf-8") as handle:
        on_disk = handle.read()

    load_pure, parsed_pure = _fastest(lambda: yaml.safe_load(on_disk))
    load_c, parsed_c = _fastest(lambda: yaml.load(on_disk, Loader=CSafeLoader))

    summary = "{} services · {} · {:,} B on disk".format(
        len(document["services"]), os.path.basename(path), os.path.getsize(path)
    )
    rows = [
        ("emit", "yaml.safe_dump", f"{emit_pure:.2f}", f"{len(pure.encode()):,} B"),
        (
            "emit",
            "Dumper=CSafeDumper",
            f"{emit_c:.2f}",
            "identical bytes" if pure == text else "DIFFERENT BYTES",
        ),
        (
            "load",
            "yaml.safe_load",
            f"{load_pure:.2f}",
            "{} services".format(len(parsed_pure["services"])),
        ),
        (
            "load",
            "Loader=CSafeLoader",
            f"{load_c:.2f}",
            "same object" if parsed_c == parsed_pure else "DIFFERENT OBJECT",
        ),
    ]
    verdict = "C is {:.1f}x faster reading and {:.1f}x faster writing {:,} B{}".format(
        load_pure / load_c,
        emit_pure / emit_c,
        len(text.encode()),
        "" if parsed_pure == document else " — round trip LOST data",
    )
    return summary, rows, verdict


def _describe(document):
    """Name what a parse produced.

    Valid YAML is not necessarily a mapping: an emptied editor parses to `None`
    and a stray line of prose parses to a string, both without complaint from
    either loader. Saying so beats asserting a shape the user can delete.
    """
    if isinstance(document, dict):
        return f"{len(document)} key" if len(document) == 1 else f"{len(document)} keys"
    if document is None:
        return "empty document"
    return f"a bare {type(document).__name__}"


def parse_report(text, loader):
    """Parse `text` and describe the outcome the way an editing screen would.

    Returns the outcome, where it happened, and whether the exception's mark
    could produce a source snippet — the one thing the C loader cannot do, since
    libyaml never hands PyYAML the buffer the caret would point into. Marks count
    lines and columns from zero, so both are shifted for display.

    The catch is deliberately everything rather than `yaml.YAMLError`: a loader is
    only exception-safe up to the point where it hands a scalar to
    `SafeConstructor`, and that stage lets plain Python errors through — the
    perfectly ordinary typo `2026-02-30` reaches `datetime` and raises
    `ValueError`, `!!bool 'zzz'` raises `KeyError`, `!!timestamp 'zzz'` raises
    `AttributeError`, and a deeply nested flow collection exhausts the pure
    scanner's stack with `RecursionError`. All four are reachable from a text
    field, none is a `YAMLError`, and Flet reports an unhandled error in an event
    handler by crashing the session — so anything that gets this far belongs in
    the table under its own name, with no position to report.
    """
    try:
        document = yaml.load(text, Loader=loader)
    except Exception as error:
        mark = getattr(error, "problem_mark", None)
        where = f"line {mark.line + 1} col {mark.column + 1}" if mark else "unreported"
        snippet = "yes" if mark is not None and mark.get_snippet() else "none"
        return type(error).__name__, where, snippet
    return _describe(document), "—", "—"


def version_line(platform_name):
    """Name the versions, the capability, and how the extension got loaded.

    `_yaml.__file__` is the last field because it is the one expected to differ
    between the two platforms: Flet moves native extensions out of site-packages
    and leaves a marker at the import path, so this reports whatever the import
    system resolved rather than the name in the wheel.
    """
    origin = getattr(libyaml, "__file__", None)
    return (
        f"PyYAML {yaml.__version__} · libyaml {libyaml.get_version_string()} · "
        f"__with_libyaml__ {yaml.__with_libyaml__} · "
        f"Python {platform.python_version()} · {platform_name} · "
        f"_yaml.__file__ {os.path.basename(origin) if origin else 'none'}"
    )
