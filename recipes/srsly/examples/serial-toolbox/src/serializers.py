import gc
import os
import time

import msgpack
import srsly

COUNTS = ("200", "1000", "2000")

FORMATS = (
    ("json", srsly.json_dumps, srsly.json_loads),
    ("msgpack", srsly.msgpack_dumps, srsly.msgpack_loads),
    ("pickle", srsly.pickle_dumps, srsly.pickle_loads),
    ("yaml", srsly.yaml_dumps, srsly.yaml_loads),
)

# Both numbers on one line, because the whole point of the app is that they are
# different numbers: the first is the fork frozen inside srsly, the second is the
# msgpack wheel installed next to it.
HEADLINE = (
    f"srsly {srsly.__version__} · vendored msgpack "
    f"{'.'.join(map(str, srsly.msgpack.version))} · msgpack wheel "
    f"{'.'.join(map(str, msgpack.version))}"
)


def make_records(count):
    """Build the record set: short repeated keys around values that keep changing.

    Two of the fields are chosen to expose what srsly's JSON does to a float,
    in every record rather than in most of them. `value` is a third plus a
    seventh of the index: both are repeating fractions, so it never lands on a
    dyadic float such as 1.5 that a text format would carry through unchanged,
    and it always needs more digits than ujson writes. `drift` stays under
    5e-11 even at the largest count, which is where ujson's ten digits after
    the decimal point round to zero -- and it never falls back to an exponent.
    """
    return [
        {
            "id": index,
            "sensor": f"sensor-{index % 97}",
            "value": 1 / 3 + index / 7,
            "drift": (index + 1) * 3.2e-15,
            "unit": "degC",
            "enabled": bool(index % 3),
            "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
        }
        for index in range(count)
    ]


def bench(records):
    """Round-trip the records through each format and time both directions.

    Returns plain tuples -- label, payload size in bytes, encode and decode
    milliseconds, and whether the object that came back compares equal to the
    one that went in. That last column is the interesting one: msgpack, pickle
    and YAML carry a float through unchanged, and JSON does not, because
    srsly's JSON is a 2016 ujson that writes ten digits after the point.
    """
    rows = []
    for label, dump, load in FORMATS:
        started = time.perf_counter()
        blob = dump(records)
        encoded = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        restored = load(blob)
        decoded = (time.perf_counter() - started) * 1000

        size = len(blob.encode("utf-8")) if isinstance(blob, str) else len(blob)
        rows.append((label, size, encoded, decoded, restored == records))
    return rows


def store(records):
    """Write the records through srsly's file API and read them straight back.

    The read_*/write_* pairs take a path and own the file handle, so one call
    puts a whole collection on disk. JSONL and its gzip variant exist only as
    file functions -- there is no jsonl_dumps to go with them -- which is why a
    line-delimited corpus is the case the file API is really for.
    """
    data_dir = os.getenv("FLET_APP_STORAGE_DATA", ".")
    rows = []
    for name, write, read in (
        ("records.jsonl", srsly.write_jsonl, srsly.read_jsonl),
        ("records.jsonl.gz", srsly.write_gzip_jsonl, srsly.read_gzip_jsonl),
        ("records.msgpack", srsly.write_msgpack, srsly.read_msgpack),
    ):
        path = os.path.join(data_dir, name)
        write(path, records)
        rows.append((name, os.path.getsize(path), len(list(read(path)))))
    return rows


def _loader(module):
    """Name the import machinery that produced a module.

    `ExtensionFileLoader` means a compiled extension is in use and anything else
    means Python source. `__file__` is the obvious thing to look at instead, but
    a native extension on Android can have none at all, so ask the loader.
    """
    return type(getattr(module, "__loader__", None)).__name__


def vendored():
    """Report the four serialisers srsly carries inside itself.

    Every version here comes from the copy inside the package rather than from
    anything installed beside it, and each one moves only when srsly re-vendors.
    Two of the four are compiled and two are Python, which is most of the
    explanation for the timings in the table above. The ujson number is the one
    to look at: 1.35 is a 2016 ultrajson, and it is why the JSON row says no.
    """
    return (
        (
            "msgpack",
            ".".join(map(str, srsly.msgpack.version)),
            _loader(srsly.msgpack._packer),
        ),
        ("ujson", srsly.ujson.ujson.__version__, _loader(srsly.ujson.ujson)),
        (
            "cloudpickle",
            srsly.cloudpickle.__version__,
            _loader(srsly.cloudpickle.cloudpickle),
        ),
        (
            "ruamel.yaml",
            srsly.ruamel_yaml.__version__,
            _loader(srsly.ruamel_yaml.main),
        ),
    )


def two_msgpacks():
    """Pack the same values with both msgpack implementations in this process.

    Plain data comes out byte-identical, which is why the split stays invisible
    until something crosses it. An `ExtType` is that something: the one built by
    the msgpack wheel is not the class srsly's packer checks for, so it falls
    through to the ordinary tuple path, ships as a two-element array, and comes
    back as a list. Nothing raises anywhere along the way.
    """
    record = {"id": 7, "tags": ["alpha", "beta"], "score": 0.5}
    same = srsly.msgpack_dumps(record) == msgpack.packb(record, use_bin_type=True)
    return (
        ("same bytes for a record", "yes" if same else "no"),
        ("srsly ExtType comes back", _ext_round_trip(srsly.msgpack.ExtType)),
        ("msgpack ExtType comes back", _ext_round_trip(msgpack.ExtType)),
    )


def _ext_round_trip(ext_type):
    """Send one extension value through srsly's packer and describe what returns."""
    return repr(
        srsly.msgpack_loads(srsly.msgpack_dumps({"x": ext_type(42, b"xy")}))["x"]
    )


def gc_after_bad_read():
    """Feed msgpack_loads one byte that is not msgpack, then report the GC state.

    srsly wraps the unpack in gc.disable()/gc.enable() with no try/finally, so a
    raise on the way through leaves the cyclic collector switched off for the
    rest of the process. Switch it back on before returning, or the app pays for
    the demonstration.
    """
    try:
        srsly.msgpack_loads(b"\xc1")
    except Exception:
        pass
    enabled = gc.isenabled()
    gc.enable()
    return enabled
