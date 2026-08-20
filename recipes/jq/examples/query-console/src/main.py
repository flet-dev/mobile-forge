"""Run jq programs against a bundled JSON document, on this device."""

import functools
import json
import operator
import platform
import re
import time
import types

import flet as ft

try:
    import jq
except Exception as error:  # the wheel may be missing or fail to load
    jq = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    IMPORT_ERROR = ""

REGIONS = ("north", "south", "east", "west")

QUALITIES = ("ok", "ok", "ok", "suspect", "missing")

TAGS = ("coastal", "alpine", "urban", "rural", "buoy", "airport")

MISSING = -99.0

OUTPUT_LIMIT = 1600


def document(stations=120, readings=24):
    """Build the JSON document every query runs against.

    Generated rather than bundled as a file, so the same build produces the same
    bytes on every device and one phone's timings can be compared with another's
    and with the desktop figures in the README. The shape is the one that makes
    jq worth having: a list of objects, each with a nested list of records, plus
    a couple of fields a real payload would carry and you would rather not leak.
    """
    out = []
    for i in range(stations):
        rows = []
        for j in range(readings):
            quality = QUALITIES[(i * 7 + j * 3) % len(QUALITIES)]
            temp = (
                MISSING
                if quality == "missing"
                else round(-8.0 + ((i * 13 + j * 29) % 470) / 10.0, 1)
            )
            rows.append(
                {
                    "at": f"2026-08-{1 + j % 28:02d}T{j % 24:02d}:00:00Z",
                    "tempC": temp,
                    "rh": 30 + (i * 5 + j * 11) % 65,
                    "quality": quality,
                }
            )
        out.append(
            {
                "id": f"ST-{i:04d}",
                "name": f"Station {i}",
                "region": REGIONS[i % len(REGIONS)],
                "online": bool((i * 3) % 7),
                # i % 4 rather than i: an uneven spread, so the tag ranking has
                # something to rank and two pairs of ties to break.
                "tags": [TAGS[(i % 4 + k) % len(TAGS)] for k in range((i % 3) + 1)],
                "api_token": f"tok_{i:04d}_secret",
                "position": {"lat": 40.0 + i / 100.0, "lon": -3.0 - i / 100.0},
                "readings": rows,
            }
        )
    return {"generated": "2026-08-20T00:00:00Z", "stations": out}


DOC = document()

DOC_TEXT = json.dumps(DOC)


def top_means(doc):
    """Five warmest stations by mean temperature, ignoring the missing sentinel.

    `functools.reduce`, not `sum`: CPython 3.12 gave `sum` compensated
    (Neumaier) summation over floats, while jq's `add` is a plain left fold, so
    the two disagree in the last two digits and the app would report DIFFERENT
    for an answer that is arithmetically right either way.
    """
    rows = []
    for station in doc["stations"]:
        temps = [r["tempC"] for r in station["readings"] if r["quality"] != "missing"]
        total = functools.reduce(operator.add, temps)
        rows.append(
            {
                "id": station["id"],
                "name": station["name"],
                "mean": total / len(temps),
            }
        )
    rows.sort(key=lambda row: -row["mean"])
    return rows[:5]


def sentinel_paths(doc):
    """Dotted paths of the first five numbers anywhere in the tree equal to -99.

    The point of the comparison: jq expresses this as `paths(numbers)` over the
    whole document, and Python needs a recursive walker that knows the document's
    shape well enough to descend it.
    """
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + [key])
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, path + [str(index)])
        elif node == MISSING:
            hits.append(".".join(path))

    walk(doc, [])
    return hits[:5]


def tag_index(doc):
    """Invert stations-to-tags into tags-to-stations, counted and ranked."""
    index = {}
    for station in doc["stations"]:
        for tag in station["tags"]:
            index.setdefault(tag, []).append(station["id"])
    rows = [
        {"tag": tag, "n": len(ids), "first": sorted(ids)[0]}
        for tag, ids in index.items()
    ]
    rows.sort(key=lambda row: (-row["n"], row["tag"]))
    return rows


def redacted(doc):
    """First station with every secret-looking key masked, at any depth."""
    pattern = re.compile("token|secret|password", re.I)

    def walk(node):
        if isinstance(node, dict):
            return {
                key: ("***" if pattern.search(key) else walk(value))
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node

    station = walk(doc["stations"][0])
    return {
        "id": station["id"],
        "api_token": station["api_token"],
        "tags": station["tags"],
    }


def csv_rows(doc):
    """Five online northern stations as CSV lines, matching jq's `@csv`.

    `json.dumps` for the non-string cells rather than `str`: jq keeps a number's
    literal spelling, so a maximum of 36.0 stays `36.0` where `str(int(...))`
    would print `36` and the two outputs would differ by one character.
    """
    out = []
    for station in doc["stations"]:
        if not (station["online"] and station["region"] == "north"):
            continue
        cells = [
            station["id"],
            station["name"],
            len(station["readings"]),
            max(r["tempC"] for r in station["readings"]),
        ]
        rendered = [
            '"' + cell.replace('"', '""') + '"'
            if isinstance(cell, str)
            else json.dumps(cell)
            for cell in cells
        ]
        out.append(",".join(rendered))
    return out[:5]


PRESETS = (
    (
        "means",
        """[ .stations[]
  | {id, name, mean: ([.readings[]
      | select(.quality != "missing")
      | .tempC] | add / length)}
] | sort_by(-.mean) | .[:5]""",
        top_means,
    ),
    (
        "sentinels",
        """[ paths(numbers) as $p
  | select(getpath($p) == -99)
  | $p | map(tostring) | join(".")
] | .[:5]""",
        sentinel_paths,
    ),
    (
        "tag index",
        """[ .stations[] | {id} + {tag: .tags[]} ]
| group_by(.tag)
| map({tag: .[0].tag, n: length, first: (map(.id) | sort | .[0])})
| sort_by(-.n, .tag)""",
        tag_index,
    ),
    (
        "redact",
        """.stations[0]
| walk(
    if type == "object"
    then with_entries(
      if (.key | test("token|secret|password"; "i"))
      then .value = "***" else . end)
    else . end)
| {id, api_token, tags}""",
        redacted,
    ),
    (
        "@csv",
        """[ .stations[]
  | select(.online and (.region == "north"))
  | [.id, .name, (.readings | length), ([.readings[].tempC] | max)]
  | @csv
] | .[:5]""",
        csv_rows,
    ),
    ("bad query", ".stations[] | mean_temperature", None),
)

TWINS = {name: twin for name, _, twin in PRESETS}


def source_lines(fn):
    """Count the source lines of `fn` that carry code, from its code objects.

    `inspect.getsource` raises `OSError: could not get source code` on device:
    Flet's `compile.packages` defaults to true, so the app ships as `.pyc` with
    no `.py` beside it. Line numbers survive in the code object, and nested
    functions live in `co_consts`, so walking that tree gives a figure that is
    the same on desktop and on device — and counting the lines rather than
    spanning them leaves out the docstring and the blank lines.
    """
    lines, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        lines.update(line for _, _, line in code.co_lines() if line)
        stack.extend(k for k in code.co_consts if isinstance(k, types.CodeType))
    return len(lines)


def render(values):
    """Format jq's output values the way `jq -r` prints them.

    Strings raw and everything else as indented JSON, then truncated: a query
    like `.` emits the whole document, and handing a quarter of a megabyte to
    one `Text` control buys nothing a reader can use.
    """
    body = "\n".join(
        value if isinstance(value, str) else json.dumps(value, indent=2)
        for value in values
    )
    if len(body) <= OUTPUT_LIMIT:
        return body
    return f"{body[:OUTPUT_LIMIT]}\n... {len(body) - OUTPUT_LIMIT:,} more characters"


def run_jq(program):
    """Compile and run one jq program over the cached document text.

    Returns the output values, the compile time and the run time in
    milliseconds. `input_text` on the cached string rather than
    `input_value(DOC)`, because `input_value` is `input_text(json.dumps(value))`
    and re-serialising the document on every keystroke-driven run is a cost the
    app can simply not pay.
    """
    started = time.perf_counter()
    compiled = jq.compile(program)
    middle = time.perf_counter()
    values = compiled.input_text(DOC_TEXT).all()
    done = time.perf_counter()
    return values, (middle - started) * 1000.0, (done - middle) * 1000.0


def run_twin(twin):
    """Run the hand-written Python equivalent and time it, in milliseconds."""
    started = time.perf_counter()
    values = twin(DOC)
    return values, (time.perf_counter() - started) * 1000.0


def main(page: ft.Page):
    """A jq console: pick or type a program, run it, see what it answered.

    Each preset ships with a hand-written Python function that computes the same
    thing, so the status line can report both timings and whether the two agree
    — the claim the app exists to make checkable. Without the wheel it degrades
    to running only the Python twins and says what the import raised.
    """

    def choose(preset):
        """Load a preset into the editable field and run it."""
        name, program, _ = preset
        query.value = program
        run_now(name)

    def run_now(name=""):
        """Run whatever is in the field, next to the twin if this is a preset.

        Runs inline rather than in
        [`page.run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread):
        jq holds the GIL for the whole call, so a worker thread would neither
        run in parallel nor let anything else make progress while it worked.

        Every failure path lands here on purpose. A bad program is a `ValueError`
        from `jq.compile`, a bad input or a type error at run time is a
        `ValueError` from the iterator, and an unhandled exception in a Flet
        handler ends the session with a crash screen — so the message goes on
        screen instead.
        """
        program = (query.value or "").strip()
        twin = TWINS.get(name)
        result.color = None
        if not program:
            status.value = "type a jq program, or pick one above"
            result.value = ""
            comparison.value = ""
            page.update()
            return
        try:
            if jq is None:
                if twin is None:
                    raise RuntimeError("jq is missing and this query has no twin")
                expected, twin_ms = run_twin(twin)
                status.value = f"jq absent — Python twin only, {twin_ms:.2f} ms"
                result.value = render([expected])
                comparison.value = f"{source_lines(twin)} lines of Python"
                page.update()
                return
            values, compile_ms, run_ms = run_jq(program)
        except Exception as error:  # jq reports bad programs and bad data alike
            status.value = type(error).__name__
            result.value = str(error)
            result.color = ft.Colors.ERROR
            comparison.value = ""
            page.update()
            return
        plural = "" if len(values) == 1 else "s"
        status.value = (
            f"{len(values)} output value{plural} — compiled in {compile_ms:.2f} ms, "
            f"ran in {run_ms:.1f} ms"
        )
        result.value = render(values)
        if twin is None:
            comparison.value = "no Python twin for this query"
        else:
            expected, twin_ms = run_twin(twin)
            agree = values == [expected]  # every preset emits exactly one value
            comparison.value = (
                f"{source_lines(twin)} lines of hand-written Python: "
                f"{twin_ms:.2f} ms, "
                f"{'same answer' if agree else 'DIFFERENT ANSWER'}"
            )
        page.update()

    if jq is None:
        library = f"jq absent — {IMPORT_ERROR}"
    else:
        builtins = jq.compile("builtins | length").input_value(None).first()
        library = f"jq: {builtins} builtins"
    library += (
        f" — document {len(DOC_TEXT):,} B, "
        f"{len(DOC['stations'])} stations, "
        f"{sum(len(s['readings']) for s in DOC['stations']):,} readings"
    )

    page.appbar = ft.AppBar(title=ft.Text("jq query console"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        library,
                        size=11,
                        color=ft.Colors.ERROR if jq is None else None,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} — {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,  # a plain Row overflows on a phone
                        controls=[
                            ft.Button(
                                preset[0],
                                on_click=lambda _, p=preset: choose(p),
                            )
                            for preset in PRESETS
                        ],
                    ),
                    query := ft.TextField(
                        label="jq program",
                        multiline=True,
                        min_lines=4,
                        max_lines=8,
                        text_size=12,
                        autocorrect=False,  # a keyboard "fixing" .[] breaks the query
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        keyboard_type=ft.KeyboardType.MULTILINE,
                    ),
                    ft.Row(
                        controls=[
                            ft.FilledButton("Run", on_click=lambda _: run_now()),
                            status := ft.Text(size=11, expand=True),
                        ]
                    ),
                    result := ft.Text(
                        size=11, selectable=True, font_family="monospace"
                    ),
                    ft.Divider(),
                    comparison := ft.Text(size=11),
                ],
            ),
        )
    )

    choose(PRESETS[0])


if __name__ == "__main__":
    ft.run(main)
