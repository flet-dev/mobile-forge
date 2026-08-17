"""Validate a JSON order feed and refuse the records that do not fit the schema."""

import decimal
import json
import random
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import flet as ft
import pydantic
import pydantic_core
from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter, ValidationError
from pydantic_core import _pydantic_core

CURRENCIES = ("NGN", "KES", "GHS")
SKUS = ("SKU-1001", "SKU-1002", "SKU-2117", "SKU-3050", "SKU-4488")
FAULTS = ("placed_at", "currency", "qty", "unit_price", "sku", "lines")


class Line(BaseModel):
    """One order line: what was bought, how many, and at what unit price."""

    sku: str = Field(min_length=6)
    qty: int = Field(gt=0)
    unit_price: decimal.Decimal = Field(gt=0)


class Order(BaseModel):
    """One record of the feed, and the only definition of what "valid" means here."""

    id: str
    placed_at: AwareDatetime
    currency: Literal[CURRENCIES]
    lines: list[Line] = Field(min_length=1)


FEED = TypeAdapter(list[Order])
PROBE = TypeAdapter(Any)


def corrupt(record, fault):
    """Break one field of `record` in place, one named fault per call.

    Each fault trips a different part of the schema, so the rejection table ends
    up showing the whole spread: a datetime the parser cannot read, a currency
    outside the `Literal`, a constrained int and a constrained `Decimal`, a
    too-short string, and a required field that is simply absent.
    """
    if fault == "placed_at":
        record["placed_at"] = "yesterday"
    elif fault == "currency":
        record["currency"] = "USD"
    elif fault == "qty":
        record["lines"][0]["qty"] = 0
    elif fault == "unit_price":
        record["lines"][0]["unit_price"] = "-12.00"
    elif fault == "sku":
        record["lines"][0]["sku"] = "x"
    elif fault == "lines":
        del record["lines"]


def make_feed(count):
    """Emit `count` order records as JSON bytes, six of them deliberately broken.

    The feed stands in for something the app did not write — bytes off a network
    or out of a file — so nothing here is a model yet. The seed is fixed, so
    every install gets the same records, the same six rejections and the same
    totals, and two devices can be compared against each other directly. Prices
    are strings rather than JSON numbers, which is the habit to copy for money: a
    JSON number reaches `Decimal` through a double, which does survive two
    decimal places but silently rounds anything past about seventeen significant
    digits, while a string arrives verbatim.
    """
    rng = random.Random(20260817)
    start = datetime(2026, 8, 17, tzinfo=timezone.utc)
    records = [
        {
            "id": f"ORD-{index:05d}",
            "placed_at": (start + timedelta(minutes=7 * index)).isoformat(),
            "currency": rng.choice(CURRENCIES),
            "lines": [
                {
                    "sku": rng.choice(SKUS),
                    "qty": rng.randint(1, 9),
                    "unit_price": f"{rng.uniform(4.5, 250.0):.2f}",
                }
                for _ in range(rng.randint(1, 3))
            ],
        }
        for index in range(count)
    ]
    for offset, fault in enumerate(FAULTS):
        corrupt(records[(offset + 1) * count // (len(FAULTS) + 1)], fault)
    return json.dumps(records).encode()


def validate_feed(payload):
    """Validate the whole feed in one pass, then salvage the records that fit.

    `validate_json` takes the raw bytes straight to typed objects — pydantic's
    own JSON parser feeds the validators directly, with no dicts in between —
    and one bad record fails the entire list. What comes back with the failure is
    a path per error, so the leading index of each `loc` names the record to
    drop, and a second pass over everything else returns the orders worth
    showing. That second pass has to start from the parsed records rather than
    from the bytes, which is what recovering costs over rejecting the batch.
    """
    try:
        return FEED.validate_json(payload), [], []
    except ValidationError as error:
        problems = error.errors(include_url=False)
    rejected = {problem["loc"][0] for problem in problems if problem["loc"]}
    records = json.loads(payload)
    kept = [record for index, record in enumerate(records) if index not in rejected]
    return FEED.validate_python(kept), problems, sorted(rejected)


def rollup(orders):
    """Total each currency in `Decimal`: orders, lines and revenue, richest first."""
    totals = {}
    for order in orders:
        count, lines, revenue = totals.get(order.currency, (0, 0, decimal.Decimal(0)))
        totals[order.currency] = (
            count + 1,
            lines + len(order.lines),
            revenue + sum(line.qty * line.unit_price for line in order.lines),
        )
    return sorted(totals.items(), key=lambda entry: entry[1][2], reverse=True)


def parse_then_validate(payload):
    """The two-step alternative to `validate_json`: stdlib parse, then validate."""
    return FEED.validate_python(json.loads(payload))


def compare_paths(payload, reps=3):
    """Time `validate_json` against `json.loads` + `validate_python`, same bytes.

    Both produce the same list of orders; all that differs is which parser reads
    the JSON. The ratio depends on the payload and on the phone, which is the
    only reason to measure it here instead of quoting a number.
    """

    def fastest(work):
        """Best of `reps` runs of `work(payload)`, in milliseconds."""
        best = None
        for _ in range(reps):
            started = time.perf_counter()
            work(payload)
            elapsed = (time.perf_counter() - started) * 1000.0
            best = elapsed if best is None else min(best, elapsed)
        return best

    return fastest(FEED.validate_json), fastest(parse_then_validate)


def deepest_nesting():
    """Measure how deeply nested a JSON document `validate_json` will accept.

    pydantic's JSON parser carries its own recursion limit, far below the depth
    `json.loads` manages. One level past it the failure arrives as a validation
    error against the input — type `json_invalid`, message "recursion limit
    exceeded" — rather than as a stated limit, so it reads like malformed JSON.
    Binary-searching it costs a handful of tiny parses and gives the number this
    device actually enforces.
    """

    def accepted(depth):
        """Whether a `depth`-deep nest of empty arrays validates."""
        try:
            PROBE.validate_json("[" * depth + "]" * depth)
            return True
        except ValidationError:
            return False

    low, high = 1, 2
    while accepted(high) and high < 4096:
        low, high = high, high * 2
    while low + 1 < high:
        middle = (low + high) // 2
        if accepted(middle):
            low = middle
        else:
            high = middle
    return low


def build_line():
    """Name the versions, the Rust build profile, and how the extension loaded.

    `__file__` is the wheel's own tagged filename only on desktop. Flet moves
    native extensions out of site-packages on both mobile platforms — into the
    APK's jniLibs on Android, into a signed framework on iOS — and leaves a
    marker behind at the import path, so on a phone this reports the relocated
    name instead. Read it as which file the import system resolved, not as the
    wheel tag. libmpdec is the C accelerator behind the stdlib `decimal` module
    that every `Decimal` field and the revenue rollup run through; "pure-Python"
    there would mean this Python runtime shipped without it.

    Every attribute is read through `getattr`, because this line is built inside
    the `page.add(...)` call: an `AttributeError` here would abort `main` before
    a single control existed, leaving a blank screen and no way to say why.
    """
    accelerator = getattr(decimal, "__libmpdec_version__", None)
    origin = getattr(_pydantic_core, "__file__", None)
    return (
        f"pydantic {pydantic.VERSION} · pydantic-core {pydantic_core.__version__} · "
        f"{getattr(_pydantic_core, 'build_info', 'build_info absent')} · "
        f"{Path(origin).name if origin else 'no __file__'} · "
        f"libmpdec {accelerator or 'absent, decimal is pure Python'}"
    )


def table_row(values, weights):
    """One row of a table: a `Text` per value, laid out by relative width."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, weights)
        ]
    )


def main(page: ft.Page):
    """Show a feed size driving a validation run, and what each run made of it.

    Everything on screen is computed from the one `validate_json` call and the
    `ValidationError` it raises: the survivor count, the `Decimal` revenue per
    currency, and a rejection table built out of `errors(include_url=False)`.
    """

    def show_count():
        """Report the feed size the next run will validate, as the slider moves."""
        caption.value = f"{int(size.value):,} records per feed"

    def start():
        """Hand a run to a background thread and show that one is in flight.

        Driven by the slider's on_change_end, which fires once on release —
        on_change would start a fresh run for every pixel of the drag.
        """
        size.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Generate a feed, validate it, and fill the screen in from the result.

        Validation holds the GIL from start to finish, so this thread buys
        responsiveness only in the sense that the event handler returns
        immediately. The try/except is not decoration: `page.run_thread`
        discards whatever a worker raises, so without it a mistake in here would
        show up as a screen that quietly stopped updating.
        """
        try:
            payload = make_feed(int(size.value))

            started = time.perf_counter()
            orders, problems, rejected = validate_feed(payload)
            elapsed = (time.perf_counter() - started) * 1000.0

            summary.value = (
                f"{len(orders):,} valid, {len(rejected)} records rejected over "
                f"{len(problems)} errors — {len(payload) / 1000:.0f} KB validated "
                f"and salvaged in {elapsed:.0f} ms"
            )
            totals.controls = [
                table_row(("currency", "orders", "lines", "revenue"), (2, 2, 2, 3)),
                ft.Divider(height=1),
                *(
                    table_row(
                        (currency, f"{count:,}", f"{lines:,}", f"{revenue:,.2f}"),
                        (2, 2, 2, 3),
                    )
                    for currency, (count, lines, revenue) in rollup(orders)
                ),
            ]
            rejections.controls = [
                table_row(("where", "error", "message", "input"), (3, 3, 6, 3)),
                ft.Divider(height=1),
                *(
                    table_row(
                        (
                            ".".join(str(part) for part in problem["loc"]),
                            problem["type"],
                            problem["msg"],
                            textwrap.shorten(
                                repr(problem["input"]), 32, placeholder="…"
                            ),
                        ),
                        (3, 3, 6, 3),
                    )
                    for problem in problems
                ),
            ]

            clean = FEED.dump_json(orders)
            through_rust, through_stdlib = compare_paths(clean)
            footer.value = (
                f"survivors re-serialised to {len(clean) / 1000:.0f} KB, then read back: "
                f"validate_json {through_rust:.1f} ms against json.loads + "
                f"validate_python {through_stdlib:.1f} ms — deepest JSON nesting "
                f"accepted on this device: {deepest_nesting()}"
            )
        except Exception as error:
            footer.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("pydantic feed validator"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build_line(), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=200,
                        max=2000,
                        value=500,
                        divisions=9,
                        round=0,
                        label="{value}",
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    summary := ft.Text(),
                    totals := ft.Column(spacing=4),
                    rejections := ft.Column(spacing=4),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    show_count()
    start()


if __name__ == "__main__":
    ft.run(main)
