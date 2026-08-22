"""The ledger itself: engine, mapped classes, and the queries the screen shows."""

import datetime as dt
import decimal
import os
import random
import sqlite3  # the DBAPI the default sqlite dialect drives; imported only to print it
import time

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


def reseed(count):
    """Rewrite the ledger at `count` rows and roll it up, timing both halves."""
    started = time.perf_counter()
    seed(count)
    written = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    rows, totals = rollup()
    grouped = (time.perf_counter() - started) * 1000.0
    note = (
        f"{count:,} expenses written in {written:.0f} ms, grouped into "
        f"{len(rows)} categories in {grouped:.0f} ms"
    )
    return rows, totals, note


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
