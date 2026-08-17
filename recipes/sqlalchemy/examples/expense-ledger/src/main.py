"""An expense ledger the SQLAlchemy ORM keeps in a SQLite file in app storage."""

import datetime as dt
import decimal
import os
import random
import sqlite3  # the DBAPI the default sqlite dialect drives; imported only to print it
import threading
import time

import flet as ft
import sqlalchemy
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

# _has_cy is private, and the only place the reason survives: it imports all five extensions
# in one try/except, so a single missing .so demotes the whole library, and its
# _CYEXTENSION_MSG holds the ImportError text that says which one.
from sqlalchemy.util import _has_cy, concurrency, has_compiled_ext

STORAGE = os.getenv("FLET_APP_STORAGE_DATA", ".")
DB_PATH = os.path.join(STORAGE, "ledger.db")
CATEGORIES = ("Groceries", "Transport", "Rent", "Utilities", "Dining", "Health")
DEFAULT_ROWS = 5000

# URL.create builds the URL from an absolute path without the sqlite:/// spelling having
# to be counted out by hand — a fourth slash is what separates an absolute path from one
# resolved against the working directory. pool_size/max_overflow replace the defaults of
# 5 and 10, which would let a single-user app open fifteen sqlite3 connections.
engine = create_engine(
    URL.create("sqlite", database=DB_PATH), pool_size=1, max_overflow=0
)


@event.listens_for(engine, "connect")
def configure_connection(dbapi_connection, connection_record):
    """Apply the three PRAGMAs a phone wants to every connection the pool opens.

    They are per-connection state rather than engine configuration, so there is nowhere
    in `create_engine` to put them, and issuing them once on a checked-out connection
    would not reach the next one the pool hands out. WAL lets a read run while a write
    is open, busy_timeout is what a blocked writer waits before raising instead of the
    5 s sqlite3 defaults to, and SQLite leaves foreign keys unenforced unless asked.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    """Declarative base for the two mapped classes."""


class Category(Base):
    """A spending category, one row per name."""

    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    expenses: Mapped[list["Expense"]] = relationship(back_populates="category")


class Expense(Base):
    """One dated amount charged to a category."""

    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), index=True)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    spent_at: Mapped[dt.datetime] = mapped_column(DateTime)
    category: Mapped[Category] = relationship(back_populates="expenses")


Base.metadata.create_all(engine)

with engine.connect() as _probe:
    JOURNAL = _probe.exec_driver_sql("pragma journal_mode").scalar()

# func.avg is the one aggregate with no declared return type — its .type is NullType(),
# so no result processor runs and the driver's raw float comes back, where func.sum and
# func.max inherit Numeric(10, 2) and come back as Decimal. Mixing the two in a money
# total is how cents go missing, so name the type rather than letting it default.
ROLLUP = (
    select(
        Category.name,
        func.count(Expense.id),
        func.sum(Expense.amount),
        func.avg(Expense.amount, type_=Numeric(10, 2)),
    )
    .join(Category.expenses)
    .group_by(Category.name)
    .order_by(func.sum(Expense.amount).desc())
)
TOTALS = select(
    func.count(Expense.id),
    func.sum(Expense.amount),
    func.avg(Expense.amount, type_=Numeric(10, 2)),
)


def capabilities():
    """Describe the SQLAlchemy underneath, for the header.

    Everything here can differ from what a desktop run shows: the compiled extensions
    are per-slice and silently absent if any one of the five fails to load, SQLite is
    bundled on Android but supplied by the OS on iOS, and whether greenlet arrived is
    decided by the CPU of the machine that ran `flet build` rather than by this project.
    """
    cext = "on" if has_compiled_ext() else f"OFF ({_has_cy._CYEXTENSION_MSG})"
    greenlet = "present" if concurrency.have_greenlet else "absent"
    return (
        f"sqlalchemy {sqlalchemy.__version__} · C ext {cext} · "
        f"sqlite {sqlite3.sqlite_version} ({engine.dialect.driver}) · "
        f"{type(engine.pool).__name__}/{engine.pool.size()} · "
        f"journal={JOURNAL} · greenlet {greenlet}"
    )


def filesize(path):
    """Render one file's size, or `absent` when it is not there."""
    if not os.path.exists(path):
        return "absent"
    size = os.path.getsize(path)
    return f"{size / 1e6:.2f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"


def storage_line():
    """Report where the database lives and how its bytes are split across three files.

    Split rather than summed, because that is the part that surprises people: in WAL
    mode a fresh write sits in `ledger.db-wal` until SQLite checkpoints, so the `.db`
    on its own can stay tiny. The three files are one database — copy, export or back
    them up together.
    """
    beside = ", ".join(f"{s} {filesize(DB_PATH + s)}" for s in ("-wal", "-shm"))
    return f"{DB_PATH} — {filesize(DB_PATH)}, plus {beside}"


def seed(count):
    """Replace the whole ledger with `count` freshly generated expenses.

    The rows come out of a fixed seed rather than a bundled file, so every install
    holds identical data and two devices can be compared number for number. One
    executemany does the insert: handing `insert(Expense)` a list of dicts skips
    building `count` ORM objects that would only be thrown away.
    """
    generator = random.Random(7)
    start = dt.datetime(2026, 1, 1)
    rows = [
        {
            "id": i + 1,
            "category_id": generator.randrange(1, len(CATEGORIES) + 1),
            "amount": decimal.Decimal(generator.randrange(150, 20000)) / 100,
            "spent_at": start + dt.timedelta(minutes=7 * i),
        }
        for i in range(count)
    ]
    with Session(engine) as session:
        session.execute(delete(Expense))
        session.execute(delete(Category))
        session.execute(
            insert(Category),
            [{"id": i + 1, "name": name} for i, name in enumerate(CATEGORIES)],
        )
        session.execute(insert(Expense), rows)
        session.commit()


def rollup():
    """Run the join + GROUP BY and, separately, the ungrouped totals.

    Two queries rather than one on purpose: the per-category totals on screen have to
    add up to the row the second query returns, which makes the numbers checkable
    instead of merely plausible.
    """
    with Session(engine) as session:
        return session.execute(ROLLUP).all(), session.execute(TOTALS).one()


def largest():
    """Read the single biggest expense back as an object rather than as a row.

    Everything else on screen is an aggregate, which Core would do just as well. This is
    the part only the ORM gives you, and both halves are checkable against the file:
    SQLite has neither a decimal nor a date type, so `amount` is stored as `REAL` and
    `spent_at` as text, and they arrive here as `Decimal` and `datetime` because
    SQLAlchemy's result processors — among the five modules the compiled extensions
    replace — convert them. The category name comes off the `relationship`, which is one
    more `SELECT` issued while the session is open, not a column of this query.
    """
    with Session(engine) as session:
        top = session.scalars(
            select(Expense).order_by(Expense.amount.desc()).limit(1)
        ).one()
        return (
            f"largest: {top.amount:,.2f} on {top.category.name}, "
            f"{top.spent_at:%d %b %Y %H:%M} — amount {type(top.amount).__name__}, "
            f"spent_at {type(top.spent_at).__name__}"
        )


def compare():
    """Sum every amount twice — once through the ORM, once through Core — and time both.

    The Row class, the tuplegetter and the Numeric processor that the compiled extensions
    replace are all on this path, so it is the one thing in the app whose timing they
    move. Printing both totals next to both timings is the point: they have to match,
    because the extensions are a speed change and never a behaviour change.
    """
    started = time.perf_counter()
    with Session(engine) as session:
        objects = session.scalars(select(Expense)).all()
        orm_total = sum(expense.amount for expense in objects)
    orm_ms = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    with engine.connect() as connection:
        core_rows = connection.execute(select(Expense.id, Expense.amount)).all()
        core_total = sum(row.amount for row in core_rows)
    core_ms = (time.perf_counter() - started) * 1000.0

    return (
        f"ORM {len(objects):,} objects in {orm_ms:.0f} ms → {orm_total:,.2f} · "
        f"Core {len(core_rows):,} rows in {core_ms:.0f} ms → {core_total:,.2f} · "
        f"same total: {orm_total == core_total}"
    )


def cell(value):
    """Format one aggregate value: counts with separators, money at two decimals."""
    if isinstance(value, decimal.Decimal):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def line(*cells):
    """One row of the rollup table, weighted so four columns fit a phone width."""
    return ft.Row(
        controls=[
            ft.Text(text, size=11, expand=expand)
            for text, expand in zip(cells, (3, 2, 3, 2))
        ]
    )


def main(page: ft.Page):
    """A slider that reseeds the ledger, and the per-category rollup of what it wrote.

    Reseeding writes a file, so it runs on Flet's thread pool rather than the UI thread
    and the slider is disabled for the duration. The engine's default QueuePool is what
    makes that legal: for a file database SQLAlchemy passes `check_same_thread=False`
    and then checks each sqlite3 connection out to one thread at a time.
    """
    busy = threading.Lock()

    def render(rows, totals, note):
        """Lay the rollup out with the ungrouped totals underneath, then the three lines."""
        results.controls = [
            line("Category", "Expenses", "Total", "Average"),
            ft.Divider(height=1),
            *(line(*(cell(value) for value in row)) for row in rows),
            ft.Divider(height=1),
            line("All", *(cell(value) for value in totals)),
        ]
        storage.value = storage_line()
        detail.value = largest()
        footer.value = note

    def start(worker):
        """Disable the controls and hand `worker` to Flet's thread pool.

        Disabling them is not on its own enough: `run_thread` submits to a shared pool,
        so a tap that was already in flight still arrives, and with `pool_size=1` a
        second worker would sit on the connection pool for its 30 s timeout before
        raising. The non-blocking lock is what makes the extra tap a no-op.
        """
        if not busy.acquire(blocking=False):
            return

        def guard():
            """Run the worker and report whatever it raised.

            The wrapper is load-bearing: `page.run_thread` never retrieves the worker's
            future, so an exception in there is discarded with no crash, no log line and
            no trace — the screen simply stops changing. Clearing the table alongside the
            message matters as much, because numbers from the previous run left under a
            fresh error read as current.
            """
            try:
                worker()
            except Exception as error:
                results.controls = []
                detail.value = ""
                footer.value = str(error)
            finally:
                slider.disabled = False
                comparer.disabled = False
                spinner.visible = False
                busy.release()
                page.update()  # auto-update does not reach background threads

        slider.disabled = True
        comparer.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(guard)

    def reseed():
        """Rewrite the ledger at the slider's size, then roll it up."""
        count = int(slider.value)
        started = time.perf_counter()
        seed(count)
        written = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        rows, totals = rollup()
        render(
            rows,
            totals,
            f"{count:,} expenses written in {written:.0f} ms, "
            f"grouped into {len(rows)} categories in "
            f"{(time.perf_counter() - started) * 1000.0:.0f} ms",
        )

    def refresh():
        """Roll up whatever is already stored, seeding first if the ledger is empty."""
        rows, totals = rollup()
        if not rows:
            reseed()
            return
        render(rows, totals, f"{totals[0]:,} expenses already stored")

    def timings():
        """Put the ORM-versus-Core comparison in the footer."""
        footer.value = compare()

    def resize():
        """Update the caption only — on_change fires continuously while dragging."""
        caption.value = f"{int(slider.value):,} expenses"

    def rewrite():
        """Send the reseed off the UI thread, once, on the slider's release."""
        start(reseed)

    def measure():
        """Send the ORM-versus-Core comparison off the UI thread."""
        start(timings)

    page.appbar = ft.AppBar(title=ft.Text("sqlalchemy ledger"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(capabilities(), size=11),
                    storage := ft.Text(size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(
                                f"{DEFAULT_ROWS:,} expenses", expand=True
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    slider := ft.Slider(
                        min=1000,
                        max=20000,
                        divisions=19,
                        value=DEFAULT_ROWS,
                        label="{value}",
                        on_change=resize,
                        on_change_end=rewrite,
                    ),
                    comparer := ft.Button(
                        "Compare ORM vs Core",
                        icon=ft.Icons.SPEED,
                        on_click=measure,
                    ),
                    results := ft.Column(spacing=2),
                    detail := ft.Text(size=11),
                    footer := ft.Text(size=11),
                ],
            ),
        )
    )

    start(refresh)


if __name__ == "__main__":
    ft.run(main)
